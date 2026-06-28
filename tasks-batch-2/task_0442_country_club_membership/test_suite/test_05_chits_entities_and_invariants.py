"""Chit compensating invariants (void conserves balance and F&B spend), entity
creation/validation/computed-field corner claims, statement idempotency, and
immediate-consistency of the charge balance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, make_member_headers,
    create_club, create_category, create_and_activate_membership,
    create_membership, post_chit, open_statements, close_period,
    get_period_statement,
)
from test_helpers import api_client as _client_mod  # noqa: F401

_MANAGER = TEST_USERS["club_manager_headers"]
_CLERK = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Difficulty: compensating_invariant
# ===========================================================================

def test_chit_void_conserves_charge_balance(api):
    """PRD §3.5: "Voiding is the compensating reversal of a post: it credits
    amount_cents back to the member's charge_balance_cents, and if the chit
    counted toward food-and-beverage spend, it recomputes the member's
    fb_spend_period_cents by removing that amount — so the balance and the
    food-and-beverage tally are exactly conserved across a post followed by a
    void."

    Design: Difficulty/compensating_invariant/chit_void_conserves_charge_balance
    """
    club = create_club(name="Void Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    chit = post_chit(club["id"], m["id"], 7000, "PRO_SHOP")  # balance -> 7000

    data = validate_success(api.void_chit(chit["id"], _CLERK))
    assert data["status"] == "VOIDED", f"got {data['status']}"
    m_after = validate_success(api.get_membership(m["id"], _MANAGER))
    assert m_after["charge_balance_cents"] == 0, (
        f"forward debit 7000 must be fully reversed by the void, got {m_after['charge_balance_cents']}"
    )


def test_chit_void_credits_back_only_its_own_amount(api):
    """PRD §3.5: "Voiding is the compensating reversal of a post: it credits
    amount_cents back to the member's charge_balance_cents."
    PRD §2.9: "a charge voided always credits it back as a compensating reversal."

    Design: Difficulty/compensating_invariant/chit_void_conserves_charge_balance
    """
    club = create_club(name="Void Club 2")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    keep = post_chit(club["id"], m["id"], 3000, "PRO_SHOP")   # balance -> 3000
    drop = post_chit(club["id"], m["id"], 7000, "EVENT")      # balance -> 10000

    validate_success(api.void_chit(drop["id"], _CLERK))
    m_after = validate_success(api.get_membership(m["id"], _MANAGER))
    # Only the 7000 chit is credited back; the 3000 chit's debit remains.
    assert m_after["charge_balance_cents"] == 3000, (
        f"void must credit back exactly its own 7000, leaving 3000, "
        f"got {m_after['charge_balance_cents']}"
    )
    keep_after = validate_success(api.get_chit(keep["id"], _MANAGER))
    assert keep_after["status"] == "POSTED", f"untouched chit must stay POSTED, got {keep_after['status']}"


def test_dining_chit_void_conserves_fb_spend(api):
    """PRD §3.5: "if the chit counted toward food-and-beverage spend, it recomputes
    the member's fb_spend_period_cents by removing that amount — so the balance and
    the food-and-beverage tally are exactly conserved across a post followed by a
    void."

    Design: Difficulty/compensating_invariant/dining_void_conserves_fb_spend
    """
    club = create_club(name="Void2 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=20000, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    chit = post_chit(club["id"], m["id"], 9000, "DINING")  # fb_spend -> 9000

    data = validate_success(api.void_chit(chit["id"], _CLERK))
    assert data["status"] == "VOIDED", f"got {data['status']}"
    m_after = validate_success(api.get_membership(m["id"], _MANAGER))
    assert m_after["fb_spend_period_cents"] == 0, (
        f"DINING F&B contribution must be fully reversed, got {m_after['fb_spend_period_cents']}"
    )
    assert m_after["charge_balance_cents"] == 0, f"got {m_after['charge_balance_cents']}"


def test_voided_dining_chit_excluded_from_statement_fb_spend(api):
    """PRD §3.7: "The qualifying spend, fb_spend_cents, is the sum of the member's
    DINING chit amounts in the closing period whose status is POSTED or SETTLED
    (voided chits are excluded)."
    PRD §3.5: "if the chit counted toward food-and-beverage spend, it recomputes
    the member's fb_spend_period_cents by removing that amount."

    Design: Difficulty/compensating_invariant/dining_void_conserves_fb_spend
    """
    club = create_club(name="Void3 Club", fb_minimum_carryover_allowed=False)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=0,
                          fb_minimum_cents=20000, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    voided = post_chit(club["id"], m["id"], 9000, "DINING")
    post_chit(club["id"], m["id"], 5000, "DINING")  # this one survives
    validate_success(api.void_chit(voided["id"], _CLERK))
    close_period(club["id"])

    stmt = get_period_statement(club["id"], m["id"], 0)
    assert stmt["fb_spend_cents"] == 5000, (
        f"voided DINING chit must be excluded, only 5000 counts, got {stmt['fb_spend_cents']}"
    )
    assert stmt["fb_shortfall_cents"] == 15000, f"got {stmt['fb_shortfall_cents']}"


# ===========================================================================
# Corner: entities
# ===========================================================================

def test_create_membership_returns_pending_defaults(api):
    """PRD §3.2: "A new membership starts with account_status of PENDING and
    billing_status of CURRENT."
    PRD §2.4: "version, an integer that starts at 1 and increments by exactly one
    on every mutation of that resource."

    Design: Corner/entities/create_membership_returns_pending_defaults
    """
    club = create_club(name="E1 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    data = validate_success(api.create_membership({
        "club_id": club["id"], "category_id": cat["id"], "holder_name": "New M",
    }, _MANAGER), expected_status=201)
    assert data["account_status"] == "PENDING", f"got {data['account_status']}"
    assert data["billing_status"] == "CURRENT", f"got {data['billing_status']}"
    assert data["charge_balance_cents"] == 0, f"got {data['charge_balance_cents']}"
    assert data["version"] == 1, f"got {data['version']}"


def test_get_membership_not_found(api):
    """PRD §2.10: "Any referenced resource that does not exist yields ERR_NOT_FOUND
    (HTTP 404)."

    Design: Corner/entities/get_membership_not_found
    """
    resp = api.get_membership(NON_EXISTENT_UUID, _MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_category_missing_required_field(api):
    """PRD §3.1: "A create request whose refundable_equity_cents exceeds
    initiation_fee_cents, or that omits a required field, names an invalid enum, or
    supplies a non-positive amount where a positive integer is required, is
    rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_category_missing_required_field
    """
    club = create_club(name="E3 Club")
    # monthly_dues_cents omitted.
    resp = api.create_category({
        "club_id": club["id"], "code": "SOCIAL", "initiation_fee_cents": 0,
        "refundable_equity_cents": 0, "fb_minimum_cents": 0, "capacity": 50,
        "guest_fee_cents": 5000,
    }, _MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_category_invalid_enum_code(api):
    """PRD §3.1: "a code that must be one of GOLF, SOCIAL, or CORPORATE."
    PRD §3.1: "A create request whose ... names an invalid enum ... is rejected
    with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_category_invalid_enum_code
    """
    club = create_club(name="E4 Club")
    resp = api.create_category({
        "club_id": club["id"], "code": "PLATINUM", "initiation_fee_cents": 0,
        "refundable_equity_cents": 0, "monthly_dues_cents": 15000,
        "fb_minimum_cents": 0, "capacity": 50, "guest_fee_cents": 5000,
    }, _MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_category_equity_exceeds_initiation_rejected(api):
    """PRD §3.1: "refundable_equity_cents (the portion of that initiation treated as
    refundable equity, which must not exceed initiation_fee_cents)."
    PRD §3.1: "A create request whose refundable_equity_cents exceeds
    initiation_fee_cents ... is rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_category_equity_exceeds_initiation_rejected
    """
    club = create_club(name="E5 Club")
    resp = api.create_category({
        "club_id": club["id"], "code": "GOLF", "initiation_fee_cents": 50000,
        "refundable_equity_cents": 60000, "monthly_dues_cents": 30000,
        "fb_minimum_cents": 0, "capacity": 50, "guest_fee_cents": 5000,
        "allows_golf": True,
    }, _MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_active_member_count_is_computed(api):
    """PRD §3.1: "A category also exposes the computed active_member_count,
    initialized to 0 at creation, which counts the memberships in this category
    whose account_status is either ACTIVE or SUSPENDED."

    Design: Corner/entities/computed_active_member_count_ignores_input
    """
    club = create_club(name="E6 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=5, guest_fee_cents=5000,
                          allows_golf=True)
    create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    data = validate_success(api.get_category(cat["id"], _MANAGER))
    assert data["active_member_count"] == 1, (
        f"count should become 1 after one activation, got {data['active_member_count']}"
    )


def test_list_memberships_pagination_envelope(api):
    """PRD §2.3: "The meta block of a list response reports limit, offset,
    total_count (the total number of matching records before pagination), and
    has_more (true when records remain beyond the current page)."

    Design: Corner/entities/list_memberships_pagination_envelope
    """
    club = create_club(name="E7 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    create_membership(club["id"], cat["id"], holder_name="M1")
    create_membership(club["id"], cat["id"], holder_name="M2")

    resp = api.list_memberships(_MANAGER, params={"club_id": club["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 should return one record, got {len(data)}"
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert meta["has_more"] is True, f"got {meta['has_more']}"


def test_corporate_membership_self_referential_primary_member(api):
    """PRD §3.2: "supplying the holder_name and, for a corporate designated user,
    an optional primary_member_id that points at the roster head's membership."
    PRD §2.10: "listing memberships by club_id, category_id, or primary_member_id."

    Design: Corner/entities/corporate_self_referential_primary_member
    """
    club = create_club(name="E8 Club")
    cat = create_category(club["id"], code="CORPORATE", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=50000,
                          fb_minimum_cents=0, capacity=10, guest_fee_cents=5000,
                          allows_golf=True)
    head = create_and_activate_membership(club["id"], cat["id"], holder_name="Head")
    designated = validate_success(api.create_membership({
        "club_id": club["id"], "category_id": cat["id"], "holder_name": "Designated",
        "primary_member_id": head["id"],
    }, _MANAGER), expected_status=201)

    listing = get_success_data(api.list_memberships(
        _MANAGER, params={"primary_member_id": head["id"]}))
    match = [m for m in listing if m["id"] == designated["id"]
             and m["primary_member_id"] == head["id"]]
    assert len(match) == 1, (
        f"primary_member_id filter should return the designated user, got {listing}"
    )


# ===========================================================================
# Corner: endpoints (statement idempotency)
# ===========================================================================

def test_open_statements_idempotent_within_period(api):
    """PRD §3.6: "A manager or clerk opens statements for the current period, which
    creates one OPEN Statement per eligible membership ... for the club's current
    billing_period_index if one is not already present; the operation is idempotent
    within a period, so calling it again does not duplicate statements."

    Design: Corner/endpoints/open_statements_idempotent_within_period
    """
    club = create_club(name="EP1 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    open_statements(club["id"])
    # Second call (shared role: clerk) must not create a duplicate.
    validate_success(api.open_statements(club["id"], _CLERK))

    listing = get_success_data(api.list_statements(
        _MANAGER, params={"membership_id": m["id"], "period_index": 0}))
    period0 = [s for s in listing if s["period_index"] == 0]
    assert len(period0) == 1, f"expected exactly one OPEN statement, got {len(period0)}"


# ===========================================================================
# Corner: consistency_model (immediate)
# ===========================================================================

def test_chit_post_immediately_visible_in_balance(api):
    """PRD §3.5: "debits the member's charge_balance_cents by amount_cents."
    PRD §2.9: "a charge posted to a member always debits that member's
    charge_balance_cents."

    Design: Corner/consistency_model/chit_post_immediately_visible_in_balance
    """
    club = create_club(name="CM1 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    post_chit(club["id"], m["id"], 4000, "PRO_SHOP")

    data = validate_success(api.get_membership(m["id"], _MANAGER))
    assert data["charge_balance_cents"] == 4000, (
        f"posted chit must immediately reflect in the balance, got {data['charge_balance_cents']}"
    )
