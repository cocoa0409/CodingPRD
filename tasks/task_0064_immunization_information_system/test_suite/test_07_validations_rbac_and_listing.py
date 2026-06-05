"""Recording-guardrail violations in isolation, existence-before-state ordering,
RBAC denials, authentication, and list/pagination behavior."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, build_user_headers,
    setup_catalog_and_patient, create_allergy, create_product, create_provider,
    create_lot, create_patient, set_clock, record_dose, run_evaluation,
    issue_certificate, open_report, add_line, make_provider_headers,
    make_clerk_headers, make_registrar_headers, api_client,
    create_product_payload, create_immunization_payload,
)

REG = make_registrar_headers()
CLERK = make_clerk_headers()
C1 = dict(product_code="C1", antigen="C1", doses_in_series=1, min_age_days=0,
          recommended_age_days=0, min_interval_days=0)


# ---- validations section ----
def test_provider_not_authorized_for_product(api):
    """PRD §3.3: "provider authorization: the administering provider's
    authorized_product_codes must contain the product_code of the lot's product,
    or the recording is rejected with ERR_PRODUCT_NOT_AUTHORIZED (HTTP 422)."

    Design: Corner/validations/provider_not_authorized_for_product
    """
    product, provider, lot, patient = setup_catalog_and_patient(
        product_overrides=create_product_payload(**C1),
        provider_overrides={"authorized_product_codes": ["OTHER"]},
        patient_overrides={"date_of_birth": "2024-01-01"})
    resp = api_client.create_immunization(create_immunization_payload(
        patient_id=patient["id"], lot_id=lot["id"],
        provider_id=provider["id"], administered_date="2025-01-01"), REG)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_AUTHORIZED.value)


def test_existence_checked_before_state(api):
    """PRD §2.5: "This existence sweep covers every path-referenced and
    body-referenced resource ... and runs after authentication and authorization
    but before any business rule is evaluated."

    Adjudicating a non-existent report returns ERR_NOT_FOUND, not
    ERR_INVALID_STATE.

    Design: Corner/validations/existence_before_state_left_to_right
    """
    validate_error(
        api_client.adjudicate_provider_report(NON_EXISTENT_UUID, REG),
        ApiErrorId.ERR_NOT_FOUND.value)


def test_contraindication_blocks_record_alone(api):
    """PRD §3.3: "the safety check: the patient must have no CONTRAINDICATED
    allergy record for the product's antigen, or the dose is rejected with
    ERR_CONTRAINDICATED (HTTP 422)."

    Design: Corner/validations/contraindication_blocks_record_alone
    """
    product, provider, lot, patient = setup_catalog_and_patient(
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    create_allergy(patient["id"], "C1", severity="CONTRAINDICATED")
    resp = api_client.create_immunization(create_immunization_payload(
        patient_id=patient["id"], lot_id=lot["id"],
        provider_id=provider["id"], administered_date="2025-01-01"), REG)
    validate_error(resp, ApiErrorId.ERR_CONTRAINDICATED.value)


# ---- errors section ----
def test_suspended_provider_cannot_submit(api):
    """PRD §3.8: "a provider whose status is SUSPENDED attempting to submit is
    rejected with ERR_PROVIDER_SUSPENDED (HTTP 409)".

    Design: Corner/errors/provider_suspended_blocks_submit
    """
    product = create_product(**create_product_payload(**C1))
    provider = create_provider(authorized_product_codes=["C1"],
                               status="SUSPENDED")
    lot = create_lot(product["id"])
    patient = create_patient(date_of_birth="2024-01-01")
    prov_headers = make_provider_headers(provider["id"])
    report = open_report(provider["id"], 1, headers=prov_headers)
    add_line(report["id"], patient["id"], lot["id"], "2025-01-01",
             headers=prov_headers)
    validate_error(
        api_client.submit_provider_report(report["id"], prov_headers),
        ApiErrorId.ERR_PROVIDER_SUSPENDED.value)


# ---- rbac section ----
def test_records_clerk_cannot_issue_certificate(api):
    """PRD §4: certificate issuance (POST /patients/{id}/certificates) is
    authorized only for ImmunizationRegistrar.
    PRD §2.1: "A request whose role is well-formed but not permitted to perform
    the requested operation under the access matrix in Section 4 is rejected with
    ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/records_clerk_cannot_issue_certificate
    """
    set_clock("2026-06-01T00:00:00Z")
    product = create_product(**create_product_payload(**C1))
    provider = create_provider(authorized_product_codes=["C1"])
    lot = create_lot(product["id"])
    patient = create_patient(date_of_birth="2024-01-01")
    record_dose(patient["id"], lot["id"], provider["id"], "2025-01-01")
    ev = run_evaluation(patient["id"], "2026-06-01")
    pat = get_success_data(api_client.get_patient(patient["id"], REG))
    resp = issue_certificate(patient["id"], ev["id"], pat["version"],
                             headers=CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_provider_cannot_adjudicate_report(api):
    """PRD §4: adjudication (POST /provider-reports/{id}/adjudicate) is
    authorized only for ImmunizationRegistrar.
    PRD §2.1: "A request whose role is well-formed but not permitted to perform
    the requested operation under the access matrix in Section 4 is rejected with
    ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/provider_cannot_adjudicate_own_report
    """
    from test_helpers import setup_submitted_report
    _, provider, _lots, _patient, report = setup_submitted_report(
        lines=[{"lot_key": "main", "administered_date": "2025-01-01"}],
        line_count=1,
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    prov_headers = make_provider_headers(provider["id"])
    validate_error(
        api_client.adjudicate_provider_report(report["id"], prov_headers),
        ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that presents an
    X-User-Role value that is not one of these three, is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    validate_error(api_client.list_patients(headers={}),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---- endpoints section ----
def test_list_patients_pagination_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope, where total_count reflects the
    full size of the collection before the limit/offset window is applied and
    has_more indicates whether further items remain beyond the current window."

    Design: Corner/endpoints/list_patients_pagination_envelope
    """
    create_patient(full_name="P1", state_code="CA")
    create_patient(full_name="P2", state_code="NY")
    data, meta = validate_paginated(
        api_client.list_patients(REG, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1, f"expected 1 item in window, got {len(data)}"


def test_filtered_list_lots_by_product(api):
    """PRD §4: "GET /lots | List lots, optionally filtered by product".
    PRD §2.3: "total_count reflects the full size of the collection before the
    limit/offset window is applied".

    Filtering by product_id returns only that product's two lots.

    Design: Corner/endpoints/filtered_list_lots_by_product
    """
    product = create_product(**create_product_payload(**C1))
    create_lot(product["id"], lot_number="L-1")
    create_lot(product["id"], lot_number="L-2")
    data, meta = validate_paginated(
        api_client.list_lots(REG, params={"product_id": product["id"]}))
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
