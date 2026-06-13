"""Hour logging, verification, reliability scoring, and recognition milestones:
provisional vs verified divergence, round-per-line-item-then-sum totals, the
non-linear reliability formula, the BRONZE@25 inclusive boundary, the verify->tier
bubble-up, the HOURS_LOGGED<->ATTENDED revision cycle, and reliability flooring.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, boundary_precision_check,
transitive_cascade, non_linear_state_machine.
Queue B (Corner): calculations.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import (
    create_organization, create_volunteer, create_opportunity, create_shift,
    publish_opportunity, set_clock, get_shift, get_volunteer,
    create_signup, confirm_signup, create_confirmed_signup, create_attended_signup,
    create_logged_signup, create_verified_signup,
    setup_volunteer_with_verified_hours, setup_signup_ready,
)
from test_helpers.test_users import TEST_USERS, make_volunteer_headers

COORD = TEST_USERS["shift_coordinator_headers"]


def test_provisional_and_verified_hours_diverge_on_same_signup(api):
    """PRD §3.5: "it takes the difference between the shift's `ends_at` and `starts_at`
    in seconds, divides by 3,600 to obtain hours, and rounds that half up to two
    decimal places."
    PRD §3.6: "Verification sets the signup's `verified_hours` to the smaller of the
    volunteer's `logged_hours` and the signup's `provisional_hours` — that is, the
    logged figure capped at the scheduled duration — rounded half up to two decimal
    places."

    Design: Difficulty/dual_variant_calc/provisional_vs_verified_hours_diverge_on_signup
    """
    org, vol, opp, shift = setup_signup_ready(
        capacity=1, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T12:30:00Z")
    su = create_attended_signup(shift, vol["id"], "2026-07-01T09:30:00Z")
    assert su["provisional_hours"] == 3.50, f"expected provisional 3.50, got {su['provisional_hours']}"

    validate_success(api.log_hours_signup(su["id"], {"logged_hours": 3.0},
                                          make_volunteer_headers(vol["id"])))
    verified = validate_success(api.verify_hours_signup(su["id"], COORD))
    assert verified["verified_hours"] == 3.00, \
        f"expected verified 3.00 (logged 3.0 < scheduled 3.5), got {verified['verified_hours']}"
    assert verified["provisional_hours"] != verified["verified_hours"], \
        "provisional and verified must diverge on the same signup"


def test_verified_equals_provisional_when_cap_not_binding(api):
    """PRD §3.6: "Verification sets the signup's `verified_hours` to the smaller of the
    volunteer's `logged_hours` and the signup's `provisional_hours` — that is, the
    logged figure capped at the scheduled duration — rounded half up to two decimal
    places."

    Design: Difficulty/dual_variant_calc/provisional_vs_verified_hours_diverge_on_signup
    """
    # Logged hours == full scheduled duration -> cap does not bind -> verified == provisional.
    org, vol, opp, shift = setup_signup_ready(
        capacity=1, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T12:30:00Z")
    su = create_attended_signup(shift, vol["id"], "2026-07-01T09:30:00Z")
    assert su["provisional_hours"] == 3.50
    validate_success(api.log_hours_signup(su["id"], {"logged_hours": 3.5},
                                          make_volunteer_headers(vol["id"])))
    verified = validate_success(api.verify_hours_signup(su["id"], COORD))
    assert verified["verified_hours"] == 3.50, \
        f"with logged==scheduled the cap does not bind; expected 3.50, got {verified['verified_hours']}"


def test_provisional_hours_rounds_fractional_duration(api):
    """PRD §3.5: "it takes the difference between the shift's `ends_at` and `starts_at`
    in seconds, divides by 3,600 to obtain hours, and rounds that half up to two
    decimal places."

    Design: Corner/calculations/provisional_hours_rounds_fractional_duration
    """
    # 09:00:00 -> 11:30:45 = 2h 30m 45s = 9045s / 3600 = 2.5125h -> 2.51 (round half up, 2dp).
    org, vol, opp, shift = setup_signup_ready(
        capacity=2, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T11:30:45Z")
    su = create_attended_signup(shift, vol["id"], "2026-07-01T12:00:00Z")
    assert su["provisional_hours"] == 2.51, \
        f"expected provisional 2.51 from 2.5125h, got {su['provisional_hours']}"


def test_milestone_total_rounds_per_line_then_sums(api):
    """PRD §3.6: "each contributing signup's `verified_hours` is rounded half up to two
    decimal places, those per-line values are summed, and the sum is itself rounded
    half up to two decimal places."

    Design: Difficulty/combinatorial_formula/milestone_round_per_line_then_sum_pins_cents
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:30:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-01T13:00:00Z", "2026-07-01T15:15:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    va = create_verified_signup(sa, vol["id"], 3.5, "2026-07-01T16:00:00Z")
    vb = create_verified_signup(sb, vol["id"], 2.25, "2026-07-01T16:00:00Z")
    assert va["verified_hours"] == 3.50, f"shift A verified expected 3.50, got {va['verified_hours']}"
    assert vb["verified_hours"] == 2.25, f"shift B verified expected 2.25, got {vb['verified_hours']}"

    vol_after = get_volunteer(vol["id"], headers=COORD)
    assert vol_after["total_verified_hours"] == 5.75, \
        f"expected total_verified_hours 5.75, got {vol_after['total_verified_hours']}"


def test_milestone_total_round_per_line_distinct_pair(api):
    """PRD §3.6: "each contributing signup's `verified_hours` is rounded half up to two
    decimal places, those per-line values are summed, and the sum is itself rounded
    half up to two decimal places."

    Design: Difficulty/combinatorial_formula/milestone_round_per_line_then_sum_pins_cents
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    # Two non-overlapping shifts: 1.25h and 2.50h -> per-line 1.25 + 2.50 = 3.75.
    sa = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T10:15:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-01T11:00:00Z", "2026-07-01T13:30:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    va = create_verified_signup(sa, vol["id"], 1.25, "2026-07-01T14:00:00Z")
    vb = create_verified_signup(sb, vol["id"], 2.5, "2026-07-01T14:00:00Z")
    assert va["verified_hours"] == 1.25
    assert vb["verified_hours"] == 2.50
    vol_after = get_volunteer(vol["id"], headers=COORD)
    assert vol_after["total_verified_hours"] == 3.75, \
        f"expected total 3.75, got {vol_after['total_verified_hours']}"


def test_reliability_score_ratio_plus_penalty_nonlinear(api):
    """PRD §3.5: "take the attendance ratio as kept divided by the sum of kept and
    broken, compute a raw value of 100 multiplied by that ratio minus a penalty of 8
    points for each no-show in the broken count, round that raw value half up to a
    whole number, and then clamp the result to lie between 0 and 100 inclusive."

    Design: Difficulty/combinatorial_formula/reliability_score_ratio_plus_penalty_nonlinear
    """
    org = create_organization(headers=COORD, no_show_strike_limit=5)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-02T09:00:00Z", "2026-07-02T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    # One HOURS_VERIFIED (kept=1).
    create_verified_signup(sa, vol["id"], 3.0, "2026-07-01T13:00:00Z")
    # One NO_SHOW (broken=1): confirm then mark-no-show.
    su_b = create_confirmed_signup(sb, vol["id"])
    validate_success(api.mark_no_show_signup(su_b["id"], COORD))

    after = get_volunteer(vol["id"], headers=COORD)
    # raw = 100*(1/2) - 8*1 = 42.
    assert after["reliability_score"] == 42, \
        f"expected reliability 42 (=round(100*1/2)-8), got {after['reliability_score']}"
    assert after["lifetime_no_show_count"] == 1


def test_reliability_score_two_kept_one_broken(api):
    """PRD §3.5: "take the attendance ratio as kept divided by the sum of kept and
    broken, compute a raw value of 100 multiplied by that ratio minus a penalty of 8
    points for each no-show in the broken count, round that raw value half up to a
    whole number, and then clamp the result to lie between 0 and 100 inclusive."

    Design: Difficulty/combinatorial_formula/reliability_score_ratio_plus_penalty_nonlinear
    """
    org = create_organization(headers=COORD, no_show_strike_limit=5)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    s1 = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    s2 = create_shift(opp["id"], "2026-07-02T09:00:00Z", "2026-07-02T12:00:00Z", 5, headers=COORD)
    s3 = create_shift(opp["id"], "2026-07-03T09:00:00Z", "2026-07-03T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    # Two HOURS_VERIFIED (kept=2), one NO_SHOW (broken=1).
    create_verified_signup(s1, vol["id"], 3.0, "2026-07-04T00:00:00Z")
    create_verified_signup(s2, vol["id"], 3.0, "2026-07-04T00:00:00Z")
    su3 = create_confirmed_signup(s3, vol["id"])
    validate_success(api.mark_no_show_signup(su3["id"], COORD))

    after = get_volunteer(vol["id"], headers=COORD)
    # raw = 100*(2/3) - 8*1 = 66.666... - 8 = 58.67 -> round half up = 59.
    assert after["reliability_score"] == 59, \
        f"expected reliability 59 (=round(100*2/3)-8), got {after['reliability_score']}"
    assert after["lifetime_no_show_count"] == 1


def test_reliability_score_floored_at_zero_on_all_no_shows(api):
    """PRD §3.5: "round that raw value half up to a whole number, and then clamp the
    result to lie between 0 and 100 inclusive."

    Design: Corner/calculations/reliability_score_zero_floor_on_all_no_shows
    """
    org = create_organization(headers=COORD, no_show_strike_limit=9, reliability_suspension_threshold=0)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-02T09:00:00Z", "2026-07-02T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    su_a = create_confirmed_signup(sa, vol["id"])
    su_b = create_confirmed_signup(sb, vol["id"])
    validate_success(api.mark_no_show_signup(su_a["id"], COORD))
    validate_success(api.mark_no_show_signup(su_b["id"], COORD))

    after = get_volunteer(vol["id"], headers=COORD)
    # raw = 100*(0/2) - 8*2 = -16, clamped to 0.
    assert after["reliability_score"] == 0, \
        f"expected reliability clamped to 0, got {after['reliability_score']}"
    assert after["lifetime_no_show_count"] == 2


def test_milestone_tier_bronze_at_inclusive_25(api):
    """PRD §3.6: "Because the bounds are inclusive, a total of exactly 25.00 hours
    earns `BRONZE` while 24.99 remains `NONE`."

    Design: Difficulty/boundary_precision_check/milestone_tier_inclusive_lower_bound_at_25
    """
    # 5 verified shifts of 5h each -> exactly 25.00 verified hours.
    org, vol, opp, shifts, signups = setup_volunteer_with_verified_hours(
        num_shifts=5, hours_each=5.0, org_overrides={"no_show_strike_limit": 9})
    after = get_volunteer(vol["id"], headers=COORD)
    assert after["total_verified_hours"] == 25.00, \
        f"expected total 25.00, got {after['total_verified_hours']}"
    assert after["milestone_tier"] == "BRONZE", \
        f"expected BRONZE at exactly 25.00, got {after['milestone_tier']}"


def test_milestone_tier_none_just_below_25(api):
    """PRD §3.6: "Because the bounds are inclusive, a total of exactly 25.00 hours earns
    `BRONZE` while 24.99 remains `NONE`."

    Design: Difficulty/boundary_precision_check/milestone_tier_inclusive_lower_bound_at_25
    """
    org = create_organization(headers=COORD, no_show_strike_limit=9)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    # Four 5h shifts (20.00) plus one 4.99h shift (4h 59m 24s) -> total 24.99.
    shift_specs = [
        ("2026-07-01T08:00:00Z", "2026-07-01T13:00:00Z", 5.0),
        ("2026-07-02T08:00:00Z", "2026-07-02T13:00:00Z", 5.0),
        ("2026-07-03T08:00:00Z", "2026-07-03T13:00:00Z", 5.0),
        ("2026-07-04T08:00:00Z", "2026-07-04T13:00:00Z", 5.0),
        ("2026-07-05T08:00:00Z", "2026-07-05T12:59:24Z", 4.99),
    ]
    shifts = [create_shift(opp["id"], s, e, 9, headers=COORD) for s, e, _ in shift_specs]
    publish_opportunity(opp["id"], headers=COORD)
    for (s, e, hrs), sh in zip(shift_specs, shifts):
        create_verified_signup(sh, vol["id"], hrs, "2026-07-06T00:00:00Z")

    after = get_volunteer(vol["id"], headers=COORD)
    assert after["total_verified_hours"] == 24.99, \
        f"expected total 24.99, got {after['total_verified_hours']}"
    assert after["milestone_tier"] == "NONE", \
        f"24.99 is below the inclusive 25 bound; expected NONE, got {after['milestone_tier']}"


def test_verify_bubbles_hours_into_milestone_tier(api):
    """PRD §3.6: "Verification triggers the recognition chain on the volunteer. First,
    the volunteer's `total_verified_hours` is recomputed from every signup of theirs in
    `HOURS_VERIFIED`, taken in order of the signup's creation timestamp."
    PRD §3.6: "otherwise `BRONZE` at no fewer than 25 hours, otherwise `NONE`."

    Design: Difficulty/transitive_cascade/signup_verify_bubbles_hours_to_tier_depth2
    """
    org = create_organization(headers=COORD, no_show_strike_limit=9)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shifts = []
    for i in range(5):
        day = 1 + i
        shifts.append(create_shift(
            opp["id"], f"2026-07-{day:02d}T08:00:00Z", f"2026-07-{day:02d}T13:00:00Z", 9,
            headers=COORD))
    publish_opportunity(opp["id"], headers=COORD)

    # First 4 verified (=20.00h, still NONE), 5th attended+logged but pending verify.
    signups = []
    for sh in shifts:
        fresh = get_shift(sh["id"], headers=COORD)
        su = create_signup(fresh["id"], vol["id"], fresh["version"])
        confirm_signup(su["id"], vol["id"])
        signups.append(su)
    set_clock("2026-07-06T00:00:00Z", headers=COORD)
    for su in signups:
        validate_success(api.check_in_signup(su["id"], COORD))
        validate_success(api.log_hours_signup(su["id"], {"logged_hours": 5.0},
                                              make_volunteer_headers(vol["id"])))
    for su in signups[:4]:
        validate_success(api.verify_hours_signup(su["id"], COORD))

    before = get_volunteer(vol["id"], headers=COORD)
    assert before["total_verified_hours"] == 20.00, \
        f"before trigger expected 20.00, got {before['total_verified_hours']}"
    assert before["milestone_tier"] == "NONE", \
        f"before trigger expected NONE, got {before['milestone_tier']}"

    validate_success(api.verify_hours_signup(signups[4]["id"], COORD))
    after = get_volunteer(vol["id"], headers=COORD)
    assert after["total_verified_hours"] == 25.00, \
        f"after trigger expected 25.00, got {after['total_verified_hours']}"
    assert after["milestone_tier"] == "BRONZE", \
        f"verify must bubble hours into BRONZE tier, got {after['milestone_tier']}"


def test_verify_below_breakpoint_leaves_tier_none(api):
    """PRD §3.6: "Verification triggers the recognition chain on the volunteer. First,
    the volunteer's `total_verified_hours` is recomputed from every signup of theirs in
    `HOURS_VERIFIED`, taken in order of the signup's creation timestamp."
    PRD §3.6: "otherwise `BRONZE` at no fewer than 25 hours, otherwise `NONE`."

    Design: Difficulty/transitive_cascade/signup_verify_bubbles_hours_to_tier_depth2
    """
    # A single 5h verified signup -> total 5.00 < 25, so the tier hop does not fire.
    org, vol, opp, shift = setup_signup_ready(
        capacity=1, org_overrides={"no_show_strike_limit": 9},
        starts_at="2026-07-01T08:00:00Z", ends_at="2026-07-01T13:00:00Z")
    create_verified_signup(shift, vol["id"], 5.0, "2026-07-02T00:00:00Z")
    after = get_volunteer(vol["id"], headers=COORD)
    assert after["total_verified_hours"] == 5.00, \
        f"expected total 5.00, got {after['total_verified_hours']}"
    assert after["milestone_tier"] == "NONE", \
        f"5.00 hours is below the BRONZE breakpoint; tier must stay NONE, got {after['milestone_tier']}"


def test_signup_hours_revision_cycle_logged_to_attended_and_back(api):
    """PRD §3.6: "Should the coordinator instead reject the logged hours, the signup
    moves from `HOURS_LOGGED` back to `ATTENDED`, clearing `logged_hours` back to null
    so the volunteer can re-log."

    Design: Difficulty/non_linear_state_machine/signup_hours_revision_cycle_logged_to_attended
    """
    org, vol, opp, shift = setup_signup_ready(
        capacity=1, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T12:00:00Z")
    su = create_logged_signup(shift, vol["id"], 2.0, "2026-07-01T12:30:00Z")
    assert su["status"] == "HOURS_LOGGED"

    rejected = validate_success(api.reject_hours_signup(su["id"], COORD))
    assert rejected["status"] == "ATTENDED", \
        f"reject-hours must return to ATTENDED, got {rejected['status']}"
    assert rejected["logged_hours"] is None, "reject-hours clears logged_hours to null"

    relogged = validate_success(api.log_hours_signup(su["id"], {"logged_hours": 1.5},
                                                     make_volunteer_headers(vol["id"])))
    assert relogged["status"] == "HOURS_LOGGED", \
        f"re-log must return to HOURS_LOGGED, got {relogged['status']}"
    assert relogged["logged_hours"] == 1.5


def test_reject_hours_requires_hours_logged_state(api):
    """PRD §3.6: "rejection likewise requires the signup to currently be `HOURS_LOGGED`
    (else `ERR_SIGNUP_NOT_LOGGED`)."

    Design: Difficulty/non_linear_state_machine/signup_hours_revision_cycle_logged_to_attended
    """
    # After reject-hours the signup is ATTENDED (not HOURS_LOGGED); a second reject must fail.
    org, vol, opp, shift = setup_signup_ready(
        capacity=1, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T12:00:00Z")
    su = create_logged_signup(shift, vol["id"], 2.0, "2026-07-01T12:30:00Z")
    validate_success(api.reject_hours_signup(su["id"], COORD))  # -> ATTENDED
    resp = api.reject_hours_signup(su["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_SIGNUP_NOT_LOGGED.value)
