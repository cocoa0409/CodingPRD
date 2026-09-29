"""Compensating actions must restore exactly what the forward action moved."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    SURVEYOR,
    SURVEYOR_BETA,
    add_finding,
    api_client,
    assert_logical_instant,
    capture_and_post_result,
    capture_results,
    create_device,
    excursion_resolution_payload,
    issue_survey,
    open_survey,
    qc_unlock_payload,
    read_deficiency,
    read_device,
    read_inspection,
    read_lot,
    read_readiness,
    read_result,
    read_site,
    read_storage_unit,
    record_qc_run,
    rescind_survey,
    setup_covered_site,
    setup_site_with_verified_lot,
    setup_temperature_excursion,
    validate_success,
)

# ─── held_result_count_and_posture_restored_exactly_by_qc_unlock ──────


def _locked_instrument_with_three_held_and_one_posted_result():
    """Three held results plus one already-posted result and a MANUAL_ENTRY sibling."""
    env = setup_site_with_verified_lot(
        certificate_overrides={"certificate_number": "45D2243026"},
        site_overrides={
            "name": "Conservation POCT",
            "department_code": "DEPT-330",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Alma Ruiz"},
        device_overrides={"serial_number": "SN-1201"},
        lot_overrides={"lot_number": "LOT-J1"},
    )
    env["manual_device"] = create_device(
        env["site"]["id"], serial_number="SN-1202",
        device_model="StripReader-Z", analyte="URINALYSIS",
        connectivity_mode="MANUAL_ENTRY",
    )
    env["posted"] = capture_and_post_result(
        env, patient_mrn="MRN-8000", measured_value=95.0
    )
    env["pending"] = capture_results(env, 3)
    env["pre_site"] = read_site(env["site"]["id"])
    record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", 140.0,
    )
    env["mid_site"] = read_site(env["site"]["id"])
    env["confirming_run"] = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", 100.0,
    )
    return env


def _clear_the_lock(env):
    return api_client.qc_unlock_device(
        env["device"]["id"], qc_unlock_payload(env["confirming_run"]["id"]),
        COORDINATOR,
    )


def test_the_unlock_returns_the_held_count_and_posture_to_their_pre_lock_values():
    """0 -> 3 -> 0 with the posture walking OPEN -> RESTRICTED -> OPEN.

    PRD 3.4: "Then the compensation runs: every patient result on the instrument
    whose `posting_status` is `HELD` **and** whose `held_by_device_lock_at` is not null
    returns `HELD → PENDING_REVIEW` with `held_by_device_lock_at` cleared to null,
    processed by `created_at` ascending then `patient_mrn` ascending, and the site's
    `held_result_count` is decremented by exactly that count."

    Design: Difficulty/compensating_invariant/held_result_count_and_posture_restored_exactly_by_qc_unlock
    """
    env = _locked_instrument_with_three_held_and_one_posted_result()

    assert env["pre_site"]["held_result_count"] == 0
    assert env["pre_site"]["oversight_posture"] == "OPEN"
    assert env["mid_site"]["held_result_count"] == 3
    assert env["mid_site"]["oversight_posture"] == "RESTRICTED"

    _clear_the_lock(env)

    post_site = read_site(env["site"]["id"])
    assert post_site["held_result_count"] == 0
    assert post_site["oversight_posture"] == "OPEN"


def test_every_held_result_returns_to_pending_review_with_a_cleared_stamp():
    """The three released results carry no residue of the hold.

    PRD 3.6: "An instrument lock from a failing control run moves `PENDING_REVIEW`
    results to `HELD` and stamps `held_by_device_lock_at`, and clearing that lock
    brings them back to `PENDING_REVIEW` (§3.4)."

    Design: Difficulty/compensating_invariant/held_result_count_and_posture_restored_exactly_by_qc_unlock
    """
    env = _locked_instrument_with_three_held_and_one_posted_result()

    unlocked = validate_success(_clear_the_lock(env), 200)

    assert unlocked["id"] == env["device"]["id"]
    for result in env["pending"]:
        read_back = read_result(result["id"])
        assert read_back["posting_status"] == "PENDING_REVIEW"
        assert read_back["held_by_device_lock_at"] is None
    device = read_device(env["device"]["id"])
    assert device["status"] == "ACTIVE"
    assert device["qc_lock_reason"] is None


def test_the_compensation_touches_neither_the_posted_result_nor_the_sibling():
    """The already-posted value and the MANUAL_ENTRY instrument end where they began.

    PRD 3.4: "The posture is then re-derived; when the held count falls below 3 and no
    other restricting condition holds, the posture returns to its pre-lock value and
    the `manual_entry_suspended` flags at the site are cleared."

    Design: Difficulty/compensating_invariant/held_result_count_and_posture_restored_exactly_by_qc_unlock
    """
    env = _locked_instrument_with_three_held_and_one_posted_result()

    _clear_the_lock(env)

    posted = read_result(env["posted"]["id"])
    assert posted["posting_status"] == "POSTED"
    assert posted["posted_value"] == 95.0
    sibling = read_device(env["manual_device"]["id"])
    assert sibling["status"] == "ACTIVE"
    assert sibling["manual_entry_suspended"] is False
    assert read_site(env["site"]["id"])["manual_entry_blocked"] is False


# ─── open_deficiency_weight_ledger_restored_by_inspection_rescind ─────


def _two_issued_surveys_weighing_three_and_eleven():
    """Survey A pins 3.00 and survey B pins 11.00, for a ledger of 14.00."""
    _certificate, site, _coverage = setup_covered_site(
        certificate_overrides={"certificate_number": "45D2243027"},
        site_overrides={
            "name": "Ledger POCT",
            "department_code": "DEPT-340",
            "complexity_scope": "WAIVED",
        },
    )
    inspection_a = open_survey(
        site["id"], SURVEYOR,
        inspection_type="INTERNAL_READINESS", scheduled_date="2026-08-01",
    )
    finding_a = add_finding(
        inspection_a["id"], SURVEYOR,
        category="PERSONNEL_COMPETENCY", severity="STANDARD_LEVEL",
        description="Annual competency records incomplete",
        correction_due_date="2026-10-31",
    )
    issued_a = issue_survey(inspection_a["id"], SURVEYOR, issued_on="2026-08-01")
    pre_site = read_site(site["id"])

    inspection_b = open_survey(
        site["id"], SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-08-01",
    )
    finding_b1 = add_finding(
        inspection_b["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="CONDITION_LEVEL",
        description="No two-level QC before patient testing",
        correction_due_date="2026-10-31",
    )
    finding_b2 = add_finding(
        inspection_b["id"], SURVEYOR,
        category="RESULT_REPORTING", severity="STANDARD_LEVEL",
        description="Manual results posted without review",
        correction_due_date="2026-10-31",
    )
    issued_b = issue_survey(inspection_b["id"], SURVEYOR, issued_on="2026-08-01")
    mid_site = read_site(site["id"])
    return {
        "site": site,
        "inspection_a": issued_a,
        "inspection_b": issued_b,
        "finding_a": finding_a,
        "finding_b1": finding_b1,
        "finding_b2": finding_b2,
        "pre_site": pre_site,
        "mid_site": mid_site,
    }


def test_the_rescind_restores_the_ledger_to_the_exact_pre_issuance_value():
    """14.00 returns to precisely 3.00, with no recompute-from-zero drift.

    PRD 3.8: "Every finding of that survey whose `status` is `DRAFT`, `OPEN`,
    `CORRECTION_SUBMITTED` or `CORRECTION_REJECTED` moves to `VOIDED`, and the site's
    `open_deficiency_weight` is decremented by the sum of those findings' `weight`,
    with `DRAFT` findings contributing 0.00 because they were never weighed. The
    survey's `issued_weight_total` is left exactly as it was."

    Design: Difficulty/compensating_invariant/open_deficiency_weight_ledger_restored_exactly_by_inspection_rescind
    """
    env = _two_issued_surveys_weighing_three_and_eleven()

    assert env["inspection_a"]["issued_weight_total"] == 3.00
    assert env["pre_site"]["open_deficiency_weight"] == 3.00
    assert env["pre_site"]["oversight_posture"] == "OPEN"
    assert env["inspection_b"]["issued_weight_total"] == 11.00
    assert env["inspection_b"]["status"] == "DEFICIENCIES_ISSUED"
    assert env["mid_site"]["open_deficiency_weight"] == 14.00
    assert env["mid_site"]["oversight_posture"] == "RESTRICTED"

    rescinded = rescind_survey(env["inspection_b"]["id"], SURVEYOR)

    assert rescinded["status"] == "RESCINDED"
    assert rescinded["issued_weight_total"] == 11.00
    readiness = read_readiness(env["site"]["id"], SURVEYOR_BETA)
    assert readiness["open_deficiency_weight"] == 3.00
    assert readiness["deficiency_penalty"] == 7.50
    assert readiness["score"] == 92.50


def test_the_voided_findings_keep_their_pinned_weights():
    """Only ledger membership changes; the audited weights stay put.

    PRD 3.8: "A finding's weight is decided once, at issuance, and never recomputed
    afterwards. The base weight comes from severity: 8.00 for `CONDITION_LEVEL`, 3.00
    for `STANDARD_LEVEL`, 1.00 for `ADVISORY`."

    Design: Difficulty/compensating_invariant/open_deficiency_weight_ledger_restored_exactly_by_inspection_rescind
    """
    env = _two_issued_surveys_weighing_three_and_eleven()

    rescind_survey(env["inspection_b"]["id"], SURVEYOR)

    b1 = read_deficiency(env["finding_b1"]["id"])
    b2 = read_deficiency(env["finding_b2"]["id"])
    assert b1["status"] == "VOIDED"
    assert b1["weight"] == 8.00
    assert b2["status"] == "VOIDED"
    assert b2["weight"] == 3.00


def test_the_untouched_survey_and_its_finding_survive_the_compensation():
    """Survey A never moves, and the site posture returns to its pre-B value.

    PRD 2.10: "Otherwise the posture is `OPEN`."

    Design: Difficulty/compensating_invariant/open_deficiency_weight_ledger_restored_exactly_by_inspection_rescind
    """
    env = _two_issued_surveys_weighing_three_and_eleven()

    rescind_survey(env["inspection_b"]["id"], SURVEYOR)

    assert read_deficiency(env["finding_a"]["id"])["status"] == "OPEN"
    assert read_inspection(env["inspection_a"]["id"])["status"] == (
        "DEFICIENCIES_ISSUED"
    )
    site = read_site(env["site"]["id"])
    assert site["oversight_posture"] == "OPEN"
    assert site["manual_entry_blocked"] is False


# ─── excursion_release_restores_lots_but_devices_and_results_stay ─────


def _open_excursion_over_a_verified_lot():
    env = setup_temperature_excursion(
        result_count=2,
        certificate_overrides={"certificate_number": "45D2243028"},
        site_overrides={
            "name": "Excursion Release POCT",
            "department_code": "DEPT-350",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Alma Ruiz"},
        device_overrides={"serial_number": "SN-1301"},
        lot_overrides={"lot_number": "LOT-K1"},
    )
    env["verified_at"] = env["lot"]["verified_at"]
    env["mid_unit"] = read_storage_unit(env["storage_unit"]["id"])
    return env


def _release(env):
    return api_client.resolve_excursion(
        env["storage_unit"]["id"],
        excursion_resolution_payload(
            "RELEASE",
            assessment_note=(
                "Door ajar for 20 minutes; manufacturer confirms stability"
            ),
        ),
        COORDINATOR,
    )


def test_the_release_closes_the_excursion_and_empties_the_quarantine_counter():
    """The unit returns to IN_RANGE with its opened-at and counter reset.

    PRD 3.5: "On success the unit moves `EXCURSION_OPEN → IN_RANGE`, its
    `excursion_opened_at` returns to null and its `quarantined_lot_count` returns to
    0."

    Design: Difficulty/compensating_invariant/excursion_release_restores_lots_but_devices_and_rejected_results_stay
    """
    env = _open_excursion_over_a_verified_lot()

    assert env["mid_unit"]["excursion_state"] == "EXCURSION_OPEN"
    assert env["mid_unit"]["quarantined_lot_count"] == 1
    assert_logical_instant(
        env["mid_unit"]["excursion_opened_at"], "2026-08-01T00:00:00Z"
    )

    _release(env)

    unit = read_storage_unit(env["storage_unit"]["id"])
    assert unit["excursion_state"] == "IN_RANGE"
    assert unit["quarantined_lot_count"] == 0
    assert unit["excursion_opened_at"] is None
    assert unit["last_reading_c"] == 12.5


def test_the_released_lot_regains_verified_without_a_fresh_verification_instant():
    """The lot's original `verified_at` is preserved rather than re-stamped.

    PRD 3.5: "Under a **release** disposition, every `QUARANTINED` lot in the unit
    returns to `VERIFIED` with `quarantine_reason` cleared to null; because that return
    path is only available to a lot that had already passed two-level verification,
    release requires every quarantined lot in the unit to carry a non-null
    `verified_at`, and a unit holding a never-verified quarantined lot cannot be
    released — the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/excursion_release_restores_lots_but_devices_and_rejected_results_stay
    """
    env = _open_excursion_over_a_verified_lot()

    _release(env)

    lot = read_lot(env["lot"]["id"])
    assert lot["verification_status"] == "VERIFIED"
    assert lot["quarantine_reason"] is None
    assert lot["verified_at"] == env["verified_at"]


def test_the_release_is_partial_and_leaves_the_instrument_locked():
    """Neither the instrument lock nor the terminal rejections are undone.

    PRD 3.5: "In neither case are instruments unlocked: an instrument locked with
    `qc_lock_reason` of `LOT_QUARANTINE` stays `QC_LOCKED` until someone clears it with
    a passing confirming run as described in §3.4."

    Design: Difficulty/compensating_invariant/excursion_release_restores_lots_but_devices_and_rejected_results_stay
    """
    env = _open_excursion_over_a_verified_lot()

    _release(env)

    device = read_device(env["device"]["id"])
    assert device["status"] == "QC_LOCKED"
    assert device["qc_lock_reason"] == "LOT_QUARANTINE"
    for result in env["results"]:
        read_back = read_result(result["id"])
        assert read_back["posting_status"] == "REJECTED"
        assert read_back["posted_value"] is None
    site = read_site(env["site"]["id"], ADMIN)
    assert site["held_result_count"] == 0
    assert site["oversight_posture"] == "OPEN"
