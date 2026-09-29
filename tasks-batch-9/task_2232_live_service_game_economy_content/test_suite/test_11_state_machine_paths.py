"""State-machine paths: declared initial states, full valid walks, guarded and precondition-gated
transitions, invalid-trigger rejection, terminal lockdown and the conclude cascade."""

from typing import Any, Dict, List

from test_helpers import (
    CLOCK_EPOCH,
    COMPLIANCE,
    DESIGNER,
    LIVEOPS,
    OPERATOR_IDS,
    PRODUCER,
    TEST_DEFAULTS,
    ApiErrorId,
    api_client,
    archive_season,
    create_balance_change_payload,
    create_cluster,
    create_cluster_payload,
    create_disclosure_payload,
    create_draft_episode,
    create_draft_offer,
    create_episode_payload,
    create_live_event_payload,
    create_live_season,
    create_live_single_line_offer,
    create_offer_payload,
    create_pending_purchase,
    create_planned_event,
    create_player,
    create_monitoring_run_payload,
    create_scheduled_episode,
    create_season_payload,
    decide_refund,
    disclosure_entry,
    draft_disclosure,
    get_success_data,
    lock_player,
    offer_line_item,
    open_account,
    publish_disclosure,
    read_account,
    read_cluster,
    read_live_event,
    read_offer,
    read_player,
    read_purchase,
    read_season,
    release_episode_at,
    rollback_episode_at,
    set_clock,
    settle_purchase,
    submit_refund,
    unlock_player,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Private helpers — every test rebuilds its own world from scratch
# ---------------------------------------------------------------------------

_CRATE_TABLE_1 = [
    disclosure_entry("C_COMMON", 8500, 200, False),
    disclosure_entry("C_RARE", 1400, 1500, False),
    disclosure_entry("C_MYTHIC", 100, 9000, True),
]

_CRATE_TABLE_2 = [
    disclosure_entry("C_COMMON", 9000, 200, False),
    disclosure_entry("C_RARE", 900, 1500, False),
    disclosure_entry("C_MYTHIC", 100, 9000, True),
]

_CRATE_OFFER_OVERRIDES: Dict[str, Any] = {
    "offer_type": "LOOT_BOX",
    "sku": "CRATE_A",
    "price_tier": "T1",
    "list_price_minor": 300,
    "line_items": [offer_line_item("CRATE_KEY", 300, 400, "HARD_GEM", 300)],
    "window_start": "2026-08-01T00:00:00Z",
    "window_end": "2026-08-20T00:00:00Z",
}


def _read_episode(episode_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_episode(episode_id, PRODUCER))


def _disclosure_rows(offer_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api_client.list_disclosures(offer_id, DESIGNER))
    return rows


def _disclosure_row(offer_id: str, disclosure_id: str) -> Dict[str, Any]:
    matches = [row for row in _disclosure_rows(offer_id) if row["id"] == disclosure_id]
    assert matches, f"Disclosure {disclosure_id} must be listed under offer {offer_id}"
    return matches[0]


def _event_on_a_fresh_cluster(forecast_ccu: int) -> Dict[str, Any]:
    """LIVE season, ACTIVE cluster NA-1 at 10000 CCU, and one PLANNED event on it.

    Returns a dict with keys: season, cluster, event.
    """
    season = create_live_season()
    cluster = get_success_data(
        api_client.create_cluster(create_cluster_payload(name="NA-1"), LIVEOPS)
    )
    event = create_planned_event(
        season["id"],
        cluster["id"],
        code="EVT_A",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-05T02:00:00Z",
        forecast_ccu=forecast_ccu,
    )
    return {"season": season, "cluster": cluster, "event": event}


# ---------------------------------------------------------------------------
# Initial states
# ---------------------------------------------------------------------------
def test_every_machine_opens_in_its_declared_initial_state():
    """PRD §3.1: "The season is stored in `PLANNED`, with `economy_health` at `HEALTHY`, `content_posture` at `ON_TRACK`, `version` at 1, and every derived counter at its opening value: `scheduled_episode_count`, `released_episode_count`, `cadence_debt_days`, `gross_faucet_minor`, `gross_sink_minor`, `pending_revenue_minor`, `settled_revenue_minor`, `live_offer_count`, `active_tuning_count` and `tuning_stage_epoch` all at 0, and `lifetime_ratio_bp` and `effective_sink_rate_bp` both at 10000."
    PRD §3.2: "Episodes are created in `DRAFT`."
    PRD §3.3: "A new cluster is `ACTIVE` with `reserved_ccu` at 0, that field being the sum of the reservations held by events on the cluster that are `APPROVED` or `RUNNING`."
    PRD §3.3: "The event is created in `PLANNED` with `reserved_ccu_at_approval` at 0 and `rollback_reason` null, and no capacity whatsoever is reserved until approval."
    PRD §3.5: "A newly created offer is `DRAFT` on the first dimension and `OFFLINE` on the second, and neither dimension ever moves the other implicitly: an offer can be re-reviewed while it sits live on the storefront, and it can be suspended and resumed without its approval ever being revisited."
    PRD §3.5: "A drafted table is `DRAFT` with `published_at` and `published_by_user_id` both null, and it does not yet change the offer's `disclosure_state`."
    PRD §3.8: "The change is stored in `DRAFT` with the authoring operator recorded as `authored_by_user_id`, `promoted_by_user_id` and `pre_live_sink_rate_bp` null, and `comms_state` at `MISSING`."
    PRD §3.9: "A new run is `OPEN`, with `gross_faucet_minor`, `gross_sink_minor`, `suspended_offer_count` and `denied_purchase_count` at 0, and `sink_faucet_ratio_bp`, `resulting_health`, `computed_at` and `certified_by_user_id` all null."

    Design: Corner/state_machines/corner_sm_initial_states_across_machines
    """
    set_clock(CLOCK_EPOCH)

    season = validate_success(api_client.create_season(create_season_payload(), PRODUCER), 201)
    episode = validate_success(
        api_client.create_episode(create_episode_payload(season["id"]), PRODUCER), 201
    )
    cluster = validate_success(
        api_client.create_cluster(create_cluster_payload(name="NA-1"), LIVEOPS), 201
    )
    event = validate_success(
        api_client.create_live_event(
            create_live_event_payload(
                season["id"],
                cluster["id"],
                code="EVT_A",
                window_start="2026-08-05T00:00:00Z",
                window_end="2026-08-05T02:00:00Z",
                forecast_ccu=1000,
            ),
            PRODUCER,
        ),
        201,
    )
    offer = validate_success(
        api_client.create_offer(create_offer_payload(season["id"], **_CRATE_OFFER_OVERRIDES), DESIGNER),
        201,
    )
    disclosure = validate_success(
        api_client.create_disclosure(
            offer["id"], create_disclosure_payload(entries=_CRATE_TABLE_1), DESIGNER
        ),
        201,
    )
    change = validate_success(
        api_client.create_balance_change(
            create_balance_change_payload(season["id"], rationale="Sink is under target"), DESIGNER
        ),
        201,
    )
    run = validate_success(
        api_client.create_monitoring_run(
            create_monitoring_run_payload(
                season["id"],
                epoch_no=1,
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-08-02T00:00:00Z",
            ),
            LIVEOPS,
        ),
        201,
    )

    assert season["status"] == "PLANNED", f"A new season must open PLANNED, got {season['status']}"
    assert episode["status"] == "DRAFT", f"A new episode must open DRAFT, got {episode['status']}"
    assert cluster["status"] == "ACTIVE", f"A new cluster must open ACTIVE, got {cluster['status']}"
    assert event["status"] == "PLANNED", f"A new live event must open PLANNED, got {event['status']}"
    assert offer["approval_status"] == "DRAFT", (
        f"A new offer must open DRAFT on the governance dimension, got {offer['approval_status']}"
    )
    assert offer["availability_status"] == "OFFLINE", (
        f"A new offer must open OFFLINE on the storefront dimension, got {offer['availability_status']}"
    )
    assert disclosure["status"] == "DRAFT", (
        f"A drafted probability table must open DRAFT, got {disclosure['status']}"
    )
    assert change["stage"] == "DRAFT", f"A new tuning change must open DRAFT, got {change['stage']}"
    assert run["status"] == "OPEN", f"A new monitoring run must open OPEN, got {run['status']}"


# ---------------------------------------------------------------------------
# Valid transition walks
# ---------------------------------------------------------------------------
def test_live_event_walks_planned_approved_running_completed():
    """PRD §3.3: "Approval is a `LiveOpsCommander` action that carries the event from `PLANNED` to `APPROVED`."
    PRD §3.3: "On success the event's `forecast_ccu` is snapshotted into `reserved_ccu_at_approval`, the cluster's `reserved_ccu` grows by that same figure, and the cluster's `version` moves by 1."
    PRD §3.3: "Starting an event moves `APPROVED → RUNNING` and requires the clock to have reached or passed `window_start` and the cluster to be either `ACTIVE` or `DRAINING`, a `RETIRED` cluster being refused with `ERR_CLUSTER_NOT_ACTIVE`; it moves only the event's own `version`."
    PRD §3.3: "Completing a `RUNNING` event moves it to `COMPLETED`, lowers the cluster's `reserved_ccu` by the event's `reserved_ccu_at_approval`, resets `reserved_ccu_at_approval` to 0, and moves the cluster's `version` by 1."

    Design: Corner/state_machines/corner_sm_live_event_full_valid_path
    """
    world = _event_on_a_fresh_cluster(forecast_ccu=6000)
    event_id = world["event"]["id"]

    approved = validate_success(api_client.approve_live_event(event_id, LIVEOPS))
    set_clock("2026-08-05T00:00:00Z")
    started = validate_success(api_client.start_live_event(event_id, LIVEOPS))
    completed = validate_success(api_client.complete_live_event(event_id, LIVEOPS))

    assert approved["status"] == "APPROVED", (
        f"Approval must land the event on APPROVED, got {approved['status']}"
    )
    assert approved["reserved_ccu_at_approval"] == 6000, (
        f"Approval must snapshot forecast_ccu into reserved_ccu_at_approval, got "
        f"{approved['reserved_ccu_at_approval']}"
    )
    assert started["status"] == "RUNNING", (
        f"Starting must land the event on RUNNING, got {started['status']}"
    )
    assert completed["status"] == "COMPLETED", (
        f"Completing must land the event on COMPLETED, got {completed['status']}"
    )
    assert read_live_event(event_id)["status"] == "COMPLETED", (
        "The stored event must read COMPLETED after the full walk"
    )
    assert read_cluster(world["cluster"]["id"])["reserved_ccu"] == 0, (
        "Completion must release the whole snapshotted reservation back to the cluster"
    )


# ---------------------------------------------------------------------------
# Precondition enforcement at the instant boundary
# ---------------------------------------------------------------------------
def test_episode_release_one_second_early_is_not_due_then_succeeds_on_the_instant():
    """PRD §3.2: "Four conditions gate it: the episode is `SCHEDULED`, the season is `LIVE` (otherwise `ERR_SEASON_NOT_LIVE`), the logical clock has reached or passed the episode's `planned_release_at` (an early attempt yielding `ERR_EPISODE_NOT_DUE`), and the season's `economy_health` is not `INFLATED` (otherwise `ERR_ECONOMY_INFLATED_BLOCK`)."
    PRD §3.2: "On success the episode's `actual_release_at` is stamped with the clock, the season's `scheduled_episode_count` falls by 1 and its `released_episode_count` rises by 1, and any episode of the same season that is currently `LIVE` with a lower `sequence_no` is automatically carried from `LIVE` to `CONCLUDED` — the previous drop closing out as the new one opens, with `released_episode_count` unaffected by that automatic closure."
    PRD §3.2: "At the second level, because those entries now exist, each recipient account's `lifetime_faucet_minor` grows by the granted amount, its `balance_minor` is recomputed as lifetime faucet minus lifetime sink, and its `version` moves by 1."

    Design: Corner/state_machines/corner_sm_precondition_episode_release_before_due
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_p1", region_code="NA")
    account = open_account(player["id"], "SOFT_COIN")
    episode = create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=1200,
    )

    set_clock("2026-08-01T23:59:59Z")
    validate_error(
        api_client.release_episode(episode["id"], PRODUCER),
        ApiErrorId.ERR_EPISODE_NOT_DUE.value,
        422,
    )

    rejected = _read_episode(episode["id"])
    assert rejected["status"] == "SCHEDULED", (
        f"A release one second early must leave the episode SCHEDULED, got {rejected['status']}"
    )
    assert read_account(account["id"])["balance_minor"] == 0, (
        "A rejected release must mint no soft-currency grant at all"
    )

    set_clock("2026-08-02T00:00:00Z")
    released = validate_success(api_client.release_episode(episode["id"], PRODUCER))

    assert released["status"] == "LIVE", (
        f"Releasing exactly on planned_release_at must land the episode LIVE, got {released['status']}"
    )
    assert released["actual_release_at"].startswith("2026-08-02T00:00:00"), (
        "actual_release_at must be stamped with the release-instant clock, got "
        f"{released['actual_release_at']}"
    )
    assert read_account(account["id"])["balance_minor"] == 1200, (
        "The on-time release must credit the recipient account with the full grant"
    )


# ---------------------------------------------------------------------------
# Invalid triggers per machine
# ---------------------------------------------------------------------------
def test_triggers_absent_from_the_current_state_are_refused_per_entity():
    """PRD §2.11: "The target resource is in a state from which the requested transition exists, on every transition endpoint (`ERR_SEASON_INVALID_STATE`, `ERR_EPISODE_INVALID_STATE`, `ERR_CLUSTER_INVALID_STATE`, `ERR_EVENT_INVALID_STATE`, `ERR_OFFER_INVALID_APPROVAL_STATE`, `ERR_OFFER_INVALID_AVAILABILITY_STATE`, `ERR_DISCLOSURE_INVALID_STATE`, `ERR_PURCHASE_INVALID_STATE`, `ERR_REFUND_INVALID_STATE`, `ERR_BALANCE_CHANGE_INVALID_STATE`, `ERR_COMMS_NOTICE_INVALID_STATE`, `ERR_MONITORING_RUN_INVALID_STATE`)."
    PRD §3.2: "Releasing an episode advances it from `SCHEDULED` to `LIVE` and is open to both a `ContentProducer` and a `LiveOpsCommander`."
    PRD §3.2: "Rolling an episode back is a `LiveOpsCommander` action, permitted only while the episode is `LIVE` and its season is `LIVE`, and it takes a `reason` in the body."
    PRD §3.2: "It carries the episode from `LIVE` to `ROLLED_BACK`, raises the episode's `rollback_count` by 1 — a counter that is never reset — and lowers the season's `released_episode_count` by 1."
    PRD §3.3: "`COMPLETED`, `ROLLED_BACK` and `CANCELLED` are all terminal, and a request for a transition that does not exist from the event's current status is refused with `ERR_EVENT_INVALID_STATE`."
    PRD §3.3: "The event is created in `PLANNED` with `reserved_ccu_at_approval` at 0 and `rollback_reason` null, and no capacity whatsoever is reserved until approval."

    Design: Corner/state_machines/corner_sm_invalid_transitions_rejected_per_machine
    """
    season = create_live_season()
    scheduled_episode = create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    draft_episode = create_draft_episode(
        season["id"],
        sequence_no=2,
        title="E2 Undertow",
        planned_release_at="2026-08-09T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    cluster = create_cluster(name="NA-1")
    event = create_planned_event(
        season["id"],
        cluster["id"],
        code="EVT_A",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-05T02:00:00Z",
        forecast_ccu=1000,
    )

    validate_error(
        api_client.release_episode(draft_episode["id"], PRODUCER),
        ApiErrorId.ERR_EPISODE_INVALID_STATE.value,
        409,
    )
    validate_error(
        api_client.rollback_episode(
            scheduled_episode["id"], {"reason": "Never went live"}, LIVEOPS
        ),
        ApiErrorId.ERR_EPISODE_INVALID_STATE.value,
        409,
    )
    validate_error(
        api_client.start_live_event(event["id"], LIVEOPS),
        ApiErrorId.ERR_EVENT_INVALID_STATE.value,
        409,
    )

    assert _read_episode(draft_episode["id"])["status"] == "DRAFT", (
        "The refused release must leave the DRAFT episode in DRAFT"
    )
    still_scheduled = _read_episode(scheduled_episode["id"])
    assert still_scheduled["status"] == "SCHEDULED", (
        f"The refused rollback must leave the episode SCHEDULED, got {still_scheduled['status']}"
    )
    assert still_scheduled["rollback_count"] == 0, (
        f"A refused rollback must not raise rollback_count, got {still_scheduled['rollback_count']}"
    )
    assert read_live_event(event["id"])["status"] == "PLANNED", (
        "The refused start must leave the event PLANNED"
    )
    assert read_cluster(cluster["id"])["reserved_ccu"] == 0, (
        "No capacity may be reserved while the event is still PLANNED"
    )


# ---------------------------------------------------------------------------
# Idempotency: replaying an accepted trigger
# ---------------------------------------------------------------------------
def test_second_approve_of_the_same_event_is_refused_and_does_not_double_reserve():
    """PRD §3.3: "It requires the event to be `PLANNED`, the season to be `LIVE` (otherwise `ERR_SEASON_NOT_LIVE`), the cluster to be `ACTIVE` (a `DRAINING` or `RETIRED` cluster yielding `ERR_CLUSTER_NOT_ACTIVE`), and the logical clock to be strictly before the event's `window_end` — an approval attempted at or after the window has closed is refused with `ERR_EVENT_INVALID_STATE`."
    PRD §3.3: "`COMPLETED`, `ROLLED_BACK` and `CANCELLED` are all terminal, and a request for a transition that does not exist from the event's current status is refused with `ERR_EVENT_INVALID_STATE`."
    PRD §3.3: "On success the event's `forecast_ccu` is snapshotted into `reserved_ccu_at_approval`, the cluster's `reserved_ccu` grows by that same figure, and the cluster's `version` moves by 1."

    Design: Corner/state_machines/corner_sm_idempotency_second_approve_rejected
    """
    world = _event_on_a_fresh_cluster(forecast_ccu=6000)
    event_id = world["event"]["id"]
    validate_success(api_client.approve_live_event(event_id, LIVEOPS))

    validate_error(
        api_client.approve_live_event(event_id, LIVEOPS),
        ApiErrorId.ERR_EVENT_INVALID_STATE.value,
        409,
    )

    event_after = read_live_event(event_id)
    assert event_after["status"] == "APPROVED", (
        f"The replayed approve must leave the event APPROVED, got {event_after['status']}"
    )
    assert event_after["reserved_ccu_at_approval"] == 6000, (
        f"The snapshot must stay at the single reservation, got {event_after['reserved_ccu_at_approval']}"
    )
    assert read_cluster(world["cluster"]["id"])["reserved_ccu"] == 6000, (
        "A refused replay must not re-run the reservation side effect"
    )


# ---------------------------------------------------------------------------
# Terminal state lockdown
# ---------------------------------------------------------------------------
def test_archived_season_refuses_every_further_status_trigger():
    """PRD §3.1: "`ARCHIVED` is terminal — no further mutation of the season or of anything beneath it is accepted."
    PRD §3.1: "A request that satisfies neither of those two conditions is refused with `ERR_SEASON_INVALID_STATE`, as is any attempt to take a transition that does not exist from the current status."

    Design: Corner/state_machines/corner_sm_terminal_lockdown_archived_season
    """
    season = create_live_season()
    archived = archive_season(season["id"])
    assert archived["status"] == "ARCHIVED", (
        f"Setup must reach the terminal ARCHIVED state, got {archived['status']}"
    )

    validate_error(
        api_client.set_season_status(season["id"], {"to_status": "LIVE"}, PRODUCER),
        ApiErrorId.ERR_SEASON_INVALID_STATE.value,
        409,
    )
    validate_error(
        api_client.set_season_status(season["id"], {"to_status": "CONCLUDED"}, LIVEOPS),
        ApiErrorId.ERR_SEASON_INVALID_STATE.value,
        409,
    )

    after = read_season(season["id"])
    assert after["status"] == "ARCHIVED", (
        f"The archived season must stay ARCHIVED, got {after['status']}"
    )
    assert after["version"] == archived["version"], (
        f"Refused triggers must not mutate the archived season: expected version "
        f"{archived['version']}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Conclude cascade, conditional on child state
# ---------------------------------------------------------------------------
def test_conclude_cascades_to_non_terminal_children_only():
    """PRD §3.1: "A `ContentProducer` also closes it, moving `LIVE` to `CONCLUDED`, but only when either the logical clock has reached or passed `ends_at`, or every episode of the season has already come to rest in `CONCLUDED` or `ROLLED_BACK`."
    PRD §3.1: "Every episode still `LIVE` is moved to `CONCLUDED`, and `released_episode_count` is deliberately left untouched, because a concluded episode still counts as released."
    PRD §3.1: "Every offer of the season whose `availability_status` is `LIVE` or `SUSPENDED` is moved to `WITHDRAWN`, processed in ascending `created_at` order, and the season's `live_offer_count` is set to 0."
    PRD §3.1: "Each offer that has just become `WITHDRAWN` then denies each of its own purchases still in `PENDING`, recording the `deny_reason` `SEASON_CONCLUDED`, and the season's `pending_revenue_minor` drops by each such purchase's `quoted_price_minor`."
    PRD §3.1: "Every live event still in `PLANNED` is moved to `CANCELLED`."
    PRD §3.2: "It carries the episode from `LIVE` to `ROLLED_BACK`, raises the episode's `rollback_count` by 1 — a counter that is never reset — and lowers the season's `released_episode_count` by 1."
    PRD §3.5: "A newly created offer is `DRAFT` on the first dimension and `OFFLINE` on the second, and neither dimension ever moves the other implicitly: an offer can be re-reviewed while it sits live on the storefront, and it can be suspended and resumed without its approval ever being revisited."
    PRD §3.6: "The supplied `deny_reason` is recorded, the season's `pending_revenue_minor` and the player's `pending_spend_minor` each fall by the purchase's `quoted_price_minor`, the offer's `pending_purchase_count` falls by 1, and the `version` of the offer, the season and the player each move by 1."
    PRD §3.6: "The same `PENDING → DENIED` transition also occurs as a system cascade in four situations, each writing its own `deny_reason`: an offer being withdrawn (`OFFER_WITHDRAWN`), a season concluding (`SEASON_CONCLUDED`), a player being locked (`SPEND_LOCKED`), and an offer being suspended by an inflation monitoring run (`OFFER_SUSPENDED_BY_MONITORING`)."

    Design: Corner/state_machines/corner_sm_conclude_cascades_only_non_terminal_children
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_p1", region_code="NA")
    open_account(player["id"], "HARD_GEM")
    cluster = create_cluster(name="NA-1")
    event = create_planned_event(
        season["id"],
        cluster["id"],
        code="EVT_A",
        window_start="2026-09-05T00:00:00Z",
        window_end="2026-09-05T02:00:00Z",
        forecast_ccu=1000,
    )

    episode_one = create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    release_episode_at(episode_one["id"], "2026-08-02T00:00:00Z")
    rollback_episode_at(episode_one["id"], "Zone was unplayable")

    episode_two = create_scheduled_episode(
        season["id"],
        sequence_no=2,
        title="E2 Undertow",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    release_episode_at(episode_two["id"])

    offer = create_live_single_line_offer(
        season["id"],
        sku="STARTER_5K",
        base_price_minor=5000,
        declared_value_minor=6000,
        granted_currency_code="HARD_GEM",
        granted_amount_minor=5000,
    )
    purchase = create_pending_purchase(player["id"], offer["id"])

    # Episode 2 is still LIVE, so the conclude gate is satisfied through the clock reaching ends_at.
    set_clock(TEST_DEFAULTS["SEASON_ENDS_AT"])
    concluded = validate_success(
        api_client.set_season_status(season["id"], {"to_status": "CONCLUDED"}, PRODUCER)
    )

    assert concluded["status"] == "CONCLUDED", (
        f"The season must land on CONCLUDED, got {concluded['status']}"
    )
    assert _read_episode(episode_two["id"])["status"] == "CONCLUDED", (
        "The LIVE episode must be carried to CONCLUDED by the cascade"
    )
    terminal_episode = _read_episode(episode_one["id"])
    assert terminal_episode["status"] == "ROLLED_BACK", (
        f"The already-terminal episode must be left untouched, got {terminal_episode['status']}"
    )
    assert terminal_episode["rollback_count"] == 1, (
        f"The rolled-back episode must keep its single rollback mark, got "
        f"{terminal_episode['rollback_count']}"
    )

    offer_after = read_offer(offer["id"])
    assert offer_after["availability_status"] == "WITHDRAWN", (
        f"The LIVE offer must be withdrawn by the cascade, got {offer_after['availability_status']}"
    )
    assert offer_after["approval_status"] == "APPROVED", (
        f"The governance dimension must not move with the storefront one, got "
        f"{offer_after['approval_status']}"
    )
    assert read_live_event(event["id"])["status"] == "CANCELLED", (
        "The still-PLANNED live event must be cancelled by the cascade"
    )
    assert read_purchase(purchase["id"])["status"] == "DENIED", (
        "The PENDING purchase of the withdrawn offer must be denied by the cascade"
    )

    season_after = read_season(season["id"])
    assert season_after["live_offer_count"] == 0, (
        f"live_offer_count must be set to 0 by the cascade, got {season_after['live_offer_count']}"
    )
    assert season_after["pending_revenue_minor"] == 0, (
        f"pending_revenue_minor must drop by the denied purchase's quoted price, got "
        f"{season_after['pending_revenue_minor']}"
    )
    assert read_player(player["id"])["pending_spend_minor"] == 0, (
        "The buyer's pending_spend_minor must drop by the denied purchase's quoted price"
    )


# ---------------------------------------------------------------------------
# Cyclic spend gate: two different routes back to UNRESTRICTED
# ---------------------------------------------------------------------------
def test_spend_state_returns_to_unrestricted_by_refund_and_then_by_unlock():
    """PRD §3.7: "A player enters the cooldown band when `spend_30d_minor` reaches or exceeds 40000 minor units while remaining below 75000, and enters the lock band when it reaches or exceeds 75000; both boundaries are inclusive, so exactly 40000 is already cooldown and exactly 75000 is already lock."
    PRD §3.7: "The rolling spend figure is computed by taking the window that begins 30 days before the current clock and ends at the clock itself, summing the `price_paid_minor` of every purchase of that player whose `status` is `SETTLED` or `REFUNDED` and whose `settled_at` falls inside that window with both ends inclusive, then subtracting the `refund_amount_minor` of every refund request in `EXECUTED` status against that player's purchases whose `executed_at` falls inside the same inclusive window, and finally flooring the result at 0 so it can never go negative."
    PRD §3.7: "**Step three** selects the restocking fee tier, and it is keyed on the Step-two figure and on nothing else: the tier is 0 basis points when `refund_base_minor` is strictly below 1000 minor units, 500 basis points when it is at least 1000 but strictly below 5000, and 1000 basis points at 5000 or above."
    PRD §3.7: "**Step four** computes `restock_fee_minor`: `refund_base_minor` multiplied by that tier, divided by 10000, rounded half up."
    PRD §3.7: "**Step five** computes `refund_amount_minor`: `refund_base_minor` minus `restock_fee_minor`, floored at 0."
    PRD §3.7: "**Step six** computes `goodwill_credit_minor`: half of the restocking fee — that is, `restock_fee_minor` multiplied by 5000, divided by 10000, rounded half up — but only when the player holds a currency account whose `currency_code` is `SOFT_COIN` and the player's `spend_state` is not `LOCKED`; when either condition fails the goodwill credit is 0."
    PRD §3.7: "Where `goodwill_credit_minor` came out greater than 0, it is appended as a further ledger entry with `direction` `FAUCET` and `source_kind` `ADMIN_ADJUSTMENT` against the player's `SOFT_COIN` account."
    PRD §3.7: "The invariant worth stating: when the purchase had consumed nothing, both the affected accounts' `balance_minor` and the difference between the season's `gross_faucet_minor` and `gross_sink_minor` return exactly to their pre-settlement values."
    PRD §3.7: "A player in `COOLDOWN` returns `COOLDOWN → UNRESTRICTED` automatically when a recompute triggered by a refund execution or by a monitoring run brings `spend_30d_minor` back strictly below 40000 minor units — refund execution being the natural compensating trigger for the cooldown cycle."
    PRD §3.7: "Locking is a cascade: every currency account of the player is moved to `FROZEN` with each account's `version` moving by 1, every purchase of the player still in `PENDING` is denied with the `deny_reason` `SPEND_LOCKED` while the season's `pending_revenue_minor` and the player's `pending_spend_minor` are each lowered by that purchase's `quoted_price_minor`, and the player's own `version` moves by 1."
    PRD §3.7: "A player in `LOCKED`, by contrast, is only released by a `ComplianceOfficer` supplying an `action` of `UNLOCK`, which reactivates every currency account back to `ACTIVE` with each account's `version` moving by 1, and lands the player directly on `UNRESTRICTED`; a locked player never falls back to `COOLDOWN`."
    PRD §3.6: "On the player, `pending_spend_minor` falls by the quoted price, `lifetime_spend_minor` rises by the price paid, `spend_30d_minor` is recomputed, `spend_state` is re-evaluated against the responsible-spending thresholds, `pacing_bp_realized` and `retention_band` are recomputed, and `version` moves by 1."

    Design: Corner/state_machines/corner_sm_player_spend_state_returns_to_unrestricted_twice
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_whale", region_code="NA")
    gem_account = open_account(player["id"], "HARD_GEM")
    soft_account = open_account(player["id"], "SOFT_COIN")

    offer = create_live_single_line_offer(
        season["id"],
        sku="WHALE_40K",
        base_price_minor=40000,
        declared_value_minor=50000,
        granted_currency_code="HARD_GEM",
        granted_amount_minor=40000,
    )
    purchase = create_pending_purchase(player["id"], offer["id"])
    settle_purchase(purchase["id"])
    request = submit_refund(purchase["id"], player["id"], reason_code="DISSATISFIED")
    decide_refund(request["id"], "APPROVE", "Goodwill for a first-time buyer")

    executed = validate_success(api_client.execute_refund_request(request["id"], LIVEOPS))
    after_refund = read_player(player["id"])

    assert executed["restock_fee_minor"] == 4000, (
        f"Expected restock_fee_minor 4000, got {executed['restock_fee_minor']}"
    )
    assert executed["refund_amount_minor"] == 36000, (
        f"Expected refund_amount_minor 36000, got {executed['refund_amount_minor']}"
    )
    assert executed["goodwill_credit_minor"] == 2000, (
        f"Expected goodwill_credit_minor 2000, got {executed['goodwill_credit_minor']}"
    )
    assert after_refund["spend_30d_minor"] == 4000, (
        f"Expected spend_30d_minor 4000 after the refund execution, got "
        f"{after_refund['spend_30d_minor']}"
    )
    assert after_refund["spend_state"] == "UNRESTRICTED", (
        "The refund execution must pull the player out of COOLDOWN, got "
        f"{after_refund['spend_state']}"
    )

    locked = lock_player(player["id"], note="Chargeback review")
    assert locked["spend_state"] == "LOCKED", (
        f"The compliance LOCK must land the player on LOCKED, got {locked['spend_state']}"
    )
    assert read_account(gem_account["id"])["status"] == "FROZEN", (
        "Locking must freeze every currency account of the player"
    )

    unlocked = unlock_player(player["id"], note="Cleared by the payment processor")
    assert unlocked["spend_state"] == "UNRESTRICTED", (
        f"The compliance UNLOCK must land the player directly on UNRESTRICTED, got "
        f"{unlocked['spend_state']}"
    )

    gem_after = read_account(gem_account["id"])
    assert gem_after["status"] == "ACTIVE", (
        f"Unlocking must reactivate every currency account, got {gem_after['status']}"
    )
    assert gem_after["balance_minor"] == 0, (
        f"An unconsumed refund must return the granted balance to 0, got {gem_after['balance_minor']}"
    )
    assert read_account(soft_account["id"])["balance_minor"] == 2000, (
        "The goodwill credit must be minted into the player's SOFT_COIN account"
    )
    assert read_player(player["id"])["lifetime_spend_minor"] == 40000, (
        "lifetime_spend_minor must keep the settled price paid"
    )


# ---------------------------------------------------------------------------
# Guarded transition: offer submit reads the season's status
# ---------------------------------------------------------------------------
def test_offer_submit_is_guarded_on_the_season_being_live():
    """PRD §3.5: "An `EconomyDesigner` first submits a `DRAFT` offer into review, which requires the offer's `approval_status` to be `DRAFT`, its `availability_status` to be `OFFLINE`, and its season to be `LIVE` (otherwise `ERR_SEASON_NOT_LIVE`); the submission recomputes `fairness_index_bp` and moves the offer's `version` by 1, touching the storefront dimension not at all."
    PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."
    PRD §3.1: "A `ContentProducer` opens the season for business by moving it from `PLANNED` to `LIVE`, which is permitted only while the season is still `PLANNED`."

    Design: Corner/state_machines/corner_sm_guarded_offer_submit_requires_live_season
    """
    set_clock(CLOCK_EPOCH)
    season = get_success_data(api_client.create_season(create_season_payload(), PRODUCER))
    offer = create_draft_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="PACK_A",
        price_tier="T1",
        list_price_minor=499,
        line_items=[offer_line_item("COIN_PACK_A", 499, 700, "SOFT_COIN", 700)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-10T00:00:00Z",
    )

    validate_error(
        api_client.submit_offer(offer["id"], DESIGNER),
        ApiErrorId.ERR_SEASON_NOT_LIVE.value,
        409,
    )
    assert read_offer(offer["id"])["approval_status"] == "DRAFT", (
        "The refused submit must leave the governance dimension on DRAFT"
    )

    live_season = validate_success(
        api_client.set_season_status(season["id"], {"to_status": "LIVE"}, PRODUCER)
    )
    assert live_season["status"] == "LIVE", (
        f"The season must be LIVE before the second submit, got {live_season['status']}"
    )

    submitted = validate_success(api_client.submit_offer(offer["id"], DESIGNER))
    assert submitted["approval_status"] == "IN_REVIEW", (
        f"The identical submit must now reach IN_REVIEW, got {submitted['approval_status']}"
    )
    assert submitted["revision_count"] == 0, (
        f"Submitting must not touch revision_count, got {submitted['revision_count']}"
    )


# ---------------------------------------------------------------------------
# Side effects of publishing a second probability table
# ---------------------------------------------------------------------------
def test_publishing_a_second_disclosure_supersedes_the_first():
    """PRD §3.5: "A `ComplianceOfficer` publishes the table, carrying it `DRAFT → PUBLISHED`."
    PRD §3.5: "On success the table's `published_at` is stamped with the clock and `published_by_user_id` with the acting `X-User-ID`; any other table of the same offer that was `PUBLISHED` is carried `PUBLISHED → SUPERSEDED`, its own `version` moving by 1; and the offer's `disclosure_state` becomes `PUBLISHED` with the offer's `version` moving by 1."
    PRD §3.5: "Two figures are computed and stored on the table: `total_probability_bp`, the sum of the entries' `probability_bp`, which must come to exactly 10000 basis points or the request is refused with `ERR_DISCLOSURE_PROBABILITY_SUM`; and `expected_value_minor`, the sum over all entries of each entry's `probability_bp` multiplied by its `item_value_minor`, that total divided by 10000, and the result rounded half up."

    Design: Corner/state_machines/corner_sm_disclosure_publish_supersedes_previous
    """
    season = create_live_season()
    offer = create_draft_offer(season["id"], **_CRATE_OFFER_OVERRIDES)
    first = draft_disclosure(offer["id"], entries=_CRATE_TABLE_1)
    publish_disclosure(offer["id"], first["id"])
    second = draft_disclosure(offer["id"], entries=_CRATE_TABLE_2)

    published = validate_success(
        api_client.publish_disclosure(offer["id"], second["id"], COMPLIANCE)
    )

    assert published["status"] == "PUBLISHED", (
        f"The second table must land on PUBLISHED, got {published['status']}"
    )
    assert published["published_at"].startswith("2026-08-01T00:00:00"), (
        f"published_at must be stamped with the logical clock, got {published['published_at']}"
    )
    assert published["published_by_user_id"] == OPERATOR_IDS["ComplianceOfficer"], (
        "published_by_user_id must record the acting compliance officer, got "
        f"{published['published_by_user_id']}"
    )
    assert published["total_probability_bp"] == 10000, (
        f"Expected total_probability_bp 10000, got {published['total_probability_bp']}"
    )
    assert published["expected_value_minor"] == 405, (
        f"Expected expected_value_minor 405, got {published['expected_value_minor']}"
    )
    assert _disclosure_row(offer["id"], first["id"])["status"] == "SUPERSEDED", (
        "The previously published table must be carried to SUPERSEDED"
    )
    assert read_offer(offer["id"])["disclosure_state"] == "PUBLISHED", (
        "The offer's disclosure_state must stay PUBLISHED across the swap"
    )
