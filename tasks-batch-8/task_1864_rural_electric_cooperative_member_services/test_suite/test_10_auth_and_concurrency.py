"""Authentication, RBAC denials, ownership scoping, and OCC stale-version rules
(PRD §2.1, §2.7, §2.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_allocation_payload,
    create_election_payload,
    create_retirement_payload,
    get_success_data,
    make_member_headers,
    set_clock,
    setup_cooperative,
    setup_finalized_invoice,
    setup_member,
    setup_published_schedule,
    validate_error,
    validate_success,
)

REP = TEST_USERS["rep"]
DIRECTOR = TEST_USERS["board_director"]
SECRETARY = TEST_USERS["board_secretary"]
CLERK = TEST_USERS["billing_clerk"]
DISPATCHER = TEST_USERS["dispatcher"]


class TestAuthentication:
    def test_unauthenticated_missing_role_header(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name a declared role is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/unauthenticated_missing_role_header
        """
        coop = setup_cooperative()
        resp = api.get_cooperative(coop["id"], headers={"X-User-ID": "someone"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRbacDenials:
    def test_member_cannot_create_rate_schedule(self, api):
        """PRD §2.1: "an actor whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." Rate design
        belongs to the RateAnalyst (§3.4).

        Design: Corner/rbac/member_cannot_create_rate_schedule
        """
        setup_cooperative()
        member, _loc = setup_member(status="ACTIVE")
        resp = api.create_rate_schedule(
            {"code": "HACK", "rate_class": "RESIDENTIAL",
             "effective_from": "2026-01-01T00:00:00Z", "customer_charge_cents": 1,
             "tiers": [{"up_to_kwh": None, "cents_per_kwh": 1}],
             "demand_charge_cents_per_kw": 0, "irrigation_offseason_discount_pct": 0,
             "load_management_credit_cents": 0},
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_billing_clerk_cannot_approve_allocation(self, api):
        """PRD §2.1: "an actor whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." Board approval of
        allocations is a BoardDirector step (§3.7).

        Design: Corner/rbac/billing_clerk_cannot_approve_allocation
        """
        coop = setup_cooperative()
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 10000}, REP), 200)
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            REP), 201)
        resp = api.approve_allocation(alloc["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_member_cannot_read_other_member_record(self, api):
        """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of
        the acting `Member` ... A member acting on a resource they do not own is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/member_cannot_read_other_member_record
        """
        setup_cooperative()
        m1 = get_success_data(api.create_member(
            {"legal_name": "M1", "member_type": "RESIDENTIAL", "district_id": 1}, REP), 201)
        m2 = get_success_data(api.create_member(
            {"legal_name": "M2", "member_type": "RESIDENTIAL", "district_id": 2}, REP), 201)
        resp = api.get_member(m2["id"], make_member_headers(m1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_dispatcher_cannot_restore_outage(self, api):
        """PRD §2.1: "an actor whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." Restoration is a
        field-operations act (§3.6).

        Design: Corner/rbac/dispatcher_cannot_restore_outage
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        outage = get_success_data(api.create_outage_report(
            {"service_location_id": location["id"], "cause": "VEGETATION"}, DISPATCHER), 201)
        outage = get_success_data(api.acknowledge_outage(outage["id"], DISPATCHER), 200)
        outage = get_success_data(api.dispatch_outage(outage["id"], DISPATCHER), 200)
        assert outage["status"] == "CREW_DISPATCHED"
        resp = api.restore_outage(outage["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOwnershipPriority:
    def test_non_owner_consent_on_recorded_row_is_forbidden(self, api):
        """PRD §2.8: "Fourth, entity-backed ownership: on member-scoped
        endpoints, a `Member` actor may act only on their own resources, else
        `ERR_FORBIDDEN`. Fifth, state validity: the target resource must be in a
        legitimate from-state for the requested transition, else
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_state_on_row_consent
        """
        from test_helpers import create_row_agreement_payload
        setup_cooperative()
        m1, loc1 = setup_member(
            status="ACTIVE", member_overrides={"legal_name": "M1", "district_id": 1})
        m2, _loc2 = setup_member(
            status="ACTIVE", member_overrides={"legal_name": "M2", "district_id": 2})
        row = get_success_data(api.create_row_agreement(
            create_row_agreement_payload(service_location_id=loc1["id"]),
            TEST_USERS["field_ops"]), 201)
        row = get_success_data(api.consent_row(row["id"], make_member_headers(m1["id"])), 200)
        row = get_success_data(api.record_row(row["id"], TEST_USERS["field_ops"]), 200)
        assert row["status"] == "RECORDED"
        # Non-owner consent on an already-RECORDED agreement: ownership (rule
        # four) is evaluated before state (rule five).
        resp = api.consent_row(row["id"], make_member_headers(m2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_non_owner_consent_on_requested_row_is_forbidden(self, api):
        """PRD §2.8: "Fourth, entity-backed ownership: on member-scoped
        endpoints, a `Member` actor may act only on their own resources, else
        `ERR_FORBIDDEN`." and §3.3: "Consent — from `REQUESTED →
        `MEMBER_CONSENTED` — may be given only by the `Member` who owns the
        location (anyone else is refused with `ERR_FORBIDDEN`)".

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_state_on_row_consent
        """
        from test_helpers import create_row_agreement_payload
        setup_cooperative()
        m1, loc1 = setup_member(
            status="ACTIVE", member_overrides={"legal_name": "M1", "district_id": 1})
        m2, _loc2 = setup_member(
            status="ACTIVE", member_overrides={"legal_name": "M2", "district_id": 2})
        row = get_success_data(api.create_row_agreement(
            create_row_agreement_payload(service_location_id=loc1["id"]),
            TEST_USERS["field_ops"]), 201)
        assert row["status"] == "REQUESTED"
        # Non-owner on a REQUESTED agreement: ownership fails even though the
        # from-state would be valid for the owner.
        resp = api.consent_row(row["id"], make_member_headers(m2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOptimisticConcurrency:
    def _posted_setup_with_margin(self, api):
        """One ACTIVE member with 100 kWh billed in FY2025 and a pool of 10000;
        returns (coop, member)."""
        coop = setup_cooperative()
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 10000}, REP), 200)
        setup_published_schedule(rate_class="RESIDENTIAL")
        member, location = setup_member(status="ACTIVE")
        setup_finalized_invoice(
            location["id"], "2025-12-01T00:00:00Z", "2025-12-31T00:00:00Z", 0, 100)
        return coop, member

    def test_occ_allocation_post_stale_version(self, api):
        """PRD §2.7: "Each takes a non-optional request field
        `expected_cooperative_version` carrying the cooperative's `version` as
        the client last observed it. If that value does not match the
        cooperative's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)." The protected operations include
        "posting an approved capital-credit allocation".

        Design: Corner/cross_cutting_layers/occ_allocation_post_stale_version
        """
        coop, member = self._posted_setup_with_margin(api)
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            REP), 201)
        alloc = get_success_data(api.approve_allocation(alloc["id"], DIRECTOR), 200)
        stale = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        # An intervening pool mutation advances the cooperative's version.
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2026, "margin_cents": 5}, REP), 200)
        resp = api.post_allocation(
            alloc["id"], {"expected_cooperative_version": stale["version"]}, REP)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_retirement_execute_stale_version_then_fresh(self, api):
        """PRD §2.7: "The protected operations are: posting an approved
        capital-credit allocation (`POST
        /coop/capital-credit-allocations/{id}/post`), executing a board-approved
        retirement run (`POST /coop/capital-credit-retirements/{id}/execute`),
        and opening voting on a board election (`POST
        /coop/board-elections/{id}/open-voting`)."

        Design: Corner/cross_cutting_layers/occ_retirement_execute_stale_version
        """
        coop, member = self._posted_setup_with_margin(api)
        # Post the allocation so the member has a balance (pool already 10000).
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            REP), 201)
        alloc = get_success_data(api.approve_allocation(alloc["id"], DIRECTOR), 200)
        coop_now = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        alloc = get_success_data(api.post_allocation(
            alloc["id"], {"expected_cooperative_version": coop_now["version"]}, REP), 200)

        ret = get_success_data(api.create_retirement(
            create_retirement_payload(
                cooperative_id=coop["id"], method="PRO_RATA_PERCENTAGE",
                total_retire_cents=5000, pro_rata_pct=0.5),
            REP), 201)
        fresh = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        ret = get_success_data(api.board_approve_retirement(ret["id"], DIRECTOR), 200)
        # Deliberately stale version rejected...
        resp = api.execute_retirement(
            ret["id"], {"expected_cooperative_version": fresh["version"] - 1}, REP)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        # ...and the current version succeeds.
        executed = validate_success(api.execute_retirement(
            ret["id"], {"expected_cooperative_version": fresh["version"]}, REP), 200)
        assert executed["status"] == "EXECUTING"

    def test_occ_open_voting_stale_version(self, api):
        """PRD §3.9: "Opening the vote is the third OCC-guarded operation of
        §2.7: the request must carry `expected_cooperative_version` equal to the
        cooperative's current `version`, else `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_open_voting_stale_version
        """
        coop = setup_cooperative()
        set_clock("2026-08-01T00:00:00Z")
        election = get_success_data(api.create_election(
            create_election_payload(cooperative_id=coop["id"]), SECRETARY), 201)
        get_success_data(api.open_nominations(election["id"], SECRETARY), 200)
        stale = get_success_data(api.get_cooperative(coop["id"], SECRETARY), 200)
        # Closing nominations mutates the cooperative (active_election_id stays
        # but the version advances per §2.4's mutation rule) — a version one
        # behind the current is therefore stale.
        get_success_data(api.close_nominations(
            election["id"], {"candidate_names": ["Cand A"]}, SECRETARY), 200)
        resp = api.open_voting(
            election["id"], {"expected_cooperative_version": stale["version"] - 1},
            SECRETARY)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
