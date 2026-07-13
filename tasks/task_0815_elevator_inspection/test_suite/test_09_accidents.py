"""Accident reporting and investigation: provisional-vs-final risk scoring,
the unsubstantiated discount, and the segregation-of-duties guard."""
import test_helpers as th
from test_helpers import ApiErrorId


# --------------------------------------------------------------------------
# Difficulty: dual_variant_calc / accident_risk_provisional_vs_final_substantiated
# --------------------------------------------------------------------------
def test_accident_provisional_risk_is_severity_weight(api):
    """PRD §3.9: "At filing, a provisional_risk_score is computed as the severity
    weight alone: 10 for MINOR, 30 for MODERATE, 60 for SEVERE, and 100 for FATAL."

    Design: Difficulty/dual_variant_calc/accident_risk_provisional_vs_final_substantiated
    """
    owner = th.new_owner(api)
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    report = th.validate_success(
        api.create_accident_report(
            th.create_accident_report_payload(device["id"], severity="SEVERE", occurred_period=1), th.SAFETY),
        expected_status=201)
    assert report["provisional_risk_score"] == 60, "SEVERE weight only, no multiplier"


def test_accident_substantiated_final_risk_scores_device(api):
    """PRD §3.9: "A finding of SUBSTANTIATED ... Its final_risk_score is the
    severity weight multiplied by the device's risk factor (1.5 for HIGH ...) and
    rounded half up, then increased by a bonus of 20 points for each of the device's
    deficiencies whose severity is CRITICAL and whose status is either OPEN or CITED."
    PRD §3.9: "In both branches the computed final_risk_score is written onto the
    report and also copied to the device's accident_risk_score".

    Design: Difficulty/dual_variant_calc/accident_risk_provisional_vs_final_substantiated
    """
    owner = th.new_owner(api)
    insp_a = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    lead = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    # A failed inspection with a CRITICAL deficiency leaves it CITED via the cascade.
    ins = th.inspection_in_progress(api, device["id"], insp_a["id"], itype="ANNUAL", start=1, end=2)
    th.complete_inspection(api, ins["id"], insp_a["id"], "FAIL",
                           [th.deficiency_entry("C-CRIT", "CRITICAL", "brake failure")])
    report = th.file_accident_report(api, device["id"], severity="SEVERE", occurred_period=1)
    th.open_investigation(api, report["id"], lead["id"])
    closed = th.close_investigation(api, report["id"], lead["id"], "SUBSTANTIATED")
    assert closed["status"] == "SUBSTANTIATED"
    assert closed["final_risk_score"] == 110, "round(60*1.5)=90 + 20*1 CITED critical"
    dev = th.get_device(api, device["id"])
    assert dev["accident_risk_score"] == 110


# --------------------------------------------------------------------------
# Corner: calculations / accident_close_unsubstantiated_risk_variant
# --------------------------------------------------------------------------
def test_accident_unsubstantiated_discounts_to_quarter_weight(api):
    """PRD §3.9: "A finding of UNSUBSTANTIATED moves the report to the terminal
    UNSUBSTANTIATED state. Its final_risk_score is the severity weight multiplied by
    a factor of 0.25 and rounded half up — a discount to one quarter of the weight,
    with no device-risk multiplier and no deficiency bonus."

    Design: Corner/calculations/accident_close_unsubstantiated_risk_variant
    """
    owner = th.new_owner(api)
    lead = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    report = th.file_accident_report(api, device["id"], severity="SEVERE", occurred_period=1)
    th.open_investigation(api, report["id"], lead["id"])
    closed = th.close_investigation(api, report["id"], lead["id"], "UNSUBSTANTIATED")
    assert closed["status"] == "UNSUBSTANTIATED"
    assert closed["final_risk_score"] == 15, "round_half_up(60*0.25)"
    dev = th.get_device(api, device["id"])
    assert dev["accident_risk_score"] == 15


# --------------------------------------------------------------------------
# Corner: validations / accident_lead_current_inspector_returns_segregation
# --------------------------------------------------------------------------
def test_accident_lead_current_inspector_returns_segregation(api):
    """PRD §3.9: "the nominated lead must not be the assigned_inspector_id of any
    inspection of this same device that is currently ASSIGNED or IN_PROGRESS — an
    inspector routinely servicing the device may not lead its accident
    investigation — otherwise the request is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/validations/accident_lead_current_inspector_returns_segregation
    """
    owner = th.new_owner(api)
    insp_x = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.schedule_inspection(api, device["id"], itype="ANNUAL", start=1, end=2)
    th.assign_inspection(api, ins["id"], insp_x["id"])
    report = th.file_accident_report(api, device["id"], severity="MODERATE", occurred_period=1)
    resp = api.open_investigation(report["id"], th.open_investigation_payload(insp_x["id"]), th.SAFETY)
    th.validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
