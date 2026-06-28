"""Difficulty-queue tests for validation priority pairs, numeric boundary
precision, cross-entity state dependencies, and temporal overlap rules."""
import pytest
from test_helpers import (
    ApiErrorId, TEST_USERS, make_client_headers, validate_error, get_success_data,
    create_offer_payload, accept_offer_payload, create_settlement_payload,
    set_clock, create_client, create_program, create_debt,
    create_offer, accept_offer,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


def _fund(api, program_id, client_id, months, amount=600, day=10, start=1):
    for i in range(months):
        m = start + i
        api.create_deposit(
            {"program_id": program_id, "scheduled_for": f"2026-{m:02d}-{day:02d}T00:00:00Z",
             "amount": amount}, make_client_headers(client_id))


# =========================================================================
# Difficulty/priority_pair_validation_conflict
# =========================================================================
class TestValidationPriorityPairs:

    def test_invalid_state_beats_projected_reserve_shortfall(self, api):
        """PRD §3.6: "After the universal authentication, authorization, existence, and request-validity checks, the system verifies that the offer is `PENDING` (else `ERR_INVALID_STATE`, HTTP 409)."
        PRD §3.6: "The system then applies the forward-looking reserve check (below), rejecting a shortfall with `ERR_PROJECTED_RESERVE_SHORTFALL` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_projected_reserve_shortfall
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Con Flict", email="cf@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="CF-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        get_success_data(api.reject_offer(offer["id"], AGENT))
        # account balance is 0 (no deposits) so the reserve check would also fail;
        # the PENDING-state check fires first.
        res = api.accept_offer(offer["id"], accept_offer_payload(v1), AGENT)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_offer_acceptance_returns_state_not_fiscal(self, api):
        """PRD §3.6: "the system verifies that the offer is `PENDING` (else `ERR_INVALID_STATE`, HTTP 409)."
        PRD §3.6: "The preconditions on acceptance are evaluated in the following priority order, so that the earliest-failing condition determines the error returned."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_projected_reserve_shortfall
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Conf Two", email="cf2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="CF-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        get_success_data(api.reject_offer(offer["id"], AGENT))
        res = api.accept_offer(offer["id"], accept_offer_payload(v1), AGENT)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_account_delinquent_beats_offer_already_accepted(self, api):
        """PRD §3.6: "It then enforces account standing: a `DEFAULTED` program blocks acceptance with `ERR_ACCOUNT_DEFAULTED` (HTTP 409), and a `DELINQUENT` program blocks acceptance with `ERR_ACCOUNT_DELINQUENT` (HTTP 409). Next it confirms the debt does not already carry another `ACCEPTED` offer; a second acceptance on a debt that already has one is rejected with `ERR_OFFER_ALREADY_ACCEPTED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/account_delinquent_beats_offer_already_accepted
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Del Inq", email="del@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="DQ-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund(api, program["id"], client["id"], 5)
        offer_1 = create_offer(program["id"], debt["id"], offer_pct=0.40,
                              due_date="2026-07-01T00:00:00Z")
        accept_offer(offer_1["id"], v1)
        offer_2 = create_offer(program["id"], debt["id"], offer_pct=0.45,
                              due_date="2026-12-01T00:00:00Z")
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-06-10T00:00:00Z",
             "amount": 600, "status": "MISSED"}, ADMIN)
        prog = get_success_data(api.get_program(program["id"], ADMIN))
        v_now = prog["version"]
        res = api.accept_offer(offer_2["id"], accept_offer_payload(v_now), AGENT)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_DELINQUENT)

    def test_delinquent_blocks_second_acceptance_with_standing_error(self, api):
        """PRD §2.9: "While a program is `DELINQUENT`, no settlement offer may be accepted, though offers may still be recorded."
        PRD §3.6: "a `DELINQUENT` program blocks acceptance with `ERR_ACCOUNT_DELINQUENT` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/account_delinquent_beats_offer_already_accepted
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Delq Two", email="del2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="DQ-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund(api, program["id"], client["id"], 5)
        offer_1 = create_offer(program["id"], debt["id"], offer_pct=0.40,
                              due_date="2026-07-01T00:00:00Z")
        accept_offer(offer_1["id"], v1)
        offer_2 = create_offer(program["id"], debt["id"], offer_pct=0.45,
                              due_date="2026-12-01T00:00:00Z")
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-06-10T00:00:00Z",
             "amount": 600, "status": "MISSED"}, ADMIN)
        prog = get_success_data(api.get_program(program["id"], ADMIN))
        res = api.accept_offer(offer_2["id"], accept_offer_payload(prog["version"]), AGENT)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_DELINQUENT)


# =========================================================================
# Difficulty/boundary_precision_check
# =========================================================================
class TestBoundaryPrecision:

    def test_fee_tier_below_10000_is_low_band(self, api):
        """PRD §3.2: "a total below 10,000 dollars yields a rate of 0.25; a total of at least 10,000 but below 30,000 dollars yields 0.22; a total of 30,000 dollars or more yields 0.18."

        Design: Difficulty/boundary_precision_check/fee_tier_ceiling_boundary_at_10000
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Bo Und", email="bound@x.com", state_code="CA")
        prog_a = create_program(client["id"], monthly_deposit_amount=500)
        debt_a = create_debt(prog_a["id"], creditor_name="Cred", account_number="BA-1",
                            original_balance=9999)
        debt = get_success_data(api.get_debt(debt_a["id"], ADMIN))
        assert debt["fee_rate_pct"] == pytest.approx(0.25, abs=0.0001)

    def test_fee_tier_at_10000_is_mid_band(self, api):
        """PRD §3.2: "a total of at least 10,000 but below 30,000 dollars yields 0.22"

        Design: Difficulty/boundary_precision_check/fee_tier_ceiling_boundary_at_10000
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Bound2", email="bound2@x.com", state_code="CA")
        prog_b = create_program(client["id"], monthly_deposit_amount=500)
        debt_b = create_debt(prog_b["id"], creditor_name="Cred", account_number="BB-1",
                            original_balance=10000)
        debt = get_success_data(api.get_debt(debt_b["id"], ADMIN))
        assert debt["fee_rate_pct"] == pytest.approx(0.22, abs=0.0001)

    def test_tax_reportable_at_floor_600(self, api):
        """PRD §3.7: "a `reportable` flag that is true when the forgiven amount is at least 600 dollars (the IRS 1099-C reporting threshold) and false when it is greater than zero but below 600."

        Design: Difficulty/boundary_precision_check/tax_1099c_reportable_floor_at_600
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Flo Or", email="floor@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="FL-1",
                          original_balance=1000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        for m in (4, 5):
            api.create_deposit(
                {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-10T00:00:00Z",
                 "amount": 600}, make_client_headers(client["id"]))
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        accept_offer(offer["id"], v1)
        settle = get_success_data(api.create_settlement(
            create_settlement_payload(program["id"], offer["id"]), AGENT))
        get_success_data(api.complete_settlement(settle["id"], AGENT))
        tes = get_success_data(api.list_tax_events(
            ADMIN, params={"source_settlement_id": settle["id"]}))
        assert tes[0]["forgiven_amount"] == pytest.approx(600.00, abs=0.01)
        assert tes[0]["reportable"] is True

    def test_tax_forgiven_amount_equals_original_minus_funded(self, api):
        """PRD §3.7: "The forgiven amount is the debt's `original_balance` minus the settlement's `funded_amount`."

        Design: Difficulty/boundary_precision_check/tax_1099c_reportable_floor_at_600
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Floor2", email="floor2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="FL-1",
                          original_balance=1000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        for m in (4, 5):
            api.create_deposit(
                {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-10T00:00:00Z",
                 "amount": 600}, make_client_headers(client["id"]))
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        accept_offer(offer["id"], v1)
        settle = get_success_data(api.create_settlement(
            create_settlement_payload(program["id"], offer["id"]), AGENT))
        get_success_data(api.complete_settlement(settle["id"], AGENT))
        tes = get_success_data(api.list_tax_events(
            ADMIN, params={"source_settlement_id": settle["id"]}))
        # 1000 - 400
        assert tes[0]["forgiven_amount"] == pytest.approx(600.00, abs=0.01)


# =========================================================================
# Difficulty/cross_entity_state_dependency
# =========================================================================
class TestCrossEntityStateDependency:

    def test_offer_accept_blocked_by_defaulted_program(self, api):
        """PRD §2.9: "While a program is `DEFAULTED`, offer acceptance, settlement funding, and program completion are all blocked until the standing is cured."
        PRD §3.6: "a `DEFAULTED` program blocks acceptance with `ERR_ACCOUNT_DEFAULTED` (HTTP
        409)"

        Design: Difficulty/cross_entity_state_dependency/offer_accept_depends_on_program_standing
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Def Ault", email="def@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="DEF-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund(api, program["id"], client["id"], 5)
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        for m in (6, 7, 8):
            api.create_deposit(
                {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-02T00:00:00Z",
                 "amount": 600, "status": "MISSED"}, ADMIN)
        prog = get_success_data(api.get_program(program["id"], ADMIN))
        assert prog["account_standing"] == "DEFAULTED"
        res = api.accept_offer(offer["id"], accept_offer_payload(prog["version"]), AGENT)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_DEFAULTED)

    def test_defaulted_standing_set_before_accept_attempt(self, api):
        """PRD §2.9: "the moment the missed count reaches three or more, standing becomes `DEFAULTED`."

        Design: Difficulty/cross_entity_state_dependency/offer_accept_depends_on_program_standing
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Def Two", email="def2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        create_debt(program["id"], creditor_name="Cred", account_number="DEF-1",
                   original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        for m in (6, 7, 8):
            api.create_deposit(
                {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-02T00:00:00Z",
                 "amount": 600, "status": "MISSED"}, ADMIN)
        prog = get_success_data(api.get_program(program["id"], ADMIN))
        assert prog["account_standing"] == "DEFAULTED"
        assert prog["missed_deposit_count"] == 3

    def test_settlement_fund_blocked_when_offer_pending(self, api):
        """PRD §3.7: "Funding may only draw from an offer that is `ACCEPTED` and has not already produced a non-voided settlement; a request against an offer that is not in that condition is rejected with `ERR_OFFER_NOT_ACCEPTED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/settlement_fund_depends_on_offer_state
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Pen Ding", email="pend@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="PN-1",
                          original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-05-10T00:00:00Z",
             "amount": 600}, make_client_headers(client["id"]))
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        res = api.create_settlement(create_settlement_payload(program["id"], offer["id"]), AGENT)
        validate_error(res, ApiErrorId.ERR_OFFER_NOT_ACCEPTED)

    def test_fund_against_unaccepted_offer_rejected(self, api):
        """PRD §3.7: "Funding may only draw from an offer that is `ACCEPTED` and has not already produced a non-voided settlement; a request against an offer that is not in that condition is rejected with `ERR_OFFER_NOT_ACCEPTED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/settlement_fund_depends_on_offer_state
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Pend2", email="pend2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="PN-2",
                          original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-05-10T00:00:00Z",
             "amount": 600}, make_client_headers(client["id"]))
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        res = api.create_settlement(create_settlement_payload(program["id"], offer["id"]), AGENT)
        validate_error(res, ApiErrorId.ERR_OFFER_NOT_ACCEPTED)


# =========================================================================
# Difficulty/resource_temporal_overlap
# =========================================================================
class TestTemporalOverlap:

    def test_offer_window_overlap_within_30_days(self, api):
        """PRD §3.5: "A new offer collides when its `due_date` falls within 30 days of an existing `PENDING` offer's `due_date` on the same debt — that is, when the absolute gap between the two due dates is 30 days or fewer, so two offers exactly 30 days apart still collide because their closed buffers touch. A collision is rejected with `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/offer_window_pairwise_closed_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Ov Erlap", email="ov@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="OV-1",
                          original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        create_offer(program["id"], debt["id"], offer_pct=0.40,
                    due_date="2026-08-01T00:00:00Z")
        # 2026-07-15 is 17 days from 2026-08-01 (< 30) -> overlap
        res = api.create_offer(
            create_offer_payload(program["id"], debt["id"], offer_pct=0.45,
                                due_date="2026-07-15T00:00:00Z"), AGENT)
        validate_error(res, ApiErrorId.ERR_OFFER_WINDOW_OVERLAP)

    def test_offer_window_overlap_rejected_same_debt(self, api):
        """PRD §3.5: "Offers on the same debt must also be spaced apart in time. Treat each existing `PENDING` offer's `due_date` as the center of a closed buffer window extending 30 days on either side."

        Design: Difficulty/resource_temporal_overlap/offer_window_pairwise_closed_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Over2", email="ov2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="OV-2",
                          original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        create_offer(program["id"], debt["id"], offer_pct=0.40,
                    due_date="2026-08-01T00:00:00Z")
        res = api.create_offer(
            create_offer_payload(program["id"], debt["id"], offer_pct=0.45,
                                due_date="2026-07-15T00:00:00Z"), AGENT)
        validate_error(res, ApiErrorId.ERR_OFFER_WINDOW_OVERLAP)

    def test_deposit_same_month_bucket_occupied(self, api):
        """PRD §3.3: "If a `CLEARED` deposit's `scheduled_for` falls in a month bucket already occupied by another `CLEARED` deposit on the same program, it is rejected with `ERR_DEPOSIT_MONTH_OCCUPIED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/deposit_month_bucket_halfopen_occupancy
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Bu Cket", email="buck@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600)
        ch = make_client_headers(client["id"])
        get_success_data(api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-03-10T00:00:00Z",
             "amount": 600}, ch))
        res = api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-03-28T00:00:00Z",
             "amount": 600}, ch)
        validate_error(res, ApiErrorId.ERR_DEPOSIT_MONTH_OCCUPIED)

    def test_deposit_next_month_first_instant_is_distinct_bucket(self, api):
        """PRD §3.3: "Because the upper bound is exclusive, a deposit whose `scheduled_for` lands exactly on the first instant of the next month belongs to that next bucket, not the occupied one."

        Design: Difficulty/resource_temporal_overlap/deposit_month_bucket_halfopen_occupancy
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Buck2", email="buck2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600)
        ch = make_client_headers(client["id"])
        get_success_data(api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-03-10T00:00:00Z",
             "amount": 600}, ch))
        # 2026-04-01 first instant belongs to April bucket, distinct from March
        res = api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-04-01T00:00:00Z",
             "amount": 600}, ch)
        dep = get_success_data(res)
        assert dep["status"] == "CLEARED"
