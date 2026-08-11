"""Winding down, closing jurisdictions and dissolving the entity."""
from test_helpers import (
    AGENT,
    DE_RULE_FINAL_REPORT,
    DE_RULE_MIN,
    OFFICER,
    ApiErrorId,
    capture,
    draft_standalone_filing,
    new_obligation,
    new_payment,
    read_entity,
    read_obligation,
    read_registration,
    record_filing_outcome,
    setup_winding_down_entity,
    submit_filing,
    validate_error,
    validate_success,
)


def test_aborting_the_wind_down_keeps_the_final_report_flag_raised(api):
    """PRD §3.12: "On success `lifecycle_status` returns to `ACTIVE` and the entity's
    `version` increases by 1. `final_report_required` is **deliberately not cleared**:
    it stays true, so the final-report obligation survives the abort and will still have
    to be settled if the entity is wound down again later."

    Design: Corner/state_machines/corner_abort_wind_down_returns_to_active_but_keeps_final_report_flag
    """
    scene = setup_winding_down_entity(DE_RULE_MIN)
    assert scene["entity"]["lifecycle_status"] == "WINDING_DOWN"
    assert scene["entity"]["final_report_required"] is True

    data = validate_success(api.abort_wind_down(scene["entity"]["id"], OFFICER))

    assert data["lifecycle_status"] == "ACTIVE"
    assert data["final_report_required"] is True
    assert read_entity(scene["entity"]["id"])["final_report_required"] is True


def test_final_report_survives_termination_and_blocks_the_dissolution(api):
    """PRD §3.12: "Obligations of the registration in one of the four open statuses are
    voided in the same way as on withdrawal, **except that obligations whose
    `obligation_type` is `FINAL_REPORT` are left untouched**: the final-report duty
    deliberately survives termination of the registration it belongs to, because it is
    the last thing the jurisdiction expects to receive."
    PRD §3.12: "then every registration of the entity must be in `WITHDRAWN`,
    `TERMINATED` or `CLOSED_PERMANENT` — registered-agent service cannot end while any
    registration is still occupied — else `ERR_ACTIVE_REGISTRATIONS_EXIST`; then, when
    `final_report_required` is true, every `FINAL_REPORT` obligation of the entity must
    be in `SATISFIED` or `WAIVED`, else `ERR_FINAL_REPORT_OUTSTANDING`."

    Design: Corner/validations/corner_final_report_obligation_survives_termination_and_blocks_dissolution
    """
    scene = setup_winding_down_entity(DE_RULE_FINAL_REPORT)
    registration_id = scene["registration"]["id"]
    annual = new_obligation(registration_id, "ANNUAL_REPORT", 2027)
    final = new_obligation(registration_id, "FINAL_REPORT", 2026)

    filing = draft_standalone_filing(registration_id, "DISSOLUTION")
    # dissolution_fee_cents 0 plus the 4900 base service charge.
    assert filing["total_fee_cents"] == 4900
    payment = new_payment(scene["client"]["id"], 4900)
    capture(payment["id"], 4900, filing["id"])
    submit_filing(filing["id"])
    record_filing_outcome(filing["id"], "ACCEPTED")

    validate_success(api.terminate_registration(registration_id, AGENT))

    assert read_registration(registration_id)["status"] == "TERMINATED"
    assert read_obligation(annual["id"])["status"] == "VOIDED"
    assert read_obligation(final["id"])["status"] == "SCHEDULED"
    assert read_entity(scene["entity"]["id"])["final_report_required"] is True

    response = api.dissolve_legal_entity(scene["entity"]["id"], OFFICER)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_FINAL_REPORT_OUTSTANDING.value)
    assert read_entity(scene["entity"]["id"])["lifecycle_status"] == "WINDING_DOWN"
