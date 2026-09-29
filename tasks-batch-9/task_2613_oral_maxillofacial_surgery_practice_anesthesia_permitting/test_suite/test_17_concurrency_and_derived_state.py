"""Optimistic concurrency on the three versioned parents, reconciliation of the
consignment and cabinet counters across a reservation's whole life, and the
immediacy of every derived figure.
"""
from test_helpers import (
    ADMIN,
    INVENTORY,
    SCHEDULER,
    ApiErrorId,
    api_client as api,
    assert_block_ledger_conserved,
    assert_lot_quantities_consistent,
    assert_pagination_meta,
    make_anesthesia_coordinator_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _practice_with_surgeon(name):
    practice = validate_success(
        api.create_practice(
            {"name": name, "state_code": "OH", "recovery_bay_count": 2}, ADMIN
        ),
        201,
    )
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": practice["id"],
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    return practice, surgeon


def _hire(practice_id, full_name, role_type):
    return validate_success(
        api.create_staff_member(
            {
                "practice_id": practice_id,
                "full_name": full_name,
                "role_type": role_type,
            },
            ADMIN,
        ),
        201,
    )


def _patient(practice_id, full_name):
    return validate_success(
        api.create_patient(
            {
                "practice_id": practice_id,
                "full_name": full_name,
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )


def _local_case(practice_id, patient_id, surgeon_id,
                planned_start="2026-09-20T13:00:00Z",
                planned_end="2026-09-20T14:00:00Z"):
    return validate_success(
        api.create_surgical_case(
            {
                "practice_id": practice_id,
                "patient_id": patient_id,
                "primary_surgeon_id": surgeon_id,
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "IMPLANT",
                "planned_start": planned_start,
                "planned_end": planned_end,
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )


def _consignment_lot(practice_id, unit_cost_cents, quantity_on_hand,
                     is_consignment=True):
    return validate_success(
        api.create_implant_lot(
            {
                "practice_id": practice_id,
                "manufacturer_code": "NOBEL",
                "catalog_reference": "NB-4310",
                "diameter_mm": 4.3,
                "length_mm": 10.0,
                "unit_cost_cents": unit_cost_cents,
                "quantity_on_hand": quantity_on_hand,
                "expiry_date": "2027-01-31T00:00:00Z",
                "is_consignment": is_consignment,
            },
            INVENTORY,
        ),
        201,
    )


def _exposure(practice_id):
    return validate_success(api.get_practice(practice_id, INVENTORY))[
        "consignment_committed_cents"
    ]


def test_occ_stale_block_version_blocks_confirmation():
    """The hold itself spends the block version the client read at creation.

    PRD: "If the block's `version` has advanced since the client read it —
    because another case held minutes against it, another case was confirmed on
    it, another case on it was cancelled, or the block's open minutes were
    released — the confirmation is rejected with `ERR_STALE_BLOCK_VERSION`
    (HTTP 412)."

    PRD: "A successful hold persists `block_id` on the case, advances
    `scheduling_status` from `DRAFT` to `BLOCK_HELD`, adds the case's
    `duration_minutes` to the block's `committed_minutes`, recomputes the
    block's `open_minutes` and `utilization_pct`, and increments the block's
    `version` — which is exactly why a client that read the block before someone
    else's hold will find its `expected_block_version` stale at confirmation
    time."

    PRD: "`utilization_pct` is one hundred multiplied by `committed_minutes`,
    divided by `block_duration_minutes`, rounded half-up to two decimal places."

    Design: Corner/complexity_layers/stale_block_version_blocks_confirmation
    """
    set_clock("2026-09-13T10:00:00Z")
    practice, surgeon = _practice_with_surgeon("Block OCC OMS")
    prac_id = practice["id"]
    author = _hire(prac_id, "Nia Author", "ANESTHESIA_MONITOR")
    verifier = _hire(prac_id, "Val Verifier", "ANESTHESIA_MONITOR")
    patient = _patient(prac_id, "Pat Stale")
    block = validate_success(
        api.create_block_time(
            {
                "practice_id": prac_id,
                "surgeon_id": surgeon["id"],
                "room_code": "OR-1",
                "block_start": "2026-09-14T13:00:00Z",
                "block_end": "2026-09-14T17:00:00Z",
                "release_deadline_hours": 48,
            },
            SCHEDULER,
        ),
        201,
    )
    block_version_at_creation = block["version"]
    case = _local_case(
        prac_id,
        patient["id"],
        surgeon["id"],
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
    )
    evaluation = validate_success(
        api.create_evaluation(
            case["id"],
            {
                "evaluator_staff_id": author["id"],
                "asa_class_recorded": 2,
                "airway_class_recorded": 2,
                "comorbidity_count": 0,
                "expected_case_version": case["version"],
            },
            make_anesthesia_coordinator_headers(author["id"]),
        ),
        201,
    )
    validate_success(
        api.sign_evaluation(
            evaluation["id"], {}, make_anesthesia_coordinator_headers(author["id"])
        )
    )
    set_clock("2026-09-14T07:00:00Z")
    validate_success(
        api.verify_evaluation(
            evaluation["id"],
            {
                "intent": "CLEAR",
                "fasting_solids_last_at": "2026-09-13T20:00:00Z",
                "fasting_clears_last_at": "2026-09-14T06:00:00Z",
                "escort_confirmed": False,
            },
            make_anesthesia_coordinator_headers(verifier["id"]),
        )
    )
    validate_success(api.hold_block(case["id"], {"block_id": block["id"]}, SCHEDULER))

    validate_error(
        api.confirm_case(
            case["id"],
            {"expected_block_version": block_version_at_creation},
            SCHEDULER,
        ),
        ApiErrorId.ERR_STALE_BLOCK_VERSION.value,
    )
    after_refusal = validate_success(api.get_block_time(block["id"], SCHEDULER))
    assert after_refusal["committed_minutes"] == 60
    assert after_refusal["open_minutes"] == 180
    assert float(after_refusal["utilization_pct"]) == 25.00
    assert after_refusal["version"] > block_version_at_creation, (
        "the hold advanced the block version the client was still quoting"
    )
    assert_block_ledger_conserved(after_refusal)
    current_version = after_refusal["version"]

    confirmed = validate_success(
        api.confirm_case(
            case["id"], {"expected_block_version": current_version}, SCHEDULER
        )
    )
    assert confirmed["scheduling_status"] == "CONFIRMED"
    after_confirm = validate_success(api.get_block_time(block["id"], SCHEDULER))
    assert after_confirm["version"] > current_version, (
        "confirmation re-publishes the block and advances its version once more"
    )
    assert after_confirm["committed_minutes"] == 60, (
        "the minutes were committed at hold time and do not move again"
    )
    assert after_confirm["open_minutes"] == 180
    assert_block_ledger_conserved(after_confirm)


def test_occ_stale_lot_version_blocks_a_second_reservation():
    """The first reservation supersedes the availability snapshot of the second.

    PRD: "If the lot's `version` has advanced since the client read it — because
    another reservation was placed against it, a reservation on it was consumed
    or released, or the lot was quarantined — the creation is rejected with
    `ERR_STALE_LOT_VERSION` (HTTP 412), because each of those actions supersedes
    the caller's availability snapshot."

    PRD: "Thereafter `quantity_reserved` is always the sum of `quantity` over the
    lot's reservations whose `status` is `HELD`, and `available_quantity` is
    `quantity_on_hand` less `quantity_reserved`, never negative."

    Design: Corner/complexity_layers/stale_lot_version_blocks_a_second_reservation
    """
    set_clock("2026-09-11T10:00:00Z")
    practice, surgeon = _practice_with_surgeon("Lot OCC OMS")
    prac_id = practice["id"]
    patient = _patient(prac_id, "Pat Implant")
    case = _local_case(prac_id, patient["id"], surgeon["id"])
    lot = _consignment_lot(prac_id, 20000, 5, is_consignment=False)
    lot_version_at_creation = lot["version"]
    first = validate_success(
        api.create_reservation(
            {
                "case_id": case["id"],
                "lot_id": lot["id"],
                "quantity": 1,
                "expected_lot_version": lot_version_at_creation,
            },
            INVENTORY,
        ),
        201,
    )
    assert first["status"] == "HELD"
    assert first["consignment_credit_cents"] == 0, "an owned lot earns no credit"
    assert first["consignment_liability_cents"] == 20000, (
        "the consignment flag suppresses only the credit, never the exposure"
    )
    assert _exposure(prac_id) == 20000

    validate_error(
        api.create_reservation(
            {
                "case_id": case["id"],
                "lot_id": lot["id"],
                "quantity": 1,
                "expected_lot_version": lot_version_at_creation,
            },
            INVENTORY,
        ),
        ApiErrorId.ERR_STALE_LOT_VERSION.value,
    )
    after_refusal = validate_success(api.get_implant_lot(lot["id"], INVENTORY))
    assert after_refusal["available_quantity"] == 4, (
        "stock was never the reason for the refusal"
    )
    assert after_refusal["quantity_reserved"] == 1
    assert after_refusal["version"] > lot_version_at_creation
    assert_lot_quantities_consistent(after_refusal)
    current_version = after_refusal["version"]
    assert _exposure(prac_id) == 20000

    second = validate_success(
        api.create_reservation(
            {
                "case_id": case["id"],
                "lot_id": lot["id"],
                "quantity": 1,
                "expected_lot_version": current_version,
            },
            INVENTORY,
        ),
        201,
    )
    assert second["status"] == "HELD"
    reread = validate_success(api.get_implant_lot(lot["id"], INVENTORY))
    assert reread["quantity_reserved"] == 2
    assert reread["available_quantity"] == 3
    assert_lot_quantities_consistent(reread)
    assert _exposure(prac_id) == 40000


def test_occ_stale_case_version_blocks_a_replacement_evaluation():
    """A writer holding the pre-signature case version cannot open a new evaluation.

    PRD: "If the case's `version` has advanced since the client read it, the
    creation is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    PRD: "Signature stamps `signed_at` with the logical clock, recomputes
    `provisional_risk_score` and re-derives `risk_band` from it against the
    case's *current* `planned_anesthesia_level` (so a case whose planned depth
    changed between drafting and signature is rescored, not left stale), advances
    the evaluation from `DRAFT` to `SIGNED`, moves the case's `clearance_status`
    from `NOT_EVALUATED` to `EVALUATED`, and increments the case's `version`."

    PRD: "Any prior evaluation on the same case whose `status` is `SIGNED` or
    `VERIFIED` moves to the terminal `SUPERSEDED`, and the case's
    `clearance_status` resets to `NOT_EVALUATED` — whether it stood at
    `EVALUATED`, at `CLEARED`, or at `DEFERRED` — with the case's `version`
    incremented."

    Design: Corner/complexity_layers/stale_case_version_blocks_a_replacement_evaluation
    """
    set_clock("2026-09-13T10:00:00Z")
    practice, surgeon = _practice_with_surgeon("Case OCC OMS")
    prac_id = practice["id"]
    author = _hire(prac_id, "Nia Author", "ANESTHESIA_MONITOR")
    patient = _patient(prac_id, "Pat Reeval")
    case = _local_case(prac_id, patient["id"], surgeon["id"])
    case_id = case["id"]
    case_version_at_creation = case["version"]
    author_headers = make_anesthesia_coordinator_headers(author["id"])
    first_evaluation = validate_success(
        api.create_evaluation(
            case_id,
            {
                "evaluator_staff_id": author["id"],
                "asa_class_recorded": 2,
                "airway_class_recorded": 2,
                "comorbidity_count": 0,
                "expected_case_version": case_version_at_creation,
            },
            author_headers,
        ),
        201,
    )
    signed = validate_success(
        api.sign_evaluation(first_evaluation["id"], {}, author_headers)
    )
    assert signed["status"] == "SIGNED"
    after_signature = validate_success(api.get_surgical_case(case_id, ADMIN))
    assert after_signature["clearance_status"] == "EVALUATED"
    assert after_signature["version"] > case_version_at_creation, (
        "signing incremented the case version the client is still quoting"
    )

    validate_error(
        api.create_evaluation(
            case_id,
            {
                "evaluator_staff_id": author["id"],
                "asa_class_recorded": 3,
                "airway_class_recorded": 2,
                "comorbidity_count": 0,
                "expected_case_version": case_version_at_creation,
            },
            author_headers,
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION.value,
    )
    only_one, meta = validate_paginated(
        api.list_evaluations(ADMIN, params={"case_id": case_id})
    )
    assert_pagination_meta(meta, expected_total=1)
    assert only_one[0]["id"] == first_evaluation["id"]
    unchanged_case = validate_success(api.get_surgical_case(case_id, ADMIN))
    assert unchanged_case["version"] == after_signature["version"], (
        "the refused creation left the case exactly where the signature put it"
    )
    assert unchanged_case["clearance_status"] == "EVALUATED"

    replacement = validate_success(
        api.create_evaluation(
            case_id,
            {
                "evaluator_staff_id": author["id"],
                "asa_class_recorded": 3,
                "airway_class_recorded": 2,
                "comorbidity_count": 0,
                "expected_case_version": unchanged_case["version"],
            },
            author_headers,
        ),
        201,
    )
    assert replacement["status"] == "DRAFT"
    assert float(replacement["provisional_risk_score"]) == 15.0, (
        "10 * 3 = 30 factor points halved by the LOCAL_ONLY multiplier"
    )
    assert replacement["risk_band"] == "LOW"
    superseded = validate_success(api.get_evaluation(first_evaluation["id"], ADMIN))
    assert superseded["status"] == "SUPERSEDED", (
        "the signed evaluation it displaced moves to the terminal SUPERSEDED"
    )
    both, both_meta = validate_paginated(
        api.list_evaluations(ADMIN, params={"case_id": case_id})
    )
    assert_pagination_meta(both_meta, expected_total=2)
    assert {row["id"] for row in both} == {first_evaluation["id"], replacement["id"]}
    reset_case = validate_success(api.get_surgical_case(case_id, ADMIN))
    assert reset_case["clearance_status"] == "NOT_EVALUATED"


def test_occ_derived_totals_reconcile_after_reserve_consume_and_release():
    """Exposure and cabinet counters re-derive independently across three writes.

    PRD: "Consumption moves the reservation to `CONSUMED`, subtracts the
    `quantity` from both the lot's `quantity_on_hand` and its
    `quantity_reserved`, recomputes `available_quantity`, increments the lot's
    `version`, leaves `consignment_liability_cents` exactly as it stood while
    `HELD`, recomputes the practice's `consignment_committed_cents` — a consumed
    reservation still counts toward exposure — and increments the practice's
    `version`."

    PRD: "On `RELEASED` the fixtures come back to the shelf: `quantity_on_hand`
    is deliberately unchanged while `quantity_reserved` is decremented by the
    reservation's `quantity`, the tiered `restocking_fee_cents` is charged,
    `consignment_credit_cents` drops to 0, and `consignment_liability_cents`
    becomes the restocking fee."

    PRD: "The practice's rolling `consignment_committed_cents` is the sum of
    `consignment_liability_cents` over the practice's reservations whose
    `status` is `HELD` or `CONSUMED`; released and shorted rows drop out."

    Design: Corner/complexity_layers/derived_totals_reconcile_after_reserve_consume_and_release
    """
    set_clock("2026-09-11T10:00:00Z")
    practice, surgeon = _practice_with_surgeon("Reconcile OMS")
    prac_id = practice["id"]
    author = _hire(prac_id, "Nia Author", "ANESTHESIA_MONITOR")
    verifier = _hire(prac_id, "Val Verifier", "ANESTHESIA_MONITOR")
    patient = _patient(prac_id, "Pat Ledger")
    block = validate_success(
        api.create_block_time(
            {
                "practice_id": prac_id,
                "surgeon_id": surgeon["id"],
                "room_code": "OR-1",
                "block_start": "2026-09-20T13:00:00Z",
                "block_end": "2026-09-20T17:00:00Z",
                "release_deadline_hours": 48,
            },
            SCHEDULER,
        ),
        201,
    )
    case = _local_case(prac_id, patient["id"], surgeon["id"])
    case_id = case["id"]
    evaluation = validate_success(
        api.create_evaluation(
            case_id,
            {
                "evaluator_staff_id": author["id"],
                "asa_class_recorded": 2,
                "airway_class_recorded": 2,
                "comorbidity_count": 0,
                "expected_case_version": case["version"],
            },
            make_anesthesia_coordinator_headers(author["id"]),
        ),
        201,
    )
    validate_success(
        api.sign_evaluation(
            evaluation["id"], {}, make_anesthesia_coordinator_headers(author["id"])
        )
    )
    validate_success(
        api.verify_evaluation(
            evaluation["id"],
            {
                "intent": "CLEAR",
                "fasting_solids_last_at": "2026-09-11T00:00:00Z",
                "fasting_clears_last_at": "2026-09-11T08:00:00Z",
                "escort_confirmed": False,
            },
            make_anesthesia_coordinator_headers(verifier["id"]),
        )
    )
    validate_success(api.hold_block(case_id, {"block_id": block["id"]}, SCHEDULER))
    held_block = validate_success(api.get_block_time(block["id"], SCHEDULER))
    confirmed = validate_success(
        api.confirm_case(
            case_id, {"expected_block_version": held_block["version"]}, SCHEDULER
        )
    )
    assert confirmed["scheduling_status"] == "CONFIRMED", (
        "fixtures cannot be placed in a case that has not been committed"
    )
    lot = _consignment_lot(prac_id, 30000, 4)

    reservation_a = validate_success(
        api.create_reservation(
            {
                "case_id": case_id,
                "lot_id": lot["id"],
                "quantity": 2,
                "expected_lot_version": lot["version"],
            },
            INVENTORY,
        ),
        201,
    )
    assert reservation_a["line_subtotal_cents"] == 60000
    assert reservation_a["restocking_fee_cents"] == 6000
    assert reservation_a["consignment_credit_cents"] == 12000
    assert reservation_a["consignment_liability_cents"] == 48000
    lot_after_hold = validate_success(api.get_implant_lot(lot["id"], INVENTORY))
    assert lot_after_hold["quantity_on_hand"] == 4
    assert lot_after_hold["quantity_reserved"] == 2
    assert lot_after_hold["available_quantity"] == 2
    assert_lot_quantities_consistent(lot_after_hold)
    assert _exposure(prac_id) == 48000

    consumed = validate_success(
        api.consume_reservation(reservation_a["id"], {}, INVENTORY)
    )
    assert consumed["status"] == "CONSUMED"
    assert consumed["consignment_liability_cents"] == 48000, (
        "the price pinned while HELD survives consumption"
    )
    assert _exposure(prac_id) == 48000, "a CONSUMED row stays in the exposure sum"
    lot_after_consume = validate_success(api.get_implant_lot(lot["id"], INVENTORY))
    assert lot_after_consume["quantity_on_hand"] == 2, (
        "consuming removes the units from the cabinet"
    )
    assert lot_after_consume["quantity_reserved"] == 0
    assert lot_after_consume["available_quantity"] == 2
    assert_lot_quantities_consistent(lot_after_consume)

    reservation_b = validate_success(
        api.create_reservation(
            {
                "case_id": case_id,
                "lot_id": lot["id"],
                "quantity": 1,
                "expected_lot_version": lot_after_consume["version"],
            },
            INVENTORY,
        ),
        201,
    )
    assert reservation_b["line_subtotal_cents"] == 30000
    assert reservation_b["restocking_fee_cents"] == 4500
    assert reservation_b["consignment_credit_cents"] == 6000
    assert reservation_b["consignment_liability_cents"] == 24000
    assert _exposure(prac_id) == 72000

    released = validate_success(
        api.release_reservation(
            reservation_b["id"], {"disposition": "RELEASED"}, INVENTORY
        )
    )
    assert released["status"] == "RELEASED"
    assert released["consignment_credit_cents"] == 0
    assert released["consignment_liability_cents"] == 4500
    lot_after_release = validate_success(api.get_implant_lot(lot["id"], INVENTORY))
    assert lot_after_release["quantity_on_hand"] == 2, (
        "a release returns nothing to the cabinet count, only to availability"
    )
    assert lot_after_release["quantity_reserved"] == 0
    assert lot_after_release["available_quantity"] == 2
    assert_lot_quantities_consistent(lot_after_release)
    assert _exposure(prac_id) == 48000, (
        "the RELEASED row drops out of the sum entirely, its fee included"
    )


def test_occ_every_derived_field_is_current_in_the_same_response():
    """A write's own body already carries the recomputed money and stock figures.

    PRD: "Creating a reservation in either path stamps its `status` `HELD`,
    computes all four money fields, adds the `quantity` to the lot's
    `quantity_reserved`, recomputes the lot's `available_quantity`, increments
    the lot's `version`, recomputes and re-checks the practice's
    `consignment_committed_cents`, and increments the practice's `version`."

    PRD: "`consignment_committed_cents` is the practice's rolling consignment
    exposure: the sum of `consignment_liability_cents` across every reservation
    on any lot of this practice whose reservation `status` is `HELD` or
    `CONSUMED`."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
    """
    set_clock("2026-09-11T10:00:00Z")
    practice, surgeon = _practice_with_surgeon("Immediate OMS")
    prac_id = practice["id"]
    patient = _patient(prac_id, "Pat Instant")
    case = _local_case(prac_id, patient["id"], surgeon["id"])
    lot = _consignment_lot(prac_id, 30000, 4)
    lot_version = lot["version"]

    reservation = validate_success(
        api.create_reservation(
            {
                "case_id": case["id"],
                "lot_id": lot["id"],
                "quantity": 2,
                "expected_lot_version": lot_version,
            },
            INVENTORY,
        ),
        201,
    )
    assert reservation["status"] == "HELD"
    assert reservation["line_subtotal_cents"] == 60000
    assert reservation["restocking_fee_cents"] == 6000
    assert reservation["consignment_credit_cents"] == 12000
    assert reservation["consignment_liability_cents"] == 48000

    lot_now = validate_success(api.get_implant_lot(lot["id"], INVENTORY))
    assert lot_now["quantity_reserved"] == 2
    assert lot_now["available_quantity"] == 2
    assert lot_now["version"] == lot_version + 1, (
        "the very next call sees the lot already updated exactly once"
    )
    assert_lot_quantities_consistent(lot_now)

    practice_now = validate_success(api.get_practice(prac_id, INVENTORY))
    assert practice_now["consignment_committed_cents"] == (
        reservation["consignment_liability_cents"]
    ), "the exposure matches the reservation body with no lag"
    assert practice_now["version"] > practice["version"]
