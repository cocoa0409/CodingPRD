"""
State recovery: high-cost fund claims, Medicaid claims and cost projection.

The high-cost arithmetic nests a tier selection inside a per-student annual cap,
the Medicaid arithmetic counts only district-verified service delivery, and the
cost projection reports two forward-looking views without writing anything.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_HIGH_COST_THRESHOLD_NOT_MET,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MEDICAID_CONSENT_MISSING,
)
from test_helpers.fixtures import (
    ATTENDANCE_FILING_INSTANT,
    FULL_MONTH_PERIOD,
    add_authorized_addendum,
    bill_and_settle_cycle,
    build_active_day_placement,
    build_reference_data,
    build_simple_billing_cycle,
    create_invoice,
    file_attendance,
    file_funding_claim,
    list_rows,
    make_active_placement,
    make_approved_decision,
    read_attendance,
    read_funding_claim,
    read_placement,
    read_student,
    set_clock,
    verify_attendance,
    verify_invoice,
    approve_payment,
)
from test_helpers.test_users import COORDINATOR_HEADERS, FISCAL_OFFICER_HEADERS

# ─── The high-cost world: day 120000, residential 145000, service hour 9000 ────
HIGH_COST_RATES = {
    "day_rate_cents": 120000,
    "residential_rate_cents": 145000,
    "service_hourly_rate_cents": 9000,
}
PLACEMENT_A_OVERRIDES = {
    "residential": True,
    "placement_type": "RESIDENTIAL",
    "start_date": "2026-09-01",
    "end_date": "2026-12-31",
    "contracted_instructional_days": 80,
    "contracted_residential_nights": 120,
}
PLACEMENT_B_OVERRIDES = {
    "residential": True,
    "placement_type": "RESIDENTIAL",
    "start_date": "2027-01-05",
    "end_date": "2027-06-15",
    "contracted_instructional_days": 100,
    "contracted_residential_nights": 150,
}
PLACEMENT_A_ENCUMBRANCE_CENTS = 27000000
PLACEMENT_B_ENCUMBRANCE_CENTS = 33750000

# 28 days x 120000 + 28 nights x 145000 = 7420000 gross, 3% credit, 2.25% fee.
RESIDENTIAL_CYCLE_NET_CENTS = 7359342
CYCLE_A = {"period_start": "2026-10-05", "period_end": "2026-11-01"}
CYCLE_B = {"period_start": "2027-01-05", "period_end": "2027-02-01"}
CYCLE_A_FILED_AT = "2026-11-02T09:00:00Z"
CYCLE_B_FILED_AT = "2027-02-02T09:00:00Z"
PLACEMENT_B_ACTIVATED_AT = "2027-01-05T08:00:00Z"

# excess 7359342 - 4000000 = 3359342, tier 0.75, product 2519506.5 -> 2519507.
HIGH_COST_EXCESS_CENTS = 3359342
HIGH_COST_TIER_RATE = 0.75
FIRST_CLAIM_REIMBURSABLE_CENTS = 2519507
SECOND_CLAIM_REIMBURSABLE_CENTS = 2480493
PER_STUDENT_CAP_CENTS = 5000000
CAP_TRIM_CENTS = 39014

# ─── The Medicaid world ───────────────────────────────────────────────────────
MEDICAID_STUDENT = {"medicaid_eligible": True, "medicaid_consent_on_file": True}
MEDICAID_BILLABLE_HOURS = 7.5
MEDICAID_ELIGIBLE_BASE_CENTS = 67500
MEDICAID_TIER_RATE = 0.5432
MEDICAID_REIMBURSABLE_CENTS = 36666
MEDICAID_BASE_IF_BOTH_RECORDS_COUNTED_CENTS = 135000
MEDICAID_AWARD_IF_BOTH_RECORDS_COUNTED_CENTS = 73332
SECOND_CYCLE = {"period_start": "2026-11-02", "period_end": "2026-11-29"}
SECOND_CYCLE_FILED_AT = "2026-11-30T09:00:00Z"
STATE_SUBMISSION_INSTANT = "2026-12-01T10:30:00Z"
STATE_REFERENCE = "MCD-2027-000481"
SECOND_STATE_REFERENCE = "MCD-2027-000999"

# ─── The cost-projection world ────────────────────────────────────────────────
PLAIN_NET_CENTS = 654400
CONTRACTED_PROJECTION_CENTS = 6552000
RUN_RATE_PROJECTION_CENTS = 8507200
PROJECTION_GAP_CENTS = 1955200
REMAINING_COMMITMENT_CENTS = 5897600
DAY_CONTRACT_ENCUMBRANCE_CENTS = 5760000


def _two_sequential_residential_placements(api):
    """
    One student, two non-overlapping RESIDENTIAL placements in the same fiscal
    year. Both decisions are approved before the first activation, because approval
    is barred once the student is already out of district.
    """
    ref = build_reference_data(api, rate_overrides=HIGH_COST_RATES)
    student_id = ref["student"]["id"]
    decision_a = make_approved_decision(api, student_id, residential=True)
    decision_b = make_approved_decision(api, student_id, residential=True)

    placement_a = make_active_placement(
        api, ref, decision=decision_a, **PLACEMENT_A_OVERRIDES
    )
    assert (
        placement_a["contract_encumbrance_cents"] == PLACEMENT_A_ENCUMBRANCE_CENTS
    )
    world_a = dict(ref)
    world_a["placement"] = placement_a
    return ref, world_a, decision_b


def _settle_residential_cycle(api, world, *, period, filing_instant, settle=True):
    return bill_and_settle_cycle(
        api,
        world,
        period_start=period["period_start"],
        period_end=period["period_end"],
        filing_instant=filing_instant,
        submitted_amount_cents=RESIDENTIAL_CYCLE_NET_CENTS,
        basis="ENROLLMENT",
        days_enrolled=28,
        days_attended=28,
        days_absent_unexcused=0,
        residential_nights=28,
        settle=settle,
    )


def _claims_for(api, placement_id):
    rows, meta = list_rows(
        api.list_funding_claims(FISCAL_OFFICER_HEADERS, {"placement_id": placement_id})
    )
    return rows, meta


class TestHighCostTierAndCap:
    """A tier chosen from the excess, then trimmed by the per-student ceiling."""

    def test_the_tier_rate_is_selected_from_the_excess_over_the_trigger(self, api):
        """
        A settled 7359342 leaves an excess of 3359342, which selects the middle
        tier of 0.75 and awards 2519507 with no trimming.

        PRD: "The `tier_rate` is selected from that excess by inclusive floors: 0.90 when the excess is at least 6 000 000 cents, otherwise 0.75 when the excess is at least 2 000 000 cents, otherwise 0.60."

        Design: Difficulty/combinatorial_formula/high_cost_fund_nested_min_max_tier_and_per_student_cap
        """
        ref, world_a, _ = _two_sequential_residential_placements(api)
        _settle_residential_cycle(
            api, world_a, period=CYCLE_A, filing_instant=CYCLE_A_FILED_AT
        )

        placement_a = read_placement(api, world_a["placement"]["id"])
        assert placement_a["paid_total_ytd_cents"] == RESIDENTIAL_CYCLE_NET_CENTS

        rows, meta = _claims_for(api, world_a["placement"]["id"])
        assert meta["total_count"] == 1
        claim = rows[0]
        assert claim["source"] == "AUTO_CASCADE"
        assert claim["claim_type"] == "HIGH_COST_FUND"
        assert claim["eligible_base_cents"] == RESIDENTIAL_CYCLE_NET_CENTS
        assert claim["tier_rate"] == pytest.approx(HIGH_COST_TIER_RATE)
        assert claim["reimbursable_amount_cents"] == FIRST_CLAIM_REIMBURSABLE_CENTS
        assert (
            RESIDENTIAL_CYCLE_NET_CENTS - 4000000 == HIGH_COST_EXCESS_CENTS
        )

        student = read_student(api, ref["student"]["id"])
        assert student["high_cost_flag"] is True
        assert (
            student["projected_state_recovery_cents"]
            == FIRST_CLAIM_REIMBURSABLE_CENTS
        )

    def test_the_second_placement_claim_is_trimmed_by_the_per_student_cap(self, api):
        """
        The same tier product on the student's second placement is cut to the
        remaining headroom under the five-million-cent annual ceiling.

        PRD: "`reimbursable_amount_cents` is then the greater of 0 and the lesser of two quantities: the excess multiplied by the `tier_rate` and rounded half up to whole cents, and 5 000 000 cents minus the prior awarded total."

        Design: Difficulty/combinatorial_formula/high_cost_fund_nested_min_max_tier_and_per_student_cap
        """
        ref, world_a, decision_b = _two_sequential_residential_placements(api)
        _settle_residential_cycle(
            api, world_a, period=CYCLE_A, filing_instant=CYCLE_A_FILED_AT
        )

        placement_b = make_active_placement(
            api,
            ref,
            decision=decision_b,
            activation_instant=PLACEMENT_B_ACTIVATED_AT,
            **PLACEMENT_B_OVERRIDES,
        )
        assert (
            placement_b["contract_encumbrance_cents"] == PLACEMENT_B_ENCUMBRANCE_CENTS
        )
        world_b = dict(ref)
        world_b["placement"] = placement_b
        _settle_residential_cycle(
            api, world_b, period=CYCLE_B, filing_instant=CYCLE_B_FILED_AT
        )

        first_rows, first_meta = _claims_for(api, world_a["placement"]["id"])
        second_rows, second_meta = _claims_for(api, placement_b["id"])
        assert first_meta["total_count"] == 1
        assert second_meta["total_count"] == 1

        first_claim, second_claim = first_rows[0], second_rows[0]
        assert first_claim["reimbursable_amount_cents"] == (
            FIRST_CLAIM_REIMBURSABLE_CENTS
        )
        assert second_claim["source"] == "AUTO_CASCADE"
        assert second_claim["eligible_base_cents"] == RESIDENTIAL_CYCLE_NET_CENTS
        assert second_claim["tier_rate"] == pytest.approx(HIGH_COST_TIER_RATE)
        assert second_claim["reimbursable_amount_cents"] == (
            SECOND_CLAIM_REIMBURSABLE_CENTS
        )
        assert (
            FIRST_CLAIM_REIMBURSABLE_CENTS - SECOND_CLAIM_REIMBURSABLE_CENTS
            == CAP_TRIM_CENTS
        )

        student = read_student(api, ref["student"]["id"])
        assert student["projected_state_recovery_cents"] == PER_STUDENT_CAP_CENTS
        assert student["high_cost_flag"] is True


def _medicaid_world(api, *, consent=True, second_record=False):
    """
    A placement whose speech addendum is Medicaid billable, with 7.5 verified
    hours on it and, optionally, a further 7.5 hours left unverified.
    """
    world = build_active_day_placement(
        api,
        student_overrides={
            "medicaid_eligible": True,
            "medicaid_consent_on_file": consent,
        },
    )
    placement_id = world["placement"]["id"]
    addendum = add_authorized_addendum(
        api,
        placement_id,
        service_type="SPEECH",
        authorized_hours_per_week=2.0,
        contract_weeks=36,
        medicaid_billable=True,
    )
    set_clock(api, ATTENDANCE_FILING_INSTANT)
    verified_record = file_attendance(
        api,
        world,
        placement_id,
        days_enrolled=20,
        days_attended=20,
        days_absent_unexcused=0,
        residential_nights=0,
        service_delivery_lines=[f.service_line(addendum["id"], 7.5)],
        **FULL_MONTH_PERIOD,
    )
    verify_attendance(api, verified_record["id"])
    world["addendum"] = addendum
    world["verified_record"] = verified_record

    if second_record:
        set_clock(api, SECOND_CYCLE_FILED_AT)
        world["submitted_record"] = file_attendance(
            api,
            world,
            placement_id,
            days_enrolled=20,
            days_attended=20,
            days_absent_unexcused=0,
            residential_nights=0,
            service_delivery_lines=[f.service_line(addendum["id"], 7.5)],
            **SECOND_CYCLE,
        )
    return world


class TestMedicaidClaimArithmetic:
    """Only district-verified service delivery is federally billable."""

    def test_hours_on_an_unverified_record_are_excluded(self, api):
        """
        Two records each report 7.5 billable hours, but only the verified one
        counts, so the claim is worth half of what both together would be.

        PRD: "Three exclusions are load-bearing: a line naming an addendum with `medicaid_billable` false contributes zero, a record still in `SUBMITTED` contributes zero, and a record in `DISPUTED` contributes zero — only district-verified delivery is federally billable."

        Design: Corner/calculations/medicaid_claim_counts_only_verified_attendance_hours
        """
        world = _medicaid_world(api, second_record=True)

        claim = validate_success(
            api.create_funding_claim(
                f.funding_claim_payload(world["placement"]["id"], "MEDICAID"),
                FISCAL_OFFICER_HEADERS,
            ),
            201,
        )
        assert claim["billable_service_hours"] == pytest.approx(
            MEDICAID_BILLABLE_HOURS
        )
        assert claim["eligible_base_cents"] == MEDICAID_ELIGIBLE_BASE_CENTS
        assert claim["eligible_base_cents"] != (
            MEDICAID_BASE_IF_BOTH_RECORDS_COUNTED_CENTS
        )
        assert claim["tier_rate"] == pytest.approx(MEDICAID_TIER_RATE)
        assert claim["reimbursable_amount_cents"] == MEDICAID_REIMBURSABLE_CENTS
        assert claim["reimbursable_amount_cents"] != (
            MEDICAID_AWARD_IF_BOTH_RECORDS_COUNTED_CENTS
        )
        assert claim["status"] == "ELIGIBLE"
        assert claim["source"] == "MANUAL"

        assert read_attendance(api, world["submitted_record"]["id"])["status"] == (
            "SUBMITTED"
        )

    def test_a_medicaid_claim_without_consent_on_file_is_refused(self, api):
        """
        Eligibility alone is not enough: both flags must be true, and the safety
        rung answers before any fiscal rule.

        PRD: "For a `MEDICAID` claim, the student must have both `medicaid_eligible` and `medicaid_consent_on_file` set to true, or the claim is refused with `ERR_MEDICAID_CONSENT_MISSING`."

        Design: Corner/validations/medicaid_funding_claim_without_parental_consent_rejected
        """
        world = _medicaid_world(api, consent=False)

        response = api.create_funding_claim(
            f.funding_claim_payload(world["placement"]["id"], "MEDICAID"),
            FISCAL_OFFICER_HEADERS,
        )
        validate_error(response, ERR_MEDICAID_CONSENT_MISSING, 409)

        _, meta = _claims_for(api, world["placement"]["id"])
        assert meta["total_count"] == 0
        student = read_student(api, world["student"]["id"])
        assert student["projected_state_recovery_cents"] == 0
        assert student["high_cost_flag"] is False


class TestHighCostEligibilityGate:
    """The trigger is checked before any tier or cap arithmetic."""

    def test_a_high_cost_claim_below_the_trigger_is_refused_on_eligibility(
        self, api
    ):
        """
        One settled cycle is nowhere near the trigger, and the refusal names the
        threshold rather than the per-student ceiling.

        PRD: "If that figure is *below* 4 000 000 cents the claim is refused with `ERR_HIGH_COST_THRESHOLD_NOT_MET`; the comparison is strict, so a placement that has paid exactly 4 000 000 cents qualifies."

        Design: Corner/validations/high_cost_claim_below_the_trigger_rejected
        """
        world = build_simple_billing_cycle(api)
        placement_id = world["placement"]["id"]
        invoice = create_invoice(
            api, world, placement_id, world["record"]["id"], PLAIN_NET_CENTS
        )
        verify_invoice(api, invoice["id"])
        approve_payment(api, invoice["id"])
        assert read_placement(api, placement_id)["paid_total_ytd_cents"] == (
            PLAIN_NET_CENTS
        )

        response = api.create_funding_claim(
            f.funding_claim_payload(placement_id, "HIGH_COST_FUND"),
            FISCAL_OFFICER_HEADERS,
        )
        validate_error(response, ERR_HIGH_COST_THRESHOLD_NOT_MET, 409)

        _, meta = _claims_for(api, placement_id)
        assert meta["total_count"] == 0
        student = read_student(api, world["student"]["id"])
        assert student["high_cost_flag"] is False
        assert student["projected_state_recovery_cents"] == 0


class TestSubmitClaimToState:
    """The state submission stamps the reference and is a one-way door."""

    def test_submission_stamps_the_reference_and_the_clock_then_locks(self, api):
        """
        The first submission records the state's reference at the current logical
        instant; a second submission of the same claim is refused and changes
        nothing.

        PRD: "Side effects: `status` set to `SUBMITTED`, `submitted_at` set to the logical clock's current instant, `state_claim_reference` stored, and `version` incremented."

        Design: Corner/endpoints/funding_claim_submit_to_state_stamps_reference_and_timestamp
        """
        world = _medicaid_world(api)
        claim = file_funding_claim(api, world["placement"]["id"], "MEDICAID")
        assert claim["status"] == "ELIGIBLE"
        assert claim["reimbursable_amount_cents"] == MEDICAID_REIMBURSABLE_CENTS
        assert claim["submitted_at"] is None
        assert claim["state_claim_reference"] is None
        filed_version = claim["version"]

        set_clock(api, STATE_SUBMISSION_INSTANT)
        submitted = validate_success(
            api.submit_funding_claim_to_state(
                claim["id"],
                f.submit_to_state_payload(STATE_REFERENCE),
                FISCAL_OFFICER_HEADERS,
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["state_claim_reference"] == STATE_REFERENCE
        assert_instant_equals(submitted["submitted_at"], STATE_SUBMISSION_INSTANT)
        assert submitted["reimbursable_amount_cents"] == MEDICAID_REIMBURSABLE_CENTS
        assert submitted["version"] == filed_version + 1

        replay = api.submit_funding_claim_to_state(
            claim["id"],
            f.submit_to_state_payload(SECOND_STATE_REFERENCE),
            FISCAL_OFFICER_HEADERS,
        )
        validate_error(replay, ERR_INVALID_STATE_TRANSITION, 409)

        stored = read_funding_claim(api, claim["id"])
        assert stored["state_claim_reference"] == STATE_REFERENCE
        assert_instant_equals(stored["submitted_at"], STATE_SUBMISSION_INSTANT)
        assert stored["status"] == "SUBMITTED"


class TestCostProjectionVariants:
    """Two forward-looking views of the same placement, neither of them a write."""

    def test_the_run_rate_view_diverges_from_the_commitment_view(self, api):
        """
        A single settled cycle annualised over thirteen periods projects well
        above the signed commitment, while the commitment view ignores invoices
        entirely; both reads leave the placement alone.

        PRD: "The response carries `placement_id`, the `variant` actually applied, `projected_annual_cents`, `remaining_commitment_cents`, `variance_cents` and `periods_paid`, with `periods_paid` reported as 0 under the contracted-encumbrance variant, which does not consult invoices at all."

        Design: Corner/calculations/cost_projection_run_rate_diverges_from_contracted_encumbrance
        """
        world = build_simple_billing_cycle(api)
        placement_id = world["placement"]["id"]
        add_authorized_addendum(
            api,
            placement_id,
            service_type="SPEECH",
            authorized_hours_per_week=2.0,
            contract_weeks=36,
        )
        invoice = create_invoice(
            api, world, placement_id, world["record"]["id"], PLAIN_NET_CENTS
        )
        verify_invoice(api, invoice["id"])
        approve_payment(api, invoice["id"])

        before = read_placement(api, placement_id)
        assert before["contract_encumbrance_cents"] == DAY_CONTRACT_ENCUMBRANCE_CENTS
        assert before["paid_total_ytd_cents"] == PLAIN_NET_CENTS

        contracted = validate_success(
            api.get_cost_projection(placement_id, COORDINATOR_HEADERS)
        )
        assert contracted["placement_id"] == placement_id
        assert contracted["variant"] == "CONTRACTED_ENCUMBRANCE"
        assert contracted["projected_annual_cents"] == CONTRACTED_PROJECTION_CENTS
        assert contracted["variance_cents"] == (
            CONTRACTED_PROJECTION_CENTS - DAY_CONTRACT_ENCUMBRANCE_CENTS
        )
        assert contracted["remaining_commitment_cents"] == REMAINING_COMMITMENT_CENTS
        assert contracted["periods_paid"] == 0

        run_rate = validate_success(
            api.get_cost_projection(
                placement_id,
                COORDINATOR_HEADERS,
                {"variant": "ACTUAL_RUN_RATE"},
            )
        )
        assert run_rate["variant"] == "ACTUAL_RUN_RATE"
        assert run_rate["periods_paid"] == 1
        assert run_rate["projected_annual_cents"] == RUN_RATE_PROJECTION_CENTS
        assert run_rate["variance_cents"] == (
            RUN_RATE_PROJECTION_CENTS - DAY_CONTRACT_ENCUMBRANCE_CENTS
        )
        assert run_rate["remaining_commitment_cents"] == REMAINING_COMMITMENT_CENTS

        assert (
            run_rate["projected_annual_cents"]
            - contracted["projected_annual_cents"]
        ) == PROJECTION_GAP_CENTS

        after = read_placement(api, placement_id)
        assert after == before
