"""Validation-priority pairs, business-rule violation errors, RBAC / ownership /
authentication enforcement, optimistic-concurrency stale-version errors, and the
resource-version increment invariant.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_member_headers, make_invalid_role_headers,
    create_club, create_category, create_and_activate_membership,
    create_membership, create_resource, create_reservation, get_resource_version,
    create_waitlist_entry, offer_waitlist_entry, get_category_version,
    create_assessment,
)

_MANAGER = TEST_USERS["club_manager_headers"]
_CLERK = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict
# ===========================================================================

def test_settle_resignation_wrong_state_reports_invalid_state_over_balance(api):
    """PRD §2.11: "Only then is the target's state validated for the requested
    transition (ERR_INVALID_STATE). ... The remaining business, safety, temporal,
    fiscal, and well-formedness checks follow, each described alongside the
    workflow it guards in §3."
    PRD §2.11: "a transition attempted from the wrong state reports
    ERR_INVALID_STATE before any version or capacity check is consulted."

    Design: Difficulty/priority_pair_validation_conflict/outstanding_balance_beats_no_eligible_independence
    """
    # Member is ACTIVE (not RESIGNED_PENDING) AND carries a non-zero balance, so
    # both the p6 state precondition and the p13 outstanding-balance check would
    # fire; PRD pins the state check first.
    club = create_club(name="Pair2 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=50000,
                          refundable_equity_cents=40000, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")  # balance 50000, ACTIVE

    resp = api.settle_resignation(m["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_membership(m["id"], _MANAGER))
    assert after["account_status"] == "ACTIVE", f"got {after['account_status']}"


def test_settle_resignation_from_suspended_reports_invalid_state_over_balance(api):
    """PRD §2.11: "Only then is the target's state validated for the requested
    transition (ERR_INVALID_STATE). ... The remaining business, safety, temporal,
    fiscal, and well-formedness checks follow."
    PRD §3.3: "settling from any state other than RESIGNED_PENDING yields
    ERR_INVALID_STATE (409)."

    Design: Difficulty/priority_pair_validation_conflict/outstanding_balance_beats_no_eligible_independence
    """
    # SUSPENDED (not RESIGNED_PENDING) AND a non-zero balance: the state check and
    # the p13 outstanding-balance check both apply; the state check is reported.
    club = create_club(name="Pair2b Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=50000,
                          refundable_equity_cents=40000, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")  # balance 50000
    validate_success(api.suspend_membership(m["id"], _MANAGER))  # SUSPENDED, balance still 50000

    resp = api.settle_resignation(m["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_membership(m["id"], _MANAGER))
    assert after["account_status"] == "SUSPENDED", f"got {after['account_status']}"


# Note: the second instance under this rule (not_active_beats_resource_conflict,
# asserting ERR_MEMBERSHIP_NOT_ACTIVE wins over ERR_RESOURCE_CONFLICT) is SKIPPED.
# Both checks live in PRD §2.11's undifferentiated "remaining business, safety,
# temporal ... checks follow" group; the PRD pins no relative order between the
# business_safety active-membership check and the business_temporal overlap check,
# so a faithful PRD-only implementer could surface either error
# (validation-priority silence pattern).


# ===========================================================================
# Corner: validations (business-rule violation -> error)
# ===========================================================================

def test_payment_exceeds_balance_rejected(api):
    """PRD §3.6: "The payment supplies a positive amount_cents that may not exceed
    the member's outstanding charge_balance_cents; a non-positive amount or one
    larger than the balance is refused with ERR_PAYMENT_INVALID (HTTP 422)."

    Design: Corner/validations/payment_exceeds_balance_rejected
    """
    club = create_club(name="V3 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=50000,
                          refundable_equity_cents=40000, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")  # balance 50000
    mh = make_member_headers(m["id"])

    resp = api.create_payment(m["id"], {"amount_cents": 99999}, mh)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID.value, 422)
    after = validate_success(api.get_membership(m["id"], _MANAGER))
    assert after["charge_balance_cents"] == 50000, f"got {after['charge_balance_cents']}"


def test_levy_no_eligible_members_rejected(api):
    """PRD §3.5: "A levy is permitted only when at least one such eligible
    membership exists (and the target was positive at creation); a levy with no
    eligible members is refused with ERR_NO_ELIGIBLE_MEMBERS (HTTP 409)."

    Design: Corner/validations/levy_no_eligible_members_rejected
    """
    club = create_club(name="V4 Club")
    create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                    refundable_equity_cents=0, monthly_dues_cents=15000,
                    fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    asmt = create_assessment(club["id"], 1000, "EQUAL", description="Roof")

    resp = api.levy_assessment(asmt["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_MEMBERS.value, 409)
    after = validate_success(api.get_assessment(asmt["id"], _MANAGER))
    assert after["status"] == "DRAFT", f"got {after['status']}"


def test_settle_resignation_outstanding_balance_blocked(api):
    """PRD §3.3: "Settlement is permitted only when the member has fully cleared
    their charge account: the membership's charge_balance_cents must equal zero,
    every chit having been settled first. A settlement attempted with a non-zero
    balance is refused with ERR_OUTSTANDING_BALANCE (HTTP 409)."

    Design: Corner/validations/settle_resignation_outstanding_balance_blocked
    """
    club = create_club(name="V5 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=50000,
                          refundable_equity_cents=40000, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")  # balance 50000
    mh = make_member_headers(m["id"])
    validate_success(api.resign_membership(m["id"], mh))  # -> RESIGNED_PENDING, balance still 50000

    resp = api.settle_resignation(m["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE.value, 409)
    after = validate_success(api.get_membership(m["id"], _MANAGER))
    assert after["account_status"] == "RESIGNED_PENDING", f"got {after['account_status']}"


# ===========================================================================
# Corner: errors (optimistic concurrency)
# ===========================================================================

def test_stale_version_on_reservation_create(api):
    """PRD §2.8: "A reservation-create request must carry expected_resource_version,
    a non-optional field whose value is the version of the Resource the client last
    observed. A resource's version is bumped every time a reservation is confirmed,
    cancelled, or amended against it ... If expected_resource_version does not match
    the resource's current version, the create is rejected with ERR_STALE_VERSION
    (HTTP 412) before the overlap check runs."

    Design: Corner/errors/stale_version_on_reservation_create
    """
    club = create_club(name="ERR1 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")
    res = create_resource(club["id"], kind="COURT", label="Court 1", turnaround_minutes=0)
    res_v0 = res["version"]
    # First booking bumps the resource version, making res_v0 stale.
    create_reservation(club["id"], res["id"], m1["id"],
                       "2026-02-01T08:00:00Z", "2026-02-01T09:00:00Z", res_v0)

    resp = api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m2["id"],
        "starts_at": "2026-02-01T10:00:00Z", "ends_at": "2026-02-01T11:00:00Z",
        "expected_resource_version": res_v0,  # stale
    }, make_member_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_stale_version_on_waitlist_accept(api):
    """PRD §2.8: "An accept request must carry expected_category_version, a
    non-optional field whose value is the version of the MembershipCategory the
    client last observed when the offer was seen. ... If expected_category_version
    does not match the category's current version, the accept is rejected with
    ERR_STALE_VERSION (HTTP 412) before a seat can be granted."

    Design: Corner/errors/stale_version_on_waitlist_accept
    """
    club = create_club(name="ERR2 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    w = create_waitlist_entry(club["id"], cat["id"], applicant_name="W")
    offer_waitlist_entry(w["id"])
    cat_v = get_category_version(cat["id"])

    resp = api.accept_waitlist_entry(
        w["id"], {"expected_category_version": cat_v - 1}, _MANAGER)  # deliberately stale
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
    after = validate_success(api.get_waitlist_entry(w["id"], _MANAGER))
    assert after["status"] == "OFFERED", f"got {after['status']}"


# ===========================================================================
# Corner: cross_cutting_complexity_layers (OCC version increment)
# ===========================================================================

def test_resource_version_increments_on_each_booking(api):
    """PRD §2.8: "A resource's version is bumped every time a reservation is
    confirmed, cancelled, or amended against it, because each of those changes the
    slot-occupancy map."
    PRD §2.4: "version, an integer that starts at 1 and increments by exactly one
    on every mutation of that resource."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_write
    """
    club = create_club(name="X1 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")
    res = create_resource(club["id"], kind="COURT", label="Court 1", turnaround_minutes=0)
    assert res["version"] == 1, f"resource version at create should be 1, got {res['version']}"

    create_reservation(club["id"], res["id"], m1["id"],
                       "2026-02-01T08:00:00Z", "2026-02-01T09:00:00Z", res["version"])
    assert get_resource_version(res["id"]) == 2, "version should be 2 after first booking"

    create_reservation(club["id"], res["id"], m2["id"],
                       "2026-02-01T10:00:00Z", "2026-02-01T11:00:00Z",
                       get_resource_version(res["id"]))
    assert get_resource_version(res["id"]) == 3, "version should be 3 after second booking"


# ===========================================================================
# Corner: rbac
# ===========================================================================

def test_member_cannot_activate_membership(api):
    """PRD §2.1: "Once a caller is authenticated, the system checks whether the
    role is permitted to perform the requested operation; a role acting outside its
    permitted operations is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: the activate endpoint is authorized for ClubManager only.

    Design: Corner/rbac/member_cannot_activate_membership
    """
    club = create_club(name="R1 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m = create_membership(club["id"], cat["id"], holder_name="M")  # PENDING

    resp = api.activate_membership(m["id"], make_member_headers(m["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_member_cannot_resign_other_member(api):
    """PRD §2.1: "a Member may only act on a Membership, Reservation, Chit, or
    GuestPass they own — meaning the resource's membership_id or
    sponsor_membership_id equals X-User-ID. A member attempting to mutate someone
    else's resource is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/member_cannot_resign_other_member
    """
    club = create_club(name="R2 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")

    # M1 acts on M2's membership: X-User-ID (m1) != membership_id (m2).
    resp = api.resign_membership(m2["id"], make_member_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    after = validate_success(api.get_membership(m2["id"], _MANAGER))
    assert after["account_status"] == "ACTIVE", f"got {after['account_status']}"


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If X-User-Role is absent or names a role the system does not
    recognize, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    club = create_club(name="R3 Club")
    resp = api.get_club(club["id"], make_invalid_role_headers())  # unrecognized role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_clerk_cannot_levy_assessment(api):
    """PRD §2.1: "Once a caller is authenticated, the system checks whether the
    role is permitted to perform the requested operation; a role acting outside its
    permitted operations is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: the levy endpoint is authorized for ClubManager only.

    Design: Corner/rbac/clerk_cannot_levy_assessment
    """
    club = create_club(name="R4 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    asmt = create_assessment(club["id"], 1000, "EQUAL", description="Roof")

    resp = api.levy_assessment(asmt["id"], _CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    after = validate_success(api.get_assessment(asmt["id"], _MANAGER))
    assert after["status"] == "DRAFT", f"got {after['status']}"
