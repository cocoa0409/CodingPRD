"""Version guards, exact counter reconciliation and the scheduled sweep."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    api_client,
    assert_logical_instant,
    assessment_payload,
    capture_result,
    correction_payload,
    create_trained_operator,
    decide_assessment,
    make_lab_director_headers,
    make_operator_headers,
    post_result,
    read_device,
    read_lot,
    read_operator,
    read_readiness,
    read_result,
    read_site,
    run_oversight,
    set_clock,
    setup_covered_site,
    setup_site_with_verified_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

SEPTEMBER = "2026-09-01T08:00:00Z"
OCTOBER_SWEEP = "2026-10-05T06:00:00Z"
OCTOBER_SWEEP_STAMP = "2026-10-05T06:00:00.000Z"


def test_the_version_that_worked_once_is_stale_the_second_time_around():
    """Posting supersedes the captured version, and the replay is 412 not 409.

    PRD 2.9: "Patient-result correction (`POST /poct/test-results/{id}/correct`) requires
    `expected_test_result_version`, carrying the client's last observed `version` of the
    `TestResult` being amended. A posted result may be corrected any number of times,
    each correction superseding the previously posted value, so again no state
    precondition stands in the way; only a stale version reveals that the corrector is
    amending a value that has already been superseded. A mismatch with the result's
    current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412."

    PRD 2.7: "10. **Rank 30 — optimistic concurrency.** On competency-assessment
    submission and on patient-result correction, the supplied expected version must equal
    the parent's current `version`. Otherwise `ERR_STALE_VERSION` (412). See §2.9."

    PRD 3.6: "On success the result moves `POSTED → CORRECTION_PENDING`, its
    `correction_count` rises by one, `correction_reason` records the most recent reason,
    and `version` increments — but `posted_value` keeps the previously posted number,
    because until the amendment is posted again the medical record still holds the old
    value."

    Design: Corner/cross_cutting_complexity_layers/result_correction_with_stale_expected_version_returns_stale_version
    """
    env = setup_site_with_verified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243052"},
        site_overrides={
            "name": "Transplant Clinic POCT", "department_code": "DEPT-4900",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={
            "full_name": "Tomas Villalba", "role_title": "MEDICAL_TECHNOLOGIST",
            "hire_date": "2026-01-05",
        },
        device_overrides={"serial_number": "SN-GL-4900"},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    operator_headers = make_operator_headers(env["operator"]["id"])
    director_headers = make_lab_director_headers(env["operator"]["id"])
    captured = capture_result(
        env, patient_mrn="MRN-5001", measured_value=118.0
    )
    posted = post_result(
        captured["id"], operator_headers,
        attestation="instrument transmission verified",
    )
    assert captured["version"] == 1
    assert posted["version"] == 2
    assert posted["posting_status"] == "POSTED"
    assert posted["posted_value"] == 118.0

    stale = api_client.correct_test_result(
        captured["id"],
        correction_payload(
            181.0, captured["version"],
            correction_reason="transposed digits at the analyser",
        ),
        director_headers,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)

    corrected = validate_success(
        api_client.correct_test_result(
            captured["id"],
            correction_payload(
                181.0, posted["version"],
                correction_reason="transposed digits at the analyser",
            ),
            director_headers,
        ),
        200,
    )
    assert corrected["posting_status"] == "CORRECTION_PENDING"
    assert corrected["version"] == 3
    assert corrected["correction_count"] == 1
    assert corrected["posted_value"] == 118.0

    replay = api_client.correct_test_result(
        captured["id"],
        correction_payload(
            182.0, posted["version"],
            correction_reason="second amendment attempt on a stale read",
        ),
        director_headers,
    )

    validate_error(replay, "ERR_STALE_VERSION", 412)
    unchanged = read_result(captured["id"], COORDINATOR)
    assert unchanged["correction_count"] == 1
    assert unchanged["version"] == 3
    assert unchanged["posting_status"] == "CORRECTION_PENDING"
    assert unchanged["posted_value"] == 118.0


def test_revoking_an_operator_leaves_the_readiness_score_exactly_where_it_was():
    """The revoked operator leaves numerator and denominator together, so 100.00 holds.

    PRD 3.3: "**On rejection** the assessment moves `SUBMITTED → REJECTED` and the
    subject's `consecutive_rejection_count` rises by one. A first rejection is a setback;
    a second consecutive one ends the operator's tenure. When the incremented count
    reaches 2 — that is, when it stood at 1 before this decision — the operator's
    competency moves from `PROVISIONAL`, `COMPETENT` or `LAPSED` to `REVOKED` and their
    access moves to `DEACTIVATED` with `lockout_reason` of `COMPETENCY_REVOKED`."

    PRD 2.11: "`total_operator_count` is the number of the site's operators whose
    `access_status` is not `DEACTIVATED`, so a deactivated operator leaves that
    denominator." and "`lapsed_or_locked_operator_count` counts those whose
    `competency_status` is `LAPSED` **or** whose `access_status` is `LOCKED_OUT` — an
    operator satisfying both conditions is counted once."

    Design: Corner/cross_cutting_complexity_layers/site_operator_counters_reconcile_after_second_rejection_revokes_operator
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243053"},
        site_overrides={
            "name": "Burn Unit POCT", "department_code": "DEPT-5000",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    subject = create_trained_operator(
        site["id"], full_name="Uli Marchetti",
        role_title="NURSE", hire_date="2026-01-05",
        training={
            "training_module_code": "POCT-GLUCO-101", "completed_on": "2026-08-20"
        },
    )
    assessor = create_trained_operator(
        site["id"], full_name="Vera Lindgren",
        role_title="MEDICAL_TECHNOLOGIST", hire_date="2026-01-06",
        training={
            "training_module_code": "POCT-GLUCO-101", "completed_on": "2026-08-21"
        },
    )
    before = read_site(site["id"], COORDINATOR)
    assert before["total_operator_count"] == 2
    assert before["lapsed_or_locked_operator_count"] == 0
    assert before["inspection_readiness_score"] == 100.00

    first_assessment = validate_success(
        api_client.create_assessment(
            assessment_payload(
                subject["id"], assessor["id"],
                read_operator(subject["id"], COORDINATOR)["version"],
                effective_date="2026-09-01", expires_at="2027-03-01",
            ),
            COORDINATOR,
        ),
        201,
    )
    first_rejection = decide_assessment(
        first_assessment["id"], "REJECT", ADMIN,
        note="two methods repeated incorrectly",
    )
    assert first_rejection["status"] == "REJECTED"
    after_one = read_operator(subject["id"], COORDINATOR)
    assert after_one["consecutive_rejection_count"] == 1
    assert after_one["competency_status"] == "PROVISIONAL"
    assert after_one["access_status"] == "ACTIVE"

    second_assessment = validate_success(
        api_client.create_assessment(
            assessment_payload(
                subject["id"], assessor["id"], after_one["version"],
                effective_date="2026-09-01", expires_at="2027-03-01",
            ),
            COORDINATOR,
        ),
        201,
    )
    assert second_assessment["status"] == "SUBMITTED"

    second_rejection = decide_assessment(
        second_assessment["id"], "REJECT", ADMIN,
        note="same two methods failed again",
    )

    assert second_rejection["status"] == "REJECTED"
    revoked = read_operator(subject["id"], COORDINATOR)
    assert revoked["consecutive_rejection_count"] == 2
    assert revoked["competency_status"] == "REVOKED"
    assert revoked["access_status"] == "DEACTIVATED"
    assert revoked["lockout_reason"] == "COMPETENCY_REVOKED"

    after = read_site(site["id"], COORDINATOR)
    assert after["total_operator_count"] == 1
    assert after["lapsed_or_locked_operator_count"] == 0
    assert after["locked_out_operator_count"] == 0
    assert after["inspection_readiness_score"] == 100.00
    assert after["oversight_posture"] == "OPEN"
    breakdown = read_readiness(site["id"], COORDINATOR)
    assert breakdown["competency_penalty"] == 0.00
    assert breakdown["score"] == 100.00
    _roster, meta = validate_paginated(
        api_client.list_site_operators(site["id"], COORDINATOR)
    )
    assert meta["total_count"] == 2


def test_lot_expiry_lands_only_when_the_sweep_runs_and_spares_the_posted_result():
    """Crossing the expiry date changes nothing; the sweep rejects only what is pending.

    PRD 3.9: "2. Every reagent lot whose `verification_status` is `UNVERIFIED` or
    `VERIFIED` and whose `expiration_date` is strictly before the current logical date
    moves to `EXPIRED`, and every `PENDING_REVIEW` patient result on that lot moves to
    `REJECTED`."

    PRD 3.9: "The run answers with a summary of what it did: the `evaluated_at` instant,
    and the counts `certificates_expired`, `lots_expired`, `competencies_lapsed`,
    `operators_locked_out`, `devices_qc_locked`, `scope_creep_sites` and
    `sites_posture_changed`." and "6. Every site's counters, `oversight_posture`,
    `site_qc_compliance_index` and `inspection_readiness_score` are recomputed, and each
    site's `last_oversight_run_at` is stamped with the run's instant."

    PRD 3.6: "A reagent-lot quarantine or expiry moves `PENDING_REVIEW` results to
    `REJECTED`, which is terminal: `posted_value` stays null forever and the site's
    `inspection_readiness_score` is recomputed."

    Design: Corner/cross_cutting_complexity_layers/oversight_run_expires_lot_and_rejects_pending_results
    """
    env = setup_site_with_verified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243054"},
        site_overrides={
            "name": "Stroke Unit POCT", "department_code": "DEPT-5100",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={
            "full_name": "Wynn Achebe", "role_title": "MEDICAL_TECHNOLOGIST",
            "hire_date": "2026-01-05",
        },
        device_overrides={
            "serial_number": "SN-GL-5100", "qc_frequency_days": 90,
        },
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2026-09-30"},
    )
    pending_one = capture_result(env, patient_mrn="MRN-5101", measured_value=96.0)
    pending_two = capture_result(env, patient_mrn="MRN-5102", measured_value=104.0)
    third = capture_result(env, patient_mrn="MRN-5103", measured_value=110.0)
    released = post_result(
        third["id"], make_operator_headers(env["operator"]["id"]),
        attestation="released to the chart",
    )
    assert released["posting_status"] == "POSTED"

    set_clock(OCTOBER_SWEEP)
    assert read_lot(env["lot"]["id"], COORDINATOR)["verification_status"] == "VERIFIED"

    summary = run_oversight(note="scheduled sweep after the lot's expiry date")

    assert_logical_instant(summary["evaluated_at"], OCTOBER_SWEEP_STAMP)
    assert summary["lots_expired"] == 1
    assert summary["certificates_expired"] == 0
    assert summary["devices_qc_locked"] == 0
    assert summary["competencies_lapsed"] == 0
    assert read_lot(env["lot"]["id"], COORDINATOR)["verification_status"] == "EXPIRED"
    for rejected_id in (pending_one["id"], pending_two["id"]):
        rejected = read_result(rejected_id, COORDINATOR)
        assert rejected["posting_status"] == "REJECTED"
        assert rejected["posted_value"] is None
    survivor = read_result(third["id"], COORDINATOR)
    assert survivor["posting_status"] == "POSTED"
    assert survivor["posted_value"] == 110.0
    device = read_device(env["device"]["id"], COORDINATOR)
    assert device["status"] == "ACTIVE"
    assert device["qc_next_due_at"] == "2026-11-30"
    site = read_site(env["site"]["id"], COORDINATOR)
    assert site["held_result_count"] == 0
    assert site["oversight_posture"] == "OPEN"
    assert_logical_instant(site["last_oversight_run_at"], OCTOBER_SWEEP_STAMP)
