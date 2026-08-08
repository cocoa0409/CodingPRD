"""Care-team handoff, the two workload cap policies and the global
active-episode conservation invariant."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_handoff,
    assert_same_instant,
    add_navigator,
    propose_handoff,
    read_episode,
    read_handoff,
    read_navigator,
    respond_handoff,
    set_clock,
    setup_episode,
    setup_program,
    setup_program_with_episode,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def _four_episode_cap_scenario(api):
    """nav0 holds four HIGH-tier episodes; nav_a is COUNT-capped at 2 and
    nav_b is WEIGHTED-capped at 2. Episodes 1 and 2 land on nav_a, episode 3
    lands on nav_b, and episode 4 is proposed to nav_b but not yet answered."""
    ctx = setup_program(navigator_overrides={"full_name": "Nora Vance", "active_episode_cap": 5, "cap_policy": "COUNT"})
    nav_a, nav_a_headers = add_navigator(
        ctx, full_name="Amir Cole", active_episode_cap=2, cap_policy="COUNT"
    )
    nav_b, nav_b_headers = add_navigator(
        ctx, full_name="Bea Lund", active_episode_cap=2, cap_policy="WEIGHTED"
    )
    episodes = [setup_episode(ctx) for _ in range(4)]

    for episode in episodes[:2]:
        handoff = propose_handoff(ctx, episode, nav_a["id"])
        respond_handoff(ctx, handoff["id"], nav_a_headers, "ACCEPT")
    third = propose_handoff(ctx, episodes[2], nav_b["id"])
    respond_handoff(ctx, third["id"], nav_b_headers, "ACCEPT")
    fourth = propose_handoff(ctx, episodes[3], nav_b["id"])
    return ctx, episodes, nav_a, nav_a_headers, nav_b, nav_b_headers, fourth


def test_count_policy_navigator_absorbs_two_high_tier_episodes(api):
    """PRD §3.7: "Under the `COUNT` policy, `workload_score` is simply that
    count, every open episode weighs exactly 1 whatever its risk tier, and an
    incoming episode weighs 1 — a navigator with a cap of 2 can hold two
    `SEVERE` episodes without difficulty."
    PRD §3.7: "The acceptance gate itself is inclusive: the receiving
    navigator's current `workload_score` plus the incoming episode's weight must
    be **at most** their `active_episode_cap`, so landing exactly on the cap is
    permitted and exceeding it is refused with `ERR_NAVIGATOR_CAP_EXCEEDED`."

    Design: Difficulty/dual_variant_calc/navigator_cap_count_policy_vs_weighted_policy
    """
    ctx, episodes, nav_a, _a_headers, _nav_b, _b_headers, _fourth = _four_episode_cap_scenario(api)
    reloaded = read_navigator(ctx, nav_a["id"])
    assert reloaded["active_episode_count"] == 2
    assert float(reloaded["workload_score"]) == 2
    assert reloaded["availability_status"] == "AT_CAP"
    assert read_episode(ctx, episodes[0]["episode_id"])["navigator_id"] == nav_a["id"]
    assert read_episode(ctx, episodes[1]["episode_id"])["navigator_id"] == nav_a["id"]


def test_weighted_policy_navigator_refuses_the_second_high_tier_episode(api):
    """PRD §3.7: "Under the `WEIGHTED` policy, each open episode weighs
    according to its `risk_tier`: 1 for `LOW`, 1 for `MODERATE`, 2 for `HIGH`
    and 3 for `SEVERE`; `workload_score` is the sum of those weights across the
    navigator's open episodes, and the incoming episode weighs whatever its own
    tier is worth."
    PRD §3.7: "so landing exactly on the cap is permitted and exceeding it is
    refused with `ERR_NAVIGATOR_CAP_EXCEEDED`."

    Design: Difficulty/dual_variant_calc/navigator_cap_count_policy_vs_weighted_policy
    """
    ctx, episodes, _nav_a, _a_headers, nav_b, nav_b_headers, fourth = _four_episode_cap_scenario(api)
    before = read_navigator(ctx, nav_b["id"])
    assert before["active_episode_count"] == 1
    assert float(before["workload_score"]) == 2
    assert before["availability_status"] == "AT_CAP"

    validate_error(
        api.respond_handoff(fourth["id"], {"response": "ACCEPT"}, nav_b_headers),
        ApiErrorId.ERR_NAVIGATOR_CAP_EXCEEDED.value,
    )
    assert read_handoff(ctx, fourth["id"])["status"] == "PROPOSED"
    assert (
        read_episode(ctx, episodes[3]["episode_id"])["navigator_id"]
        == ctx["navigator_id"]
    )
    after = read_navigator(ctx, nav_b["id"])
    assert after["active_episode_count"] == 1
    assert float(after["workload_score"]) == 2


def test_accepted_handoff_moves_the_episode_between_navigators(api):
    """PRD §3.7: "`ACCEPT` moves the handoff `PROPOSED → ACCEPTED`, stamps
    `responded_at`, reassigns the episode's `navigator_id` to the accepting
    navigator, decrements the sending navigator's `active_episode_count` by 1
    and increments the receiving navigator's by 1, and recomputes
    `workload_score` and `availability_status` for both."

    Design: Difficulty/compensating_invariant/handoff_accept_conserves_global_active_episode_count
    """
    ctx = setup_program()
    nav2, nav2_headers = add_navigator(ctx, full_name="Owen Park")
    ep1 = setup_episode(ctx)
    ep2 = setup_episode(ctx)

    handoff = propose_handoff(ctx, ep1, nav2["id"])
    assert_handoff(handoff)
    assert handoff["from_navigator_id"] == ctx["navigator_id"]
    assert handoff["to_navigator_id"] == nav2["id"]

    accepted = validate_success(
        api.respond_handoff(handoff["id"], {"response": "ACCEPT"}, nav2_headers)
    )
    assert accepted["status"] == "ACCEPTED"
    assert_same_instant(
        accepted["responded_at"], "2026-05-01T16:00:00.000Z", "responded_at"
    )
    assert read_episode(ctx, ep1["episode_id"])["navigator_id"] == nav2["id"]
    assert read_episode(ctx, ep2["episode_id"])["navigator_id"] == ctx["navigator_id"]

    sender = read_navigator(ctx, ctx["navigator_id"])
    receiver = read_navigator(ctx, nav2["id"])
    assert float(sender["workload_score"]) == 1
    assert sender["availability_status"] == "AVAILABLE"
    assert float(receiver["workload_score"]) == 1
    assert receiver["availability_status"] == "AVAILABLE"


def test_global_active_episode_count_is_conserved_across_the_handoff(api):
    """PRD §2.9: "Third, across the whole programme, the sum of
    `active_episode_count` over all navigators always equals the number of care
    episodes whose `status` is `INTAKE`, `ACTIVE` or `SERVICE_PERIOD_CLOSED`. An
    accepted handoff decrements one navigator and increments another inside the
    same request, so the global total never drifts; episodes in `BILLED`,
    `CLOSED_READMITTED` or `ADMIN_CLOSED` contribute to nobody's count."

    Design: Difficulty/compensating_invariant/handoff_accept_conserves_global_active_episode_count
    """
    ctx = setup_program()
    nav2, nav2_headers = add_navigator(ctx, full_name="Owen Park")
    ep1 = setup_episode(ctx)
    setup_episode(ctx)

    before_total = (
        read_navigator(ctx, ctx["navigator_id"])["active_episode_count"]
        + read_navigator(ctx, nav2["id"])["active_episode_count"]
    )
    assert before_total == 2
    assert read_navigator(ctx, ctx["navigator_id"])["active_episode_count"] == 2
    assert read_navigator(ctx, nav2["id"])["active_episode_count"] == 0

    handoff = propose_handoff(ctx, ep1, nav2["id"])
    respond_handoff(ctx, handoff["id"], nav2_headers, "ACCEPT")

    sender_count = read_navigator(ctx, ctx["navigator_id"])["active_episode_count"]
    receiver_count = read_navigator(ctx, nav2["id"])["active_episode_count"]
    assert sender_count == 1
    assert receiver_count == 1

    open_episodes, _meta = validate_paginated(
        api.list_episodes(ADMIN, params={"limit": 100, "offset": 0})
    )
    open_count = sum(
        1
        for row in open_episodes
        if row["status"] in ("INTAKE", "ACTIVE", "SERVICE_PERIOD_CLOSED")
    )
    assert sender_count + receiver_count == open_count == 2


def test_new_proposal_supersedes_the_prior_proposed_request(api):
    """PRD §3.7: "A fresh proposal supersedes any handoff on the same episode
    still sitting in `PROPOSED`, moving it `PROPOSED → SUPERSEDED` with
    `superseded_by_id` set to the new proposal's `id`."
    PRD §3.7: "The proposal records `from_navigator_id` as the episode's
    navigator at the moment of proposal, opens in `PROPOSED`, stamps
    `proposed_at` from the logical clock, and sets `expires_at` to 24 hours
    after `proposed_at`. Proposing also increments the episode's own `version`
    by 1 — which is precisely why the operation is version-guarded, since a
    second proposal made from a stale view would silently cancel a proposal its
    author never saw."

    Design: Corner/state_machines/new_handoff_proposal_supersedes_prior_proposed_request
    """
    ctx, ep = setup_program_with_episode()
    nav2, nav2_headers = add_navigator(ctx, full_name="Owen Park")
    nav3, _nav3_headers = add_navigator(ctx, full_name="Pim Ash")

    version_before = read_episode(ctx, ep["episode_id"])["version"]
    first = propose_handoff(ctx, ep, nav2["id"], expected_episode_version=version_before)
    version_after_first = read_episode(ctx, ep["episode_id"])["version"]
    assert version_after_first == version_before + 1

    second = validate_success(
        api.propose_handoff(
            ep["episode_id"],
            {
                "to_navigator_id": nav3["id"],
                "handoff_type": "PCP_PROGRAM",
                "expected_episode_version": version_after_first,
            },
            ep["nav_headers"],
        ),
        201,
    )
    assert second["status"] == "PROPOSED"
    assert second["handoff_type"] == "PCP_PROGRAM"
    assert_same_instant(second["expires_at"], "2026-05-02T16:00:00.000Z", "expires_at")

    superseded = read_handoff(ctx, first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_id"] == second["id"]

    validate_error(
        api.respond_handoff(first["id"], {"response": "ACCEPT"}, nav2_headers),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_episode(ctx, ep["episode_id"])["navigator_id"] == ctx["navigator_id"]


def test_sweep_expires_a_stale_proposal_and_the_later_response_is_rejected(api):
    """PRD §3.7: "The same expiry also happens unattended in phase 3 of the
    operational sweep, where every proposal past its `expires_at` is moved to
    `EXPIRED`; either way, the episode's `navigator_id` is left exactly where it
    was."
    PRD §3.7: "A response that arrives after expiry does not simply fail: the
    handoff row is first flipped `PROPOSED → EXPIRED`, that change is persisted,
    and only then is the caller told `ERR_HANDOFF_EXPIRED`."

    The rejection is asserted as one of two error ids because the sweep has
    already moved the row out of `PROPOSED` before the response arrives, and the
    PRD does not uniquely determine which rung then decides. PRD §2.10 rung 10
    ("The target resource is in a state from which the requested transition is
    declared — otherwise `ERR_INVALID_STATE`") precedes rung 33 ("The current
    instant is on or before the handoff's `expires_at` — otherwise
    `ERR_HANDOFF_EXPIRED` ... Applies to responding to a handoff"), and the
    ordering is normative, so an `EXPIRED` row may legitimately be reported at
    rung 10; the §3.7 sentence above describes the flip as `PROPOSED → EXPIRED`
    and so speaks only to a row still in `PROPOSED`. Both readings are faithful.

    Design: Corner/endpoints/sla_sweep_phase3_expires_stale_handoff_and_response_is_rejected
    """
    ctx, ep = setup_program_with_episode()
    nav2, nav2_headers = add_navigator(ctx, full_name="Owen Park")
    handoff = propose_handoff(ctx, ep, nav2["id"])
    assert_same_instant(handoff["expires_at"], "2026-05-02T16:00:00.000Z", "expires_at")

    set_clock("2026-05-02T16:00:01Z")
    sweep = validate_success(api.run_sla_sweep(ep["episode_id"], ADMIN))
    assert sweep["handoffs_expired"] == 1
    assert read_handoff(ctx, handoff["id"])["status"] == "EXPIRED"

    validate_error_is_one_of(
        api.respond_handoff(handoff["id"], {"response": "ACCEPT"}, nav2_headers),
        [
            ApiErrorId.ERR_HANDOFF_EXPIRED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ],
    )
    assert read_handoff(ctx, handoff["id"])["status"] == "EXPIRED"
    assert read_episode(ctx, ep["episode_id"])["navigator_id"] == ctx["navigator_id"]
    assert read_navigator(ctx, nav2["id"])["active_episode_count"] == 0


def test_stale_episode_version_rejects_a_handoff_proposal(api):
    """PRD §2.6: "Proposing a handoff on a care episode requires
    `expected_episode_version` carrying the client's last observed `version` of
    that `CareEpisode`. A new proposal legitimately supersedes any handoff still
    awaiting a response on the same episode, so a caller working from a stale
    view of the episode would cancel a proposal it never read; if the episode's
    `version` has advanced since the client last read it, the proposal is
    refused rather than applied."
    PRD §2.6: "In each case the version field is a **required** part of the
    request body — omitting it is a plain request-validation failure — and in
    each case a value that does not equal the parent's current `version` is
    rejected with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_episode_version_rejects_handoff_creation
    """
    ctx, ep = setup_program_with_episode()
    nav2, _nav2_headers = add_navigator(ctx, full_name="Owen Park")
    nav3, _nav3_headers = add_navigator(ctx, full_name="Pim Ash")

    stale_version = read_episode(ctx, ep["episode_id"])["version"]
    first = propose_handoff(ctx, ep, nav2["id"], expected_episode_version=stale_version)

    validate_error(
        api.propose_handoff(
            ep["episode_id"],
            {
                "to_navigator_id": nav3["id"],
                "handoff_type": "INTERNAL_NAVIGATOR",
                "expected_episode_version": stale_version,
            },
            ep["nav_headers"],
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )
    unchanged = read_handoff(ctx, first["id"])
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["superseded_by_id"] is None
    _, meta = validate_paginated(
        api.list_handoffs(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 1
    assert read_episode(ctx, ep["episode_id"])["version"] == stale_version + 1
