"""Multi-hop cascades that reach several entity kinds inside one request."""

from test_helpers import (
    assert_logical_instant,
    capture_results,
    create_device,
    create_trained_operator,
    read_assessment,
    read_certificate,
    read_coverage,
    read_device,
    read_lot,
    read_operator,
    read_result,
    read_site,
    read_storage_unit,
    record_qc_run,
    setup_site_with_director,
    setup_site_with_verified_lot,
    setup_temperature_excursion,
    submit_assessment,
    suspend_certificate,
)

# ─── qc_failure_holds_results_restricts_site_and_suspends_manual_entry ─


def _site_with_two_instruments_and_three_pending_results():
    """An interfaced instrument holding three PENDING_REVIEW results, plus an
    unrelated MANUAL_ENTRY instrument at the same site."""
    env = setup_site_with_verified_lot(
        certificate_overrides={"certificate_number": "45D2243009"},
        site_overrides={
            "name": "Dialysis POCT",
            "department_code": "DEPT-180",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Alma Ruiz"},
        device_overrides={"serial_number": "SN-0301"},
        lot_overrides={"lot_number": "LOT-D1"},
    )
    env["manual_device"] = create_device(
        env["site"]["id"], serial_number="SN-0302",
        device_model="StripReader-Z", analyte="URINALYSIS",
        connectivity_mode="MANUAL_ENTRY",
    )
    env["results"] = capture_results(env, 3)
    return env


def _fail_the_control(env):
    return record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", 140.0,
    )


def test_a_failing_control_run_locks_its_instrument_and_holds_its_pending_results():
    """One out-of-band control run locks the instrument and holds all three results.

    PRD 3.4: "The instrument moves `ACTIVE → QC_LOCKED` with `qc_lock_reason` of
    `QC_FAILURE`, and the offending run's `locked_device` is set true." and "Caused
    by the lock: every patient result on that instrument whose `posting_status` is
    `PENDING_REVIEW` moves `PENDING_REVIEW → HELD` with `held_by_device_lock_at`
    stamped at the current logical instant, processed by `created_at` ascending then
    `patient_mrn` ascending, and the site's `held_result_count` rises by exactly the
    number moved."

    Design: Difficulty/transitive_cascade/qc_failure_holds_results_restricts_site_and_suspends_manual_entry
    """
    env = _site_with_two_instruments_and_three_pending_results()

    run = _fail_the_control(env)

    assert run["result"] == "FAIL"
    assert run["expected_max"] == 120.0
    assert run["locked_device"] is True
    device = read_device(env["device"]["id"])
    assert device["status"] == "QC_LOCKED"
    assert device["qc_lock_reason"] == "QC_FAILURE"
    for result in env["results"]:
        read_back = read_result(result["id"])
        assert read_back["posting_status"] == "HELD"
        assert_logical_instant(
            read_back["held_by_device_lock_at"], "2026-08-01T00:00:00Z"
        )


def test_three_held_results_restrict_the_site_and_suspend_hand_keying():
    """The held count reaches 3, the posture restricts and hand entry is barred.

    PRD 3.4: "Caused by the changed held count: the site's posture is re-derived,
    and it becomes `RESTRICTED` once `held_result_count` reaches 3."

    Design: Difficulty/transitive_cascade/qc_failure_holds_results_restricts_site_and_suspends_manual_entry
    """
    env = _site_with_two_instruments_and_three_pending_results()

    _fail_the_control(env)

    site = read_site(env["site"]["id"])
    assert site["held_result_count"] == 3
    assert site["oversight_posture"] == "RESTRICTED"
    assert site["manual_entry_blocked"] is True


def test_the_posture_change_suspends_an_unrelated_manual_entry_instrument():
    """The bystander MANUAL_ENTRY instrument is flagged while staying ACTIVE.

    PRD 3.4: "Caused by the posture change: the site's `manual_entry_blocked`
    becomes true and every instrument at that site whose `connectivity_mode` is
    `MANUAL_ENTRY` gets `manual_entry_suspended` set to true — including instruments
    that had nothing to do with the failure."

    Design: Difficulty/transitive_cascade/qc_failure_holds_results_restricts_site_and_suspends_manual_entry
    """
    env = _site_with_two_instruments_and_three_pending_results()

    _fail_the_control(env)

    bystander = read_device(env["manual_device"]["id"])
    offender = read_device(env["device"]["id"])
    assert bystander["status"] == "ACTIVE"
    assert bystander["manual_entry_suspended"] is True
    assert offender["manual_entry_suspended"] is False
    assert read_lot(env["lot"]["id"])["verification_status"] == "VERIFIED"


# ─── temperature_excursion_quarantines_lot_locks_device_and_rejects ─


def _excursion_environment():
    return setup_temperature_excursion(
        result_count=2,
        certificate_overrides={"certificate_number": "45D2243010"},
        site_overrides={
            "name": "Infusion POCT",
            "department_code": "DEPT-190",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Alma Ruiz"},
        device_overrides={"serial_number": "SN-0401"},
        lot_overrides={"lot_number": "LOT-E1"},
    )


def test_an_out_of_band_reading_opens_the_excursion_and_quarantines_the_lot():
    """A 12.5 C reading opens the excursion and quarantines the stock inside.

    PRD 3.5: "The unit moves `IN_RANGE → EXCURSION_OPEN`, its `excursion_opened_at`
    is stamped with the current logical instant, and the reading's
    `triggered_excursion` flag is set true." and "Caused by the excursion opening:
    every reagent lot stored in that unit whose `verification_status` is
    `UNVERIFIED` or `VERIFIED` moves to `QUARANTINED` with `quarantine_reason` of
    `TEMPERATURE_EXCURSION`, and the unit's `quarantined_lot_count` is updated to
    match."

    Design: Difficulty/transitive_cascade/temperature_excursion_quarantines_lot_locks_device_and_rejects_results
    """
    env = _excursion_environment()

    reading = env["excursion_reading"]
    assert reading["disposition"] == "OUT_OF_RANGE"
    assert reading["triggered_excursion"] is True
    assert reading["reading_c"] == 12.5
    unit = read_storage_unit(env["storage_unit"]["id"])
    assert unit["excursion_state"] == "EXCURSION_OPEN"
    assert unit["last_reading_c"] == 12.5
    assert_logical_instant(unit["excursion_opened_at"], "2026-08-01T00:00:00Z")
    assert unit["quarantined_lot_count"] == 1
    lot = read_lot(env["lot"]["id"])
    assert lot["verification_status"] == "QUARANTINED"
    assert lot["quarantine_reason"] == "TEMPERATURE_EXCURSION"


def test_the_quarantine_locks_the_matching_instrument_and_rejects_its_results():
    """The third and fourth hops reach the instrument and its pending results.

    PRD 3.5: "Caused by link 3: on those instruments, every patient result whose
    `posting_status` is `PENDING_REVIEW` and whose `reagent_lot_id` is one of the
    quarantined lots moves `PENDING_REVIEW → REJECTED`. These results are rejected
    outright rather than held, because the reagent itself is suspect — the value can
    never be trusted, so there is nothing to release later."

    Design: Difficulty/transitive_cascade/temperature_excursion_quarantines_lot_locks_device_and_rejects_results
    """
    env = _excursion_environment()

    device = read_device(env["device"]["id"])
    assert device["status"] == "QC_LOCKED"
    assert device["qc_lock_reason"] == "LOT_QUARANTINE"
    for result in env["results"]:
        assert read_result(result["id"])["posting_status"] == "REJECTED"


def test_the_excursion_cascade_leaves_the_held_count_at_zero():
    """Rejection, unlike a hold, never moves the held-result counter.

    PRD 2.11: "`held_result_count` is the number of patient results on the site's
    instruments whose `posting_status` is `HELD`."

    Design: Difficulty/transitive_cascade/temperature_excursion_quarantines_lot_locks_device_and_rejects_results
    """
    env = _excursion_environment()

    site = read_site(env["site"]["id"])
    assert site["held_result_count"] == 0
    assert site["oversight_posture"] == "OPEN"


# ─── certificate_suspension_cascades_to_four_entity_kinds ───────────


def _site_with_pending_assessment_and_manual_instrument():
    env = setup_site_with_director(
        certificate_overrides={"certificate_number": "45D2243011"},
        site_overrides={
            "name": "Wound Care POCT",
            "department_code": "DEPT-200",
            "complexity_scope": "WAIVED",
        },
    )
    env["assessor"] = create_trained_operator(
        env["site"]["id"], full_name="Ben Osei", role_title="MEDICAL_TECHNOLOGIST",
    )
    env["subject"] = create_trained_operator(
        env["site"]["id"], full_name="Alma Ruiz", role_title="MEDICAL_ASSISTANT",
        hire_date="2026-03-01",
    )
    env["assessment"] = submit_assessment(
        env["subject"]["id"], env["assessor"]["id"],
    )
    env["device"] = create_device(
        env["site"]["id"], serial_number="SN-0501",
        connectivity_mode="MANUAL_ENTRY",
    )
    return env


def test_suspending_the_certificate_suspends_the_site_and_locks_every_operator():
    """The first two cascade links move the site and its whole roster.

    PRD 3.1: "Caused by link 1: at each such site, every operator whose
    `access_status` is `ACTIVE` moves to `LOCKED_OUT` with `lockout_reason` of
    `SITE_SUSPENDED`. Their `competency_status` is deliberately **not** touched — a
    suspended site does not make anyone incompetent."

    Design: Difficulty/transitive_cascade/certificate_suspension_cascades_to_site_operators_assessments_and_devices
    """
    env = _site_with_pending_assessment_and_manual_instrument()
    assert env["assessment"]["status"] == "SUBMITTED"
    before_suspension = read_certificate(env["certificate"]["id"])

    suspended = suspend_certificate(
        env["certificate"]["id"],
        reason="Sanction pending after complaint survey",
    )

    assert suspended["status"] == "SUSPENDED"
    assert suspended["covered_site_count"] == 1
    assert suspended["version"] == before_suspension["version"] + 1
    assert suspended["suspension_reason"] == "Sanction pending after complaint survey"
    site = read_site(env["site"]["id"])
    assert site["oversight_posture"] == "SUSPENDED"
    assert site["manual_entry_blocked"] is True
    assert site["locked_out_operator_count"] == 3
    assert site["total_operator_count"] == 3
    for operator_key in ("director", "assessor", "subject"):
        assert read_operator(env[operator_key]["id"])["access_status"] == "LOCKED_OUT"
    subject = read_operator(env["subject"]["id"])
    assert subject["lockout_reason"] == "SITE_SUSPENDED"
    assert subject["competency_status"] == "PROVISIONAL"


def test_suspension_voids_the_in_flight_assessment_without_a_decider():
    """The SUBMITTED assessment is voided and keeps a null decider.

    PRD 3.1: "That is only the first line of the **certificate withdrawal
    cascade**, whose four links run inside the same request:"

    Design: Difficulty/transitive_cascade/certificate_suspension_cascades_to_site_operators_assessments_and_devices
    """
    env = _site_with_pending_assessment_and_manual_instrument()

    suspend_certificate(env["certificate"]["id"])

    assessment = read_assessment(env["assessment"]["id"])
    assert assessment["status"] == "VOIDED"
    assert assessment["decided_by_user_id"] is None


def test_suspension_locks_the_instrument_on_scope_and_preserves_the_snapshot():
    """The instrument locks with CERTIFICATE_SCOPE while the coverage snapshot stands.

    PRD 3.4: "Instruments acquire locks from five distinct sources, and
    `qc_lock_reason` records which: `QC_FAILURE` from a failing control run,
    `QC_OVERDUE` from an oversight run finding the compliance horizon passed,
    `LOT_QUARANTINE` from a temperature excursion, `PT_UNSUCCESSFUL` from a
    proficiency-testing failure, and `CERTIFICATE_SCOPE` from a withdrawn
    certificate or a detected scope violation."

    Design: Difficulty/transitive_cascade/certificate_suspension_cascades_to_site_operators_assessments_and_devices
    """
    env = _site_with_pending_assessment_and_manual_instrument()

    suspend_certificate(env["certificate"]["id"])

    device = read_device(env["device"]["id"])
    assert device["status"] == "QC_LOCKED"
    assert device["qc_lock_reason"] == "CERTIFICATE_SCOPE"
    assert device["manual_entry_suspended"] is True
    assert read_coverage(env["coverage"]["id"])[
        "permitted_complexity_snapshot"
    ] == "WAIVED"
    assert read_certificate(env["certificate"]["id"])["status"] == "SUSPENDED"
