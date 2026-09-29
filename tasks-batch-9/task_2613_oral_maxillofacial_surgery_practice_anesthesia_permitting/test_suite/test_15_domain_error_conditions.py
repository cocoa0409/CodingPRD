"""Domain error conditions: duplicate permits, clock monotonicity, remediation
windows, prohibitive risk bands, referral coordination, consignment credit and
the sedation staffing matrix.
"""
from test_helpers import (
    ADMIN,
    INVENTORY,
    SCHEDULER,
    ApiErrorId,
    api_client as api,
    assert_block_ledger_conserved,
    assert_lot_quantities_consistent,
    make_anesthesia_coordinator_headers,
    parse_iso,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_error_second_open_permit_for_one_practice_rejected():
    """A practice already holding an APPLIED permit cannot file a second one.

    PRD: "A practice may hold at most one permit whose `status` is outside
    `EXPIRED` and `REVOKED`; a second application while one is open is refused
    with `ERR_PERMIT_ALREADY_OPEN` (HTTP 409)."

    Design: Corner/errors/second_open_permit_for_one_practice_rejected
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Duplicate OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    first = validate_success(
        api.create_permit(
            {
                "practice_id": prac_id,
                "permit_level": "MINIMAL_SEDATION",
                "applied_on": "2026-08-25T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    assert first["status"] == "APPLIED"

    validate_error(
        api.create_permit(
            {
                "practice_id": prac_id,
                "permit_level": "DEEP_SEDATION_GENERAL",
                "applied_on": "2026-09-01T00:00:00Z",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_PERMIT_ALREADY_OPEN.value,
    )

    permits, meta = validate_paginated(api.list_permits(ADMIN, {"practice_id": prac_id}))
    assert meta["total_count"] == 1
    assert [row["permit_level"] for row in permits] == ["MINIMAL_SEDATION"]


def test_error_rewinding_the_logical_clock_rejected():
    """Re-setting the same instant is accepted; any earlier instant is refused.

    PRD: "The clock is monotonic: a requested value that is earlier than the
    current value is rejected with `ERR_CLOCK_MONOTONIC_VIOLATION` (HTTP 409),
    while a value equal to the current one is accepted and leaves the clock where
    it is."

    PRD: "Any operator role may advance the clock by supplying a `current_utc`
    instant, and the response reports both the newly effective `current_utc` and
    the `previous_utc` value it displaced."

    Design: Corner/errors/rewinding_the_logical_clock_rejected
    """
    set_clock("2026-09-05T12:00:00Z")

    same = validate_success(
        api.set_clock({"current_utc": "2026-09-05T12:00:00Z"}, SCHEDULER)
    )
    assert parse_iso(same["current_utc"]) == parse_iso("2026-09-05T12:00:00Z")
    assert parse_iso(same["previous_utc"]) == parse_iso("2026-09-05T12:00:00Z"), (
        "an equal value is accepted and leaves the clock where it is"
    )

    validate_error(
        api.set_clock({"current_utc": "2026-09-05T11:59:59Z"}, SCHEDULER),
        ApiErrorId.ERR_CLOCK_MONOTONIC_VIOLATION.value,
    )

    unchanged = validate_success(
        api.set_clock({"current_utc": "2026-09-05T12:00:00Z"}, SCHEDULER)
    )
    assert parse_iso(unchanged["previous_utc"]) == parse_iso("2026-09-05T12:00:00Z"), (
        "the refused rewind must not have moved the clock"
    )


def test_error_remediation_after_the_deadline_rejected():
    """With compliance fully restored the late attestation still loses to the window.

    PRD: "Second, the logical clock must be at or before
    `remediation_deadline_at`; a clock past the deadline yields
    `ERR_REMEDIATION_WINDOW_EXPIRED` (HTTP 409)."

    PRD: "Third, the `drill_compliance_ratio`, recomputed at that instant, must
    be at or above 0.75; a still-lapsed practice is refused with
    `ERR_DRILL_COMPLIANCE_LAPSED` (HTTP 409)."

    Design: Corner/errors/remediation_after_the_deadline_rejected
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Window Lapse OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    monitor = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Mo Monitor",
                "role_type": "ANESTHESIA_MONITOR",
                "monitoring_certified": True,
            },
            ADMIN,
        ),
        201,
    )
    nurse = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Rhea Nurse",
                "role_type": "RECOVERY_NURSE",
            },
            ADMIN,
        ),
        201,
    )
    participants = [monitor["id"], nurse["id"]]
    permit = validate_success(
        api.create_permit(
            {
                "practice_id": prac_id,
                "permit_level": "MODERATE_SEDATION",
                "applied_on": "2026-08-25T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    for drill_type, conducted_at in (
        ("AIRWAY_OBSTRUCTION", "2026-08-20T09:00:00Z"),
        ("LARYNGOSPASM", "2026-08-21T09:00:00Z"),
    ):
        validate_success(
            api.create_drill(
                {
                    "practice_id": prac_id,
                    "drill_type": drill_type,
                    "conducted_at": conducted_at,
                    "participant_staff_ids": participants,
                },
                ADMIN,
            ),
            201,
        )
    inspection = validate_success(
        api.create_inspection(
            {"permit_id": permit["id"], "scheduled_for": "2026-09-02T09:00:00Z"}, ADMIN
        ),
        201,
    )
    set_clock("2026-09-02T10:00:00Z")
    validate_success(
        api.record_inspection_result(
            inspection["id"],
            {
                "minor_deficiency_count": 0,
                "major_deficiency_count": 0,
                "critical_deficiency_count": 0,
            },
            ADMIN,
        )
    )
    for drill_type, conducted_at in (
        ("LOCAL_ANESTHETIC_TOXICITY", "2026-09-02T09:30:00Z"),
        ("CARDIAC_ARREST", "2026-09-02T09:45:00Z"),
    ):
        validate_success(
            api.create_drill(
                {
                    "practice_id": prac_id,
                    "drill_type": drill_type,
                    "conducted_at": conducted_at,
                    "participant_staff_ids": participants,
                },
                ADMIN,
            ),
            201,
        )

    on_probation = validate_success(api.get_permit(permit["id"], ADMIN))
    assert on_probation["status"] == "PROBATION"
    assert parse_iso(on_probation["remediation_deadline_at"]) == parse_iso(
        "2026-10-02T10:00:00Z"
    )
    assert float(on_probation["drill_compliance_ratio"]) == 1.00, (
        "all four required types are covered inside the trailing window"
    )

    set_clock("2026-10-03T10:00:00Z")
    validate_error(
        api.remediate_permit(
            permit["id"], {"attestation_note": "Filed one day late."}, ADMIN
        ),
        ApiErrorId.ERR_REMEDIATION_WINDOW_EXPIRED.value,
    )

    after = validate_success(api.get_permit(permit["id"], ADMIN))
    assert after["status"] == "PROBATION"
    assert parse_iso(after["remediation_deadline_at"]) == parse_iso(
        "2026-10-02T10:00:00Z"
    )
    assert after["probation_count"] == 1
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["sedation_privilege_state"]
        == "RESTRICTED"
    )


def test_error_clearing_a_prohibitive_case_rejected_but_deferral_allowed():
    """A 56.0 final score blocks CLEAR while DEFER records the very same score.

    PRD: "Then the band: the recomputed `risk_band` must not be `PROHIBITIVE`,
    or the answer is `ERR_RISK_BAND_PROHIBITIVE` (HTTP 409)."

    PRD: "`DEFER` moves it from `EVALUATED` to `DEFERRED` and skips every
    clinical gate — no fasting, escort, or band check is enforced on that
    branch."

    PRD: "Verification then computes the two fasting intervals:
    `npo_solids_minutes` is the whole minutes from `fasting_solids_last_at` to
    the logical clock at verification, and `npo_clears_minutes` is the whole
    minutes from `fasting_clears_last_at` to that same instant."

    Design: Corner/errors/clearing_a_prohibitive_case_rejected_but_deferral_allowed
    """
    set_clock("2026-09-13T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Band OMS", "state_code": "OH", "recovery_bay_count": 2}, ADMIN
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
                "acls_expires_on": "2027-06-30T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    author = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Nia Author",
                "role_type": "ANESTHESIA_MONITOR",
                "monitoring_certified": True,
            },
            ADMIN,
        ),
        201,
    )
    verifier = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Val Verifier",
                "role_type": "ANESTHESIA_MONITOR",
                "monitoring_certified": True,
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Fragile",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 4,
                "airway_class": 4,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "monitor_staff_id": author["id"],
                "planned_anesthesia_level": "MODERATE_SEDATION",
                "procedure_category": "PATHOLOGY",
                "planned_start": "2026-09-14T13:00:00Z",
                "planned_end": "2026-09-14T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )
    evaluation = validate_success(
        api.create_evaluation(
            case["id"],
            {
                "evaluator_staff_id": author["id"],
                "asa_class_recorded": 4,
                "airway_class_recorded": 4,
                "comorbidity_count": 0,
                "expected_case_version": case["version"],
            },
            make_anesthesia_coordinator_headers(author["id"]),
        ),
        201,
    )
    assert float(evaluation["provisional_risk_score"]) == 56.0, (
        "40 base points plus 16 airway points, multiplied by 1.0 for MODERATE_SEDATION"
    )
    assert evaluation["risk_band"] == "PROHIBITIVE"
    validate_success(
        api.sign_evaluation(
            evaluation["id"], {}, make_anesthesia_coordinator_headers(author["id"])
        )
    )

    set_clock("2026-09-14T13:00:00Z")
    fasting = {
        "fasting_solids_last_at": "2026-09-13T20:00:00Z",
        "fasting_clears_last_at": "2026-09-14T06:00:00Z",
        "escort_confirmed": True,
        "escort_name": "Sam Escort",
    }
    validate_error(
        api.verify_evaluation(
            evaluation["id"],
            dict(fasting, intent="CLEAR"),
            make_anesthesia_coordinator_headers(verifier["id"]),
        ),
        ApiErrorId.ERR_RISK_BAND_PROHIBITIVE.value,
    )
    refused = validate_success(api.get_evaluation(evaluation["id"], ADMIN))
    assert refused["status"] == "SIGNED"
    assert (
        validate_success(api.get_surgical_case(case["id"], SCHEDULER))["clearance_status"]
        == "EVALUATED"
    )

    deferred = validate_success(
        api.verify_evaluation(
            evaluation["id"],
            dict(fasting, intent="DEFER"),
            make_anesthesia_coordinator_headers(verifier["id"]),
        )
    )
    assert deferred["status"] == "VERIFIED"
    assert float(deferred["final_risk_score"]) == 56.0
    assert deferred["risk_band"] == "PROHIBITIVE"
    assert deferred["npo_solids_minutes"] == 1020
    assert deferred["npo_clears_minutes"] == 420
    assert (
        validate_success(api.get_surgical_case(case["id"], SCHEDULER))["clearance_status"]
        == "DEFERRED"
    )


def test_error_unacknowledged_referral_blocks_confirmation():
    """A cleared LOCAL_ONLY case still fails confirmation on the referral gate.

    PRD: "Ninth, referral coordination: a case whose
    `referral_coordination_status` is still `PENDING` — meaning a `THIRD_MOLAR`
    or `ORTHOGNATHIC` case with a `referring_provider_npi` whose referring
    provider has not signed off — is refused with
    `ERR_REFERRAL_ACKNOWLEDGEMENT_REQUIRED` (HTTP 409); `NOT_REQUIRED` and
    `ACKNOWLEDGED` both pass."

    PRD: "A confirmation that survives all eleven gates advances the case's
    `scheduling_status` from `BLOCK_HELD` to `CONFIRMED` and increments the
    case's `version`."

    Design: Corner/errors/unacknowledged_referral_blocks_confirmation
    """
    set_clock("2026-09-14T07:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Coordinate OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    author = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Nia Author",
                "role_type": "ANESTHESIA_MONITOR",
            },
            ADMIN,
        ),
        201,
    )
    verifier = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Val Verifier",
                "role_type": "ANESTHESIA_MONITOR",
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Referred",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
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
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "THIRD_MOLAR",
                "planned_start": "2026-09-14T13:00:00Z",
                "planned_end": "2026-09-14T14:00:00Z",
                "total_charge_cents": 50000,
                "referring_provider_npi": "1447382910",
            },
            SCHEDULER,
        ),
        201,
    )
    assert case["referral_coordination_status"] == "PENDING"
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
    held = validate_success(
        api.hold_block(case["id"], {"block_id": block["id"]}, SCHEDULER)
    )
    assert held["scheduling_status"] == "BLOCK_HELD"
    block_held = validate_success(api.get_block_time(block["id"], SCHEDULER))
    assert block_held["committed_minutes"] == 60
    assert_block_ledger_conserved(block_held)

    validate_error(
        api.confirm_case(
            case["id"], {"expected_block_version": block_held["version"]}, SCHEDULER
        ),
        ApiErrorId.ERR_REFERRAL_ACKNOWLEDGEMENT_REQUIRED.value,
    )
    refused_case = validate_success(api.get_surgical_case(case["id"], SCHEDULER))
    assert refused_case["clearance_status"] == "CLEARED"
    assert refused_case["scheduling_status"] == "BLOCK_HELD"
    assert (
        validate_success(api.get_block_time(block["id"], SCHEDULER))["committed_minutes"]
        == 60
    ), "the refusal moved no minute counter"

    acknowledged = validate_success(
        api.record_referral_coordination(
            case["id"], {"acknowledged_by_npi": "1447382910"}, SCHEDULER
        )
    )
    assert acknowledged["referral_coordination_status"] == "ACKNOWLEDGED"

    block_now = validate_success(api.get_block_time(block["id"], SCHEDULER))
    confirmed = validate_success(
        api.confirm_case(
            case["id"], {"expected_block_version": block_now["version"]}, SCHEDULER
        )
    )
    assert confirmed["scheduling_status"] == "CONFIRMED", (
        "the only thing that changed is the referral dimension"
    )
    block_after = validate_success(api.get_block_time(block["id"], SCHEDULER))
    assert block_after["committed_minutes"] == 60
    assert_block_ledger_conserved(block_after)


def test_error_consignment_liability_over_the_credit_limit_rejected():
    """The credit limit is tested against liability net of the consignment credit.

    PRD: "Before any new reservation is admitted, the practice's exposure
    including that reservation's liability is compared against
    `consignment_credit_limit_cents`, and a request that would push the total
    past the limit is refused with `ERR_CONSIGNMENT_CREDIT_LIMIT_EXCEEDED`
    (HTTP 409)."

    PRD: "`consignment_credit_cents` is twenty percent of
    `line_subtotal_cents`, rounded half-up to whole cents, when the lot's
    `is_consignment` is true, and 0 when it is false."

    PRD: "While `HELD`, and still after it becomes `CONSUMED`, the liability is
    `line_subtotal_cents` less `consignment_credit_cents`."

    Design: Corner/errors/consignment_liability_over_the_credit_limit_rejected
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {
                "name": "Credit OMS",
                "state_code": "OH",
                "recovery_bay_count": 2,
                "consignment_credit_limit_cents": 40000,
            },
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Credit",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "IMPLANT",
                "planned_start": "2026-09-20T13:00:00Z",
                "planned_end": "2026-09-20T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )
    lot = validate_success(
        api.create_implant_lot(
            {
                "practice_id": prac_id,
                "manufacturer_code": "NOBEL",
                "catalog_reference": "NB-4310",
                "diameter_mm": 4.3,
                "length_mm": 10.0,
                "unit_cost_cents": 30000,
                "quantity_on_hand": 5,
                "expiry_date": "2027-01-31T00:00:00Z",
                "is_consignment": True,
            },
            INVENTORY,
        ),
        201,
    )
    lot_version = lot["version"]

    validate_error(
        api.create_reservation(
            {
                "case_id": case["id"],
                "lot_id": lot["id"],
                "quantity": 2,
                "expected_lot_version": lot_version,
            },
            INVENTORY,
        ),
        ApiErrorId.ERR_CONSIGNMENT_CREDIT_LIMIT_EXCEEDED.value,
    )
    lot_after_refusal = validate_success(api.get_implant_lot(lot["id"], INVENTORY))
    assert lot_after_refusal["quantity_reserved"] == 0
    assert lot_after_refusal["available_quantity"] == 5
    assert lot_after_refusal["version"] == lot_version, (
        "a refused reservation must not touch the lot"
    )
    assert_lot_quantities_consistent(lot_after_refusal)
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["consignment_committed_cents"]
        == 0
    )

    reservation = validate_success(
        api.create_reservation(
            {
                "case_id": case["id"],
                "lot_id": lot["id"],
                "quantity": 1,
                "expected_lot_version": lot_version,
            },
            INVENTORY,
        ),
        201,
    )
    assert reservation["status"] == "HELD"
    assert reservation["line_subtotal_cents"] == 30000
    assert reservation["consignment_credit_cents"] == 6000
    assert reservation["consignment_liability_cents"] == 24000
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["consignment_committed_cents"]
        == 24000
    ), "a single unit's 24000 of liability fits under the 40000 limit"


def test_error_minimal_sedation_case_without_a_monitor_rejected():
    """Step one of the staffing matrix fires alone on a fully permitted practice.

    PRD: "For a `MINIMAL_SEDATION` case a monitor is required but need not be
    certified, and neither a current surgeon ACLS card nor a dedicated recovery
    nurse is required."

    PRD: "The five steps run in this order: whether a monitor is required and
    `monitor_staff_id` is null; whether a monitor is required and that monitor's
    `role_type` is something other than `ANESTHESIA_MONITOR`; whether
    certification is required and the monitor's `monitoring_certified` is false;
    whether a surgeon ACLS card is required and the `primary_surgeon_id`'s
    `acls_expires_on` is at or before the case's `planned_start`, which a null
    `acls_expires_on` also fails since it means never certified; and whether a
    dedicated recovery nurse is required and the practice has no `StaffMember`
    at all whose `role_type` is `RECOVERY_NURSE`."

    PRD: "Any of the five failing yields `ERR_STAFFING_RATIO_UNMET` (HTTP 409)."

    Design: Corner/errors/minimal_sedation_case_without_a_monitor_rejected
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Staffing OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]

    def hire(full_name, role_type):
        return validate_success(
            api.create_staff_member(
                {
                    "practice_id": prac_id,
                    "full_name": full_name,
                    "role_type": role_type,
                },
                ADMIN,
            ),
            201,
        )

    surgeon = hire("Dr Alma Reyes", "SURGEON")
    author = hire("Nia Author", "ANESTHESIA_MONITOR")
    nurse = hire("Rhea Nurse", "RECOVERY_NURSE")
    verifier = hire("Val Verifier", "ANESTHESIA_MONITOR")
    permit = validate_success(
        api.create_permit(
            {
                "practice_id": prac_id,
                "permit_level": "MINIMAL_SEDATION",
                "applied_on": "2026-08-25T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    for drill_type, conducted_at in (
        ("AIRWAY_OBSTRUCTION", "2026-08-20T09:00:00Z"),
        ("LOCAL_ANESTHETIC_TOXICITY", "2026-08-21T09:00:00Z"),
    ):
        validate_success(
            api.create_drill(
                {
                    "practice_id": prac_id,
                    "drill_type": drill_type,
                    "conducted_at": conducted_at,
                    "participant_staff_ids": [author["id"], nurse["id"]],
                },
                ADMIN,
            ),
            201,
        )
    inspection = validate_success(
        api.create_inspection(
            {"permit_id": permit["id"], "scheduled_for": "2026-09-02T09:00:00Z"}, ADMIN
        ),
        201,
    )
    set_clock("2026-09-02T10:00:00Z")
    validate_success(
        api.record_inspection_result(
            inspection["id"],
            {
                "minor_deficiency_count": 0,
                "major_deficiency_count": 0,
                "critical_deficiency_count": 0,
            },
            ADMIN,
        )
    )
    live_permit = validate_success(api.get_permit(permit["id"], ADMIN))
    assert live_permit["status"] == "ACTIVE"
    assert float(live_permit["drill_compliance_ratio"]) == 1.00
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["sedation_privilege_state"]
        == "PERMITTED"
    )

    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Unmonitored",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
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
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "MINIMAL_SEDATION",
                "procedure_category": "IMPLANT",
                "planned_start": "2026-09-14T13:00:00Z",
                "planned_end": "2026-09-14T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )
    assert case["monitor_staff_id"] is None, "no monitor was nominated at creation"
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
    set_clock("2026-09-14T13:00:00Z")
    verified = validate_success(
        api.verify_evaluation(
            evaluation["id"],
            {
                "intent": "CLEAR",
                "fasting_solids_last_at": "2026-09-13T20:00:00Z",
                "fasting_clears_last_at": "2026-09-14T06:00:00Z",
                "escort_confirmed": True,
                "escort_name": "Sam Escort",
            },
            make_anesthesia_coordinator_headers(verifier["id"]),
        )
    )
    assert float(verified["final_risk_score"]) == 16.0, "20 * 0.8 with no penalties"
    assert verified["risk_band"] == "LOW"
    cleared = validate_success(api.get_surgical_case(case["id"], SCHEDULER))
    assert cleared["clearance_status"] == "CLEARED"

    validate_success(api.hold_block(case["id"], {"block_id": block["id"]}, SCHEDULER))
    block_held = validate_success(api.get_block_time(block["id"], SCHEDULER))
    validate_error(
        api.confirm_case(
            case["id"], {"expected_block_version": block_held["version"]}, SCHEDULER
        ),
        ApiErrorId.ERR_STAFFING_RATIO_UNMET.value,
    )
    after = validate_success(api.get_surgical_case(case["id"], SCHEDULER))
    assert after["scheduling_status"] == "BLOCK_HELD", (
        "the refused confirmation leaves the case holding its block"
    )
    assert after["clearance_status"] == "CLEARED"
