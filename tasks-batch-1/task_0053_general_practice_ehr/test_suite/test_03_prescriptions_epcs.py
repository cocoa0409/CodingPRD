"""Prescription lifecycle: the submit/revise cycle, the EPCS signing protocol,
the validation-priority conflict at signing, and the dispense -> adherence
cascade.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_provider_headers,
    TEST_USERS,
    set_clock,
    create_provider,
    create_patient,
    create_hedis_measure,
    create_visit_in_progress,
    create_prescription,
    create_prescription_pending,
    create_prescription_transmitted,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── Queue A: non_linear_state_machine / prescription_submit_revise_cycle ───

def test_submit_advances_draft_to_pending_signature(api):
    """PRD §3.7: "Submitting a draft advances it from `DRAFT` to `PENDING_SIGNATURE`;
    this requires the prescription to be `DRAFT` and requires the referenced visit to
    be in `IN_PROGRESS`, `CODED`, or `FINALIZED` status."

    Design: Difficulty/non_linear_state_machine/prescription_submit_revise_cycle
    """
    provider, patient, visit, rx = create_prescription_pending(schedule="NON_CONTROLLED")
    assert rx["status"] == "PENDING_SIGNATURE"


def test_revise_returns_pending_to_draft(api):
    """PRD §3.7: "A pending prescription can be revised back from `PENDING_SIGNATURE`
    to `DRAFT` so the drug or schedule can be corrected before signing."

    Design: Difficulty/non_linear_state_machine/prescription_submit_revise_cycle
    """
    provider, patient, visit, rx = create_prescription_pending(schedule="NON_CONTROLLED")
    prov_hdr = make_provider_headers(provider["id"])
    revised = validate_success(api.revise_prescription(rx["id"], prov_hdr), 200)
    assert revised["status"] == "DRAFT", (
        f"revise must return PENDING_SIGNATURE prescription to DRAFT, got {revised['status']}"
    )


# ─── Queue A: priority_pair_validation_conflict / sign_state_beats_epcs_safety ───

def test_sign_draft_controlled_returns_invalid_state_not_epcs(api):
    """PRD §2.9: "Only after these structural checks does the system evaluate state
    legality — whether the requested transition is defined from the resource's current
    state (`ERR_INVALID_STATE`) — followed by resource-ownership checks
    (`ERR_NOT_RESOURCE_OWNER`), and finally the domain-specific business rules
    described throughout Section 3."
    PRD §3.7: "Signing advances it from `PENDING_SIGNATURE` to `SIGNED`."

    Design: Difficulty/priority_pair_validation_conflict/sign_state_beats_epcs_safety
    """
    provider = create_provider(epcs_enrolled=False)
    provider, patient, visit = create_visit_in_progress(provider=provider)
    prov_hdr = make_provider_headers(provider["id"])
    # DRAFT controlled prescription, never submitted; no token, prescriber not enrolled.
    rx = create_prescription(patient["id"], provider["id"], visit["id"],
                             drug_name="Oxycodone", schedule="C_II")
    assert rx["status"] == "DRAFT"
    res = api.sign_prescription(rx["id"], {}, prov_hdr)
    # State legality (DRAFT cannot be signed) is evaluated before the EPCS business rule.
    validate_error(res, "ERR_INVALID_STATE")


def test_sign_draft_controlled_does_not_change_state(api):
    """PRD §3.7: "Signing advances it from `PENDING_SIGNATURE` to `SIGNED`."

    Design: Difficulty/priority_pair_validation_conflict/sign_state_beats_epcs_safety
    """
    provider = create_provider(epcs_enrolled=False)
    provider, patient, visit = create_visit_in_progress(provider=provider)
    prov_hdr = make_provider_headers(provider["id"])
    rx = create_prescription(patient["id"], provider["id"], visit["id"],
                             drug_name="Oxycodone", schedule="C_II")
    api.sign_prescription(rx["id"], {}, prov_hdr)
    after = validate_success(api.get_prescription(rx["id"], prov_hdr), 200)
    assert after["status"] == "DRAFT", (
        f"a rejected sign from DRAFT must leave the prescription in DRAFT, got {after['status']}"
    )


# ─── Queue B: validations / controlled_sign_without_epcs_enrollment_returns_422 ───

def test_controlled_sign_without_epcs_enrollment_rejected(api):
    """PRD §3.7: "When the prescription's `schedule` is anything other than
    `NON_CONTROLLED`, signing additionally requires that the prescribing provider has
    `epcs_enrolled` true, has a non-null `dea_number`, and that a non-empty
    `two_factor_token` is supplied with the sign request. If any of those three
    controlled-substance requirements is unmet, the sign is rejected with
    `ERR_EPCS_REQUIREMENTS_NOT_MET`."

    Design: Corner/validations/controlled_sign_without_epcs_enrollment_returns_422
    """
    provider = create_provider(epcs_enrolled=False)
    # PENDING_SIGNATURE C_II prescription so the state precondition passes and the
    # EPCS safety check is the failing rule.
    provider, patient, visit, rx = create_prescription_pending(
        provider=provider, schedule="C_II", rx_overrides={"drug_name": "Hydrocodone"}
    )
    prov_hdr = make_provider_headers(provider["id"])
    res = api.sign_prescription(rx["id"], {"two_factor_token": "abc"}, prov_hdr)
    validate_error(res, "ERR_EPCS_REQUIREMENTS_NOT_MET")


# ─── Queue A: transitive_cascade / dispense_prescription_depth2_cascade ───

def test_dispense_increments_active_medication_count(api):
    """PRD §3.7: "When a prescription is dispensed, the patient's
    `active_medication_count` is recomputed upward."

    Design: Difficulty/transitive_cascade/dispense_prescription_depth2_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    provider = create_provider()
    patient = create_patient(first_name="Adult", date_of_birth="1980-01-01", sex="F")
    create_hedis_measure(patient["id"], measure_type="MED_ADHERENCE",
                         measurement_year=2026, method="ADMINISTRATIVE")
    provider, patient, visit, rx = create_prescription_transmitted(
        provider=provider, patient=patient, rx_overrides={"drug_name": "Metformin"}
    )
    prov_hdr = make_provider_headers(provider["id"])
    validate_success(api.dispense_prescription(rx["id"], prov_hdr), 200)
    refreshed = validate_success(api.get_patient(patient["id"], FD), 200)
    assert refreshed["active_medication_count"] == 1, (
        f"dispense must recompute active_medication_count to 1, got {refreshed['active_medication_count']}"
    )


def test_dispense_flips_adherence_measure_and_closes_gap(api):
    """PRD §3.7: "if the patient has a HEDIS measure of type `MED_ADHERENCE` still in
    `GAP` status for the current measurement year and the recomputed
    `active_medication_count` is at least the adherence minimum of one fill, that
    measure flips to `NUMERATOR_COMPLIANT` and the patient's `open_care_gaps` is
    recomputed."

    Design: Difficulty/transitive_cascade/dispense_prescription_depth2_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    provider = create_provider()
    patient = create_patient(first_name="Adult", date_of_birth="1980-01-01", sex="F")
    measure = create_hedis_measure(patient["id"], measure_type="MED_ADHERENCE",
                                   measurement_year=2026, method="ADMINISTRATIVE")
    provider, patient, visit, rx = create_prescription_transmitted(
        provider=provider, patient=patient, rx_overrides={"drug_name": "Metformin"}
    )
    prov_hdr = make_provider_headers(provider["id"])
    validate_success(api.dispense_prescription(rx["id"], prov_hdr), 200)

    refreshed_measure = validate_success(api.get_hedis_measure(measure["id"], FD), 200)
    assert refreshed_measure["status"] == "NUMERATOR_COMPLIANT", (
        f"adherence measure must flip to NUMERATOR_COMPLIANT, got {refreshed_measure['status']}"
    )
    refreshed_patient = validate_success(api.get_patient(patient["id"], FD), 200)
    assert refreshed_patient["open_care_gaps"] == 0, (
        f"open_care_gaps must recompute to 0 after the gap closes, got {refreshed_patient['open_care_gaps']}"
    )
