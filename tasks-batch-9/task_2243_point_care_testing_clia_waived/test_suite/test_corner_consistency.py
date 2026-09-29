"""Immediate consistency: the mutating response already carries the new derived state."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    SURVEYOR,
    add_finding,
    api_client,
    issue_survey,
    make_operator_headers,
    open_survey,
    patient_result_payload,
    read_deficiency,
    read_device,
    read_readiness,
    read_site,
    setup_site_with_verified_lot,
    validate_error,
)

SEPTEMBER = "2026-09-01T08:00:00Z"


def test_the_issue_response_and_every_read_after_it_agree_on_the_new_posture():
    """11.00 of pinned weight restricts the site inside the issuing request itself.

    PRD 3.8: "Issuance then sets the survey's `issued_weight_total` to the sum of the
    weights it just pinned, adds that total to the site's `open_deficiency_weight`,
    re-derives the site's posture — 6.0 of open weight is enough to restrict a site, and
    16.0 suspends it, so a single repeat condition-level citation suspends a site on its
    own — recomputes the site's `inspection_readiness_score`, and snapshots that freshly
    computed score into the survey's `readiness_score_at_issue`."

    PRD 3.9: "1. **Deficiency penalty.** Multiply the open deficiency weight by 2.5,
    round the product half up to 2 decimals, and take the lesser of that and the cap of
    50.0."

    PRD 3.6: "A `MANUAL` `entry_mode` demands a non-empty `manual_entry_reason`, reported
    as `ERR_MANUAL_ENTRY_REASON_REQUIRED` when missing, and it additionally demands that
    the site's `manual_entry_blocked` be false **and** the instrument's
    `manual_entry_suspended` be false, reported as `ERR_MANUAL_ENTRY_NOT_PERMITTED`
    otherwise."

    Design: Corner/consistency_model/issue_response_carries_the_recomputed_readiness_and_weight_with_no_lag
    """
    env = setup_site_with_verified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243055"},
        site_overrides={
            "name": "Cath Lab POCT", "department_code": "DEPT-5200",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={
            "full_name": "Yusuf Delacroix", "role_title": "MEDICAL_TECHNOLOGIST",
            "hire_date": "2026-01-05",
        },
        device_overrides={
            "serial_number": "SN-GL-5200", "connectivity_mode": "MANUAL_ENTRY",
        },
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    before = read_site(env["site"]["id"], COORDINATOR)
    assert before["inspection_readiness_score"] == 100.00
    assert before["oversight_posture"] == "OPEN"
    assert before["manual_entry_blocked"] is False

    survey = open_survey(
        env["site"]["id"], SURVEYOR,
        inspection_type="COMPLAINT_SURVEY", scheduled_date="2026-09-01",
    )
    condition_level = add_finding(
        survey["id"], SURVEYOR,
        category="RESULT_REPORTING", severity="CONDITION_LEVEL",
        description="manually entered results posted without second-person review",
        correction_due_date="2026-10-01",
    )
    standard_level = add_finding(
        survey["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="STANDARD_LEVEL",
        description="control log missing two days",
        correction_due_date="2026-10-01",
    )

    issued = issue_survey(survey["id"], SURVEYOR, issued_on="2026-09-01")

    assert issued["issued_weight_total"] == 11.00
    assert issued["readiness_score_at_issue"] == 72.50
    assert issued["status"] == "DEFICIENCIES_ISSUED"

    after = read_site(env["site"]["id"], COORDINATOR)
    assert after["inspection_readiness_score"] == 72.50
    assert after["open_deficiency_weight"] == 11.00
    assert after["oversight_posture"] == "RESTRICTED"
    assert after["manual_entry_blocked"] is True
    breakdown = read_readiness(env["site"]["id"], SURVEYOR)
    assert breakdown["score"] == 72.50
    assert breakdown["deficiency_penalty"] == 27.50
    assert breakdown["open_deficiency_weight"] == 11.00
    device = read_device(env["device"]["id"], COORDINATOR)
    assert device["status"] == "ACTIVE"
    assert device["manual_entry_suspended"] is True

    response = api_client.create_test_result(
        patient_result_payload(
            env["device"]["id"], env["operator"]["id"], env["lot"]["id"],
            patient_mrn="MRN-5201", measured_value=108.0,
            entry_mode="MANUAL", manual_entry_reason="interface still down",
        ),
        make_operator_headers(env["operator"]["id"]),
    )

    validate_error(response, "ERR_MANUAL_ENTRY_NOT_PERMITTED", 422)
    assert read_deficiency(condition_level["id"], ADMIN)["weight"] == 8.00
    assert read_deficiency(standard_level["id"], ADMIN)["weight"] == 3.00
