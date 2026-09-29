"""Field and domain validation: the cone-beam justification rule, block-window
containment, open-minute capacity, the service-line fiscal identity, the implant
stock boundary, permit rank at confirmation, path-before-body resolution, and the
staged-treatment cycle walk."""
import pytest

from test_helpers import (
    ADMIN,
    BENEFITS,
    INVENTORY,
    NON_EXISTENT_UUID,
    SCHEDULER,
    ApiErrorId,
    apply_permit,
    assert_block_ledger_conserved,
    assert_determination,
    assert_lot_quantities_consistent,
    assert_money_identity,
    assert_reservation,
    assert_surgical_case,
    create_block,
    create_case,
    create_determination_payload,
    create_evaluation_payload,
    create_imaging_study_payload,
    create_lot,
    create_patient,
    create_practice,
    create_reservation_payload,
    create_staff,
    day_of_verification_payload,
    fetch_block,
    fetch_case,
    fetch_lot,
    fetch_permit,
    fetch_practice,
    hold_case_on_block,
    log_drill,
    make_anesthesia_coordinator_headers,
    make_surgeon_headers,
    record_inspection_result,
    schedule_inspection,
    service_line,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_validation_cbct_field_of_view_justification_rule_applies_only_to_cone_beam(api):
    """PRD: "A `CBCT_LARGE_FOV` study accepts only `ORTHOGNATHIC_PLANNING`,
    `PATHOLOGY_STAGING`, or `TRAUMA_SURVEY` — planning a single implant does not
    warrant a large field of view."
    PRD: "A `CBCT_SMALL_FOV` study accepts `IMPLANT_PLANNING`,
    `THIRD_MOLAR_ASSESSMENT`, `PATHOLOGY_STAGING`, or `TRAUMA_SURVEY`, but not
    `ORTHOGNATHIC_PLANNING`, whose skeletal analysis needs the larger volume."
    PRD: "`PANORAMIC` and `CEPHALOMETRIC` studies accept any of the five codes."
    PRD: "A mismatched pairing is rejected with `ERR_CBCT_JUSTIFICATION_INVALID`
    (HTTP 422)."
    PRD: "`dose_flag` is `ABOVE_REFERENCE_LEVEL` when the recorded dose is strictly
    greater than its modality's reference level, and `WITHIN_PROTOCOL` otherwise;
    because the comparison is strict, a dose exactly at the reference level is
    `WITHIN_PROTOCOL`."

    The same justification code is illegal on a large-FOV cone beam, legal on a
    small-FOV cone beam and legal on a plain film.

    Design: Corner/validations/cbct_field_of_view_justification_rule_applies_only_to_cone_beam
    """
    # The logical clock boots at 2026-08-01T00:00:00Z (PRD 2.5) and is monotonic,
    # so the session clock must sit at or after that instant. Every assertion below
    # is anchored to `acquired_at`, which stays at or before the clock.
    set_clock("2026-08-05T10:00:00Z")
    practice = create_practice(name="CBCT OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    surgeon_headers = make_surgeon_headers(surgeon["id"])
    patient = create_patient(practice["id"], full_name="Pat Cone")

    validate_error(
        api.create_imaging_study(
            create_imaging_study_payload(
                patient["id"], modality="CBCT_LARGE_FOV",
                justification_code="IMPLANT_PLANNING",
                acquired_at="2026-06-01T09:00:00Z", dose_mgy_cm2=800.0,
            ),
            surgeon_headers,
        ),
        ApiErrorId.ERR_CBCT_JUSTIFICATION_INVALID.value,
    )

    small = validate_success(
        api.create_imaging_study(
            create_imaging_study_payload(
                patient["id"], modality="CBCT_SMALL_FOV",
                justification_code="IMPLANT_PLANNING",
                acquired_at="2026-06-01T09:00:00Z", dose_mgy_cm2=180.0,
            ),
            surgeon_headers,
        ),
        201,
    )
    panoramic = validate_success(
        api.create_imaging_study(
            create_imaging_study_payload(
                patient["id"], modality="PANORAMIC",
                justification_code="IMPLANT_PLANNING",
                acquired_at="2026-06-01T09:00:00Z", dose_mgy_cm2=40.0,
            ),
            surgeon_headers,
        ),
        201,
    )
    large_ok = validate_success(
        api.create_imaging_study(
            create_imaging_study_payload(
                patient["id"], modality="CBCT_LARGE_FOV",
                justification_code="ORTHOGNATHIC_PLANNING",
                acquired_at="2026-06-01T09:00:00Z", dose_mgy_cm2=800.0,
            ),
            surgeon_headers,
        ),
        201,
    )

    assert small["justification_code"] == "IMPLANT_PLANNING"
    assert panoramic["modality"] == "PANORAMIC"
    assert large_ok["dose_flag"] == "WITHIN_PROTOCOL", (
        f"800.0 does not exceed the 900.0 large-FOV reference level, got {large_ok['dose_flag']}"
    )

    stored, meta = validate_paginated(
        api.list_imaging_studies(ADMIN, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 3, (
        f"the rejected pairing left no study row behind, got {meta['total_count']}"
    )
    assert {row["id"] for row in stored} == {small["id"], panoramic["id"], large_ok["id"]}


def test_validation_case_window_reaching_past_the_block_end_rejected(api):
    """PRD: "The block must belong to the case's practice, its `status` must not be
    `RELEASED`, and the case's half-open window from `planned_start` to
    `planned_end` must be wholly contained inside the block's half-open window from
    `block_start` to `block_end`; a case that starts before the block opens or ends
    after it closes is refused with `ERR_CASE_OUTSIDE_BLOCK_WINDOW` (HTTP 409)."
    PRD: "A successful hold persists `block_id` on the case, advances
    `scheduling_status` from `DRAFT` to `BLOCK_HELD`, adds the case's
    `duration_minutes` to the block's `committed_minutes`, recomputes the block's
    `open_minutes` and `utilization_pct`, and increments the block's `version` —
    which is exactly why a client that read the block before someone else's hold will
    find its `expected_block_version` stale at confirmation time."

    A case running 30 minutes past the block's close is refused, while a case whose
    `planned_end` lands exactly on `block_end` is admitted.

    Design: Corner/validations/case_window_reaching_past_the_block_end_rejected
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Window OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(practice["id"], full_name="Pat Window")
    block = create_block(
        practice["id"], surgeon["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z",
        room_code="OR-1", release_deadline_hours=48,
    )
    overrun_case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-14T16:30:00Z", "2026-09-14T17:30:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    edge_case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-14T16:00:00Z", "2026-09-14T17:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    version_before = fetch_block(block["id"])["version"]

    validate_error(
        api.hold_block(overrun_case["id"], {"block_id": block["id"]}, SCHEDULER),
        ApiErrorId.ERR_CASE_OUTSIDE_BLOCK_WINDOW.value,
    )

    refused = fetch_case(overrun_case["id"])
    assert refused["scheduling_status"] == "DRAFT", (
        f"the refused case keeps no block minutes, got {refused['scheduling_status']}"
    )
    assert refused["block_id"] is None, "a refused hold must not persist block_id"
    assert fetch_block(block["id"])["committed_minutes"] == 0, (
        "no minutes may be committed by a refused hold"
    )

    held = validate_success(
        api.hold_block(edge_case["id"], {"block_id": block["id"]}, SCHEDULER)
    )
    assert_surgical_case(held)
    assert held["scheduling_status"] == "BLOCK_HELD", (
        "planned_end exactly equal to block_end is inside the half-open block window, "
        f"got {held['scheduling_status']}"
    )

    after = fetch_block(block["id"])
    assert after["committed_minutes"] == 60, (
        f"only the admitted 60-minute case commits minutes, got {after['committed_minutes']}"
    )
    assert after["version"] == version_before + 1, (
        f"the block version moves once, for the one successful hold, got {after['version']}"
    )
    assert_block_ledger_conserved(after)


def test_validation_released_minutes_make_a_fitting_case_exceed_block_capacity(api):
    """PRD: "The last gate is arithmetic: the case's `duration_minutes` may not
    exceed the block's current `open_minutes`, or the hold is refused with
    `ERR_BLOCK_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD: "When `committed_minutes` is greater than zero the block becomes
    `PARTIALLY_RELEASED`: the current `open_minutes` are added to
    `released_minutes`, `open_minutes` is set to 0, and `utilization_pct` is
    recomputed against the unchanged `block_duration_minutes` — the committed
    minutes are untouched, so the percentage does not move, and the conservation
    identity still holds."
    PRD: "The invariant that holds after every write is that `committed_minutes`,
    `released_minutes`, and `open_minutes` sum to exactly `block_duration_minutes`;
    a two-hundred-minute block carrying ninety committed minutes therefore reports
    a utilization of 45.00 with 110 minutes still open."

    A 30-minute case cannot take minutes from a 240-minute block once 60 are
    committed and the other 180 have been handed back.

    Design: Corner/validations/released_minutes_make_a_fitting_case_exceed_block_capacity
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Capacity OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(practice["id"], full_name="Pat Capacity")
    block = create_block(
        practice["id"], surgeon["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z",
        room_code="OR-1", release_deadline_hours=48,
    )
    first_case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    late_case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-14T15:00:00Z", "2026-09-14T15:30:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="THIRD_MOLAR",
        total_charge_cents=30000,
    )
    hold_case_on_block(first_case["id"], block["id"])
    released = validate_success(
        api.release_block_time(block["id"], {"release_note": "half day given back"}, SCHEDULER)
    )

    assert released["status"] == "PARTIALLY_RELEASED", (
        f"a block with committed minutes partially releases, got {released['status']}"
    )
    assert released["committed_minutes"] == 60
    assert released["released_minutes"] == 180
    assert released["open_minutes"] == 0, (
        f"every still-open minute was handed back, got {released['open_minutes']}"
    )
    assert_block_ledger_conserved(released)

    validate_error(
        api.hold_block(late_case["id"], {"block_id": block["id"]}, SCHEDULER),
        ApiErrorId.ERR_BLOCK_CAPACITY_EXCEEDED.value,
    )

    stalled = fetch_case(late_case["id"])
    assert stalled["scheduling_status"] == "DRAFT", (
        "30 minutes is less than the block's 240, but none of them are open"
    )
    assert stalled["block_id"] is None
    after = fetch_block(block["id"])
    assert after["status"] == "PARTIALLY_RELEASED", (
        "the block was never RELEASED, so the refusal is the capacity gate and not "
        f"the block-status precondition, got {after['status']}"
    )
    assert (after["committed_minutes"], after["released_minutes"], after["open_minutes"]) == (
        60, 180, 0
    ), f"no counter may move on a refused hold, got {after}"


def test_validation_service_lines_that_do_not_sum_to_the_case_total_rejected(api):
    """PRD: "The lines must also sum, in `charge_cents`, to exactly the parent case's
    `total_charge_cents`; a mismatch is refused with `ERR_CHARGE_TOTAL_MISMATCH`
    (HTTP 422), and that rule is enforced both at creation and at every submission."
    PRD: "Routing reads only the patient's two coverage flags. When both
    `medical_plan_active` and `dental_plan_active` are true the `route` is `SPLIT`;
    when only `medical_plan_active` is true it is `MEDICAL_PRIMARY`; when only
    `dental_plan_active` is true it is `DENTAL_PRIMARY`; and when neither is true it
    is `SELF_PAY`."

    The fiscal identity is checked before any routing or coinsurance work, so the
    short pair of lines leaves no determination behind at all.

    Design: Corner/validations/service_lines_that_do_not_sum_to_the_case_total_rejected
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Charge OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(
        practice["id"], full_name="Pat Charge",
        medical_plan_active=True, dental_plan_active=False,
    )
    case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-20T13:00:00Z", "2026-09-20T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="PATHOLOGY",
        total_charge_cents=90000,
    )

    short_lines = [
        service_line("41899", 50000, "MEDICAL"),
        service_line("21031", 30000, "MEDICAL"),
    ]
    validate_error(
        api.create_determination(
            create_determination_payload(case["id"], short_lines), BENEFITS
        ),
        ApiErrorId.ERR_CHARGE_TOTAL_MISMATCH.value,
    )

    _rows, meta = validate_paginated(
        api.list_determinations(BENEFITS, params={"case_id": case["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a refused determination must not be persisted, got {meta['total_count']}"
    )

    corrected_lines = [
        service_line("41899", 60000, "MEDICAL"),
        service_line("21031", 30000, "MEDICAL"),
    ]
    determination = validate_success(
        api.create_determination(
            create_determination_payload(case["id"], corrected_lines), BENEFITS
        ),
        201,
    )
    assert_determination(determination)
    assert determination["route"] == "MEDICAL_PRIMARY", (
        "the patient carries medical cover only, so the route is MEDICAL_PRIMARY, "
        f"got {determination['route']}"
    )
    assert_money_identity(determination, 90000)


def test_validation_reservation_for_the_last_available_units_is_accepted(api):
    """PRD: "the lot's
    `available_quantity` must be at least the requested `quantity` and the lot's
    `expiry_date` must fall after the case's `planned_start`, or the answer is
    `ERR_IMPLANT_STOCK_INSUFFICIENT` (HTTP 409) — stock that expires before the
    operation is no stock at all; then the consignment credit test described below."
    PRD: "Thereafter `quantity_reserved` is always the sum of `quantity` over the
    lot's reservations whose `status` is `HELD`, and `available_quantity` is
    `quantity_on_hand` less `quantity_reserved`, never negative."
    PRD: "`line_subtotal_cents` is the lot's `unit_cost_cents` multiplied by the
    reservation's `quantity`."
    PRD: "While `HELD`, and still after it becomes `CONSUMED`, the liability is
    `line_subtotal_cents` less `consignment_credit_cents`."

    Taking exactly the whole available quantity passes the at-least test, drains the
    lot to zero available while it stays AVAILABLE, and makes the very next unit
    impossible.

    Design: Corner/validations/reservation_for_the_last_available_units_is_accepted
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Stock OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(practice["id"], full_name="Pat Stock")
    case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-20T13:00:00Z", "2026-09-20T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="IMPLANT",
        total_charge_cents=90000,
    )
    lot = create_lot(
        practice["id"], manufacturer_code="NOBEL", catalog_reference="NB-4310",
        diameter_mm=4.3, length_mm=10.0, unit_cost_cents=30000,
        quantity_on_hand=2, expiry_date="2027-01-31T00:00:00Z",
    )

    reservation = validate_success(
        api.create_reservation(
            create_reservation_payload(case["id"], lot["id"], 2, lot["version"]),
            INVENTORY,
        ),
        201,
    )

    assert_reservation(reservation)
    assert reservation["status"] == "HELD"
    assert reservation["line_subtotal_cents"] == 60000, (
        f"30000 cents a fixture for two fixtures is 60000, got {reservation['line_subtotal_cents']}"
    )
    assert reservation["consignment_liability_cents"] == 60000, (
        "owned stock earns no consignment credit, so the held liability is the whole "
        f"subtotal, got {reservation['consignment_liability_cents']}"
    )

    drained = fetch_lot(lot["id"])
    assert drained["quantity_reserved"] == 2
    assert drained["quantity_on_hand"] == 2, (
        "holding fixtures does not remove them from the cabinet"
    )
    assert drained["available_quantity"] == 0
    assert drained["status"] == "AVAILABLE", (
        f"units are still physically on hand, so the lot stays AVAILABLE, got {drained['status']}"
    )
    assert_lot_quantities_consistent(drained)

    validate_error(
        api.create_reservation(
            create_reservation_payload(case["id"], lot["id"], 1, drained["version"]),
            INVENTORY,
        ),
        ApiErrorId.ERR_IMPLANT_STOCK_INSUFFICIENT.value,
    )
    assert fetch_lot(lot["id"])["quantity_reserved"] == 2, (
        "the refused second request reserves nothing"
    )


def test_validation_case_level_above_the_open_permit_level_rejected(api):
    """PRD: "Fifth is permit rank, which is a different question from privilege: the
    practice's open permit — the one whose `status` is `ACTIVE` or `PROBATION` —
    must be licensed at least as deep as the case requires."
    PRD: "Ranking `LOCAL_ONLY` at zero, `MINIMAL_SEDATION` at one,
    `MODERATE_SEDATION` at two, and `DEEP_SEDATION_GENERAL` at three, the open
    permit's `permit_level` rank must be at or above the rank the case's
    `planned_anesthesia_level` demands; a `LOCAL_ONLY` case demands rank zero and
    therefore needs no permit level at all."
    PRD: "For a `MODERATE_SEDATION` case a monitor is required and must be certified,
    and a current surgeon ACLS card is required, but no dedicated recovery nurse
    is."
    PRD: "Because so many rules converge here, their order is normative and is stated
    in full below; the first violated rule decides the response."

    Every case-local gate is satisfied — cleared evaluation, certified monitor,
    in-date ACLS card, free room, free bay — and a privilege state of PERMITTED is
    still not the same thing as a permit licensed deeply enough.

    Design: Corner/validations/case_level_above_the_open_permit_level_rejected
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = create_practice(name="Rank OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(
        practice["id"], "SURGEON", "Dr Alma Reyes",
        acls_expires_on="2027-06-30T00:00:00Z",
    )
    monitor = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Mo Monitor", monitoring_certified=True
    )
    nurse = create_staff(practice["id"], "RECOVERY_NURSE", "Rhea Nurse")
    verifier = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Val Verifier", monitoring_certified=True
    )
    permit = apply_permit(
        practice["id"], permit_level="MINIMAL_SEDATION", applied_on="2026-08-25T00:00:00Z"
    )
    log_drill(
        practice["id"], "AIRWAY_OBSTRUCTION", "2026-08-20T09:00:00Z",
        [monitor["id"], nurse["id"]],
    )
    log_drill(
        practice["id"], "LOCAL_ANESTHETIC_TOXICITY", "2026-08-21T09:00:00Z",
        [monitor["id"], nurse["id"]],
    )
    inspection = schedule_inspection(permit["id"], "2026-09-02T09:00:00Z")
    set_clock("2026-09-02T10:00:00Z")
    record_inspection_result(inspection["id"], minor=0, major=0, critical=0)

    open_permit = fetch_permit(permit["id"])
    assert open_permit["status"] == "ACTIVE", (
        f"a clean inspection with full drill coverage issues the permit, got {open_permit['status']}"
    )
    assert open_permit["drill_compliance_ratio"] == pytest.approx(1.00, abs=0.01)
    assert fetch_practice(practice["id"])["sedation_privilege_state"] == "PERMITTED"

    patient = create_patient(practice["id"], full_name="Pat Rank")
    block = create_block(
        practice["id"], surgeon["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z",
        room_code="OR-1", release_deadline_hours=48,
    )
    case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T14:00:00Z",
        monitor_staff_id=monitor["id"], planned_anesthesia_level="MODERATE_SEDATION",
        procedure_category="IMPLANT", total_charge_cents=90000,
    )
    evaluation = validate_success(
        api.create_evaluation(
            case["id"],
            create_evaluation_payload(
                monitor["id"], case["version"],
                asa_class_recorded=2, airway_class_recorded=2, comorbidity_count=0,
            ),
            make_anesthesia_coordinator_headers(monitor["id"]),
        ),
        201,
    )
    validate_success(
        api.sign_evaluation(
            evaluation["id"], {}, make_anesthesia_coordinator_headers(monitor["id"])
        )
    )

    set_clock("2026-09-14T13:00:00Z")
    verified = validate_success(
        api.verify_evaluation(
            evaluation["id"],
            day_of_verification_payload(
                "CLEAR", "2026-09-13T20:00:00Z", "2026-09-14T06:00:00Z",
                escort_confirmed=True, escort_name="Sam Escort",
            ),
            make_anesthesia_coordinator_headers(verifier["id"]),
        )
    )
    assert verified["npo_solids_minutes"] == 1020
    assert verified["npo_clears_minutes"] == 420
    assert verified["final_risk_score"] == pytest.approx(20.0, abs=0.01), (
        f"ASA 2 under the moderate multiplier with no penalties is 20.0, got {verified['final_risk_score']}"
    )
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"

    hold_case_on_block(case["id"], block["id"])
    block_version = fetch_block(block["id"])["version"]

    validate_error(
        api.confirm_case(case["id"], {"expected_block_version": block_version}, SCHEDULER),
        ApiErrorId.ERR_PERMIT_LEVEL_INSUFFICIENT.value,
    )

    stalled = fetch_case(case["id"])
    assert stalled["scheduling_status"] == "BLOCK_HELD", (
        f"a refused confirmation leaves the case on its held block, got {stalled['scheduling_status']}"
    )
    assert stalled["clearance_status"] == "CLEARED"
    assert fetch_block(block["id"])["committed_minutes"] == 60, (
        "the minutes were committed at hold time and the refusal does not move them"
    )


def test_validation_path_ids_are_resolved_before_the_body_is_checked(api):
    """PRD: "The case identifier is resolved to a live row before the request body is
    read at all, so a request naming a non-existent case returns
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404) even if its body is also malformed."
    PRD: "Third, resolution of every identifier embedded in the request path, failing
    which the answer is `ERR_RESOURCE_NOT_FOUND`."
    PRD: "Fourth, on every write endpoint, structural validation of the body —
    well-formed JSON, all required fields present, no unknown fields, and a
    `service_lines` array that is neither empty nor longer than eight entries —
    failing which the answer is `ERR_INVALID_REQUEST`."

    The body is missing `evaluator_staff_id`, `airway_class_recorded` and
    `expected_case_version`, and the answer is still the path-level 404.

    Design: Corner/validations/path_ids_are_resolved_before_the_body_is_checked
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Resolution OMS", state_code="OH", recovery_bay_count=2)
    coordinator = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Mo Monitor", monitoring_certified=True
    )

    validate_error(
        api.create_evaluation(
            NON_EXISTENT_UUID,
            {"asa_class_recorded": 2},
            make_anesthesia_coordinator_headers(coordinator["id"]),
        ),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
    )


def test_validation_repointing_a_prerequisite_into_a_cycle_rejected(api):
    """PRD: "Whether a `prerequisite_case_id` arrives with the initial draft or is
    attached later, the system walks the chain outward from the proposed predecessor
    before writing anything; if the walk reaches the case being edited — meaning the
    link would make a case its own transitive prerequisite — the write is refused
    with `ERR_PREREQUISITE_CYCLE` (HTTP 409)."
    PRD: "The predecessor may also be re-pointed after drafting: a
    `SchedulingCoordinator` may attach or replace a case's `prerequisite_case_id`
    while the case's `scheduling_status` is still `DRAFT` or `BLOCK_HELD`, supplying
    the new predecessor, which must belong to the same practice and must not close a
    cycle."
    PRD: "A successful re-point increments the case's `version`."

    With C staged behind B and B behind A, pointing A at C closes a three-node cycle;
    the degenerate self-reference is refused on the same rule, and an unrelated
    predecessor is accepted.

    Design: Corner/validations/repointing_a_prerequisite_into_a_cycle_rejected
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Cycle OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(practice["id"], full_name="Pat Cycle")
    case_a = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    case_b = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-21T13:00:00Z", "2026-09-21T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="ORTHOGNATHIC",
        total_charge_cents=60000, prerequisite_case_id=case_a["id"],
    )
    case_c = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-28T13:00:00Z", "2026-09-28T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="ORTHOGNATHIC",
        total_charge_cents=70000, prerequisite_case_id=case_b["id"],
    )
    case_d = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-10-05T13:00:00Z", "2026-10-05T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="ORTHOGNATHIC",
        total_charge_cents=80000,
    )
    version_before = fetch_case(case_a["id"])["version"]

    validate_error(
        api.set_prerequisite(
            case_a["id"], {"prerequisite_case_id": case_c["id"]}, SCHEDULER
        ),
        ApiErrorId.ERR_PREREQUISITE_CYCLE.value,
    )
    validate_error(
        api.set_prerequisite(
            case_a["id"], {"prerequisite_case_id": case_a["id"]}, SCHEDULER
        ),
        ApiErrorId.ERR_PREREQUISITE_CYCLE.value,
    )

    untouched = fetch_case(case_a["id"])
    assert untouched["prerequisite_case_id"] is None, (
        "neither refusal may write a predecessor onto the case"
    )
    assert untouched["version"] == version_before, (
        f"a refused re-point does not bump the version, got {untouched['version']}"
    )

    repointed = validate_success(
        api.set_prerequisite(
            case_a["id"], {"prerequisite_case_id": case_d["id"]}, SCHEDULER
        )
    )
    assert_surgical_case(repointed)
    assert repointed["prerequisite_case_id"] == case_d["id"], (
        "an unrelated fourth draft closes no cycle and is accepted"
    )
    assert repointed["version"] == version_before + 1, (
        f"a successful re-point increments the version once, got {repointed['version']}"
    )
