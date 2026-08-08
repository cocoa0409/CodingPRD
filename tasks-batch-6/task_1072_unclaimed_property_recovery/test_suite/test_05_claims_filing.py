"""Claim filing: the escheated-property precondition, the fee-cap boundary and its
over-cap rejection, the firm-shape rule, and the one-live-claim constraint.

Translates queue A (boundary_precision_check/fee_cap_exact_boundary,
cross_entity_state_dependency/claim_requires_property_escheated) and queue B
(fee exceeds cap, firm required, claim already active).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures, TEST_USERS,
)
from test_helpers.test_users import (
    make_holder_headers, make_owner_headers, make_recovery_agent_headers,
)


def _escheated_ca_property(api, *, amount_cents=200000, interest_bearing=False):
    return fixtures.escheat_property(api, amount_cents=amount_cents,
                                     interest_bearing=interest_bearing,
                                     dormancy_basis="ISSUANCE", pt_code="MO02",
                                     clock="2026-07-15T00:00:00Z")


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/fee_cap_exact_boundary
# ---------------------------------------------------------------------------
def test_fee_at_exact_cap_accepted(api):
    """PRD §3.6: "It may not exceed the smaller of the filing firm's own max_fee_pct and the
    statutory ceiling of 10 percent (STATE_MAX_FEE_PCT, 0.10); a fee exactly at that combined
    cap is allowed, and anything above it is rejected with ERR_FEE_EXCEEDS_CAP (HTTP 422)."

    firm max_fee_pct 0.10, contract_fee_pct exactly 0.10 == min(0.10, 0.10) is accepted; the
    new claim is FILED.

    Design: Difficulty/boundary_precision_check/fee_cap_exact_boundary
    """
    ctx = _escheated_ca_property(api)
    owner = fixtures.create_owner(api)
    firm = fixtures.create_recovery_firm(api, max_fee_pct=0.10)
    ra = make_recovery_agent_headers(firm["id"])
    claim = validate_success(api.create_claim(f.create_claim_payload(
        ctx["property"]["id"], owner["id"], "FIRM", recovery_firm_id=firm["id"],
        contract_fee_pct=0.10), ra), 201)
    assert claim["status"] == "FILED", f"fee exactly at cap must be accepted, got {claim['status']}"


def test_provisional_fee_uses_face_value_at_cap(api):
    """PRD §3.6: "The provisional fee uses the property's pre-interest face value: it is the
    effective fee fraction — the smaller of the claim's contract_fee_pct and the 10-percent
    statutory ceiling — multiplied by the property's face amount_cents, rounded half-up to
    whole cents."

    face 200000, effective fraction 0.10 -> provisional_fee_cents 20000.

    Design: Difficulty/boundary_precision_check/fee_cap_exact_boundary
    """
    ctx = _escheated_ca_property(api)
    owner = fixtures.create_owner(api)
    firm = fixtures.create_recovery_firm(api, max_fee_pct=0.10)
    ra = make_recovery_agent_headers(firm["id"])
    claim = validate_success(api.create_claim(f.create_claim_payload(
        ctx["property"]["id"], owner["id"], "FIRM", recovery_firm_id=firm["id"],
        contract_fee_pct=0.10), ra), 201)
    assert claim["provisional_fee_cents"] == 20000, \
        f"provisional fee 0.10*200000 must be 20000, got {claim['provisional_fee_cents']}"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/claim_requires_property_escheated
# ---------------------------------------------------------------------------
def _owner_and_property(api, *, evaluate=True):
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="MO02", dormancy_basis="ISSUANCE")
    owner = fixtures.create_owner(api)
    prop = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_last_known_state="CA", amount_cents=50000,
        last_activity_date="2020-01-01T00:00:00Z", issue_date="2020-01-01T00:00:00Z"), hh), 201)
    if evaluate:
        validate_success(api.evaluate_dormancy(prop["id"], hh), 200)
    return owner, prop


def test_claim_against_dormant_property_rejected(api):
    """PRD §3.6: "A claim may be filed only against a Property in ESCHEATED; filing against a
    property in any other status is rejected with ERR_PROPERTY_NOT_CLAIMABLE (HTTP 409)."

    Filing against a DORMANT (not yet escheated) property is rejected.

    Design: Difficulty/cross_entity_state_dependency/claim_requires_property_escheated
    """
    owner, prop = _owner_and_property(api, evaluate=True)
    oh = make_owner_headers(owner["id"])
    validate_error(api.create_claim(f.create_claim_payload(prop["id"], owner["id"], "OWNER"), oh),
                   ApiErrorId.ERR_PROPERTY_NOT_CLAIMABLE.value)


def test_claim_against_active_property_rejected(api):
    """PRD §3.6: "A claim may be filed only against a Property in ESCHEATED; filing against a
    property in any other status is rejected with ERR_PROPERTY_NOT_CLAIMABLE (HTTP 409)."

    ACTIVE is another non-ESCHEATED status, so a claim against a never-evaluated property is
    likewise rejected.

    Design: Difficulty/cross_entity_state_dependency/claim_requires_property_escheated
    """
    owner, prop = _owner_and_property(api, evaluate=False)
    oh = make_owner_headers(owner["id"])
    validate_error(api.create_claim(f.create_claim_payload(prop["id"], owner["id"], "OWNER"), oh),
                   ApiErrorId.ERR_PROPERTY_NOT_CLAIMABLE.value)


# ---------------------------------------------------------------------------
# Corner/validations/claim_fee_exceeds_cap_returns_error
# ---------------------------------------------------------------------------
def test_claim_fee_exceeds_cap_rejected(api):
    """PRD §3.6: "It may not exceed the smaller of the filing firm's own max_fee_pct and the
    statutory ceiling of 10 percent (STATE_MAX_FEE_PCT, 0.10); a fee exactly at that combined
    cap is allowed, and anything above it is rejected with ERR_FEE_EXCEEDS_CAP (HTTP 422)."

    contract_fee_pct 0.20 exceeds min(firm 0.10, 0.10).

    Design: Corner/validations/claim_fee_exceeds_cap_returns_error
    """
    ctx = _escheated_ca_property(api, amount_cents=50000)
    owner = fixtures.create_owner(api)
    firm = fixtures.create_recovery_firm(api, max_fee_pct=0.10)
    ra = make_recovery_agent_headers(firm["id"])
    validate_error(api.create_claim(f.create_claim_payload(
        ctx["property"]["id"], owner["id"], "FIRM", recovery_firm_id=firm["id"],
        contract_fee_pct=0.20), ra), ApiErrorId.ERR_FEE_EXCEEDS_CAP.value)


# ---------------------------------------------------------------------------
# Corner/validations/firm_claim_without_firm_id_returns_error
# ---------------------------------------------------------------------------
def test_firm_claim_without_firm_id_rejected(api):
    """PRD §3.6: "When filed_by is FIRM, the request must supply a non-null recovery_firm_id and
    an agreed fee fraction in contract_fee_pct ... A filing that violates this shape — a
    firm-filed claim without a firm, or an owner-filed claim carrying a firm or a nonzero fee —
    is rejected with ERR_FIRM_REQUIRED (HTTP 422)."

    Design: Corner/validations/firm_claim_without_firm_id_returns_error
    """
    ctx = _escheated_ca_property(api, amount_cents=50000)
    owner = fixtures.create_owner(api)
    ra = TEST_USERS["recovery_agent_headers"]
    validate_error(api.create_claim(f.create_claim_payload(
        ctx["property"]["id"], owner["id"], "FIRM"), ra),
        ApiErrorId.ERR_FIRM_REQUIRED.value)


# ---------------------------------------------------------------------------
# Corner/validations/second_active_claim_on_property_returns_already_active
# ---------------------------------------------------------------------------
def test_second_active_claim_on_property_rejected(api):
    """PRD §3.6: "A property may carry at most one live claim at a time: if the property already
    has a claim in any non-terminal status — FILED, UNDER_REVIEW, NEEDS_EVIDENCE, APPROVED, or
    PAID — a new filing is rejected with ERR_CLAIM_ALREADY_ACTIVE (HTTP 409)."

    Design: Corner/validations/second_active_claim_on_property_returns_already_active
    """
    ctx = _escheated_ca_property(api, amount_cents=50000)
    owner1 = fixtures.create_owner(api, ssn_last4="1234", email="j@x.com")
    owner2 = fixtures.create_owner(api, full_name="John Roe", ssn_last4="5678", email="r@x.com")
    validate_success(api.create_claim(f.create_claim_payload(
        ctx["property"]["id"], owner1["id"], "OWNER"), make_owner_headers(owner1["id"])), 201)
    validate_error(api.create_claim(f.create_claim_payload(
        ctx["property"]["id"], owner2["id"], "OWNER"), make_owner_headers(owner2["id"])),
        ApiErrorId.ERR_CLAIM_ALREADY_ACTIVE.value)
