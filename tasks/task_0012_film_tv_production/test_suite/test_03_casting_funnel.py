"""Casting funnel: Role/Audition state machine, offer/sign/recast/substitute.

Covers PRD §3.2 (the casting funnel), §2.6 (posture-blocking on sign).
Difficulty design: dual_variant_calc/cast_commit_estimate_offer_vs_sign,
combinatorial_formula/cast_commit_min_cap_with_state_filtered_sum,
non_linear_state_machine/role_audition_shortlist_cycle,
transitive_cascade/role_sign_to_budget_to_alert_to_posture_depth_three,
priority_pair_validation_conflict (state vs fiscal),
cross_entity_state_dependency/role_sign_depends_on_production_status,
compensating_invariant/substitute_role_preserves_total_cast_committed.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_audition_payload,
    offer_role_payload,
    substitute_role_payload,
    schedule_scene_payload,
    setup_production_with_categories,
    create_role_in_production,
    create_actor,
    create_scene_in_production,
    walk_role_to_offered,
    walk_role_to_signed,
    setup_role_with_n_breakdown_scenes,
    setup_signed_role,
    setup_wrap_pending,
    get_categories_by_code,
    get_production,
    iso,
    EXEC,
    LP,
    FC,
    CD,
    PC,
)


# ─── Audition + role state machine ───────────────────────────────────────────

def test_first_audition_advances_role_open_to_auditioning(api):
    """PRD §3.2: "When the first audition is recorded against a role, the role
    auto-advances from `OPEN` to `AUDITIONING`."

    Claim: first POST /auditions transitions Role.casting_status OPEN→AUDITIONING.
    """
    prod, _ = setup_production_with_categories(api)
    role = create_role_in_production(api, production_id=prod["id"])
    actor = create_actor(api)
    assert role["casting_status"] == "OPEN"

    res = api.create_audition(
        prod["id"], role["id"],
        create_audition_payload(actor_id=actor["id"], outcome="PASS"),
        CD,
    )
    validate_success(res, 201)
    role_after = validate_success(api.get_production(prod["id"], CD), 200)
    # Role state isn't on Production; re-fetch via list/audit. We can call shortlist
    # to test role state — first verify by re-fetching role through shortlist preflight.
    # The cleanest way: shortlist requires AUDITIONING, so it should now succeed.
    short = api.shortlist_role(prod["id"], role["id"], CD)
    role_short = validate_success(short, 200)
    assert role_short["casting_status"] == "SHORTLISTED"


def test_shortlist_requires_at_least_one_pass_audition(api):
    """PRD §3.2: "After at least one audition records `outcome` of `PASS`, the
    casting director may shortlist the role, transitioning `AUDITIONING →
    SHORTLISTED`."

    Claim: shortlist with no PASS audition → ERR_INVALID_STATE.
    """
    prod, _ = setup_production_with_categories(api)
    role = create_role_in_production(api, production_id=prod["id"])
    actor = create_actor(api)
    # Record a REJECT audition: role now AUDITIONING but no PASS exists.
    api.create_audition(
        prod["id"], role["id"],
        create_audition_payload(actor_id=actor["id"], outcome="REJECT"),
        CD,
    )
    res = api.shortlist_role(prod["id"], role["id"], CD)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_offer_requires_pass_audition_for_offered_actor(api):
    """PRD §3.2: "The actor must already have a `PASS` audition recorded on
    this exact role, otherwise the call is rejected with
    `ERR_AUDITION_NOT_PASSED` (HTTP 422)."

    Claim: offer with actor_id whose audition outcome != PASS →
    ERR_AUDITION_NOT_PASSED.
    """
    prod, _ = setup_production_with_categories(api)
    role = create_role_in_production(api, production_id=prod["id"])
    actor_pass = create_actor(api)
    actor_no_pass = create_actor(api)
    # Pass audition for actor_pass; reject for actor_no_pass.
    api.create_audition(
        prod["id"], role["id"],
        create_audition_payload(actor_id=actor_pass["id"], outcome="PASS"),
        CD,
    )
    api.create_audition(
        prod["id"], role["id"],
        create_audition_payload(actor_id=actor_no_pass["id"], outcome="REJECT"),
        CD,
    )
    api.shortlist_role(prod["id"], role["id"], CD)
    # Offer to actor_no_pass — no PASS audition.
    res = api.offer_role(
        prod["id"], role["id"],
        offer_role_payload(actor_id=actor_no_pass["id"]),
        CD,
    )
    validate_error(res, "ERR_AUDITION_NOT_PASSED", expected_status=422)


def test_role_audition_shortlist_cycle(api):
    """PRD §3.2: "A shortlisted role can be reopened — `SHORTLISTED →
    AUDITIONING` — provided the production is still in `PLANNING`."

    # difficulty: non_linear_state_machine/role_audition_shortlist_cycle
    Claim: OPEN→AUDITIONING (via audition) → SHORTLISTED (via shortlist) →
    AUDITIONING (via reopen-auditions) → SHORTLISTED (via shortlist) — the
    cycle works and the role lands back at SHORTLISTED.
    """
    prod, _ = setup_production_with_categories(api)
    role = create_role_in_production(api, production_id=prod["id"])
    actor = create_actor(api)

    # First leg: OPEN→AUDITIONING (first audition is PASS)
    api.create_audition(
        prod["id"], role["id"],
        create_audition_payload(actor_id=actor["id"], outcome="PASS"),
        CD,
    )
    role_short = validate_success(api.shortlist_role(prod["id"], role["id"], CD), 200)
    assert role_short["casting_status"] == "SHORTLISTED"

    # Cycle leg: SHORTLISTED→AUDITIONING (reopen)
    role_reopen = validate_success(api.reopen_auditions(prod["id"], role["id"], CD), 200)
    assert role_reopen["casting_status"] == "AUDITIONING"

    # Back to SHORTLISTED
    role_short2 = validate_success(api.shortlist_role(prod["id"], role["id"], CD), 200)
    assert role_short2["casting_status"] == "SHORTLISTED"


# ─── Sign-time CAST commit (dual variant + combinatorial cap) ────────────────

def test_sign_role_uses_at_sign_time_variant_excluding_shot_scenes(api):
    """PRD §3.2: "For each scene of the production whose `required_actor_role_ids`
    includes this role and whose scene `status` is in the set `BREAKDOWN`,
    `SCHEDULED`, or `RESCHEDULING` (scenes already in `SHOT` or `OMITTED` are
    excluded)(...)."

    # difficulty: dual_variant_calc/cast_commit_estimate_offer_vs_sign_on_role_entity
    Claim: with 3 scenes total — 1 SHOT, 2 BREAKDOWN — the at_sign_time variant
    counts only the 2 BREAKDOWN scenes; CAST.committed_cents == 2 * 1 day *
    day_rate_cents (not 3 * day_rate_cents).
    """
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=2,
        n_shot_scenes=1,
        scene_minutes=480,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=200_000,
        cast_planned_cents=10_000_000,
    )
    # Sign the role.
    signed = validate_success(api.sign_role(s["production"]["id"], s["role"]["id"], LP), 200)
    assert signed["casting_status"] == "SIGNED"

    # Verify CAST.committed_cents.
    cats = get_categories_by_code(api, production_id=s["production"]["id"])
    cast = cats["CAST"]
    # Each scene is 480 min → ceil(480/480) = 1 day. Two BREAKDOWN scenes → 2 days
    # * 200_000 = 400_000. SHOT scene excluded.
    assert cast["committed_cents"] == 400_000, (
        f"Expected 400000, got {cast['committed_cents']}"
    )
    assert cast["committed_cents"] != 600_000


def test_sign_role_combinatorial_cap_by_union_tier(api):
    """PRD §3.2: "Those per-scene work-days are summed, then capped at the
    union-tier ceiling: 60 days for `PRINCIPAL`, 30 days for `SUPPORTING`,
    and 10 days for `FEATURED_BACKGROUND`."

    # difficulty: combinatorial_formula/cast_commit_min_cap_with_state_filtered_sum
    Claim: 12 scenes * 720 min each → ceil(720/480)=2 days each → 24 days raw
    sum, capped to 10 days (FEATURED_BACKGROUND), commit = 10 *
    day_rate_cents. With day_rate_cents=100_000 → CAST.committed_cents ==
    1_000_000 (NOT 2_400_000).
    """
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=12,
        n_shot_scenes=0,
        scene_minutes=720,
        role_union_tier="FEATURED_BACKGROUND",
        role_day_rate_cents=100_000,
        cast_planned_cents=20_000_000,
    )
    signed = validate_success(api.sign_role(s["production"]["id"], s["role"]["id"], LP), 200)
    assert signed["casting_status"] == "SIGNED"
    cats = get_categories_by_code(api, production_id=s["production"]["id"])
    assert cats["CAST"]["committed_cents"] == 1_000_000, (
        f"Expected 1000000 (capped), got {cats['CAST']['committed_cents']}"
    )
    assert cats["CAST"]["committed_cents"] != 2_400_000


def test_sign_role_blocked_when_posture_frozen(api):
    """PRD §2.6: "A `FROZEN` posture gates all non-wrap-progression operations:
    any mutation other than the wrap-progression endpoints is rejected with
    `ERR_POSTURE_BLOCKED` (HTTP 409)."

    # difficulty: cross_entity_state_dependency/role_sign_depends_on_production_status
    Claim: in WRAP_PENDING (posture FROZEN), an OFFERED role cannot be signed —
    request returns ERR_POSTURE_BLOCKED.
    """
    # Build a Production walked to WRAP_PENDING, which forces posture=FROZEN.
    setup = setup_wrap_pending(api)
    prod = setup["production"]
    assert prod["posture"] == "FROZEN"
    # Now create a fresh Role on this production at OFFERED — but in WRAP_PENDING
    # creating a Role is itself blocked. So this test requires the Role to be at
    # OFFERED before begin-wrap. Restructure: build an alternate fixture chain.
    # Easier path: reuse setup_role_with_n_breakdown_scenes (role at OFFERED)
    # then walk that production to WRAP_PENDING. But the difficulty design recipe
    # is direct: production at WRAP_PENDING with role at OFFERED.

    # Inline: build a brand-new production in PLANNING with role at OFFERED, then
    # walk to IN_PRODUCTION (must satisfy lock_baseline preconditions), then to
    # WRAP_PENDING.
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=1,
        n_shot_scenes=0,
        scene_minutes=120,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=100_000,
        cast_planned_cents=10_000_000,
    )
    # Need a SCHEDULED scene under THIS production to lock-baseline.
    # The setup helper creates BREAKDOWN scenes. Let's set one up to SCHEDULED.
    from test_helpers import (
        create_location,
        create_held_reservation,
        confirm_reservation_with_permit_and_weather,
    )
    location = create_location(api)
    scene = s["scenes_breakdown"][0]
    res = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=s["production"]["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 3, 1, 9),
        end_at=iso(2026, 3, 1, 11),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=res["id"])
    validate_success(api.schedule_scene(
        s["production"]["id"], scene["id"],
        schedule_scene_payload(reservation_id=res["id"]),
        LP,
    ), 200)
    # Lock baseline → IN_PRODUCTION
    prod_ip = validate_success(api.lock_baseline(s["production"]["id"], LP), 200)
    # Mark scene SHOT and begin-wrap
    validate_success(api.mark_shot(s["production"]["id"], scene["id"], PC), 200)
    prod_wp = validate_success(api.begin_wrap(s["production"]["id"], LP), 200)
    assert prod_wp["posture"] == "FROZEN"

    # Now attempt to sign the OFFERED role → ERR_POSTURE_BLOCKED.
    sign_res = api.sign_role(s["production"]["id"], s["role"]["id"], LP)
    validate_error(sign_res, "ERR_POSTURE_BLOCKED", expected_status=409)


# ─── Substitute role: compensating invariant ────────────────────────────────

def test_substitute_role_preserves_cast_committed_invariant(api):
    """PRD §3.2: "On success, the previously projected `CAST` commit (computed
    under the original role) is decremented from the `CAST` category's
    `committed_cents`, a fresh `Role` record is created carrying the
    replacement values and is immediately signed in-line (its own projected
    commit is added to `CAST.committed_cents`)(...)."

    # difficulty: compensating_invariant/substitute_role_preserves_total_cast_committed
    Claim: substitute decrements old role's commit (400000) and adds new role's
    commit (600000); CAST.committed_cents lands at 600000 (== sum over signed
    roles), with no drift left from the original commit.
    """
    s = setup_signed_role(
        api,
        n_breakdown_scenes=2,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=200_000,
        cast_planned_cents=10_000_000,
    )
    cats = get_categories_by_code(api, production_id=s["production"]["id"])
    assert cats["CAST"]["committed_cents"] == 400_000

    # Substitute with replacement_day_rate_cents=300_000 (still 2 BREAKDOWN scenes
    # → 2 days * 300000 = 600_000)
    replacement = create_actor(api)
    sub_res = validate_success(api.substitute_role(
        s["production"]["id"], s["role"]["id"],
        substitute_role_payload(
            replacement_actor_id=replacement["id"],
            replacement_day_rate_cents=300_000,
        ),
        LP,
    ), 200)
    # Old role recast
    assert sub_res["casting_status"] == "RECAST"

    cats = get_categories_by_code(api, production_id=s["production"]["id"])
    assert cats["CAST"]["committed_cents"] == 600_000, (
        f"Expected 600000 (= -400000 + 600000), got {cats['CAST']['committed_cents']}"
    )
