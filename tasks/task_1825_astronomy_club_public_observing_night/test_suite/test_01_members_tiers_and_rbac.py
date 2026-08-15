"""Member registration, system-managed fields, pagination, and RBAC denials."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_member,
    create_event,
    create_member,
    create_member_payload,
    create_operator_assignment_payload,
    create_telescope,
    create_tier,
    get_success_data,
    make_member_headers,
    open_dark_sky_report,
    record_reading,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["club_officer_headers"]
COORDINATOR = TEST_USERS["event_coordinator_headers"]
CHAIR = TEST_USERS["equipment_chair_headers"]


class TestMemberCreation:
    def test_create_member_applies_system_fields_and_defaults(self, api):
        """PRD: "The server stamps `joined_at` at registration, initializes
        `status` to `ACTIVE`, and initializes `dues_paid_through` to exactly
        `joined_at` — that is, joined plus zero days — so a brand-new member's
        first invoice is due immediately even though the account is technically
        in good standing."
        PRD: "`effective_access_level` equals the tier's
        `observatory_access_level` while the member is `ACTIVE` and is 0 in
        every other status, and `no_show_strikes` counts the member's no-show
        marks within a rolling 365-day window"
        PRD: "`version` (integer): starts at 1 and increments by exactly 1 on
        every mutation"

        Design: Corner/entities/create_member_applies_system_fields_and_defaults
        """
        tier = create_tier(code="STUDENT", annual_dues_cents=60000,
                           observatory_access_level=1, loan_privilege=False,
                           max_concurrent_loans=1)
        resp = api.create_member(
            create_member_payload(tier["id"], full_name="New Nick"), OFFICER)
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["status"] == "ACTIVE", "A new member is born ACTIVE"
        assert member["effective_access_level"] == 1, (
            "ACTIVE member's effective_access_level mirrors the tier level")
        assert member["no_show_strikes"] == 0, "A new member has no strikes"
        assert member["version"] == 1, "A new member is born with version 1"
        assert member["dues_paid_through"] == member["joined_at"], (
            "dues_paid_through initializes to joined_at + 0 days")

    def test_get_member_not_found(self, api):
        """PRD: "The first path identifier that does not resolve to an
        existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404)
        before any later identifier or business rule is consulted."

        Design: Corner/entities/get_member_not_found
        """
        resp = api.get_member(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestMemberListing:
    def test_member_list_pagination_envelope(self, api):
        """PRD: "The `limit` parameter caps the number of items returned; it
        defaults to 10 when omitted, accepts a minimum of 1, and a maximum of
        100. The `offset` parameter skips a number of items from the front of
        the result set and defaults to 0."
        PRD: "Every paginated list response includes `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` object of the
        envelope, so clients can page deterministically through the
        collection."

        Design: Corner/entities/member_list_pagination_envelope
        """
        tier = create_tier()
        for name in ("P A", "P B", "P C"):
            create_member(tier["id"], full_name=name)

        data, meta = validate_paginated(
            api.list_members(OFFICER, params={"limit": 2, "offset": 0}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(
            api.list_members(OFFICER, params={"limit": 2, "offset": 2}))
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        _data3, meta3 = validate_paginated(api.list_members(OFFICER))
        assert meta3["limit"] == 10, "Default limit is 10 when omitted"


class TestRbacDenials:
    def test_member_cannot_create_telescope(self, api):
        """PRD: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST | `/club/telescopes` | Register a telescope (initial
        status `AVAILABLE`) | EquipmentChair"

        Design: Corner/roles/member_cannot_create_telescope
        """
        tier = create_tier()
        member = create_member(tier["id"], full_name="RBAC Rita")
        resp = api.create_telescope(
            {"name": "Forbidden Scope", "equipment_class": "SCT"},
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

    def test_event_coordinator_cannot_finalize_report(self, api):
        """PRD: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST | `/club/dark-sky-reports/{reportId}/finalize` |
        Finalize a report, freezing median and grade | ClubOfficer"

        Design: Corner/roles/event_coordinator_cannot_finalize_report
        """
        tier = create_tier()
        member = create_member(tier["id"], full_name="Rep Reader")
        event = create_event(title="RR E")
        for v in (21.10, 21.20, 21.30):
            record_reading(member, event["id"], v)
        report = open_dark_sky_report("2026-08-01T00:00:00Z",
                                      "2026-09-01T00:00:00Z")

        resp = api.finalize_dark_sky_report(report["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

        done = validate_success(
            api.finalize_dark_sky_report(report["id"], OFFICER))
        assert done["status"] == "FINALIZED"

    def test_member_accept_only_own_assignment(self, api):
        """PRD: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of
        the acting `Member` entity; any ownership check on a resource that
        references a `Member` — a loan reservation's `member_id`, an
        assignment's `member_id`, a booking's `contact_member_id`, a
        payment's `member_id`, a reading's `taken_by_member_id` — compares
        that foreign-key field to `X-User-ID`."
        PRD: "Only the invited `Member` may respond."

        Design: Corner/roles/member_accept_only_own_assignment
        """
        tier = create_tier()
        member_a = create_member(tier["id"], full_name="A Owner")
        member_b = create_member(tier["id"], full_name="B Sneak")
        scope = create_telescope(name="Own Scope", equipment_class="DOBSONIAN")
        event = create_event(title="Own E", event_kind="MEMBER_NIGHT",
                             moon_illumination_pct=50)
        payload = create_operator_assignment_payload(
            event["id"], member_a["id"], scope["id"])
        assignment = get_success_data(
            api.create_operator_assignment(payload, COORDINATOR))

        resp = api.accept_assignment(
            assignment["id"], make_member_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

        fetched = validate_success(
            api.get_operator_assignment(assignment["id"], COORDINATOR))
        assert fetched["status"] == "INVITED", (
            "Rejected acceptance leaves the assignment INVITED")

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD: "A request that omits either header, or that names a role
        outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/roles/missing_auth_headers_unauthenticated
        """
        resp = api.list_members({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401
