"""Pledging, the committed-amount formula, inventory boundaries, OCC, and validation precedence.

Translates queue-A difficulty rules combinatorial_formula (pledge_total), boundary_precision_check,
non_linear_state_machine (tier cycle), priority_pair_validation_conflict, cross_entity_state_dependency
(pledge-requires-live), plus queue-B validations and cross_cutting (OCC) corners.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_creator_headers, make_backer_headers,
    create_campaign_payload, create_tier_payload, create_addon_product_payload,
    create_pledge_payload, attach_addon_payload,
    register_creator, register_backer, create_draft_campaign, add_tier,
    add_addon_product, launch_campaign, create_live_campaign_with_tier,
    create_pledge, attach_addon_line, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# combinatorial_formula / pledge_total_zone_weight_addons_mode_a (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_pledge_total_with_addons_domestic(api):
    """PRD §3.6: "The total shipping weight in grams is the tier's weight_grams plus, for each
    attached add-on line, that line's quantity multiplied by its add-on's weight_grams."
    PRD §3.6: "For a DOMESTIC destination, the shipping is a base of 500 cents plus 150 cents
    for every billable kilogram."
    PRD §3.5: "The pledge's items subtotal, items_subtotal_cents, is the backer's chosen
    pledge_amount_cents plus the sum of every attached add-on line's total".

    Design: Difficulty/combinatorial_formula/pledge_total_zone_weight_addons_mode_a
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "weight_grams": 800})
    addon = add_addon_product(api, creator, campaign,
                              title="Sticker", price_cents=2000, limit_quantity=10, weight_grams=300)
    backer = register_backer(api)
    pledge = create_pledge(api, campaign, backer, tier, campaign["version"],
                           pledge_amount_cents=5000, destination_zone="DOMESTIC")
    attach_addon_line(api, backer, pledge, addon, 2)
    backer_headers = make_backer_headers(backer["id"])
    data = validate_success(api.get_pledge(pledge["id"], backer_headers), 200)
    # items 5000 + 2*2000 = 9000; weight 800 + 2*300 = 1400 -> ceil 2kg; ship 500 + 2*150 = 800
    assert data["items_subtotal_cents"] == 9000, f"items {data['items_subtotal_cents']}"
    assert data["shipping_cents"] == 800, f"shipping {data['shipping_cents']}"
    assert data["committed_amount_cents"] == 9800, f"committed {data['committed_amount_cents']}"


def test_pledge_total_intl_no_addons(api):
    """PRD §3.6: "For an INTL destination, the shipping is a base of 1500 cents plus 400 cents
    for every billable kilogram."
    PRD §3.6: "That gram total is converted to billable kilograms by dividing by 1000 and
    rounding up to the next whole kilogram (a partial kilogram always rounds up to the next
    whole kilogram)."
    PRD §3.6: "a partial kilogram always rounds up to the next whole kilogram"

    Design: Difficulty/combinatorial_formula/pledge_total_zone_weight_addons_mode_a
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 3000, "weight_grams": 1200})
    backer = register_backer(api)
    pledge = create_pledge(api, campaign, backer, tier, campaign["version"],
                           pledge_amount_cents=3000, destination_zone="INTL")
    # items 3000; weight 1200 -> ceil 2kg; ship 1500 + 2*400 = 2300; committed 5300
    assert pledge["items_subtotal_cents"] == 3000, f"items {pledge['items_subtotal_cents']}"
    assert pledge["shipping_cents"] == 2300, f"shipping {pledge['shipping_cents']}"
    assert pledge["committed_amount_cents"] == 5300, f"committed {pledge['committed_amount_cents']}"


# --------------------------------------------------------------------------- #
# boundary_precision_check / tier_soldout_at_exact_limit_on_pledge_create (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_tier_first_pledge_at_limit_succeeds(api):
    """PRD §3.2: "A tier becomes SOLD_OUT exactly when its limit_quantity is not null and,
    after a claiming pledge, its claimed_quantity is equal to its limit_quantity — the
    boundary is "equal to or greater than the limit", not "strictly greater"."

    Design: Difficulty/boundary_precision_check/tier_soldout_at_exact_limit_on_pledge_create
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "limit_quantity": 1, "weight_grams": 800})
    backer = register_backer(api, email="b1@x.com", display_name="B1")
    pledge = create_pledge(api, campaign, backer, tier, campaign["version"], pledge_amount_cents=5000)
    data = validate_success(api.get_tier(tier["id"], ADMIN), 200)
    assert data["claimed_quantity"] == 1, f"claimed {data['claimed_quantity']}"
    assert data["status"] == "SOLD_OUT", f"Expected SOLD_OUT at limit, got {data['status']}"


def test_tier_second_pledge_over_limit_rejected(api):
    """PRD §3.5: "the tier must be AVAILABLE and, when its limit_quantity is not null, its
    claimed_quantity must still be below the limit, failing with ERR_TIER_SOLD_OUT (HTTP 409)."

    Design: Difficulty/boundary_precision_check/tier_soldout_at_exact_limit_on_pledge_create
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "limit_quantity": 1, "weight_grams": 800})
    b1 = register_backer(api, email="b1@x.com", display_name="B1")
    create_pledge(api, campaign, b1, tier, campaign["version"], pledge_amount_cents=5000)
    camp_now = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    b2 = register_backer(api, email="b2@x.com", display_name="B2")
    b2_headers = make_backer_headers(b2["id"])
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(b2["id"], tier["id"], camp_now["version"],
                                                   pledge_amount_cents=5000), b2_headers)
    validate_error(resp, ApiErrorId.ERR_TIER_SOLD_OUT.value)


# --------------------------------------------------------------------------- #
# boundary_precision_check / addon_soldout_when_sum_exceeds_limit_on_addon_attach (queue A, >=2)
# --------------------------------------------------------------------------- #
def test_addon_attach_landing_on_limit_allowed(api):
    """PRD §3.5: "the boundary is that claimed-plus-requested must not go above the limit;
    landing exactly on the limit is allowed."

    Design: Difficulty/boundary_precision_check/addon_soldout_when_sum_exceeds_limit_on_addon_attach
    """
    creator, campaign, tier = create_live_campaign_with_tier(api)
    addon = add_addon_product(api, creator, campaign,
                              title="Pin", price_cents=1000, limit_quantity=5, weight_grams=100)
    backer = register_backer(api)
    pledge = create_pledge(api, campaign, backer, tier, campaign["version"], pledge_amount_cents=5000)
    attach_addon_line(api, backer, pledge, addon, 3)
    backer_headers = make_backer_headers(backer["id"])
    # 3 + 2 = 5 == limit -> allowed (landing exactly on the limit)
    resp = api.attach_addon(pledge["id"], attach_addon_payload(addon["id"], 2), backer_headers)
    validate_success(resp, 201)
    data = validate_success(api.get_addon_product(addon["id"], ADMIN), 200)
    assert data["claimed_quantity"] == 5, f"claimed {data['claimed_quantity']}"


def test_addon_attach_over_limit_rejected(api):
    """PRD §3.5: "the attach is rejected with ERR_ADDON_SOLD_OUT (HTTP 409) when the add-on's
    limit_quantity is not null and its current claimed_quantity plus the requested quantity
    would exceed the limit".

    Design: Difficulty/boundary_precision_check/addon_soldout_when_sum_exceeds_limit_on_addon_attach
    """
    creator, campaign, tier = create_live_campaign_with_tier(api)
    addon = add_addon_product(api, creator, campaign,
                              title="Pin", price_cents=1000, limit_quantity=5, weight_grams=100)
    backer = register_backer(api)
    pledge = create_pledge(api, campaign, backer, tier, campaign["version"], pledge_amount_cents=5000)
    attach_addon_line(api, backer, pledge, addon, 3)
    backer_headers = make_backer_headers(backer["id"])
    # 3 + 3 = 6 > limit 5 -> rejected
    resp = api.attach_addon(pledge["id"], attach_addon_payload(addon["id"], 3), backer_headers)
    validate_error(resp, ApiErrorId.ERR_ADDON_SOLD_OUT.value)


# --------------------------------------------------------------------------- #
# non_linear_state_machine / tier_available_soldout_available_cycle (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_tier_flips_sold_out_on_second_claim(api):
    """PRD §3.2: "A tier becomes SOLD_OUT exactly when its limit_quantity is not null and,
    after a claiming pledge, its claimed_quantity is equal to its limit_quantity".

    Design: Difficulty/non_linear_state_machine/tier_available_soldout_available_cycle
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "limit_quantity": 2, "weight_grams": 800})
    b1 = register_backer(api, email="b1@x.com", display_name="B1")
    create_pledge(api, campaign, b1, tier, campaign["version"], pledge_amount_cents=5000)
    camp_now = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    b2 = register_backer(api, email="b2@x.com", display_name="B2")
    create_pledge(api, campaign, b2, tier, camp_now["version"], pledge_amount_cents=5000)
    data = validate_success(api.get_tier(tier["id"], ADMIN), 200)
    assert data["status"] == "SOLD_OUT", f"Expected SOLD_OUT after 2 claims, got {data['status']}"
    assert data["claimed_quantity"] == 2, f"claimed {data['claimed_quantity']}"


def test_tier_returns_available_after_cancel(api):
    """PRD §3.2: "when a pledge cancels or a declined authorization releases a unit and the
    tier's claimed_quantity falls below limit_quantity again, a SOLD_OUT tier returns to
    AVAILABLE and accepts pledges once more."

    Design: Difficulty/non_linear_state_machine/tier_available_soldout_available_cycle
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "limit_quantity": 2, "weight_grams": 800})
    b1 = register_backer(api, email="b1@x.com", display_name="B1")
    create_pledge(api, campaign, b1, tier, campaign["version"], pledge_amount_cents=5000)
    camp_now = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    b2 = register_backer(api, email="b2@x.com", display_name="B2")
    p2 = create_pledge(api, campaign, b2, tier, camp_now["version"], pledge_amount_cents=5000)
    # tier now SOLD_OUT; cancel p2 -> claimed 1 < limit 2 -> AVAILABLE
    b2_headers = make_backer_headers(b2["id"])
    validate_success(api.cancel_pledge(p2["id"], b2_headers), 200)
    data = validate_success(api.get_tier(tier["id"], ADMIN), 200)
    assert data["status"] == "AVAILABLE", f"Expected AVAILABLE after cancel, got {data['status']}"
    assert data["claimed_quantity"] == 1, f"claimed {data['claimed_quantity']}"


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict (queue A, >=2 tests each instance via 2 instances)
# --------------------------------------------------------------------------- #
def test_not_live_beats_below_tier_min(api):
    """PRD §3.5: "Then the temporal gate: pledging is allowed only while the campaign is LIVE
    and the clock is still before deadline_utc; a pledge against a campaign that is not live, or
    whose deadline has passed, is rejected with ERR_CAMPAIGN_NOT_LIVE (HTTP 409). Then the
    pledge amount is checked: pledge_amount_cents must be at least the tier's price_cents,
    failing with ERR_PLEDGE_BELOW_TIER_MIN (HTTP 422) when it is below."
    PRD §3.5: "In short, the ordering is authentication, then role, then path existence, then
    foreign-key resolution, then body well-formedness, then state, then the live-window temporal
    gate, then the tier-minimum amount check, then tier inventory, then the stale-version check."

    Design: Difficulty/priority_pair_validation_conflict/not_live_temporal_beats_below_tier_min_constraint
    """
    creator, campaign = create_draft_campaign(api, set_clock_to=None)
    tier = add_tier(api, creator, campaign, price_cents=5000, weight_grams=800)
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    # DRAFT campaign (not LIVE) AND amount 100 below the 5000 minimum: temporal gate wins.
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(backer["id"], tier["id"], campaign["version"],
                                                   pledge_amount_cents=100), backer_headers)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_LIVE.value)


def test_fk_invalid_beats_below_tier_min(api):
    """PRD §3.5: "Then the body's foreign keys are resolved — the tier_id must name a tier
    belonging to this campaign and the backer_id must name a real backer — failing with
    ERR_FK_INVALID (HTTP 422) otherwise."
    PRD §3.5: "Then the pledge amount is checked: pledge_amount_cents must be at least the
    tier's price_cents, failing with ERR_PLEDGE_BELOW_TIER_MIN (HTTP 422) when it is below."

    Design: Difficulty/priority_pair_validation_conflict/fk_invalid_referential_beats_below_tier_min_constraint
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    # tier_id non-existent (FK fails) AND amount 1 below min: FK resolution (priority 4) wins.
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(backer["id"],
                                                   "00000000-0000-4000-8000-000000000000",
                                                   campaign["version"], pledge_amount_cents=1),
                             backer_headers)
    validate_error(resp, ApiErrorId.ERR_FK_INVALID.value)


def test_below_tier_min_fires_when_only_amount_check_fails(api):
    """PRD §3.5: "Then the pledge amount is checked: pledge_amount_cents must be at least the
    tier's price_cents, failing with ERR_PLEDGE_BELOW_TIER_MIN (HTTP 422) when it is below."

    Isolated lower-priority loser: on a LIVE campaign with a valid tier_id, only the amount
    check can fail, so the response is ERR_PLEDGE_BELOW_TIER_MIN (it does not pre-empt to the
    not-live or FK error).

    Design: Difficulty/priority_pair_validation_conflict/not_live_temporal_beats_below_tier_min_constraint
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    # campaign is LIVE and tier_id is valid: only the below-min amount check can fail.
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(backer["id"], tier["id"], campaign["version"],
                                                   pledge_amount_cents=100), backer_headers)
    validate_error(resp, ApiErrorId.ERR_PLEDGE_BELOW_TIER_MIN.value)


def test_fk_invalid_fires_when_only_fk_check_fails(api):
    """PRD §3.5: "Then the body's foreign keys are resolved — the tier_id must name a tier
    belonging to this campaign and the backer_id must name a real backer — failing with
    ERR_FK_INVALID (HTTP 422) otherwise."

    Isolated higher-priority winner: on a LIVE campaign, a pledge naming a non-existent tier_id
    but a valid amount surfaces ERR_FK_INVALID — confirming the FK gate fires on its own.

    Design: Difficulty/priority_pair_validation_conflict/fk_invalid_referential_beats_below_tier_min_constraint
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    # valid amount (>= 5000); only the non-existent tier_id can fail the create.
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(backer["id"],
                                                   "00000000-0000-4000-8000-000000000000",
                                                   campaign["version"], pledge_amount_cents=5000),
                             backer_headers)
    validate_error(resp, ApiErrorId.ERR_FK_INVALID.value)


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / pledge_create_requires_campaign_live (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_pledge_on_draft_campaign_rejected(api):
    """PRD §3.5: "the temporal gate: pledging is allowed only while the campaign is LIVE and
    the clock is still before deadline_utc; a pledge against a campaign that is not live, or
    whose deadline has passed, is rejected with ERR_CAMPAIGN_NOT_LIVE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/pledge_create_requires_campaign_live
    """
    creator, campaign = create_draft_campaign(api, set_clock_to=None)
    tier = add_tier(api, creator, campaign, price_cents=5000, weight_grams=800)
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    # amount meets the tier minimum; only the not-LIVE gate can fire.
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(backer["id"], tier["id"], campaign["version"],
                                                   pledge_amount_cents=5000), backer_headers)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_LIVE.value)


def test_pledge_on_live_campaign_succeeds(api):
    """PRD §3.5: "Once a campaign is LIVE, backers pledge." ... "A new pledge begins with status
    of ACTIVE, payment_status of PENDING_AUTH, and fulfillment_status of NOT_STARTED."

    Design: Difficulty/cross_entity_state_dependency/pledge_create_requires_campaign_live
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(backer["id"], tier["id"], campaign["version"],
                                                   pledge_amount_cents=5000), backer_headers)
    data = validate_success(resp, 201)
    assert data["payment_status"] == "PENDING_AUTH"
    assert data["fulfillment_status"] == "NOT_STARTED"
    assert data["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Queue-B validations corners
# --------------------------------------------------------------------------- #
def test_pledge_below_tier_min_on_live_campaign(api):
    """PRD §3.5: "Then the pledge amount is checked: pledge_amount_cents must be at least the
    tier's price_cents, failing with ERR_PLEDGE_BELOW_TIER_MIN (HTTP 422) when it is below."

    Design: Corner/validations/pledge_below_tier_min_on_live_campaign_returns_error
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(backer["id"], tier["id"], campaign["version"],
                                                   pledge_amount_cents=4999), backer_headers)
    validate_error(resp, ApiErrorId.ERR_PLEDGE_BELOW_TIER_MIN.value)


def test_addon_from_other_campaign_returns_currency_mismatch(api):
    """PRD §3.5: "The add-on must belong to the same campaign as the pledge; an add-on from
    another campaign is rejected with ERR_CURRENCY_MISMATCH (HTTP 422), since cross-campaign
    means cross-currency."

    Design: Corner/validations/addon_from_other_campaign_returns_currency_mismatch
    """
    set_clock(api, "2026-06-01T00:00:00.000Z")
    creator = register_creator(api)
    c_headers = make_creator_headers(creator["id"])
    # K1 LIVE with a pledge
    k1 = validate_success(api.create_campaign(
        create_campaign_payload(creator["id"], title="K1", funding_goal_cents=1000,
                                funding_model="FLEXIBLE", deadline_utc="2026-06-20T00:00:00.000Z"),
        c_headers), 201)
    t1 = validate_success(api.create_tier(k1["id"], create_tier_payload(title="T1"), c_headers), 201)
    k1 = validate_success(api.launch_campaign(k1["id"], c_headers), 200)
    # K2 (same creator, non-overlapping window) owns the add-on
    k2 = validate_success(api.create_campaign(
        create_campaign_payload(creator["id"], title="K2", funding_goal_cents=1000,
                                funding_model="FLEXIBLE", deadline_utc="2026-08-01T00:00:00.000Z"),
        c_headers), 201)
    k2_addon = validate_success(api.create_addon_product(
        k2["id"], create_addon_product_payload(title="OtherPin", price_cents=1000,
                                                limit_quantity=10, weight_grams=100), c_headers), 201)
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    pledge = validate_success(api.create_pledge(
        k1["id"], create_pledge_payload(backer["id"], t1["id"], k1["version"]), backer_headers), 201)
    resp = api.attach_addon(pledge["id"], attach_addon_payload(k2_addon["id"], 1), backer_headers)
    validate_error(resp, ApiErrorId.ERR_CURRENCY_MISMATCH.value)


# --------------------------------------------------------------------------- #
# cross_cutting_complexity_layers / OCC (queue B)
# --------------------------------------------------------------------------- #
def test_occ_stale_campaign_version_rejected(api):
    """PRD §2.7: "The server compares expected_campaign_version against the campaign's current
    version. If they do not match — because another pledge create, a stretch-goal unlock, or
    an inventory recompute has advanced the campaign's version since the client last read it —
    the create is rejected with ERR_STALE_CAMPAIGN_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_campaign_version_on_pledge_create_returns_stale
    """
    creator, campaign, tier = create_live_campaign_with_tier(api)
    launch_version = campaign["version"]
    b1 = register_backer(api, email="b1@x.com", display_name="B1")
    # first pledge advances campaign.version past launch_version
    create_pledge(api, campaign, b1, tier, launch_version, pledge_amount_cents=5000)
    b2 = register_backer(api, email="b2@x.com", display_name="B2")
    b2_headers = make_backer_headers(b2["id"])
    # second create still carries the stale launch_version
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(b2["id"], tier["id"], launch_version,
                                                   pledge_amount_cents=5000), b2_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_CAMPAIGN_VERSION.value)


def test_occ_correct_version_succeeds_and_increments(api):
    """PRD §2.7: "The create request must carry a field named expected_campaign_version whose
    value is the version of the target campaign as the client last observed it".
    PRD §3.5: "Creating the pledge then recomputes the tier's claimed_quantity ..., recomputes
    the campaign's projected raise committed_amount_cents ..., and increments the campaign's
    version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    creator, campaign, tier = create_live_campaign_with_tier(api)
    launch_version = campaign["version"]
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    resp = api.create_pledge(campaign["id"],
                             create_pledge_payload(backer["id"], tier["id"], launch_version,
                                                   pledge_amount_cents=5000), backer_headers)
    validate_success(resp, 201)
    camp_after = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    assert camp_after["version"] == launch_version + 1, (
        f"Expected version {launch_version + 1}, got {camp_after['version']}"
    )
