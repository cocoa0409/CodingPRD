"""Guest-pass check-in: guest-visit quota boundary, active-sponsor dependency, the
fee-chit cascade; and category-capacity activation boundary.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, TEST_USERS, make_member_headers,
    create_club, create_category, create_and_activate_membership,
    create_membership, register_guest_pass, list_member_chits,
)

_MANAGER = TEST_USERS["club_manager_headers"]


# ===========================================================================
# Difficulty: boundary_precision_check
# ===========================================================================

def test_guest_quota_first_checkin_succeeds_second_rejected(api):
    """PRD §3.5: "the sponsor must be under their guest-visit quota — the count of
    the sponsor's guest passes already CHECKED_IN in the club's current
    billing_period_index, surfaced as guest_visits_used_period, must be strictly
    less than the club's guest_visits_cap_per_period. The quota boundary is
    strict: when used visits equal the cap, the next check-in is refused with
    ERR_GUEST_QUOTA_EXCEEDED (HTTP 409)."

    Design: Difficulty/boundary_precision_check/guest_quota_strict_less_than_boundary
    """
    club = create_club(name="Quota Club", guest_visits_cap_per_period=1)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    s = create_and_activate_membership(club["id"], cat["id"], holder_name="S")
    g1 = register_guest_pass(club["id"], s["id"], guest_name="G1",
                             visit_date="2026-01-05T12:00:00Z")
    g2 = register_guest_pass(club["id"], s["id"], guest_name="G2",
                             visit_date="2026-01-05T13:00:00Z")

    # used 0 < 1 -> first check-in succeeds.
    validate_success(api.check_in_guest(g1["id"], _MANAGER))

    # used 1, not < 1 -> second rejected.
    resp = api.check_in_guest(g2["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_GUEST_QUOTA_EXCEEDED.value, 409)

    g2_after = validate_success(api.get_guest_pass(g2["id"], _MANAGER))
    assert g2_after["status"] == "REGISTERED", f"got {g2_after['status']}"
    s_after = validate_success(api.get_membership(s["id"], _MANAGER))
    assert s_after["guest_visits_used_period"] == 1, f"got {s_after['guest_visits_used_period']}"


def test_guest_quota_first_checkin_records_used_visit(api):
    """PRD §3.5: "recomputes the sponsor's guest_visits_used_period, which now
    rises by one."
    PRD §3.5: "the count of the sponsor's guest passes already CHECKED_IN in the
    club's current billing_period_index, surfaced as guest_visits_used_period,
    must be strictly less than the club's guest_visits_cap_per_period."

    Design: Difficulty/boundary_precision_check/guest_quota_strict_less_than_boundary
    """
    club = create_club(name="Quota Club 2", guest_visits_cap_per_period=1)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    s = create_and_activate_membership(club["id"], cat["id"], holder_name="S")
    g1 = register_guest_pass(club["id"], s["id"], guest_name="G1",
                             visit_date="2026-01-05T12:00:00Z")
    # The first check-in (used 0, strictly < cap 1) is allowed and increments used.
    data = validate_success(api.check_in_guest(g1["id"], _MANAGER))
    assert data["status"] == "CHECKED_IN", f"got {data['status']}"
    s_after = validate_success(api.get_membership(s["id"], _MANAGER))
    assert s_after["guest_visits_used_period"] == 1, f"got {s_after['guest_visits_used_period']}"


def test_category_capacity_first_activation_succeeds_second_rejected(api):
    """PRD §3.2: "Activation is gated on capacity: it is permitted only when the
    category's active_member_count is strictly less than its capacity; if the
    category is already at or above capacity, the activation is refused with
    ERR_CATEGORY_AT_CAPACITY (HTTP 409) and the applicant must instead go through
    the waitlist."

    Design: Difficulty/boundary_precision_check/category_capacity_empty_slot_vs_full_boundary
    """
    club = create_club(name="Cap Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    # count 0 < 1 -> first activation succeeds.
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    assert m1["account_status"] == "ACTIVE"

    m2 = create_membership(club["id"], cat["id"], holder_name="M2")
    # count 1, not < 1 -> second activation rejected.
    resp = api.activate_membership(m2["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_AT_CAPACITY.value, 409)

    m2_after = validate_success(api.get_membership(m2["id"], _MANAGER))
    assert m2_after["account_status"] == "PENDING", f"got {m2_after['account_status']}"


def test_category_capacity_first_activation_recomputes_count(api):
    """PRD §3.2: "recomputes the category's active_member_count, which now rises by
    one."
    PRD §3.1: "active_member_count ... counts the memberships in this category
    whose account_status is either ACTIVE or SUSPENDED."

    Design: Difficulty/boundary_precision_check/category_capacity_empty_slot_vs_full_boundary
    """
    club = create_club(name="Cap Club 2")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    # count 0 < capacity 1 -> activation succeeds, count becomes 1 (slot now full).
    create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    cat_after = validate_success(api.get_category(cat["id"], _MANAGER))
    assert cat_after["active_member_count"] == 1, (
        f"the single seat should now read as filled, got {cat_after['active_member_count']}"
    )


# ===========================================================================
# Difficulty: cross_entity_state_dependency (guest -> sponsor)
# ===========================================================================

def test_guest_checkin_requires_active_sponsor(api):
    """PRD §3.5: "Check-in is gated three ways: the pass must be REGISTERED (else
    ERR_INVALID_STATE, 409); the sponsoring membership must be ACTIVE; and the
    sponsor must be under their guest-visit quota."

    Design: Difficulty/cross_entity_state_dependency/guest_checkin_requires_active_sponsor
    """
    club = create_club(name="Dep2 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    s = create_and_activate_membership(club["id"], cat["id"], holder_name="S")
    g = register_guest_pass(club["id"], s["id"], guest_name="G",
                            visit_date="2026-01-05T12:00:00Z")
    validate_success(api.suspend_membership(s["id"], _MANAGER))  # sponsor now SUSPENDED

    resp = api.check_in_guest(g["id"], _MANAGER)
    # PRD §3.5 gates check-in on "the sponsoring membership must be ACTIVE" but does
    # not name the error_id for that gate (it names ERR_INVALID_STATE only for the
    # pass-not-REGISTERED gate). A PRD-faithful implementer may surface either the
    # adjacent ERR_INVALID_STATE or the catalog's ERR_MEMBERSHIP_NOT_ACTIVE (used at
    # §3.4 for the structurally identical "booking membership must be ACTIVE" gate);
    # both are HTTP 409. Accept either.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE.value,
                                    ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value])
    assert resp.status_code == 409, f"sponsor-not-active gate must be 409, got {resp.status_code}"
    g_after = validate_success(api.get_guest_pass(g["id"], _MANAGER))
    assert g_after["status"] == "REGISTERED", f"got {g_after['status']}"


def test_guest_checkin_blocked_for_suspended_sponsor_posts_no_fee(api):
    """PRD §3.5: "the sponsoring membership must be ACTIVE."
    PRD §3.5: "A successful check-in cascades a charge: it creates a chit of kind
    GUEST_FEE ... debits the sponsor's charge_balance_cents."

    Design: Difficulty/cross_entity_state_dependency/guest_checkin_requires_active_sponsor
    """
    club = create_club(name="Dep2b Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    s = create_and_activate_membership(club["id"], cat["id"], holder_name="S")
    g = register_guest_pass(club["id"], s["id"], guest_name="G",
                            visit_date="2026-01-05T12:00:00Z")
    validate_success(api.suspend_membership(s["id"], _MANAGER))

    resp = api.check_in_guest(g["id"], _MANAGER)
    # PRD §3.5 gates check-in on the sponsor being ACTIVE but does not pin the
    # error_id for that gate; ERR_INVALID_STATE and ERR_MEMBERSHIP_NOT_ACTIVE are
    # both PRD-faithful (both HTTP 409). Accept either; the load-bearing assertion
    # is that the check-in is BLOCKED and posts no fee.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE.value,
                                    ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value])
    assert resp.status_code == 409, f"sponsor-not-active gate must be 409, got {resp.status_code}"
    # No successful check-in -> no GUEST_FEE cascade onto the sponsor's balance.
    s_after = validate_success(api.get_membership(s["id"], _MANAGER))
    assert s_after["charge_balance_cents"] == 0, (
        f"a blocked check-in must not post the guest fee, got {s_after['charge_balance_cents']}"
    )


# ===========================================================================
# Corner: cross_cutting_complexity_layers (guest check-in cascade)
# ===========================================================================

def test_guest_checkin_cascades_fee_chit_to_sponsor_balance(api):
    """PRD §3.5: "A successful check-in cascades a charge: it creates a chit of
    kind GUEST_FEE whose amount_cents is the sponsor category's guest_fee_cents and
    which does not count toward the food-and-beverage minimum, records that chit's
    id on the pass as fee_chit_id, debits the sponsor's charge_balance_cents, and
    recomputes the sponsor's guest_visits_used_period, which now rises by one."

    Design: Corner/cross_cutting_complexity_layers/guest_checkin_cascades_fee_chit_to_sponsor_balance
    """
    club = create_club(name="X2 Club")  # guest cap default 4
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    s = create_and_activate_membership(club["id"], cat["id"], holder_name="S")
    g = register_guest_pass(club["id"], s["id"], guest_name="G",
                            visit_date="2026-01-05T12:00:00Z")

    data = validate_success(api.check_in_guest(g["id"], _MANAGER))
    assert data["status"] == "CHECKED_IN", f"got {data['status']}"
    assert data["fee_chit_id"] is not None, "fee_chit_id must be recorded on check-in"

    s_after = validate_success(api.get_membership(s["id"], _MANAGER))
    assert s_after["charge_balance_cents"] == 5000, f"got {s_after['charge_balance_cents']}"
    assert s_after["guest_visits_used_period"] == 1, f"got {s_after['guest_visits_used_period']}"

    chits = list_member_chits(s["id"])
    fee = [c for c in chits if c["kind"] == "GUEST_FEE" and c["amount_cents"] == 5000]
    assert len(fee) == 1, f"expected one GUEST_FEE chit of 5000, got {[(c['kind'], c['amount_cents']) for c in chits]}"
