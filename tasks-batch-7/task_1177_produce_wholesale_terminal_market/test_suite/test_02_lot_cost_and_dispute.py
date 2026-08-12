"""Lot cost accounting (provisional vs final) and the grade-dispute cycle (PRD §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    certify_inspection,
    create_accepted_lot,
    create_disputed_lot,
    create_ordered_lot,
    file_inspection,
    get_lot,
    get_success_data,
    receive_lot,
    resolve_dispute,
    setup_accepted_lot,
    setup_lot_with_certified_defect,
    setup_market_day,
    validate_error,
    validate_success,
)
from test_helpers import (
    ADMIN_HEADERS,
    INSPECTOR_HEADERS,
    NON_EXISTENT_UUID,
    RECEIVER_HEADERS,
)


def test_lot_provisional_cost_set_at_creation(api):
    """PRD §3.2: "At creation the server computes the **provisional landed cost**:
    `provisional_cost_cents` is `quantity_units` multiplied by `shipper_unit_price`
    multiplied by 100, rounded half-up to integer cents."
    PRD §3.2: "Until a final-cost event runs, both `adjusted_cost_cents` and
    `payable_cents` are initialized equal to `provisional_cost_cents`."

    Design: Difficulty/dual_variant_calc/lot_landed_cost_provisional_vs_final_on_inspection
    """
    base = setup_lot_with_certified_defect(defect_pct=20, quantity=100, unit_price=10.00)
    # Re-fetch history is impossible; instead rebuild the pre-certify observation by
    # creating a fresh identical lot that has NOT been certified yet.
    fresh = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                               quantity_units=100, shipper_unit_price=10.00)
    assert fresh["provisional_cost_cents"] == 100000
    assert fresh["adjusted_cost_cents"] == 100000
    assert fresh["payable_cents"] == 100000
    # And the certified lot proves the FINAL variant diverged on identical inputs.
    assert base["lot"]["provisional_cost_cents"] == 100000
    assert base["lot"]["adjusted_cost_cents"] == 85000


def test_lot_final_cost_after_certified_pass_with_defect(api):
    """PRD §3.4: "if the certified `defect_pct` is less than or equal to 5,
    `adjusted_cost_cents` remains equal to `provisional_cost_cents`; otherwise the
    defect-discount formula applies."
    PRD §3.4: "The defect-discount formula computes a final unit price by taking the
    shipper's unit price, multiplying it by one minus the excess-defect fraction
    (the excess being `defect_pct` minus 5, divided by 100), rounding that unit price
    half-up to four decimal places, then multiplying by `quantity_units` and by 100
    and rounding half-up to integer cents to obtain the new `adjusted_cost_cents`."
    PRD §3.4: "`payable_cents` is then recomputed as `adjusted_cost_cents` minus the
    sum of `ISSUED` credit memos on the lot, and the shipper's `trust_exposure_cents`
    is recomputed."

    Design: Difficulty/dual_variant_calc/lot_landed_cost_provisional_vs_final_on_inspection
    """
    base = setup_lot_with_certified_defect(defect_pct=20, quantity=100, unit_price=10.00)
    lot = base["lot"]
    assert lot["status"] == "ACCEPTED"
    # final_unit = round_half_up(10.00 * (1 - (20-5)/100), 4) = 8.5000
    # adjusted   = round_half_up(100 * 8.5000 * 100) = 85000
    assert lot["provisional_cost_cents"] == 100000, "provisional never rewrites"
    assert lot["adjusted_cost_cents"] == 85000
    assert lot["payable_cents"] == 85000
    assert lot["provisional_cost_cents"] != lot["adjusted_cost_cents"], (
        "identical lot inputs must diverge across the provisional and final variants")


def test_fail_certification_keeps_lot_inspected_then_dispute_opens(api):
    """PRD §3.4: "When the result is `FAIL`, the inspection still becomes `CERTIFIED`,
    but the lot remains `INSPECTED`; the dispute itself is a separate `Receiver`
    action, not an automatic transition."
    PRD §3.4: "A `Receiver` opens a grade/pack dispute on an `INSPECTED` lot only when
    a `CERTIFIED` inspection with `result` equal to `FAIL` exists for that lot."

    Design: Difficulty/non_linear_state_machine/purchase_lot_dispute_reinspection_cycle
    """
    base = setup_market_day()
    lot = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"])
    receive_lot(lot["id"])
    inspection = file_inspection(lot["id"], inspected_grade="US2", defect_pct=25,
                                 result="FAIL")
    certified = certify_inspection(inspection["id"])
    assert certified["status"] == "CERTIFIED"
    mid = get_lot(lot["id"])
    assert mid["status"] == "INSPECTED", (
        "FAIL certification must not auto-dispute; the lot stays INSPECTED")

    disputed = get_success_data(
        api_client.dispute_lot(lot["id"], {"reason": "grade below contract"},
                               RECEIVER_HEADERS))
    assert disputed["status"] == "DISPUTED"


def test_reinspection_loops_back_and_second_pass_accepts(api):
    """PRD §3.4: "A re-inspection loop is supported: from `DISPUTED`, a
    `USDAInspector` may file a fresh inspection (provided none is currently
    `SUBMITTED` for the lot), which moves the lot back to `INSPECTED`; the
    `INSPECTED → DISPUTED → INSPECTED` cycle may repeat across multiple rounds."
    PRD §3.4: "if the certified `defect_pct` is less than or equal to 5,
    `adjusted_cost_cents` remains equal to `provisional_cost_cents`"

    Design: Difficulty/non_linear_state_machine/purchase_lot_dispute_reinspection_cycle
    """
    base = setup_market_day()
    lot, _ = create_disputed_lot(base["shipper"]["id"], base["commodity"]["id"],
                                 defect_pct=25)
    # Re-inspection: filing on DISPUTED loops the lot back to INSPECTED.
    second = file_inspection(lot["id"], inspected_grade="US1", defect_pct=5,
                             result="PASS")
    looped = get_lot(lot["id"])
    assert looped["status"] == "INSPECTED"

    certify_inspection(second["id"])
    final = get_lot(lot["id"])
    assert final["status"] == "ACCEPTED"
    # defect_pct 5 <= tolerance 5: adjusted stays at the provisional 100000.
    assert final["provisional_cost_cents"] == 100000
    assert final["adjusted_cost_cents"] == 100000


def test_purchase_lot_computed_fields_at_creation(api):
    """PRD §3.2: "Until a final-cost event runs, both `adjusted_cost_cents` and
    `payable_cents` are initialized equal to `provisional_cost_cents`."
    PRD §3.2: "The lot's `dumped_units`, `reserved_units`, and `sold_units` all start
    at 0, so `available_units` starts equal to `quantity_units`."

    Design: Corner/entities/purchase_lot_computed_fields_at_creation
    """
    base = setup_market_day()
    lot = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                             quantity_units=100, shipper_unit_price=10.00)
    assert lot["provisional_cost_cents"] == 100000
    assert lot["adjusted_cost_cents"] == 100000
    assert lot["payable_cents"] == 100000
    assert lot["available_units"] == 100


def test_lot_initial_state_is_ordered(api):
    """PRD §3.2: "The new lot is created in `ORDERED` status."
    PRD §2.4: "an integer `version` that starts at 1 and increments by exactly 1 on
    every mutation of that entity, including mutations driven by system cascades"

    Design: Corner/state_machines/lot_initial_state_is_ordered
    """
    base = setup_market_day()
    lot = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                             quantity_units=10)
    assert lot["status"] == "ORDERED"
    assert lot["version"] == 1


def test_receive_twice_returns_invalid_state(api):
    """PRD §3.2: "A receive attempted on a lot that is not `ORDERED` is rejected as
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/receive_twice_returns_invalid_state
    """
    base = setup_market_day()
    lot = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                             quantity_units=10)
    received = receive_lot(lot["id"])
    resp = api.receive_lot(lot["id"], RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_lot(lot["id"])
    assert after["version"] == received["version"], (
        "a rejected transition must not mutate the lot")


def test_dispute_on_accepted_lot_returns_invalid_state(api):
    """PRD §3.4: "A `Receiver` opens a grade/pack dispute on an `INSPECTED` lot only
    when a `CERTIFIED` inspection with `result` equal to `FAIL` exists for that lot."
    PRD §2.8: "the target entity's own state legality (`ERR_INVALID_STATE`, including
    the specialized `ERR_INVOICE_EXISTS` and `ERR_INSPECTION_OPEN` variants where they
    apply)"

    Design: Corner/state_machines/dispute_on_accepted_lot_returns_invalid_state
    """
    base = setup_accepted_lot(defect_pct=0, quantity=10)
    resp = api.dispute_lot(base["lot"]["id"], {"reason": "too late"}, RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_get_purchase_lot_not_found_returns_404(api):
    """PRD §2.8: "existence of path ids and body foreign keys, validated left-to-right
    with path parameters first (`ERR_NOT_FOUND`)"
    PRD §5: "ERR_NOT_FOUND | 404".

    Design: Corner/entities/get_purchase_lot_not_found_returns_404
    """
    resp = api.get_purchase_lot(NON_EXISTENT_UUID, RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_reject_lot_voids_open_submitted_inspection(api):
    """PRD §3.4: "`REJECT_TO_SHIPPER` moves the lot `DISPUTED → REJECTED`. The lot's
    `payable_cents` is set to 0 (rejecting the lot wipes the shipper's claim on it),
    and the shipper's `trust_exposure_cents` is recomputed."
    PRD §3.4: "As a compensating cascade, any `Inspection` still in `SUBMITTED` for
    this lot is voided — its status flips to `VOIDED` — preserving the invariant that
    a `REJECTED` lot never has an open inspection."

    Design: Corner/state_machines/reject_lot_voids_open_submitted_inspection
    """
    base = setup_market_day()
    lot, first = create_disputed_lot(base["shipper"]["id"], base["commodity"]["id"],
                                     defect_pct=25)
    # Re-inspection filed on DISPUTED: lot back to INSPECTED, I2 SUBMITTED.
    second = file_inspection(lot["id"], inspected_grade="US1", defect_pct=8,
                             result="PASS")
    # Second dispute is legal: the lot is INSPECTED and a CERTIFIED FAIL (I1) exists.
    get_success_data(api_client.dispute_lot(
        lot["id"], {"reason": "second opinion contested"}, RECEIVER_HEADERS))

    resolved = resolve_dispute(lot["id"], "REJECT_TO_SHIPPER")
    assert resolved["status"] == "REJECTED"
    assert resolved["payable_cents"] == 0

    inspections = get_success_data(
        api_client.list_lot_inspections(lot["id"], INSPECTOR_HEADERS))
    by_id = {row["id"]: row for row in inspections}
    assert by_id[first["id"]]["status"] == "CERTIFIED"
    assert by_id[second["id"]]["status"] == "VOIDED"
    assert all(row["status"] != "SUBMITTED" for row in inspections), (
        "a REJECTED lot never has an open inspection")


def test_second_inspection_while_submitted_open_returns_inspection_open(api):
    """PRD §3.4: "Only one inspection may be open at a time per lot: attempting to
    file while another inspection for the same lot is still `SUBMITTED` is rejected
    with `ERR_INSPECTION_OPEN`."

    Design: Corner/errors/second_inspection_while_submitted_open_returns_inspection_open
    """
    base = setup_market_day()
    lot, _ = create_disputed_lot(base["shipper"]["id"], base["commodity"]["id"],
                                 defect_pct=25)
    second = file_inspection(lot["id"], inspected_grade="US1", defect_pct=8,
                             result="PASS")
    assert second["status"] == "SUBMITTED"
    get_success_data(api_client.dispute_lot(
        lot["id"], {"reason": "contested again"}, RECEIVER_HEADERS))

    resp = api.create_inspection(
        {"purchase_lot_id": lot["id"], "inspected_grade": "US1", "defect_pct": 3,
         "result": "PASS"}, INSPECTOR_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_OPEN)

    lot_after = get_lot(lot["id"])
    assert lot_after["status"] == "DISPUTED"
    inspections = get_success_data(
        api_client.list_lot_inspections(lot["id"], INSPECTOR_HEADERS))
    by_id = {row["id"]: row for row in inspections}
    assert by_id[second["id"]]["status"] == "SUBMITTED", (
        "the rejected filing must not mutate the open inspection")
