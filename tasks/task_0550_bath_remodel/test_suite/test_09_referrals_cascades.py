"""Referral program credit accounting, the acceptance reward cascade, project
cancellation cascade, and the reward/void compensating invariant.

Queue A (difficulty): dual_variant_calc (premium reward), transitive_cascade
(accept depth-3, cancel depth-2), compensating_invariant (referral credit).
Queue B (corner): state_machines / referral_void_twice.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_customer, create_referral,
    setup_referral_rewarded, refresh_referral, refresh_customer, refresh_project,
)

PA = TEST_USERS["platform_admin_headers"]
IC = TEST_USERS["install_coordinator_headers"]


# --- Queue A: PREMIUM percentage reward variant ----------------------------

def test_premium_referral_reward_is_three_percent(api):
    """PRD §3.7: "For a PREMIUM tier the reward is 3% of the referred project's
    accepted_quote_total_cents, rounded half-up to a whole cent — so the same sold
    project yields a different reward under PREMIUM than under STANDARD."
    PRD §3.7: "a referral that is REGISTERED for that customer or project advances
    REGISTERED → REWARDED, has its referred_project_id set to the sold project,
    and has its reward_cents computed by program tier."

    Design: Difficulty/dual_variant_calc/referral_reward_premium_percentage_variant
    """
    ctx = setup_referral_rewarded(
        api, program_tier="PREMIUM", area=60.0, wall_system="SMOOTH_ACRYLIC",
        accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    referral = ctx["referral"]
    assert referral["status"] == "REWARDED"
    assert referral["reward_cents"] == 19420  # round(647344 * 0.03)
    assert referral["referred_project_id"] == ctx["project"]["id"]


def test_premium_reward_credited_to_referrer(api):
    """PRD §3.7: "When a referral becomes REWARDED, its computed reward_cents is
    added to the referrer's referral_credit_cents."

    Design: Difficulty/dual_variant_calc/referral_reward_premium_percentage_variant
    """
    ctx = setup_referral_rewarded(
        api, program_tier="PREMIUM", area=60.0, wall_system="SMOOTH_ACRYLIC",
        accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    assert ctx["referrer"]["referral_credit_cents"] == 19420


# --- Queue A: accept cascade (depth 3) -------------------------------------

def test_accept_cascade_advances_quote_and_project(api):
    """PRD §3.5: "The quote moves PRESENTED → ACCEPTED; the project moves QUOTED →
    SOLD; the project's permit_required and requires_accessible_crew flags are
    both set from the permit condition above (both true together when the add-on
    triggers a permit, both false otherwise); and the project's
    accepted_quote_total_cents is set to the quote's final_total_cents."
    PRD §3.5: "when none is required it advances SOLD → INSTALL_READY and its
    permit_status stays NOT_APPLICABLE."

    Design: Difficulty/transitive_cascade/accept_cascade_quote_project_referral_customer_depth3
    """
    ctx = setup_referral_rewarded(api, program_tier="STANDARD", area=100.0,
                                  wall_system="TILE_LOOK_ACRYLIC")
    assert ctx["quote"]["status"] == "ACCEPTED"
    assert ctx["project"]["status"] == "INSTALL_READY"


def test_accept_cascade_rewards_registered_referral(api):
    """PRD §3.7: "For a STANDARD tier the reward is a flat 50000 cents, regardless
    of the project's value."
    PRD §3.7: "When a referral becomes REWARDED, its computed reward_cents is added
    to the referrer's referral_credit_cents."

    Design: Difficulty/transitive_cascade/accept_cascade_quote_project_referral_customer_depth3
    """
    ctx = setup_referral_rewarded(api, program_tier="STANDARD", area=100.0,
                                  wall_system="TILE_LOOK_ACRYLIC")
    assert ctx["referral"]["status"] == "REWARDED"
    assert ctx["referral"]["reward_cents"] == 50000
    assert ctx["referrer"]["referral_credit_cents"] == 50000


# --- Queue A: cancel cascade (depth 2) -------------------------------------

def test_cancel_cascade_voids_referral(api):
    """PRD §3.8: "The cancellation records the supplied cancel_reason on the
    project and moves it to CANCELLED, then unwinds everything still in flight
    beneath it: ... and every REWARDED referral tied to this project is moved to
    VOID, which reverses the referrer's credit exactly as an explicit void would."

    Design: Difficulty/transitive_cascade/cancel_cascade_project_referral_customer_depth2
    """
    ctx = setup_referral_rewarded(api, program_tier="STANDARD", area=100.0,
                                  wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.cancel_project(
        ctx["project"]["id"], {"cancel_reason": "customer backed out"}, IC), 200)
    assert refresh_project(api, ctx["project"]["id"])["status"] == "CANCELLED"
    assert refresh_referral(api, ctx["referral"]["id"])["status"] == "VOID"


def test_cancel_cascade_reverses_referrer_credit(api):
    """PRD §3.8: "and every REWARDED referral tied to this project is moved to
    VOID, which reverses the referrer's credit exactly as an explicit void would."
    PRD §3.7: "It is floored at zero and never goes negative."

    Design: Difficulty/transitive_cascade/cancel_cascade_project_referral_customer_depth2
    """
    ctx = setup_referral_rewarded(api, program_tier="STANDARD", area=100.0,
                                  wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.cancel_project(
        ctx["project"]["id"], {"cancel_reason": "customer backed out"}, IC), 200)
    referrer = refresh_customer(api, ctx["referrer"]["id"])
    assert referrer["referral_credit_cents"] == 0


# --- Queue A: reward/void compensating invariant ---------------------------

def test_void_rewarded_referral_moves_to_void(api):
    """PRD §3.7: "Voiding is allowed from any non-void status
    (ERR_REFERRAL_INVALID_STATE if it is already VOID) and moves the referral to
    VOID."

    Design: Difficulty/compensating_invariant/referral_credit_conserved_after_reward_then_void
    """
    ctx = setup_referral_rewarded(api, program_tier="STANDARD", area=100.0,
                                  wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.void_referral(ctx["referral"]["id"], PA), 200)
    assert refresh_referral(api, ctx["referral"]["id"])["status"] == "VOID"


def test_void_rewarded_referral_reverses_credit(api):
    """PRD §3.7: "Crucially, if the referral had already reached REWARDED, voiding
    it reverses the compensation: the referrer's referral_credit_cents is reduced
    by that same reward_cents."

    Design: Difficulty/compensating_invariant/referral_credit_conserved_after_reward_then_void
    """
    ctx = setup_referral_rewarded(api, program_tier="STANDARD", area=100.0,
                                  wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.void_referral(ctx["referral"]["id"], PA), 200)
    referrer = refresh_customer(api, ctx["referrer"]["id"])
    assert referrer["referral_credit_cents"] == 0


# --- Queue B (corner) ------------------------------------------------------

def test_void_already_void_referral_rejected(api):
    """PRD §3.7: "Voiding is allowed from any non-void status
    (ERR_REFERRAL_INVALID_STATE if it is already VOID) and moves the referral to
    VOID."

    Design: Corner/state_machines/referral_void_twice_returns_invalid_state
    """
    referrer = create_customer(api)
    referral = create_referral(api, referrer["id"])
    validate_success(api.void_referral(referral["id"], PA), 200)
    resp = api.void_referral(referral["id"], PA)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_INVALID_STATE.value)
