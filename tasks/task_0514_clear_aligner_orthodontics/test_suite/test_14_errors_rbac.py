"""Error-catalogue and RBAC corner cases (PRD §2.1, §2.10, §5)."""
from test_helpers import (
    validate_success, validate_error,
    create_clinician, create_patient,
    setup_submitted_plan, setup_financing_active,
    create_plan_payload, create_case_payload,
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    make_clinician_headers, make_patient_headers,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


def test_plan_create_with_bad_case_fk_returns_fk_not_found(api):
    """PRD §2.10: "then existence of body foreign keys (`ERR_FK_NOT_FOUND`) ...
    The body foreign keys that participate in the existence check at this stage
    include `case_id`, `financing_plan_id`, `step_id`, `triggering_checkin_id`,
    `patient_id`, and `author_clinician_id`."

    POST /plans with a non-existent case_id returns ERR_FK_NOT_FOUND (404).

    Design: Corner/errors/error_fk_not_found_on_plan_create_bad_case
    """
    clinician = create_clinician(license_state_codes=["CA"])
    res = api.create_plan(
        create_plan_payload(NON_EXISTENT_UUID, clinician["id"],
                            proposed_step_count=10, weeks_per_step=2),
        make_clinician_headers(clinician["id"]),
    )
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


def test_patient_cannot_approve_plan(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted
    to invoke the requested endpoint, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 (endpoint): "Approve a submitted plan, pricing the case and generating
    aligner steps. | Clinician".

    A Patient calling the Clinician-only POST /plans/{id}/approve returns
    ERR_UNAUTHORIZED (403).

    Design: Corner/rbac/patient_cannot_approve_plan
    """
    ctx = setup_submitted_plan(proposed_step_count=10, list_price_cents=300000)
    res = api.approve_plan(ctx["plan"]["id"], ctx["pat_headers"])
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers identifying the caller:
    `X-User-ID` and `X-User-Role`. If either header is absent, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    A POST /cases with no auth headers returns ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    patient = create_patient(state_code="CA")
    res = api.create_case(
        create_case_payload(patient["id"], intake_channel="IMPRESSION_KIT",
                            list_price_cents=300000),
        {},
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_manufacturing_cannot_post_installment(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted
    to invoke the requested endpoint, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 (endpoint): "Post a monthly installment payment (in-order). |
    BillingAdmin".

    ManufacturingOps calling the BillingAdmin-only installment post-payment
    endpoint returns ERR_UNAUTHORIZED (403).

    Design: Corner/rbac/manufacturing_cannot_post_installment
    """
    ctx = setup_financing_active(proposed_step_count=10, term_months=12,
                                down_payment_cents=0, apr_bps=0, list_price_cents=300000)
    res = api.post_installment_payment(ctx["financing"]["id"], 1, MFG)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
