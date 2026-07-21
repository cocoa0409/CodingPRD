"""Membership registration, activation, and co-op dividend calculations."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    fixtures, factories,
)

ADMIN = fixtures.ADMIN
STAFF = fixtures.STAFF
ANON = fixtures.ANON


# ---------------------------------------------------------------------------
# Queue B — entities corner
# ---------------------------------------------------------------------------

def test_register_member_defaults_to_basic_tier(api):
    """PRD §3.1: "optionally choosing a `membership_tier` of either `BASIC` or
    `PREMIER`; when the tier is omitted it defaults to `BASIC`. Registration
    creates the member in `PENDING` `membership_status` and pins a read-only
    `join_fee_cents` from the chosen tier: a `BASIC` join costs 3000 cents,
    while a `PREMIER` join costs 12000 cents."

    Design: Corner/entities/create_member_success_defaults_basic
    """
    data = validate_success(api.register_member(
        {"email": "def@x.com", "full_name": "Default Member"}, ANON), 201)
    assert data["membership_tier"] == "BASIC"
    assert data["join_fee_cents"] == 3000
    assert data["membership_status"] == "PENDING"


def test_register_premier_member_pins_higher_join_fee(api):
    """PRD §3.1: "pins a read-only `join_fee_cents` from the chosen tier: a
    `BASIC` join costs 3000 cents, while a `PREMIER` join costs 12000 cents."

    Design: Corner/entities/create_member_premier_join_fee
    """
    data = validate_success(api.register_member(
        {"email": "prem@x.com", "full_name": "Premier Member",
         "membership_tier": "PREMIER"}, ANON), 201)
    assert data["join_fee_cents"] == 12000


def test_get_missing_member_returns_not_found(api):
    """PRD §2.9: "A missing member yields `ERR_MEMBER_NOT_FOUND`".

    Design: Corner/entities/member_not_found_returns_404
    """
    validate_error(api.get_member(NON_EXISTENT_UUID, ADMIN),
                   ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


def test_activate_already_active_member_rejected(api):
    """PRD §3.1: "Collecting the join fee and moving a member from `PENDING` to
    `ACTIVE` is a front-desk action; it requires the member currently be
    `PENDING`, otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/member_activate_from_active_returns_invalid_state
    """
    member, _ = fixtures.create_active_member(api)
    validate_error(api.activate_member(member["id"], STAFF),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / dividend_provisional_vs_final_on_member
# ---------------------------------------------------------------------------

def test_provisional_dividend_uses_fixed_provisional_rate(api):
    """PRD §3.9: "The provisional figure shown on a member's summary before any
    declaration is finalized, `provisional_dividend_cents`, is the floor of the
    member's `eligible_spend_cents` multiplied by the fixed provisional rate of
    0.05."

    Design: Difficulty/dual_variant_calc/dividend_provisional_vs_final_on_member
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, _, _ = fixtures.setup_member_with_eligible_spend(
        api, 200000, tier="PREMIER")
    fixtures.create_draft_declaration(api, year=2026, declared_rate=0.08)
    summary = validate_success(api.get_member_summary(member["id"], member_headers))
    assert summary["eligible_spend_cents"] == 200000
    assert summary["provisional_dividend_cents"] == 10000


def test_final_dividend_uses_declared_rate_and_credits_wallet(api):
    """PRD §3.9: "At finalize, every member whose `eligible_spend_cents` is at
    least 100000 cents receives a final dividend equal to the floor of that
    member's `eligible_spend_cents` multiplied by the declaration's
    `declared_rate`, credited to the member's `wallet_credit_cents`."
    PRD §3.9: "and `total_payout_cents` is pinned as the sum of those final
    dividends."

    Design: Difficulty/dual_variant_calc/dividend_provisional_vs_final_on_member
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, _, _ = fixtures.setup_member_with_eligible_spend(
        api, 200000, tier="PREMIER")
    decl = fixtures.create_draft_declaration(api, year=2026, declared_rate=0.08)
    decl = validate_success(api.finalize_declaration(decl["id"], ADMIN))
    assert decl["total_payout_cents"] == 16000
    member = validate_success(api.get_member(member["id"], member_headers))
    assert member["wallet_credit_cents"] == 16000


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / dividend_eligibility_threshold_ge_boundary
# ---------------------------------------------------------------------------

def test_dividend_paid_at_exact_eligibility_boundary(api):
    """PRD §3.9: "At finalize, every member whose `eligible_spend_cents` is at
    least 100000 cents receives a final dividend equal to the floor of that
    member's `eligible_spend_cents` multiplied by the declaration's
    `declared_rate`, credited to the member's `wallet_credit_cents`."

    Design: Difficulty/boundary_precision_check/dividend_eligibility_threshold_ge_boundary
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, _, _ = fixtures.setup_member_with_eligible_spend(api, 100000)
    decl = fixtures.create_draft_declaration(api, year=2026, declared_rate=0.10)
    decl = validate_success(api.finalize_declaration(decl["id"], ADMIN))
    assert decl["total_payout_cents"] == 10000
    member = validate_success(api.get_member(member["id"], member_headers))
    assert member["wallet_credit_cents"] == 10000


def test_dividend_not_paid_below_eligibility_boundary(api):
    """PRD §3.9: "Members below the 100000-cent threshold receive no payout and
    no payout entry."

    Design: Difficulty/boundary_precision_check/dividend_eligibility_threshold_ge_boundary
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, _, _ = fixtures.setup_member_with_eligible_spend(api, 99999)
    decl = fixtures.create_draft_declaration(api, year=2026, declared_rate=0.10)
    decl = validate_success(api.finalize_declaration(decl["id"], ADMIN))
    assert decl["total_payout_cents"] == 0
    assert decl["payouts"] == []
    member = validate_success(api.get_member(member["id"], member_headers))
    assert member["wallet_credit_cents"] == 0
