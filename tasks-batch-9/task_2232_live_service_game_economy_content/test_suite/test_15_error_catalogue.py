"""Error catalogue coverage: every documented code is reachable through its own trigger."""

from typing import Any, Dict, List

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    approve_offer,
    create_cluster,
    create_draft_balance_change,
    create_live_season,
    create_pending_purchase,
    create_player,
    create_scheduled_episode,
    create_single_line_offer,
    disclosure_entry,
    draft_comms_notice,
    draft_disclosure,
    make_player_headers,
    open_account,
    open_monitoring_run,
    publish_comms_notice,
    publish_disclosure,
    publish_offer,
    read_account,
    read_balance_change,
    read_cluster,
    read_offer,
    read_player,
    read_purchase,
    read_refund,
    read_season,
    season_version,
    settle_purchase,
    submit_offer,
    submit_refund,
    validate_error,
    validate_paginated,
    validate_success,
)

CRATE_ENTRIES: List[Dict[str, Any]] = [
    disclosure_entry("COMMON_SKIN", 8500, 200),
    disclosure_entry("RARE_SKIN", 1400, 1500),
    disclosure_entry("MYTHIC_SKIN", 100, 9000),
]


def _live_loot_box(season_id: str, sku: str) -> Dict[str, Any]:
    """A randomized offer priced 300, table published, approved and live on the storefront."""
    offer = create_single_line_offer(
        season_id,
        sku,
        300,
        400,
        offer_type="LOOT_BOX",
        granted_currency_code="HARD_GEM",
        granted_amount_minor=300,
    )
    table = draft_disclosure(offer["id"], entries=CRATE_ENTRIES)
    publish_disclosure(offer["id"], table["id"])
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    live = publish_offer(offer["id"], season_id)
    return {"offer": live, "disclosure": table}


def _live_single_line(season_id: str, sku: str, base: int, declared: int, **overrides):
    """Author, review and publish a one-line offer, pinning the season version at publish."""
    offer = create_single_line_offer(season_id, sku, base, declared, **overrides)
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    return publish_offer(offer["id"], season_id)


def test_every_secondary_collection_reports_its_own_not_found_code(
    api, producer_headers, liveops_headers, compliance_headers
):
    """PRD §2.11: "3. Existence of every path-addressed resource, left to right, on every path-parameterised endpoint (the family of 404 codes listed in §2.5)."

    PRD §2.5: "Where a URL carries more than one identifier, the server resolves them strictly left to right and fails on the first one that does not exist."

    PRD §2.5: "A request naming a disclosure under an offer resolves the `offer_id` first, so a bad offer identifier yields `ERR_OFFER_NOT_FOUND` and the disclosure is never looked up; only once the offer is known does a bad `disclosure_id` yield `ERR_DISCLOSURE_NOT_FOUND`."

    PRD §2.5: "The same ordering governs community notices under a tuning change (`change_id` before `notice_id`, giving `ERR_BALANCE_CHANGE_NOT_FOUND` before `ERR_COMMS_NOTICE_NOT_FOUND`) and currency accounts under a player (`player_id` before the account)."

    PRD §2.5: "The remaining single-identifier lookups follow the same shape: `ERR_EPISODE_NOT_FOUND` for an unknown `episode_id`, `ERR_LIVE_EVENT_NOT_FOUND` for an unknown `event_id`, `ERR_LEDGER_ENTRY_NOT_FOUND` for an unknown `entry_id`, `ERR_REFUND_REQUEST_NOT_FOUND` for an unknown `request_id`, and `ERR_MONITORING_RUN_NOT_FOUND` for an unknown `run_id`."

    PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."

    PRD §3.8: "The change is stored in `DRAFT` with the authoring operator recorded as `authored_by_user_id`, `promoted_by_user_id` and `pre_live_sink_rate_bp` null, and `comms_state` at `MISSING`."

    Design: Corner/errors/corner_err_not_found_for_every_secondary_collection
    """
    season = create_live_season()
    offer = create_single_line_offer(
        season["id"],
        "NF_PACK",
        900,
        1200,
        offer_type="BUNDLE",
        granted_currency_code="SOFT_COIN",
        granted_amount_minor=1200,
    )
    change = create_draft_balance_change(season["id"], rationale="Not-found fixture")

    validate_error(
        api.get_episode(NON_EXISTENT_UUID, producer_headers), ApiErrorId.ERR_EPISODE_NOT_FOUND
    )
    validate_error(
        api.get_live_event(NON_EXISTENT_UUID, liveops_headers),
        ApiErrorId.ERR_LIVE_EVENT_NOT_FOUND,
    )
    validate_error(
        api.get_currency_account(NON_EXISTENT_UUID, liveops_headers),
        ApiErrorId.ERR_CURRENCY_ACCOUNT_NOT_FOUND,
    )
    validate_error(
        api.get_ledger_entry(NON_EXISTENT_UUID, liveops_headers),
        ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND,
    )
    validate_error(
        api.publish_disclosure(offer["id"], NON_EXISTENT_UUID, compliance_headers),
        ApiErrorId.ERR_DISCLOSURE_NOT_FOUND,
    )
    validate_error(
        api.get_refund_request(NON_EXISTENT_UUID, liveops_headers),
        ApiErrorId.ERR_REFUND_REQUEST_NOT_FOUND,
    )
    validate_error(
        api.get_balance_change(NON_EXISTENT_UUID, liveops_headers),
        ApiErrorId.ERR_BALANCE_CHANGE_NOT_FOUND,
    )
    validate_error(
        api.publish_comms_notice(change["id"], NON_EXISTENT_UUID, compliance_headers),
        ApiErrorId.ERR_COMMS_NOTICE_NOT_FOUND,
    )

    assert read_offer(offer["id"])["disclosure_state"] == "NOT_REQUIRED"
    assert read_balance_change(change["id"])["stage"] == "DRAFT"


def test_offer_disclosure_purchase_and_refund_report_distinct_invalid_state_codes(
    api, liveops_headers, compliance_headers, designer_headers
):
    """PRD §3.5: "Rejections name the dimension at fault — `ERR_OFFER_INVALID_APPROVAL_STATE` for a governance transition that does not exist from the current `approval_status`, and `ERR_OFFER_INVALID_AVAILABILITY_STATE` for a storefront transition that does not exist from the current `availability_status`."

    PRD §3.5: "Publication requires the table to be `DRAFT` (otherwise `ERR_DISCLOSURE_INVALID_STATE`), requires its `total_probability_bp` to be exactly 10000 (otherwise `ERR_DISCLOSURE_PROBABILITY_SUM`, the same check applied a second time at the moment of record), and requires the owning offer not to be `WITHDRAWN` (otherwise `ERR_OFFER_INVALID_AVAILABILITY_STATE`)."

    PRD §3.6: "Both outcomes require the purchase to be `PENDING`, anything else yielding `ERR_PURCHASE_INVALID_STATE`."

    PRD §3.7: "Execution is a `LiveOpsCommander` action, permitted only when the request is `APPROVED` and the purchase is still `SETTLED`, and it runs the compensating cascade in four levels."

    PRD §2.11: "8. The target resource is in a state from which the requested transition exists, on every transition endpoint (`ERR_SEASON_INVALID_STATE`, `ERR_EPISODE_INVALID_STATE`, `ERR_CLUSTER_INVALID_STATE`, `ERR_EVENT_INVALID_STATE`, `ERR_OFFER_INVALID_APPROVAL_STATE`, `ERR_OFFER_INVALID_AVAILABILITY_STATE`, `ERR_DISCLOSURE_INVALID_STATE`, `ERR_PURCHASE_INVALID_STATE`, `ERR_REFUND_INVALID_STATE`, `ERR_BALANCE_CHANGE_INVALID_STATE`, `ERR_COMMS_NOTICE_INVALID_STATE`, `ERR_MONITORING_RUN_INVALID_STATE`)."

    PRD §3.6: "Then, for each entry of the offer's `line_items` taken in ascending line `sku` order, a ledger entry is appended with `direction` `FAUCET`, `source_kind` `PURCHASE_GRANT`, an `amount_minor` equal to that line's `granted_amount_minor`, the purchase as its `purchase_id`, and the offer's season as its `season_id`; the purchase's `granted_total_minor` becomes the sum of those amounts."

    Design: Corner/errors/corner_err_invalid_state_codes_offer_purchase_refund_disclosure
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_ps")
    account = open_account(player["id"], "HARD_GEM")

    offline_offer = create_single_line_offer(
        season["id"],
        "OFFLINE_PACK",
        900,
        1200,
        offer_type="BUNDLE",
        granted_currency_code="SOFT_COIN",
        granted_amount_minor=1200,
    )
    crate = _live_loot_box(season["id"], "STATE_CRATE")
    purchase = create_pending_purchase(player["id"], crate["offer"]["id"])
    settle_purchase(purchase["id"])
    refund = submit_refund(purchase["id"], player["id"])

    validate_error(
        api.set_offer_availability(
            offline_offer["id"], {"to_status": "SUSPENDED", "reason": "Wrong state"}, liveops_headers
        ),
        ApiErrorId.ERR_OFFER_INVALID_AVAILABILITY_STATE,
    )
    validate_error(
        api.publish_disclosure(
            crate["offer"]["id"], crate["disclosure"]["id"], compliance_headers
        ),
        ApiErrorId.ERR_DISCLOSURE_INVALID_STATE,
    )
    validate_error(
        api.settle_purchase(purchase["id"], {"outcome": "SETTLED"}, liveops_headers),
        ApiErrorId.ERR_PURCHASE_INVALID_STATE,
    )
    validate_error(
        api.execute_refund_request(refund["id"], liveops_headers),
        ApiErrorId.ERR_REFUND_INVALID_STATE,
    )

    assert read_offer(offline_offer["id"])["availability_status"] == "OFFLINE"
    tables, _ = validate_paginated(
        api.list_disclosures(crate["offer"]["id"], designer_headers)
    )
    stored_table = next(row for row in tables if row["id"] == crate["disclosure"]["id"])
    assert stored_table["status"] == "PUBLISHED"
    assert read_purchase(purchase["id"])["status"] == "SETTLED"
    assert read_refund(refund["id"])["status"] == "SUBMITTED"
    assert read_account(account["id"])["balance_minor"] == 300


def test_cluster_change_notice_and_run_report_distinct_invalid_state_codes(
    api, liveops_headers, compliance_headers
):
    """PRD §3.3: "Draining an `ACTIVE` cluster leaves existing approved and running events holding their reservations but refuses new approvals; a `DRAINING` cluster may be brought back to `ACTIVE`; and a `DRAINING` cluster may be retired only once its `reserved_ccu` has fallen to exactly 0, an attempt to retire a cluster that still holds reservations being refused with `ERR_CLUSTER_INVALID_STATE`, the same code used for any transition that does not exist from the current status."

    PRD §3.3: "Live events consume server headroom, and headroom is modelled as a **CapacityCluster**, registered by a `LiveOpsCommander` with a `name`, a `region_code` of `NA`, `EU`, `LATAM`, or `APAC`, a `ccu_capacity` of at least 1 concurrent users, and an optional `maintenance_buffer_minutes` cool-down that defaults to 30 minutes and must fall between 0 and 240 inclusive."

    PRD §3.3: "A new cluster is `ACTIVE` with `reserved_ccu` at 0, that field being the sum of the reservations held by events on the cluster that are `APPROVED` or `RUNNING`."

    PRD §3.8: "Reverting is available from two stages and behaves differently in each."

    PRD §3.8: "It requires the notice to still be `DRAFT` and the owning change to be in one of the stages `DRAFT`, `SHADOW`, `CANARY`, or `LIVE` — a notice against a change that has already reverted or retired is refused with `ERR_COMMS_NOTICE_INVALID_STATE`, the same code used for a notice that is already published — and it requires the acting `X-User-ID` to differ from the change's `authored_by_user_id`, that segregation failure being `ERR_SEGREGATION_OF_DUTIES`."

    PRD §3.9: "It requires the run to be `OPEN` and the season to be `LIVE` or `CONCLUDED`, and it carries the run `OPEN → COMPUTED`."

    PRD §2.11: "8. The target resource is in a state from which the requested transition exists, on every transition endpoint (`ERR_SEASON_INVALID_STATE`, `ERR_EPISODE_INVALID_STATE`, `ERR_CLUSTER_INVALID_STATE`, `ERR_EVENT_INVALID_STATE`, `ERR_OFFER_INVALID_APPROVAL_STATE`, `ERR_OFFER_INVALID_AVAILABILITY_STATE`, `ERR_DISCLOSURE_INVALID_STATE`, `ERR_PURCHASE_INVALID_STATE`, `ERR_REFUND_INVALID_STATE`, `ERR_BALANCE_CHANGE_INVALID_STATE`, `ERR_COMMS_NOTICE_INVALID_STATE`, `ERR_MONITORING_RUN_INVALID_STATE`)."

    PRD §3.9: "The health band follows from the ratio: `HEALTHY` when the ratio is at least 6000 basis points, `WATCH` when it is at least 4000 but below 6000, and `INFLATED` when it is below 4000."

    Design: Corner/errors/corner_err_invalid_state_codes_cluster_change_notice_run
    """
    season = create_live_season()
    cluster = create_cluster(name="NA-1", region_code="NA", ccu_capacity=10000)
    change = create_draft_balance_change(season["id"], rationale="State fixture")
    notice = draft_comms_notice(
        change["id"],
        channel="PATCH_NOTES",
        headline="Sink rate up 5 percent",
        body="Crafting costs rise slightly next week.",
    )
    publish_comms_notice(change["id"], notice["id"])
    run = open_monitoring_run(
        season["id"],
        epoch_no=1,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )
    validate_success(api.compute_monitoring_run(run["id"], liveops_headers))

    validate_error(
        api.set_cluster_status(cluster["id"], {"to_status": "RETIRED"}, liveops_headers),
        ApiErrorId.ERR_CLUSTER_INVALID_STATE,
    )
    validate_error(
        api.revert_balance_change(
            change["id"], {"reason": "Never rolled out"}, liveops_headers
        ),
        ApiErrorId.ERR_BALANCE_CHANGE_INVALID_STATE,
    )
    validate_error(
        api.publish_comms_notice(change["id"], notice["id"], compliance_headers),
        ApiErrorId.ERR_COMMS_NOTICE_INVALID_STATE,
    )
    validate_error(
        api.compute_monitoring_run(run["id"], liveops_headers),
        ApiErrorId.ERR_MONITORING_RUN_INVALID_STATE,
    )

    stored_cluster = read_cluster(cluster["id"])
    assert stored_cluster["status"] == "ACTIVE"
    assert stored_cluster["maintenance_buffer_minutes"] == 30
    assert read_balance_change(change["id"])["stage"] == "DRAFT"

    notices, _ = validate_paginated(api.list_comms_notices(change["id"], liveops_headers))
    stored_notice = next(row for row in notices if row["id"] == notice["id"])
    assert stored_notice["status"] == "PUBLISHED"

    stored_run = validate_success(api.get_monitoring_run(run["id"], liveops_headers))
    assert stored_run["status"] == "COMPUTED"
    assert stored_run["resulting_health"] == "HEALTHY"


def test_offline_offer_and_minor_ineligible_offer_report_their_own_codes(api, liveops_headers):
    """PRD §3.6: "Beyond the ownership and pin checks, the offer must actually be sellable: its `availability_status` must be `LIVE`, anything else being refused with `ERR_OFFER_NOT_PURCHASABLE`, and the clock must be at or before its `window_end`, a closed window yielding `ERR_OFFER_WINDOW_CLOSED`."

    PRD §3.7: "A player flagged `is_minor` may only buy offers whose `minor_purchasable` flag is true, an ineligible offer being refused with `ERR_MINOR_OFFER_FORBIDDEN`."

    PRD §3.6: "The offer's `pending_purchase_count` rises by 1 and its `version` moves by 1; the season's `pending_revenue_minor` and the player's `pending_spend_minor` each rise by the quoted price."

    PRD §3.1: "The season is stored in `PLANNED`, with `economy_health` at `HEALTHY`, `content_posture` at `ON_TRACK`, `version` at 1, and every derived counter at its opening value: `scheduled_episode_count`, `released_episode_count`, `cadence_debt_days`, `gross_faucet_minor`, `gross_sink_minor`, `pending_revenue_minor`, `settled_revenue_minor`, `live_offer_count`, `active_tuning_count` and `tuning_stage_epoch` all at 0, and `lifetime_ratio_bp` and `effective_sink_rate_bp` both at 10000."

    PRD §3.4: "A new player starts with `spend_state` `UNRESTRICTED`, `retention_band` `HEALTHY`, `pacing_bp_realized` at 10000, `last_active_at` null, and `season_xp_total`, `session_count`, `spend_30d_minor`, `pending_spend_minor` and `lifetime_spend_minor` all at 0."

    Design: Corner/errors/corner_err_offer_not_purchasable_and_minor_offer_forbidden
    """
    season = create_live_season()
    minor = create_player(
        season["id"], handle="tide_pmv", is_minor=True, guardian_verified=True
    )
    open_account(minor["id"], "HARD_GEM")
    open_account(minor["id"], "SOFT_COIN")

    shelf = create_single_line_offer(
        season["id"],
        "SHELF_PACK",
        900,
        1200,
        offer_type="BUNDLE",
        granted_currency_code="SOFT_COIN",
        granted_amount_minor=1200,
        minor_purchasable=True,
    )
    adult_only = _live_single_line(
        season["id"],
        "ADULT_PACK",
        300,
        400,
        granted_currency_code="HARD_GEM",
        granted_amount_minor=300,
        minor_purchasable=False,
    )

    validate_error(
        api.create_purchase(
            {
                "player_id": minor["id"],
                "offer_id": shelf["id"],
                "expected_offer_version": shelf["version"],
            },
            make_player_headers(minor["id"]),
        ),
        ApiErrorId.ERR_OFFER_NOT_PURCHASABLE,
    )
    validate_error(
        api.create_purchase(
            {
                "player_id": minor["id"],
                "offer_id": adult_only["id"],
                "expected_offer_version": adult_only["version"],
            },
            make_player_headers(minor["id"]),
        ),
        ApiErrorId.ERR_MINOR_OFFER_FORBIDDEN,
    )

    _, meta = validate_paginated(
        api.list_purchases(liveops_headers, params={"player_id": minor["id"]})
    )
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert read_season(season["id"])["pending_revenue_minor"] == 0
    assert read_player(minor["id"])["pending_spend_minor"] == 0


def test_publish_below_the_fairness_floor_is_refused(api, designer_headers):
    """PRD §3.5: "The declared value of the offer is the sum of its lines' `declared_value_minor`."

    PRD §3.5: "The value ratio in basis points is that declared value multiplied by 10000, divided by the offer's `list_price_minor`, rounded half up — so an offer that declares exactly the value it charges for scores 10000."

    PRD §3.5: "The offer's `availability_status` must be `OFFLINE` and its `approval_status` must be `APPROVED`; the season must be `LIVE`; the pinned `expected_season_version` must match the season's current `version`, as §2.7 describes; the logical clock must be at or before the offer's `window_end`, a closed window yielding `ERR_OFFER_WINDOW_CLOSED`; the offer's `disclosure_state` must not be `REQUIRED_MISSING`, a randomized offer without a published table being refused with `ERR_DISCLOSURE_NOT_PUBLISHED`; the freshly recomputed `fairness_index_bp` must be at least 8000 basis points, a lower index being refused with `ERR_FAIRNESS_FLOOR_BREACH`; there must be no sku-window collision; the season's `economy_health` must not be `INFLATED`; and if the `offer_type` is `LIMITED_TIME`, the season's `content_posture` must not be `BEHIND`."

    PRD §3.5: "Approving carries the offer `IN_REVIEW → APPROVED`, records the reviewer as `reviewed_by_user_id`, and moves the offer's `version` by 1."

    PRD §3.5: "A successful publish raises the season's `live_offer_count` by 1 and moves both the season's and the offer's `version` by 1."

    Design: Corner/errors/corner_err_fairness_floor_breach_blocks_publish
    """
    season = create_live_season()
    gouge = create_single_line_offer(
        season["id"],
        "GOUGE_PACK",
        2000,
        1200,
        offer_type="BUNDLE",
        granted_currency_code="SOFT_COIN",
        granted_amount_minor=1200,
    )
    submit_offer(gouge["id"])
    approve_offer(gouge["id"])
    pinned = season_version(season["id"])

    validate_error(
        api.publish_offer(gouge["id"], {"expected_season_version": pinned}, designer_headers),
        ApiErrorId.ERR_FAIRNESS_FLOOR_BREACH,
    )

    stored = read_offer(gouge["id"])
    assert stored["fairness_index_bp"] == 6000, (
        f"Expected fairness_index_bp 6000, got {stored['fairness_index_bp']}"
    )
    assert stored["approval_status"] == "APPROVED"
    assert stored["availability_status"] == "OFFLINE"
    assert read_season(season["id"])["live_offer_count"] == 0


def test_cadence_debt_blocks_only_limited_time_publishes(api, designer_headers, liveops_headers):
    """PRD §2.9: "The second is `content_posture`, which reads `ON_TRACK` or `BEHIND` and starts at `ON_TRACK`."

    PRD §2.9: "A `BEHIND` posture blocks exactly one operation — publishing an offer whose `offer_type` is `LIMITED_TIME` — and that rejection carries `ERR_CADENCE_DEBT_BLOCK` (HTTP 409)."

    PRD §3.2: "An episode that is still `SCHEDULED` with a `planned_release_at` earlier than the current clock contributes the whole days that have elapsed since that instant, truncated downward."

    PRD §3.2: "The accumulated total is stored as `cadence_debt_days`, and `content_posture` becomes `BEHIND` when that total is strictly greater than 14 days and `ON_TRACK` otherwise."

    PRD §3.5: "A successful publish raises the season's `live_offer_count` by 1 and moves both the season's and the offer's `version` by 1."

    Design: Corner/errors/corner_err_cadence_debt_blocks_limited_time_only
    """
    season = create_live_season()
    create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )

    limited_time = create_single_line_offer(
        season["id"],
        "FLASH_LT",
        900,
        1200,
        granted_currency_code="SOFT_COIN",
        granted_amount_minor=1200,
        window_end="2026-08-31T00:00:00Z",
    )
    submit_offer(limited_time["id"])
    approve_offer(limited_time["id"])

    bundle = create_single_line_offer(
        season["id"],
        "CALM_BUNDLE",
        900,
        1200,
        offer_type="BUNDLE",
        granted_currency_code="SOFT_COIN",
        granted_amount_minor=1200,
        window_end="2026-08-31T00:00:00Z",
    )
    submit_offer(bundle["id"])
    approve_offer(bundle["id"])

    validate_success(api.set_clock("2026-08-25T00:00:00Z", liveops_headers))
    create_scheduled_episode(
        season["id"],
        sequence_no=2,
        title="E2 Undertow",
        planned_release_at="2026-09-01T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )

    behind_season = read_season(season["id"])
    assert behind_season["cadence_debt_days"] == 23, (
        f"Expected cadence_debt_days 23, got {behind_season['cadence_debt_days']}"
    )
    assert behind_season["content_posture"] == "BEHIND"

    validate_error(
        api.publish_offer(
            limited_time["id"],
            {"expected_season_version": behind_season["version"]},
            designer_headers,
        ),
        ApiErrorId.ERR_CADENCE_DEBT_BLOCK,
    )
    assert read_offer(limited_time["id"])["availability_status"] == "OFFLINE"

    validate_success(
        api.publish_offer(
            bundle["id"],
            {"expected_season_version": season_version(season["id"])},
            designer_headers,
        ),
        200,
    )
    assert read_offer(bundle["id"])["availability_status"] == "LIVE"
    assert read_season(season["id"])["live_offer_count"] == 1


def test_monitoring_epoch_and_tuning_stage_ladders_reject_skips(api, liveops_headers):
    """PRD §3.9: "Two constraints bind: the `epoch_no` must be exactly one greater than the highest `epoch_no` already used by that season, and no other run of that season may still be `OPEN`."

    PRD §3.9: "Either violation is refused with `ERR_MONITORING_EPOCH_SEQUENCE`."

    PRD §3.8: "**No stage may be skipped**: a `to_stage` that is not the single next stage available from the current one is refused with `ERR_BALANCE_CHANGE_STAGE_SKIP`, while a stage from which the requested advance does not exist at all is refused with `ERR_BALANCE_CHANGE_INVALID_STATE`."

    PRD §3.8: "The change is stored in `DRAFT` with the authoring operator recorded as `authored_by_user_id`, `promoted_by_user_id` and `pre_live_sink_rate_bp` null, and `comms_state` at `MISSING`."

    PRD §3.1: "The season is stored in `PLANNED`, with `economy_health` at `HEALTHY`, `content_posture` at `ON_TRACK`, `version` at 1, and every derived counter at its opening value: `scheduled_episode_count`, `released_episode_count`, `cadence_debt_days`, `gross_faucet_minor`, `gross_sink_minor`, `pending_revenue_minor`, `settled_revenue_minor`, `live_offer_count`, `active_tuning_count` and `tuning_stage_epoch` all at 0, and `lifetime_ratio_bp` and `effective_sink_rate_bp` both at 10000."

    Design: Corner/errors/corner_err_sequence_codes_for_monitoring_and_tuning
    """
    season = create_live_season()
    change = create_draft_balance_change(season["id"], rationale="Ladder fixture")
    pinned = season_version(season["id"])

    validate_error(
        api.create_monitoring_run(
            {
                "season_id": season["id"],
                "epoch_no": 2,
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-02T00:00:00Z",
            },
            liveops_headers,
        ),
        ApiErrorId.ERR_MONITORING_EPOCH_SEQUENCE,
    )
    validate_error(
        api.advance_balance_change(
            change["id"],
            {"to_stage": "CANARY", "expected_season_version": pinned},
            liveops_headers,
        ),
        ApiErrorId.ERR_BALANCE_CHANGE_STAGE_SKIP,
    )

    _, meta = validate_paginated(
        api.list_monitoring_runs(liveops_headers, params={"season_id": season["id"]})
    )
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert read_balance_change(change["id"])["stage"] == "DRAFT"
    assert read_season(season["id"])["effective_sink_rate_bp"] == 10000


def test_refund_window_and_duplicate_request_report_their_own_codes(api, liveops_headers):
    """PRD §3.7: "The purchase must belong to the requester, must be in `SETTLED` status (otherwise `ERR_PURCHASE_INVALID_STATE`), must be within its refund window — the clock must be at or before the purchase's `settled_at` plus 14 days, a later request being refused with `ERR_REFUND_WINDOW_EXPIRED` — and must not already carry a refund request in `SUBMITTED`, `APPROVED`, or `EXECUTED` status, a duplicate being refused with `ERR_REFUND_ALREADY_REQUESTED`."

    PRD §3.7: "A request is stored in `SUBMITTED` with `decided_by_user_id`, `decision_note` and `executed_at` all null and all five money fields at 0."

    PRD §3.7: "The rolling spend figure is computed by taking the window that begins 30 days before the current clock and ends at the clock itself, summing the `price_paid_minor` of every purchase of that player whose `status` is `SETTLED` or `REFUNDED` and whose `settled_at` falls inside that window with both ends inclusive, then subtracting the `refund_amount_minor` of every refund request in `EXECUTED` status against that player's purchases whose `executed_at` falls inside the same inclusive window, and finally flooring the result at 0 so it can never go negative."

    Design: Corner/errors/corner_err_refund_window_expired_and_already_requested
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pr")
    open_account(player["id"], "HARD_GEM")
    offer = _live_single_line(
        season["id"],
        "RF_PACK",
        900,
        1200,
        granted_currency_code="HARD_GEM",
        granted_amount_minor=900,
    )

    first = create_pending_purchase(player["id"], offer["id"])
    settle_purchase(first["id"])
    second = create_pending_purchase(player["id"], offer["id"])
    settle_purchase(second["id"])
    request = submit_refund(second["id"], player["id"])

    validate_error(
        api.create_refund_request(
            {"purchase_id": second["id"], "reason_code": "DISSATISFIED"},
            make_player_headers(player["id"]),
        ),
        ApiErrorId.ERR_REFUND_ALREADY_REQUESTED,
    )

    validate_success(api.set_clock("2026-08-16T00:00:00Z", liveops_headers))
    validate_error(
        api.create_refund_request(
            {"purchase_id": first["id"], "reason_code": "ACCIDENTAL"},
            make_player_headers(player["id"]),
        ),
        ApiErrorId.ERR_REFUND_WINDOW_EXPIRED,
    )

    _, second_meta = validate_paginated(
        api.list_refund_requests(liveops_headers, params={"purchase_id": second["id"]})
    )
    assert second_meta["total_count"] == 1, (
        f"Expected total_count 1, got {second_meta['total_count']}"
    )
    _, first_meta = validate_paginated(
        api.list_refund_requests(liveops_headers, params={"purchase_id": first["id"]})
    )
    assert first_meta["total_count"] == 0, (
        f"Expected total_count 0, got {first_meta['total_count']}"
    )
    assert read_refund(request["id"])["status"] == "SUBMITTED"
    assert read_player(player["id"])["spend_30d_minor"] == 1800


def test_uniqueness_scopes_and_account_integrity_codes(
    api, producer_headers, liveops_headers, designer_headers
):
    """PRD §3.1: "A `ContentProducer` opens one by supplying a `code` — a human-readable label of between 1 and 16 characters that must be unique across all seasons, a collision being answered with `ERR_SEASON_CODE_DUPLICATE` — together with a marketing `title`, an inclusive window bounded by `starts_at` and `ends_at` where the end must be strictly later than the start, a roadmap target of `planned_episode_count` episodes (at least 1), a full-season `target_xp_total` of at least 1 that serves as the denominator for progression pacing, and a `pass_price_minor` battle-pass reference price of zero or more minor units."

    PRD §3.4: "A `LiveOpsCommander` provisions a **Player** with a `handle` that must be unique across all players (a collision yielding `ERR_PLAYER_HANDLE_DUPLICATE`), a price `region_code` of `NA`, `EU`, `LATAM`, or `APAC`, the `active_season_id` of the season the player is progressing through, and two optional protection flags: `is_minor`, which defaults to false and marks the account as belonging to a minor, and `guardian_verified`, which defaults to false and records that guardian consent is on file."

    PRD §3.5: "An `EconomyDesigner` authors an **Offer** — the unit of monetization — by supplying the `season_id` it is merchandised in, an `offer_type` of `BATTLE_PASS`, `BUNDLE`, `LIMITED_TIME`, or `LOOT_BOX`, a storefront `sku` that must be unique within the season (a collision yielding `ERR_OFFER_SKU_DUPLICATE`), a `price_tier` of `T1`, `T2`, `T3`, or `T4`, a `list_price_minor` of at least 1 minor unit that serves as the North-American reference price, a `line_items` array of between 1 and 8 entries, an optional `personalization_discount_bp` defaulting to 0, an optional `minor_purchasable` flag defaulting to false, and an inclusive merchandising window bounded by `window_start` and a strictly later `window_end`."

    PRD §3.3: "A `ContentProducer` places a **LiveEvent** on the calendar with a payload naming the `season_id` it belongs to, the `capacity_cluster_id` whose concurrency it will occupy, a `code` that must be unique within the season (a collision answered with `ERR_EVENT_CODE_DUPLICATE`), an inclusive `window_start`, an exclusive `window_end` that must be strictly later, and a `forecast_ccu` of at least 1 forecast peak concurrent users."

    PRD §3.4: "A player may hold at most one account per currency; a second attempt in the same currency is refused with `ERR_DUPLICATE_CURRENCY_ACCOUNT`."

    PRD §3.6: "The buyer must also already hold a currency account for every distinct `granted_currency_code` appearing in the offer's line items; a missing account is refused with `ERR_CURRENCY_ACCOUNT_MISSING`."

    Design: Corner/errors/corner_err_uniqueness_and_missing_account_codes
    """
    season = create_live_season()
    cluster = create_cluster(name="NA-1", region_code="NA", ccu_capacity=10000)
    player = create_player(season["id"], handle="tide_pu")
    open_account(player["id"], "HARD_GEM")
    create_single_line_offer(
        season["id"],
        "UNIQ_PACK",
        900,
        1200,
        offer_type="BUNDLE",
        granted_currency_code="HARD_GEM",
        granted_amount_minor=900,
    )
    validate_success(
        api.create_live_event(
            {
                "season_id": season["id"],
                "capacity_cluster_id": cluster["id"],
                "code": "EVT_UNIQ",
                "window_start": "2026-08-05T00:00:00Z",
                "window_end": "2026-08-05T02:00:00Z",
                "forecast_ccu": 1000,
            },
            producer_headers,
        ),
        201,
    )
    soft_only = _live_single_line(
        season["id"],
        "SOFT_ONLY",
        300,
        400,
        granted_currency_code="SOFT_COIN",
        granted_amount_minor=400,
    )

    validate_error(
        api.create_season(
            {
                "code": "S7",
                "title": "Season 7 Duplicate",
                "starts_at": "2026-11-01T00:00:00Z",
                "ends_at": "2027-01-30T00:00:00Z",
                "planned_episode_count": 6,
                "target_xp_total": 9000,
                "pass_price_minor": 1000,
            },
            producer_headers,
        ),
        ApiErrorId.ERR_SEASON_CODE_DUPLICATE,
    )
    validate_error(
        api.create_player(
            {"handle": "tide_pu", "region_code": "EU", "active_season_id": season["id"]},
            liveops_headers,
        ),
        ApiErrorId.ERR_PLAYER_HANDLE_DUPLICATE,
    )
    validate_error(
        api.create_offer(
            {
                "season_id": season["id"],
                "offer_type": "BUNDLE",
                "sku": "UNIQ_PACK",
                "price_tier": "T2",
                "list_price_minor": 900,
                "line_items": [
                    {
                        "sku": "UNIQ_COINS_2",
                        "base_price_minor": 900,
                        "declared_value_minor": 1200,
                        "granted_currency_code": "HARD_GEM",
                        "granted_amount_minor": 900,
                    }
                ],
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-09-20T00:00:00Z",
            },
            designer_headers,
        ),
        ApiErrorId.ERR_OFFER_SKU_DUPLICATE,
    )
    validate_error(
        api.create_live_event(
            {
                "season_id": season["id"],
                "capacity_cluster_id": cluster["id"],
                "code": "EVT_UNIQ",
                "window_start": "2026-08-07T00:00:00Z",
                "window_end": "2026-08-07T02:00:00Z",
                "forecast_ccu": 1000,
            },
            producer_headers,
        ),
        ApiErrorId.ERR_EVENT_CODE_DUPLICATE,
    )
    validate_error(
        api.create_currency_account(player["id"], {"currency_code": "HARD_GEM"}, liveops_headers),
        ApiErrorId.ERR_DUPLICATE_CURRENCY_ACCOUNT,
    )
    validate_error(
        api.create_purchase(
            {
                "player_id": player["id"],
                "offer_id": soft_only["id"],
                "expected_offer_version": soft_only["version"],
            },
            make_player_headers(player["id"]),
        ),
        ApiErrorId.ERR_CURRENCY_ACCOUNT_MISSING,
    )

    _, account_meta = validate_paginated(
        api.list_currency_accounts(player["id"], liveops_headers)
    )
    assert account_meta["total_count"] == 1, (
        f"Expected total_count 1, got {account_meta['total_count']}"
    )
    _, offer_meta = validate_paginated(
        api.list_offers(designer_headers, params={"season_id": season["id"]})
    )
    assert offer_meta["total_count"] == 2, (
        f"Expected total_count 2, got {offer_meta['total_count']}"
    )
    _, event_meta = validate_paginated(
        api.list_live_events(liveops_headers, params={"season_id": season["id"]})
    )
    assert event_meta["total_count"] == 1, (
        f"Expected total_count 1, got {event_meta['total_count']}"
    )
    _, purchase_meta = validate_paginated(
        api.list_purchases(liveops_headers, params={"player_id": player["id"]})
    )
    assert purchase_meta["total_count"] == 0, (
        f"Expected total_count 0, got {purchase_meta['total_count']}"
    )


def test_locked_buyer_is_stopped_outright_and_cooldown_only_for_loot_boxes(
    api, liveops_headers, compliance_headers
):
    """PRD §3.7: "And a player whose `spend_state` is `LOCKED` may neither create a purchase nor have one settled, both being refused with `ERR_SPEND_LOCKED`."

    PRD §3.7: "A player whose `spend_state` is `COOLDOWN` may continue to buy ordinary offers but may not buy an offer whose `offer_type` is `LOOT_BOX`, that combination being refused with `ERR_SPEND_COOLDOWN_RESTRICTED`."

    PRD §3.7: "A player enters the cooldown band when `spend_30d_minor` reaches or exceeds 40000 minor units while remaining below 75000, and enters the lock band when it reaches or exceeds 75000; both boundaries are inclusive, so exactly 40000 is already cooldown and exactly 75000 is already lock."

    PRD §3.7: "The system moves a player `UNRESTRICTED → COOLDOWN` when a recompute — triggered either by a settlement or by a monitoring run — lands the recomputed `spend_30d_minor` in the cooldown band, and that move only touches the player's `version`."

    PRD §3.7: "The system moves a player `UNRESTRICTED → LOCKED` or `COOLDOWN → LOCKED` when a settlement recompute pushes `spend_30d_minor` into the lock band, and a `ComplianceOfficer` can force the same landing at any time by supplying an `action` of `LOCK`, optionally with a `note`."

    PRD §3.6: "On success the purchase is stored in `PENDING` with `quoted_price_minor` and `applied_personalization_bp` pinned from the quote just computed, `price_paid_minor` and `granted_total_minor` and `granted_consumed_minor` at 0, `settled_at` and `deny_reason` null, and `is_minor_purchase` snapshotted from the buyer's `is_minor` flag at this moment so that a later change to the account's minor status cannot rewrite history."

    PRD §3.6: "The offer's `pending_purchase_count` rises by 1 and its `version` moves by 1; the season's `pending_revenue_minor` and the player's `pending_spend_minor` each rise by the quoted price."

    Design: Corner/errors/corner_err_spend_locked_and_cooldown_restricted
    """
    season = create_live_season()
    spender = create_player(season["id"], handle="tide_pcd")
    open_account(spender["id"], "HARD_GEM")
    locked = create_player(season["id"], handle="tide_plk")
    open_account(locked["id"], "HARD_GEM")
    validate_success(
        api.set_spend_guard(
            locked["id"], {"action": "LOCK", "note": "Guardian request"}, compliance_headers
        )
    )

    whale = _live_single_line(
        season["id"],
        "WHALE_40K",
        40000,
        50000,
        granted_currency_code="HARD_GEM",
        granted_amount_minor=40000,
    )
    crate = _live_loot_box(season["id"], "COOL_CRATE")
    bundle = _live_single_line(
        season["id"],
        "COOL_BUNDLE",
        300,
        400,
        offer_type="BUNDLE",
        granted_currency_code="HARD_GEM",
        granted_amount_minor=300,
    )

    whale_purchase = validate_success(
        api.create_purchase(
            {
                "player_id": spender["id"],
                "offer_id": whale["id"],
                "expected_offer_version": whale["version"],
            },
            make_player_headers(spender["id"]),
        ),
        201,
    )
    settle_purchase(whale_purchase["id"])

    assert read_player(spender["id"])["spend_state"] == "COOLDOWN"
    assert read_player(locked["id"])["spend_state"] == "LOCKED"

    validate_error(
        api.create_purchase(
            {
                "player_id": locked["id"],
                "offer_id": bundle["id"],
                "expected_offer_version": bundle["version"],
            },
            make_player_headers(locked["id"]),
        ),
        ApiErrorId.ERR_SPEND_LOCKED,
    )
    validate_error(
        api.create_purchase(
            {
                "player_id": spender["id"],
                "offer_id": crate["offer"]["id"],
                "expected_offer_version": crate["offer"]["version"],
            },
            make_player_headers(spender["id"]),
        ),
        ApiErrorId.ERR_SPEND_COOLDOWN_RESTRICTED,
    )
    accepted = validate_success(
        api.create_purchase(
            {
                "player_id": spender["id"],
                "offer_id": bundle["id"],
                "expected_offer_version": bundle["version"],
            },
            make_player_headers(spender["id"]),
        ),
        201,
    )

    assert accepted["quoted_price_minor"] == 300, (
        f"Expected quoted_price_minor 300, got {accepted['quoted_price_minor']}"
    )
    assert read_player(spender["id"])["pending_spend_minor"] == 300
    _, meta = validate_paginated(
        api.list_purchases(liveops_headers, params={"player_id": locked["id"]})
    )
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
