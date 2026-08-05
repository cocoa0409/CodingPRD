"""The four-tier escalation ladder, its acknowledgement clock and the held bed."""

from test_helpers import (
    ApiErrorId,
    assert_bed_census,
    assert_bed_reservation,
    assert_escalation_event,
    assert_same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_bed_reservation_payload,
    create_visit_payload,
)
from test_helpers.test_users import (
    ADMITTING_PHYSICIAN,
    COMMUNITY_PARAMEDIC,
    FIELD_NURSE,
    PROGRAM_ADMIN,
)


# ─── The acknowledgement clock ─────────────────────────────────────────────

def test_acknowledgement_one_second_past_the_deadline_is_rejected(api):
    """PRD §3.8: "It is permitted only while the logical clock is **at or
    before** `ack_deadline_at`; an acknowledgement arriving when the clock has
    passed the deadline is refused with `ERR_INVALID_STATE` at HTTP 409, as is an
    acknowledgement aimed at an escalation that is not currently in an open
    tier."
    PRD §3.8: "Each open tier carries its own base allowance measured from
    `tier_entered_at`: ten minutes at tier 1, twenty minutes at tier 2, thirty
    minutes at tier 3, and fifteen minutes at tier 4 — the ladder deliberately
    tightens again at the top, because a tier-4 escalation is already a
    physician-level emergency."

    Design: Corner/state_machines/escalation_acknowledge_after_the_sla_deadline_is_rejected
    """
    parts = fx.setup_active_episode(mrn="MRN-SL", full_name="Sam Sla")
    episode_id = parts["episode"]["id"]

    escalation = fx.open_escalation(
        episode_id, reason="TELEMETRY_LOSS", opened_by_user_id="rn-1"
    )
    assert_escalation_event(escalation)
    assert_same_instant(
        escalation["ack_deadline_at"], "2026-06-01T08:10:00Z", "ack_deadline_at"
    )

    fx.set_clock("2026-06-01T08:10:01Z")
    validate_error(
        api.acknowledge_escalation(escalation["id"], FIELD_NURSE),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    unchanged = fx.read_escalation(episode_id, escalation["id"])
    assert unchanged["status"] == "TIER1_OPEN"
    assert unchanged["acknowledged_by_user_id"] is None


def test_promotion_at_exactly_the_deadline_is_not_yet_a_breach(api):
    """PRD §3.8: "From an **open** tier it represents a breach: it is permitted
    only when the logical clock is **strictly greater than** `ack_deadline_at`,
    and a promotion attempted while the clock is still at or before the deadline
    is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/escalation_promote_at_exactly_the_deadline_is_rejected_as_not_yet_breached
    """
    parts = fx.setup_active_episode(mrn="MRN-PB", full_name="Pat Promote")
    episode_id = parts["episode"]["id"]

    escalation = fx.open_escalation(
        episode_id, reason="PATIENT_REQUEST", opened_by_user_id="rn-1"
    )
    fx.set_clock("2026-06-01T08:10:00Z")

    validate_error(
        api.promote_escalation(escalation["id"], PROGRAM_ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    unchanged = fx.read_escalation(episode_id, escalation["id"])
    assert unchanged["status"] == "TIER1_OPEN"
    assert unchanged["current_tier"] == 1
    assert unchanged["promotion_count"] == 0
    assert fx.read_episode(episode_id)["status"] == "ACTIVE"


def test_high_acuity_halves_every_escalation_tier_allowance(api):
    """PRD §3.8: "On an episode whose `acuity` is `HIGH` every tier allowance is
    **halved and then rounded half up to a whole number of minutes**, giving
    five, ten, fifteen and eight minutes for tiers 1 through 4 respectively —
    note that halving fifteen yields seven and a half minutes, which rounds up to
    eight."
    PRD §3.8: "`ack_deadline_at` is `tier_entered_at` plus the effective number
    of minutes for the current tier, and it is recomputed from scratch on every
    promotion."

    Design: Corner/calculations/high_acuity_halves_every_escalation_tier_sla
    """
    high = fx.setup_active_episode(acuity="HIGH", mrn="MRN-HI", full_name="Hal High")
    standard = fx.setup_active_episode(
        acuity="STANDARD",
        set_the_clock=False,
        mrn="MRN-ST",
        full_name="Stu Standard",
    )

    high_escalation = fx.open_escalation(
        high["episode"]["id"], reason="VITALS_OUT_OF_RANGE", opened_by_user_id="rn-1"
    )
    standard_escalation = fx.open_escalation(
        standard["episode"]["id"],
        reason="VITALS_OUT_OF_RANGE",
        opened_by_user_id="rn-1",
    )
    assert_same_instant(
        high_escalation["ack_deadline_at"],
        "2026-06-01T08:05:00Z",
        "HIGH tier-1 ack_deadline_at",
    )
    assert_same_instant(
        standard_escalation["ack_deadline_at"],
        "2026-06-01T08:10:00Z",
        "STANDARD tier-1 ack_deadline_at",
    )

    fx.set_clock("2026-06-01T08:06:00Z")

    promoted = validate_success(
        api.promote_escalation(high_escalation["id"], PROGRAM_ADMIN)
    )
    assert promoted["status"] == "TIER2_OPEN"
    assert promoted["current_tier"] == 2
    assert promoted["promotion_count"] == 1
    assert_same_instant(
        promoted["ack_deadline_at"],
        "2026-06-01T08:16:00Z",
        "HIGH tier-2 ack_deadline_at",
    )

    validate_error(
        api.promote_escalation(standard_escalation["id"], PROGRAM_ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert (
        fx.read_escalation(standard["episode"]["id"], standard_escalation["id"])["status"]
        == "TIER1_OPEN"
    )


def test_resolving_the_last_open_escalation_returns_the_episode_to_active(api):
    """PRD §3.8: "Resolution closes an escalation from any acknowledged tier —
    `TIER1_ACKED`, `TIER2_ACKED`, `TIER3_ACKED` or `TIER4_ACKED` — driving it to
    `RESOLVED` and advancing its `version` by 1; resolving from an unacknowledged
    tier is `ERR_INVALID_STATE`."
    PRD §3.8: "The episode's `open_escalation_count` is recomputed, and when no
    escalation of that episode remains outside `RESOLVED` and
    `BED_RETURN_CONVERTED` **and** the episode is currently `ESCALATED`, the
    episode is driven `ESCALATED → ACTIVE` with its `open_escalation_count`
    landing at 0 and its `version` advancing by 1."

    Design: Corner/validations/resolving_the_last_open_escalation_returns_the_episode_to_active
    """
    parts = fx.setup_active_episode(mrn="MRN-RS", full_name="Ros Resolve")
    episode_id = parts["episode"]["id"]

    escalation, _ = fx.escalate_to_tier(
        episode_id, 3, "2026-06-01T08:00:00Z", acuity="STANDARD"
    )
    acknowledged = validate_success(
        api.acknowledge_escalation(escalation["id"], COMMUNITY_PARAMEDIC)
    )
    assert acknowledged["status"] == "TIER3_ACKED"
    assert acknowledged["current_tier"] == 3
    assert acknowledged["acknowledged_by_user_id"] == "medic-1"
    assert fx.read_episode(episode_id)["status"] == "ESCALATED"

    resolved = validate_success(
        api.resolve_escalation(escalation["id"], COMMUNITY_PARAMEDIC)
    )
    assert resolved["status"] == "RESOLVED"

    episode = fx.read_episode(episode_id)
    assert episode["open_escalation_count"] == 0
    assert episode["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_episode_escalation_events(
            episode_id, PROGRAM_ADMIN, params={"status": "RESOLVED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == escalation["id"]


# ─── Tier-3 promotion flips the episode out of ACTIVE ──────────────────────

def test_tier_three_promotion_moves_the_episode_to_escalated(api):
    """PRD §3.8: "Promotion **into `TIER3_OPEN` additionally moves the owning
    episode `ACTIVE → ESCALATED`**, recomputing `open_escalation_count` and
    advancing the episode's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/visit_creation_blocked_while_parent_episode_is_escalated
    """
    parts = fx.setup_active_episode(
        home_distance_km=6.0, mrn="MRN-E1", full_name="Elsa Escalate"
    )
    episode_id = parts["episode"]["id"]

    escalation, _ = fx.escalate_to_tier(
        episode_id, 3, "2026-06-01T08:00:00Z", acuity="STANDARD"
    )
    assert escalation["status"] == "TIER3_OPEN"
    assert escalation["promotion_count"] == 2

    episode = fx.read_episode(episode_id)
    assert episode["status"] == "ESCALATED"
    assert episode["open_escalation_count"] == 1


def test_visit_cannot_be_scheduled_while_the_episode_is_escalated(api):
    """PRD §2.5: "**Rung 8 — Parent episode state gate.** For operations that
    write into a live episode, the parent episode's `status` is `ACTIVE`.
    Violation: `ERR_EPISODE_NOT_ACTIVE` (409)."
    PRD §3.3: "The episode must be `ACTIVE` at the moment of scheduling."

    Design: Difficulty/cross_entity_state_dependency/visit_creation_blocked_while_parent_episode_is_escalated
    """
    parts = fx.setup_active_episode(
        home_distance_km=6.0, mrn="MRN-E2", full_name="Elsa Escalate Two"
    )
    episode_id = parts["episode"]["id"]

    fx.escalate_to_tier(episode_id, 3, "2026-06-01T08:00:00Z", acuity="STANDARD")
    assert fx.read_episode(episode_id)["status"] == "ESCALATED"

    payload = create_visit_payload(
        episode_id,
        "2026-06-01",
        "2026-06-01T10:00:00Z",
        "2026-06-01T10:45:00Z",
        staff_user_id="rn-1",
        distance_km=6.0,
    )
    validate_error(
        api.create_visit(payload, FIELD_NURSE),
        ApiErrorId.ERR_EPISODE_NOT_ACTIVE.value,
    )

    rows, meta = validate_paginated(api.list_episode_visits(episode_id, PROGRAM_ADMIN))
    assert meta["total_count"] == 0
    assert rows == []


# ─── Bed capacity ──────────────────────────────────────────────────────────

def test_second_hold_on_a_single_bed_unit_is_refused_while_the_first_is_live(api):
    """PRD §3.8: "Before capacity is judged, the unit's stale holds are swept
    (see below); if the resulting `available_bed_count` is then below 1 the
    request is refused with `ERR_NO_BEDS_AVAILABLE` at HTTP 409."
    PRD §2.8: "An inpatient unit's `total_beds` is supplied at registration and
    is immutable thereafter; it always equals the sum of `available_bed_count`,
    `held_bed_count` and `occupied_bed_count`."

    Design: Difficulty/resource_temporal_overlap/inpatient_bed_capacity_is_aggregate_and_released_by_hold_expiry
    """
    first = fx.setup_active_episode(
        clock="2026-06-02T09:32:00Z",
        eval_at="2026-06-02T08:00:00Z",
        mrn="MRN-P2",
        full_name="Pam Peak",
    )
    second = fx.setup_active_episode(
        set_the_clock=False,
        eval_at="2026-06-02T08:00:00Z",
        mrn="MRN-Q2",
        full_name="Quinn Queue",
    )

    unit = fx.register_unit(unit_code="UNIT-ONE", total_beds=1)
    fx.hold_bed(unit["id"], first["episode"]["id"], unit["version"])

    live = validate_success(api.get_inpatient_unit(unit["id"], PROGRAM_ADMIN))
    assert_bed_census(live, available=0, held=1, occupied=0)

    validate_error(
        api.create_bed_reservation(
            create_bed_reservation_payload(
                unit["id"], second["episode"]["id"], live["version"]
            ),
            ADMITTING_PHYSICIAN,
        ),
        ApiErrorId.ERR_NO_BEDS_AVAILABLE.value,
    )


def test_lazy_expiry_of_a_stale_hold_frees_the_bed_for_the_next_episode(api):
    """PRD §3.8: "A reservation still in `HELD` whose `hold_expires_at` the
    logical clock has passed — strictly greater, so a clock sitting exactly on
    `hold_expires_at` has not yet expired it — moves `HELD → EXPIRED` at the
    moment anyone looks: when that single reservation is read, when its inpatient
    unit is read, and when a new hold is attempted against the same `unit_id`."
    PRD §3.8: "A successful hold opens the reservation in `HELD`, stamps
    `held_at` from the logical clock, sets `hold_expires_at` to `held_at` plus
    one hundred and twenty minutes, increments the unit's `held_bed_count` and
    decrements its `available_bed_count`, and advances the **unit's** `version`
    by 1."

    Design: Difficulty/resource_temporal_overlap/inpatient_bed_capacity_is_aggregate_and_released_by_hold_expiry
    """
    first = fx.setup_active_episode(
        clock="2026-06-02T09:32:00Z",
        eval_at="2026-06-02T08:00:00Z",
        mrn="MRN-P3",
        full_name="Pam Peak Two",
    )
    second = fx.setup_active_episode(
        set_the_clock=False,
        eval_at="2026-06-02T08:00:00Z",
        mrn="MRN-Q3",
        full_name="Quinn Queue Two",
    )

    unit = fx.register_unit(unit_code="UNIT-TWO", total_beds=1)
    reservation = fx.hold_bed(unit["id"], first["episode"]["id"], unit["version"])
    assert_bed_reservation(reservation)
    assert_same_instant(
        reservation["hold_expires_at"], "2026-06-02T11:32:00Z", "hold_expires_at"
    )

    fx.set_clock("2026-06-02T11:33:00Z")
    swept = validate_success(api.get_inpatient_unit(unit["id"], PROGRAM_ADMIN))
    assert_bed_census(swept, available=1, held=0, occupied=0)

    expired = validate_success(
        api.get_bed_reservation(reservation["id"], ADMITTING_PHYSICIAN)
    )
    assert expired["status"] == "EXPIRED"
    assert expired["occupied_at"] is None

    retried = validate_success(
        api.create_bed_reservation(
            create_bed_reservation_payload(
                unit["id"], second["episode"]["id"], swept["version"]
            ),
            ADMITTING_PHYSICIAN,
        ),
        201,
    )
    assert retried["status"] == "HELD"
    assert_bed_census(
        validate_success(api.get_inpatient_unit(unit["id"], PROGRAM_ADMIN)),
        available=0,
        held=1,
        occupied=0,
    )


def test_bed_reservation_with_a_stale_unit_version_is_rejected(api):
    """PRD §2.6: "A `POST /bed-reservations` request must carry
    `expected_unit_version` holding the `version` of the target `InpatientUnit`
    the client last read. Every hold, expiry and release mutates that unit's bed
    census and therefore its `version`; a mismatch means the caller's picture of
    remaining capacity is out of date, and the reservation is rejected with
    `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/bed_reservation_with_stale_unit_version_returns_stale_version
    """
    first = fx.setup_active_episode(mrn="MRN-OA", full_name="Olly Occ A")
    second = fx.setup_active_episode(
        set_the_clock=False, mrn="MRN-OB", full_name="Ora Occ B"
    )

    unit = fx.register_unit(unit_code="UNIT-OCC", total_beds=3)
    version_at_creation = unit["version"]
    reservation = fx.hold_bed(
        unit["id"], first["episode"]["id"], version_at_creation
    )

    error = validate_error(
        api.create_bed_reservation(
            create_bed_reservation_payload(
                unit["id"], second["episode"]["id"], version_at_creation
            ),
            ADMITTING_PHYSICIAN,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )
    assert error["error_id"] != "ERR_NO_BEDS_AVAILABLE", (
        "two of the three beds are still free — the failure is the stale version"
    )

    census = validate_success(api.get_inpatient_unit(unit["id"], PROGRAM_ADMIN))
    assert_bed_census(census, available=2, held=1, occupied=0)

    rows, meta = validate_paginated(
        api.list_bed_reservations(PROGRAM_ADMIN, params={"unit_id": unit["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == reservation["id"]
