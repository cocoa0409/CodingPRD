"""Validation precedence, operating gates, and cross-entity state dependencies.

Covers the named precedence pairs (state-beats-fiscal, blackout-beats-fiscal),
the program / member / partner operating gates, config-shape validations, and the
qualifying-window conservation invariant across confirm+cancel.
"""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    validate_error,
    set_clock,
    create_program,
    define_tiers,
    setup_program,
    register_member,
    post_purchase,
    get_member,
    member_version,
    add_reward,
    add_partner,
    quote_redemption,
    confirm_redemption,
    setup_quoted_redemption,
    schedule_blackout,
    create_program_payload,
    create_partner_transfer_payload,
    create_promotion_payload,
    redemption_line,
    ApiErrorId,
    STANDARD_ONLY,
    STANDARD_GOLD,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Priority pair: state gate beats fiscal gate
# ---------------------------------------------------------------------------
def test_confirm_invalid_state_beats_insufficient_points(api):
    """PRD 3.11: "After shape and conflict checks, state and business gates apply in order: the program-active gate (`ERR_PROGRAM_NOT_ACTIVE`), the target-state gate for the requested transition (`ERR_INVALID_STATE`), the member-active gate (`ERR_MEMBER_NOT_ACTIVE`), the partner-active gate (`ERR_PARTNER_PAUSED`), the transfer-blackout gate (`ERR_TRANSFER_BLACKED_OUT`), the internal past-expiry lot guard (`ERR_LOT_EXPIRED`), the transfer-block constraint (`ERR_INVALID_TRANSFER_BLOCK`), reward availability (`ERR_REWARD_UNAVAILABLE`), fulfillment stock (`ERR_INSUFFICIENT_STOCK`), and then the fiscal sufficiency check that the member's `available_points` covers the `quoted_cost_points` at confirm or the `loyalty_points` at transfer submit (`ERR_INSUFFICIENT_POINTS`)."

    A member spends exactly 600 points on a confirmed redemption (now 0 points);
    confirming the already-CONFIRMED redemption again — while points are also
    insufficient — returns the state-gate error ERR_INVALID_STATE, which precedes
    the fiscal gate.

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_insufficient_points
    """
    base = setup_program()
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=600, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 60000)   # exactly 600 points
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    v = member_version(member["id"])
    get_success_data(api.confirm_redemption(red["id"], {"expected_member_version": v}, ADMIN))
    # Second confirm: redemption is CONFIRMED (state-illegal) AND member now has 0 points.
    resp = api.confirm_redemption(red["id"], {"expected_member_version": v}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_already_confirmed_state_gate_in_isolation(api):
    """PRD 2.8: "When a state-transition endpoint is invoked against a target that is not in a state from which that transition is legal — a redemption, referral, partner transfer, promotion, points lot, or transfer blackout in the wrong state — the request is rejected with `ERR_INVALID_STATE` (HTTP 409), except where a more specific code is named for that transition (for example program activation, below)."

    Confirming an already-CONFIRMED redemption while the member still has ample
    points isolates the state gate: it fires on its own (no fiscal shortfall
    present), confirming the state check, not the fiscal check, owns this rejection.

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_insufficient_points
    """
    base = setup_program()
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=600, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 200000)   # 2000 points, far more than the cost
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    confirm_redemption(red["id"], member["id"])
    # Member still has 1400 points; redemption is CONFIRMED, so the only failing
    # gate is the state gate.
    v = member_version(member["id"])
    resp = api.confirm_redemption(red["id"], {"expected_member_version": v}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_transfer_blacked_out_beats_insufficient_points(api):
    """PRD 3.11: "After shape and conflict checks, state and business gates apply in order: the program-active gate (`ERR_PROGRAM_NOT_ACTIVE`), the target-state gate for the requested transition (`ERR_INVALID_STATE`), the member-active gate (`ERR_MEMBER_NOT_ACTIVE`), the partner-active gate (`ERR_PARTNER_PAUSED`), the transfer-blackout gate (`ERR_TRANSFER_BLACKED_OUT`), the internal past-expiry lot guard (`ERR_LOT_EXPIRED`), the transfer-block constraint (`ERR_INVALID_TRANSFER_BLOCK`), reward availability (`ERR_REWARD_UNAVAILABLE`), fulfillment stock (`ERR_INSUFFICIENT_STOCK`), and then the fiscal sufficiency check that the member's `available_points` covers the `quoted_cost_points` at confirm or the `loyalty_points` at transfer submit (`ERR_INSUFFICIENT_POINTS`)."

    A transfer during an active blackout by a member with 0 available points
    returns the blackout-gate error ERR_TRANSFER_BLACKED_OUT, which precedes the
    fiscal gate.

    Design: Difficulty/priority_pair_validation_conflict/transfer_blacked_out_beats_insufficient_points
    """
    base = setup_program()  # already activated
    prog = base["program"]
    # Build partner + blackout via the config endpoints, then activate is already done.
    partner = add_partner(prog["id"], transfer_block_size=100, min_transfer_points=100)
    schedule_blackout(partner["id"], "2026-06-14T00:00:00Z", "2026-06-16T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    member = register_member(prog["id"])   # 0 points
    v = member_version(member["id"])
    payload = create_partner_transfer_payload(member["id"], partner["id"], 100, v)
    resp = api.create_partner_transfer(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_BLACKED_OUT.value)


def test_transfer_blacked_out_gate_in_isolation(api):
    """PRD 3.8: "a transfer is refused with `ERR_TRANSFER_BLACKED_OUT` (HTTP 409) when any `SCHEDULED` blackout on the partner covers the current clock time, where coverage is the closed interval — the clock time at or after `starts_at` and at or before `ends_at`."

    A funded member (1000 points, well above the 100-point transfer) submitting
    during an active blackout is still refused with ERR_TRANSFER_BLACKED_OUT,
    isolating the blackout gate from the fiscal gate.

    Design: Difficulty/priority_pair_validation_conflict/transfer_blacked_out_beats_insufficient_points
    """
    base = setup_program()
    prog = base["program"]
    partner = add_partner(prog["id"], transfer_block_size=100, min_transfer_points=100)
    schedule_blackout(partner["id"], "2026-06-14T00:00:00Z", "2026-06-16T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    member = register_member(prog["id"])
    post_purchase(member["id"], 100000)   # 1000 points, ample
    v = member_version(member["id"])
    payload = create_partner_transfer_payload(member["id"], partner["id"], 100, v)
    resp = api.create_partner_transfer(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_BLACKED_OUT.value)


# ---------------------------------------------------------------------------
# Cross-entity state dependency
# ---------------------------------------------------------------------------
def test_confirm_requires_member_active(api):
    """PRD 2.8: "While a member is `SUSPENDED`, that member's earn (purchase posting), redemption confirmation, and partner transfers are rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."

    A QUOTED redemption whose owning member is SUSPENDED cannot confirm.

    Design: Difficulty/cross_entity_state_dependency/redemption_confirm_requires_member_active
    """
    base = setup_program()
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=600, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 60000)
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    get_success_data(api.suspend_member(member["id"], ADMIN))
    v = member_version(member["id"])   # captured AFTER suspend, so OCC matches
    resp = api.confirm_redemption(red["id"], {"expected_member_version": v}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)


def test_confirm_succeeds_after_member_reactivated(api):
    """PRD 3.2: "Administrators may suspend an `ACTIVE` member, driving them to `SUSPENDED`, and may reactivate a `SUSPENDED` member back to `ACTIVE`; the suspension gate of Section 2.8 governs what a suspended member may not do."
    PRD 3.7: "Confirmation is performed by the `Member` (or a `ProgramAdmin` acting for them) and is legal only from `QUOTED`."

    A member suspended then reactivated may confirm their QUOTED redemption: the
    member-active dependency no longer blocks it once the member is ACTIVE again.

    Design: Difficulty/cross_entity_state_dependency/redemption_confirm_requires_member_active
    """
    base = setup_program()
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=600, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 60000)
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    get_success_data(api.suspend_member(member["id"], ADMIN))
    get_success_data(api.reactivate_member(member["id"], ADMIN))
    v = member_version(member["id"])
    confirmed = get_success_data(
        api.confirm_redemption(red["id"], {"expected_member_version": v}, ADMIN))
    assert confirmed["status"] == "CONFIRMED", \
        f"Expected CONFIRMED after reactivation, got {confirmed['status']}"


def test_transfer_requires_partner_active(api):
    """PRD 2.8: "A `PartnerAccount` is either `ACTIVE` or `PAUSED`; a new partner transfer against a `PAUSED` partner is rejected with `ERR_PARTNER_PAUSED` (HTTP 409)."

    A transfer against a PAUSED partner by a funded member is rejected.

    Design: Difficulty/cross_entity_state_dependency/partner_transfer_requires_partner_active
    """
    base = setup_program()
    prog = base["program"]
    partner = add_partner(prog["id"], transfer_block_size=100, min_transfer_points=100)
    get_success_data(api.pause_partner(partner["id"], ADMIN))
    set_clock("2026-03-01T00:00:00Z")
    member = register_member(prog["id"])
    post_purchase(member["id"], 100000)   # 1000 points
    v = member_version(member["id"])
    payload = create_partner_transfer_payload(member["id"], partner["id"], 100, v)
    resp = api.create_partner_transfer(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PARTNER_PAUSED.value)


def test_transfer_succeeds_after_partner_resumed(api):
    """PRD 3.8: "An administrator may pause an `ACTIVE` partner (moving it to `PAUSED`, after which new transfers are refused with `ERR_PARTNER_PAUSED`) and resume a `PAUSED` partner back to `ACTIVE`."

    A transfer against a partner that was paused then resumed succeeds (201,
    SUBMITTED): the partner-active dependency no longer blocks it once the partner
    is ACTIVE again.

    Design: Difficulty/cross_entity_state_dependency/partner_transfer_requires_partner_active
    """
    base = setup_program()
    prog = base["program"]
    partner = add_partner(prog["id"], transfer_block_size=100, min_transfer_points=100)
    get_success_data(api.pause_partner(partner["id"], ADMIN))
    get_success_data(api.resume_partner(partner["id"], ADMIN))
    set_clock("2026-03-01T00:00:00Z")
    member = register_member(prog["id"])
    post_purchase(member["id"], 100000)   # 1000 points
    v = member_version(member["id"])
    payload = create_partner_transfer_payload(member["id"], partner["id"], 100, v)
    resp = api.create_partner_transfer(payload, ADMIN)
    xfer = get_success_data(resp)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert xfer["status"] == "SUBMITTED", f"Expected SUBMITTED, got {xfer['status']}"


# ---------------------------------------------------------------------------
# Compensating invariant: confirm+cancel conserves qualifying_points_window
# ---------------------------------------------------------------------------
def test_confirm_cancel_conserves_qualifying_window(api):
    """PRD 2.5: "A member's `qualifying_points_window` is the sum of the `qualifying_points` of that member's `EARN_PURCHASE` ledger rows whose `created_at` falls within the trailing qualifying window (Section 3.4)."
    PRD 3.3: "This same value is stamped on the `PurchaseEvent.qualifying_points` field and carried on the resulting `EARN_PURCHASE` ledger row's `qualifying_points`, while every non-`EARN_PURCHASE` ledger row carries a `qualifying_points` of 0."

    A member who spent 900000c has qualifying_points_window 9000 (and is GOLD).
    A confirm (REDEEM rows, qualifying 0) followed by a cancel (compensating
    EARN_BONUS row, qualifying 0) leaves qualifying_points_window at 9000, tier
    still GOLD, and available_points back at 9000.

    Design: Difficulty/compensating_invariant/redeem_confirm_cancel_conserves_qualifying_points_window
    """
    base = setup_program(tiers=STANDARD_GOLD, clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=600, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 900000)   # qualifying 9000 => GOLD, available 9000
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    confirm_redemption(red["id"], member["id"])
    get_success_data(api.cancel_redemption(red["id"], ADMIN))

    member = get_member(member["id"])
    assert member["qualifying_points_window"] == 9000, \
        f"Expected qualifying 9000, got {member['qualifying_points_window']}"
    assert member["current_tier_code"] == "GOLD", \
        f"Expected GOLD, got {member['current_tier_code']}"
    assert member["available_points"] == 9000, \
        f"Expected available 9000, got {member['available_points']}"


def test_confirm_cancel_preserves_gold_tier(api):
    """PRD 3.4: "Tier is recomputed on every purchase posting and on every
    expiration sweep, so that both earning and the passage of time can move a member
    between tiers."

    Burns and compensating mints contribute zero qualifying points, so a GOLD
    member who confirms then cancels a redemption remains GOLD throughout.

    Design: Difficulty/compensating_invariant/redeem_confirm_cancel_conserves_qualifying_points_window
    """
    base = setup_program(tiers=STANDARD_GOLD, clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=600, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 900000)
    member_before = get_member(member["id"])
    assert member_before["current_tier_code"] == "GOLD"
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    confirm_redemption(red["id"], member["id"])
    member_mid = get_member(member["id"])
    assert member_mid["current_tier_code"] == "GOLD", \
        f"Expected GOLD after confirm, got {member_mid['current_tier_code']}"
    get_success_data(api.cancel_redemption(red["id"], ADMIN))
    member_after = get_member(member["id"])
    assert member_after["current_tier_code"] == "GOLD", \
        f"Expected GOLD after cancel, got {member_after['current_tier_code']}"


# ---------------------------------------------------------------------------
# Program gate
# ---------------------------------------------------------------------------
def test_purchase_on_closed_program_rejected(api):
    """PRD 2.8: "Member registration, purchase posting, redemption creation, and partner transfers are permitted only while the owning program is `ACTIVE`; attempting any of them against a program that is not `ACTIVE` is rejected with `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/validations/purchase_on_closed_program_returns_409
    """
    base = setup_program()
    prog = base["program"]
    member = register_member(prog["id"])
    get_success_data(api.close_program(prog["id"], ADMIN))
    resp = api.create_purchase_event(
        {"member_id": member["id"], "eligible_amount_cents": 10000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Config-shape and uniqueness validations
# ---------------------------------------------------------------------------
def test_program_invalid_rate_rejected(api):
    """PRD 3.1: "At creation, `base_earn_rate`, `point_value_cents`, and any tier's `transfer_ratio` must each be strictly greater than zero, and any tier's `earn_multiplier` must be at least 1.0; a configuration value violating these bounds is rejected with `ERR_INVALID_RATE` (HTTP 422)."

    Design: Corner/entities/invalid_rate_on_program_create_returns_422
    """
    resp = api.create_program(create_program_payload(base_earn_rate=0), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_RATE.value)


def test_duplicate_tier_rank_rejected(api):
    """PRD 3.1: "A tier whose `code` or `rank` collides with an existing tier in the program, or a `STANDARD` tier whose threshold or rank is not 0, is rejected with `ERR_DUPLICATE_TIER` (HTTP 409)."

    Defining a second tier at rank 0 (already used by STANDARD) is rejected.

    Design: Corner/entities/tier_duplicate_rank_returns_409
    """
    prog = create_program()
    define_tiers(prog["id"], STANDARD_ONLY)
    resp = api.create_tier(prog["id"], {
        "program_id": prog["id"], "code": "SILVER", "qualify_threshold": 2000,
        "earn_multiplier": 1.25, "transfer_ratio": 0.6, "rank": 0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TIER.value)


def test_duplicate_member_email_rejected(api):
    """PRD 3.2: "A registration whose `email` already belongs to a member of that program is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409)."

    Design: Corner/entities/duplicate_member_email_within_program_returns_409
    """
    base = setup_program()
    prog = base["program"]
    register_member(prog["id"], email="m@x.com")
    resp = api.create_member(
        {"program_id": prog["id"], "email": "m@x.com", "full_name": "M2",
         "birth_month_day": "04-10"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_member_missing_required_field_rejected(api):
    """PRD 3.2: "A registrant supplies the `program_id`, an `email` (which must be unique within the program), a `full_name`, a `birth_month_day` expressed as a two-part month-day string in `MM-DD` form, and optionally a `referred_by_member_id` naming the member who invited them."
    PRD 3.11: "Then come request-shape checks — required body fields present and well-typed, enums within their domains, `birth_month_day` in `MM-DD` form, timestamps in ISO form (`ERR_INVALID_REQUEST`)".

    Registering without the required email is rejected with ERR_INVALID_REQUEST.

    Design: Corner/entities/create_member_missing_required_field_returns_422
    """
    base = setup_program()
    resp = api.create_member(
        {"program_id": base["program"]["id"], "full_name": "M",
         "birth_month_day": "03-10"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_negative_purchase_amount_rejected(api):
    """PRD 3.3: "the `eligible_amount_cents` (the eligible spend in cents that earns points, which must be at least 0; a negative amount is rejected with `ERR_NEGATIVE_AMOUNT`, HTTP 422)".

    Design: Corner/entities/negative_purchase_amount_returns_422
    """
    base = setup_program()
    member = register_member(base["program"]["id"])
    resp = api.create_purchase_event(
        {"member_id": member["id"], "eligible_amount_cents": -1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_AMOUNT.value)


def test_promotion_overlap_rejected(api):
    """PRD 3.10: "A new promotion's half-open window must not overlap any non-`CANCELLED` promotion in the program; adjacency is allowed (one window's `ends_at` may equal another's `starts_at`), and two windows overlap exactly when the new `starts_at` is strictly before the existing `ends_at` and the existing `starts_at` is strictly before the new `ends_at`. An overlapping schedule is rejected with `ERR_PROMOTION_OVERLAP` (HTTP 409)."

    Promotion A [2026-06-01, 2026-07-01); a second promotion B [2026-06-15,
    2026-07-15) strictly overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/promotion_window_overlap_half_open_adjacency_allowed
    """
    prog = create_program()
    get_success_data(api.create_promotion(
        prog["id"],
        create_promotion_payload(prog["id"], name="A", bonus_multiplier=2.0,
                                 starts_at="2026-06-01T00:00:00Z",
                                 ends_at="2026-07-01T00:00:00Z", min_eligible_cents=0),
        ADMIN))
    resp = api.create_promotion(
        prog["id"],
        create_promotion_payload(prog["id"], name="B", bonus_multiplier=3.0,
                                 starts_at="2026-06-15T00:00:00Z",
                                 ends_at="2026-07-15T00:00:00Z", min_eligible_cents=0),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROMOTION_OVERLAP.value)


def test_promotion_adjacent_window_accepted(api):
    """PRD 3.10: "A new promotion's half-open window must not overlap any non-`CANCELLED` promotion in the program; adjacency is allowed (one window's `ends_at` may equal another's `starts_at`), and two windows overlap exactly when the new `starts_at` is strictly before the existing `ends_at` and the existing `starts_at` is strictly before the new `ends_at`."

    Promotion A [2026-06-01, 2026-07-01); a promotion B starting exactly at A's
    ends_at [2026-07-01, 2026-08-01) is adjacent, not overlapping, and is accepted.

    Design: Difficulty/resource_temporal_overlap/promotion_window_overlap_half_open_adjacency_allowed
    """
    prog = create_program()
    get_success_data(api.create_promotion(
        prog["id"],
        create_promotion_payload(prog["id"], name="A", bonus_multiplier=2.0,
                                 starts_at="2026-06-01T00:00:00Z",
                                 ends_at="2026-07-01T00:00:00Z", min_eligible_cents=0),
        ADMIN))
    resp = api.create_promotion(
        prog["id"],
        create_promotion_payload(prog["id"], name="B", bonus_multiplier=3.0,
                                 starts_at="2026-07-01T00:00:00Z",
                                 ends_at="2026-08-01T00:00:00Z", min_eligible_cents=0),
        ADMIN)
    promo_b = get_success_data(resp)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert promo_b["status"] == "SCHEDULED", f"Expected SCHEDULED, got {promo_b['status']}"


def test_promotion_invalid_window_rejected(api):
    """PRD 3.10: "The `ends_at` must be strictly after the `starts_at`; otherwise the schedule is rejected with `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/promotion_invalid_window_returns_422
    """
    prog = create_program()
    resp = api.create_promotion(
        prog["id"],
        create_promotion_payload(prog["id"], name="BAD", bonus_multiplier=2.0,
                                 starts_at="2026-07-01T00:00:00Z",
                                 ends_at="2026-06-01T00:00:00Z", min_eligible_cents=0),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_program_activate_twice_rejected(api):
    """PRD 3.1: "Activation is legal only from `DRAFT`; invoking it on a program that is already `ACTIVE` or already `CLOSED` is rejected with the specific code `ERR_PROGRAM_ALREADY_ACTIVE` (HTTP 409) rather than the generic invalid-state code."

    Design: Corner/errors/program_activate_twice_returns_409
    """
    prog = create_program()
    get_success_data(api.activate_program(prog["id"], ADMIN))
    resp = api.activate_program(prog["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_ALREADY_ACTIVE.value)


# ---------------------------------------------------------------------------
# Referral creation guards
# ---------------------------------------------------------------------------
def test_self_referral_rejected(api):
    """PRD 3.6: "The `referee_email` must differ from the referrer's own email — a self-referral is rejected with `ERR_SELF_REFERRAL` (HTTP 409)."

    Design: Corner/validations/self_referral_returns_409
    """
    base = setup_program()
    prog = base["program"]
    referrer = register_member(prog["id"], email="ref@x.com", full_name="Ref")
    resp = api.create_referral(
        {"program_id": prog["id"], "referrer_member_id": referrer["id"],
         "referee_email": "ref@x.com"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SELF_REFERRAL.value)


def test_referee_already_member_rejected(api):
    """PRD 3.6: "the `referee_email` must not already belong to a registered member of the program at the time the invitation is created; an invitation to an already-enrolled address is rejected with `ERR_REFEREE_EXISTS` (HTTP 409)."

    Design: Corner/validations/referee_already_member_returns_409
    """
    base = setup_program()
    prog = base["program"]
    referrer = register_member(prog["id"], email="ref@x.com", full_name="Ref")
    register_member(prog["id"], email="friend@x.com", full_name="Friend", birth_month_day="04-20")
    resp = api.create_referral(
        {"program_id": prog["id"], "referrer_member_id": referrer["id"],
         "referee_email": "friend@x.com"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REFEREE_EXISTS.value)
