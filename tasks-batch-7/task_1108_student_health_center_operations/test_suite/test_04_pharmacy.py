"""Pharmacy claims: dispense state machine (partial self-loop, terminal
cancel lockout), stock decrements, the boundary-inclusive reorder flag,
dispense/restock conservation, validation-order priority, and existence
checking (PRD §2.7, §2.9, §3.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_prescription,
    dispense_payload,
    get_stock_by_code,
    restock_payload,
    set_clock,
    setup_encounter_with_prescription,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Corner: full invalid-transition matrix on one encounter
# ---------------------------------------------------------------------------

def test_prescription_invalid_transition_matrix(api, clinician_headers,
                                                pharmacist_headers):
    """PRD §3.6: "attempting to cancel one already partly dispensed is rejected
    with `ERR_PRESCRIPTION_NOT_CANCELLABLE`".
    PRD §3.6: "the quantity must be positive (`ERR_INVALID_QUANTITY`); it must
    not exceed the units still outstanding — that is, `quantity_prescribed`
    minus `quantity_dispensed` (`ERR_DISPENSE_QUANTITY_EXCEEDS`); and the
    medication stock must hold at least that many units on hand
    (`ERR_INSUFFICIENT_STOCK`)."

    Design: Corner/state_machines/prescription_invalid_transition_matrix
    """
    set_clock("2026-05-01T00:00:00Z")
    student, provider, appt, enc, stock, rx1 = setup_encounter_with_prescription(
        stock_code="MTRX", initial_on_hand=10, reorder_threshold=0,
        quantity=5, external_ref="S14",
    )
    # rx1 -> PARTIALLY_DISPENSED (2 of 5); stock on_hand 10 -> 8.
    partial = validate_success(
        api.dispense_prescription(rx1["id"], dispense_payload(2), pharmacist_headers),
        200,
    )
    assert partial["status"] == "PARTIALLY_DISPENSED"
    assert partial["quantity_dispensed"] == 2

    rx2 = validate_success(
        api.create_prescription(enc["id"], {"medication_stock_id": stock["id"],
                                            "quantity": 20}, clinician_headers),
        201,
    )
    rx3 = validate_success(
        api.create_prescription(enc["id"], {"medication_stock_id": stock["id"],
                                            "quantity": 5}, clinician_headers),
        201,
    )

    # Cancel from PARTIALLY_DISPENSED is locked out.
    res1 = api.cancel_prescription(rx1["id"], clinician_headers)
    validate_error(res1, ApiErrorId.ERR_PRESCRIPTION_NOT_CANCELLABLE, expected_status=409)

    # 4 > remaining 3 on rx1.
    res2 = api.dispense_prescription(rx1["id"], dispense_payload(4), pharmacist_headers)
    validate_error(res2, ApiErrorId.ERR_DISPENSE_QUANTITY_EXCEEDS, expected_status=422)

    # 20 > on_hand 8 for rx2 (20 <= 20 prescribed, so the stock gate fires).
    res3 = api.dispense_prescription(rx2["id"], dispense_payload(20), pharmacist_headers)
    validate_error(res3, ApiErrorId.ERR_INSUFFICIENT_STOCK, expected_status=409)

    # Zero quantity is invalid.
    res4 = api.dispense_prescription(rx3["id"], dispense_payload(0), pharmacist_headers)
    validate_error(res4, ApiErrorId.ERR_INVALID_QUANTITY, expected_status=422)


def test_existence_checked_before_state(api, pharmacist_headers):
    """PRD §2.7: "Each identifier in the path is resolved in order, and the
    request is rejected with `ERR_NOT_FOUND` at the first identifier that does
    not correspond to an existing resource, before any later identifier is
    examined and before any body validation runs."

    Design: Corner/validations/existence_checked_before_state
    """
    res = api.dispense_prescription(NON_EXISTENT_UUID, dispense_payload(1),
                                    pharmacist_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


# ---------------------------------------------------------------------------
# Depth probes: PARTIALLY_DISPENSED -> PARTIALLY_DISPENSED self-loop
# ---------------------------------------------------------------------------

def test_partial_dispense_self_loop_repeats(api, pharmacist_headers):
    """PRD §3.6: "short of that it sits in `PARTIALLY_DISPENSED`, where further
    dispenses remain legal under the same four rules."
    PRD §3.6: "A successful dispense adds the quantity to `quantity_dispensed`,
    subtracts it from the stock's `on_hand`, and recomputes `needs_reorder`."

    Design: Difficulty/non_linear_state_machine/prescription_partial_dispense_self_loop
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, _, rx = setup_encounter_with_prescription(
        stock_code="AMOX500", initial_on_hand=100, reorder_threshold=5,
        quantity=5, external_ref="S410",
    )
    first = validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(2), pharmacist_headers), 200
    )
    assert first["status"] == "PARTIALLY_DISPENSED"
    assert first["quantity_dispensed"] == 2

    second = validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(2), pharmacist_headers), 200
    )
    assert_prescription(second)
    assert second["status"] == "PARTIALLY_DISPENSED", (
        "the self-loop must revisit PARTIALLY_DISPENSED, not advance to DISPENSED"
    )
    assert second["quantity_dispensed"] == 4


def test_partial_dispense_completes_at_prescribed_total(api, pharmacist_headers):
    """PRD §3.6: "When the dispensed total reaches the prescribed total the
    prescription becomes `DISPENSED`".

    Design: Difficulty/non_linear_state_machine/prescription_partial_dispense_self_loop
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, _, rx = setup_encounter_with_prescription(
        stock_code="AMOX500", initial_on_hand=100, reorder_threshold=5,
        quantity=5, external_ref="S410",
    )
    validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(2), pharmacist_headers), 200
    )
    validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(2), pharmacist_headers), 200
    )
    final = validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(1), pharmacist_headers), 200
    )
    assert final["status"] == "DISPENSED"
    assert final["quantity_dispensed"] == 5


# ---------------------------------------------------------------------------
# Depth probes: state-machine error (step 5) beats fiscal error (step 10)
# ---------------------------------------------------------------------------

def _setup_cancelled_rx_with_thin_stock():
    set_clock("2026-05-01T00:00:00Z")
    student, provider, appt, enc, stock, rx = setup_encounter_with_prescription(
        stock_code="RARE1", initial_on_hand=1, reorder_threshold=0,
        quantity=5, external_ref="S600",
    )
    return stock, rx


def test_dispense_cancelled_prescription_reports_state_error(api, clinician_headers,
                                                             pharmacist_headers):
    """PRD §2.9: "the error the caller sees is determined by a fixed evaluation
    order" — "5. **State-machine preconditions** — the target resource is not in
    the state the action requires ... rejected with the transition's specific
    `409` error." precedes "10. **Fiscal gates** — ... stock sufficiency and
    quantity bounds ... These are checked last."
    PRD §3.6: "the prescription must be `WRITTEN` or `PARTIALLY_DISPENSED`
    (`ERR_PRESCRIPTION_NOT_DISPENSABLE`)".

    Design: Difficulty/priority_pair_validation_conflict/dispense_state_beats_stock_fiscal
    """
    stock, rx = _setup_cancelled_rx_with_thin_stock()
    validate_success(api.cancel_prescription(rx["id"], clinician_headers), 200)

    # quantity 5 violates both the state rule (CANCELLED) and the stock rule
    # (5 > on_hand 1); the state-machine error must win.
    res = api.dispense_prescription(rx["id"], dispense_payload(5), pharmacist_headers)
    validate_error(res, ApiErrorId.ERR_PRESCRIPTION_NOT_DISPENSABLE, expected_status=409)


def test_rejected_dispense_mutates_nothing(api, clinician_headers, pharmacist_headers):
    """PRD §3.6: "A successful dispense adds the quantity to
    `quantity_dispensed`, subtracts it from the stock's `on_hand`" — a dispense
    rejected with `ERR_PRESCRIPTION_NOT_DISPENSABLE` (PRD §3.6) applies none of
    those effects.

    Design: Difficulty/priority_pair_validation_conflict/dispense_state_beats_stock_fiscal
    """
    stock, rx = _setup_cancelled_rx_with_thin_stock()
    cancelled = validate_success(api.cancel_prescription(rx["id"], clinician_headers), 200)
    assert cancelled["status"] == "CANCELLED"

    res = api.dispense_prescription(rx["id"], dispense_payload(5), pharmacist_headers)
    validate_error(res, ApiErrorId.ERR_PRESCRIPTION_NOT_DISPENSABLE, expected_status=409)

    rx_after = validate_success(api.get_prescription(rx["id"], pharmacist_headers), 200)
    assert rx_after["status"] == "CANCELLED"
    assert rx_after["quantity_dispensed"] == 0
    stock_after = get_stock_by_code("RARE1")
    assert stock_after["on_hand"] == 1, "rejected dispense must not decrement stock"


# ---------------------------------------------------------------------------
# Depth probes: boundary precision — dispensing exactly on_hand empties stock
# ---------------------------------------------------------------------------

def test_dispense_exactly_on_hand_succeeds(api, pharmacist_headers):
    """PRD §3.6: "the medication stock must hold at least that many units on
    hand (`ERR_INSUFFICIENT_STOCK`)" — a quantity exactly equal to on_hand
    satisfies "at least that many", so the dispense succeeds and "the dispensed
    total reaches the prescribed total the prescription becomes `DISPENSED`".

    Design: Difficulty/boundary_precision_check/dispense_exactly_on_hand_empties_stock
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, _, rx = setup_encounter_with_prescription(
        stock_code="CIPRO", initial_on_hand=10, reorder_threshold=4,
        quantity=10, external_ref="S700",
    )
    dispensed = validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(10), pharmacist_headers),
        200,
    )
    assert dispensed["status"] == "DISPENSED"
    assert dispensed["quantity_dispensed"] == 10


def test_dispense_exactly_on_hand_flags_reorder(api, pharmacist_headers):
    """PRD §3.6: "it is true exactly when `on_hand` is less than or equal to
    `reorder_threshold`. The comparison is boundary-inclusive — a stock sitting
    precisely at its threshold is already flagged."

    Design: Difficulty/boundary_precision_check/dispense_exactly_on_hand_empties_stock
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, _, rx = setup_encounter_with_prescription(
        stock_code="CIPRO", initial_on_hand=10, reorder_threshold=4,
        quantity=10, external_ref="S700",
    )
    validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(10), pharmacist_headers),
        200,
    )
    stock = get_stock_by_code("CIPRO")
    assert stock["on_hand"] == 0
    assert stock["needs_reorder"] is True, "0 <= 4 must flag reorder (boundary inclusive)"


# ---------------------------------------------------------------------------
# Depth probes: dispense cascade recomputes the reorder flag (depth-2 chain)
# ---------------------------------------------------------------------------

def test_dispense_decrements_stock_and_lands_on_threshold(api, pharmacist_headers):
    """PRD §3.6: "A successful dispense adds the quantity to
    `quantity_dispensed`, subtracts it from the stock's `on_hand`, and
    recomputes `needs_reorder`." and "When the dispensed total reaches the
    prescribed total the prescription becomes `DISPENSED`".

    Design: Difficulty/transitive_cascade/dispense_decrement_to_reorder_flag
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, _, rx = setup_encounter_with_prescription(
        stock_code="IBU200", initial_on_hand=10, reorder_threshold=4,
        quantity=6, external_ref="S501",
    )
    dispensed = validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(6), pharmacist_headers), 200
    )
    assert dispensed["status"] == "DISPENSED"
    assert dispensed["quantity_dispensed"] == 6


def test_dispense_cascade_sets_needs_reorder_at_inclusive_boundary(api, pharmacist_headers):
    """PRD §3.6: "it is true exactly when `on_hand` is less than or equal to
    `reorder_threshold`" — dispensing 6 from 10 leaves on_hand 4 == threshold 4,
    which must flag reorder.

    Design: Difficulty/transitive_cascade/dispense_decrement_to_reorder_flag
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, _, rx = setup_encounter_with_prescription(
        stock_code="IBU200", initial_on_hand=10, reorder_threshold=4,
        quantity=6, external_ref="S501",
    )
    validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(6), pharmacist_headers), 200
    )
    stock = get_stock_by_code("IBU200")
    assert stock["on_hand"] == 4
    assert stock["needs_reorder"] is True, "4 <= 4 must flag reorder (boundary inclusive)"


# ---------------------------------------------------------------------------
# Depth probes: dispense then restock conserves physical units
# ---------------------------------------------------------------------------

def test_dispense_subtracts_units_from_on_hand(api, pharmacist_headers):
    """PRD §3.6: the live `on_hand` "starts equal to `initial_on_hand`, grows
    with each restock, and shrinks with each dispense, and is never allowed to
    go negative."

    Design: Difficulty/compensating_invariant/stock_dispense_then_restock_conserves_units
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, _, rx = setup_encounter_with_prescription(
        stock_code="DOXY", initial_on_hand=50, reorder_threshold=0,
        quantity=20, external_ref="S1000",
    )
    dispensed = validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(20), pharmacist_headers),
        200,
    )
    assert dispensed["status"] == "DISPENSED"
    stock = get_stock_by_code("DOXY")
    assert stock["on_hand"] == 30, "50 - 20 dispensed must leave 30 on hand"


def test_restock_after_dispense_restores_on_hand_exactly(api, pharmacist_headers):
    """PRD §3.6: restocking — "the stock's `on_hand` grows by that amount, and
    `needs_reorder` is recomputed against the new level" — so dispense 20 then
    restock 20 against an initial 50 conserves the unit invariant with zero
    drift (on_hand == initial + restocked - dispensed == 50).

    Design: Difficulty/compensating_invariant/stock_dispense_then_restock_conserves_units
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, stock, rx = setup_encounter_with_prescription(
        stock_code="DOXY", initial_on_hand=50, reorder_threshold=0,
        quantity=20, external_ref="S1000",
    )
    validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(20), pharmacist_headers),
        200,
    )
    restocked = validate_success(
        api.restock_medication_stock(stock["id"], restock_payload(20),
                                     pharmacist_headers),
        200,
    )
    assert restocked["on_hand"] == 50, (
        f"invariant 50 == 50 (initial) + 20 (restocked) - 20 (dispensed); "
        f"got {restocked['on_hand']}"
    )
    assert restocked["needs_reorder"] is False


# ---------------------------------------------------------------------------
# Corner: reorder flag boundary walk
# ---------------------------------------------------------------------------

def test_stock_reorder_flag_boundary_walk(api, pharmacist_headers):
    """PRD §3.6: "`needs_reorder` is recomputed after every stock movement: it
    is true exactly when `on_hand` is less than or equal to `reorder_threshold`.
    The comparison is boundary-inclusive — a stock sitting precisely at its
    threshold is already flagged."

    Design: Corner/calculations/stock_reorder_flag_boundary_walk
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, stock, rx = setup_encounter_with_prescription(
        stock_code="FLAG1", initial_on_hand=5, reorder_threshold=4,
        quantity=1, external_ref="S42",
    )
    assert stock["on_hand"] == 5
    assert stock["needs_reorder"] is False, "5 > 4 must not flag at creation"

    validate_success(
        api.dispense_prescription(rx["id"], dispense_payload(1), pharmacist_headers),
        200,
    )
    at_threshold = get_stock_by_code("FLAG1")
    assert at_threshold["on_hand"] == 4
    assert at_threshold["needs_reorder"] is True, "4 <= 4 flags (boundary inclusive)"

    restocked = validate_success(
        api.restock_medication_stock(stock["id"], restock_payload(1), pharmacist_headers),
        200,
    )
    assert restocked["on_hand"] == 5
    assert restocked["needs_reorder"] is False, "5 > 4 clears the flag again"
