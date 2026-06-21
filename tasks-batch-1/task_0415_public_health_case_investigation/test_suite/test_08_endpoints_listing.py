"""Listing, pagination, filtering, reverse-lookup, and cross-reference endpoints.

Queue B (Corner): endpoints section instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_investigator_headers,
    make_tracer_headers,
    make_epi_headers,
    ApiErrorId,
)
from test_helpers import fixtures as fx

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_list_cases_paginated_envelope_total_count_has_more(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return."
    PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_cases_paginated_envelope_total_count_has_more
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    for i, ref in enumerate(("PT-1", "PT-2", "PT-3")):
        fx.open_case(
            program["id"], j, patient_reference=ref,
            symptom_onset_date=f"2026-03-1{i}T00:00:00.000Z",
        )
    res = api.list_cases(make_epi_headers(), params={"program_id": program["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert len(data) == 2, len(data)
    assert meta["total_count"] == 3, meta["total_count"]
    assert meta["has_more"] is True


def test_list_contacts_filter_by_status_returns_only_matching(api):
    """PRD §4 endpoint: "GET `/surveillance/contacts` List contacts (filterable by program_id,
    source_case_id, monitoring_jurisdiction_id, status, priority_band, promoted_case_id)".
    PRD §3.8: "Queuing a contact for notification advances it to `NOTIFICATION_PENDING`".

    Design: Corner/endpoints/list_contacts_filter_by_status_returns_only_matching
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    ka = fx.elicit_contact(program["id"], ci["id"], j, contact_reference="K-A")
    kb = fx.elicit_contact(
        program["id"], ci["id"], j, contact_reference="K-B",
        exposure_setting="WORKPLACE", proximity_meters=1.5, cumulative_exposure_minutes=10,
    )
    validate_success(api.queue_notification(kb["id"], make_tracer_headers(j)))
    res = api.list_contacts(make_tracer_headers(j), params={"program_id": program["id"], "status": "ELICITED"})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1, meta["total_count"]
    assert data[0]["id"] == ka["id"]


def test_case_cluster_reverse_lookup_empty_for_unclustered_case(api):
    """PRD §3.11: "A case's cluster can be retrieved by a reverse lookup that returns the
    zero-or-one cluster the case belongs to."

    Design: Corner/endpoints/case_cluster_reverse_lookup_empty_for_unclustered_case
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    cn = fx.open_case(program["id"], j, patient_reference="PT-N")
    res = api.get_case_cluster(cn["id"], make_epi_headers())
    data, meta = validate_paginated(res)
    assert len(data) == 0, len(data)


def test_link_lab_result_nonexistent_lab_returns_lab_result_not_found(api):
    """PRD §2.5: "the foreign keys it accepts — `program_id`, `jurisdiction_id`, `condition_code`,
    `source_case_id`, `lab_result_id`, ... must each reference an existing row within the same
    program; an unresolved reference yields the corresponding not-found error."

    Design: Corner/endpoints/link_lab_result_nonexistent_lab_returns_lab_result_not_found
    """
    program, jurisdiction, _, ci = fx.setup_interviewed_case()
    j = jurisdiction["id"]
    res = api.link_lab_result(ci["id"], {"lab_result_id": MISSING_UUID}, make_investigator_headers(j))
    validate_error(res, ApiErrorId.ERR_LAB_RESULT_NOT_FOUND.value)


def test_record_notification_failed_outcome_conditional_action(api):
    """PRD §3.8: "a `FAILED` outcome advances `NOTIFICATION_PENDING → NOTIFICATION_FAILED` and
    likewise increments `notification_attempts` by one, after which the contact can be re-queued,
    looping back to `NOTIFICATION_PENDING`."

    Design: Corner/endpoints/record_notification_failed_outcome_conditional_action
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    kf = fx.elicit_contact(program["id"], ci["id"], j, contact_reference="K-F")
    validate_success(api.queue_notification(kf["id"], make_tracer_headers(j)))
    res = api.record_notification(kf["id"], {"outcome": "FAILED"}, make_tracer_headers(j))
    data = validate_success(res)
    assert data["status"] == "NOTIFICATION_FAILED"
    assert data["notification_attempts"] == 1
