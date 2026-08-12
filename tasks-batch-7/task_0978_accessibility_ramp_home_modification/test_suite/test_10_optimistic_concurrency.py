"""Optimistic concurrency control on the case version (PRD §2.4)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_case, create_assessed_case, add_funding_source, case_version, get_case,
    create_assessment_payload, complete_assessment_payload,
    create_quote_payload, approve_funding_payload,
    create_draft_invoice, add_invoice_line, set_clock,
)

IC = TEST_USERS["intake_coordinator_headers"]
AS = TEST_USERS["assessor_headers"]
PM = TEST_USERS["project_manager_headers"]
FC = TEST_USERS["funding_coordinator_headers"]
BC = TEST_USERS["billing_coordinator_headers"]


def _complete_second_assessment(api, case_id, mobility_score, hazard_count,
                                assessor_id, recommended,
                                assessment_type="REASSESSMENT"):
    """Run a further assessment to completion; per PRD §3.1 'Completing an
    assessment also re-evaluates the parent case', mutating it."""
    asmt = validate_success(api.create_assessment(
        case_id,
        create_assessment_payload(assessor_id=assessor_id,
                                  assessment_type=assessment_type,
                                  mobility_score=mobility_score,
                                  hazard_count=hazard_count),
        IC), 201)
    validate_success(api.start_assessment(case_id, asmt["id"], AS), 200)
    validate_success(api.complete_assessment(
        case_id, asmt["id"],
        complete_assessment_payload(mobility_score=mobility_score,
                                    hazard_count=hazard_count,
                                    recommended_modifications=recommended),
        AS), 200)


def test_occ_quote_create_stale_version_returns_412(api):
    """PRD §2.4: "Creating a quote (`POST /cases/{caseId}/quotes`) requires
    `expected_case_version`, carrying the `version` of the case as the client last
    observed it." "On each of these three endpoints, if the supplied
    `expected_case_version` does not equal the case's current `version` — meaning
    another writer has advanced the case since the client last read it, for
    example by completing an assessment, changing funding, or sending another
    invoice — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no
    change is applied."

    Design: Corner/cross_cutting_complexity_layers/occ_quote_create_stale_version_returns_412
    """
    set_clock()
    case, _ = create_assessed_case(mobility_score=50, hazard_count=1,
                                   client_name="Occ One", client_address="71 Occ Rd",
                                   client_phone="555-0801")
    stale_v = get_case(case["id"])["version"]
    # Another writer advances the case (different scores -> recomputed values).
    _complete_second_assessment(api, case["id"], mobility_score=55, hazard_count=0,
                                assessor_id="ot-61", recommended=["RAILS"])
    res = api.create_quote(case["id"], create_quote_payload(stale_v), PM)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    quotes, _ = validate_paginated(api.list_quotes(case["id"], IC))
    assert quotes == [], "rejected write must apply no change"


def test_occ_funding_approve_stale_version_returns_412(api):
    """PRD §2.4: "Approving a funding source
    (`POST /cases/{caseId}/funding-sources/{sourceId}/approve`) requires
    `expected_case_version` on the same terms." "On each of these three
    endpoints, if the supplied `expected_case_version` does not equal the case's
    current `version` — meaning another writer has advanced the case since the
    client last read it, for example by completing an assessment, changing
    funding, or sending another invoice — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and no change is applied."

    Design: Corner/cross_cutting_complexity_layers/occ_funding_approve_stale_version_returns_412
    """
    set_clock()
    case, _ = create_assessed_case(mobility_score=50, hazard_count=1,
                                   client_name="Occ Two", client_address="72 Occ Rd",
                                   client_phone="555-0802")
    src = add_funding_source(case["id"], 9000, source_type="VA_BENEFIT",
                             program_name="VA3")
    stale_v = get_case(case["id"])["version"]
    _complete_second_assessment(api, case["id"], mobility_score=60, hazard_count=0,
                                assessor_id="ot-63", recommended=["RAILS"])
    res = api.approve_funding_source(case["id"], src["id"],
                                     approve_funding_payload(9000, stale_v), FC)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert after["status"] == "PENDING", "rejected approval must apply no change"


def test_occ_invoice_send_stale_version_returns_412(api):
    """PRD §2.4: "Sending an invoice
    (`POST /cases/{caseId}/invoices/{invoiceId}/send`) requires
    `expected_case_version` on the same terms." "On each of these three
    endpoints, if the supplied `expected_case_version` does not equal the case's
    current `version` — meaning another writer has advanced the case since the
    client last read it, for example by completing an assessment, changing
    funding, or sending another invoice — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and no change is applied."

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_send_stale_version_returns_412
    """
    set_clock()
    case = create_case(client_name="Occ Three", client_address="73 Occ Rd",
                       client_phone="555-0803")
    inv = create_draft_invoice(case["id"])
    add_invoice_line(case["id"], inv["id"], unit_price_cents=2000)
    stale_v = get_case(case["id"])["version"]
    _complete_second_assessment(api, case["id"], mobility_score=50, hazard_count=1,
                                assessor_id="ot-64", recommended=["RAMP"],
                                assessment_type="INITIAL")
    res = api.send_invoice(case["id"], inv["id"],
                           {"expected_case_version": stale_v}, BC)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api.get_invoice(case["id"], inv["id"], IC), 200)
    assert after["status"] == "DRAFT"
    assert get_case(case["id"])["total_billed_cents"] == 0


def test_case_version_increments_on_each_mutation(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increments by one on every mutation."
    PRD §3.1: "The assessment is created in `SCHEDULED` status, and creating it
    moves the case from `INTAKE` to `ASSESSMENT_SCHEDULED`."

    Design: Corner/cross_cutting_complexity_layers/case_version_increments_on_each_mutation
    """
    set_clock()
    case = validate_success(api.create_case(
        {"client_name": "Ver Bump", "client_address": "74 Version Rd",
         "client_phone": "555-0804"}, IC), 201)
    assert case["version"] == 1
    validate_success(api.create_assessment(
        case["id"], create_assessment_payload(assessor_id="ot-65"), IC), 201)
    after = get_case(case["id"])
    assert after["version"] == 2, "exactly +1 for the intake -> scheduled mutation"
    assert after["status"] == "ASSESSMENT_SCHEDULED"
