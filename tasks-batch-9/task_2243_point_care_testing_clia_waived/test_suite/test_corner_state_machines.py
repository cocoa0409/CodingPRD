"""Initial states, once-only transitions, terminal lockdown and divergent cascades."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    SURVEYOR,
    SURVEYOR_BETA,
    add_finding,
    api_client,
    assert_logical_instant,
    capture_result,
    correction_decision_payload,
    create_device,
    create_operator,
    create_reagent_lot,
    create_site,
    create_storage_unit,
    deficiency_payload,
    enroll_pt,
    issue_payload,
    issue_survey,
    make_operator_headers,
    open_survey,
    patient_result_payload,
    pt_score_payload,
    qc_unlock_payload,
    read_deficiency,
    read_device,
    read_inspection,
    read_operator,
    read_pt_enrollment,
    read_pt_event,
    read_result,
    read_site,
    register_pt_event,
    retire_device,
    run_oversight,
    score_pt_event,
    set_clock,
    setup_covered_site,
    setup_site_with_verified_lot,
    training_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SEPTEMBER = "2026-09-01T08:00:00Z"
SEPTEMBER_STAMP = "2026-09-01T08:00:00.000Z"


def test_every_child_row_is_created_in_its_declared_initial_state():
    """Seven entity types are created in one chain and each starts where it must.

    PRD 3.4: "A new instrument's `status` is `ACTIVE`, its `qc_lock_reason` and
    `retirement_reason` are null, its `manual_entry_suspended` is false, its
    `last_two_level_qc_pass_on` is null, its `use_day_count` is 0, both
    compliance-rate variants read 100.00, and its `qc_next_due_at` is the date of its
    own `created_at`."

    PRD 3.5: "A new unit has `excursion_state` of `IN_RANGE`, a null
    `excursion_opened_at`, a null `last_reading_c` and a `quarantined_lot_count` of
    0." and "A received lot starts `UNVERIFIED` with null `verified_at` and null
    `quarantine_reason`."

    PRD 3.8: "The survey is created directly in `IN_PROGRESS` with
    `issued_weight_total` of 0, null `issued_on`, null `issued_by_user_id`, null
    `readiness_score_at_issue` and null `rescind_reason`." and "A new finding is
    `DRAFT` with `weight` 0, `repeat_multiplier` 1.0, `correction_round` 0, and null
    `issued_by_user_id`, `correction_narrative`, `evidence_ref` and
    `closed_by_user_id`; its `site_id` is copied from the survey rather than supplied
    by the client."

    PRD 3.7: "A new enrolment has `status` of `ENROLLED`, a `graded_event_count` of 0
    and a `fail_count_last_three` of 0." and "A new event has `status` of `PENDING`, a
    null `outcome`, null `score_pct`, null `graded_on`, null `root_cause` and
    `corrective_action`, and an `investigation_round` of 0."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243010"},
        site_overrides={
            "name": "Rheumatology POCT",
            "department_code": "DEPT-1000",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )

    device = create_device(site["id"], serial_number="SN-GL-1000")
    storage_unit = create_storage_unit(site["id"], name="Reagent Fridge 1")
    lot = create_reagent_lot(
        site["id"], storage_unit["id"],
        lot_number="LOT-A1", expiration_date="2027-01-31",
    )
    inspection = open_survey(
        site["id"], SURVEYOR,
        inspection_type="INTERNAL_READINESS", scheduled_date="2026-09-01",
    )
    finding = add_finding(
        inspection["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="CONDITION_LEVEL",
        description="No QC log for the glucose meter",
        correction_due_date="2026-10-31",
    )
    enrollment = enroll_pt(
        site["id"], analyte="GLUCOSE", program_provider="AccuProficiency"
    )
    event = register_pt_event(enrollment["id"], 1, due_date="2026-10-15")

    assert device["status"] == "ACTIVE"
    assert device["qc_next_due_at"] == "2026-09-01"
    assert device["last_two_level_qc_pass_on"] is None
    assert storage_unit["excursion_state"] == "IN_RANGE"
    assert storage_unit["excursion_opened_at"] is None
    assert storage_unit["last_reading_c"] is None
    assert storage_unit["quarantined_lot_count"] == 0
    assert lot["verification_status"] == "UNVERIFIED"
    assert lot["verified_at"] is None
    assert lot["quarantine_reason"] is None
    assert inspection["status"] == "IN_PROGRESS"
    assert inspection["issued_on"] is None
    assert inspection["issued_weight_total"] == 0.00
    assert inspection["readiness_score_at_issue"] is None
    assert finding["status"] == "DRAFT"
    assert finding["weight"] == 0.00
    assert finding["repeat_multiplier"] == 1.0
    assert finding["site_id"] == site["id"]
    assert enrollment["status"] == "ENROLLED"
    assert enrollment["graded_event_count"] == 0
    assert enrollment["fail_count_last_three"] == 0
    assert event["status"] == "PENDING"
    assert event["outcome"] is None
    assert event["investigation_round"] == 0
    assert read_site(site["id"])["open_deficiency_weight"] == 0.00


def test_recording_training_advances_both_operator_dimensions_at_once():
    """Competency and access move on the single training call, and the site follows.

    PRD 3.3: "On success the operator's `training_module_code` is stored,
    `training_completed_at` is stamped with the current logical instant, competency
    advances `PENDING → PROVISIONAL`, access advances `LOCKED_OUT → ACTIVE`,
    `lockout_reason` is cleared to null, and the operator's `version` increments. The
    site's `locked_out_operator_count` drops by one, its
    `lapsed_or_locked_operator_count` is recomputed and its posture is re-derived."

    PRD 3.2: "The new row starts `PENDING` and `LOCKED_OUT` with `lockout_reason` of
    `NEVER_TRAINED`, null `training_completed_at` and `training_module_code`, null
    `competency_expires_at` and `lapse_deadline`, `current_grace_days` of 0 and
    `consecutive_rejection_count` of 0."

    PRD 2.10: "2. Otherwise, if its `open_deficiency_weight` is at least 6.0, **or** its
    `held_result_count` is at least 3, **or** twice its `locked_out_operator_count` is
    strictly greater than its `total_operator_count`, the posture is `RESTRICTED`."

    PRD 3.9: "2. **Competency penalty.** Compute the competency gap percentage as one
    hundred multiplied by the site's `lapsed_or_locked_operator_count`, divided by its
    `total_operator_count` or by 1 when that count is 0 (whichever is larger). Multiply
    the gap percentage by 0.25, round half up to 2 decimals, and take the lesser of that
    and the cap of 25.0."

    Design: Corner/state_machines/training_moves_operator_to_provisional_and_active_and_updates_counters
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243011"},
        site_overrides={
            "name": "Dermatology POCT",
            "department_code": "DEPT-1100",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    operator = create_operator(
        site["id"], full_name="Jae Park", role_title="NURSE", hire_date="2026-03-02",
    )
    assert operator["competency_status"] == "PENDING"
    assert operator["access_status"] == "LOCKED_OUT"
    assert operator["lockout_reason"] == "NEVER_TRAINED"
    assert operator["training_completed_at"] is None
    before = read_site(site["id"], COORDINATOR)
    assert before["oversight_posture"] == "RESTRICTED"
    assert before["locked_out_operator_count"] == 1
    assert before["total_operator_count"] == 1
    assert before["inspection_readiness_score"] == 75.00

    trained = validate_success(
        api_client.record_training(
            operator["id"],
            training_payload(
                training_module_code="POCT-GLUCO-101", completed_on="2026-08-28"
            ),
            COORDINATOR,
        ),
        200,
    )

    assert trained["competency_status"] == "PROVISIONAL"
    assert trained["access_status"] == "ACTIVE"
    assert trained["lockout_reason"] is None
    assert trained["training_module_code"] == "POCT-GLUCO-101"
    assert trained["version"] == operator["version"] + 1
    assert_logical_instant(trained["training_completed_at"], SEPTEMBER_STAMP)
    assert read_operator(operator["id"])["competency_expires_at"] is None
    after = read_site(site["id"], COORDINATOR)
    assert after["locked_out_operator_count"] == 0
    assert after["lapsed_or_locked_operator_count"] == 0
    assert after["total_operator_count"] == 1
    assert after["oversight_posture"] == "OPEN"
    assert after["manual_entry_blocked"] is False
    assert after["inspection_readiness_score"] == 100.00


def test_a_finding_cannot_be_added_once_the_statement_has_been_issued():
    """The issued weight total cannot be topped up after the fact.

    PRD 3.8: "Adding a finding to a survey that is no longer `IN_PROGRESS` fails with
    `ERR_INSPECTION_NOT_IN_PROGRESS`."

    Design: Corner/state_machines/deficiency_create_after_issue_returns_inspection_not_in_progress
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243012"},
        site_overrides={
            "name": "Wound Care POCT",
            "department_code": "DEPT-1200",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    inspection = open_survey(
        site["id"], SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-09-01",
    )
    add_finding(
        inspection["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="STANDARD_LEVEL",
        description="QC log gaps", correction_due_date="2026-10-31",
    )
    issued = issue_survey(inspection["id"], SURVEYOR, issued_on="2026-09-01")
    assert issued["issued_weight_total"] == 3.00

    response = api_client.create_deficiency(
        deficiency_payload(
            inspection["id"],
            category="RESULT_REPORTING", severity="CONDITION_LEVEL",
            description="Late finding added after issuance",
            correction_due_date="2026-11-30",
        ),
        SURVEYOR,
    )

    validate_error(response, "ERR_INSPECTION_NOT_IN_PROGRESS", 409)
    assert read_inspection(inspection["id"])["issued_weight_total"] == 3.00
    _rows, meta = validate_paginated(
        api_client.list_deficiencies(
            SURVEYOR, params={"inspection_id": inspection["id"]}
        )
    )
    assert meta["total_count"] == 1
    read_back = read_site(site["id"])
    assert read_back["open_deficiency_weight"] == 3.00
    assert read_back["oversight_posture"] == "OPEN"


def test_a_graded_shipment_cannot_be_re_graded_down_to_a_failure():
    """The second score is refused and the passing 92.0 survives untouched.

    PRD 3.7: "The event must still be `PENDING`, or the request fails with
    `ERR_PT_EVENT_ALREADY_GRADED`, and `score_pct` must lie between 0.00 and 100.00
    inclusive."

    Design: Corner/state_machines/score_on_already_graded_event_returns_pt_event_already_graded
    """
    set_clock(SEPTEMBER)
    site = create_site(name="Cardiac Clinic POCT", department_code="DEPT-1300")
    enrollment = enroll_pt(
        site["id"], analyte="GLUCOSE", program_provider="AccuProficiency"
    )
    event = register_pt_event(enrollment["id"], 1, due_date="2026-08-15")
    graded = score_pt_event(event["id"], 92.0, graded_on="2026-08-20")
    assert graded["outcome"] == "PASS"
    assert graded["status"] == "PASSED"

    response = api_client.score_pt_event(
        event["id"], pt_score_payload(40.0, graded_on="2026-08-25"), COORDINATOR
    )

    validate_error(response, "ERR_PT_EVENT_ALREADY_GRADED", 409)
    read_back = read_pt_event(event["id"])
    assert read_back["score_pct"] == 92.0
    assert read_back["graded_on"] == "2026-08-20"
    assert read_back["outcome"] == "PASS"
    assert read_back["status"] == "PASSED"
    enrollment_after = read_pt_enrollment(enrollment["id"])
    assert enrollment_after["graded_event_count"] == 1
    assert enrollment_after["fail_count_last_three"] == 0
    assert enrollment_after["status"] == "ENROLLED"
    assert read_site(site["id"])["pt_unsuccessful_count"] == 0


def test_a_correction_cannot_be_decided_before_the_site_has_answered():
    """A decision is legal only from CORRECTION_SUBMITTED, never straight from OPEN.

    PRD 3.8: "A `Surveyor` then decides the plan with a `decision` of `ACCEPT` or
    `REJECT` and an optional `note`. The finding must be `CORRECTION_SUBMITTED`, and
    the acting `X-User-ID` must differ from the finding's `issued_by_user_id`."

    Design: Corner/state_machines/correction_decision_on_open_finding_returns_deficiency_not_correctable
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243013"},
        site_overrides={
            "name": "Sleep Lab POCT",
            "department_code": "DEPT-1400",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    inspection = open_survey(
        site["id"], SURVEYOR,
        inspection_type="COMPLAINT_SURVEY", scheduled_date="2026-09-01",
    )
    finding = add_finding(
        inspection["id"], SURVEYOR,
        category="RESULT_REPORTING", severity="CONDITION_LEVEL",
        description="Results not posted to the medical record",
        correction_due_date="2026-10-31",
    )
    issue_survey(inspection["id"], SURVEYOR, issued_on="2026-09-01")

    response = api_client.decide_correction(
        finding["id"],
        correction_decision_payload(
            "ACCEPT", note="closing without a plan of correction"
        ),
        SURVEYOR_BETA,
    )

    validate_error(response, "ERR_DEFICIENCY_NOT_CORRECTABLE", 409)
    read_back = read_deficiency(finding["id"])
    assert read_back["status"] == "OPEN"
    assert read_back["correction_round"] == 0
    assert read_back["closed_by_user_id"] is None
    assert read_back["weight"] == 8.00
    site_after = read_site(site["id"])
    assert site_after["open_deficiency_weight"] == 8.00
    assert site_after["oversight_posture"] == "RESTRICTED"


def test_a_retired_instrument_refuses_an_unlock_and_a_capture_with_two_error_ids():
    """One terminal state produces two different refusals from two different rungs.

    PRD 3.4: "The instrument must be `QC_LOCKED`; the confirming run must belong to
    that instrument, must have `result` of `PASS`, and must reference a lot whose
    `verification_status` is `VERIFIED`."

    PRD 2.7: "**Rank 41 — instrument usable.** On patient-result capture, posting and
    correction, the device's `status` must be `ACTIVE`. Otherwise
    `ERR_DEVICE_QC_LOCKED` (409), which also covers a `RETIRED` instrument."

    Design: Corner/state_machines/retired_device_rejects_qc_unlock_and_new_results
    """
    env = setup_site_with_verified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243014"},
        site_overrides={
            "name": "Occupational Health POCT",
            "department_code": "DEPT-1500",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Kim Salas", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-1500"},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    assert env["qc_run_level_1"]["result"] == "PASS"
    assert env["qc_run_level_2"]["result"] == "PASS"
    assert env["lot"]["verification_status"] == "VERIFIED"
    retired = retire_device(
        env["device"]["id"],
        reason="instrument decommissioned - end of service life",
    )
    assert retired["status"] == "RETIRED"
    assert retired["qc_lock_reason"] is None

    unlock_response = api_client.qc_unlock_device(
        env["device"]["id"],
        qc_unlock_payload(
            env["qc_run_level_1"]["id"],
            note="attempting to revive a retired instrument",
        ),
        COORDINATOR,
    )
    capture_response = api_client.create_test_result(
        patient_result_payload(
            env["device"]["id"], env["operator"]["id"], env["lot"]["id"],
            patient_mrn="MRN-9001", measured_value=105.0,
        ),
        make_operator_headers(env["operator"]["id"]),
    )

    validate_error(unlock_response, "ERR_INVALID_STATE", 409)
    validate_error(capture_response, "ERR_DEVICE_QC_LOCKED", 409)
    device = read_device(env["device"]["id"])
    assert device["status"] == "RETIRED"
    assert device["retirement_reason"] == (
        "instrument decommissioned - end of service life"
    )
    _rows, meta = validate_paginated(
        api_client.list_test_results(
            ADMIN, params={"device_id": env["device"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_site(env["site"]["id"])["site_qc_compliance_index"] == 100.00


def test_issuance_is_once_only_and_never_additive():
    """A second issue would have doubled 8.00 into a suspending 16.00.

    PRD 3.8: "Issuing the deficiency statement is the moment citations become real. A
    `Surveyor` supplies the `issued_on` date; the survey must be `IN_PROGRESS` and
    must hold at least one `DRAFT` finding, an empty statement being rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/second_issue_of_the_same_inspection_returns_inspection_not_in_progress
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243015"},
        site_overrides={
            "name": "Travel Clinic POCT",
            "department_code": "DEPT-1600",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    inspection = open_survey(
        site["id"], SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-09-01",
    )
    finding = add_finding(
        inspection["id"], SURVEYOR,
        category="PERSONNEL_COMPETENCY", severity="CONDITION_LEVEL",
        description="No competency records on file",
        correction_due_date="2026-10-31",
    )
    issued = issue_survey(inspection["id"], SURVEYOR, issued_on="2026-09-01")
    assert issued["status"] == "DEFICIENCIES_ISSUED"
    assert issued["issued_weight_total"] == 8.00
    assert issued["readiness_score_at_issue"] == 80.00

    response = api_client.issue_inspection(
        inspection["id"], issue_payload(issued_on="2026-09-02"), SURVEYOR
    )

    validate_error(response, "ERR_INSPECTION_NOT_IN_PROGRESS", 409)
    read_back = read_inspection(inspection["id"])
    assert read_back["issued_weight_total"] == 8.00
    assert read_back["issued_on"] == "2026-09-01"
    site_after = read_site(site["id"])
    assert site_after["open_deficiency_weight"] == 8.00
    assert site_after["oversight_posture"] == "RESTRICTED"
    finding_after = read_deficiency(finding["id"])
    assert finding_after["weight"] == 8.00
    assert finding_after["repeat_multiplier"] == 1.0


def test_the_overdue_branch_of_the_sweep_locks_the_instrument_but_holds_nothing():
    """The same target state QC_LOCKED arrives with a strictly smaller cascade.

    PRD 3.9: "Every instrument whose `status` is `ACTIVE` and whose `qc_next_due_at`
    is strictly before the current logical date moves to `QC_LOCKED` with
    `qc_lock_reason` of `QC_OVERDUE`. This branch diverges from the control-failure
    branch of §3.4 in one important respect: `PENDING_REVIEW` results on the
    instrument are **not** held. Only the site's `site_qc_compliance_index` and
    `inspection_readiness_score` are recomputed."

    Design: Corner/state_machines/qc_overdue_lock_leaves_pending_results_unheld_unlike_qc_failure_lock
    """
    env = setup_site_with_verified_lot(
        clock="2026-08-01T08:00:00Z",
        certificate_overrides={"certificate_number": "45D2243016"},
        site_overrides={
            "name": "Anticoag Clinic POCT",
            "department_code": "DEPT-1700",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Lena Sorel", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-1700", "qc_frequency_days": 1},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    result = capture_result(env, patient_mrn="MRN-7001", measured_value=98.0)
    assert result["posting_status"] == "PENDING_REVIEW"
    set_clock("2026-08-05T09:00:00Z")

    summary = run_oversight(note="daily QC-schedule sweep")

    assert summary["devices_qc_locked"] == 1
    assert summary["competencies_lapsed"] == 0
    assert summary["sites_posture_changed"] == 0
    device = read_device(env["device"]["id"])
    assert device["status"] == "QC_LOCKED"
    assert device["qc_lock_reason"] == "QC_OVERDUE"
    read_back = read_result(result["id"], COORDINATOR)
    assert read_back["posting_status"] == "PENDING_REVIEW"
    assert read_back["held_by_device_lock_at"] is None
    site = read_site(env["site"]["id"], COORDINATOR)
    assert site["held_result_count"] == 0
    assert site["oversight_posture"] == "OPEN"
    assert site["site_qc_compliance_index"] == 100.00
    assert site["inspection_readiness_score"] == 100.00
    assert_logical_instant(site["last_oversight_run_at"], "2026-08-05T09:00:00.000Z")
