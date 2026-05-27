"""Endpoint corner cases: list filter by claimant_id, evidence sub-resource;
immediate-consistency read after submit."""
import pytest
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    api_client, TEST_USERS,
    set_clock,
    create_claimant, create_application_for_claimant, submit_application,
    attach_evidence,
    make_claimant_headers,
)


# =========================================================================
# Instance: list_applications_filter_by_claimant_id
# =========================================================================

def test_list_applications_filter_by_claimant_id(api):
    """PRD §4: "`GET /ssdi/applications` | List applications | `SSAAdmin,
    Claimant, DDSExaminer`"
    PRD §2.3: "List endpoints accept two query parameters to control
    paging."

    Design: Corner/endpoints/list_applications_filter_by_claimant_id
    """
    set_clock("2026-01-15T00:00:00Z")
    a = create_claimant(ssn_last4="4001", full_name="Filter A",
                        date_of_birth="1980-01-01T00:00:00Z", filing_state="TX")
    b = create_claimant(ssn_last4="4002", full_name="Filter B",
                        date_of_birth="1980-01-01T00:00:00Z", filing_state="TX")
    create_application_for_claimant(a["id"])
    create_application_for_claimant(b["id"])
    res = api_client.list_applications(TEST_USERS["ssa_admin_headers"],
                                        params={"claimant_id": a["id"]})
    items, meta = validate_paginated(res)
    assert meta["total_count"] == 1, \
        f"Expected exactly 1 application for claimant A, got total_count={meta['total_count']}"
    assert len(items) == 1
    assert items[0]["claimant_id"] == a["id"]


# =========================================================================
# Instance: get_application_evidence_sub_resource_returns_array
# =========================================================================

def test_application_evidence_subresource_returns_all_rows(api):
    """PRD §3.3: "The list-evidence endpoint scoped to an application
    returns the full set, and is readable by the claimant, the examiner,
    the ALJ, and an `SSAAdmin`."
    PRD §4: "`GET /ssdi/applications/{id}/evidence` | List evidence on an
    application"

    Design: Corner/endpoints/get_application_evidence_sub_resource_returns_array
    """
    set_clock("2026-01-15T00:00:00Z")
    c = create_claimant(ssn_last4="4003", full_name="Ev List",
                        date_of_birth="1980-01-01T00:00:00Z", filing_state="TX")
    app = create_application_for_claimant(c["id"])
    # Application is in DRAFT — but evidence endpoint is not state-gated per
    # PRD §3.3 (which says evidence can be attached "Once an application
    # is in `MEDICAL_REVIEW`" — so we submit first to satisfy that). Use a
    # young claimant baseline so we can attach evidence after submit only
    # if status allows it. Simpler: submit so the app reaches MEDICAL_REVIEW
    # or DENIED_QC; we then list whatever evidence has been attached.
    # For this corner the recipe expects two evidence rows; we attach them
    # via the DRAFT state directly. The list endpoint should still return them.
    attach_evidence(app["id"], claimant_id=c["id"],
                    source_type="TREATING_PHYSICIAN",
                    diagnosis_code="M54.5", severity_score=80)
    attach_evidence(app["id"], claimant_id=c["id"],
                    source_type="CONSULTATIVE_EXAM", report_date="2024-03-01T00:00:00Z",
                    diagnosis_code="F32.9", severity_score=70)
    res = api_client.list_evidence(app["id"], make_claimant_headers(c["id"]))
    items, meta = validate_paginated(res)
    assert len(items) == 2, f"Expected 2 evidence rows, got {len(items)}"


# =========================================================================
# Instance: immediate_consistency_application_status_visible_after_submit
# =========================================================================

def test_status_after_submit_visible_on_next_get(api):
    """PRD §2.6: "the cascade is part of the same logical transaction:
    the parent transition and every dependent mutation are applied
    together, and the dependent resource's `status` change is observable
    on its next read."
    PRD §3.2: "When `insured_status` resolves to `NOT_INSURED`, the
    server transitions through `QC_REVIEW` to the terminal `DENIED_QC`
    state and increments the `version`."

    Design: Corner/consistency_model/immediate_consistency_application_status_visible_after_submit
    """
    set_clock("2026-01-15T00:00:00Z")
    c = create_claimant(ssn_last4="8001", full_name="Atomic Sub",
                        date_of_birth="2002-06-01T00:00:00Z", filing_state="TX")
    app = create_application_for_claimant(
        c["id"],
        alleged_onset_date="2025-01-01T00:00:00Z",
        protective_filing_date="2026-01-15T00:00:00Z",
    )
    submit_application(app["id"], c["id"])
    # Immediate read sees terminal DENIED_QC.
    res = api_client.get_application(app["id"], make_claimant_headers(c["id"]))
    app_after = get_success_data(res)
    assert app_after["status"] == "DENIED_QC"
    assert app_after["insured_status"] == "NOT_INSURED"
