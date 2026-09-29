"""Writes whose legality depends on the state of a different entity."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    api_client,
    assert_logical_instant,
    capture_result,
    create_certificate,
    create_coverage,
    enroll_pt,
    lot_verify_payload,
    make_operator_headers,
    post_payload,
    qc_unlock_payload,
    read_coverage,
    read_device,
    read_lot,
    read_operator,
    read_pt_enrollment,
    read_pt_event,
    read_readiness,
    read_result,
    read_site,
    record_qc_run,
    register_pt_event,
    reinstatement_payload,
    score_pt_event,
    set_clock,
    setup_site_with_operator,
    setup_site_with_unverified_lot,
    setup_site_with_verified_lot,
    suspend_certificate,
    validate_error,
    validate_success,
)

# ─── access_reinstatement_blocked_by_site_posture_then_allowed ────────


def _operator_locked_out_by_a_suspended_certificate():
    """One operator locked out because the site lost its only coverage."""
    env = setup_site_with_operator(
        certificate_overrides={
            "certificate_number": "45D2243018",
            "expiration_date": "2026-12-31",
        },
        site_overrides={
            "name": "Reinstatement POCT",
            "department_code": "DEPT-270",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-08-31"},
    )
    suspend_certificate(env["certificate"]["id"])
    return env


def _reinstate(operator_id):
    return api_client.reinstate_access(
        operator_id, reinstatement_payload(), ADMIN
    )


def test_reinstatement_is_refused_while_the_site_posture_is_suspended():
    """The operator is eligible in itself; the site's posture is what blocks it.

    PRD 3.3: "Reinstatement requires `access_status` of `LOCKED_OUT`, a
    `competency_status` of `PROVISIONAL` or `COMPETENT` — a `LAPSED`, `PENDING` or
    `REVOKED` operator cannot be reinstated, which surfaces as `ERR_INVALID_STATE` —
    and a site whose `oversight_posture` is not `SUSPENDED`, or the request fails with
    `ERR_SITE_OVERSIGHT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/access_reinstatement_blocked_by_site_posture_then_allowed_after_recoverage
    """
    env = _operator_locked_out_by_a_suspended_certificate()

    operator = read_operator(env["operator"]["id"])
    assert operator["access_status"] == "LOCKED_OUT"
    assert operator["lockout_reason"] == "SITE_SUSPENDED"
    assert operator["competency_status"] == "PROVISIONAL"
    assert read_site(env["site"]["id"])["oversight_posture"] == "SUSPENDED"

    validate_error(
        _reinstate(env["operator"]["id"]), "ERR_SITE_OVERSIGHT_SUSPENDED", 409
    )


def test_fresh_coverage_lifts_the_suspension_and_the_same_request_succeeds():
    """Re-covering the site changes nothing about the operator, yet unblocks it.

    PRD 2.10: "If the site has no in-window active coverage, **or** its
    `open_deficiency_weight` is at least 16.0, the posture is `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/access_reinstatement_blocked_by_site_posture_then_allowed_after_recoverage
    """
    env = _operator_locked_out_by_a_suspended_certificate()
    _reinstate(env["operator"]["id"])

    set_clock("2026-09-05T00:00:00Z")
    replacement = create_certificate(
        certificate_number="45D2243019",
        effective_date="2026-09-01", expiration_date="2027-12-31",
    )
    coverage = create_coverage(
        env["site"]["id"], replacement["id"],
        coverage_start="2026-09-01", coverage_end="2027-12-31",
    )
    assert read_coverage(coverage["id"])["permitted_complexity_snapshot"] == "WAIVED"
    # Twice the locked-out count now exceeds the roster of one, so RESTRICTED.
    assert read_site(env["site"]["id"])["oversight_posture"] == "RESTRICTED"

    validate_success(_reinstate(env["operator"]["id"]), 200)

    operator = read_operator(env["operator"]["id"])
    assert operator["access_status"] == "ACTIVE"
    assert operator["lockout_reason"] is None
    assert operator["competency_status"] == "PROVISIONAL"


def test_the_restored_access_returns_the_site_to_an_open_posture():
    """With nobody locked out the third posture rung applies again.

    PRD 3.3: "On success access moves `LOCKED_OUT → ACTIVE`, `lockout_reason` is
    cleared to null, the operator's `version` increments, the site's
    `locked_out_operator_count` drops by one, its `lapsed_or_locked_operator_count` is
    recomputed and its posture is re-derived."

    Design: Difficulty/cross_entity_state_dependency/access_reinstatement_blocked_by_site_posture_then_allowed_after_recoverage
    """
    env = _operator_locked_out_by_a_suspended_certificate()
    set_clock("2026-09-05T00:00:00Z")
    replacement = create_certificate(
        certificate_number="45D2243019",
        effective_date="2026-09-01", expiration_date="2027-12-31",
    )
    create_coverage(
        env["site"]["id"], replacement["id"],
        coverage_start="2026-09-01", coverage_end="2027-12-31",
    )

    _reinstate(env["operator"]["id"])

    site = read_site(env["site"]["id"])
    assert site["oversight_posture"] == "OPEN"
    assert site["locked_out_operator_count"] == 0


# ─── qc_unlock_requires_verified_lot_on_the_confirming_run ────────────


def _locked_instrument_with_a_passing_run_on_an_unverified_lot():
    env = setup_site_with_unverified_lot(
        certificate_overrides={"certificate_number": "45D2243020"},
        site_overrides={
            "name": "Unlock POCT",
            "department_code": "DEPT-280",
            "complexity_scope": "WAIVED",
        },
        device_overrides={"serial_number": "SN-0901"},
        lot_overrides={"lot_number": "LOT-H1"},
    )
    env["failing_run"] = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", 140.0,
    )
    env["confirming_run"] = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", 100.0,
    )
    return env


def _unlock(env):
    return api_client.qc_unlock_device(
        env["device"]["id"], qc_unlock_payload(env["confirming_run"]["id"]),
        COORDINATOR,
    )


def test_a_passing_confirming_run_on_an_unverified_lot_cannot_clear_the_lock():
    """The run itself is a PASS; the lot behind it is what blocks the unlock.

    PRD 3.4: "The instrument must be `QC_LOCKED`; the confirming run must belong to
    that instrument, must have `result` of `PASS`, and must reference a lot whose
    `verification_status` is `VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/qc_unlock_requires_verified_lot_on_the_confirming_run
    """
    env = _locked_instrument_with_a_passing_run_on_an_unverified_lot()

    assert env["failing_run"]["result"] == "FAIL"
    assert env["confirming_run"]["result"] == "PASS"
    assert read_lot(env["lot"]["id"])["verification_status"] == "UNVERIFIED"

    validate_error(_unlock(env), "ERR_LOT_NOT_VERIFIED", 409)
    assert read_device(env["device"]["id"])["status"] == "QC_LOCKED"


def test_verifying_that_same_lot_lets_the_unchanged_request_through():
    """Two-level verification of the referenced lot is the missing precondition.

    PRD 3.5: "When **both** referenced runs have `result` of `PASS`, the lot moves
    `UNVERIFIED → VERIFIED`, its `verified_at` is stamped with the current logical
    instant and its `version` increments."

    Design: Difficulty/cross_entity_state_dependency/qc_unlock_requires_verified_lot_on_the_confirming_run
    """
    env = _locked_instrument_with_a_passing_run_on_an_unverified_lot()
    validate_error(_unlock(env), "ERR_LOT_NOT_VERIFIED", 409)

    level_two = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_2", 300.0,
    )
    verified = validate_success(
        api_client.verify_reagent_lot(
            env["lot"]["id"],
            lot_verify_payload(env["confirming_run"]["id"], level_two["id"]),
            COORDINATOR,
        )
    )
    assert verified["verification_status"] == "VERIFIED"
    assert_logical_instant(verified["verified_at"], "2026-08-01T00:00:00Z")

    unlocked = validate_success(_unlock(env), 200)

    assert unlocked["status"] == "ACTIVE"
    assert unlocked["qc_lock_reason"] is None


def test_the_cleared_lock_recomputes_the_compliance_horizon():
    """Clearing the lock recomputes the two-level stamp and the next-due date.

    PRD 3.4: "On success the instrument moves `QC_LOCKED → ACTIVE`, `qc_lock_reason`
    returns to null, and `last_two_level_qc_pass_on` and `qc_next_due_at` are
    recomputed."

    Design: Difficulty/cross_entity_state_dependency/qc_unlock_requires_verified_lot_on_the_confirming_run
    """
    env = _locked_instrument_with_a_passing_run_on_an_unverified_lot()
    level_two = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_2", 300.0,
    )
    validate_success(
        api_client.verify_reagent_lot(
            env["lot"]["id"],
            lot_verify_payload(env["confirming_run"]["id"], level_two["id"]),
            COORDINATOR,
        )
    )
    _unlock(env)

    device = read_device(env["device"]["id"])
    site = read_site(env["site"]["id"])
    assert device["last_two_level_qc_pass_on"] == "2026-08-01"
    assert device["qc_next_due_at"] == "2026-08-31"
    assert site["held_result_count"] == 0
    assert site["oversight_posture"] == "OPEN"


# ─── posting_blocked_by_device_locked_through_proficiency_failure ─────


def _pending_result_on_an_instrument_locked_by_proficiency_failure():
    env = setup_site_with_verified_lot(
        certificate_overrides={"certificate_number": "45D2243021"},
        site_overrides={
            "name": "Proficiency Lock POCT",
            "department_code": "DEPT-290",
            "complexity_scope": "WAIVED",
        },
        device_overrides={"serial_number": "SN-1001"},
        lot_overrides={"lot_number": "LOT-I1"},
    )
    env["result"] = capture_result(env, patient_mrn="MRN-7001", measured_value=97.0)
    env["enrollment"] = enroll_pt(env["site"]["id"], analyte="GLUCOSE")
    first = register_pt_event(env["enrollment"]["id"], 1, due_date="2026-08-10")
    second = register_pt_event(env["enrollment"]["id"], 2, due_date="2026-08-20")
    env["first_event"] = score_pt_event(first["id"], 60.00)
    env["second_event"] = score_pt_event(second["id"], 60.00)
    return env


def _post(env):
    return api_client.post_test_result(
        env["result"]["id"], post_payload(),
        make_operator_headers(env["operator"]["id"]),
    )


def test_a_second_proficiency_failure_locks_the_matching_analyte_instrument():
    """Two failures of the last three lock every ACTIVE instrument for the analyte.

    PRD 3.7: "Every instrument at the enrolment's site whose `status` is `ACTIVE` and
    whose `analyte` equals the enrolment's `analyte` moves `ACTIVE → QC_LOCKED` with
    `qc_lock_reason` of `PT_UNSUCCESSFUL`, processed by `created_at` ascending then
    `serial_number` ascending."

    Design: Difficulty/cross_entity_state_dependency/posting_blocked_by_device_locked_through_proficiency_failure
    """
    env = _pending_result_on_an_instrument_locked_by_proficiency_failure()

    assert read_pt_event(env["first_event"]["id"])["status"] == "INVESTIGATION_OPEN"
    assert read_pt_event(env["second_event"]["id"])["status"] == "UNSUCCESSFUL_LOCKED"
    device = read_device(env["device"]["id"])
    assert device["status"] == "QC_LOCKED"
    assert device["qc_lock_reason"] == "PT_UNSUCCESSFUL"
    enrollment = read_pt_enrollment(env["enrollment"]["id"])
    assert enrollment["status"] == "UNSUCCESSFUL_PARTICIPATION"
    assert enrollment["fail_count_last_three"] == 2


def test_posting_is_refused_because_the_instrument_is_no_longer_active():
    """The result and the actor are both fine; the instrument's status is not.

    PRD 3.6: "The result must be `PENDING_REVIEW` or `CORRECTION_PENDING`; the
    instrument must be `ACTIVE`; and the acting user — identified by `X-User-ID` —
    must have `access_status` of `ACTIVE`, `competency_status` of `PROVISIONAL` or
    `COMPETENT`, and belong to the same site as the instrument."

    Design: Difficulty/cross_entity_state_dependency/posting_blocked_by_device_locked_through_proficiency_failure
    """
    env = _pending_result_on_an_instrument_locked_by_proficiency_failure()

    validate_error(_post(env), "ERR_DEVICE_QC_LOCKED", 409)

    result = read_result(env["result"]["id"])
    assert result["posting_status"] == "PENDING_REVIEW"
    assert result["posted_value"] is None
    assert result["posted_by_user_id"] is None
    assert result["posted_at"] is None


def test_the_proficiency_lock_costs_readiness_but_leaves_the_posture_open():
    """A lock is not a hold, so the posture stays OPEN while the score drops.

    PRD 3.9: "**Proficiency penalty.** The per-failure unit depends on the site's
    declared `complexity_scope`: 6 points per unsuccessful proficiency event when the
    scope is `MODERATE`, and 3 points when it is `WAIVED`."

    Design: Difficulty/cross_entity_state_dependency/posting_blocked_by_device_locked_through_proficiency_failure
    """
    env = _pending_result_on_an_instrument_locked_by_proficiency_failure()

    _post(env)

    readiness = read_readiness(env["site"]["id"], ADMIN)
    site = read_site(env["site"]["id"])
    assert readiness["pt_unsuccessful_count"] == 2
    assert readiness["pt_penalty"] == 6.00
    assert readiness["score"] == 94.00
    assert site["held_result_count"] == 0
    assert site["oversight_posture"] == "OPEN"
