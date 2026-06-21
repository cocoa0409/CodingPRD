"""RBAC (exclusive-op denial, positive grant, jurisdiction-scope denial) and cross-cutting
layers (OCC success + version bump, multi-tenant listing isolation, derived-count
reconciliation, immediate consistency).

Queue B (Corner): rbac, cross_cutting_complexity_layers (non-stub), and consistency_model.
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
    make_intake_headers,
    make_epi_headers,
    ApiErrorId,
    create_program_payload,
    create_case_payload,
    create_contact_payload,
    create_transfer_payload,
)
from test_helpers import fixtures as fx, TEST_USERS


# ===========================================================================
# Queue B — rbac section
# ===========================================================================
def test_contact_tracer_cannot_create_program(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 endpoint: "POST `/surveillance/programs` Create a surveillance program JurisdictionAdmin".

    Design: Corner/rbac/contact_tracer_cannot_create_program
    """
    res = api.create_program(create_program_payload(name="Rogue PH"), TEST_USERS["tracer_headers"])
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_case_investigator_cannot_request_jurisdiction_transfer(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 endpoint: "POST `/surveillance/jurisdiction-transfers` Request transfer of a case to
    another jurisdiction EpiAnalyst".

    Design: Corner/rbac/case_investigator_cannot_request_jurisdiction_transfer
    """
    program = fx.create_program()
    j1 = fx.create_jurisdiction(program["id"], name="County 1", fips_code="06001")
    j2 = fx.create_jurisdiction(program["id"], name="County 2", fips_code="06002")
    fx.create_condition(program["id"])
    ci = fx.open_and_interview_case(program["id"], j1["id"], case_overrides={"patient_reference": "PT-I"})
    version = fx.observe_case_version(ci["id"])
    res = api.create_transfer(
        create_transfer_payload(program["id"], ci["id"], j2["id"], version),
        make_investigator_headers(j1["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_intake_processor_can_run_elr_intake_shared_op(api):
    """PRD §3.2: "An `IntakeProcessor` receives electronic lab reports. ... A freshly intaken
    result begins in `RECEIVED`."
    PRD §3.2: "If no such single matching case exists, the result instead becomes `UNLINKED` and
    carries no `linked_case_id`."

    Design: Corner/rbac/intake_processor_can_run_elr_intake_shared_op
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    res = api.create_lab_result(
        fx.create_lab_result_payload(program["id"], j, patient_reference="PT-X", result_value="POSITIVE"),
        make_intake_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["status"] == "UNLINKED"


def test_case_investigator_cross_jurisdiction_interview_scope_violation(api):
    """PRD §2.1: "When `X-User-Role` is `CaseInvestigator`, `X-User-ID` is the `id` of the acting
    `Jurisdiction`, and the investigator may act only on cases whose `jurisdiction_id` equals
    `X-User-ID`. ... Any attempt by a scoped role to operate on a resource outside its own
    jurisdiction is denied with `ERR_JURISDICTION_SCOPE_VIOLATION`."

    Design: Corner/rbac/case_investigator_cross_jurisdiction_interview_scope_violation
    """
    program = fx.create_program()
    j1 = fx.create_jurisdiction(program["id"], name="County 1", fips_code="06001")
    j2 = fx.create_jurisdiction(program["id"], name="County 2", fips_code="06002")
    fx.create_condition(program["id"])
    c1 = fx.open_case(program["id"], j1["id"], patient_reference="PT-1")
    # CaseInvestigator scoped to J2 interviews a J1-owned case.
    res = api.interview_case(c1["id"], {}, make_investigator_headers(j2["id"]))
    validate_error(res, ApiErrorId.ERR_JURISDICTION_SCOPE_VIOLATION.value)


# ===========================================================================
# Queue B — cross_cutting_complexity_layers (non-stub)
# ===========================================================================
def test_transfer_create_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "Before any state or business precondition on the case is evaluated, the system
    compares `expected_case_version` to the case's current `version`; if they differ, the request
    is rejected with `ERR_STALE_CASE_VERSION` and HTTP status 412."
    PRD §3.12: "A successful request creates a `JurisdictionTransfer` in `REQUESTED` whose
    `from_jurisdiction_id` is copied from the case's current `jurisdiction_id`, drives the case
    from its current state (`UNDER_INVESTIGATION` or `CLASSIFIED`) into `TRANSFER_PENDING` while
    remembering the prior state to restore on resolution, and increments the case's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/transfer_create_correct_version_succeeds_and_bumps_version
    """
    program = fx.create_program()
    j1 = fx.create_jurisdiction(program["id"], name="County 1", fips_code="06001")
    j2 = fx.create_jurisdiction(program["id"], name="County 2", fips_code="06002")
    fx.create_condition(program["id"])
    cc = fx.open_and_interview_case(program["id"], j1["id"], case_overrides={"patient_reference": "PT-CC"})
    cc_v = fx.observe_case_version(cc["id"])
    res = api.create_transfer(
        create_transfer_payload(program["id"], cc["id"], j2["id"], cc_v), make_epi_headers()
    )
    transfer = validate_success(res, expected_status=201)
    assert transfer["status"] == "REQUESTED"
    case = validate_success(api.get_case(cc["id"], make_epi_headers()))
    assert case["status"] == "TRANSFER_PENDING"
    assert case["version"] == cc_v + 1, case["version"]


def test_multi_tenancy_program_scoped_listing_isolation(api):
    """PRD §4 endpoint: "GET `/surveillance/cases` List cases (filterable by program_id,
    jurisdiction_id, condition_code, status, cluster_id, source_contact_id, source_lab_result_id)".
    PRD §2.5: "Resources in this platform form flat peer collections beneath the surveillance
    program rather than deep URL nesting".

    Design: Corner/cross_cutting_complexity_layers/multi_tenancy_program_scoped_listing_isolation
    """
    p1 = fx.create_program(name="State PH 1")
    j1 = fx.create_jurisdiction(p1["id"], name="County 1", fips_code="06001")
    fx.create_condition(p1["id"])
    c1 = fx.open_case(p1["id"], j1["id"], patient_reference="PT-P1")
    p2 = fx.create_program(name="State PH 2")
    j2 = fx.create_jurisdiction(p2["id"], name="County 2", fips_code="06002")
    fx.create_condition(p2["id"])
    fx.open_case(p2["id"], j2["id"], patient_reference="PT-P2")
    res = api.list_cases(make_epi_headers(), params={"program_id": p1["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1, meta["total_count"]
    assert data[0]["id"] == c1["id"]


def test_derived_field_contact_count_reconciles_after_second_elicit(api):
    """PRD §2.7: "`Case.contact_count` tracks the number of non-`VOIDED` contacts whose
    `source_case_id` equals that case's `id`. It rises by one when a contact is elicited and falls
    by one when such a contact is voided."

    Design: Corner/cross_cutting_complexity_layers/derived_field_contact_count_reconciles_after_second_elicit
    """
    program, jurisdiction, _, cr = fx.setup_interviewed_case(case_overrides={"patient_reference": "PT-R"})
    j = jurisdiction["id"]
    fx.elicit_contact(program["id"], cr["id"], j, contact_reference="K-1")
    fx.elicit_contact(
        program["id"], cr["id"], j, contact_reference="K-2",
        exposure_setting="WORKPLACE", proximity_meters=1.5, cumulative_exposure_minutes=10,
    )
    case = validate_success(api.get_case(cr["id"], make_investigator_headers(j)))
    assert case["contact_count"] == 2, case["contact_count"]


# ===========================================================================
# Queue B — consistency_model section
# ===========================================================================
def test_immediate_contact_count_visible_in_elicit_response(api):
    """PRD §2.7: "`Case.contact_count` tracks the number of non-`VOIDED` contacts whose
    `source_case_id` equals that case's `id`. It rises by one when a contact is elicited".
    PRD §3.6: "Eliciting a contact increments the source case's `contact_count` by one and
    recomputes that case's completeness score."

    Design: Corner/consistency_model/immediate_contact_count_visible_in_elicit_response
    """
    program, jurisdiction, _, ci = fx.setup_interviewed_case(case_overrides={"patient_reference": "PT-I"})
    j = jurisdiction["id"]
    fx.elicit_contact(program["id"], ci["id"], j, contact_reference="K-IMM")
    case = validate_success(api.get_case(ci["id"], make_investigator_headers(j)))
    assert case["contact_count"] == 1, case["contact_count"]
