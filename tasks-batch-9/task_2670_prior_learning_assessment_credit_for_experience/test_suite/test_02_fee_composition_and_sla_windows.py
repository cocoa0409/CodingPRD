"""Invoice line composition and turnaround allowance composition.

Neither figure is a single lookup. The invoice total re-selects its discount tier
from the post-credit subtotal, and the turnaround allowance stacks the artifact
tier and the rush halving in a fixed order.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_claim_dimensions,
    assert_fields_equal,
    assert_instant,
    assert_invoice_money,
    assert_ledger,
    assert_line,
    assert_lines_exactly,
    assert_sla,
)
from test_helpers.test_users import COORDINATOR, make_student_headers
from test_helpers.types import (
    Alignment,
    AssignmentStatus,
    CourseLevel,
    FeeStatus,
    InvoiceLineKind,
    PaymentMethod,
    PriorityTier,
    RevokeReason,
    SelectionReason,
    SlaState,
    SourceType,
)


def _bscs_program(client):
    return fx.new_program(
        client,
        program_code="BSCS",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
    )


def _cs200(client):
    """Course CS200: 5 credits, LOWER, OC1 weighted 8000 and OC2 weighted 2000."""
    return fx.new_course(
        client,
        course_code="CS200",
        department_code="CS",
        credits=5,
        level=CourseLevel.LOWER,
        learning_outcomes=[
            f.outcome_payload("OC1", 8000, mastery_threshold_bp=7000),
            f.outcome_payload("OC2", 2000, mastery_threshold_bp=7000),
        ],
    )


def _two_artifact_portfolio(client, claim_id, student_id, outcomes):
    portfolio = fx.new_portfolio(client, claim_id, student_id)
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)]
    )
    return fx.submit_portfolio(client, portfolio["id"], student_id)


@pytest.fixture
def breached_assignment(client):
    """A paid 5-credit portfolio claim whose 240-hour allowance has just expired.

    The invoice is priced at a 27500-cent subtotal, which is the top discount
    band, and paid in full. The clock then stands exactly on ``due_at``.
    """
    program = _bscs_program(client)
    course = _cs200(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    first = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    second = fx.new_assessor(
        client,
        employee_number="E-9002",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=5,
        rush_requested=False,
    )
    _two_artifact_portfolio(client, claim["id"], student["id"], outcomes)
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.pay_invoice(
            invoice["id"],
            f.payment_payload(24750, PaymentMethod.CARD),
            headers=make_student_headers(student["id"]),
        )
    )
    assignment = fx.assign_assessor(client, claim["id"], first["id"])
    fx.accept_assignment(client, assignment["id"], first["id"])
    fx.set_clock(client, "2026-08-11T00:00:00Z")
    return {
        "student": student,
        "claim": claim,
        "invoice": invoice,
        "assignment": assignment,
        "first": first,
        "second": second,
    }


def test_negative_service_credit_line_reselects_a_lower_discount_tier(
    client, breached_assignment
):
    """A -4125 credit line drops the subtotal out of the 25000-cent band.

    PRD: "The service credit is a **negative** line, present only when the claim's
    `sla_breach_count` is at least 1, equal to minus one times the base,
    per-credit, artifact and rush lines summed, multiplied by 1500 basis points,
    divided by 10000, rounded half up". "A subtotal of at least 25000 cents earns
    `discount_bp` of 1000; a subtotal of at least 10000 but below 25000 earns 500;
    anything below 10000 earns 0." "Because the tier is keyed on the subtotal, a
    negative service-credit line can drop a claim into a lower discount band and
    therefore change `discount_bp` as well as the total."

    Design: Difficulty/combinatorial_formula/fee_invoice_six_line_composition_with_discount_tier_reselection
    """
    invoice_id = breached_assignment["invoice"]["id"]

    before = get_success_data(client.get_invoice(invoice_id, headers=COORDINATOR))
    # A PORTFOLIO base of 15000 plus 2500 per credit over 5 credits, with two
    # artifacts charging nothing on the tier line.
    assert_lines_exactly(
        before,
        [
            (InvoiceLineKind.BASE_ASSESSMENT_FEE, 15000),
            (InvoiceLineKind.PER_CREDIT_FEE, 12500),
        ],
    )
    assert_invoice_money(
        before,
        subtotal_cents=27500,
        discount_bp=1000,
        discount_cents=2750,
        total_cents=24750,
        paid_cents=24750,
        balance_due_cents=0,
    )

    validate_success(client.run_escalation_sweep(headers=COORDINATOR))

    after = get_success_data(client.get_invoice(invoice_id, headers=COORDINATOR))
    # 15000 + 12500 = 27500, times 1500 basis points, is 4125 charged as a credit.
    assert_line(after, InvoiceLineKind.SLA_SERVICE_CREDIT, -4125)
    assert_invoice_money(
        after,
        subtotal_cents=23375,
        discount_bp=500,
        discount_cents=1169,
        total_cents=22206,
    )


def test_service_credit_refund_is_smaller_than_the_credit_line_itself(
    client, breached_assignment
):
    """The shrinking discount claws back part of the 4125-cent credit.

    PRD: "**Hop three:** the claim's invoice gains a negative service-credit line
    and is repriced, which can re-select a lower discount tier and therefore
    change `discount_bp` as well as `total_cents`; the resulting overpayment is
    auto-refunded so that `balance_due_cents` returns to 0 and `fee_status`
    remains `PAID`." "The overpayment is then moved into `refunded_cents` so that
    `balance_due_cents` lands on exactly 0."

    Design: Difficulty/combinatorial_formula/fee_invoice_six_line_composition_with_discount_tier_reselection
    """
    invoice_id = breached_assignment["invoice"]["id"]
    claim_id = breached_assignment["claim"]["id"]
    assignment_id = breached_assignment["assignment"]["id"]

    sweep = validate_success(client.run_escalation_sweep(headers=COORDINATOR))
    assert sweep["breached_count"] == 1, "exactly one assignment stands on its due_at"
    assert assignment_id in sweep["revoked_assignment_ids"]
    assert invoice_id in sweep["credited_invoice_ids"]

    assignment = get_success_data(client.get_assignment(assignment_id, headers=COORDINATOR))
    assert_fields_equal(
        assignment,
        status=AssignmentStatus.REVOKED,
        revoke_reason=RevokeReason.SLA_BREACH,
    )
    assert_sla(assignment, sla_hours=240, elapsed_bp=10000, sla_state=SlaState.BREACHED)

    claim = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_fields_equal(claim, sla_breach_count=1, priority_tier=PriorityTier.EXPEDITED)
    assert_claim_dimensions(claim, fee_status=FeeStatus.PAID)

    # 24750 already settled against a new total of 22206 leaves 2544 over, which
    # is strictly less than the 4125-cent credit line.
    invoice = get_success_data(client.get_invoice(invoice_id, headers=COORDINATOR))
    assert_invoice_money(
        invoice,
        total_cents=22206,
        paid_cents=24750,
        refunded_cents=2544,
        balance_due_cents=0,
        recompute_count=1,
    )
    assert invoice["refunded_cents"] < 4125, (
        "the refund must be smaller than the credit line because the discount shrank"
    )

    student = get_success_data(
        client.get_student(breached_assignment["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, fee_paid_net_cents=22206)

    replacement_ids = sweep["replacement_assignment_ids"]
    assert len(replacement_ids) == 1, "the breach cascade must issue one replacement"
    replacement = get_success_data(
        client.get_assignment(replacement_ids[0], headers=COORDINATOR)
    )
    assert_fields_equal(
        replacement,
        assessor_id=breached_assignment["second"]["id"],
        selection_reason=SelectionReason.AUTO_REPLACEMENT,
    )


@pytest.fixture
def expedited_five_artifact_claim(client):
    """A rush portfolio claim on CS200 holding 5 artifacts, fee waived.

    Five artifacts land in the 4-through-8 tier and the rush flag makes the claim
    ``EXPEDITED``, so the allowance is stretched and then halved.
    """
    program = _bscs_program(client)
    course = _cs200(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=5,
        rush_requested=True,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student["id"])
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[0]["id"], Alignment.SUPPORTING)]
    )
    for _ in range(3):
        fx.attach_artifact(
            client,
            portfolio["id"],
            student["id"],
            [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)],
        )
    submitted_portfolio = fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.waive_invoice(invoice["id"], {"waive_reason": "HARDSHIP"}, headers=COORDINATOR)
    )
    return {
        "claim": claim,
        "portfolio": submitted_portfolio,
        "assessor": assessor,
    }


def test_sla_hours_stretches_by_the_artifact_tier_then_halves_for_rush(
    client, expedited_five_artifact_claim
):
    """240 hours becomes 300 on the artifact tier and then 150 on the rush.

    PRD: "one holding 4 through 8 artifacts applies 12500 basis points". "Step one:
    multiply the source base by the artifact multiplier, divide by 10000, and round
    half up to whole hours — call this the tiered allowance. Step two: when the
    claim's `priority_tier` is `EXPEDITED`, multiply the tiered allowance by 5000
    basis points, divide by 10000, and round half up to whole hours; when it is
    `STANDARD`, the tiered allowance stands unchanged. The result is `sla_hours`."

    Design: Difficulty/combinatorial_formula/sla_due_at_tier_then_rush_two_step_composition
    """
    assert_fields_equal(expedited_five_artifact_claim["portfolio"], artifact_count=5)

    claim = get_success_data(
        client.get_claim(expedited_five_artifact_claim["claim"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(claim, priority_tier=PriorityTier.EXPEDITED)

    assignment = fx.assign_assessor(
        client,
        expedited_five_artifact_claim["claim"]["id"],
        expedited_five_artifact_claim["assessor"]["id"],
    )
    assert_sla(assignment, sla_hours=150)
    assert assignment["sla_hours"] != 300, (
        "150 hours is the halved figure; 300 is the pre-rush tiered allowance"
    )
    assert_instant(assignment["assigned_at"], "2026-08-01T00:00:00Z", "assigned_at")
    assert_instant(assignment["due_at"], "2026-08-07T06:00:00Z", "due_at")


def test_at_risk_at_derives_from_the_final_allowance_not_the_pre_rush_one(
    client, expedited_five_artifact_claim
):
    """The at-risk offset is 120 hours, eight tenths of 150 and not of 300.

    PRD: "`at_risk_at` is `assigned_at` advanced by `sla_hours` multiplied by 8000
    basis points, divided by 10000, rounded half up to whole hours — and it is
    derived from the **final** `sla_hours`, never from the pre-rush tiered
    allowance." "an `EXPEDITED` portfolio claim whose portfolio holds 5 artifacts
    has a tiered allowance of 300 hours, an `sla_hours` of 150, and an at-risk
    offset of 120 hours"

    Design: Difficulty/combinatorial_formula/sla_due_at_tier_then_rush_two_step_composition
    """
    assignment = fx.assign_assessor(
        client,
        expedited_five_artifact_claim["claim"]["id"],
        expedited_five_artifact_claim["assessor"]["id"],
    )

    assert_sla(
        assignment,
        sla_hours=150,
        due_at="2026-08-07T06:00:00Z",
        at_risk_at="2026-08-06T00:00:00Z",
        sla_state=SlaState.ON_TRACK,
        elapsed_bp=0,
    )
    # An offset taken from the pre-rush 300 hours would have landed here instead.
    assert assignment["at_risk_at"] != "2026-08-11T00:00:00Z"
