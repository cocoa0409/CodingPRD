"""Access control, validation precedence, frozen-posture gating, reference integrity,
and filtered listing.

Translates Difficulty queue (A) priority_pair_validation_conflict,
cross_entity_state_dependency (frozen) and Corner queue (B) rbac/errors/endpoints.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, build_user_headers,
    create_household, create_account, invite_member,
    setup_goal_with_funding, setup_household_period_category, contribute,
)


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict                                           #
# --------------------------------------------------------------------------- #
def test_frozen_beats_insufficient_envelope(api):
    """PRD §2.7: "Seventh, the frozen-posture guard (ERR_HOUSEHOLD_FROZEN) applies to
    spend-affecting writes. ... Then the fiscal checks: insufficient envelope on
    contribution (ERR_INSUFFICIENT_ENVELOPE)".
    PRD §2.8: "While a household's posture is FROZEN, every spend-affecting write is
    rejected with ERR_HOUSEHOLD_FROZEN."

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_insufficient_envelope
    """
    ctx = setup_goal_with_funding(allocated_cents=1000, target_cents=20000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    validate_success(api.freeze_household(hh["id"], owner_headers))
    # Contribution 9000 exceeds the 1000 envelope AND the household is frozen;
    # frozen guard (priority 7) fires before the fiscal envelope check (priority 11).
    resp = api.contribute_goal(
        hh["id"], goal["id"], {"amount_cents": 9000}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FROZEN)


def test_frozen_beats_insufficient_envelope_small_amount(api):
    """PRD §2.8: "The spend-affecting writes are: creating a transaction, posting a
    transaction, recategorizing a transaction, allocating funds to an envelope, and
    contributing to a goal."
    PRD §2.8: "While a household's posture is FROZEN, every spend-affecting write is
    rejected with ERR_HOUSEHOLD_FROZEN."

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_insufficient_envelope
    """
    ctx = setup_goal_with_funding(allocated_cents=1000, target_cents=20000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    validate_success(api.freeze_household(hh["id"], owner_headers))
    # Even an over-envelope contribution of 5000 (> available 1000) reports frozen first.
    resp = api.contribute_goal(
        hh["id"], goal["id"], {"amount_cents": 5000}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FROZEN)


def test_forbidden_beats_not_found(api):
    """PRD §2.7: "Authorization is next: a role not permitted for the operation, or an
    entity-backed user acting outside their own household, yields ERR_FORBIDDEN. Third,
    path-resource existence is checked left-to-right, yielding ERR_NOT_FOUND."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_not_found
    """
    hh, owner_headers = create_household(name="H10")
    member, member_headers = invite_member(hh["id"], owner_headers)
    # MEMBER (never permitted the OWNER-only archive) targets a non-existent account.
    resp = api.archive_account(
        hh["id"], "00000000-0000-0000-0000-000000000000", member_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_forbidden_beats_not_found_on_freeze(api):
    """PRD §2.7: "Authorization is next: a role not permitted for the operation ... yields
    ERR_FORBIDDEN. Third, path-resource existence is checked left-to-right, yielding
    ERR_NOT_FOUND."
    PRD §2.1: "a HouseholdMember ... cannot perform owner-exclusive operations."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_not_found
    """
    hh, owner_headers = create_household(name="H10b")
    member, member_headers = invite_member(hh["id"], owner_headers)
    # Freeze is OWNER-exclusive; MEMBER calling it on a real household is forbidden
    # (authorization precedes any state/body consideration).
    resp = api.freeze_household(hh["id"], member_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency (Goal -> Household frozen)                    #
# --------------------------------------------------------------------------- #
def test_contribute_blocked_by_household_frozen(api):
    """PRD §3.6: "The contribution is blocked while the household is frozen
    (ERR_HOUSEHOLD_FROZEN)".

    Design: Difficulty/cross_entity_state_dependency/contribute_blocked_by_household_frozen
    """
    ctx = setup_goal_with_funding(allocated_cents=9000, target_cents=9000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    validate_success(api.freeze_household(hh["id"], owner_headers))
    # Envelope (9000) and goal are otherwise valid; frozen household blocks the contribute.
    resp = api.contribute_goal(
        hh["id"], goal["id"], {"amount_cents": 5000}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FROZEN)


def test_contribute_allowed_after_unfreeze(api):
    """PRD §2.8: "Read operations and non-spend operations are unaffected by the freeze."
    PRD §3.6: "A successful contribution creates a GoalContribution recording its goal_id,
    its amount_cents, and a reversed flag (default false)".

    Design: Difficulty/cross_entity_state_dependency/contribute_blocked_by_household_frozen
    """
    ctx = setup_goal_with_funding(allocated_cents=9000, target_cents=9000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    validate_success(api.freeze_household(hh["id"], owner_headers))
    # Frozen -> blocked.
    blocked = api.contribute_goal(
        hh["id"], goal["id"], {"amount_cents": 5000}, owner_headers)
    validate_error(blocked, ApiErrorId.ERR_HOUSEHOLD_FROZEN)
    # Unfreeze -> the same contribution now succeeds.
    validate_success(api.unfreeze_household(hh["id"], owner_headers))
    ok = api.contribute_goal(
        hh["id"], goal["id"], {"amount_cents": 5000}, owner_headers)
    data = validate_success(ok, expected_status=201)
    assert data["amount_cents"] == 5000


# --------------------------------------------------------------------------- #
# RBAC corner instances                                                       #
# --------------------------------------------------------------------------- #
def test_member_cannot_freeze_household(api):
    """PRD §2.1: "a HouseholdMember may spend, categorize, allocate, and contribute within
    their household but cannot perform owner-exclusive operations."

    Design: Corner/rbac/member_cannot_freeze_household
    """
    hh, owner_headers = create_household()
    member, member_headers = invite_member(hh["id"], owner_headers)
    resp = api.freeze_household(hh["id"], member_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If X-User-Role is missing or is not one of the recognized role names, the
    request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    hh, owner_headers = create_household()
    # Unrecognized role -> unauthenticated.
    bad_headers = build_user_headers("someone", "Stranger")
    resp = api.get_household(hh["id"], bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_member_from_other_household_forbidden(api):
    """PRD §2.1: "When a recognized user attempts an operation their role is not permitted
    to perform — or attempts to act on a household that is not their own — the request is
    rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/member_from_other_household_forbidden
    """
    h1, owner1 = create_household(name="H1", owner_email="o1@x.com")
    p1 = get_success_data(api.create_budget_period(
        h1["id"], {"month": "2026-01", "income_expected_cents": 5000}, owner1))
    c1 = get_success_data(api.create_category(
        h1["id"], p1["id"], {"name": "C1", "allocated_cents": 5000}, owner1))
    h2, owner2 = create_household(name="H2", owner_email="o2@x.com")
    m2, m2_headers = invite_member(h2["id"], owner2, email="m2@x.com")
    # M2 (member of H2) acts on H1's allocate endpoint -> forbidden.
    resp = api.allocate_category(
        h1["id"], c1["id"], {"allocated_cents": 1000}, m2_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# --------------------------------------------------------------------------- #
# Reference integrity                                                          #
# --------------------------------------------------------------------------- #
def test_reference_not_found_on_category_rule(api):
    """PRD §2.6: "When a request body names a foreign key — an account_id, a
    budget_category_id, a funding_category_id, or a goal_id — that referent must exist and
    belong to the same household as the operation; if it does not exist or belongs to
    another household, the request fails with ERR_REFERENCE_NOT_FOUND."

    Design: Corner/errors/reference_not_found_on_category_rule
    """
    hh, owner_headers = create_household()
    get_success_data(api.create_budget_period(
        hh["id"], {"month": "2026-01", "income_expected_cents": 0}, owner_headers))
    resp = api.create_category_rule(
        hh["id"],
        {"match_substring": "x",
         "budget_category_id": "00000000-0000-0000-0000-000000000000", "priority": 1},
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


# --------------------------------------------------------------------------- #
# Filtered listing                                                            #
# --------------------------------------------------------------------------- #
def test_list_accounts_filtered_by_status(api):
    """PRD §3.2: "the listing can be filtered by household_id and by status".

    Design: Corner/endpoints/list_accounts_filtered_by_status
    """
    hh, owner_headers = create_household()
    create_account(hh["id"], owner_headers, opening_balance_cents=1000,
                   institution_name="A")
    acc_b = create_account(hh["id"], owner_headers, opening_balance_cents=2000,
                           institution_name="B")
    validate_success(api.archive_account(hh["id"], acc_b["id"], owner_headers))

    resp = api.list_accounts(
        owner_headers, params={"household_id": hh["id"], "status": "ARCHIVED"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, \
        f"only the archived account, total_count expected 1, got {meta['total_count']}"
    assert data[0]["id"] == acc_b["id"], \
        f"the single account is the archived one, got {data[0]['id']}"
