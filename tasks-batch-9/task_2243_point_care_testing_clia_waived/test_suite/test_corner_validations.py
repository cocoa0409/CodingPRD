"""Conditional requirements, two-conjunct rules and temporal gates on capture."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    api_client,
    assert_logical_instant,
    capture_result,
    capture_results,
    create_device,
    create_operator,
    create_site,
    create_trained_operator,
    director_payload,
    make_operator_headers,
    patient_result_payload,
    post_payload,
    read_device,
    read_operator,
    read_result,
    read_site,
    record_qc_run,
    set_clock,
    setup_site_with_verified_lot,
    training_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SEPTEMBER = "2026-09-01T08:00:00Z"
SEPTEMBER_STAMP = "2026-09-01T08:00:00.000Z"
AUGUST_MORNING = "2026-08-01T08:00:00Z"
AUGUST_MORNING_STAMP = "2026-08-01T08:00:00.000Z"


def test_a_hand_keyed_result_without_a_reason_dies_before_the_permission_gate():
    """The 400 wins even though the site and the instrument would both allow it.

    PRD 2.7: "**Rank 21 — manual-entry reason.** On patient-result capture, an
    `entry_mode` of `MANUAL` requires a non-empty `manual_entry_reason`. Otherwise
    `ERR_MANUAL_ENTRY_REASON_REQUIRED` (400)."

    Design: Corner/validations/manual_entry_result_without_reason_returns_manual_entry_reason_required
    """
    env = setup_site_with_verified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243030"},
        site_overrides={
            "name": "Infusion Suite POCT",
            "department_code": "DEPT-2200",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Rhea Talbot", "hire_date": "2026-01-05"},
        device_overrides={
            "serial_number": "SN-GL-2200", "connectivity_mode": "MANUAL_ENTRY",
        },
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    assert env["lot"]["verification_status"] == "VERIFIED"

    response = api_client.create_test_result(
        patient_result_payload(
            env["device"]["id"], env["operator"]["id"], env["lot"]["id"],
            patient_mrn="MRN-3001", measured_value=112.0, entry_mode="MANUAL",
        ),
        make_operator_headers(env["operator"]["id"]),
    )

    validate_error(response, "ERR_MANUAL_ENTRY_REASON_REQUIRED", 400)
    _rows, meta = validate_paginated(
        api_client.list_test_results(
            ADMIN, params={"device_id": env["device"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    site = read_site(env["site"]["id"], COORDINATOR)
    assert site["oversight_posture"] == "OPEN"
    assert site["manual_entry_blocked"] is False


def test_a_hand_keyed_result_reaches_the_record_only_through_a_second_pair_of_eyes():
    """The keying operator's own post is refused; a colleague's post succeeds.

    PRD 3.6: "When the result's `entry_mode` is `MANUAL`, the acting `X-User-ID` must
    differ from the result's `operator_id`, or the post is refused with
    `ERR_SEGREGATION_OF_DUTIES`. On success the result moves to `POSTED`:
    `posted_value` becomes the `measured_value` on a first post, or the most recent
    corrected value when the result arrived from `CORRECTION_PENDING`;
    `posted_by_user_id` and `posted_at` are recorded; and `version` increments."

    Design: Corner/validations/manual_entry_result_posts_only_after_a_second_person_review
    """
    env = setup_site_with_verified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243031"},
        site_overrides={
            "name": "Pre-Op Clinic POCT",
            "department_code": "DEPT-2300",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Sam Ito", "hire_date": "2026-01-05"},
        device_overrides={
            "serial_number": "SN-GL-2300", "connectivity_mode": "MANUAL_ENTRY",
        },
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    reviewer = create_trained_operator(
        env["site"]["id"], full_name="Tia Moreau",
        role_title="NURSE", hire_date="2026-02-05",
    )
    result = capture_result(
        env, patient_mrn="MRN-3101", measured_value=112.0, entry_mode="MANUAL",
        manual_entry_reason="meter interface offline during the draw",
    )
    assert result["posting_status"] == "PENDING_REVIEW"
    assert result["manual_entry_reason"] == (
        "meter interface offline during the draw"
    )

    self_post = api_client.post_test_result(
        result["id"], post_payload(attestation="self review by the keying operator"),
        make_operator_headers(env["operator"]["id"]),
    )
    validate_error(self_post, "ERR_SEGREGATION_OF_DUTIES", 422)

    posted = validate_success(
        api_client.post_test_result(
            result["id"],
            post_payload(
                attestation="value re-read from the meter display and confirmed"
            ),
            make_operator_headers(reviewer["id"]),
        ),
        200,
    )

    assert posted["posting_status"] == "POSTED"
    assert posted["posted_value"] == 112.0
    assert posted["posted_by_user_id"] == reviewer["id"]
    assert_logical_instant(posted["posted_at"], SEPTEMBER_STAMP)
    read_back = read_result(result["id"], COORDINATOR)
    assert read_back["operator_id"] == env["operator"]["id"]
    assert read_back["correction_count"] == 0
    site = read_site(env["site"]["id"], COORDINATOR)
    assert site["held_result_count"] == 0
    assert site["oversight_posture"] == "OPEN"


def test_both_conjuncts_of_director_eligibility_are_enforced_separately():
    """An ineligible title and an untrained physician fail with the same error id.

    PRD 3.2: "A `ProgramAdmin` nominates one by supplying a
    `lab_director_operator_id`; the nominee must already exist on the roster, must
    belong to this site (a nominee from another site fails with
    `ERR_CROSS_SITE_REFERENCE`), must hold a `role_title` of `PHYSICIAN`,
    `DOCTORAL_SCIENTIST` or `MIDLEVEL_PRACTITIONER`, and must have a
    `competency_status` of `PROVISIONAL` or `COMPETENT`. A nominee who fails either of
    the last two tests is rejected with `ERR_DIRECTOR_NOT_QUALIFIED`."

    Design: Corner/validations/director_nomination_requires_qualified_role_title_and_current_competency
    """
    set_clock(SEPTEMBER)
    site = create_site(name="Student Health POCT", department_code="DEPT-2400")
    assistant = create_trained_operator(
        site["id"], full_name="Uma Fields",
        role_title="MEDICAL_ASSISTANT", hire_date="2026-01-05",
    )
    physician = create_operator(
        site["id"], full_name="Dr. Val Ibarra",
        role_title="PHYSICIAN", hire_date="2026-01-06",
    )
    assert assistant["competency_status"] == "PROVISIONAL"
    assert physician["competency_status"] == "PENDING"

    ineligible_title = api_client.assign_director(
        site["id"], director_payload(assistant["id"]), ADMIN
    )
    ineligible_competency = api_client.assign_director(
        site["id"], director_payload(physician["id"]), ADMIN
    )

    validate_error(ineligible_title, "ERR_DIRECTOR_NOT_QUALIFIED", 422)
    validate_error(ineligible_competency, "ERR_DIRECTOR_NOT_QUALIFIED", 422)
    assert read_site(site["id"])["lab_director_operator_id"] is None

    trained = validate_success(
        api_client.record_training(
            physician["id"],
            training_payload(
                training_module_code="POCT-DIRECTOR-101", completed_on="2026-08-25"
            ),
            COORDINATOR,
        ),
        200,
    )
    assert trained["competency_status"] == "PROVISIONAL"

    assigned = validate_success(
        api_client.assign_director(
            site["id"], director_payload(physician["id"]), ADMIN
        ),
        200,
    )

    assert assigned["lab_director_operator_id"] == physician["id"]
    assert read_site(site["id"])["lab_director_operator_id"] == physician["id"]


def test_a_capture_past_the_compliance_horizon_is_refused_while_the_device_stays_active():
    """Rank 55 compares the clock to the horizon, not to the instrument's status.

    PRD 3.6: "The current logical date must be on or before the instrument's
    `qc_next_due_at`, or the capture is refused with `ERR_QC_OVERDUE`."

    PRD 3.4: "It is the `last_two_level_qc_pass_on` date advanced by
    `qc_frequency_days` whole days; while `last_two_level_qc_pass_on` is still null, it
    stays equal to the instrument's creation date."

    Design: Corner/validations/result_capture_after_qc_next_due_returns_qc_overdue
    """
    env = setup_site_with_verified_lot(
        clock=AUGUST_MORNING,
        certificate_overrides={"certificate_number": "45D2243032"},
        site_overrides={
            "name": "Renal Clinic POCT",
            "department_code": "DEPT-2500",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Wes Nakamura", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-2500", "qc_frequency_days": 1},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    horizon = read_device(env["device"]["id"], COORDINATOR)
    assert horizon["last_two_level_qc_pass_on"] == "2026-08-01"
    assert horizon["qc_next_due_at"] == "2026-08-02"
    set_clock("2026-08-03T09:00:00Z")

    response = api_client.create_test_result(
        patient_result_payload(
            env["device"]["id"], env["operator"]["id"], env["lot"]["id"],
            patient_mrn="MRN-3201", measured_value=99.0,
        ),
        make_operator_headers(env["operator"]["id"]),
    )

    validate_error(response, "ERR_QC_OVERDUE", 422)
    device = read_device(env["device"]["id"], COORDINATOR)
    assert device["status"] == "ACTIVE"
    assert device["qc_lock_reason"] is None
    _rows, meta = validate_paginated(
        api_client.list_test_results(
            ADMIN, params={"device_id": env["device"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_the_suspended_instrument_refuses_a_hand_keyed_value_but_takes_interfaced_traffic():
    """One instrument in one state answers two entry modes differently.

    PRD 3.6: "A `MANUAL` `entry_mode` demands a non-empty `manual_entry_reason`,
    reported as `ERR_MANUAL_ENTRY_REASON_REQUIRED` when missing, and it additionally
    demands that the site's `manual_entry_blocked` be false **and** the instrument's
    `manual_entry_suspended` be false, reported as `ERR_MANUAL_ENTRY_NOT_PERMITTED`
    otherwise. That last rule is the teeth behind the oversight posture: a restricted
    or suspended site can still receive interfaced traffic, but it cannot type values
    in by hand."

    Design: Corner/validations/manual_entry_gate_applies_only_when_entry_mode_is_manual
    """
    env = setup_site_with_verified_lot(
        clock=AUGUST_MORNING,
        certificate_overrides={"certificate_number": "45D2243033"},
        site_overrides={
            "name": "Surgical Day Unit POCT",
            "department_code": "DEPT-2600",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Yara Costa", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-2601"},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    hand_keyed_device = create_device(
        env["site"]["id"], serial_number="SN-GL-2602",
        connectivity_mode="MANUAL_ENTRY",
    )
    held = capture_results(env, 3)
    failing_run = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", 200.0,
    )
    assert failing_run["result"] == "FAIL"
    assert failing_run["locked_device"] is True
    assert read_device(env["device"]["id"], COORDINATOR)["qc_lock_reason"] == (
        "QC_FAILURE"
    )
    site = read_site(env["site"]["id"], COORDINATOR)
    assert site["held_result_count"] == 3
    assert site["oversight_posture"] == "RESTRICTED"
    assert site["manual_entry_blocked"] is True
    sibling = read_device(hand_keyed_device["id"], COORDINATOR)
    assert sibling["status"] == "ACTIVE"
    assert sibling["manual_entry_suspended"] is True

    manual_response = api_client.create_test_result(
        patient_result_payload(
            hand_keyed_device["id"], env["operator"]["id"], env["lot"]["id"],
            patient_mrn="MRN-3304", measured_value=101.0,
            entry_mode="MANUAL", manual_entry_reason="gateway down",
        ),
        make_operator_headers(env["operator"]["id"]),
    )
    interfaced = validate_success(
        api_client.create_test_result(
            patient_result_payload(
                hand_keyed_device["id"], env["operator"]["id"], env["lot"]["id"],
                patient_mrn="MRN-3305", measured_value=103.0,
            ),
            make_operator_headers(env["operator"]["id"]),
        ),
        201,
    )

    validate_error(manual_response, "ERR_MANUAL_ENTRY_NOT_PERMITTED", 422)
    assert interfaced["posting_status"] == "PENDING_REVIEW"
    assert read_site(env["site"]["id"], COORDINATOR)["held_result_count"] == 3
    for result in held:
        read_back = read_result(result["id"], COORDINATOR)
        assert read_back["posting_status"] == "HELD"
        assert_logical_instant(
            read_back["held_by_device_lock_at"], AUGUST_MORNING_STAMP
        )
    assert read_operator(env["operator"]["id"])["access_status"] == "ACTIVE"
