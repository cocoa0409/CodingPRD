"""Fee-bill computation (both methods), tier boundary, parallel dimensions,
reserve conservation, OCC, and lifecycle guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_field_adjuster_headers,
    create_fee_bill_payload,
)
from test_helpers import fixtures as fx

BILLING = TEST_USERS["billing_manager_headers"]
DESK = TEST_USERS["desk_examiner_headers"]


# --------------------------------------------------------------------------
# Difficulty: FEE_SCHEDULE vs TIME_AND_EXPENSE divergence + supersession
# --------------------------------------------------------------------------
def _wc_hurricane_acv_bignum(api):
    return fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HURRICANE", policy_type="ACV",
        rcv_line_cents=10_000_000, depreciation_pct=20, photo_count=4, with_fee_schedule=True,
    )


def test_fee_schedule_bill_total(api):
    """PRD 3.6: "To that flat fee is added a percent-of-RCV component ... and the
    product floored to whole cents. The flat fee plus this floored percent component is
    the base. If the claim's peril_type is a catastrophe peril — one of HURRICANE,
    FLOOD, WILDFIRE, or TORNADO ... — the base is scaled by the schedule's
    cat_peril_multiplier_bps ... That figure is the subtotal_cents, and because
    fee-schedule bills carry no expenses, the total_cents equals the subtotal_cents."

    Design: Difficulty/dual_variant_calc/fee_bill_method_divergence
    """
    ctx = _wc_hurricane_acv_bignum(api)
    bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                              billing_method="FEE_SCHEDULE")
    # tier2 flat 60000 + floor(0.025*10000000)=250000 -> base 310000; CAT floor(310000*1.25)=387500.
    assert bill["total_cents"] == 387500


def test_time_and_expense_bill_supersedes_fee_schedule(api):
    """PRD 2.6: "Each create mints a fresh DRAFT bill that supersedes any prior
    non-PAID bill for the same assignment (the prior bill is voided) and increments the
    assignment's version by 1." PRD 3.6: T&E "labor figure is the sum of hours across
    every time entry on the assignment, multiplied by the schedule's hourly_rate_cents,
    with the product floored to whole cents ... The total_cents is the labor plus the
    sum of expense_cents across those same time entries."

    Design: Difficulty/dual_variant_calc/fee_bill_method_divergence
    """
    ctx = _wc_hurricane_acv_bignum(api)
    fx.create_time_entry(api, ctx["asg_id"], ctx["adj_id"], work_date="2026-07-02T00:00:00Z",
                         activity="INSPECTION", hours=6.0, expense_cents=15000)
    fx.create_time_entry(api, ctx["asg_id"], ctx["adj_id"], work_date="2026-07-03T00:00:00Z",
                         activity="REPORT", hours=4.5, expense_cents=5000)
    fs_bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                                 billing_method="FEE_SCHEDULE")
    te_bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                                 billing_method="TIME_AND_EXPENSE")
    # labor = floor(10.5 * 8500) = 89250; expenses = 20000 -> total 109250.
    assert te_bill["total_cents"] == 109250
    assert te_bill["total_cents"] != 387500
    superseded = validate_success(api.get_fee_bill(fs_bill["id"], DESK))
    assert superseded["status"] == "VOID", "the prior fee-schedule bill must be voided"


# --------------------------------------------------------------------------
# Difficulty: tiered flat fee + capped percent + CAT multiplier
# --------------------------------------------------------------------------
def test_fee_schedule_cat_subtotal(api):
    """PRD 3.6: "the base is multiplied by cat_peril_multiplier_bps, divided by 10000,
    and the result floored, in that order. Otherwise the base is used unscaled. That
    figure is the subtotal_cents."

    Design: Difficulty/combinatorial_formula/fee_schedule_tiered_cat_multiplier
    """
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HURRICANE", policy_type="ACV",
        rcv_line_cents=10_000_000, depreciation_pct=0, with_fee_schedule=True,
    )
    bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                              billing_method="FEE_SCHEDULE")
    assert bill["subtotal_cents"] == 387500


def test_fee_schedule_cat_total_equals_subtotal(api):
    """PRD 3.6: "That figure is the subtotal_cents, and because fee-schedule bills
    carry no expenses, the total_cents equals the subtotal_cents."

    Design: Difficulty/combinatorial_formula/fee_schedule_tiered_cat_multiplier
    """
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HURRICANE", policy_type="ACV",
        rcv_line_cents=10_000_000, depreciation_pct=0, with_fee_schedule=True,
    )
    bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                              billing_method="FEE_SCHEDULE")
    assert bill["total_cents"] == 387500
    assert bill["total_cents"] == bill["subtotal_cents"]


# --------------------------------------------------------------------------
# Difficulty: inclusive tier-1 boundary on RCV
# --------------------------------------------------------------------------
def test_fee_tier_boundary_at_tier1_max_inclusive(api):
    """PRD 3.6: "a claim RCV at or below tier1_max_rcv_cents selects the
    tier1_flat_fee_cents; an RCV above tier 1 but at or below tier2_max_rcv_cents
    selects the tier2_flat_fee_cents; anything above tier 2 selects the
    tier3_flat_fee_cents."

    Design: Difficulty/boundary_precision_check/fee_tier_boundary_rcv_inclusive
    """
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HAIL", policy_type="RCV",
        rcv_line_cents=5_000_000, depreciation_pct=0, with_fee_schedule=True,
    )
    bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                              billing_method="FEE_SCHEDULE")
    # rcv == tier1_max -> tier1 flat 30000 + floor(0.025*5000000)=125000 -> 155000; HAIL is non-CAT.
    assert bill["total_cents"] == 155000


def test_fee_tier_above_boundary_selects_tier2(api):
    """PRD 3.6: "a claim RCV at or below tier1_max_rcv_cents selects the
    tier1_flat_fee_cents; an RCV above tier 1 but at or below tier2_max_rcv_cents
    selects the tier2_flat_fee_cents; anything above tier 2 selects the
    tier3_flat_fee_cents."

    Design: Difficulty/boundary_precision_check/fee_tier_boundary_rcv_inclusive
    """
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HAIL", policy_type="RCV",
        rcv_line_cents=5_000_001, depreciation_pct=0, with_fee_schedule=True,
    )
    bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                              billing_method="FEE_SCHEDULE")
    # rcv == tier1_max+1 -> tier2 flat 60000 + floor(0.025*5000001)=125000 -> 185000.
    assert bill["total_cents"] == 185000


# --------------------------------------------------------------------------
# Difficulty: independent work / billing dimensions
# --------------------------------------------------------------------------
def _submitted_bill_ctx(api):
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HAIL", policy_type="RCV",
        rcv_line_cents=4_000_000, depreciation_pct=0, with_fee_schedule=True,
    )
    bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                              billing_method="FEE_SCHEDULE")
    get_success_data(api.submit_fee_bill(bill["id"], make_field_adjuster_headers(ctx["adj_id"])))
    ctx["bill_id"] = bill["id"]
    return ctx


def test_bill_submit_advances_billing_status_only(api):
    """PRD 3.7: "Submission has two side effects: the assignment's billing dimension
    advances NOT_BILLED -> BILLED, and the claim's reserve_consumed_cents increases by
    the bill's total_cents."

    Design: Difficulty/non_linear_state_machine/assignment_parallel_dimensions
    """
    ctx = _submitted_bill_ctx(api)
    data = validate_success(api.get_assignment(ctx["asg_id"], DESK))
    assert data["billing_status"] == "BILLED"


def test_bill_submit_leaves_work_status_complete(api):
    """PRD 3.5: submitting a report advances "the parent assignment ... FIELDWORK ->
    WORK_COMPLETE". The billing dimension evolves independently (PRD 3.7 submit affects
    only the billing dimension), so the work dimension stays WORK_COMPLETE.

    Design: Difficulty/non_linear_state_machine/assignment_parallel_dimensions
    """
    ctx = _submitted_bill_ctx(api)
    data = validate_success(api.get_assignment(ctx["asg_id"], DESK))
    assert data["work_status"] == "WORK_COMPLETE"


# --------------------------------------------------------------------------
# Difficulty: reserve ledger conservation (submit + then void -> 0)
# --------------------------------------------------------------------------
def _submit_then_void_ctx(api):
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HAIL", policy_type="RCV",
        rcv_line_cents=5_000_000, depreciation_pct=0, with_fee_schedule=True,
    )
    bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                              billing_method="FEE_SCHEDULE")
    get_success_data(api.submit_fee_bill(bill["id"], make_field_adjuster_headers(ctx["adj_id"])))
    get_success_data(api.void_fee_bill(bill["id"], BILLING))
    ctx["bill_id"] = bill["id"]
    return ctx


def test_reserve_conserved_to_zero_after_void(api):
    """PRD 2.8: "A claim's reserve_consumed_cents equals the sum of total_cents over
    every fee bill on that claim whose status is SUBMITTED, APPROVED, or PAID ...
    Submitting a bill adds its total_cents to the claim's consumed reserve; rejecting or
    voiding a bill that had been counted subtracts it again."

    Design: Difficulty/compensating_invariant/reserve_ledger_conservation
    """
    ctx = _submit_then_void_ctx(api)
    data = validate_success(api.get_claim(ctx["claim_id"], DESK))
    assert data["reserve_consumed_cents"] == 0


def test_void_reverts_billing_and_marks_bill_void(api):
    """PRD 3.7: "if the voided bill had already debited the reserve — that is, its prior
    status was SUBMITTED or APPROVED — the void applies the same compensation, reverting
    the assignment to NOT_BILLED and subtracting the bill's total_cents from
    reserve_consumed_cents."

    Design: Difficulty/compensating_invariant/reserve_ledger_conservation
    """
    ctx = _submit_then_void_ctx(api)
    assignment = validate_success(api.get_assignment(ctx["asg_id"], DESK))
    bill = validate_success(api.get_fee_bill(ctx["bill_id"], DESK))
    assert assignment["billing_status"] == "NOT_BILLED"
    assert bill["status"] == "VOID"


# --------------------------------------------------------------------------
# Corner: TIME_AND_EXPENSE with zero time entries
# --------------------------------------------------------------------------
def test_te_bill_zero_time_entries_returns_no_time_entries(api):
    """PRD 3.6: "A time-and-expense bill additionally requires that the assignment have
    at least one logged time entry; creating one against an assignment with no entries
    is rejected with ERR_NO_TIME_ENTRIES."

    Design: Corner/validations/te_bill_zero_time_entries_returns_no_time_entries
    """
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HAIL", policy_type="RCV",
        rcv_line_cents=4_000_000, depreciation_pct=0, with_fee_schedule=True,
    )
    ver = fx.get_assignment_version(api, ctx["asg_id"], ctx["adj_id"])
    payload = create_fee_bill_payload(ctx["asg_id"], ctx["claim_id"], ctx["fs_id"],
                                      "TIME_AND_EXPENSE", ver)
    resp = api.create_fee_bill(payload, make_field_adjuster_headers(ctx["adj_id"]))
    validate_error(resp, "ERR_NO_TIME_ENTRIES")


# --------------------------------------------------------------------------
# Corner: pay a never-approved (DRAFT) bill
# --------------------------------------------------------------------------
def test_pay_unapproved_bill_returns_not_approved(api):
    """PRD 3.7: "Paying an APPROVED bill (otherwise ERR_FEE_BILL_NOT_APPROVED) is the
    settlement act."

    Design: Corner/state_machines/pay_unapproved_bill_returns_not_approved
    """
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HAIL", policy_type="RCV",
        rcv_line_cents=4_000_000, depreciation_pct=0, with_fee_schedule=True,
    )
    bill = fx.create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                              billing_method="FEE_SCHEDULE")  # DRAFT, never submitted/approved
    resp = api.pay_fee_bill(bill["id"], {"method": "ACH"}, BILLING)
    validate_error(resp, "ERR_FEE_BILL_NOT_APPROVED")


# --------------------------------------------------------------------------
# Corner: OCC stale assignment version on fee-bill create
# --------------------------------------------------------------------------
def test_occ_stale_assignment_version_on_fee_bill(api):
    """PRD 2.6: "A create-fee-bill request must carry expected_assignment_version ... If
    expected_assignment_version does not equal the assignment's current version, the
    request is rejected with ERR_STALE_ASSIGNMENT_VERSION (HTTP 412) ... fee-bill
    creation itself advances the assignment's version."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_assignment_version_on_fee_bill
    """
    ctx = fx.setup_work_complete_assignment(
        api, loss_state="FL", peril_type="HAIL", policy_type="RCV",
        rcv_line_cents=4_000_000, depreciation_pct=0, with_fee_schedule=True,
    )
    headers = make_field_adjuster_headers(ctx["adj_id"])
    v0 = fx.get_assignment_version(api, ctx["asg_id"], ctx["adj_id"])
    # First create with the correct version succeeds and bumps the assignment version.
    first = validate_success(api.create_fee_bill(
        create_fee_bill_payload(ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], "FEE_SCHEDULE", v0),
        headers), 201)
    assert first["status"] == "DRAFT"
    # Second create carrying the now-stale v0 is refused.
    resp = api.create_fee_bill(
        create_fee_bill_payload(ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], "FEE_SCHEDULE", v0),
        headers)
    validate_error(resp, "ERR_STALE_ASSIGNMENT_VERSION")
