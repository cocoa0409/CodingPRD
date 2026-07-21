"""Warranty registrations and claims: active/expiry gating, precedence, voiding, and OCC on create."""
import test_helpers as H


# ==========================================================================
# Queue A — cross-entity state dependency: claim review needs ACTIVE registration
# ==========================================================================
def test_claim_review_blocked_by_void_registration(api, associate_headers):
    """PRD §3.3: "this is permitted only when the underlying registration is `ACTIVE` (otherwise
    `ERR_REGISTRATION_NOT_ACTIVE`, so a claim on a recall-flagged or voided registration cannot
    enter review) and only when the logical clock is strictly before the registration's
    `warranty_expiry` (otherwise `ERR_WARRANTY_EXPIRED`)."

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_registration_active
    """
    product = H.new_product(api, warranty_months=24)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api, purchase_date="2026-06-20T00:00:00Z")
    claim = H.new_claim(reg["id"], reg["version"], api, defect_type="HANDLE", description="loose handle")
    H.get_success_data(api.void_registration(reg["id"], H.TEST_USERS["manager_headers"]))
    H.validate_error(api.review_claim(claim["id"], associate_headers), H.ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)


def test_claim_review_blocked_leaves_claim_submitted(api, associate_headers):
    """PRD §3.3: "this is permitted only when the underlying registration is `ACTIVE` (otherwise
    `ERR_REGISTRATION_NOT_ACTIVE`, so a claim on a recall-flagged or voided registration cannot
    enter review) and only when the logical clock is strictly before the registration's
    `warranty_expiry` (otherwise `ERR_WARRANTY_EXPIRED`)."

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_registration_active
    """
    product = H.new_product(api, warranty_months=24)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api, purchase_date="2026-06-20T00:00:00Z")
    claim = H.new_claim(reg["id"], reg["version"], api, defect_type="HANDLE", description="loose handle")
    H.get_success_data(api.void_registration(reg["id"], H.TEST_USERS["manager_headers"]))
    H.validate_error(api.review_claim(claim["id"], associate_headers), H.ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)
    after = H.get_claim(claim["id"], api)
    assert after["status"] == "SUBMITTED"


# ==========================================================================
# Queue A — validation precedence: registration-active beats warranty-expired
# ==========================================================================
def test_claim_review_reports_registration_not_active_before_expiry(api, associate_headers):
    """PRD §2.8: "6. **Registration active** — a warranty-claim action targets a registration in
    `ACTIVE` status, else `ERR_REGISTRATION_NOT_ACTIVE` (409)."
    PRD §2.8: "7. **Warranty not expired** — a claim review occurs before the registration's
    warranty expiry, else `ERR_WARRANTY_EXPIRED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_claim_review
    """
    product = H.new_product(api, warranty_months=1)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api, serial_number="SN-10",
                             purchase_date="2026-06-01T00:00:00Z")
    claim = H.new_claim(reg["id"], reg["version"], api, defect_type="ZIPPER", description="zip stuck")
    H.get_success_data(api.void_registration(reg["id"], H.TEST_USERS["manager_headers"]))
    H.set_clock("2026-08-01T00:00:00Z", api)
    H.validate_error(api.review_claim(claim["id"], associate_headers), H.ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)


def test_registration_not_active_precedence_leaves_claim_submitted(api, associate_headers):
    """PRD §2.8: "6. **Registration active** — a warranty-claim action targets a registration in
    `ACTIVE` status, else `ERR_REGISTRATION_NOT_ACTIVE` (409)."
    PRD §2.8: "7. **Warranty not expired** — a claim review occurs before the registration's
    warranty expiry, else `ERR_WARRANTY_EXPIRED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_claim_review
    """
    product = H.new_product(api, warranty_months=1)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api, serial_number="SN-10b",
                             purchase_date="2026-06-01T00:00:00Z")
    claim = H.new_claim(reg["id"], reg["version"], api, defect_type="ZIPPER", description="zip stuck")
    H.get_success_data(api.void_registration(reg["id"], H.TEST_USERS["manager_headers"]))
    H.set_clock("2026-08-01T00:00:00Z", api)
    H.validate_error(api.review_claim(claim["id"], associate_headers), H.ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)
    after = H.get_claim(claim["id"], api)
    assert after["status"] == "SUBMITTED"


# ==========================================================================
# Queue B — state machines / validations / computed fields
# ==========================================================================
def test_resolve_already_resolved_claim_returns_invalid_state(api, manager_headers):
    """PRD §3.3: "The three states `RESOLVED`, `REJECTED`, and `SUPERSEDED` are terminal."

    Design: Corner/state_machines/resolve_resolved_claim_returns_invalid_state
    """
    _p, _c, _reg, claim = H.reviewed_claim(api)
    H.get_success_data(api.resolve_claim(claim["id"], "REPLACE", manager_headers))
    H.validate_error(api.resolve_claim(claim["id"], "REPAIR", manager_headers), H.ApiErrorId.ERR_INVALID_STATE)


def test_claim_review_after_expiry_returns_warranty_expired(api, associate_headers):
    """PRD §3.3: "this is permitted only when the underlying registration is `ACTIVE` (otherwise
    `ERR_REGISTRATION_NOT_ACTIVE`, so a claim on a recall-flagged or voided registration cannot
    enter review) and only when the logical clock is strictly before the registration's
    `warranty_expiry` (otherwise `ERR_WARRANTY_EXPIRED`)."

    Design: Corner/validations/claim_review_after_warranty_expiry_returns_warranty_expired
    """
    product = H.new_product(api, warranty_months=1)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api, purchase_date="2026-06-01T00:00:00Z")
    claim = H.new_claim(reg["id"], reg["version"], api, defect_type="ZIPPER", description="jam")
    H.set_clock("2026-08-01T00:00:00Z", api)
    H.validate_error(api.review_claim(claim["id"], associate_headers), H.ApiErrorId.ERR_WARRANTY_EXPIRED)


def test_void_registration_with_open_claim_rejected(api, manager_headers):
    """PRD §3.3: "Voiding is refused with `ERR_CLAIM_OPEN_ON_REGISTRATION` while any claim on the
    registration sits in `UNDER_REVIEW` or `NEEDS_INFO`; once `VOID`, the registration accepts no
    new claims, and `VOID` is terminal."

    Design: Corner/validations/void_registration_with_open_claim_returns_claim_open
    """
    _p, _c, reg, _claim = H.reviewed_claim(api)
    H.validate_error(api.void_registration(reg["id"], manager_headers), H.ApiErrorId.ERR_CLAIM_OPEN_ON_REGISTRATION)


def test_duplicate_serial_per_product_rejected(api, associate_headers):
    """PRD §3.3: "The `serial_number` must be unique among registrations of the same `product_id` —
    the same serial may legitimately recur across different products — and a duplicate within one
    product is rejected with `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_registration_serial_per_product_returns_duplicate
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    H.new_registration(product["id"], customer["id"], api, serial_number="SER-DUP")
    resp = api.create_registration(
        H.create_registration_payload(product["id"], customer["id"], serial_number="SER-DUP",
                                      purchase_date="2026-06-02T00:00:00Z"), associate_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_DUPLICATE)


def test_registration_computes_warranty_expiry(api):
    """PRD §3.3: "the system computes `warranty_expiry` by adding the product's `warranty_months`
    whole calendar months to `purchase_date`, preserving the exact time-of-day instant of the
    purchase."

    Design: Corner/entities/warranty_registration_computes_expiry
    """
    product = H.new_product(api, warranty_months=24)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api, purchase_date="2026-06-01T00:00:00Z")
    # PRD §3.3 fixes the computed *instant* (24 whole calendar months added, preserving the
    # exact time-of-day); it does not fix warranty_expiry's fractional-digit serialization
    # format, so compare the parsed instant rather than the exact string.
    from datetime import datetime
    _instant = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    assert _instant(reg["warranty_expiry"]) == _instant("2028-06-01T00:00:00Z")


# ==========================================================================
# Queue B — errors: OCC on warranty-claim creation
# ==========================================================================
def test_create_claim_with_stale_registration_version_rejected(api, associate_headers):
    """PRD §2.7: "Creating a warranty claim requires `expected_warranty_registration_version`,
    which must equal the current `version` of the target `WarrantyRegistration`."

    Design: Corner/errors/create_claim_stale_registration_version_returns_stale
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api)
    H.new_claim(reg["id"], reg["version"], api, description="first")  # bumps registration version 1 -> 2
    resp = api.create_claim(
        H.create_claim_payload(reg["id"], reg["version"], defect_type="WHEEL", description="second stale"),
        associate_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_STALE_VERSION)


def test_create_claim_with_current_version_supersedes_prior(api):
    """PRD §3.3: "Creating a claim supersedes the registration's prior open claim: any existing
    claim on the same registration that is still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` is
    closed to `SUPERSEDED`, and the registration's `version` is incremented by one."

    Design: Corner/errors/create_claim_correct_version_supersedes_and_bumps
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api)
    claim1 = H.new_claim(reg["id"], reg["version"], api, description="first")
    reg_now = H.get_registration(reg["id"], api)
    claim2 = H.new_claim(reg_now["id"], reg_now["version"], api, defect_type="HANDLE", description="second current")
    assert H.get_claim(claim1["id"], api)["status"] == "SUPERSEDED"
    assert H.get_claim(claim2["id"], api)["status"] == "SUBMITTED"
