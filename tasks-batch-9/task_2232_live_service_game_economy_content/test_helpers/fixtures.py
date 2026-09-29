"""Composite setup helpers.

Every helper builds its preconditions from scratch through the documented endpoints,
because each test starts against an empty database. Setup calls use the lenient
validator so a broken precondition surfaces as a clear setup failure.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH
from .factories import (
    create_adjustment_payload,
    create_balance_change_payload,
    create_cluster_payload,
    create_comms_notice_payload,
    create_disclosure_payload,
    create_episode_payload,
    create_live_event_payload,
    create_monitoring_run_payload,
    create_offer_payload,
    create_player_payload,
    create_season_payload,
    single_line_offer_payload,
)
from .test_users import COMPLIANCE, DESIGNER, LIVEOPS, PRODUCER, make_player_headers

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> str:
    """Move the server logical clock and return the instant it now reads."""
    data = get_success_data(api_client.set_clock(to_iso8601, LIVEOPS))
    return data.get("current_utc", to_iso8601)


def reset_clock() -> str:
    """Put the clock back on the documented start instant."""
    return set_clock(CLOCK_EPOCH)


# ---------------------------------------------------------------------------
# Tier 1: seasons
# ---------------------------------------------------------------------------


def create_planned_season(**overrides) -> Dict[str, Any]:
    """A season shell in PLANNED at the documented clock start."""
    return get_success_data(api_client.create_season(create_season_payload(**overrides), PRODUCER))


def create_live_season(set_clock_first: bool = True, **overrides) -> Dict[str, Any]:
    """Clock at the start instant, season created and driven to LIVE. Returns the LIVE season."""
    if set_clock_first:
        reset_clock()
    season = create_planned_season(**overrides)
    return get_success_data(
        api_client.set_season_status(season["id"], {"to_status": "LIVE"}, PRODUCER)
    )


def season_version(season_id: str) -> int:
    """The season's current optimistic-concurrency counter."""
    return get_success_data(api_client.get_season(season_id, LIVEOPS))["version"]


def read_season(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_season(season_id, LIVEOPS))


def conclude_season(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.set_season_status(season_id, {"to_status": "CONCLUDED"}, PRODUCER))


def archive_season(season_id: str) -> Dict[str, Any]:
    """Drive a LIVE season all the way to ARCHIVED."""
    conclude_season(season_id)
    return get_success_data(api_client.set_season_status(season_id, {"to_status": "ARCHIVED"}, PRODUCER))


# ---------------------------------------------------------------------------
# Tier 1: episodes
# ---------------------------------------------------------------------------


def create_draft_episode(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_episode(create_episode_payload(season_id, **overrides), PRODUCER)
    )


def create_scheduled_episode(season_id: str, **overrides) -> Dict[str, Any]:
    """Episode created in DRAFT and scheduled."""
    episode = create_draft_episode(season_id, **overrides)
    return get_success_data(api_client.schedule_episode(episode["id"], PRODUCER))


def release_episode_at(episode_id: str, clock_iso: Optional[str] = None) -> Dict[str, Any]:
    """Advance the clock to the release instant (when given) and take the episode LIVE."""
    if clock_iso is not None:
        set_clock(clock_iso)
    return get_success_data(api_client.release_episode(episode_id, PRODUCER))


def rollback_episode_at(episode_id: str, reason: str, clock_iso: Optional[str] = None) -> Dict[str, Any]:
    if clock_iso is not None:
        set_clock(clock_iso)
    return get_success_data(api_client.rollback_episode(episode_id, {"reason": reason}, LIVEOPS))


def create_live_episode(season_id: str, release_at: str = "2026-08-02T00:00:00Z", **overrides) -> Dict[str, Any]:
    """Episode scheduled for release_at, then released with the clock standing on that instant."""
    overrides.setdefault("planned_release_at", release_at)
    episode = create_scheduled_episode(season_id, **overrides)
    return release_episode_at(episode["id"], release_at)


# ---------------------------------------------------------------------------
# Tier 2: players, accounts, ledger
# ---------------------------------------------------------------------------


def create_player(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_player(create_player_payload(season_id, **overrides), LIVEOPS)
    )


def open_account(player_id: str, currency_code: str = "SOFT_COIN") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_currency_account(player_id, {"currency_code": currency_code}, LIVEOPS)
    )


def create_player_with_account(
    season_id: str, currency_code: str = "SOFT_COIN", **player_overrides
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Player plus one open currency account. Returns (player, account)."""
    player = create_player(season_id, **player_overrides)
    account = open_account(player["id"], currency_code)
    return player, account


def append_adjustment(
    account_id: str,
    direction: str = "FAUCET",
    amount_minor: int = 1000,
    source_kind: str = "ADMIN_ADJUSTMENT",
    purchase_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Append an operator faucet or sink flow. Returns the updated account."""
    payload = create_adjustment_payload(
        direction=direction, amount_minor=amount_minor, source_kind=source_kind
    )
    if purchase_id is not None:
        payload["purchase_id"] = purchase_id
    return get_success_data(api_client.create_adjustment(account_id, payload, LIVEOPS))


def fund_account(account_id: str, amount_minor: int) -> Dict[str, Any]:
    """Give an account a starting balance through an operator faucet."""
    return append_adjustment(account_id, "FAUCET", amount_minor, "ADMIN_ADJUSTMENT")


def ingest_xp(player_id: str, xp_delta: int, sessions_delta: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"xp_delta": xp_delta}
    if sessions_delta is not None:
        payload["sessions_delta"] = sessions_delta
    return get_success_data(api_client.ingest_engagement_event(player_id, payload, LIVEOPS))


def lock_player(player_id: str, note: str = "Responsible spending review") -> Dict[str, Any]:
    return get_success_data(
        api_client.set_spend_guard(player_id, {"action": "LOCK", "note": note}, COMPLIANCE)
    )


def unlock_player(player_id: str, note: str = "Review cleared") -> Dict[str, Any]:
    return get_success_data(
        api_client.set_spend_guard(player_id, {"action": "UNLOCK", "note": note}, COMPLIANCE)
    )


def read_player(player_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_player(player_id, LIVEOPS))


def read_account(account_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_currency_account(account_id, LIVEOPS))


def list_ledger(**params) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_ledger_entries(LIVEOPS, params=params or None))


# ---------------------------------------------------------------------------
# Tier 2: capacity clusters and live events
# ---------------------------------------------------------------------------


def create_cluster(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_cluster(create_cluster_payload(**overrides), LIVEOPS))


def create_planned_event(season_id: str, cluster_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_live_event(create_live_event_payload(season_id, cluster_id, **overrides), PRODUCER)
    )


def create_approved_event(season_id: str, cluster_id: str, **overrides) -> Dict[str, Any]:
    """Event placed on the calendar and approved, so its forecast is reserved on the cluster."""
    event = create_planned_event(season_id, cluster_id, **overrides)
    return get_success_data(api_client.approve_live_event(event["id"], LIVEOPS))


def create_running_event(season_id: str, cluster_id: str, **overrides) -> Dict[str, Any]:
    event = create_approved_event(season_id, cluster_id, **overrides)
    return get_success_data(api_client.start_live_event(event["id"], LIVEOPS))


def read_cluster(cluster_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_cluster(cluster_id, LIVEOPS))


def read_live_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_live_event(event_id, LIVEOPS))


# ---------------------------------------------------------------------------
# Tier 3: offers, disclosures, publication
# ---------------------------------------------------------------------------


def create_draft_offer(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_offer(create_offer_payload(season_id, **overrides), DESIGNER))


def create_single_line_offer(
    season_id: str,
    sku: str = "STARTER_5K",
    base_price_minor: int = 5000,
    declared_value_minor: int = 6000,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_offer(
            single_line_offer_payload(
                season_id, sku, base_price_minor, declared_value_minor, **overrides
            ),
            DESIGNER,
        )
    )


def submit_offer(offer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.submit_offer(offer_id, DESIGNER))


def approve_offer(offer_id: str, note: str = "Value ratio and window are within policy") -> Dict[str, Any]:
    return get_success_data(
        api_client.review_offer(offer_id, {"decision": "APPROVE", "note": note}, COMPLIANCE)
    )


def create_approved_offer(season_id: str, **overrides) -> Dict[str, Any]:
    """Offer authored, submitted for review and approved (still OFFLINE)."""
    offer = create_draft_offer(season_id, **overrides)
    submit_offer(offer["id"])
    return approve_offer(offer["id"])


def publish_offer(offer_id: str, season_id: str) -> Dict[str, Any]:
    """Publish with the season's current version pinned."""
    return get_success_data(
        api_client.publish_offer(
            offer_id, {"expected_season_version": season_version(season_id)}, DESIGNER
        )
    )


def create_live_offer(season_id: str, **overrides) -> Dict[str, Any]:
    """Offer walked all the way to APPROVED / LIVE on the storefront."""
    offer = create_approved_offer(season_id, **overrides)
    return publish_offer(offer["id"], season_id)


def create_live_single_line_offer(
    season_id: str,
    sku: str = "STARTER_5K",
    base_price_minor: int = 5000,
    declared_value_minor: int = 6000,
    **overrides,
) -> Dict[str, Any]:
    offer = create_single_line_offer(
        season_id, sku, base_price_minor, declared_value_minor, **overrides
    )
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    return publish_offer(offer["id"], season_id)


def draft_disclosure(offer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_disclosure(offer_id, create_disclosure_payload(**overrides), DESIGNER)
    )


def publish_disclosure(offer_id: str, disclosure_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_disclosure(offer_id, disclosure_id, COMPLIANCE))


def create_offer_with_published_disclosure(season_id: str, **overrides) -> Dict[str, Any]:
    """A randomized-item offer whose probability table is published, so it can go LIVE."""
    overrides.setdefault("offer_type", "LOOT_BOX")
    offer = create_draft_offer(season_id, **overrides)
    disclosure = draft_disclosure(offer["id"])
    publish_disclosure(offer["id"], disclosure["id"])
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    return get_success_data(api_client.get_offer(offer["id"], DESIGNER))


def create_live_loot_box_offer(season_id: str, **overrides) -> Dict[str, Any]:
    offer = create_offer_with_published_disclosure(season_id, **overrides)
    return publish_offer(offer["id"], season_id)


def read_offer(offer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_offer(offer_id, DESIGNER))


def offer_version(offer_id: str) -> int:
    return read_offer(offer_id)["version"]


def suspend_offer(offer_id: str, reason: str = "Storefront hotfix") -> Dict[str, Any]:
    return get_success_data(
        api_client.set_offer_availability(offer_id, {"to_status": "SUSPENDED", "reason": reason}, LIVEOPS)
    )


def resume_offer(offer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_offer_availability(offer_id, {"to_status": "LIVE"}, LIVEOPS)
    )


def withdraw_offer(offer_id: str, reason: str = "Retired from the storefront") -> Dict[str, Any]:
    return get_success_data(
        api_client.set_offer_availability(offer_id, {"to_status": "WITHDRAWN", "reason": reason}, LIVEOPS)
    )


def quote_offer(offer_id: str, player_id: str) -> Dict[str, Any]:
    """Personalized quote read as the player itself."""
    return get_success_data(
        api_client.get_offer_quote(offer_id, make_player_headers(player_id), params={"player_id": player_id})
    )


# ---------------------------------------------------------------------------
# Tier 3: purchases and refunds
# ---------------------------------------------------------------------------


def create_pending_purchase(player_id: str, offer_id: str) -> Dict[str, Any]:
    """Purchase created by the player with the offer's live version pinned."""
    return get_success_data(
        api_client.create_purchase(
            {
                "player_id": player_id,
                "offer_id": offer_id,
                "expected_offer_version": offer_version(offer_id),
            },
            make_player_headers(player_id),
        )
    )


def settle_purchase(purchase_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.settle_purchase(purchase_id, {"outcome": "SETTLED"}, LIVEOPS))


def deny_purchase(purchase_id: str, deny_reason: str = "MANUAL_REVIEW") -> Dict[str, Any]:
    return get_success_data(
        api_client.settle_purchase(purchase_id, {"outcome": "DENIED", "deny_reason": deny_reason}, LIVEOPS)
    )


def create_settled_purchase(player_id: str, offer_id: str) -> Dict[str, Any]:
    purchase = create_pending_purchase(player_id, offer_id)
    return settle_purchase(purchase["id"])


def read_purchase(purchase_id: str, player_id: Optional[str] = None) -> Dict[str, Any]:
    headers = make_player_headers(player_id) if player_id else LIVEOPS
    return get_success_data(api_client.get_purchase(purchase_id, headers))


def submit_refund(purchase_id: str, player_id: str, reason_code: str = "ACCIDENTAL") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_refund_request(
            {"purchase_id": purchase_id, "reason_code": reason_code},
            make_player_headers(player_id),
        )
    )


def decide_refund(
    request_id: str,
    decision: str = "APPROVE",
    decision_note: str = "Charged within minutes of an accidental tap",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_refund_request(
            request_id, {"decision": decision, "decision_note": decision_note}, COMPLIANCE
        )
    )


def execute_refund(request_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.execute_refund_request(request_id, LIVEOPS))


def create_approved_refund(
    purchase_id: str, player_id: str, reason_code: str = "ACCIDENTAL"
) -> Dict[str, Any]:
    request = submit_refund(purchase_id, player_id, reason_code)
    return decide_refund(request["id"])


def read_refund(request_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_refund_request(request_id, LIVEOPS))


# ---------------------------------------------------------------------------
# Tier 4: full purchase pipeline in one call
# ---------------------------------------------------------------------------


def setup_live_offer_and_player(
    season_overrides: Optional[Dict[str, Any]] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
    player_overrides: Optional[Dict[str, Any]] = None,
    account_currencies: Tuple[str, ...] = ("HARD_GEM",),
) -> Dict[str, Any]:
    """LIVE season + LIVE single-line offer + player holding the named accounts.

    Returns a dict with keys: season, offer, player, accounts (currency_code -> account).
    """
    season = create_live_season(**(season_overrides or {}))
    offer = create_live_single_line_offer(season["id"], **(offer_overrides or {}))
    player = create_player(season["id"], **(player_overrides or {}))
    accounts = {code: open_account(player["id"], code) for code in account_currencies}
    return {"season": season, "offer": offer, "player": player, "accounts": accounts}


def setup_settled_purchase_scenario(
    price_minor: int = 5000,
    declared_value_minor: int = 6000,
    granted_currency_code: str = "HARD_GEM",
    player_overrides: Optional[Dict[str, Any]] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """LIVE season, LIVE offer at price_minor, player with the granted currency account,
    and one SETTLED purchase of that offer.

    Returns a dict with keys: season, offer, player, account, purchase.
    """
    overrides = dict(offer_overrides or {})
    overrides.setdefault("granted_currency_code", granted_currency_code)
    season = create_live_season()
    offer = create_live_single_line_offer(
        season["id"],
        base_price_minor=price_minor,
        declared_value_minor=declared_value_minor,
        **overrides,
    )
    player = create_player(season["id"], **(player_overrides or {}))
    account = open_account(player["id"], granted_currency_code)
    purchase = create_settled_purchase(player["id"], offer["id"])
    return {
        "season": season,
        "offer": offer,
        "player": player,
        "account": account,
        "purchase": purchase,
    }


# ---------------------------------------------------------------------------
# Tier 4: balance changes and community notices
# ---------------------------------------------------------------------------


def create_draft_balance_change(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_balance_change(create_balance_change_payload(season_id, **overrides), DESIGNER)
    )


def advance_balance_change(change_id: str, to_stage: str, season_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.advance_balance_change(
            change_id,
            {"to_stage": to_stage, "expected_season_version": season_version(season_id)},
            LIVEOPS,
        )
    )


def draft_comms_notice(change_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_comms_notice(change_id, create_comms_notice_payload(**overrides), DESIGNER)
    )


def publish_comms_notice(change_id: str, notice_id: str) -> Dict[str, Any]:
    """Published by compliance, which is never the designer who authored the change."""
    return get_success_data(api_client.publish_comms_notice(change_id, notice_id, COMPLIANCE))


def create_balance_change_at_stage(
    season_id: str,
    stage: str = "CANARY",
    with_drafted_notice: bool = False,
    with_published_notice: bool = False,
    **overrides,
) -> Dict[str, Any]:
    """Author a tuning change and walk it one stage at a time up to `stage`.

    stage is one of DRAFT, SHADOW, CANARY, LIVE. Reaching LIVE requires a published notice,
    so with_published_notice is forced on for that target.
    """
    change = create_draft_balance_change(season_id, **overrides)
    change_id = change["id"]
    notice = None
    if with_drafted_notice or with_published_notice or stage == "LIVE":
        notice = draft_comms_notice(change_id)
    if with_published_notice or stage == "LIVE":
        publish_comms_notice(change_id, notice["id"])
    for step in ("SHADOW", "CANARY", "LIVE"):
        change = advance_balance_change(change_id, step, season_id)
        if step == stage:
            break
    return change


def read_balance_change(change_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_balance_change(change_id, LIVEOPS))


# ---------------------------------------------------------------------------
# Tier 5: monitoring epochs
# ---------------------------------------------------------------------------


def open_monitoring_run(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_monitoring_run(create_monitoring_run_payload(season_id, **overrides), LIVEOPS)
    )


def compute_monitoring_run(run_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.compute_monitoring_run(run_id, LIVEOPS))


def certify_monitoring_run(run_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.decide_monitoring_run(run_id, {"decision": "CERTIFY"}, LIVEOPS))


def void_monitoring_run(run_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.decide_monitoring_run(run_id, {"decision": "VOID"}, LIVEOPS))


def run_monitoring_epoch(
    season_id: str,
    epoch_no: int = 1,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-03T00:00:00Z",
    certify: bool = False,
) -> Dict[str, Any]:
    """Open one epoch over the given window and compute it. Optionally certify the result."""
    run = open_monitoring_run(
        season_id, epoch_no=epoch_no, window_start=window_start, window_end=window_end
    )
    computed = compute_monitoring_run(run["id"])
    if certify:
        return certify_monitoring_run(run["id"])
    return computed


def drive_season_to_inflated(
    season_id: str,
    account_id: str,
    faucet_minor: int = 1000,
    sink_minor: int = 100,
    epoch_no: int = 1,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-03T00:00:00Z",
) -> Dict[str, Any]:
    """Seed a faucet-heavy ledger inside one epoch window and compute it, which rewrites the
    season posture to the resulting band. Returns the computed run."""
    append_adjustment(account_id, "FAUCET", faucet_minor, "ADMIN_ADJUSTMENT")
    append_adjustment(account_id, "SINK", sink_minor, "OFFER_SPEND")
    return run_monitoring_epoch(
        season_id, epoch_no=epoch_no, window_start=window_start, window_end=window_end
    )


# ---------------------------------------------------------------------------
# Economy reads
# ---------------------------------------------------------------------------


def economy_summary(season_id: str, variant: str, epoch_no: Optional[int] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"variant": variant}
    if epoch_no is not None:
        params["epoch_no"] = epoch_no
    return get_success_data(api_client.get_economy_summary(season_id, LIVEOPS, params=params))


def pacing(player_id: str, variant: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pacing(player_id, LIVEOPS, params={"variant": variant}))
