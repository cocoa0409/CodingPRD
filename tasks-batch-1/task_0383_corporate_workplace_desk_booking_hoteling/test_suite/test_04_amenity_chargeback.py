"""Amenity chargeback: provisional-vs-final divergence, pinned-order arithmetic
(per-line rounding, fee-inclusive discount tier), the approve/cancel monetary
conservation invariant, immediate consistency, and the post-completion lock.

Translates queue-A difficulty rules `dual_variant_calc` (amenity variant),
`combinatorial_formula`, `compensating_invariant` (chargeback variant), and
queue-B Corner `consistency_model` / `errors` instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_employee_headers,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["facility_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty A: dual_variant_calc — provisional vs final
# ---------------------------------------------------------------------------
def test_provisional_chargeback_counts_requested_and_approved(api):
    """PRD §3.5: "The provisional variant selects every line whose line_status is
    REQUESTED or APPROVED, and its result is written to
    provisional_chargeback_cents; it is recomputed on each line change while the
    reservation is open."

    Design: Difficulty/dual_variant_calc/amenity_chargeback_provisional_vs_final_diverge
    """
    # line A 40000 APPROVED + line B 40000 still REQUESTED
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "MONITOR", "unit_price_cents": 40000, "quantity": 1, "approve": True},
         {"code": "PARKING", "unit_price_cents": 40000, "quantity": 1, "approve": False}],
        booking_date="2026-06-20", level=1)
    emp_id = env["employee"]["id"]
    data = get_success_data(api.get_reservation(resv["id"], make_employee_headers(emp_id)))
    # provisional set = {A, B}: subtotal 80000, per-line fee 3400 each = 6800,
    # pre 86800, tier >=1000 -> 10%, discount 8680, total 78120
    assert data["provisional_chargeback_cents"] == 78120


def test_final_chargeback_counts_only_approved_and_diverges(api):
    """PRD §3.5: "The final variant selects only lines whose line_status is
    APPROVED (any line still merely REQUESTED at completion is excluded), and its
    result is frozen into final_chargeback_cents at completion and never
    recomputed thereafter."
    PRD §3.7: "If at completion the reservation's billing_status is PROVISIONAL,
    completion also advances billing_status to FINALIZED and freezes
    final_chargeback_cents using the final variant of the chargeback calculation,
    over approved lines only."

    Design: Difficulty/dual_variant_calc/amenity_chargeback_provisional_vs_final_diverge
    """
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "MONITOR", "unit_price_cents": 40000, "quantity": 1, "approve": True},
         {"code": "PARKING", "unit_price_cents": 40000, "quantity": 1, "approve": False}],
        booking_date="2026-06-20", level=101)
    emp_id = env["employee"]["id"]
    completed = fx.complete_reservation(resv["id"], emp_id)
    # final set = {A only}: subtotal 40000, fee 3400, pre 43400, 10%, disc 4340,
    # total 39060; provisional remains 78120 -> the two diverge
    assert completed["final_chargeback_cents"] == 39060
    assert completed["provisional_chargeback_cents"] == 78120
    assert completed["final_chargeback_cents"] != completed["provisional_chargeback_cents"]
    assert completed["billing_status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Difficulty A: combinatorial_formula — per-line round then sum (mode b)
# ---------------------------------------------------------------------------
def test_fee_rounded_per_line_then_summed_final(api):
    """PRD §3.5: "For each individual line amount, compute a service fee of that
    amount multiplied by the service-fee rate of 0.085 (8.5 percent), rounding
    the per-line result half up to a whole cent. The rounding happens per line,
    before any summing." ... "The total fee is the sum of those per-line rounded
    fees."

    Design: Difficulty/combinatorial_formula/amenity_fee_round_per_line_then_sum_mode_b
    """
    # APPROVED lines (125x1),(255x1),(75x3): line amounts 125,255,225;
    # per-line fees 11,22,19 -> sum 52; subtotal 605; pre 657; 5% tier;
    # discount 33; final 624
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "A", "unit_price_cents": 125, "quantity": 1, "approve": True},
         {"code": "B", "unit_price_cents": 255, "quantity": 1, "approve": True},
         {"code": "C", "unit_price_cents": 75, "quantity": 3, "approve": True}],
        booking_date="2026-06-22", level=3)
    emp_id = env["employee"]["id"]
    completed = fx.complete_reservation(resv["id"], emp_id)
    assert completed["final_chargeback_cents"] == 624


def test_provisional_matches_per_line_rounding_before_completion(api):
    """PRD §3.5: "The provisional variant selects every line whose line_status is
    REQUESTED or APPROVED, and its result is written to
    provisional_chargeback_cents". (same pinned per-line-then-sum arithmetic, all
    three lines APPROVED so the provisional set equals the final set)

    Design: Difficulty/combinatorial_formula/amenity_fee_round_per_line_then_sum_mode_b
    """
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "A", "unit_price_cents": 125, "quantity": 1, "approve": True},
         {"code": "B", "unit_price_cents": 255, "quantity": 1, "approve": True},
         {"code": "C", "unit_price_cents": 75, "quantity": 3, "approve": True}],
        booking_date="2026-06-22", level=31)
    emp_id = env["employee"]["id"]
    # before completion the provisional total over all three APPROVED lines is 624
    data = get_success_data(api.get_reservation(resv["id"], make_employee_headers(emp_id)))
    assert data["provisional_chargeback_cents"] == 624


# ---------------------------------------------------------------------------
# Difficulty A: combinatorial_formula — fee-inclusive discount tier (mode c)
# ---------------------------------------------------------------------------
def test_discount_tier_keyed_on_fee_inclusive_total_final(api):
    """PRD §3.5: "The pre-discount total is the subtotal plus the total fee. A
    volume discount percentage is selected from the pre-discount total: a
    pre-discount total of at most 499 cents earns 0 percent; a pre-discount total
    from 500 through 999 cents inclusive earns 5 percent". ... "The order matters
    because the discount tier is keyed on the pre-discount total, which already
    includes the fee, so the fee must be computed before the discount is
    selected."

    Design: Difficulty/combinatorial_formula/amenity_discount_tier_keyed_on_fee_inclusive_total_mode_c
    """
    # single APPROVED line 160x3 -> subtotal 480 (<500), fee 41 pushes pre to 521
    # crossing into the 5% tier; discount 26; final 495
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "CATERING", "unit_price_cents": 160, "quantity": 3, "approve": True}],
        booking_date="2026-06-23", level=4)
    emp_id = env["employee"]["id"]
    completed = fx.complete_reservation(resv["id"], emp_id)
    assert completed["final_chargeback_cents"] == 495


def test_fee_inclusive_total_provisional_before_completion(api):
    """PRD §3.5: "The pre-discount total is the subtotal plus the total fee. ...
    The order matters because the discount tier is keyed on the pre-discount
    total, which already includes the fee, so the fee must be computed before the
    discount is selected." (provisional total over the single APPROVED line)

    Design: Difficulty/combinatorial_formula/amenity_discount_tier_keyed_on_fee_inclusive_total_mode_c
    """
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "CATERING", "unit_price_cents": 160, "quantity": 3, "approve": True}],
        booking_date="2026-06-23", level=41)
    emp_id = env["employee"]["id"]
    data = get_success_data(api.get_reservation(resv["id"], make_employee_headers(emp_id)))
    assert data["provisional_chargeback_cents"] == 495


# ---------------------------------------------------------------------------
# Difficulty A: compensating_invariant — approve/cancel conserves cents
# ---------------------------------------------------------------------------
def test_amenity_approve_then_cancel_restores_provisional(api):
    """PRD §3.5: "Every line change — creation of a subsequent line, approval,
    denial, or cancellation — re-derives the parent reservation's running
    provisional_chargeback_cents."

    Design: Difficulty/compensating_invariant/amenity_approve_then_cancel_conserves_provisional_chargeback
    """
    # baseline: one APPROVED 1000c line -> subtotal 1000, fee 85, pre 1085,
    # tier >=1000 -> 10%, discount round(108.5)=109, provisional 976
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "MONITOR", "unit_price_cents": 1000, "quantity": 1, "approve": True}],
        booking_date="2026-07-09", start_minute=540, end_minute=1080, level=18)
    emp_id = env["employee"]["id"]
    base = get_success_data(api.get_reservation(resv["id"], make_employee_headers(emp_id)))
    assert base["provisional_chargeback_cents"] == 976
    # add a second line, approve it, then cancel it -> total must return to 976
    l2 = fx.add_amenity_line(resv["id"], emp_id, "PARKING", 500, 1)
    fx.approve_amenity_line(l2["id"])
    cancelled = get_success_data(api.cancel_amenity(l2["id"], make_employee_headers(emp_id)))
    assert cancelled["line_status"] == "CANCELLED"
    after = get_success_data(api.get_reservation(resv["id"], make_employee_headers(emp_id)))
    assert after["provisional_chargeback_cents"] == 976


def test_amenity_cancel_marks_line_cancelled(api):
    """PRD §3.5: "An Employee may instead CANCELLED their own line, from either
    REQUESTED or APPROVED".

    Design: Difficulty/compensating_invariant/amenity_approve_then_cancel_conserves_provisional_chargeback
    """
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "MONITOR", "unit_price_cents": 1000, "quantity": 1, "approve": True}],
        booking_date="2026-07-09", start_minute=540, end_minute=1080, level=181)
    emp_id = env["employee"]["id"]
    l2 = fx.add_amenity_line(resv["id"], emp_id, "PARKING", 500, 1)
    fx.approve_amenity_line(l2["id"])
    cancelled = get_success_data(api.cancel_amenity(l2["id"], make_employee_headers(emp_id)))
    assert cancelled["line_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Corner: consistency_model — immediate visibility
# ---------------------------------------------------------------------------
def test_amenity_total_visible_immediately(api):
    """PRD §3.5: "Every line change — creation of a subsequent line, approval,
    denial, or cancellation — re-derives the parent reservation's running
    provisional_chargeback_cents."
    PRD §3.5: "Adding the first line to a reservation whose billing_status is NONE
    advances that reservation to billing_status PROVISIONAL".

    Design: Corner/consistency_model/immediate_consistency_amenity_total_visible_same_request
    """
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "MONITOR", "unit_price_cents": 1000, "quantity": 1, "approve": True}],
        booking_date="2026-08-22", start_minute=540, end_minute=600, level=25)
    emp_id = env["employee"]["id"]
    data = get_success_data(api.get_reservation(resv["id"], make_employee_headers(emp_id)))
    assert data["provisional_chargeback_cents"] == 976
    assert data["billing_status"] == "PROVISIONAL"


# ---------------------------------------------------------------------------
# Corner: errors — amenity locked after completion
# ---------------------------------------------------------------------------
def test_cancel_approved_amenity_after_completion_locked(api):
    """PRD §3.5: "cancelling an APPROVED line is forbidden once the parent
    reservation has reached COMPLETED, since the chargeback is by then frozen, and
    such an attempt is rejected with ERR_AMENITY_LOCKED (HTTP 409)."

    Design: Corner/errors/amenity_locked_cancel_after_completion
    """
    env, resv, lines = fx.setup_reservation_with_amenity_lines(
        [{"code": "MONITOR", "unit_price_cents": 1000, "quantity": 1, "approve": True}],
        booking_date="2026-08-16", start_minute=540, end_minute=600, level=19)
    emp_id = env["employee"]["id"]
    fx.complete_reservation(resv["id"], emp_id)
    resp = api.cancel_amenity(lines[0]["id"], make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_AMENITY_LOCKED)
