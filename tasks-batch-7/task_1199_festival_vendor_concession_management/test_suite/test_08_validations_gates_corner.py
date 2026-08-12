"""Corner: auth headers, role gates, ownership, festival posture gates, referential integrity."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    advance_festival,
    api_client,
    create_application_payload,
    create_booth,
    create_festival,
    create_settlement,
    create_vendor,
    create_zone,
    make_vendor_headers,
    setup_accepted_application,
    setup_active_assignment,
    setup_confirmed_assignment,
    setup_open_festival,
    setup_reserved_assignment,
    setup_submitted_application,
    start_review,
    submit_application,
    validate_error,
    validate_success,
    get_application,
)

DIRECTOR = TEST_USERS["director_headers"]
VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]
FIN1 = TEST_USERS["finance_headers"]


class TestAuthHeaders:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry `X-User-ID` identifying the acting
        party and `X-User-Role` naming their operational capacity. A request in
        which either header is missing or empty is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        festival = create_festival(name="Auth Fest")
        resp = api.get_festival(festival["id"], headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleGate:
    def test_forbidden_role_for_zone_create(self, api):
        """PRD §2.1: "Every endpoint admits a fixed set of roles (enumerated in
        §4); a caller whose role is not admitted is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /zones — "Create a zone with utility budgets | OperationsLead".

        Design: Corner/validations/forbidden_role_for_zone_create
        """
        festival = create_festival(name="Role Fest")
        resp = api.create_zone(
            {"festival_id": festival["id"], "name": "North",
             "power_capacity_amps": 100, "water_hookup_total": 1},
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestOwnership:
    def test_vendor_cannot_withdraw_others_application(self, api):
        """PRD §2.1: "When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of
        the acting `Vendor`; ownership checks on any resource that references a
        vendor compare the resource's vendor foreign key — or the vendor reached
        by following an assignment back to its application — to `X-User-ID`, and
        a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/vendor_cannot_withdraw_others_application
        """
        scen = setup_open_festival(name="Own Fest")
        va = create_vendor(legal_name="Owner A", contact_email="a@own.com")
        vb = create_vendor(legal_name="Owner B", contact_email="b@own.com")
        app = submit_application(va, scen["festival"]["id"])
        resp = api.withdraw_application(app["id"], make_vendor_headers(vb["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_application(app["id"])["status"] == "SUBMITTED"


class TestFestivalPostureGates:
    def test_submit_blocked_before_applications_open(self, api):
        """PRD §3.2: "Submitting while the festival is not in `APPLICATIONS_OPEN`
        is rejected with `ERR_FESTIVAL_NOT_ACCEPTING_APPLICATIONS`".

        Design: Corner/validations/submit_blocked_before_applications_open
        """
        festival = create_festival(name="Posture Fest")
        create_zone(festival["id"])
        vendor = create_vendor(legal_name="Early Sub LLC")
        payload = create_application_payload(vendor["id"], festival["id"])
        resp = api.create_application(payload, make_vendor_headers(vendor["id"]))
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_ACCEPTING_APPLICATIONS)

    def test_assignment_blocked_before_curation(self, api):
        """PRD §3.3: "Creating an assignment while the festival is not `CURATED`
        is rejected with `ERR_FESTIVAL_NOT_ACCEPTING_ASSIGNMENTS`".

        Design: Corner/validations/assignment_blocked_before_curation
        """
        scen = setup_accepted_application(name="EarlyAssign Fest")
        booth = create_booth(scen["zone"]["id"])
        resp = api.create_assignment(
            {"application_id": scen["app"]["id"], "booth_id": booth["id"],
             "power_draw_amps": 20, "requires_water": False},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_ACCEPTING_ASSIGNMENTS)

    def test_pos_report_blocked_before_live(self, api):
        """PRD §3.6: "Reporting while the festival is not `LIVE` is rejected with
        `ERR_FESTIVAL_NOT_LIVE`".

        Design: Corner/validations/pos_report_blocked_before_live
        """
        scen = setup_confirmed_assignment(name="NotLive Fest")  # festival CURATED
        resp = api.create_transaction(
            {"assignment_id": scen["assignment"]["id"], "amount_cents": 1000,
             "occurred_at": "2026-07-10T14:00:00Z", "idempotency_key": "nl1"},
            make_vendor_headers(scen["vendor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_LIVE)

    def test_settlement_create_blocked_before_live(self, api):
        """PRD §3.6: "Creation requires the festival to be `LIVE` or `SETTLEMENT`,
        otherwise `ERR_FESTIVAL_NOT_IN_SETTLEMENT`."

        Design: Corner/validations/settlement_create_blocked_before_live
        """
        scen = setup_reserved_assignment(name="EarlySettle Fest")  # festival CURATED
        resp = api.create_settlement({"assignment_id": scen["assignment"]["id"]}, FIN1)
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_IN_SETTLEMENT)


class TestReferentialIntegrity:
    def test_cross_festival_booth_assignment_rejected(self, api):
        """PRD §2.6: "Linked resources must belong to the same festival: a booth
        assignment requires that the application's festival equals the booth's
        zone's festival, and a load-in reservation requires that the slot and the
        assignment share a festival. A cross-festival link is rejected with
        `ERR_CROSS_FESTIVAL_REFERENCE` (HTTP 409)."

        Design: Corner/validations/cross_festival_booth_assignment_rejected
        """
        scen = setup_accepted_application(name="Cross F1")
        advance_festival(scen["festival"]["id"], "CURATED")
        # A second festival, also CURATED, so only the referential check can fire.
        f2 = create_festival(name="Cross F2", event_start="2026-08-01T12:00:00Z",
                             event_end="2026-08-02T23:00:00Z")
        z2 = create_zone(f2["id"], name="South")
        advance_festival(f2["id"], "APPLICATIONS_OPEN")
        advance_festival(f2["id"], "CURATED")
        booth2 = create_booth(z2["id"], label="S-01")
        resp = api.create_assignment(
            {"application_id": scen["app"]["id"], "booth_id": booth2["id"],
             "power_draw_amps": 20, "requires_water": False},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_FESTIVAL_REFERENCE)

    def test_supersede_non_changes_requested_rejected(self, api):
        """PRD §3.2: "The supersede is valid only when the source is in
        `CHANGES_REQUESTED` and belongs to the same vendor and the same festival,
        otherwise `ERR_SUPERSEDE_SOURCE_INVALID`".

        Design: Corner/validations/supersede_non_changes_requested_rejected
        """
        scen = setup_submitted_application(name="Supersede Fest")
        start_review(scen["app"]["id"])  # UNDER_REVIEW — not CHANGES_REQUESTED
        payload = create_application_payload(
            scen["vendor"]["id"], scen["festival"]["id"],
            proposed_flat_fee_cents=51000,
            supersedes_application_id=scen["app"]["id"],
        )
        resp = api.create_application(payload, make_vendor_headers(scen["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SUPERSEDE_SOURCE_INVALID)

    def test_settlement_double_create_rejected(self, api):
        """PRD §3.6: "Each assignment has exactly one settlement, created by a
        `FinanceLead` naming the `assignment_id`; a second attempt is rejected
        with `ERR_SETTLEMENT_EXISTS`."

        Design: Corner/validations/settlement_double_create_rejected
        """
        scen = setup_active_assignment(name="Double Fest")
        first = create_settlement(scen["assignment"]["id"])
        assert first["status"] == "OPEN"
        resp = api.create_settlement({"assignment_id": scen["assignment"]["id"]}, FIN1)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXISTS)
