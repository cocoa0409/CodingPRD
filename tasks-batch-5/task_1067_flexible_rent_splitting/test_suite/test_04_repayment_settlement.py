"""Installment repayment, the retry loop, autopay, the flex fee, and settlement."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, create_scheduled_cycle, create_remitted_cycle,
    get_installments, charge_installment, find_ledger_entry,
    make_renter_headers, charge_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _sorted(insts):
    return sorted(insts, key=lambda i: i["sequence_no"])


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / flex_fee_provisional_vs_final_defer_cycle
# ---------------------------------------------------------------------------

def test_defer_provisional_fee_at_creation(api):
    """PRD §3.7: "in defer mode it is the deferred amount multiplied by a daily rate of 30
    basis points and by the number of defer days, divided by 10,000, with the result rounded
    half up to whole cents."
    PRD §3.7: "The provisional and final computations differ only in which defer-day count
    they use."

    Design: Difficulty/dual_variant_calc/flex_fee_provisional_vs_final_defer_cycle
    """
    set_clock("2026-07-01T00:00:00Z", api)
    ctx = create_scheduled_cycle(api, mode="DEFER", deferred_amount_cents=60000,
                                 planned_defer_days=20, unit_label="Maple #1")
    # LOW membership 1500 + split (2-1)*500 + round(60000*30*20/10000)=3600 -> 5600
    assert ctx["cycle"]["fee_provisional_cents"] == 5600


def test_defer_final_fee_and_refund_at_settle(api):
    """PRD §3.7: "The **final** fee, computed at settlement, uses the actual number of days
    the deferred installment was outstanding — the whole-day floor of the elapsed time from
    the cycle start date to the deferred installment's `paid_at`."
    PRD §3.7: "when the final fee is less than the provisional fee it appends a `FEE_REFUND`
    ledger entry for the negative of that shortfall (the provisional fee minus the final
    fee), then sets the cycle to `SETTLED`."

    Design: Difficulty/dual_variant_calc/flex_fee_provisional_vs_final_defer_cycle
    """
    set_clock("2026-07-01T00:00:00Z", api)
    ctx = create_remitted_cycle(api, mode="DEFER", deferred_amount_cents=60000,
                                planned_defer_days=20, unit_label="Maple #1b")
    insts = _sorted(ctx["installments"])
    charge_installment(insts[0]["id"], api, "MANUAL", "SUCCEED")  # immediate, day 0
    set_clock("2026-07-13T00:00:00Z", api)
    charge_installment(insts[1]["id"], api, "MANUAL", "SUCCEED")  # deferred, day 12
    data = validate_success(api.settle_cycle(ctx["cycle"]["id"], ADMIN))
    # actual defer_days 12 -> round(60000*30*12/10000)=2160 -> fee_final 4160
    assert data["fee_final_cents"] == 4160
    assert data["fee_provisional_cents"] == 5600
    assert data["status"] == "SETTLED"
    ledger = validate_success(api.list_cycle_ledger(ctx["cycle"]["id"], ADMIN))
    assert find_ledger_entry(ledger, "FEE_REFUND", -1440) is not None


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / settle_zero_outstanding_boundary
# ---------------------------------------------------------------------------

def test_settle_at_zero_outstanding_succeeds(api):
    """PRD §3.7: "Settlement requires that the cycle's `repaid_amount_cents` be at least its
    `portion_cents` — equivalently that `outstanding_cents` be zero or below, with the
    boundary case of exactly zero permitted; a settle attempted while any principal remains
    is rejected with `ERR_INSUFFICIENT_REPAYMENT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/settle_zero_outstanding_boundary
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #12")
    for inst in ctx["installments"]:
        charge_installment(inst["id"], api, "MANUAL", "SUCCEED")
    data = validate_success(api.settle_cycle(ctx["cycle"]["id"], ADMIN))
    assert data["status"] == "SETTLED"


def test_settle_zero_outstanding_amounts(api):
    """PRD §3.6: "The cycle's `outstanding_cents` is `portion_cents` minus that repaid
    amount — the principal the renter still owes."
    PRD §3.6: "The cycle's `repaid_amount_cents` is always the exact sum of the
    `amount_cents` of that cycle's installments whose `status` is either `PAID` or `WAIVED`".

    Design: Difficulty/boundary_precision_check/settle_zero_outstanding_boundary
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #12b")
    for inst in ctx["installments"]:
        charge_installment(inst["id"], api, "MANUAL", "SUCCEED")
    data = validate_success(api.settle_cycle(ctx["cycle"]["id"], ADMIN))
    assert data["outstanding_cents"] == 0
    assert data["repaid_amount_cents"] == 100000


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / installment_retry_cycle_scheduled_failed_scheduled
# ---------------------------------------------------------------------------

def test_retry_loop_returns_installment_to_failed(api):
    """PRD §3.6: "A failed charge moves the installment `SCHEDULED → FAILED` and increments
    `attempt_count` by one."
    PRD §3.6: "A `FAILED` installment can be re-armed for another attempt by the owning
    `Renter` or a `PlatformAdmin`, moving it `FAILED → SCHEDULED`, provided the attempt
    count is still below three".

    Design: Difficulty/non_linear_state_machine/installment_retry_cycle_scheduled_failed_scheduled
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #5")
    inst_id = _sorted(ctx["installments"])[0]["id"]
    charge_installment(inst_id, api, "MANUAL", "FAIL")
    validate_success(api.retry_installment(inst_id, ADMIN))
    data = validate_success(api.charge_installment(inst_id, charge_payload("MANUAL", "FAIL"), ADMIN))
    assert data["status"] == "FAILED"


def test_retry_loop_increments_attempt_count(api):
    """PRD §3.6: "A failed charge moves the installment `SCHEDULED → FAILED` and increments
    `attempt_count` by one."

    Design: Difficulty/non_linear_state_machine/installment_retry_cycle_scheduled_failed_scheduled
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #5b")
    inst_id = _sorted(ctx["installments"])[0]["id"]
    charge_installment(inst_id, api, "MANUAL", "FAIL")
    validate_success(api.retry_installment(inst_id, ADMIN))
    data = validate_success(api.charge_installment(inst_id, charge_payload("MANUAL", "FAIL"), ADMIN))
    assert data["attempt_count"] == 2


# ---------------------------------------------------------------------------
# Corner: state_machines / validations / cross_cutting
# ---------------------------------------------------------------------------

def test_retry_beyond_max_attempts_rejected(api):
    """PRD §3.6: "an installment whose `attempt_count` has reached three may not be charged
    or retried again, and such an attempt is rejected with `ERR_MAX_ATTEMPTS_EXCEEDED`
    (HTTP 409)."

    Design: Corner/state_machines/retry_beyond_max_attempts_rejected
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Oak #8")
    inst_id = _sorted(ctx["installments"])[0]["id"]
    charge_installment(inst_id, api, "MANUAL", "FAIL")
    validate_success(api.retry_installment(inst_id, ADMIN))
    charge_installment(inst_id, api, "MANUAL", "FAIL")
    validate_success(api.retry_installment(inst_id, ADMIN))
    charge_installment(inst_id, api, "MANUAL", "FAIL")  # attempt_count now 3, FAILED
    resp = api.retry_installment(inst_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MAX_ATTEMPTS_EXCEEDED.value, 409)


def test_charge_already_paid_installment_invalid_state(api):
    """PRD §3.6: "A successful charge moves the installment `SCHEDULED → PAID`".
    PRD §2.9: "then the target's state permitting the transition (`ERR_INVALID_STATE`,
    HTTP 409)".

    Design: Corner/state_machines/charge_already_paid_installment_invalid_state
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Oak #5")
    inst_id = _sorted(ctx["installments"])[0]["id"]
    charge_installment(inst_id, api, "MANUAL", "SUCCEED")
    resp = api.charge_installment(inst_id, charge_payload("MANUAL", "SUCCEED"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_settle_insufficient_repayment_returns_422(api):
    """PRD §3.7: "a settle attempted while any principal remains is rejected with
    `ERR_INSUFFICIENT_REPAYMENT` (HTTP 422)."

    Design: Corner/validations/settle_insufficient_repayment_returns_422
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Oak #12")
    inst_id = _sorted(ctx["installments"])[0]["id"]
    charge_installment(inst_id, api, "MANUAL", "SUCCEED")  # only one of two paid
    resp = api.settle_cycle(ctx["cycle"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REPAYMENT.value, 422)


def test_settle_before_remit_invalid_state(api):
    """PRD §3.7: "A `PlatformAdmin` settles a fully-repaid cycle, moving it
    `REMITTED → SETTLED`."
    PRD §2.9: "then the target's state permitting the transition (`ERR_INVALID_STATE`,
    HTTP 409)".

    Design: Corner/state_machines/settle_before_remit_invalid_state
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=2, unit_label="Oak #6")
    resp = api.settle_cycle(ctx["cycle"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_autopay_charge_paused_mandate_returns_409(api):
    """PRD §3.6: "When the `method` is autopay, the renter's autopay mandate must be
    `ACTIVE`, or the charge is rejected with `ERR_AUTOPAY_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/cross_cutting/autopay_charge_paused_mandate_returns_409
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Oak #16")
    inst_id = _sorted(ctx["installments"])[0]["id"]
    resp = api.charge_installment(inst_id, {"method": "AUTOPAY"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_AUTOPAY_NOT_ACTIVE.value, 409)


def test_autopay_mandate_activate_then_pause_toggle(api):
    """PRD §3.3: "Activating a mandate — the `PAUSED → ACTIVE` transition — requires that a
    non-null `method_ref` be present; the renter's `autopay_enabled` flag then becomes true."
    PRD §3.3: "Pausing an active mandate — `ACTIVE → PAUSED` — sets `autopay_enabled` back
    to false, and the mandate can be re-activated later, so `PAUSED` and `ACTIVE` form a
    cycle."

    Design: Corner/cross_cutting/autopay_mandate_activate_then_pause_toggle
    """
    from test_helpers import create_enrolled_renter
    ctx = create_enrolled_renter(api, unit_label="Oak #17")
    renter_id = ctx["renter"]["id"]
    rh = make_renter_headers(renter_id)
    mandate = validate_success(api.get_renter_mandate(renter_id, ADMIN))[0]
    validate_success(api.update_mandate(
        mandate["id"], {"status": "ACTIVE", "method_ref": "pm_123"}, rh))
    renter_after_active = validate_success(api.get_renter(renter_id, ADMIN))
    assert renter_after_active["autopay_enabled"] is True
    paused = validate_success(api.update_mandate(mandate["id"], {"status": "PAUSED"}, rh))
    renter_after_pause = validate_success(api.get_renter(renter_id, ADMIN))
    assert renter_after_pause["autopay_enabled"] is False
    assert paused["status"] == "PAUSED"
