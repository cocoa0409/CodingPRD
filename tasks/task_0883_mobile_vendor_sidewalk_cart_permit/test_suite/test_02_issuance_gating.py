"""Permit issuance / cart approval gating on sibling-entity state, permit
validity overlap, and issuance RBAC (Difficulty: cross_entity_state_dependency,
resource_temporal_overlap; Corner: errors, rbac)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_cart_payload, TEST_USERS, make_vendor_headers,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]
HI = TEST_USERS["health_inspector_headers"]


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / permit_issue_depends_on_vendor_insurance
# --------------------------------------------------------------------------- #
def _submitted_permit_no_insurance():
    fx.set_clock()
    vendor = fx.create_vendor()  # no insurance policy submitted
    commissary = fx.create_commissary()
    cart = fx.create_cart(vendor["id"], commissary["id"])
    zone = fx.create_zone(zone_type="STANDARD")
    permit = fx.create_submitted_permit(vendor["id"], cart["id"], zone["id"])
    return vendor, permit


def test_issue_rejected_when_vendor_insurance_not_active(api):
    """PRD §3.3: "Issuance is gated by three checks, in this order: the vendor's
    insurance_status must be ACTIVE, otherwise ERR_INSURANCE_NOT_ACTIVE"
    PRD §3.1: "The insurance_status reads NONE until a first policy is submitted"

    Design: Difficulty/cross_entity_state_dependency/permit_issue_depends_on_vendor_insurance
    """
    _, permit = _submitted_permit_no_insurance()
    res = api.issue_permit(permit["id"], PO)
    validate_error(res, "ERR_INSURANCE_NOT_ACTIVE", expected_status=422)


def test_issue_succeeds_after_insurance_activated(api):
    """PRD §3.3: "Issuance is gated by three checks, in this order: the vendor's
    insurance_status must be ACTIVE, otherwise ERR_INSURANCE_NOT_ACTIVE"
    PRD §3.1: "it reads ACTIVE when the clock is at or after insurance_effective_at
    and strictly before insurance_expires_at and insurance_coverage_cents is at
    least 100,000,000 cents"

    Design: Difficulty/cross_entity_state_dependency/permit_issue_depends_on_vendor_insurance
    """
    vendor, permit = _submitted_permit_no_insurance()
    fx.activate_insurance(vendor["id"])
    issued = validate_success(api.issue_permit(permit["id"], PO), 200)
    assert issued["status"] == "ISSUED"


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / cart_approve_depends_on_commissary_status
# --------------------------------------------------------------------------- #
def _cart_pending_under_suspended_commissary():
    fx.set_clock()
    vendor = fx.create_vendor()
    commissary = fx.create_commissary()
    get_success_data(api_update_suspend(commissary["id"]))
    cart = fx.create_cart(vendor["id"], commissary["id"], inspect=True, approve=False)
    return commissary, cart


def api_update_suspend(commissary_id):
    from test_helpers import api_client
    return api_client.update_commissary(commissary_id, {"status": "SUSPENDED"}, HI)


def test_cart_approval_rejected_when_commissary_suspended(api):
    """PRD §3.2: "Approval requires that the cart currently holds a valid, unexpired
    PASS inspection — otherwise ERR_INSPECTION_NOT_PASSED — and that its commissary
    is ACTIVE with an unexpired license — otherwise ERR_COMMISSARY_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cart_approve_depends_on_commissary_status
    """
    _, cart = _cart_pending_under_suspended_commissary()
    res = api.approve_cart(cart["id"], PO)
    validate_error(res, "ERR_COMMISSARY_NOT_ACTIVE", expected_status=422)


def test_cart_approval_succeeds_after_commissary_reactivated(api):
    """PRD §3.2: "and that its commissary is ACTIVE with an unexpired license —
    otherwise ERR_COMMISSARY_NOT_ACTIVE."
    PRD §3.2: "A commissary is usable for cart approval only while it is ACTIVE and
    its license_expires_at is strictly after the clock."

    Design: Difficulty/cross_entity_state_dependency/cart_approve_depends_on_commissary_status
    """
    from test_helpers import api_client
    commissary, cart = _cart_pending_under_suspended_commissary()
    get_success_data(api_client.update_commissary(commissary["id"], {"status": "ACTIVE"}, HI))
    approved = validate_success(api.approve_cart(cart["id"], PO), 200)
    assert approved["status"] == "APPROVED"


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / permit_validity_overlap_closed_on_cart
# --------------------------------------------------------------------------- #
def _two_permits_same_cart_one_issued():
    ctx = fx.setup_issued_permit()  # pA ISSUED on cart, validity [2026-06-01, 2027-06-01]
    vendor, cart, zone = ctx["vendor"], ctx["cart"], ctx["zone"]
    pB = fx.create_submitted_permit(vendor["id"], cart["id"], zone["id"])
    return ctx["permit"], pB


def test_second_permit_same_cart_overlap_rejected(api):
    """PRD §3.3: "and no other permit for the same cart may already be ISSUED with a
    validity window that overlaps the new term, otherwise ERR_PERMIT_OVERLAP. Overlap
    is measured as closed intervals: an existing issued permit's [issued_at,
    expires_at] window overlaps the prospective term [clock, clock + 365 days]
    whenever the existing issued_at is at or before clock + 365 days and clock is at
    or before the existing expires_at."

    Design: Difficulty/resource_temporal_overlap/permit_validity_overlap_closed_on_cart
    """
    _, pB = _two_permits_same_cart_one_issued()
    res = api.issue_permit(pB["id"], PO)
    validate_error(res, "ERR_PERMIT_OVERLAP", expected_status=409)


def test_overlapping_permit_stays_submitted(api):
    """PRD §3.3: "and no other permit for the same cart may already be ISSUED with a
    validity window that overlaps the new term, otherwise ERR_PERMIT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/permit_validity_overlap_closed_on_cart
    """
    _, pB = _two_permits_same_cart_one_issued()
    api.issue_permit(pB["id"], PO)
    after = validate_success(api.get_permit(pB["id"], PO), 200)
    assert after["status"] == "SUBMITTED"


# --------------------------------------------------------------------------- #
# Corner: cart_approve_without_inspection_rejected
# --------------------------------------------------------------------------- #
def test_cart_approval_without_inspection_rejected(api):
    """PRD §3.2: "Approval requires that the cart currently holds a valid, unexpired
    PASS inspection — otherwise ERR_INSPECTION_NOT_PASSED"

    Design: Corner/errors/cart_approve_without_inspection_rejected
    """
    fx.set_clock()
    vendor = fx.create_vendor()
    commissary = fx.create_commissary()
    cart = fx.create_cart(vendor["id"], commissary["id"], inspect=False, approve=False)
    res = api.approve_cart(cart["id"], PO)
    validate_error(res, "ERR_INSPECTION_NOT_PASSED", expected_status=422)


# --------------------------------------------------------------------------- #
# Corner rbac: vendor_cannot_issue_permit
# --------------------------------------------------------------------------- #
def test_vendor_cannot_issue_permit(api):
    """PRD §2.1: "If the headers are present but the named role is not permitted to
    invoke the target operation per the authorization matrix in Section 4, the
    request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/vendor_cannot_issue_permit
    """
    fx.set_clock()
    vendor = fx.create_insured_vendor()
    commissary = fx.create_commissary()
    cart = fx.create_cart(vendor["id"], commissary["id"])
    zone = fx.create_zone(zone_type="STANDARD")
    permit = fx.create_submitted_permit(vendor["id"], cart["id"], zone["id"])
    # POST /permits/{id}/issue is PermitOfficer-exclusive.
    res = api.issue_permit(permit["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
