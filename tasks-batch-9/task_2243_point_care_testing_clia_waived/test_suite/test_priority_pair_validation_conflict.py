"""Requests that violate two rules at once must report the higher-ranked one."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    api_client,
    assessment_payload,
    create_operator,
    create_trained_operator,
    device_payload,
    make_operator_headers,
    patient_result_payload,
    read_certificate,
    read_device,
    read_lot,
    read_operator,
    read_site,
    run_oversight,
    set_clock,
    setup_covered_site,
    setup_site_with_director,
    setup_site_with_unverified_lot,
    validate_error,
    validate_paginated,
)

# ─── expired_certificate_preempts_complexity_scope_on_device_create ──


def _site_whose_only_certificate_has_lapsed():
    """A WAIVED site whose sole certificate was expired by the oversight run."""
    certificate, site, coverage = setup_covered_site(
        certificate_overrides={
            "certificate_number": "45D2243012",
            "expiration_date": "2026-08-31",
        },
        site_overrides={
            "name": "Short Coverage POCT",
            "department_code": "DEPT-210",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-08-31"},
    )
    set_clock("2026-09-05T00:00:00Z")
    summary = run_oversight(note="Certificate expiry sweep")
    return certificate, site, coverage, summary


def _install_moderate_instrument(site_id):
    return api_client.create_device(
        device_payload(
            site_id,
            device_model="ChemAnalyzer-M",
            serial_number="SN-0601",
            analyte="CHEMISTRY_PANEL",
            complexity_class="MODERATE",
            connectivity_mode="INTERFACED",
            qc_frequency_days=7,
        ),
        ADMIN,
    )


def test_rank_fifty_seven_certificate_expiry_outranks_rank_sixty_two_scope():
    """A MODERATE install under a lapsed waiver reports the certificate, not the scope.

    PRD 2.7: "Because most write operations are guarded by several independent
    rules, the order in which those rules run is part of the contract: a request
    that violates three rules must fail with the error of the highest-ranked one.
    Rules are evaluated in the following order, and evaluation stops at the first
    failure." Rank 57 is "**Rank 57 — certificate in force.** On device
    installation, the site must have a coverage window containing the current
    logical date whose certificate's `status` is `ACTIVE` and whose
    `expiration_date` is on or after the current logical date. Otherwise
    `ERR_CERTIFICATE_EXPIRED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/expired_certificate_preempts_complexity_scope_on_device_create
    """
    _certificate, site, _coverage, _summary = _site_whose_only_certificate_has_lapsed()

    response = _install_moderate_instrument(site["id"])

    validate_error(response, "ERR_CERTIFICATE_EXPIRED", 422)


def test_the_expiry_sweep_moved_the_certificate_before_the_install_was_tried():
    """The oversight run is what makes the higher-ranked rule bite.

    PRD 3.9: "Every certificate whose `status` is `ACTIVE` and whose
    `expiration_date` is strictly before the current logical date moves to
    `EXPIRED`, running the four cascade links of §3.1 with `lockout_reason` of
    `SITE_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/expired_certificate_preempts_complexity_scope_on_device_create
    """
    certificate, site, _coverage, summary = _site_whose_only_certificate_has_lapsed()

    assert summary["certificates_expired"] == 1
    assert read_certificate(certificate["id"])["status"] == "EXPIRED"
    read_back = read_site(site["id"])
    assert read_back["oversight_posture"] == "SUSPENDED"
    assert read_back["manual_entry_blocked"] is True


def test_the_rejected_install_leaves_no_instrument_behind():
    """A precedence failure is a total failure: nothing is persisted.

    PRD 2.7: "**Rank 62 — complexity within scope.** On device installation, a
    `complexity_class` of `MODERATE` requires the site's in-window coverage to carry
    a `permitted_complexity_snapshot` of `MODERATE`. Otherwise
    `ERR_COMPLEXITY_SCOPE_EXCEEDED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/expired_certificate_preempts_complexity_scope_on_device_create
    """
    _certificate, site, _coverage, _summary = _site_whose_only_certificate_has_lapsed()

    _install_moderate_instrument(site["id"])

    _data, meta = validate_paginated(
        api_client.list_devices(ADMIN, params={"site_id": site["id"]})
    )
    assert meta["total_count"] == 0


# ─── stale_version_preempts_insufficient_competency_methods ──────────


def _site_with_three_operators():
    env = setup_site_with_director(
        certificate_overrides={"certificate_number": "45D2243013"},
        site_overrides={
            "name": "Rehab POCT",
            "department_code": "DEPT-220",
            "complexity_scope": "WAIVED",
        },
        director_overrides={"full_name": "Dr Iris Vale", "hire_date": "2026-01-15"},
    )
    env["assessor"] = create_trained_operator(
        env["site"]["id"], full_name="Ben Osei", role_title="MEDICAL_TECHNOLOGIST",
    )
    env["subject"] = create_trained_operator(
        env["site"]["id"], full_name="Alma Ruiz", role_title="MEDICAL_ASSISTANT",
        hire_date="2026-03-01",
    )
    env["subject_version"] = read_operator(env["subject"]["id"])["version"]
    return env


def _submit_stale_and_short(env):
    return api_client.create_assessment(
        assessment_payload(
            env["subject"]["id"], env["assessor"]["id"],
            env["subject_version"] - 1,
            methods_demonstrated=4,
        ),
        COORDINATOR,
    )


def test_rank_thirty_stale_version_outranks_rank_sixty_three_competency_elements():
    """A stale version and only four elements: the concurrency guard answers first.

    PRD 2.7: "**Rank 30 — optimistic concurrency.** On competency-assessment
    submission and on patient-result correction, the supplied expected version must
    equal the parent's current `version`. Otherwise `ERR_STALE_VERSION` (412). See
    §2.9."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_preempts_insufficient_competency_methods_on_assessment_create
    """
    env = _site_with_three_operators()

    response = _submit_stale_and_short(env)

    validate_error(response, "ERR_STALE_VERSION", 412)


def test_the_short_element_count_is_never_reached_and_the_operator_is_untouched():
    """The lower-ranked element rule stays silent and no version is consumed.

    PRD 2.7: "**Rank 63 — competency elements.** On competency-assessment
    submission, `methods_demonstrated` must be at least 6. Otherwise
    `ERR_INSUFFICIENT_COMPETENCY_METHODS` (422)."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_preempts_insufficient_competency_methods_on_assessment_create
    """
    env = _site_with_three_operators()

    _submit_stale_and_short(env)

    subject = read_operator(env["subject"]["id"])
    assert subject["version"] == env["subject_version"]
    assert subject["competency_status"] == "PROVISIONAL"
    assert subject["access_status"] == "ACTIVE"
    assert read_site(env["site"]["id"])["total_operator_count"] == 3


# ─── unverified_lot_preempts_operator_access_lock_on_capture ─────────


def _site_with_unverified_lot_and_a_locked_operator():
    env = setup_site_with_unverified_lot(
        certificate_overrides={"certificate_number": "45D2243014"},
        site_overrides={
            "name": "Occupational Health POCT",
            "department_code": "DEPT-230",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Alma Ruiz"},
        device_overrides={"serial_number": "SN-0701"},
        lot_overrides={"lot_number": "LOT-F1"},
    )
    # Never trained, so this operator is barred from the instrument.
    env["locked"] = create_operator(
        env["site"]["id"], full_name="Ben Osei", role_title="MEDICAL_ASSISTANT",
        hire_date="2026-03-01",
    )
    return env


def _capture_with_locked_operator_on_unverified_lot(env):
    locked_id = env["locked"]["id"]
    return api_client.create_test_result(
        patient_result_payload(
            env["device"]["id"], locked_id, env["lot"]["id"],
            patient_mrn="MRN-6001", measured_value=101.0,
        ),
        make_operator_headers(locked_id),
    )


def test_rank_forty_four_lot_verification_outranks_rank_fifty_two_operator_access():
    """An unverified lot plus a locked-out operator reports the reagent problem.

    PRD 2.7: "**Rank 44 — lot verified.** On patient-result capture the referenced
    lot's `verification_status` must be `VERIFIED`; on quality-control unlock the lot
    referenced by the confirming control run must be `VERIFIED`. Otherwise
    `ERR_LOT_NOT_VERIFIED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/unverified_lot_preempts_operator_access_lock_on_result_capture
    """
    env = _site_with_unverified_lot_and_a_locked_operator()
    assert read_operator(env["locked"]["id"])["access_status"] == "LOCKED_OUT"

    response = _capture_with_locked_operator_on_unverified_lot(env)

    validate_error(response, "ERR_LOT_NOT_VERIFIED", 409)


def test_the_blocked_capture_changes_neither_the_lot_nor_the_instrument():
    """The lower-ranked access rule never fires and no state moves.

    PRD 2.7: "**Rank 52 — operator access.** On control-run recording,
    patient-result capture, posting and correction, the referenced operator — and,
    for posting and correction, the acting operator — must have `access_status` equal
    to `ACTIVE`. Otherwise `ERR_OPERATOR_ACCESS_LOCKED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/unverified_lot_preempts_operator_access_lock_on_result_capture
    """
    env = _site_with_unverified_lot_and_a_locked_operator()

    _capture_with_locked_operator_on_unverified_lot(env)

    assert read_lot(env["lot"]["id"])["verification_status"] == "UNVERIFIED"
    assert read_device(env["device"]["id"])["status"] == "ACTIVE"
    assert read_site(env["site"]["id"])["held_result_count"] == 0
