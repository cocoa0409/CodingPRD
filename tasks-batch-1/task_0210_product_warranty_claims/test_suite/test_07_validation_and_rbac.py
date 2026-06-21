"""Validation rules, validation-priority conflicts, and role-based access
control (PRD §2.1, §2.10, §3.5–§3.7)."""
import pytest

from test_helpers import (
    create_product_payload,
    make_headers,
    make_owner_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as F


# ─── Difficulty: priority_pair_validation_conflict ───────────────────────────
def test_state_beats_safety_invalid_state_over_defect_not_covered(api):
    """PRD §3.7: "Adjudication is legal only when the claim is in `RMA_ISSUED`."
    PRD §2.10: "For transition endpoints, the target resource's state is checked
    fourth, yielding `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a
    state from which the requested transition is legal. ... Ownership scoping is
    sixth ... The remaining business rules — defect coverage, warranty window,
    refund eligibility, tier matching, fiscal coverage limits, and so on — follow".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_invalid_state_over_defect_not_covered
    """
    # Claim left in INTAKE (state violation, prio 4) with WEAR_AND_TEAR defect
    # (safety violation, prio 7). State is the lower priority number -> wins.
    s = F.setup_active_registration(base_cap_cents=40000, base_refund_eligible=True)
    claim = F.file_claim(
        s["registration"]["id"], s["owner"]["id"],
        defect_category="WEAR_AND_TEAR", reported_date="2024-02-15T00:00:00Z",
    )
    resp = api.adjudicate_claim(
        claim["id"], {"decision": "approve", "resolution_type": "REPAIR", "repair_cost_cents": 5000}, F.ADMIN
    )
    validate_error(resp, "ERR_INVALID_STATE")


def test_state_beats_safety_claim_remains_in_intake_after_rejection(api):
    """PRD §3.7: "Adjudication is legal only when the claim is in `RMA_ISSUED`."
    PRD §2.10: "For transition endpoints, the target resource's state is checked
    fourth, yielding `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a
    state from which the requested transition is legal."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_invalid_state_over_defect_not_covered
    """
    # Same conflicting scenario; a rejected adjudication leaves the claim in INTAKE.
    s = F.setup_active_registration(base_cap_cents=40000, base_refund_eligible=True)
    claim = F.file_claim(
        s["registration"]["id"], s["owner"]["id"],
        defect_category="WEAR_AND_TEAR", reported_date="2024-02-15T00:00:00Z",
    )
    resp = api.adjudicate_claim(
        claim["id"], {"decision": "approve", "resolution_type": "REPAIR", "repair_cost_cents": 5000}, F.ADMIN
    )
    validate_error(resp, "ERR_INVALID_STATE")
    assert validate_success(api.get_claim(claim["id"], F.ADMIN))["status"] == "INTAKE"


def test_refund_constraint_beats_fiscal_refund_not_eligible_over_coverage_exhausted(api):
    """PRD §3.7: "If the requested resolution is `REFUND`, the active coverage
    tier's `refund_eligible` flag must be true, or the approval is rejected with
    `ERR_REFUND_NOT_ELIGIBLE` (HTTP 422)."
    PRD §3.7: "These approval-time checks are evaluated in the priority order set
    out in §2.10 — existence and state first, then defect coverage, then refund
    eligibility, then the fiscal coverage limit".

    Design: Difficulty/priority_pair_validation_conflict/refund_constraint_beats_fiscal_refund_not_eligible_over_coverage_exhausted
    """
    # BASE tier refund_eligible=false, cap 30000. First REPAIR claim drains coverage
    # to 0, then a second REFUND attempt hits both refund-ineligibility (prio 9) and
    # coverage-exhaustion (prio 12). Refund eligibility wins.
    s = F.setup_active_registration(
        base_cap_cents=30000, base_refund_eligible=False,
        product_overrides={"base_warranty_months": 36, "serviceable_lifespan_months": 48},
    )
    claim1 = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-03-01T00:00:00Z")
    F.issue_rma(claim1["id"])
    F.adjudicate_approve(claim1["id"], "REPAIR", repair_cost_cents=30000)
    claim2 = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-06-01T00:00:00Z")
    F.issue_rma(claim2["id"])
    resp = api.adjudicate_claim(claim2["id"], {"decision": "approve", "resolution_type": "REFUND"}, F.ADMIN)
    validate_error(resp, "ERR_REFUND_NOT_ELIGIBLE")


def test_refund_constraint_beats_fiscal_claim_remains_in_rma_issued(api):
    """PRD §3.7: "If the requested resolution is `REFUND`, the active coverage
    tier's `refund_eligible` flag must be true, or the approval is rejected with
    `ERR_REFUND_NOT_ELIGIBLE` (HTTP 422)."
    PRD §3.7: "the system writes a `DEBIT` ledger entry whose `reason` matches the
    resolution ... whose `amount_cents` is the assessed value" — a rejected
    approval writes no such entry.

    Design: Difficulty/priority_pair_validation_conflict/refund_constraint_beats_fiscal_refund_not_eligible_over_coverage_exhausted
    """
    s = F.setup_active_registration(
        base_cap_cents=30000, base_refund_eligible=False,
        product_overrides={"base_warranty_months": 36, "serviceable_lifespan_months": 48},
    )
    claim1 = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-03-01T00:00:00Z")
    F.issue_rma(claim1["id"])
    F.adjudicate_approve(claim1["id"], "REPAIR", repair_cost_cents=30000)
    claim2 = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-06-01T00:00:00Z")
    F.issue_rma(claim2["id"])
    resp = api.adjudicate_claim(claim2["id"], {"decision": "approve", "resolution_type": "REFUND"}, F.ADMIN)
    validate_error(resp, "ERR_REFUND_NOT_ELIGIBLE")
    # The rejected approval leaves the second claim still under RMA, no new debit.
    assert validate_success(api.get_claim(claim2["id"], F.ADMIN))["status"] == "RMA_ISSUED"


# ─── Corner: validations (isolated single-failure scenarios) ─────────────────
def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not
    one of these three known roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_headers_returns_unauthenticated
    """
    resp = api.create_product(create_product_payload(model_number="PRD-NOAUTH"), headers={})
    validate_error(resp, "ERR_UNAUTHENTICATED")


def test_duplicate_serial_per_product_returns_duplicate_serial(api):
    """PRD §3.2: "A serial number must be non-empty and unique for its product; an
    attempt to register a serial already on file for the same product is rejected
    with `ERR_DUPLICATE_SERIAL` (HTTP 409)."

    Design: Corner/validations/duplicate_serial_per_product_returns_duplicate_serial
    """
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    F.create_registration(product["id"], owner["id"], serial_number="SN-DUP", purchase_date="2024-01-15T00:00:00Z")
    resp = api.create_registration(
        {
            "product_id": product["id"], "serial_number": "SN-DUP", "owner_user_id": owner["id"],
            "purchase_date": "2024-02-15T00:00:00Z", "purchase_price_cents": 50000,
        },
        make_owner_headers(owner["id"]),
    )
    validate_error(resp, "ERR_DUPLICATE_SERIAL")


def test_adjudicate_non_manufacturing_defect_returns_defect_not_covered(api):
    """PRD §3.7: "An attempt to approve a claim whose defect is anything other than
    `MANUFACTURING` is rejected with `ERR_DEFECT_NOT_COVERED` (HTTP 422)."

    Design: Corner/validations/adjudicate_non_manufacturing_defect_returns_defect_not_covered
    """
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={
            "base_cap_cents": 40000, "base_refund_eligible": True,
            "product_overrides": {"base_warranty_months": 24},
        },
        defect_category="ACCIDENTAL",
    )
    resp = api.adjudicate_claim(
        s["claim"]["id"], {"decision": "approve", "resolution_type": "REPAIR", "repair_cost_cents": 5000}, F.ADMIN
    )
    validate_error(resp, "ERR_DEFECT_NOT_COVERED")


def test_issue_rma_after_expiry_returns_warranty_expired(api):
    """PRD §3.6: "the claim's reported date is on or before the registration's
    `warranty_end_date`; a reported date past the warranty end (or a registration
    no longer eligible) is rejected with `ERR_WARRANTY_EXPIRED`."

    Design: Corner/validations/issue_rma_after_warranty_expired_returns_warranty_expired
    """
    s = F.setup_active_registration(base_cap_cents=40000, product_overrides={"base_warranty_months": 12})
    set_clock("2025-01-10T00:00:00Z")
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2025-01-10T00:00:00Z")
    F.advance_clock("2025-02-01T00:00:00Z")  # sweeps registration to EXPIRED.
    resp = api.issue_rma(claim["id"], F.CP)
    validate_error(resp, "ERR_WARRANTY_EXPIRED")


def test_adjudicate_refund_ineligible_tier_returns_refund_not_eligible(api):
    """PRD §3.7: "If the requested resolution is `REFUND`, the active coverage
    tier's `refund_eligible` flag must be true, or the approval is rejected with
    `ERR_REFUND_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/adjudicate_refund_ineligible_tier_returns_refund_not_eligible
    """
    # Ample coverage so only the refund-eligibility constraint can fire.
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={
            "base_cap_cents": 40000, "base_refund_eligible": False,
            "product_overrides": {"base_warranty_months": 24},
        },
        defect_category="MANUFACTURING",
    )
    resp = api.adjudicate_claim(s["claim"]["id"], {"decision": "approve", "resolution_type": "REFUND"}, F.ADMIN)
    validate_error(resp, "ERR_REFUND_NOT_ELIGIBLE")


def test_adjudicate_coverage_exhausted_returns_coverage_exhausted(api):
    """PRD §3.7: "The assessed value must not exceed the registration's remaining
    coverage, and if remaining coverage is already zero the claim cannot be
    approved — either situation is rejected with `ERR_COVERAGE_EXHAUSTED`
    (HTTP 422)."

    Design: Corner/validations/adjudicate_coverage_exhausted_returns_coverage_exhausted
    """
    # Refund-eligible BASE tier so the refund-eligibility check passes; a prior
    # REPAIR debit drains remaining to 0 so only the fiscal rule can fire.
    s = F.setup_active_registration(
        base_cap_cents=30000, base_refund_eligible=True,
        product_overrides={"base_warranty_months": 36, "serviceable_lifespan_months": 48},
    )
    claim1 = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-03-01T00:00:00Z")
    F.issue_rma(claim1["id"])
    F.adjudicate_approve(claim1["id"], "REPAIR", repair_cost_cents=30000)
    claim2 = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-06-01T00:00:00Z")
    F.issue_rma(claim2["id"])
    resp = api.adjudicate_claim(claim2["id"], {"decision": "approve", "resolution_type": "REFUND"}, F.ADMIN)
    validate_error(resp, "ERR_COVERAGE_EXHAUSTED")


# ─── Corner: cooldown (difficulty resource_temporal #2) ──────────────────────
def test_claim_cooldown_buffer_gap_rejected(api):
    """PRD §3.5: "a new claim's reported date must be strictly more than 30 days
    after the reported date of the most recent non-`CLOSED` claim on the same
    registration. The cooldown is a closed buffer — a reported date exactly 30
    days after the prior claim is still too soon and is rejected with
    `ERR_CLAIM_COOLDOWN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/claim_cooldown_buffer_gap_between_claims
    """
    # First claim reported 2024-02-01 (INTAKE); second at 2024-02-20 (19 days later).
    s = F.setup_active_registration(base_cap_cents=40000, product_overrides={"base_warranty_months": 24})
    F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-02-01T00:00:00Z")
    resp = api.create_claim(
        {"registration_id": s["registration"]["id"], "defect_category": "MANUFACTURING", "reported_date": "2024-02-20T00:00:00Z"},
        make_owner_headers(s["owner"]["id"]),
    )
    validate_error(resp, "ERR_CLAIM_COOLDOWN")


def test_claim_exactly_30_days_after_prior_still_rejected(api):
    """PRD §3.5: "The cooldown is a closed buffer — a reported date exactly 30 days
    after the prior claim is still too soon and is rejected with
    `ERR_CLAIM_COOLDOWN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/claim_cooldown_buffer_gap_between_claims
    """
    # First claim 2024-02-01; second exactly 30 days later (2024-03-02) -> rejected.
    s = F.setup_active_registration(base_cap_cents=40000, product_overrides={"base_warranty_months": 24})
    F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-02-01T00:00:00Z")
    resp = api.create_claim(
        {"registration_id": s["registration"]["id"], "defect_category": "MANUFACTURING", "reported_date": "2024-03-02T00:00:00Z"},
        make_owner_headers(s["owner"]["id"]),
    )
    validate_error(resp, "ERR_CLAIM_COOLDOWN")


# ─── Corner: RBAC ────────────────────────────────────────────────────────────
def test_owner_cannot_adjudicate_claim(api):
    """PRD §4: the adjudicate endpoint is authorized for "WarrantyAdmin" only.
    PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/owner_cannot_adjudicate_claim
    """
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={"base_cap_cents": 40000, "product_overrides": {"base_warranty_months": 24}},
    )
    resp = api.adjudicate_claim(
        s["claim"]["id"], {"decision": "approve", "resolution_type": "REPAIR", "repair_cost_cents": 5000},
        make_owner_headers(s["owner"]["id"]),
    )
    validate_error(resp, "ERR_FORBIDDEN")


def test_claims_processor_cannot_create_product(api):
    """PRD §4: the `POST /products` endpoint is authorized for "WarrantyAdmin" only.
    PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/claims_processor_cannot_create_product
    """
    resp = api.create_product(
        create_product_payload(model_number="PRD-R2"), F.make_claims_processor_headers("cp-1")
    )
    validate_error(resp, "ERR_FORBIDDEN")


def test_warranty_admin_cannot_issue_rma(api):
    """PRD §4: the `POST /claims/{id}/issue-rma` endpoint is authorized for
    "ClaimsProcessor" only.
    PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/claims_processor_cannot_issue_rma_is_false_processor_can_but_admin_cannot
    """
    s = F.setup_active_registration(base_cap_cents=40000, product_overrides={"base_warranty_months": 24})
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-02-15T00:00:00Z")
    resp = api.issue_rma(claim["id"], F.ADMIN)
    validate_error(resp, "ERR_FORBIDDEN")


def test_owner_cannot_file_claim_on_others_registration(api):
    """PRD §3.5: "A warranty claim is filed by an `Owner` against one of their own
    registrations ... An owner who is not the registration's owner is rejected
    with `ERR_NOT_OWNER`."

    Design: Corner/rbac/owner_cannot_file_claim_on_others_registration
    """
    s = F.setup_active_registration(base_cap_cents=40000, product_overrides={"base_warranty_months": 24})
    other = F.create_owner()
    resp = api.create_claim(
        {"registration_id": s["registration"]["id"], "defect_category": "MANUFACTURING", "reported_date": "2024-02-15T00:00:00Z"},
        make_owner_headers(other["id"]),
    )
    validate_error(resp, "ERR_NOT_OWNER")


def test_owner_shared_operation_register_succeeds(api):
    """PRD §3.2: "A registration may be created by either an `Owner` or a
    `WarrantyAdmin`."
    PRD §4: "POST `/registrations` ... Owner, WarrantyAdmin".

    Design: Corner/rbac/owner_shared_operation_register_succeeds
    """
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    resp = api.create_registration(
        {
            "product_id": product["id"], "serial_number": "SN-R5", "owner_user_id": owner["id"],
            "purchase_date": "2024-01-15T00:00:00Z", "purchase_price_cents": 50000,
        },
        make_owner_headers(owner["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["owner_user_id"] == owner["id"]
