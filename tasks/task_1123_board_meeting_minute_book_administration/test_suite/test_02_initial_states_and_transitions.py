"""Initial states on creation and basic state-machine invalid transitions."""
from test_helpers import (
    ApiErrorId,
    add_director,
    adopt_bylaws,
    convene_meeting,
    create_consent_resolution,
    create_corporation,
    create_draft_bylaws,
    get_minutes_for_meeting,
    schedule_noticed_meeting,
    send_notices,
    set_clock,
    setup_adjourned_meeting_with_minutes,
    setup_corporation_with_adopted_bylaws,
    setup_in_session_meeting,
    setup_corporation_with_directors,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    make_chair_headers,
    make_director_headers,
    SECRETARY,
)
from test_helpers import api_client


class TestInitialStates:
    def test_bylaws_meeting_resolution_committee_initial_states(self, api):
        """PRD §3.1: "Each draft is stamped with a `version_no` one greater
        than the highest existing number for that corporation and begins life
        in `DRAFT`." PRD §3.4: "A successfully scheduled meeting begins in
        `SCHEDULED`." PRD §3.6: "Every resolution begins in `DRAFT`."
        PRD §3.3: "A committee is born in `CHARTER_DRAFT`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        corp = create_corporation(name="Corp S1")
        bylaws = create_draft_bylaws(corp["id"])
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        cm = get_success_data(
            api.create_committee(
                {
                    "corporation_id": corp["id"],
                    "name": "C",
                    "committee_type": "SPECIAL",
                    "charter_text": "c",
                    "quorum_fixed_count": 1,
                },
                SECRETARY,
            )
        )
        m = get_success_data(
            api.create_meeting(
                {
                    "corporation_id": corp["id"],
                    "meeting_type": "REGULAR",
                    "scheduled_start": "2026-06-20T10:00:00Z",
                    "duration_minutes": 60,
                    "location_or_medium": "Boardroom",
                    "chair_director_id": d1["id"],
                },
                SECRETARY,
            )
        )
        r = get_success_data(
            api.create_resolution(
                {
                    "corporation_id": corp["id"],
                    "meeting_id": m["id"],
                    "origin": "MEETING",
                    "resolution_type": "ORDINARY",
                    "title": "R",
                    "text": "t",
                },
                SECRETARY,
            )
        )

        by = get_success_data(api.get_bylaws(bylaws["id"], SECRETARY))
        mt = get_success_data(api.get_meeting(m["id"], SECRETARY))
        rs = get_success_data(api.get_resolution(r["id"], SECRETARY))
        cm_after = get_success_data(api.get_committee(cm["id"], SECRETARY))

        assert by["status"] == "DRAFT"
        assert mt["status"] == "SCHEDULED"
        assert rs["status"] == "DRAFT"
        assert cm_after["status"] == "CHARTER_DRAFT"

    def test_director_initial_state_active_and_pending_review(self, api):
        """PRD §3.2: "A newly appointed director begins in `ACTIVE` status with
        `independence_status` preset to `PENDING_REVIEW`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        corp = create_corporation(name="Corp S1b")
        d = add_director(corp["id"], "D1", "d1@x.com")
        assert d["status"] == "ACTIVE"
        assert d["independence_status"] == "PENDING_REVIEW"


class TestNoticeWaiver:
    def _setup_notice(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp S2")
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        return corp, d1, m

    def test_waive_already_waived_notice_rejected(self, api):
        """PRD §3.4: "A director may waive only their own notice, moving it
        `SENT` → `WAIVED`". PRD §2.11: "State — the target resource stands in a
        source state of the requested transition (`ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/waive_already_waived_notice_rejected
        """
        corp, d1, m = self._setup_notice(api)
        # find D1's notice
        resp = api.list_meeting_notices(SECRETARY, params={"meeting_id": m["id"], "director_id": d1["id"]})
        data, _meta = validate_paginated(resp)
        assert len(data) == 1
        n_id = data[0]["id"]
        # first waive succeeds
        api.waive_notice(n_id, make_director_headers(d1["id"]))
        # second waive fails
        resp2 = api.waive_notice(n_id, make_director_headers(d1["id"]))
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        final = get_success_data(api.get_meeting_notice(n_id, SECRETARY))
        assert final["status"] == "WAIVED"


class TestMinutesApprovalGating:
    def test_approve_minutes_from_draft_rejected(self, api):
        """PRD §3.9: "Approval requires the minutes to be `CIRCULATED_FOR_REVIEW`
        and the linked meeting `ADJOURNED`". PRD §2.11 tier 5:
        `ERR_INVALID_STATE_TRANSITION`.

        Design: Corner/state_machines/approve_minutes_from_draft_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp S3")
        d1 = directors[0]
        m, mn = setup_adjourned_meeting_with_minutes(
            corp["id"], d1["id"], [d1["id"]], convene_clock="2026-06-20T10:00:00Z"
        )
        resp = api.approve_minutes(mn["id"], make_chair_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_minutes(mn["id"], SECRETARY))
        assert after["status"] == "DRAFT"


class TestAdjournAutoCreatesMinutes:
    def test_adjourn_auto_creates_minutes_draft(self, api):
        """PRD §3.4: "The moment a meeting moves `IN_SESSION` → `ADJOURNED`, the
        server auto-creates its Minutes record in `DRAFT` with empty `content`;
        exactly one minutes record ever exists per meeting."

        Design: Corner/state_machines/adjourn_auto_creates_minutes_draft
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp S4")
        d1 = directors[0]
        m = setup_in_session_meeting(corp["id"], d1["id"], [d1["id"]])
        api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        resp = api.list_minutes(SECRETARY, params={"meeting_id": m["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, f"expected exactly 1 minutes row, got {meta['total_count']}"
        mn = data[0]
        assert mn["status"] == "DRAFT"
        assert mn["content"] == ""
        assert mn["corporation_id"] == corp["id"]

    def test_adjourned_meeting_minutes_uniqueness(self, api):
        """PRD §3.9: "Minutes are born at adjournment: one Minutes record per
        meeting, keyed by `meeting_id`."

        Design: Corner/state_machines/adjourn_auto_creates_minutes_draft
        """
        corp, _bylaws, directors = setup_corporation_with_directors(2, name="Corp S4b")
        d1 = directors[0]
        m = setup_in_session_meeting(corp["id"], d1["id"], [d1["id"], directors[1]["id"]])
        api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        # Adjourn is terminal — calling again is invalid; the minutes row remains 1.
        resp = api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        resp2 = api.list_minutes(SECRETARY, params={"meeting_id": m["id"]})
        _data, meta = validate_paginated(resp2)
        assert meta["total_count"] == 1


class TestCommitteeDissolve:
    def test_committee_dissolve_ends_memberships(self, api):
        """PRD §3.3: "Dissolution ... moves the committee to the terminal
        `DISSOLVED` state and ends every `ACTIVE` membership with `ended_reason`
        `COMMITTEE_DISSOLVED`."

        Design: Corner/state_machines/committee_dissolve_ends_memberships
        """
        corp = create_corporation(name="Corp S5")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        cm = get_success_data(
            api.create_committee(
                {
                    "corporation_id": corp["id"],
                    "name": "C",
                    "committee_type": "SPECIAL",
                    "charter_text": "c",
                    "quorum_fixed_count": 1,
                },
                SECRETARY,
            )
        )
        api.activate_committee(cm["id"], SECRETARY)
        mb = get_success_data(
            api.create_committee_membership(
                {
                    "committee_id": cm["id"],
                    "director_id": d1["id"],
                    "committee_role": "MEMBER",
                    "term_start": "2026-02-01T00:00:00Z",
                    "term_end": "2028-02-01T00:00:00Z",
                },
                SECRETARY,
            )
        )
        api.dissolve_committee(cm["id"], SECRETARY)
        cm_after = get_success_data(api.get_committee(cm["id"], SECRETARY))
        mb_after = get_success_data(api.get_committee_membership(mb["id"], SECRETARY))
        assert cm_after["status"] == "DISSOLVED"
        assert mb_after["status"] == "ENDED"
        assert mb_after["ended_reason"] == "COMMITTEE_DISSOLVED"
        assert cm_after["active_member_count"] == 0


class TestCirculateConsentGating:
    def test_circulate_consent_without_adopted_bylaws_rejected(self, api):
        """PRD §3.7: "circulation requires an adopted bylaws
        (`ERR_NO_ADOPTED_BYLAWS`)."

        Design: Corner/state_machines/circulate_consent_without_adopted_bylaws_rejected
        """
        corp = create_corporation(name="Corp S6")
        # Leave bylaws in DRAFT — never adopt.
        create_draft_bylaws(corp["id"])
        r = get_success_data(
            api.create_resolution(
                {
                    "corporation_id": corp["id"],
                    "origin": "WRITTEN_CONSENT",
                    "resolution_type": "ORDINARY",
                    "title": "R",
                    "text": "t",
                },
                SECRETARY,
            )
        )
        resp = api.circulate_consent(r["id"], SECRETARY)
        validate_error(resp, ApiErrorId.ERR_NO_ADOPTED_BYLAWS)
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["status"] == "DRAFT"
