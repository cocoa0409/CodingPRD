"""CRUD, request-body validation, error-catalogue, listing, ledger, and RBAC tests
covering the breadth (corner) instances not exercised by the workflow files.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    build_user_headers,
    fixtures,
    factories,
    make_patient_headers,
    ApiErrorId,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
AUD = TEST_USERS["audiologist_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ==========================================================================
# Entity CRUD / required fields / type constraints / not found
# ==========================================================================

def test_create_patient_returns_201_with_system_fields(api):
    """PRD §3.1: "A new patient begins life with a status of ACTIVE"
    PRD §2.4: "The version field is an integer that starts at 1 and increments by
    exactly 1 on every mutation"

    Design: Corner/entities/create_patient_returns_201_with_system_fields
    """
    resp = api.create_patient(
        factories.create_patient_payload(full_name="New Patient", date_of_birth="1980-01-01"),
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_create_patient_missing_required_field_rejected(api):
    """PRD §2.3: "A body that is missing a required field, carries a value of the wrong
    type, or violates such an enum or range constraint is rejected with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_patient_missing_required_field_rejected
    """
    resp = api.create_patient({"date_of_birth": "1980-01-01"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_patient_nonexistent_returns_not_found(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with ERR_NOT_FOUND (HTTP 404), before any deeper
    validation runs."

    Design: Corner/entities/get_patient_nonexistent_returns_not_found
    """
    resp = api.get_patient(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_ear_count_out_of_domain_rejected(api):
    """PRD §2.3: "every write endpoint validates the shape of its request body against
    the type, enum, and range constraints declared for each field — for example
    ear_count being 1 or 2"

    Design: Corner/entities/ear_count_out_of_domain_rejected
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1960-01-01")
    model = fixtures.create_device_model(
        list_price_cents=200_000, min_severity="MILD", restock_fee_cents=10_000,
        firmware_version="1.0.0", warranty_months=24)
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=45)
    resp = api.create_order(
        factories.create_order_payload(
            patient["id"], evaluation["id"], model["id"], ear_count=3),
        AUD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_coinsurance_pct_out_of_range_rejected(api):
    """PRD §2.3: "coinsurance_pct being at least 0 and strictly less than 1. A body
    that is missing a required field, carries a value of the wrong type, or violates
    such an enum or range constraint is rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/coinsurance_pct_out_of_range_rejected
    """
    patient = fixtures.create_patient(date_of_birth="1960-01-01")
    resp = api.create_allowance_benefit(
        factories.create_allowance_benefit_payload(
            patient["id"], plan_name="Bad", total_allowance_cents=100_000,
            per_device_cap_cents=50_000, coinsurance_pct=1.5, period_end="2026-12-31"),
        CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_ledger_records_purchase_entry(api):
    """PRD §3.4: "The system appends an ORDER_PURCHASE ledger entry whose amount_cents
    is the positive gross_price_cents."
    PRD §2.4: "The LedgerEntry is an append-only record and carries only id and
    created_at; it has neither an updated_at nor a version field"

    Design: Corner/entities/ledger_immutable_no_version_field
    """
    ctx = fixtures.setup_order_purchased(
        ptag=45, model_overrides={"list_price_cents": 100_000, "min_severity": "MILD",
                                  "restock_fee_cents": 5_000, "warranty_months": 24})
    entries, _ = validate_paginated(api.list_patient_ledger(ctx["patient"]["id"], CLERK))
    purchase_entries = [e for e in entries if e["source_kind"] == "ORDER_PURCHASE"]
    assert len(purchase_entries) == 1
    entry = purchase_entries[0]
    assert entry["amount_cents"] == 100_000
    assert "version" not in entry
    assert "updated_at" not in entry


# ==========================================================================
# Validation -> error catalogue
# ==========================================================================

def test_duplicate_model_code_rejected(api):
    """PRD §3.1: "A model's model_code must be globally unique among all models that
    are not discontinued; creating a model whose model_code collides with an existing
    non-discontinued model is rejected with ERR_DUPLICATE_MODEL_CODE (HTTP 409)."

    Design: Corner/validations/duplicate_model_code_rejected
    """
    validate_success(api.create_device_model(
        factories.create_device_model_payload(
            model_code="DV-DUP-1", name="First", list_price_cents=100_000,
            restock_fee_cents=5_000, min_severity="MILD", firmware_version="1.0.0",
            warranty_months=24), ADMIN), expected_status=201)
    resp = api.create_device_model(
        factories.create_device_model_payload(
            model_code="DV-DUP-1", name="Second", list_price_cents=120_000,
            restock_fee_cents=6_000, min_severity="MODERATE", firmware_version="2.0.0",
            warranty_months=12), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MODEL_CODE.value)


def test_device_not_indicated_when_min_severity_exceeds_loss(api):
    """PRD §3.3: "A model whose min_severity is more severe than the patient's measured
    loss is rejected with ERR_DEVICE_NOT_INDICATED (HTTP 422)."

    Design: Corner/validations/device_not_indicated_when_min_severity_exceeds_loss
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1960-01-01")
    model = fixtures.create_device_model(
        list_price_cents=400_000, min_severity="SEVERE", restock_fee_cents=20_000,
        firmware_version="1.0.0", warranty_months=24)
    # ptag 35 -> MILD candidate, but SEVERE model is not indicated for MILD loss.
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=35)
    order = fixtures.create_draft_order(patient["id"], evaluation["id"], model["id"], ear_count=1)
    resp = api.start_trial(order["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_INDICATED.value)


def test_evaluation_patient_mismatch_on_start_trial(api):
    """PRD §3.3: "The referenced evaluation must belong to the same patient as the
    order — when the evaluation's patient_id does not equal the order's patient_id,
    the request is rejected with ERR_EVALUATION_PATIENT_MISMATCH (HTTP 422)."

    Design: Corner/validations/evaluation_patient_mismatch_on_start_trial
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    pat_a = fixtures.create_patient(date_of_birth="1960-01-01")
    pat_b = fixtures.create_patient(date_of_birth="1961-01-01")
    model = fixtures.create_device_model(
        list_price_cents=200_000, min_severity="MILD", restock_fee_cents=10_000,
        firmware_version="1.0.0", warranty_months=24)
    eval_a = fixtures.create_finalized_evaluation(pat_a["id"], pure_tone_avg_db=50)
    # Order owned by B but references A's evaluation.
    order = fixtures.create_draft_order(pat_b["id"], eval_a["id"], model["id"], ear_count=1)
    resp = api.start_trial(order["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_EVALUATION_PATIENT_MISMATCH.value)


def test_outside_warranty_window_on_approve(api):
    """PRD §3.8: "Approval — whether from SUBMITTED → APPROVED or from APPEALED →
    APPROVED — requires the underlying order to still be WARRANTY_ACTIVE and requires
    the incident to fall within the warranty window: the clock date must be on or
    before the order's purchase date plus the device model's warranty_months months. An
    approval for an incident beyond that window is rejected with
    ERR_OUTSIDE_WARRANTY_WINDOW (HTTP 422)."

    Design: Corner/validations/outside_warranty_window_on_approve
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=50, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 10_000, "warranty_months": 12})
    # purchase_date 2026-03-01; warranty 12 months -> window ends 2027-03-01.
    fixtures.set_clock("2028-02-01T00:00:00Z")
    claim = validate_success(api.create_warranty_claim(
        ctx["order"]["id"], factories.create_warranty_claim_payload(
            claim_type="DEFECT", incident_date="2028-01-01", assessed_value_cents=50_000), CLERK), 201)
    resp = api.approve_warranty_claim(claim["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_WARRANTY_WINDOW.value)


def test_firmware_mismatch_on_recall_reprogram(api):
    """PRD §3.7: "When the reason is RECALL_REPROGRAM, the firmware that is flashed
    must match the recall's prescribed target: the session's applied_firmware_version
    must equal the referenced recall notice's target_firmware_version. A mismatch is
    rejected with ERR_FIRMWARE_MISMATCH (HTTP 422)."

    Design: Corner/validations/firmware_mismatch_on_recall_reprogram
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=50, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 10_000, "firmware_version": "1.0.0",
                                  "warranty_months": 24})
    recall = validate_success(api.create_recall(
        factories.create_recall_payload(
            ctx["model"]["id"], affected_firmware_version="1.0.0",
            target_firmware_version="1.0.1", severity_level="MANDATORY"), ADMIN), 201)
    validate_success(api.issue_recall(recall["id"], recall["version"], ADMIN))
    resp = api.create_adjustment(
        ctx["order"]["id"], factories.create_adjustment_payload(
            reason="RECALL_REPROGRAM", applied_firmware_version="9.9.9",
            recall_notice_id=recall["id"]), AUD)
    validate_error(resp, ApiErrorId.ERR_FIRMWARE_MISMATCH.value)


def test_benefit_inactive_purchase_rejected(api):
    """PRD §3.4: "the pool's status must be ACTIVE — a pool that is EXHAUSTED or
    EXPIRED is rejected with ERR_BENEFIT_INACTIVE (HTTP 422)"

    Design: Corner/validations/benefit_inactive_purchase_rejected
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1960-01-01")
    model = fixtures.create_device_model(
        list_price_cents=400_000, min_severity="MILD", restock_fee_cents=20_000,
        firmware_version="1.0.0", warranty_months=24)
    benefit = fixtures.create_allowance_benefit(
        patient["id"], plan_name="Exh", total_allowance_cents=400_000,
        per_device_cap_cents=400_000, coinsurance_pct=0, period_end="2026-12-31")
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=50)
    # First order exhausts the benefit.
    order1 = fixtures.create_draft_order(
        patient["id"], evaluation["id"], model["id"], ear_count=1,
        allowance_benefit_id=benefit["id"])
    validate_success(api.start_trial(order1["id"], AUD))
    validate_success(api.purchase_order(order1["id"], CLERK))
    # Second order references the now-EXHAUSTED benefit.
    order2 = fixtures.create_draft_order(
        patient["id"], evaluation["id"], model["id"], ear_count=1,
        allowance_benefit_id=benefit["id"])
    validate_success(api.start_trial(order2["id"], AUD))
    resp = api.purchase_order(order2["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_BENEFIT_INACTIVE.value)


def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "If limit falls outside the inclusive range of 1 through 100, or if
    offset is negative, the request is rejected with ERR_VALIDATION_LIMIT (HTTP 422)."

    Design: Corner/validations/pagination_limit_over_max_rejected
    """
    resp = api.list_patients(ADMIN, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value)


def test_trial_not_closed_activate_warranty_early(api):
    """PRD §3.6: "if the current clock instant is at or before trial_deadline_at, the
    activation is rejected with ERR_TRIAL_NOT_CLOSED (HTTP 422), because the sale
    cannot be made final while a no-penalty return is still possible."

    Design: Corner/errors/trial_not_closed_activate_warranty_early
    """
    ctx = fixtures.setup_order_purchased(
        ptag=45, model_overrides={"list_price_cents": 100_000, "min_severity": "MILD",
                                  "restock_fee_cents": 5_000, "warranty_months": 24})
    # Clock still inside trial window (CLOCK_BASE, deadline +30 days).
    resp = api.activate_warranty(ctx["order"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_TRIAL_NOT_CLOSED.value)


def test_return_window_closed_late_return(api):
    """PRD §3.5: "For a return out of PURCHASED, the trial window must still be open:
    if the current clock instant is later than trial_deadline_at, the late return is
    rejected with ERR_RETURN_WINDOW_CLOSED (HTTP 422), because once the trial window
    closes the sale is final."

    Design: Corner/errors/return_window_closed_late_return
    """
    ctx = fixtures.setup_order_purchased(
        ptag=45, model_overrides={"list_price_cents": 100_000, "min_severity": "MILD",
                                  "restock_fee_cents": 5_000, "warranty_months": 24})
    fixtures.set_clock("2026-05-01T00:00:00Z")  # past the 30-day window.
    resp = api.return_order(ctx["order"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED.value)


def test_benefit_expired_purchase_rejected(api):
    """PRD §3.4: "and the current clock date must be on or before the pool's
    period_end; a benefit applied after its period has closed is rejected with
    ERR_BENEFIT_EXPIRED (HTTP 422)."

    Design: Corner/errors/benefit_expired_purchase_rejected
    """
    fixtures.set_clock("2026-05-25T00:00:00Z")
    patient = fixtures.create_patient(date_of_birth="1960-01-01")
    model = fixtures.create_device_model(
        list_price_cents=300_000, min_severity="MILD", restock_fee_cents=15_000,
        firmware_version="1.0.0", warranty_months=24)
    benefit = fixtures.create_allowance_benefit(
        patient["id"], plan_name="Expiring", total_allowance_cents=500_000,
        per_device_cap_cents=250_000, coinsurance_pct=0.20, period_end="2026-05-31")
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=50)
    order = fixtures.create_draft_order(
        patient["id"], evaluation["id"], model["id"], ear_count=1,
        allowance_benefit_id=benefit["id"])
    validate_success(api.start_trial(order["id"], AUD))
    fixtures.set_clock("2026-06-01T00:00:00Z")  # still in trial window, benefit lapsed.
    resp = api.purchase_order(order["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_BENEFIT_EXPIRED.value)


# ==========================================================================
# Listing / endpoints
# ==========================================================================

def test_list_patients_pagination_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope, where total_count is the number of
    items matching the query before pagination and has_more indicates whether further
    items remain beyond the current page."

    Design: Corner/endpoints/list_patients_pagination_envelope
    """
    fixtures.create_patient(full_name="List A", date_of_birth="1960-01-01")
    fixtures.create_patient(full_name="List B", date_of_birth="1961-01-01")
    data, meta = validate_paginated(api.list_patients(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# NOTE: Corner/endpoints/list_orders_filtered_by_device_model is SKIPPED.
# The PRD endpoint table labels GET /clinic/orders only as "List/filter fitting
# orders" and Section 2.3 covers pagination/ordering but states no per-field filter
# contract. A PRD-only implementer could faithfully ignore the optional
# device_model_id filter and return all orders, so the asserted "returns only orders
# for that model" outcome is not uniquely derivable from PRD prose (Core rule).


# ==========================================================================
# RBAC
# ==========================================================================

def test_audiologist_cannot_purchase(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is not
    permitted to perform, the request is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/audiologist_cannot_purchase
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=45, model_overrides={"list_price_cents": 100_000, "min_severity": "MILD",
                                  "restock_fee_cents": 5_000, "warranty_months": 24})
    resp = api.purchase_order(ctx["order"]["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_patient_cannot_appeal_others_claim(api):
    """PRD §2.1: "A Patient acting on a resource they do not own — appealing a claim on
    someone else's order ... — is rejected with ERR_FORBIDDEN (HTTP 403). This
    ownership check is distinct from, and evaluated after, the role-permission check
    that also yields ERR_FORBIDDEN."

    Design: Corner/rbac/patient_cannot_appeal_others_claim
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=50, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 10_000, "warranty_months": 24})
    # Owner A's order has a DENIED claim; intruder B attempts the appeal.
    pat_b = fixtures.create_patient(full_name="Intruder B", date_of_birth="1961-01-01")
    claim = validate_success(api.create_warranty_claim(
        ctx["order"]["id"], factories.create_warranty_claim_payload(
            claim_type="DEFECT", incident_date="2026-04-10", assessed_value_cents=50_000), CLERK), 201)
    validate_success(api.deny_warranty_claim(claim["id"], CLERK))
    resp = api.appeal_warranty_claim(claim["id"], make_patient_headers(pat_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a known
    role, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    bad_headers = build_user_headers("someone", "NotARealRole")
    resp = api.list_patients(bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
