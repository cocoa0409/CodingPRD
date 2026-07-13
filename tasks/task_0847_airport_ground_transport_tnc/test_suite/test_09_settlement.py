"""Monthly settlement: sum-then-round admin fee, empty-period WAV check, ledger
compensation, duplicate-period and swept-trip guards, and the settle payment step."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_operator_headers,
    set_clock, create_operator, register_vehicle, issue_permit, create_lot,
    queue_vehicle, dispatch_trip, transition_trip, setup_completed_trip,
    open_settlement, close_settlement, settle_settlement,
    create_settlement_payload,
)

AA = TEST_USERS["airport_authority_headers"]


def _limo_two_500_trips(api, clock, year, month):
    """One LIMO operator with two vehicles, each completing one off-peak non-WAV
    trip (fee 500). Returns (operator, open_statement)."""
    set_clock(api, clock)
    op = create_operator(api, operator_type="LIMO", legal_name="Lux Limo", activate=True)
    lot = create_lot(api, capacity=5)
    for plate, tag in (("L1", "AVI-L1"), ("L2", "AVI-L2")):
        v = register_vehicle(api, op["id"], plate=plate)
        issue_permit(api, v["id"], v["version"], avi_tag_id=tag, activate=True)
        queue_vehicle(api, op["id"], lot["id"], v["id"])
        t = dispatch_trip(api, op["id"], v["id"], lot["id"], trip_kind="PICKUP")
        transition_trip(api, op["id"], t["id"], "PICKUP")
        transition_trip(api, op["id"], t["id"], "COMPLETE")
    stmt = open_settlement(api, op["id"], year, month)
    return op, stmt


# --- combinatorial: admin fee sum-then-round ------------------------------
def test_settlement_admin_fee_sum_then_round(api):
    """PRD §2.8: "Per-trip rounding of the administrative fee is explicitly
    forbidden — the administrative fee is computed by summing the exact integer trip
    fees first and rounding only the single aggregate product."
    PRD §3.8: "`admin_fee_cents` as the gross multiplied by the administrative rate
    of 0.025 and rounded half-up once on that aggregate product (never per trip)"

    Design: Difficulty/combinatorial_formula/settlement_admin_fee_sum_then_round_mode_b
    """
    op, stmt = _limo_two_500_trips(api, "2026-05-01T12:00:00Z", 2026, 5)
    closed = close_settlement(api, stmt["id"])
    # gross 1000; round_half_up(1000 * 0.025) = round_half_up(25.0) = 25 (per-trip would give 26)
    assert closed["admin_fee_cents"] == 25, (
        f"sum-then-round admin fee should be 25, got {closed['admin_fee_cents']}"
    )


def test_settlement_gross_and_net_totals(api):
    """PRD §3.8: "`gross_fees_cents` as the exact integer sum of the swept trips'
    `final_fee_cents`"
    PRD §3.8: "The amount owed, `net_due_cents`, is the gross plus the
    administrative fee minus the wheelchair incentive credit."

    Design: Difficulty/combinatorial_formula/settlement_admin_fee_sum_then_round_mode_b
    """
    op, stmt = _limo_two_500_trips(api, "2026-05-01T12:00:00Z", 2026, 5)
    closed = close_settlement(api, stmt["id"])
    assert closed["gross_fees_cents"] == 1000, f"expected gross 1000, got {closed['gross_fees_cents']}"
    assert closed["net_due_cents"] == 1025, f"expected net 1025 (1000+25-0), got {closed['net_due_cents']}"
    assert closed["total_trip_count"] == 2, f"expected 2 swept trips, got {closed['total_trip_count']}"


# --- boundary/empty-set: close with zero trips ----------------------------
def test_settlement_close_zero_trips_totals_are_zero(api):
    """PRD §3.8: "Over the swept set the system computes `total_trip_count` as the
    number of swept trips, `wav_trip_count` as the number of those with
    `is_wheelchair_trip` true, `gross_fees_cents` as the exact integer sum of the
    swept trips' `final_fee_cents`, `admin_fee_cents` as the gross multiplied by the
    administrative rate of 0.025 and rounded half-up once on that aggregate product
    (never per trip), and `wav_incentive_credit_cents` as 50 cents times
    `wav_trip_count`."

    Design: Difficulty/boundary_precision_check/settlement_close_zero_trips_empty_set_no_wav_shortfall
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    op = create_operator(api, operator_type="SHUTTLE", legal_name="Zero Co",
                         wheelchair_pledge_pct=0.5, activate=True)
    stmt = open_settlement(api, op["id"], 2026, 7)
    closed = close_settlement(api, stmt["id"])
    assert closed["total_trip_count"] == 0, f"expected 0 trips, got {closed['total_trip_count']}"
    assert closed["gross_fees_cents"] == 0, f"expected gross 0, got {closed['gross_fees_cents']}"
    assert closed["net_due_cents"] == 0, f"expected net 0, got {closed['net_due_cents']}"


def test_settlement_close_zero_trips_issues_no_wav_shortfall(api):
    """PRD §3.8: "If the operator ran no trips in the period (`total_trip_count` is
    zero), no shortfall can exist and nothing is issued."

    Design: Difficulty/boundary_precision_check/settlement_close_zero_trips_empty_set_no_wav_shortfall
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    op = create_operator(api, operator_type="SHUTTLE", legal_name="Zero2 Co",
                         wheelchair_pledge_pct=0.5, activate=True)
    stmt = open_settlement(api, op["id"], 2026, 7)
    close_settlement(api, stmt["id"])
    _, meta = validate_paginated(api.list_violations(AA, params={"operator_id": op["id"]}))
    assert meta["total_count"] == 0, (
        f"a zero-trip close must issue no WAV_SHORTFALL; got {meta['total_count']} violations"
    )


# --- priority pair: state beats amount mismatch on SETTLE -----------------
def test_settle_open_statement_state_error_beats_amount_mismatch(api):
    """PRD §3.8: "a close or settle requested from an incompatible statement state
    is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/settle_state_beats_amount_mismatch
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    op = create_operator(api, operator_type="TAXI", legal_name="Pri Co", activate=True)
    stmt = open_settlement(api, op["id"], 2026, 6)  # OPEN, never closed
    resp = api.transition_settlement(
        stmt["id"], {"action": "SETTLE", "payment_amount_cents": 999}, make_operator_headers(op["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_settle_open_statement_state_error_regardless_of_amount(api):
    """PRD §3.8: "a close or settle requested from an incompatible statement state
    is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/settle_state_beats_amount_mismatch
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    op = create_operator(api, operator_type="TAXI", legal_name="Pri2 Co", activate=True)
    stmt = open_settlement(api, op["id"], 2026, 6)  # OPEN
    resp = api.transition_settlement(
        stmt["id"], {"action": "SETTLE", "payment_amount_cents": 0}, make_operator_headers(op["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# --- corner: duplicate period ---------------------------------------------
def test_duplicate_settlement_period_rejected(api):
    """PRD §3.8: "At most one statement may exist per operator-year-month: a second
    open request for the same `operator_id`, `period_year`, and `period_month` is
    rejected with `ERR_DUPLICATE_SETTLEMENT_PERIOD`."

    Design: Corner/validations/duplicate_settlement_period_returns_conflict
    """
    op = create_operator(api, operator_type="TAXI", legal_name="Per Co", activate=True)
    open_settlement(api, op["id"], 2026, 9)
    resp = api.create_settlement(create_settlement_payload(op["id"], 2026, 9), AA)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SETTLEMENT_PERIOD.value, 409)


# --- corner: void a swept trip --------------------------------------------
def test_void_swept_trip_rejected(api):
    """PRD §3.4: "the regulator may void an already-`COMPLETED` trip
    (`COMPLETED → VOIDED`), but only while the trip has not yet been swept into a
    statement — that is, only while its `settlement_statement_id` is null; a void
    attempted on a swept trip is rejected with `ERR_TRIP_ALREADY_SETTLED`."

    Design: Corner/validations/void_swept_trip_returns_trip_already_settled
    """
    ctx = setup_completed_trip(api, operator_type="TNC", clock="2026-08-01T12:00:00Z", avi_tag="AVI-SWV1")
    stmt = open_settlement(api, ctx["operator"]["id"], 2026, 8)
    close_settlement(api, stmt["id"])  # sweeps the trip -> sets settlement_statement_id
    resp = api.transition_trip(ctx["trip"]["id"], {"action": "VOID"}, AA)
    validate_error(resp, ApiErrorId.ERR_TRIP_ALREADY_SETTLED.value, 409)


# --- corner: settle exact amount ------------------------------------------
def test_settle_exact_amount_succeeds(api):
    """PRD §3.8: "Settling a closed statement (`CLOSED → SETTLED`) is the operator's
    payment step: it must carry a `payment_amount_cents` exactly equal to the
    statement's `net_due_cents`, or it is rejected with
    `ERR_SETTLEMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/settle_exact_amount_succeeds
    """
    ctx = setup_completed_trip(api, operator_type="TNC", clock="2026-08-02T12:00:00Z", avi_tag="AVI-PAV1")
    stmt = open_settlement(api, ctx["operator"]["id"], 2026, 8)
    closed = close_settlement(api, stmt["id"])
    # single off-peak TNC trip: gross 350, admin round_half_up(8.75)=9, net 359
    assert closed["net_due_cents"] == 359, f"expected net_due 359, got {closed['net_due_cents']}"
    settled = settle_settlement(api, ctx["operator"]["id"], stmt["id"], 359)
    assert settled["status"] == "SETTLED", f"expected SETTLED, got {settled['status']}"


# --- compensating invariant: outstanding fees complete-then-void ----------
def test_outstanding_fees_return_to_zero_after_void(api):
    """PRD §3.4: "Voiding compensates the ledger by recomputing the operator's
    `outstanding_fees_cents` to exclude that trip's final fee."

    Design: Difficulty/compensating_invariant/outstanding_fees_conserved_complete_then_void
    """
    ctx = setup_completed_trip(api, operator_type="TNC", clock="2026-05-15T12:00:00Z", avi_tag="AVI-LV1")
    voided = validate_success(api.transition_trip(ctx["trip"]["id"], {"action": "VOID"}, AA))
    assert voided["status"] == "VOIDED"
    assert voided["final_fee_cents"] == 350, f"expected final fee 350, got {voided['final_fee_cents']}"
    operator = validate_success(api.get_operator(ctx["operator"]["id"], AA))
    assert operator["outstanding_fees_cents"] == 0, (
        f"void should compensate outstanding fees back to 0, got {operator['outstanding_fees_cents']}"
    )


def test_outstanding_fees_reflect_completed_trip(api):
    """PRD §3.4: "Completing (`PICKED_UP → COMPLETED`) stamps `complete_ts`,
    computes and locks `final_fee_cents` using the final fee variant anchored on
    `pickup_ts`, adds that final fee into the operator's `outstanding_fees_cents`,
    and releases any of the trip's curb assignments still in `ACTIVE` status to
    `RELEASED`."

    Design: Difficulty/compensating_invariant/outstanding_fees_conserved_complete_then_void
    """
    ctx = setup_completed_trip(api, operator_type="TNC", clock="2026-05-15T12:00:00Z", avi_tag="AVI-LV2")
    assert ctx["trip"]["final_fee_cents"] == 350
    operator = validate_success(api.get_operator(ctx["operator"]["id"], AA))
    assert operator["outstanding_fees_cents"] == 350, (
        f"completed trip's final fee should sit in outstanding fees; expected 350, "
        f"got {operator['outstanding_fees_cents']}"
    )
