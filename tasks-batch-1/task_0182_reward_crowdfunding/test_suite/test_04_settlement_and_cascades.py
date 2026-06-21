"""Settlement, the dual-variant raise/reliability figures, multi-level cascades at close,
parallel pledge axes, compensating invariants, and terminal-state lockdowns.

Translates queue-A difficulty rules dual_variant_calc, combinatorial_formula (platform_fee),
non_linear_state_machine (parallel axes), transitive_cascade, compensating_invariant, plus
queue-B state_machines corners that require a closed campaign.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_creator_headers, make_backer_headers,
    create_pledge_payload,
    register_creator, register_backer, create_live_campaign_with_tier,
    add_stretch_goal, create_draft_campaign, add_tier, launch_campaign,
    create_pledge, queue_authorization, advance_clock, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
DEADLINE = "2026-07-01T00:00:00.000Z"


def _campaign_version(api, campaign_id):
    return validate_success(api.get_campaign(campaign_id, ADMIN), 200)["version"]


# --------------------------------------------------------------------------- #
# dual_variant_calc / projected_vs_settled_raise_on_campaign (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_projected_raise_counts_pending_auth_pledges(api):
    """PRD §3.9: "the projected committed_amount_cents while LIVE counts every ACTIVE pledge
    whose payment_status is PENDING_AUTH, AUTHORIZED, or CAPTURED, whereas the settled figure
    counts only those that ended up AUTHORIZED or CAPTURED."

    Design: Difficulty/dual_variant_calc/projected_vs_settled_raise_on_campaign
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="ALL_OR_NOTHING", funding_goal_cents=10000,
        tier_overrides={"price_cents": 5000, "weight_grams": 800})
    b = register_backer(api)
    for _ in range(3):
        v = _campaign_version(api, campaign["id"])
        create_pledge(api, campaign, b, tier, v, pledge_amount_cents=5000, destination_zone="DOMESTIC")
    data = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    # three PENDING_AUTH pledges of 5650 each -> projected 16950
    assert data["committed_amount_cents"] == 16950, (
        f"Expected projected 16950, got {data['committed_amount_cents']}"
    )


def test_settled_raise_excludes_declined_pledge(api):
    """PRD §3.9: "The campaign's settled_amount_cents is the sum of committed_amount_cents over
    the pledges that are now AUTHORIZED ... it differs from the projected raise the campaign
    showed while LIVE precisely by the total committed_amount_cents of every pledge whose
    authorization was declined".
    PRD §3.9: "the campaign's goal_met is set true exactly when the settled amount is at or
    above the funding_goal_cents".

    Design: Difficulty/dual_variant_calc/projected_vs_settled_raise_on_campaign
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="ALL_OR_NOTHING", funding_goal_cents=10000,
        tier_overrides={"price_cents": 5000, "weight_grams": 800})
    b = register_backer(api)
    pledges = []
    for _ in range(3):
        v = _campaign_version(api, campaign["id"])
        p = create_pledge(api, campaign, b, tier, v, pledge_amount_cents=5000, destination_zone="DOMESTIC")
        pledges.append(p)
    # p1, p3 SUCCEEDED; p2 DECLINED
    queue_authorization(api, pledges[0], "SUCCEEDED")
    queue_authorization(api, pledges[1], "DECLINED")
    queue_authorization(api, pledges[2], "SUCCEEDED")
    advance_clock(api, DEADLINE)
    data = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    # settled = 5650 + 5650 = 11300 (p2 declined excluded)
    assert data["settled_amount_cents"] == 11300, (
        f"Expected settled 11300, got {data['settled_amount_cents']}"
    )
    assert data["goal_met"] is True, f"Expected goal_met True, got {data['goal_met']}"
    assert data["status"] == "SUCCESSFUL", f"Expected SUCCESSFUL, got {data['status']}"


# --------------------------------------------------------------------------- #
# dual_variant_calc / provisional_vs_final_backer_reliability_score (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_provisional_reliability_is_base_while_pending(api):
    """PRD §3.7: "If the total is zero — the backer has no decided pledges, only ones still
    PENDING_AUTH ... — the reliability_score is the base value of 100.0."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_backer_reliability_score
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000, deadline_utc="2026-06-10T00:00:00.000Z",
        tier_overrides={"price_cents": 3000, "weight_grams": 1200})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=3000, destination_zone="INTL")
    queue_authorization(api, p, "DECLINED")
    data = validate_success(api.get_backer(backer["id"], ADMIN), 200)
    assert data["reliability_score"] == 100.0, (
        f"Expected provisional 100.0, got {data['reliability_score']}"
    )


def test_final_reliability_collapses_after_decline(api):
    """PRD §3.7: "If that single pledge is then declined at close, the same backer's score
    becomes 0.0 — a good count of zero over a total of one."
    PRD §3.7: "The backer also carries a declined_auth_count, the number of this backer's
    pledges whose payment_status is AUTH_DECLINED".

    Design: Difficulty/dual_variant_calc/provisional_vs_final_backer_reliability_score
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000, deadline_utc="2026-06-10T00:00:00.000Z",
        tier_overrides={"price_cents": 3000, "weight_grams": 1200})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=3000, destination_zone="INTL")
    queue_authorization(api, p, "DECLINED")
    advance_clock(api, "2026-06-10T00:00:00.000Z")
    data = validate_success(api.get_backer(backer["id"], ADMIN), 200)
    assert data["reliability_score"] == 0.0, (
        f"Expected final 0.0, got {data['reliability_score']}"
    )
    assert data["declined_auth_count"] == 1, (
        f"Expected declined_auth_count 1, got {data['declined_auth_count']}"
    )


# --------------------------------------------------------------------------- #
# combinatorial_formula / platform_fee_round_per_pledge_then_sum_mode_b (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def _setup_two_captured_5650_pledges(api):
    """FLEXIBLE campaign, two SUCCEEDED pledges of 5650, closed SUCCESSFUL. Returns campaign id."""
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 5000, "weight_grams": 800})
    b1 = register_backer(api, email="b1@x.com", display_name="B1")
    b2 = register_backer(api, email="b2@x.com", display_name="B2")
    v1 = _campaign_version(api, campaign["id"])
    p1 = create_pledge(api, campaign, b1, tier, v1, pledge_amount_cents=5000, destination_zone="DOMESTIC")
    v2 = _campaign_version(api, campaign["id"])
    p2 = create_pledge(api, campaign, b2, tier, v2, pledge_amount_cents=5000, destination_zone="DOMESTIC")
    queue_authorization(api, p1, "SUCCEEDED")
    queue_authorization(api, p2, "SUCCEEDED")
    advance_clock(api, DEADLINE)
    return campaign["id"]


def test_platform_fee_rounds_per_pledge_then_sums(api):
    """PRD §4: "for each captured pledge, its fee is the pledge's committed_amount_cents
    multiplied by the fee rate of 0.05 (five percent), rounded half-up to whole cents per
    pledge; the platform_fee_cents is then the sum of those per-pledge rounded fees. This
    per-pledge-rounding-then-summing order is mandatory and produces results that can differ
    from summing first and rounding once."

    Design: Difficulty/combinatorial_formula/platform_fee_round_per_pledge_then_sum_mode_b
    """
    campaign_id = _setup_two_captured_5650_pledges(api)
    data = validate_success(api.get_settlement(campaign_id, ADMIN), 200)
    # round_half_up(5650*0.05)=283 each -> 283+283=566 (NOT 565 from sum-then-round)
    assert data["platform_fee_cents"] == 566, (
        f"Expected fee 566 (per-pledge round then sum), got {data['platform_fee_cents']}"
    )


def test_settlement_settled_and_payout(api):
    """PRD §4: "The creator_payout_cents is the campaign's settled_amount_cents minus the
    platform_fee_cents."

    Design: Difficulty/combinatorial_formula/platform_fee_round_per_pledge_then_sum_mode_b
    """
    campaign_id = _setup_two_captured_5650_pledges(api)
    data = validate_success(api.get_settlement(campaign_id, ADMIN), 200)
    assert data["settled_amount_cents"] == 11300, (
        f"Expected settled 11300, got {data['settled_amount_cents']}"
    )
    assert data["creator_payout_cents"] == 10734, (
        f"Expected payout 10734, got {data['creator_payout_cents']}"
    )


# --------------------------------------------------------------------------- #
# non_linear_state_machine / pledge_parallel_payment_and_fulfillment_axes (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_capture_advances_payment_and_starts_fulfillment(api):
    """PRD §3.9: "On success, every AUTHORIZED pledge has its payment_status advance from
    AUTHORIZED to CAPTURED; each captured pledge has its fulfillment_status advance from
    NOT_STARTED to SURVEY_SENT with a new FulfillmentSurvey row created (its completed flag
    false)".

    Design: Difficulty/non_linear_state_machine/pledge_parallel_payment_and_fulfillment_axes
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 3000, "weight_grams": 1200})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=3000, destination_zone="INTL")
    queue_authorization(api, p, "SUCCEEDED")
    advance_clock(api, DEADLINE)
    data = validate_success(api.get_pledge(p["id"], ADMIN), 200)
    assert data["payment_status"] == "CAPTURED", f"payment {data['payment_status']}"
    assert data["fulfillment_status"] == "SURVEY_SENT", f"fulfillment {data['fulfillment_status']}"


def test_survey_advances_fulfillment_axis_only(api):
    """PRD §3.11: "The owning backer then completes the survey, advancing the pledge's
    fulfillment_status from SURVEY_SENT to SURVEY_COMPLETE."
    PRD §3.11: "Fulfillment runs on its own axis, independent of payment".

    Design: Difficulty/non_linear_state_machine/pledge_parallel_payment_and_fulfillment_axes
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 3000, "weight_grams": 1200})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=3000, destination_zone="INTL")
    queue_authorization(api, p, "SUCCEEDED")
    advance_clock(api, DEADLINE)
    backer_headers = make_backer_headers(backer["id"])
    validate_success(api.complete_survey(p["id"], {"shipping_address": "1 Main St"}, backer_headers), 200)
    data = validate_success(api.get_pledge(p["id"], ADMIN), 200)
    assert data["payment_status"] == "CAPTURED", (
        f"payment_status must stay CAPTURED through survey, got {data['payment_status']}"
    )
    assert data["fulfillment_status"] == "SURVEY_COMPLETE", (
        f"Expected SURVEY_COMPLETE, got {data['fulfillment_status']}"
    )


# --------------------------------------------------------------------------- #
# transitive_cascade / close_failed_refund_then_inventory_release_depth3 (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_close_failed_refunds_authorized_pledge(api):
    """PRD §3.9: "The campaign becomes FAILED instead when the model is ALL_OR_NOTHING and
    goal_met is false. On failure, every AUTHORIZED pledge has its payment_status advance from
    AUTHORIZED to REFUNDED, and for each such pledge a Refund row is created whose reason is
    FAILED_CAMPAIGN and whose amount_cents equals the pledge's committed_amount_cents at that
    moment".

    Design: Difficulty/transitive_cascade/close_failed_refund_then_inventory_release_depth3
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="ALL_OR_NOTHING", funding_goal_cents=100000,
        tier_overrides={"price_cents": 5000, "limit_quantity": 1, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000, destination_zone="DOMESTIC")
    queue_authorization(api, p, "SUCCEEDED")
    advance_clock(api, DEADLINE)
    camp = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    assert camp["status"] == "FAILED", f"Expected FAILED, got {camp['status']}"
    pledge = validate_success(api.get_pledge(p["id"], ADMIN), 200)
    assert pledge["payment_status"] == "REFUNDED", f"payment {pledge['payment_status']}"
    refunds, _ = _list(api.list_refunds(ADMIN, params={"pledge_id": p["id"]}))
    assert len(refunds) == 1, f"Expected 1 refund, got {len(refunds)}"
    assert refunds[0]["reason"] == "FAILED_CAMPAIGN", f"reason {refunds[0]['reason']}"
    assert refunds[0]["amount_cents"] == 5650, f"refund amount {refunds[0]['amount_cents']}"


def test_close_failed_releases_inventory_and_retires_tier(api):
    """PRD §3.9: "Each refunded pledge then releases its tier and add-on inventory, recomputing
    the affected claimed_quantity values. As on success, every tier on the campaign is retired
    to RETIRED. This is a three-level cascade: finalizing as failed refunds the pledge, which
    in turn releases tier and add-on inventory."

    Design: Difficulty/transitive_cascade/close_failed_refund_then_inventory_release_depth3
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="ALL_OR_NOTHING", funding_goal_cents=100000,
        tier_overrides={"price_cents": 5000, "limit_quantity": 1, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000, destination_zone="DOMESTIC")
    queue_authorization(api, p, "SUCCEEDED")
    advance_clock(api, DEADLINE)
    data = validate_success(api.get_tier(tier["id"], ADMIN), 200)
    assert data["claimed_quantity"] == 0, (
        f"Expected claimed released to 0, got {data['claimed_quantity']}"
    )
    assert data["status"] == "RETIRED", f"Expected RETIRED, got {data['status']}"


# --------------------------------------------------------------------------- #
# transitive_cascade / auth_declined_release_inventory_depth2 (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_auth_declined_releases_tier_claim(api):
    """PRD §3.9: "A pledge moving to AUTH_DECLINED releases the tier inventory and add-on
    inventory it held — recomputing the tier's claimed_quantity, returning a SOLD_OUT tier to
    AVAILABLE if it now sits below its limit, and recomputing each affected add-on's
    claimed_quantity".

    Design: Difficulty/transitive_cascade/auth_declined_release_inventory_depth2
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 5000, "limit_quantity": 1, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000, destination_zone="DOMESTIC")
    queue_authorization(api, p, "DECLINED")
    # before close: tier SOLD_OUT (claimed 1 == limit 1)
    before = validate_success(api.get_tier(tier["id"], ADMIN), 200)
    assert before["status"] == "SOLD_OUT", f"Expected SOLD_OUT before close, got {before['status']}"
    advance_clock(api, DEADLINE)
    after_pledge = validate_success(api.get_pledge(p["id"], ADMIN), 200)
    assert after_pledge["payment_status"] == "AUTH_DECLINED", (
        f"Expected AUTH_DECLINED, got {after_pledge['payment_status']}"
    )
    after_tier = validate_success(api.get_tier(tier["id"], ADMIN), 200)
    assert after_tier["claimed_quantity"] == 0, (
        f"Expected claimed 0 after release, got {after_tier['claimed_quantity']}"
    )


def test_declined_pledge_advances_to_auth_declined(api):
    """PRD §3.9: "if the outcome was DECLINED, the pledge's payment_status advances from
    PENDING_AUTH to AUTH_DECLINED."

    Design: Difficulty/transitive_cascade/auth_declined_release_inventory_depth2
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 5000, "limit_quantity": 1, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000, destination_zone="DOMESTIC")
    queue_authorization(api, p, "DECLINED")
    advance_clock(api, DEADLINE)
    data = validate_success(api.get_pledge(p["id"], ADMIN), 200)
    assert data["payment_status"] == "AUTH_DECLINED", (
        f"Expected AUTH_DECLINED, got {data['payment_status']}"
    )


# --------------------------------------------------------------------------- #
# compensating_invariant / inventory_count_conserved (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_tier_claimed_count_conserved_on_create_then_cancel(api):
    """PRD §3.5: "A backer may cancel their own pledge while the campaign is LIVE. Cancellation
    sets the pledge's status to CANCELED, releases its tier claim and every add-on claim it
    held (recomputing the tier's and add-ons' claimed_quantity ...)".
    PRD §3.2: "A new tier starts with status of AVAILABLE and claimed_quantity of 0."

    Design: Difficulty/compensating_invariant/inventory_count_conserved_on_pledge_create_then_cancel
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "limit_quantity": 5, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000)
    backer_headers = make_backer_headers(backer["id"])
    validate_success(api.cancel_pledge(p["id"], backer_headers), 200)
    data = validate_success(api.get_tier(tier["id"], ADMIN), 200)
    assert data["claimed_quantity"] == 0, (
        f"Expected claimed conserved at baseline 0, got {data['claimed_quantity']}"
    )


def test_tier_claimed_count_rises_on_create_before_cancel(api):
    """PRD §3.2: "A tier's claimed_quantity is the count of pledges that currently hold a unit
    of it — specifically, pledges on this tier whose status is ACTIVE and whose payment_status
    is neither AUTH_DECLINED nor REFUNDED. It is recomputed whenever a pledge is created on the
    tier".

    Forward half of the conservation invariant: the create alone drives claimed 0 -> 1, so the
    subsequent restoration to 0 is a genuine compensation rather than a no-op.

    Design: Difficulty/compensating_invariant/inventory_count_conserved_on_pledge_create_then_cancel
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "limit_quantity": 5, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000)
    data = validate_success(api.get_tier(tier["id"], ADMIN), 200)
    assert data["claimed_quantity"] == 1, (
        f"Expected claimed 1 after create, got {data['claimed_quantity']}"
    )


def test_committed_amount_conserved_and_stretch_relocks(api):
    """PRD §3.3: "when a new pledge pushes the projected raise to or past the threshold, the
    goal moves from LOCKED to UNLOCKED; when a pledge cancellation drops the projected raise
    back below the threshold, the goal moves from UNLOCKED back to LOCKED."
    PRD §3.5: "Cancellation ... recomputes the campaign's projected committed_amount_cents
    (which may re-lock a stretch goal), and increments the campaign's version."

    Design: Difficulty/compensating_invariant/projected_raise_cents_conserved_on_pledge_create_then_cancel
    """
    creator, campaign = create_draft_campaign(api, funding_model="FLEXIBLE", funding_goal_cents=1000)
    tier = add_tier(api, creator, campaign, price_cents=5000, weight_grams=800)
    sg = add_stretch_goal(api, creator, campaign, threshold_cents=5000)
    campaign = launch_campaign(api, creator, campaign)
    backer = register_backer(api)
    v = campaign["version"]
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000, destination_zone="DOMESTIC")
    # mid-state: committed 5650 >= 5000 -> unlocked
    mid = validate_success(api.get_stretch_goal(sg["id"], ADMIN), 200)
    assert mid["unlocked"] is True, f"Expected unlocked True mid-state, got {mid['unlocked']}"
    backer_headers = make_backer_headers(backer["id"])
    validate_success(api.cancel_pledge(p["id"], backer_headers), 200)
    camp = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    assert camp["committed_amount_cents"] == 0, (
        f"Expected committed restored to 0, got {camp['committed_amount_cents']}"
    )
    final = validate_success(api.get_stretch_goal(sg["id"], ADMIN), 200)
    assert final["unlocked"] is False, (
        f"Expected stretch re-locked False, got {final['unlocked']}"
    )


def test_projected_raise_rises_on_create_before_cancel(api):
    """PRD §3.5: "Creating the pledge then recomputes the tier's claimed_quantity ..., recomputes
    the campaign's projected raise committed_amount_cents (possibly unlocking a stretch goal),
    and increments the campaign's version by one."
    PRD §3.6: "For a DOMESTIC destination, the shipping is a base of 500 cents plus 150 cents
    for every billable kilogram."

    Forward half of the money conservation invariant: the create alone drives the projected
    raise 0 -> 5650, so the later restoration to 0 is a genuine compensation.

    Design: Difficulty/compensating_invariant/projected_raise_cents_conserved_on_pledge_create_then_cancel
    """
    creator, campaign = create_draft_campaign(api, funding_model="FLEXIBLE", funding_goal_cents=1000)
    tier = add_tier(api, creator, campaign, price_cents=5000, weight_grams=800)
    campaign = launch_campaign(api, creator, campaign)
    backer = register_backer(api)
    create_pledge(api, campaign, backer, tier, campaign["version"],
                  pledge_amount_cents=5000, destination_zone="DOMESTIC")
    camp = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    assert camp["committed_amount_cents"] == 5650, (
        f"Expected projected raise 5650 after create, got {camp['committed_amount_cents']}"
    )


# --------------------------------------------------------------------------- #
# Queue-B state_machines corners requiring a closed/terminal campaign
# --------------------------------------------------------------------------- #
def test_cancel_terminal_successful_campaign_returns_invalid_state(api):
    """PRD §3.10: "A creator may cancel their own campaign while it is in DRAFT or LIVE."
    PRD §3.5: "the campaign must be in a state that permits the transition, failing with
    ERR_INVALID_STATE (HTTP 409) if not."

    Design: Corner/state_machines/cancel_terminal_successful_campaign_returns_invalid_state
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000)
    queue_authorization(api, p, "SUCCEEDED")
    advance_clock(api, DEADLINE)  # -> SUCCESSFUL (terminal)
    creator_headers = make_creator_headers(creator["id"])
    resp = api.cancel_campaign(campaign["id"], creator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_close_before_deadline_returns_not_closable(api):
    """PRD §3.8: "A platform operator may also force a specific campaign to close immediately;
    this is permitted only once the clock has reached or passed the campaign's deadline_utc,
    and an attempt before that point is rejected with ERR_NOT_CLOSABLE (HTTP 409)."

    Design: Corner/state_machines/close_before_deadline_returns_not_closable
    """
    set_clock(api, "2026-06-01T00:00:00.000Z")
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        deadline_utc=DEADLINE, set_clock_to=None)
    resp = api.close_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_CLOSABLE.value)


def test_survey_before_capture_returns_survey_not_ready(api):
    """PRD §3.11: "This is permitted only when the pledge's payment_status is CAPTURED and the
    pledge's FulfillmentSurvey exists with completed still false; an attempt to submit before
    the pledge is captured, or to submit a survey that is already complete, is rejected with
    ERR_SURVEY_NOT_READY (HTTP 409)."

    Design: Corner/state_machines/survey_before_capture_returns_survey_not_ready
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000)
    backer_headers = make_backer_headers(backer["id"])
    resp = api.complete_survey(p["id"], {"shipping_address": "1 Main St"}, backer_headers)
    validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_READY.value)


def test_cancel_captured_pledge_after_close_returns_invalid_state(api):
    """PRD §3.5: "A backer may cancel their own pledge while the campaign is LIVE."
    PRD §3.5: "After that the campaign must be in a state that permits the transition, failing
    with ERR_INVALID_STATE (HTTP 409) if not."

    Design: Corner/state_machines/cancel_captured_pledge_after_close_returns_invalid_state
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    v = _campaign_version(api, campaign["id"])
    p = create_pledge(api, campaign, backer, tier, v, pledge_amount_cents=5000)
    queue_authorization(api, p, "SUCCEEDED")
    advance_clock(api, DEADLINE)  # pledge CAPTURED, campaign SUCCESSFUL
    backer_headers = make_backer_headers(backer["id"])
    resp = api.cancel_pledge(p["id"], backer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# Helper to unwrap a paginated list response into (data, meta).
def _list(response):
    from test_helpers import validate_paginated
    return validate_paginated(response)
