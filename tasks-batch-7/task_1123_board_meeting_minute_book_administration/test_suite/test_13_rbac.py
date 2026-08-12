"""RBAC denials: role admission and identity scoping."""
from test_helpers import (
    ApiErrorId,
    add_director,
    create_corporation,
    create_draft_bylaws,
    get_success_data,
    schedule_noticed_meeting,
    set_clock,
    setup_corporation_with_directors,
    setup_corporation_with_adopted_bylaws,
    add_document,
    create_package,
    validate_error,
    validate_paginated,
    validate_success,
    make_chair_headers,
    make_director_headers,
    SECRETARY,
    AUDITOR,
)
from test_helpers import api_client


class TestDirectorCannotAdoptBylaws:
    def test_director_cannot_adopt_bylaws(self, api):
        """PRD §4: "POST /bylaws/{id}/adopt | Adopt a DRAFT bylaws, superseding
        the currently ADOPTED one | CorporateSecretary". PRD §2.1: "a caller
        whose role is not admitted, or who fails an ownership check attached
        to the endpoint, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/director_cannot_adopt_bylaws
        """
        corp = create_corporation(name="Corp RBAC1")
        bylaws = create_draft_bylaws(corp["id"])
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        resp = api.adopt_bylaws(
            bylaws["id"],
            {"expected_corporation_version": corp["version"]},
            make_director_headers(d1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = get_success_data(api.get_bylaws(bylaws["id"], SECRETARY))
        assert after["status"] == "DRAFT"


class TestAuditorCannotCreateMeeting:
    def test_auditor_cannot_create_meeting(self, api):
        """PRD §2.1: "Each endpoint admits a specific subset of these roles
        (enumerated in §4); a caller whose role is not admitted, or who fails
        an ownership check attached to the endpoint, is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §2.1: "An `ExternalAuditor` is
        an outside audit requester with read access plus the audit request
        lifecycle." (Meeting creation is admitted only for CorporateSecretary
        per §4.)

        Design: Corner/rbac/auditor_cannot_create_meeting
        """
        corp = create_corporation(name="Corp RBAC2")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        resp = api.create_meeting(
            {
                "corporation_id": corp["id"],
                "meeting_type": "REGULAR",
                "scheduled_start": "2026-06-20T10:00:00Z",
                "duration_minutes": 60,
                "location_or_medium": "Boardroom",
                "chair_director_id": d1["id"],
            },
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        list_resp = api.list_meetings(SECRETARY, params={"corporation_id": corp["id"]})
        _rows, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 0


class TestDirectorCannotWaiveOthersNotice:
    def test_director_cannot_waive_others_notice(self, api):
        """PRD §3.4: "a `Director` caller whose `X-User-ID` names any other
        director's notice is refused with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/director_cannot_waive_others_notice
        """
        corp, _bylaws, directors = setup_corporation_with_directors(2, name="Corp RBAC3")
        d1, d2 = directors
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        # Get D1's notice
        resp = api.list_meeting_notices(
            SECRETARY, params={"meeting_id": m["id"], "director_id": d1["id"]}
        )
        data, _meta = validate_paginated(resp)
        assert len(data) == 1
        n_id = data[0]["id"]
        # D2 tries to waive D1's notice.
        resp2 = api.waive_notice(n_id, make_director_headers(d2["id"]))
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = get_success_data(api.get_meeting_notice(n_id, SECRETARY))
        assert after["status"] == "SENT"


class TestNonChairDirectorCannotConvene:
    def test_non_chair_director_cannot_convene(self, api):
        """PRD §3.4: "Convening belongs to the chair alone: the caller's
        `X-User-ID` must equal the meeting's `chair_director_id`
        (`ERR_FORBIDDEN_ROLE`)."

        Design: Corner/rbac/non_chair_director_cannot_convene
        """
        corp, _bylaws, directors = setup_corporation_with_directors(2, name="Corp RBAC4")
        d1, d2 = directors
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        set_clock("2026-06-20T10:00:00Z")
        resp = api.convene_meeting(m["id"], make_chair_headers(d2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["status"] == "NOTICED"


class TestRestrictedDocumentAccessDeniedForNonIndependent:
    def _setup_distributed_restricted_doc(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(2, name="Corp RBAC5")
        d1, d2 = directors
        # Mark D1 INDEPENDENT, D2 NON_INDEPENDENT.
        api.review_independence(d1["id"], {"independence_status": "INDEPENDENT"}, SECRETARY)
        api.review_independence(d2["id"], {"independence_status": "NON_INDEPENDENT"}, SECRETARY)
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        p = create_package(m["id"])
        doc = add_document(p["id"], "CEO succession", "s3://restricted", "RESTRICTED")
        api.seal_board_package(p["id"], SECRETARY)
        # clock before scheduled_start; lead window = 5 days before 2026-06-20T10:00 -> distribute by 2026-06-15T10:00.
        # Current clock is 2026-05-01 — well within window.
        api.distribute_board_package(p["id"], SECRETARY)
        return corp, d1, d2, p, doc

    def test_non_independent_director_denied_restricted_read(self, api):
        """PRD §3.5: "a `RESTRICTED` document is visible solely to `ACTIVE`
        directors whose `independence_status` is `INDEPENDENT`. ... when such
        a caller fetches a single document above their clearance, the read is
        refused outright with `ERR_PACKAGE_ACCESS_DENIED` (HTTP 403)."

        Design: Corner/rbac/restricted_document_access_denied_for_non_independent
        """
        _corp, _d1, d2, _p, doc = self._setup_distributed_restricted_doc(api)
        resp = api.get_package_document(doc["id"], make_director_headers(d2["id"]))
        validate_error(resp, ApiErrorId.ERR_PACKAGE_ACCESS_DENIED)
        assert resp.status_code == 403

    def test_independent_director_reads_restricted_doc(self, api):
        """PRD §3.5: "a `RESTRICTED` document is visible solely to `ACTIVE`
        directors whose `independence_status` is `INDEPENDENT`."

        Design: Corner/rbac/restricted_document_access_denied_for_non_independent
        """
        _corp, d1, _d2, _p, doc = self._setup_distributed_restricted_doc(api)
        resp = api.get_package_document(doc["id"], make_director_headers(d1["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["id"] == doc["id"]

    def test_non_independent_director_list_filters_restricted(self, api):
        """PRD §3.5: "When a `Director` or `BoardChair` caller lists documents,
        the result is silently filtered to the tiers that caller may read."

        Design: Corner/rbac/restricted_document_access_denied_for_non_independent
        """
        _corp, _d1, d2, p, _doc = self._setup_distributed_restricted_doc(api)
        resp = api.list_package_documents(
            make_director_headers(d2["id"]), params={"package_id": p["id"]}
        )
        _rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, (
            f"expected list to silently filter RESTRICTED, got total_count {meta['total_count']}"
        )
