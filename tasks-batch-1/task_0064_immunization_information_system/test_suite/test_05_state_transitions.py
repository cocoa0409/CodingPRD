"""Invalid transitions, terminal-state lockdown, precondition enforcement, and
divergent side-effect branches across the entity state machines."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_catalog_and_patient, setup_patient_with_doses, issue_recall,
    reverse_recall, open_report, add_line, file_adverse_event,
    setup_adverse_event_under_review, create_provider, create_patient,
    make_provider_headers, api_client, make_registrar_headers,
    create_product_payload,
)
from prd_bench_local_runner.testing import validate_paginated

REG = make_registrar_headers()
C1 = dict(product_code="C1", antigen="C1", doses_in_series=1, min_age_days=0,
          recommended_age_days=0, min_interval_days=0)


def test_adjudicate_from_draft_returns_invalid_state(api):
    """PRD §3.8: "Adjudication ... must be applied to a SUBMITTED report".
    PRD §3.3: "any state-transition endpoint whose target resource is not in a
    state from which the requested transition is defined is rejected with
    ERR_INVALID_STATE".

    Design: Corner/state_machines/adjudicate_from_draft_returns_invalid_state
    """
    provider = create_provider(authorized_product_codes=["C1"])
    report = get_success_data(api_client.create_provider_report(
        {"provider_id": provider["id"], "line_count": 1}, REG))
    validate_error(api_client.adjudicate_provider_report(report["id"], REG),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_from_reported_returns_invalid_state(api):
    """PRD §3.5: "From REPORTED it advances to UNDER_REVIEW on review; from
    UNDER_REVIEW it advances to CONFIRMED on confirmation ... a transition
    attempted from any other status is rejected with ERR_INVALID_STATE."

    Confirming a still-REPORTED event (skipping review) is rejected.

    Design: Corner/state_machines/confirm_from_reported_returns_invalid_state
    """
    _, _, _, _, doses = setup_patient_with_doses(
        dose_dates=["2025-01-01"],
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    ae = file_adverse_event(doses[0]["id"], "SERIOUS")
    validate_error(api_client.confirm_adverse_event(ae["id"], REG),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_reverse_already_reversed_recall_returns_invalid_state(api):
    """PRD §3.9: "Reversing a recall ... is permitted only while the recall is in
    its issued posture and the lot is still recalled by it; a reversal attempted
    otherwise is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/reverse_already_reversed_recall_returns_invalid_state
    """
    product, provider, lot, patient = setup_catalog_and_patient(
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    recall = issue_recall(lot["id"], reason="x")
    reverse_recall(lot["id"], recall["id"])
    validate_error(api_client.reverse_recall(lot["id"], recall["id"], REG),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_report_submit_line_count_mismatch(api):
    """PRD §3.8: "Submission requires that the report is in DRAFT, that the count
    of attached lines equals the report's line_count ... A count mismatch is
    rejected with ERR_LINE_COUNT_MISMATCH (HTTP 422)".

    A report declaring line_count 2 with only 1 line attached is rejected.

    Design: Corner/state_machines/report_submit_line_count_mismatch
    """
    product, provider, lot, patient = setup_catalog_and_patient(
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    prov_headers = make_provider_headers(provider["id"])
    report = open_report(provider["id"], 2, headers=prov_headers)
    add_line(report["id"], patient["id"], lot["id"], "2025-01-01",
             headers=prov_headers)
    validate_error(
        api_client.submit_provider_report(report["id"], prov_headers),
        ApiErrorId.ERR_LINE_COUNT_MISMATCH.value)


def test_report_all_reject_branch(api):
    """PRD §3.8: "When every line fails, the report transitions from SUBMITTED to
    REJECTED: no Immunization is created at all, accepted_count is set to 0, and
    rejected_count is set to line_count."

    A 1-line report on a recalled lot adjudicates to REJECTED.

    Design: Corner/state_machines/report_all_reject_branch
    """
    from test_helpers import setup_submitted_report
    _, _, lots, _, report = setup_submitted_report(
        lines=[{"lot_key": "main", "administered_date": "2025-01-01"}],
        line_count=1,
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    issue_recall(lots["main"]["id"], reason="recalled")
    data = validate_success(
        api_client.adjudicate_provider_report(report["id"], REG))
    assert data["status"] == "REJECTED", f"got {data['status']}"
    assert data["accepted_count"] == 0
    assert data["rejected_count"] == 1


def test_report_all_accept_branch(api):
    """PRD §3.8: "When every line passes, the report transitions from SUBMITTED
    to ACCEPTED: a RECORDED Immunization is created for each line ... each
    affected lot's administered_count is incremented by 1, and accepted_count is
    set to line_count while rejected_count is set to 0."

    Design: Corner/state_machines/report_all_accept_branch
    """
    from test_helpers import setup_submitted_report
    _, _, lots, _, report = setup_submitted_report(
        lines=[{"lot_key": "main", "administered_date": "2025-01-01"}],
        line_count=1,
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    data = validate_success(
        api_client.adjudicate_provider_report(report["id"], REG))
    assert data["status"] == "ACCEPTED", f"got {data['status']}"
    assert data["accepted_count"] == 1
    lot = get_success_data(api_client.get_lot(lots["main"]["id"], REG))
    assert lot["administered_count"] == 1


def test_confirmed_nonserious_ae_creates_no_contraindication(api):
    """PRD §3.5: "Confirming an event whose seriousness is NON_SERIOUS performs
    no such creation; the two branches differ only in this spawned record, and a
    non-serious confirmation simply records the status change."

    Design: Corner/state_machines/confirmed_nonserious_ae_no_contraindication
    """
    _, _, _, patient, _dose, ae = setup_adverse_event_under_review("NON_SERIOUS")
    data = validate_success(api_client.confirm_adverse_event(ae["id"], REG))
    assert data["status"] == "CONFIRMED"
    records, meta = validate_paginated(
        api_client.list_patient_allergy_records(patient["id"], REG))
    assert meta["total_count"] == 0, \
        f"expected no allergy records, got {meta['total_count']}"


def test_delete_immunization_blocked_by_open_adverse_event(api):
    """PRD §3.2: "A dose may not be retracted while any adverse event referencing
    it is in REPORTED, UNDER_REVIEW, or CONFIRMED status; such an attempt is
    rejected with ERR_ADVERSE_EVENT_BLOCKS_DELETE (HTTP 409)."

    Design: Corner/state_machines/delete_immunization_blocked_by_open_adverse_event
    """
    _, _, _, _, doses = setup_patient_with_doses(
        dose_dates=["2025-01-01"],
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    file_adverse_event(doses[0]["id"], "SERIOUS", symptoms="rash")
    validate_error(api_client.delete_immunization(doses[0]["id"], REG),
                   ApiErrorId.ERR_ADVERSE_EVENT_BLOCKS_DELETE.value)
