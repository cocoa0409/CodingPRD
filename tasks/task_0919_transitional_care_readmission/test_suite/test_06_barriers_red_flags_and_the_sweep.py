"""Typed barriers, the bounded red-flag escalation loop and the operational sweep."""
from test_helpers import (
    ADMIN,
    CLINICIAN,
    ApiErrorId,
    assert_barrier,
    assert_red_flag,
    assert_same_instant,
    connect_contact,
    make_clinician_headers,
    raise_barrier,
    raise_red_flag,
    read_barrier,
    read_episode,
    read_red_flag,
    read_visit,
    set_clock,
    setup_confirmed_visit,
    setup_program_with_episode,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_sweep_escalates_a_breached_blocking_barrier_and_unconfirms_the_visit(api):
    """PRD §3.6: "Breach is tested strictly: a barrier is breached only when the
    current instant is strictly after `sla_due_at`, so a barrier sitting exactly
    at its due instant is not yet breached."
    PRD §3.6: "Every barrier of a **blocking** class that is still `OPEN` and
    whose `sla_due_at` is strictly in the past moves `OPEN → ESCALATED` and
    spawns a red flag with `category` `BARRIER_SLA_BREACH` at `TIER_2` in
    `RAISED`, whose `source_barrier_id` names the breached barrier, whose
    `raised_by_user_id` is `SYSTEM`, and whose `ack_due_at` is 120 minutes after
    the current instant; the barrier's `escalated_red_flag_id` records that
    flag."
    PRD §3.6: "Escalation also reaches sideways into the calendar: every visit
    of the episode still `SCHEDULED` and `CONFIRMED` has its
    `confirmation_status` reverted to `UNCONFIRMED`, because a confirmed
    appointment behind a breached blocking barrier is not a promise the
    programme can keep."

    Design: Corner/state_machines/sla_sweep_escalates_breached_blocking_barrier_and_unconfirms_visit
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)
    barrier = raise_barrier(ctx, ep, "TRANSPORTATION", "no ride")
    assert_barrier(barrier)
    assert_same_instant(barrier["sla_due_at"], "2026-05-03T16:00:00.000Z", "sla_due_at")

    set_clock("2026-05-03T16:00:00Z")
    first = validate_success(api.run_sla_sweep(ep["episode_id"], ADMIN))
    assert first["barriers_escalated"] == 0
    assert first["red_flags_created"] == 0
    assert read_barrier(ctx, barrier["id"])["status"] == "OPEN"

    set_clock("2026-05-03T16:00:01Z")
    second = validate_success(api.run_sla_sweep(ep["episode_id"], ADMIN))
    assert second["barriers_escalated"] == 1
    assert second["red_flags_created"] == 1
    assert second["red_flags_promoted"] == 0

    escalated = read_barrier(ctx, barrier["id"])
    assert escalated["status"] == "ESCALATED"
    assert escalated["closed_at"] is None
    assert escalated["escalated_red_flag_id"] is not None

    flags, meta = validate_paginated(
        api.list_red_flags(ADMIN, params={"source_barrier_id": barrier["id"]})
    )
    assert meta["total_count"] == 1
    flag = flags[0]
    assert flag["category"] == "BARRIER_SLA_BREACH"
    assert flag["tier"] == "TIER_2"
    assert flag["status"] == "RAISED"
    assert flag["raised_by_user_id"] == "SYSTEM"
    assert_same_instant(flag["ack_due_at"], "2026-05-03T18:00:01.000Z", "ack_due_at")

    after_visit = read_visit(ctx, visit["id"])
    assert after_visit["confirmation_status"] == "UNCONFIRMED"
    assert after_visit["encounter_status"] == "SCHEDULED"

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["open_red_flag_count"] == 1
    assert episode["escalation_state"] == "ACTIVE"


def test_red_flag_promotes_twice_then_breaches_at_tier_one(api):
    """PRD §3.6: "It promotes when its current `tier` is not already `TIER_1`
    **and** its `promotion_count` is below 2: the tier steps up one notch along
    `TIER_3 → TIER_2 → TIER_1`, `promotion_count` increases by 1, `ack_due_at`
    is reset to the current instant plus the **new** tier's allowance (120
    minutes when the new tier is `TIER_2`, 30 minutes when it is `TIER_1`), and
    the role entitled to acknowledge it changes with the tier."
    PRD §3.6: "It breaches instead — moving `RAISED → BREACHED` and decrementing
    the episode's `open_red_flag_count`, with `escalation_state` returning to
    `NONE` at 0 — when its `tier` is already `TIER_1` **or** its
    `promotion_count` has already reached 2."

    Design: Corner/state_machines/red_flag_promotes_twice_then_breaches_at_tier_1
    """
    ctx, ep = setup_program_with_episode()
    flag = raise_red_flag(ctx, ep, category="CLINICAL_SYMPTOM", initial_tier="TIER_3")
    assert_red_flag(flag)
    assert flag["tier"] == "TIER_3"
    assert flag["promotion_count"] == 0
    assert_same_instant(flag["ack_due_at"], "2026-05-02T00:00:00.000Z", "ack_due_at")

    set_clock("2026-05-02T00:01:00Z")
    sweep1 = validate_success(api.run_sla_sweep(ep["episode_id"], ADMIN))
    assert sweep1["red_flags_promoted"] == 1
    after1 = read_red_flag(ctx, flag["id"])
    assert after1["tier"] == "TIER_2"
    assert after1["promotion_count"] == 1
    assert after1["status"] == "RAISED"
    assert_same_instant(after1["ack_due_at"], "2026-05-02T02:01:00.000Z", "ack_due_at")

    set_clock("2026-05-02T02:02:00Z")
    sweep2 = validate_success(api.run_sla_sweep(ep["episode_id"], ADMIN))
    assert sweep2["red_flags_promoted"] == 1
    after2 = read_red_flag(ctx, flag["id"])
    assert after2["tier"] == "TIER_1"
    assert after2["promotion_count"] == 2
    assert after2["status"] == "RAISED"
    assert_same_instant(after2["ack_due_at"], "2026-05-02T02:32:00.000Z", "ack_due_at")

    set_clock("2026-05-02T02:33:00Z")
    sweep3 = validate_success(api.run_sla_sweep(ep["episode_id"], ADMIN))
    assert sweep3["red_flags_promoted"] == 0
    assert sweep3["red_flags_breached"] == 1
    after3 = read_red_flag(ctx, flag["id"])
    assert after3["tier"] == "TIER_1"
    assert after3["promotion_count"] == 2
    assert after3["status"] == "BREACHED"

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["open_red_flag_count"] == 0
    assert episode["escalation_state"] == "NONE"


def test_acknowledged_red_flag_is_immune_to_promotion_and_breach(api):
    """PRD §3.6: "Phase 2 handles red flags, and it processes **only** flags in
    `RAISED` whose `ack_due_at` is strictly in the past — acknowledged flags are
    immune."
    PRD §3.6: "Acknowledging moves the flag `RAISED → ACKNOWLEDGED`, records
    `acknowledged_by_user_id` and `acknowledged_at`, and permanently stops the
    promotion clock — an acknowledged flag can never be promoted or breached."

    Design: Corner/state_machines/acknowledged_red_flag_is_immune_to_promotion_and_breach
    """
    ctx, ep = setup_program_with_episode()
    flag = raise_red_flag(ctx, ep, category="MEDICATION_ISSUE", initial_tier="TIER_3")

    set_clock("2026-05-01T17:00:00Z")
    validate_success(api.acknowledge_red_flag(flag["id"], ep["nav_headers"]))

    set_clock("2026-05-04T00:00:00Z")
    sweep = validate_success(api.run_sla_sweep(ep["episode_id"], ADMIN))
    assert sweep["red_flags_promoted"] == 0
    assert sweep["red_flags_breached"] == 0

    after = read_red_flag(ctx, flag["id"])
    assert after["status"] == "ACKNOWLEDGED"
    assert after["tier"] == "TIER_3"
    assert after["promotion_count"] == 0
    assert_same_instant(
        after["acknowledged_at"], "2026-05-01T17:00:00.000Z", "acknowledged_at"
    )

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["open_red_flag_count"] == 1
    assert episode["escalation_state"] == "ACTIVE"


def test_sent_to_ed_resolution_spawns_an_ed_treat_and_release_event(api):
    """PRD §3.6: "A `SENT_TO_ED` outcome has a further consequence: when the
    current calendar date falls between the day after `discharge_date` and
    `readmission_window_end_date` inclusive, the system automatically creates a
    readmission event classified `ED_TREAT_AND_RELEASE`, dated the current
    calendar date, whose `source_red_flag_id` points back at this flag and whose
    `recorded_by_user_id` is the literal string `SYSTEM`; the flag's
    `spawned_readmission_id` records the new event."
    PRD §3.9: "`ED_TREAT_AND_RELEASE` is also excluded from the rate and is
    completely inert: no episode status change, no claim change, no flag — only
    the event row itself and the episode's `excluded_readmission_count`."

    Design: Corner/state_machines/red_flag_resolution_sent_to_ed_spawns_readmission_event
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    set_clock("2026-05-10T09:00:00Z")
    flag = raise_red_flag(ctx, ep, category="CLINICAL_SYMPTOM", initial_tier="TIER_2")
    validate_success(api.acknowledge_red_flag(flag["id"], ep["nav_headers"]))

    resolved = validate_success(
        api.resolve_red_flag(flag["id"], {"resolution_outcome": "SENT_TO_ED"}, CLINICIAN)
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_outcome"] == "SENT_TO_ED"
    assert resolved["ed_event_suppressed"] is False
    assert resolved["spawned_readmission_id"] is not None

    events, meta = validate_paginated(
        api.list_readmissions(ADMIN, params={"source_red_flag_id": flag["id"]})
    )
    assert meta["total_count"] == 1
    event = events[0]
    assert event["classification"] == "ED_TREAT_AND_RELEASE"
    assert event["readmission_date"] == "2026-05-10"
    assert event["day_index"] == 9
    assert event["counts_toward_rate"] is False
    assert event["recorded_by_user_id"] == "SYSTEM"

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["status"] == "ACTIVE"
    assert episode["billing_eligible"] is True
    assert episode["readmission_event_count"] == 1
    assert episode["excluded_readmission_count"] == 1
    assert episode["counted_readmission_count"] == 0
    assert episode["open_red_flag_count"] == 0
    assert episode["escalation_state"] == "NONE"


def test_pharmacy_barrier_is_resolvable_only_by_its_clinician_owner_role(api):
    """PRD §3.6: "Resolving is restricted to the barrier's own `owner_role` — an
    insurance-authorisation barrier is resolved by a `BillingSpecialist` and a
    pharmacy-access barrier by a `Clinician`, and anyone else is turned away
    with `ERR_FORBIDDEN_ROLE`."
    PRD §3.6: "`PHARMACY_ACCESS` carries 36 hours, is owned by `Clinician`, and
    is blocking."

    Design: Corner/rbac/pharmacy_barrier_resolve_requires_clinician_owner_role
    """
    ctx, ep = setup_program_with_episode()
    barrier = raise_barrier(ctx, ep, "PHARMACY_ACCESS", "pharmacy closed")
    assert barrier["owner_role"] == "Clinician"
    assert barrier["sla_hours"] == 36
    assert barrier["blocking_class"] is True
    assert_same_instant(barrier["sla_due_at"], "2026-05-03T04:00:00.000Z", "sla_due_at")

    validate_error(
        api.close_barrier(barrier["id"], {"outcome": "RESOLVED"}, ep["nav_headers"]),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    assert read_barrier(ctx, barrier["id"])["status"] == "OPEN"

    closed = validate_success(
        api.close_barrier(barrier["id"], {"outcome": "RESOLVED"}, CLINICIAN)
    )
    assert closed["status"] == "RESOLVED"
    assert_same_instant(closed["closed_at"], "2026-05-01T16:00:00.000Z", "closed_at")


def test_tier_one_acknowledgement_requires_the_clinician_routing_role(api):
    """PRD §3.6: "`TIER_1` must be acknowledged within 30 minutes and is routed
    to a `Clinician`."
    PRD §3.6: "Only the routing role for the flag's **current** tier may
    acknowledge it, and because the tier can change under promotion, the
    acceptable role can change with it; the wrong role is refused with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/tier1_red_flag_acknowledge_requires_clinician_routing_role
    """
    ctx, ep = setup_program_with_episode()
    flag = raise_red_flag(
        ctx,
        ep,
        category="CLINICAL_SYMPTOM",
        initial_tier="TIER_1",
        headers=make_clinician_headers("clin-9"),
    )
    assert flag["tier"] == "TIER_1"
    assert flag["raised_by_user_id"] == "clin-9"
    assert_same_instant(flag["ack_due_at"], "2026-05-01T16:30:00.000Z", "ack_due_at")

    validate_error(
        api.acknowledge_red_flag(flag["id"], ep["nav_headers"]),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    assert read_red_flag(ctx, flag["id"])["status"] == "RAISED"

    acknowledged = validate_success(
        api.acknowledge_red_flag(flag["id"], make_clinician_headers("clin-4"))
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == "clin-4"


def test_red_flag_resolver_may_not_be_the_actor_who_raised_it(api):
    """PRD §2.1: "A claim may not be submitted by the same `X-User-ID` that
    prepared it, and a red flag may not be resolved by the same `X-User-ID` that
    raised it. Either violation yields `ERR_SEGREGATION_OF_DUTIES` with HTTP
    403."
    PRD §3.6: "Resolving a flag moves it `ACKNOWLEDGED → RESOLVED` and requires
    a `resolution_outcome` of `RESOLVED_AT_HOME`, `RESOLVED_URGENT_CARE` or
    `SENT_TO_ED`. The resolver may not be the same `X-User-ID` that raised the
    flag."

    Design: Corner/rbac/red_flag_resolver_cannot_be_the_raiser
    """
    ctx, ep = setup_program_with_episode()
    raiser = make_clinician_headers("clin-7")
    flag = raise_red_flag(
        ctx, ep, category="MEDICATION_ISSUE", initial_tier="TIER_2", headers=raiser
    )
    validate_success(api.acknowledge_red_flag(flag["id"], ep["nav_headers"]))

    validate_error(
        api.resolve_red_flag(
            flag["id"], {"resolution_outcome": "RESOLVED_AT_HOME"}, raiser
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    assert read_red_flag(ctx, flag["id"])["status"] == "ACKNOWLEDGED"

    resolved = validate_success(
        api.resolve_red_flag(
            flag["id"],
            {"resolution_outcome": "RESOLVED_AT_HOME"},
            make_clinician_headers("clin-8"),
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_outcome"] == "RESOLVED_AT_HOME"
    assert resolved["spawned_readmission_id"] is None
    assert resolved["ed_event_suppressed"] is False

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["open_red_flag_count"] == 0
    assert episode["escalation_state"] == "NONE"
