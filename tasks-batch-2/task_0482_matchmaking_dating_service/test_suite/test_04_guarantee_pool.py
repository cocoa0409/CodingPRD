"""The matches-guarantee credit pool: committed vs forecast, consumption, refund."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_member_headers,
    ApiErrorId,
    fixtures as fx,
)
import test_helpers.factories as f

ADMIN = TEST_USERS["billing_admin_headers"]
SCREENING = TEST_USERS["screening_officer_headers"]
MATCHMAKER = TEST_USERS["matchmaker_headers"]


def _make_active_counterpart(plan_id, email):
    member, _ = fx.create_active_member(plan_id, email, gender="FEMALE",
                                        pref_overrides={"seeking_gender": "MALE"})
    return member


def test_guarantee_committed_vs_forecast_diverge(api):
    """PRD §3.4: "guarantee_remaining_committed` is the snapshotted `guaranteed_introductions` minus that committed total, floored at 0." and
    "guarantee_remaining_forecast` is the snapshotted `guaranteed_introductions` minus that forecast total, floored at 0." PRD §3.4 worked example: "with a guarantee of
    eight, three mutual introductions consuming three credits and two still-open
    suggested introductions consuming two more, the committed remaining is five while
    the forecast remaining is three."

    Design: Difficulty/dual_variant_calc/guarantee_committed_vs_forecast_diverge
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="PLUS", guaranteed_introductions=8, priority_match_enabled=False)
    member_a, _ = fx.create_active_member(plan["id"], "a@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    a_id = member_a["id"]

    # Three counterparts mutual-accepted -> 3 committed credits.
    for i in range(3):
        b = _make_active_counterpart(plan["id"], f"b{i}@x.com")
        intro = fx.suggest_introduction(a_id, b["id"])
        intro = fx.respond(intro["id"], a_id, "ACCEPTED", intro["version"])
        fx.respond(intro["id"], b["id"], "ACCEPTED", intro["version"])

    # Two more counterparts: suggested only (still open) -> 2 forecast credits.
    for i in range(2):
        b = _make_active_counterpart(plan["id"], f"bs{i}@x.com")
        fx.suggest_introduction(a_id, b["id"])

    member_a_final = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a_final["guarantee_remaining_committed"] == 5, (
        f"committed should be 8-3=5, got {member_a_final['guarantee_remaining_committed']}"
    )
    assert member_a_final["guarantee_remaining_forecast"] == 3, (
        f"forecast should be 8-3-2=3, got {member_a_final['guarantee_remaining_forecast']}"
    )


def test_guarantee_forecast_drops_while_committed_holds_on_open_suggestions(api):
    """PRD §3.4: "The committed-consumed total is the sum of `credits_consumed` over
    introductions where the member is member A and whose status is `MUTUAL` (or closed
    after having been mutual)".
    PRD §3.4: "The forecast-consumed total is the sum of `credits_consumed` over
    introductions where the member is member A and whose status is `SUGGESTED`,
    `ONE_SIDED`, or `MUTUAL`". Two open SUGGESTED introductions reduce forecast (8-2=6)
    but leave committed full (8) because none reached MUTUAL.

    Design: Difficulty/dual_variant_calc/guarantee_committed_vs_forecast_diverge
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="PLUS", guaranteed_introductions=8, priority_match_enabled=False)
    member_a, _ = fx.create_active_member(plan["id"], "div_a@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    a_id = member_a["id"]
    for i in range(2):
        b = _make_active_counterpart(plan["id"], f"div_b{i}@x.com")
        fx.suggest_introduction(a_id, b["id"])  # left SUGGESTED

    member_a_final = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a_final["guarantee_remaining_committed"] == 8, (
        f"no MUTUAL yet, committed stays 8, got {member_a_final['guarantee_remaining_committed']}"
    )
    assert member_a_final["guarantee_remaining_forecast"] == 6, (
        f"two open suggestions reduce forecast to 6, got {member_a_final['guarantee_remaining_forecast']}"
    )


def test_guarantee_consume_min_cap_priority_second_suggestion_capped(api):
    """PRD §3.4: "when member A's plan has priority_match_enabled, the cost is 2 ...
    The amount actually consumed is the smaller of that base cost and member A's
    current guarantee_remaining_forecast, so a suggestion never over-draws the pool".
    PRD §3.4: "with one forecast credit remaining on a priority plan it consumes 1
    (capped) and leaves 0".

    Design: Difficulty/combinatorial_formula/guarantee_consume_min_cap_tier_promo_nonlinear
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="ELITE", guaranteed_introductions=3, priority_match_enabled=True)
    member_a, _ = fx.create_active_member(plan["id"], "p@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    a_id = member_a["id"]

    q1 = _make_active_counterpart(plan["id"], "q1@x.com")
    intro1 = fx.suggest_introduction(a_id, q1["id"])
    assert intro1["credits_consumed"] == 2, (
        f"first priority suggestion consumes min(2,3)=2, got {intro1['credits_consumed']}"
    )

    q2 = _make_active_counterpart(plan["id"], "q2@x.com")
    a_ver = fx.current_version(a_id)
    resp = api.create_introduction(
        f.create_introduction_payload(a_id, q2["id"], a_ver), MATCHMAKER
    )
    intro2 = validate_success(resp, 201)
    assert intro2["credits_consumed"] == 1, (
        f"second priority suggestion is capped to min(2,1)=1, got {intro2['credits_consumed']}"
    )

    member_a_final = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a_final["guarantee_remaining_forecast"] == 0, (
        f"forecast should be floored at 0 after the capped consume, got {member_a_final['guarantee_remaining_forecast']}"
    )


def test_guarantee_consume_winback_promo_consumes_zero(api):
    """PRD §3.4: "When the introduction's `win_back_promo` flag is set, the cost is 0 (a
    re-engagement promotion)." and "a win-back suggestion consumes 0 regardless." This
    is the first conditional branch of the three-input cost formula.

    Design: Difficulty/combinatorial_formula/guarantee_consume_min_cap_tier_promo_nonlinear
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="ELITE", guaranteed_introductions=3, priority_match_enabled=True)
    member_a, _ = fx.create_active_member(plan["id"], "wb_a@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    a_id = member_a["id"]
    b = _make_active_counterpart(plan["id"], "wb_b@x.com")

    a_ver = fx.current_version(a_id)
    resp = api.create_introduction(
        f.create_introduction_payload(a_id, b["id"], a_ver, win_back_promo=True), MATCHMAKER
    )
    intro = validate_success(resp, 201)
    assert intro["credits_consumed"] == 0, (
        f"win-back promo consumes 0 even on a priority plan, got {intro['credits_consumed']}"
    )
    member_a_final = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a_final["guarantee_remaining_forecast"] == 3, (
        f"win-back leaves forecast untouched at 3, got {member_a_final['guarantee_remaining_forecast']}"
    )


def test_guarantee_exhausted_blocks_suggestion(api):
    """PRD §3.4: "A guarantee guard sits above this: unless the introduction is a win-back promotion (cost 0), the introduction's credit cost must not exceed member A's `guarantee_remaining_forecast`. A suggestion whose cost would exceed the forecast pool is rejected with `ERR_GUARANTEE_EXHAUSTED` and HTTP status 402."

    Design: Corner/validations/guarantee_exhausted_blocks_suggestion
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="BASIC", monthly_fee_cents=9000, guaranteed_introductions=1)
    member_a, _ = fx.create_active_member(plan["id"], "ca9@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    a_id = member_a["id"]
    member_b = _make_active_counterpart(plan["id"], "cb9@x.com")
    member_c = _make_active_counterpart(plan["id"], "cc9@x.com")

    # The single guaranteed credit is committed by a MUTUAL introduction (forecast 0).
    intro = fx.suggest_introduction(a_id, member_b["id"])
    intro = fx.respond(intro["id"], a_id, "ACCEPTED", intro["version"])
    fx.respond(intro["id"], member_b["id"], "ACCEPTED", intro["version"])

    a_ver = fx.current_version(a_id)
    resp = api.create_introduction(
        f.create_introduction_payload(a_id, member_c["id"], a_ver), MATCHMAKER
    )
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_EXHAUSTED.value, 402)


def test_decline_refunds_guarantee_pool_conserved(api):
    """PRD §3.5: "A decline by either party, from `SUGGESTED` or `ONE_SIDED`, records that party's response as `DECLINED` and moves the introduction to `DECLINED`. A decline refunds this introduction's `credits_consumed` back to member A's guarantee — the forward consumption at suggestion time is reversed by a compensating refund, so member A's `guarantee_remaining_forecast` is restored."

    Design: Difficulty/compensating_invariant/decline_refunds_guarantee_pool_conserved
    """
    ctx = fx.setup_suggested_introduction(plan_overrides={"guaranteed_introductions": 8},
                                          a_email="a13@x.com", b_email="b17@x.com")
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    intro = ctx["introduction"]

    # Before decline: one credit consumed, forecast should be 7.
    member_a_mid = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a_mid["guarantee_remaining_forecast"] == 7, (
        f"after suggest, forecast 8-1=7, got {member_a_mid['guarantee_remaining_forecast']}"
    )

    fx.respond(intro["id"], b_id, "DECLINED", intro["version"])

    member_a = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a["guarantee_remaining_forecast"] == 8, (
        f"decline must restore forecast to 8, got {member_a['guarantee_remaining_forecast']}"
    )
    assert member_a["guarantee_remaining_committed"] == 8, (
        f"declined intro never committed; committed stays 8, got {member_a['guarantee_remaining_committed']}"
    )


def test_decline_moves_introduction_to_declined_and_nets_pool_to_zero(api):
    """PRD §3.5: "A decline by either party, from `SUGGESTED` or `ONE_SIDED`, records that party's response as `DECLINED` and moves the introduction to `DECLINED`. A decline refunds this introduction's `credits_consumed` back to member A's guarantee". The
    suggest (-1) and decline (+1) net to zero change on the forecast pool.

    Design: Difficulty/compensating_invariant/decline_refunds_guarantee_pool_conserved
    """
    ctx = fx.setup_suggested_introduction(plan_overrides={"guaranteed_introductions": 8},
                                          a_email="nz_a@x.com", b_email="nz_b@x.com")
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    intro = ctx["introduction"]

    declined = fx.respond(intro["id"], b_id, "DECLINED", intro["version"])
    assert declined["status"] == "DECLINED", f"expected DECLINED, got {declined['status']}"

    member_a = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a["guarantee_remaining_forecast"] == 8, (
        f"net pool change across suggest+decline is zero (8), got "
        f"{member_a['guarantee_remaining_forecast']}"
    )


def test_membership_fulfilled_bubble_up_on_guarantee_met(api):
    """PRD §3.5: "Reaching `MUTUAL` commits this introduction's `credits_consumed` against member A's membership; member A's `credits_consumed_committed` is recomputed, and if it reaches the snapshotted `guaranteed_introductions` the membership bubbles up to `FULFILLED` (with `guarantee_met` set true)."

    Design: Corner/state_machines/membership_fulfilled_bubble_up_on_guarantee_met
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="BASIC", monthly_fee_cents=9000, guaranteed_introductions=1)
    member_a, membership_a = fx.create_active_member(plan["id"], "ca7@x.com", gender="MALE",
                                                     pref_overrides={"seeking_gender": "FEMALE"})
    a_id = member_a["id"]
    member_b = _make_active_counterpart(plan["id"], "cb7@x.com")

    intro = fx.suggest_introduction(a_id, member_b["id"])
    intro = fx.respond(intro["id"], a_id, "ACCEPTED", intro["version"])
    fx.respond(intro["id"], member_b["id"], "ACCEPTED", intro["version"])

    ms = validate_success(api.get_membership(membership_a["id"], ADMIN), 200)
    assert ms["status"] == "FULFILLED", (
        f"guarantee met (1 mutual / guarantee 1) must FULFILL membership, got {ms['status']}"
    )
    assert ms["guarantee_met"] is True, f"guarantee_met must be true, got {ms['guarantee_met']}"
