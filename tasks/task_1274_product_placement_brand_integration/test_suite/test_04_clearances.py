"""Competitive clearance: policy dual-variant, proximity windows, exclusivity,
release semantics, and brand-state gating (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_brand,
    create_clearance_payload,
    create_episode,
    create_series,
    decide_clearance_payload,
    find_clearance,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CLEARANCE = TEST_USERS["clearance_headers"]
CLEARANCE_ALT = TEST_USERS["clearance_alt_headers"]


def _request_clearance(api, episode_id, brand_id):
    ep = get_success_data(api.get_episode(episode_id, MANAGER))
    return get_success_data(
        api.create_clearance(
            episode_id, create_clearance_payload(brand_id, ep["version"]), MANAGER
        )
    )


def test_clearance_policy_strict_vs_standard_day7(api):
    """PRD §3.3: "under `STRICT` the window includes a difference of seven days
    (seven days or fewer counts as a conflict), while under `STANDARD` the
    window is strictly less than seven days, so a pair exactly seven days apart
    conflicts under `STRICT` but not under `STANDARD`."
    PRD §3.3: "Under a `STRICT` series policy the deny threshold is 40, so a
    pure proximity hit already refuses the grant; under `STANDARD` the
    threshold is 60, so identical data yields a score of 0 and the grant
    succeeds."

    Design: Difficulty/dual_variant_calc/clearance_policy_strict_vs_standard_day7
    """
    brand = create_brand(name="Snackly", category="FOOD")
    std_series = create_series(name="Standard Show", clearance_policy="STANDARD")
    strict_series = create_series(name="Strict Show", clearance_policy="STRICT")
    ep_s1 = create_episode(std_series["id"], episode_number=1, air_date="2026-06-01T20:00:00Z")
    ep_t1 = create_episode(strict_series["id"], episode_number=1, air_date="2026-06-08T20:00:00Z")
    ep_s2 = create_episode(std_series["id"], episode_number=2, air_date="2026-06-08T20:00:00Z")

    cl_s1 = _request_clearance(api, ep_s1["id"], brand["id"])
    cl_s1 = get_success_data(api.decide_clearance(cl_s1["id"], decide_clearance_payload("GRANT"), CLEARANCE))
    assert cl_s1["status"] == "GRANTED"

    cl_t1 = _request_clearance(api, ep_t1["id"], brand["id"])
    cl_s2 = _request_clearance(api, ep_s2["id"], brand["id"])

    # STRICT: |7 days| <= 7 -> proximity hit -> score 40 >= threshold 40 -> reject
    resp_strict = api.decide_clearance(cl_t1["id"], decide_clearance_payload("GRANT"), CLEARANCE)
    validate_error(resp_strict, ApiErrorId.ERR_AIRDATE_PROXIMITY_CONFLICT)

    # STANDARD: |7 days| < 7 false -> score 0 < 60 -> grant succeeds
    cl_s2_after = get_success_data(
        api.decide_clearance(cl_s2["id"], decide_clearance_payload("GRANT"), CLEARANCE)
    )
    assert cl_s2_after["status"] == "GRANTED", (
        f"STANDARD day-7 must grant, got {cl_s2_after['status']}"
    )
    assert cl_s2_after["risk_score"] == 0, (
        f"STANDARD day-7 risk score must be 0, got {cl_s2_after['risk_score']}"
    )

    cl_t1_after = find_clearance(ep_t1["id"], cl_t1["id"])
    assert cl_t1_after["status"] == "REQUESTED", (
        f"failed GRANT must leave the clearance REQUESTED, got {cl_t1_after['status']}"
    )


def test_clearance_policy_strict_day7_score_vs_standard_zero(api):
    """PRD §3.3: "The proximity signal contributes 40 points when any
    same-category `GRANTED` clearance on another episode falls inside the
    policy window just described". PRD §3.3: "under `STANDARD` the threshold is
    60, so identical data yields a score of 0 and the grant succeeds."

    Design: Difficulty/dual_variant_calc/clearance_policy_strict_vs_standard_day7
    """
    brand = create_brand(name="Snackly", category="FOOD")
    std_series = create_series(name="Standard Show", clearance_policy="STANDARD")
    ep_a = create_episode(std_series["id"], episode_number=1, air_date="2026-06-01T20:00:00Z")
    ep_b = create_episode(std_series["id"], episode_number=2, air_date="2026-06-08T20:00:00Z")

    cl_a = _request_clearance(api, ep_a["id"], brand["id"])
    get_success_data(api.decide_clearance(cl_a["id"], decide_clearance_payload("GRANT"), CLEARANCE))

    cl_b = _request_clearance(api, ep_b["id"], brand["id"])
    granted = get_success_data(
        api.decide_clearance(cl_b["id"], decide_clearance_payload("GRANT"), CLEARANCE)
    )
    assert granted["status"] == "GRANTED"
    assert granted["risk_score"] == 0, (
        f"day-7 pair under STANDARD yields no proximity hit; risk_score must be 0, got {granted['risk_score']}"
    )


def test_airdate_strict_window_day7_conflict_day8_ok(api):
    """PRD §3.3: "a grant is rejected with `ERR_AIRDATE_PROXIMITY_CONFLICT`
    (HTTP 409) when a same-category `GRANTED` clearance exists on a different
    episode — of any series — whose `air_date` differs from this episode's by a
    number of days inside the policy window of this episode's series; under
    `STRICT` the window includes a difference of seven days (seven days or
    fewer counts as a conflict)".

    Design: Difficulty/resource_temporal_overlap/airdate_strict_window_day7_conflict_day8_ok
    """
    brand = create_brand(name="Snackly", category="FOOD")
    strict_series = create_series(name="Strict Show", clearance_policy="STRICT")
    ep_a = create_episode(strict_series["id"], episode_number=1, air_date="2026-06-01T20:00:00Z")
    ep_b = create_episode(strict_series["id"], episode_number=2, air_date="2026-06-08T20:00:00Z")
    ep_c = create_episode(strict_series["id"], episode_number=3, air_date="2026-06-09T20:00:00Z")

    cl_a = _request_clearance(api, ep_a["id"], brand["id"])
    get_success_data(api.decide_clearance(cl_a["id"], decide_clearance_payload("GRANT"), CLEARANCE))
    cl_b = _request_clearance(api, ep_b["id"], brand["id"])
    cl_c = _request_clearance(api, ep_c["id"], brand["id"])

    resp_b = api.decide_clearance(cl_b["id"], decide_clearance_payload("GRANT"), CLEARANCE)
    validate_error(resp_b, ApiErrorId.ERR_AIRDATE_PROXIMITY_CONFLICT)

    cl_c_after = get_success_data(
        api.decide_clearance(cl_c["id"], decide_clearance_payload("GRANT"), CLEARANCE)
    )
    assert cl_c_after["status"] == "GRANTED", (
        f"8 days apart is outside the STRICT window; got {cl_c_after['status']}"
    )

    cl_b_after = find_clearance(ep_b["id"], cl_b["id"])
    assert cl_b_after["status"] == "REQUESTED", (
        f"failed GRANT must leave the clearance REQUESTED, got {cl_b_after['status']}"
    )


def test_airdate_strict_window_day7_rejected_and_undecided(api):
    """PRD §3.3: "under `STRICT` the window includes a difference of seven days
    (seven days or fewer counts as a conflict)". PRD §3.3: "a grant is rejected
    with `ERR_AIRDATE_PROXIMITY_CONFLICT` (HTTP 409) when a same-category
    `GRANTED` clearance exists on a different episode".

    Design: Difficulty/resource_temporal_overlap/airdate_strict_window_day7_conflict_day8_ok
    """
    brand = create_brand(name="Snackly", category="FOOD")
    strict_series = create_series(name="Strict Show", clearance_policy="STRICT")
    ep_a = create_episode(strict_series["id"], episode_number=1, air_date="2026-06-01T20:00:00Z")
    ep_b = create_episode(strict_series["id"], episode_number=2, air_date="2026-06-08T20:00:00Z")

    cl_a = _request_clearance(api, ep_a["id"], brand["id"])
    get_success_data(api.decide_clearance(cl_a["id"], decide_clearance_payload("GRANT"), CLEARANCE))
    cl_b = _request_clearance(api, ep_b["id"], brand["id"])

    resp_b = api.decide_clearance(cl_b["id"], decide_clearance_payload("GRANT"), CLEARANCE)
    validate_error(resp_b, ApiErrorId.ERR_AIRDATE_PROXIMITY_CONFLICT)
    cl_b_after = find_clearance(ep_b["id"], cl_b["id"])
    assert cl_b_after["status"] == "REQUESTED"


def test_second_same_category_grant_rejected(api):
    """PRD §3.3: "at most one clearance may be `GRANTED` for a given episode
    and category, so a grant is rejected with
    `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` (HTTP 409) when another clearance for
    the same episode and category is already `GRANTED`."

    Design: Corner/errors/second_same_category_grant_rejected
    """
    brand_a = create_brand(name="FizzCo", category="BEVERAGE")
    brand_b = create_brand(name="BubbleCo", category="BEVERAGE")
    series = create_series()
    episode = create_episode(series["id"])

    cl1 = _request_clearance(api, episode["id"], brand_a["id"])
    cl2 = _request_clearance(api, episode["id"], brand_b["id"])
    get_success_data(api.decide_clearance(cl1["id"], decide_clearance_payload("GRANT"), CLEARANCE))

    resp = api.decide_clearance(cl2["id"], decide_clearance_payload("GRANT"), CLEARANCE_ALT)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_EXCLUSIVITY_CONFLICT)
    cl2_after = find_clearance(episode["id"], cl2["id"])
    assert cl2_after["status"] == "REQUESTED", (
        f"the rejected grant must leave the clearance REQUESTED, got {cl2_after['status']}"
    )


def test_clearance_release_restores_category_slot(api):
    """PRD §3.3: "A granted clearance holds the (episode, category) slot until
    the officer releases it: releasing moves the clearance from `GRANTED` to
    `RELEASED`, freeing the slot for a future grant; `RELEASED` is terminal."

    Design: Difficulty/compensating_invariant/clearance_release_restores_category_slot
    """
    brand = create_brand()
    series = create_series()
    episode = create_episode(series["id"])

    cl1 = _request_clearance(api, episode["id"], brand["id"])
    cl1 = get_success_data(api.decide_clearance(cl1["id"], decide_clearance_payload("GRANT"), CLEARANCE))
    assert cl1["status"] == "GRANTED", f"slot consumed: {cl1['status']}"

    cl1 = get_success_data(api.release_clearance(cl1["id"], CLEARANCE))
    assert cl1["status"] == "RELEASED", f"slot restored: {cl1['status']}"

    cl2 = _request_clearance(api, episode["id"], brand["id"])
    cl2 = get_success_data(api.decide_clearance(cl2["id"], decide_clearance_payload("GRANT"), CLEARANCE))
    assert cl2["status"] == "GRANTED", (
        f"re-grant after release must succeed (slot conserved); got {cl2['status']}"
    )


def test_clearance_release_then_regrant_succeeds(api):
    """PRD §3.3: "Neither a denied nor a released clearance participates in any
    future exclusivity or proximity evaluation."

    Design: Difficulty/compensating_invariant/clearance_release_restores_category_slot
    """
    brand = create_brand()
    series = create_series()
    episode = create_episode(series["id"])

    cl1 = _request_clearance(api, episode["id"], brand["id"])
    get_success_data(api.decide_clearance(cl1["id"], decide_clearance_payload("GRANT"), CLEARANCE))
    get_success_data(api.release_clearance(cl1["id"], CLEARANCE))

    cl2 = _request_clearance(api, episode["id"], brand["id"])
    cl2 = get_success_data(api.decide_clearance(cl2["id"], decide_clearance_payload("GRANT"), CLEARANCE))
    assert cl2["status"] == "GRANTED"
    cl1_after = find_clearance(episode["id"], cl1["id"])
    assert cl1_after["status"] == "RELEASED", (
        "the released clearance stays RELEASED and does not interfere with the new grant"
    )


def test_clearance_requires_brand_active(api, admin_headers):
    """PRD §3.3: "the request is refused when the brand is `SUSPENDED`
    (`ERR_BRAND_SUSPENDED`)". PRD §3.1: "While a brand is `SUSPENDED`, any
    attempt to create a proposal or a clearance request that references it is
    rejected with `ERR_BRAND_SUSPENDED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/clearance_requires_brand_active
    """
    brand = create_brand()
    get_success_data(api.suspend_brand(brand["id"], admin_headers))
    series = create_series()
    episode = create_episode(series["id"])
    ep = get_success_data(api.get_episode(episode["id"], MANAGER))

    resp = api.create_clearance(
        episode["id"], create_clearance_payload(brand["id"], ep["version"]), MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_BRAND_SUSPENDED)

    brand = get_success_data(api.resume_brand(brand["id"], admin_headers))
    assert brand["status"] == "ACTIVE", f"after resume: {brand['status']}"

    ep = get_success_data(api.get_episode(episode["id"], MANAGER))
    clearance = get_success_data(
        api.create_clearance(
            episode["id"], create_clearance_payload(brand["id"], ep["version"]), MANAGER
        )
    )
    assert clearance["status"] == "REQUESTED", (
        f"after resume the clearance request succeeds; got {clearance['status']}"
    )


def test_clearance_blocked_while_suspended_and_allowed_after_resume(api, admin_headers):
    """PRD §3.1: "The administrator may suspend a brand, moving it from
    `ACTIVE` to `SUSPENDED`, and later resume it back from `SUSPENDED` to
    `ACTIVE`". PRD §3.1: "While a brand is `SUSPENDED`, any attempt to create
    a proposal or a clearance request that references it is rejected with
    `ERR_BRAND_SUSPENDED` (HTTP 409); existing in-flight work is otherwise
    untouched".

    Design: Difficulty/cross_entity_state_dependency/clearance_requires_brand_active
    """
    brand = create_brand()
    get_success_data(api.suspend_brand(brand["id"], admin_headers))
    series = create_series()
    episode = create_episode(series["id"])
    ep = get_success_data(api.get_episode(episode["id"], MANAGER))

    resp = api.create_clearance(
        episode["id"], create_clearance_payload(brand["id"], ep["version"]), MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_BRAND_SUSPENDED)

    # In-flight work untouched: the episode is unchanged.
    ep_after = get_success_data(api.get_episode(episode["id"], MANAGER))
    assert ep_after["version"] == ep["version"], (
        "a rejected clearance request must not advance the episode's version"
    )

    get_success_data(api.resume_brand(brand["id"], admin_headers))
    ep = get_success_data(api.get_episode(episode["id"], MANAGER))
    clearance = get_success_data(
        api.create_clearance(
            episode["id"], create_clearance_payload(brand["id"], ep["version"]), MANAGER
        )
    )
    assert clearance["status"] == "REQUESTED"
