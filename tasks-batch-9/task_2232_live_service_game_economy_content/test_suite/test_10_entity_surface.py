"""Entity surface: creation, retrieval, listing, not-found codes, schema conformance,
defaults, computed and system-managed fields, immutability and foreign-key integrity."""

from datetime import datetime, timezone

import pytest

from test_helpers import (
    DESIGNER,
    LIVEOPS,
    PRODUCER,
    ApiErrorId,
    assert_capacity_cluster,
    assert_episode,
    assert_ledger_entry,
    assert_season,
    create_live_season,
    create_player,
    create_planned_season,
    create_scheduled_episode,
    list_ledger,
    open_account,
    release_episode_at,
    reset_clock,
    rollback_episode_at,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local helpers (private to this module)
# ---------------------------------------------------------------------------

SEASON_BODY = {
    "code": "S7",
    "title": "Season 7 Tidebreak",
    "starts_at": "2026-08-01T00:00:00Z",
    "ends_at": "2026-10-30T00:00:00Z",
    "planned_episode_count": 6,
    "target_xp_total": 9000,
    "pass_price_minor": 1000,
}


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the trailing Z and optional millis."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _same_instant(actual: str, expected: str) -> bool:
    return _instant(actual) == _instant(expected)


def _single_line_offer_body(
    season_id: str,
    sku: str,
    base_price_minor: int,
    declared_value_minor: int,
    line_sku: str,
    granted_currency_code: str,
    granted_amount_minor: int,
    offer_type: str = "BUNDLE",
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-10T00:00:00Z",
    **extra,
):
    body = {
        "season_id": season_id,
        "offer_type": offer_type,
        "sku": sku,
        "price_tier": "T1",
        "list_price_minor": base_price_minor,
        "line_items": [
            {
                "sku": line_sku,
                "base_price_minor": base_price_minor,
                "declared_value_minor": declared_value_minor,
                "granted_currency_code": granted_currency_code,
                "granted_amount_minor": granted_amount_minor,
            }
        ],
        "window_start": window_start,
        "window_end": window_end,
    }
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Creation, retrieval, listing
# ---------------------------------------------------------------------------


def test_creation_echoes_inputs_and_seeded_states_for_season_episode_cluster(api):
    """PRD §4: "Operations that mint a new resource — a season, an episode, a capacity cluster, a live event, a player, a currency account, an offer, a probability disclosure, a purchase, a refund request, a tuning change, a community notice, a monitoring run, or a ledger adjustment — answer with `201 Created`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.1: "The season is stored in `PLANNED`, with `economy_health` at `HEALTHY`, `content_posture` at `ON_TRACK`, `version` at 1, and every derived counter at its opening value: `scheduled_episode_count`, `released_episode_count`, `cadence_debt_days`, `gross_faucet_minor`, `gross_sink_minor`, `pending_revenue_minor`, `settled_revenue_minor`, `live_offer_count`, `active_tuning_count` and `tuning_stage_epoch` all at 0, and `lifetime_ratio_bp` and `effective_sink_rate_bp` both at 10000."
    PRD §3.2: "Episodes are created in `DRAFT`."
    PRD §3.3: "A new cluster is `ACTIVE` with `reserved_ccu` at 0, that field being the sum of the reservations held by events on the cluster that are `APPROVED` or `RUNNING`."

    Design: Corner/entities/corner_entity_creation_season_episode_cluster
    """
    reset_clock()

    season = validate_success(api.create_season(dict(SEASON_BODY), PRODUCER), 201)
    assert_season(season)
    assert season["code"] == "S7"
    assert season["status"] == "PLANNED"
    assert season["economy_health"] == "HEALTHY"
    assert season["content_posture"] == "ON_TRACK"
    assert season["version"] == 1

    episode = validate_success(
        api.create_episode(
            {
                "season_id": season["id"],
                "sequence_no": 1,
                "title": "E1 Tidefall",
                "planned_release_at": "2026-08-02T00:00:00Z",
                "xp_grant": 600,
                "soft_currency_grant_minor": 1200,
            },
            PRODUCER,
        ),
        201,
    )
    assert_episode(episode)
    assert episode["status"] == "DRAFT"

    cluster = validate_success(
        api.create_cluster(
            {
                "name": "NA-1",
                "region_code": "NA",
                "ccu_capacity": 10000,
                "maintenance_buffer_minutes": 30,
            },
            LIVEOPS,
        ),
        201,
    )
    assert_capacity_cluster(cluster)
    assert cluster["status"] == "ACTIVE"
    assert cluster["reserved_ccu"] == 0


def test_offer_read_matches_the_state_the_create_response_reported(api):
    """PRD §3.5: "A newly created offer is `DRAFT` on the first dimension and `OFFLINE` on the second, and neither dimension ever moves the other implicitly: an offer can be re-reviewed while it sits live on the storefront, and it can be suspended and resumed without its approval ever being revisited."
    PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."
    PRD §3.5: "The value ratio in basis points is that declared value multiplied by 10000, divided by the offer's `list_price_minor`, rounded half up — so an offer that declares exactly the value it charges for scores 10000."
    PRD §3.5: "The personalization penalty is the offer's `personalization_discount_bp` divided by 5, rounded half up, then capped at 600 basis points."
    PRD §3.5: "The index is the value ratio minus all three penalties, then clamped into the range 0 through 15000 — negative results become 0 and results above 15000 become 15000."
    PRD §2.4: "Seasons, episodes, capacity clusters, live events, players, currency accounts, offers, probability disclosures, purchases, refund requests, balance changes, community notices and monitoring runs each expose `created_at` (an ISO 8601 UTC timestamp with three fractional digits, recording when the record was first stored), `updated_at` (the same format, refreshed on every mutation of the record), and `version` (an integer that starts at 1 on creation and increases by exactly 1 on every accepted mutation of that record, including mutations caused indirectly by a cascade from another resource)."

    Design: Corner/entities/corner_entity_retrieval_offer_matches_stored_state
    """
    reset_clock()
    season = create_planned_season()

    created = validate_success(
        api.create_offer(
            {
                "season_id": season["id"],
                "offer_type": "BUNDLE",
                "sku": "AUG_BUNDLE",
                "price_tier": "T3",
                "list_price_minor": 1798,
                "line_items": [
                    {
                        "sku": "COIN_PACK",
                        "base_price_minor": 499,
                        "declared_value_minor": 700,
                        "granted_currency_code": "EVENT_TOKEN",
                        "granted_amount_minor": 600,
                    },
                    {
                        "sku": "SKIN_A",
                        "base_price_minor": 1299,
                        "declared_value_minor": 1700,
                        "granted_currency_code": "EVENT_TOKEN",
                        "granted_amount_minor": 600,
                    },
                ],
                "personalization_discount_bp": 1500,
                "minor_purchasable": False,
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-20T00:00:00Z",
            },
            DESIGNER,
        ),
        201,
    )

    read_back = validate_success(api.get_offer(created["id"], DESIGNER), 200)

    assert read_back["sku"] == "AUG_BUNDLE"
    assert read_back["approval_status"] == "DRAFT"
    assert read_back["availability_status"] == "OFFLINE"
    # declared 2400 against list 1798 gives 13348 bp, less a 300 bp personalization penalty.
    assert read_back["fairness_index_bp"] == 13048
    assert read_back["disclosure_state"] == "NOT_REQUIRED"
    assert read_back["units_sold"] == 0
    assert read_back["version"] == 1
    # No recomputation drift between the create response and the read.
    for field in (
        "sku",
        "approval_status",
        "availability_status",
        "fairness_index_bp",
        "disclosure_state",
        "units_sold",
        "version",
    ):
        assert read_back[field] == created[field], f"{field} drifted between create and read"


def test_offer_listing_reports_pagination_envelope_and_honours_filters(api):
    """PRD §2.3: "`limit` caps the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "`offset` states how many records to skip before collecting the page; it defaults to 0 and may not be negative."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` counts the records matching the filter before pagination is applied and `has_more` is true when records remain beyond the current page."
    PRD §2.5: "The offer list accepts `season_id`, `offer_type`, `approval_status`, and `availability_status`."

    Design: Corner/entities/corner_entity_listing_offers_pagination_envelope
    """
    reset_clock()
    season = create_planned_season()
    season_id = season["id"]

    validate_success(
        api.create_offer(
            _single_line_offer_body(season_id, "PACK_A", 499, 700, "COIN_PACK_A", "SOFT_COIN", 700),
            DESIGNER,
        ),
        201,
    )
    validate_success(
        api.create_offer(
            _single_line_offer_body(season_id, "PACK_B", 499, 700, "COIN_PACK_B", "SOFT_COIN", 700),
            DESIGNER,
        ),
        201,
    )
    validate_success(
        api.create_offer(
            _single_line_offer_body(
                season_id,
                "CRATE_A",
                300,
                400,
                "CRATE_KEY",
                "HARD_GEM",
                300,
                offer_type="LOOT_BOX",
            ),
            DESIGNER,
        ),
        201,
    )

    first_rows, first_meta = validate_paginated(
        api.list_offers(DESIGNER, params={"season_id": season_id, "limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api.list_offers(DESIGNER, params={"season_id": season_id, "limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    crate_rows, crate_meta = validate_paginated(
        api.list_offers(DESIGNER, params={"season_id": season_id, "offer_type": "LOOT_BOX"})
    )
    assert len(crate_rows) == 1
    assert crate_meta["total_count"] == 1
    assert crate_meta["has_more"] is False
    assert crate_rows[0]["sku"] == "CRATE_A"
    # The unpaginated read falls back to the documented defaults.
    assert crate_meta["limit"] == 10
    assert crate_meta["offset"] == 0


@pytest.mark.parametrize(
    "collection, unknown_id, expected_error",
    [
        ("seasons", "00000000-0000-0000-0000-0000000000aa", ApiErrorId.ERR_SEASON_NOT_FOUND),
        ("offers", "00000000-0000-0000-0000-0000000000bb", ApiErrorId.ERR_OFFER_NOT_FOUND),
        ("purchases", "00000000-0000-0000-0000-0000000000cc", ApiErrorId.ERR_PURCHASE_NOT_FOUND),
        (
            "monitoring-runs",
            "00000000-0000-0000-0000-0000000000dd",
            ApiErrorId.ERR_MONITORING_RUN_NOT_FOUND,
        ),
    ],
)
def test_unknown_path_id_yields_the_collection_specific_not_found_code(
    api, collection, unknown_id, expected_error
):
    """PRD §2.11: "Existence of every path-addressed resource, left to right, on every path-parameterised endpoint (the family of 404 codes listed in §2.5)."
    PRD §2.5: "Identifiers supplied in a request body are resolved after the path identifiers and produce the same not-found codes: `ERR_SEASON_NOT_FOUND`, `ERR_CLUSTER_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_PURCHASE_NOT_FOUND`."
    PRD §2.5: "The remaining single-identifier lookups follow the same shape: `ERR_EPISODE_NOT_FOUND` for an unknown `episode_id`, `ERR_LIVE_EVENT_NOT_FOUND` for an unknown `event_id`, `ERR_LEDGER_ENTRY_NOT_FOUND` for an unknown `entry_id`, `ERR_REFUND_REQUEST_NOT_FOUND` for an unknown `request_id`, and `ERR_MONITORING_RUN_NOT_FOUND` for an unknown `run_id`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/corner_entity_not_found_codes_per_collection
    """
    reset_clock()

    readers = {
        "seasons": api.get_season,
        "offers": api.get_offer,
        "purchases": api.get_purchase,
        "monitoring-runs": api.get_monitoring_run,
    }
    response = readers[collection](unknown_id, LIVEOPS)
    validate_error(response, expected_error.value, 404)


def test_missing_required_input_key_is_rejected_and_stores_nothing(api):
    """PRD §2.11: "Request-body schema conformance on every endpoint: required fields present, enum values in range, integers within their declared bounds, `window_end` strictly after `window_start`, `ends_at` strictly after `starts_at`, `list_price_minor` exactly equal to the sum of the line items' `base_price_minor`, line-item skus unique within the offer, `delta_bp` non-zero, disclosure entries well-formed, and pagination inside its bounds (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "A `ContentProducer` opens one by supplying a `code` — a human-readable label of between 1 and 16 characters that must be unique across all seasons, a collision being answered with `ERR_SEASON_CODE_DUPLICATE` — together with a marketing `title`, an inclusive window bounded by `starts_at` and `ends_at` where the end must be strictly later than the start, a roadmap target of `planned_episode_count` episodes (at least 1), a full-season `target_xp_total` of at least 1 that serves as the denominator for progression pacing, and a `pass_price_minor` battle-pass reference price of zero or more minor units."
    PRD §3.5: "An `EconomyDesigner` authors an **Offer** — the unit of monetization — by supplying the `season_id` it is merchandised in, an `offer_type` of `BATTLE_PASS`, `BUNDLE`, `LIMITED_TIME`, or `LOOT_BOX`, a storefront `sku` that must be unique within the season (a collision yielding `ERR_OFFER_SKU_DUPLICATE`), a `price_tier` of `T1`, `T2`, `T3`, or `T4`, a `list_price_minor` of at least 1 minor unit that serves as the North-American reference price, a `line_items` array of between 1 and 8 entries, an optional `personalization_discount_bp` defaulting to 0, an optional `minor_purchasable` flag defaulting to false, and an inclusive merchandising window bounded by `window_start` and a strictly later `window_end`."
    PRD §2.11: "Uniqueness of a season `code`, a player `handle`, an offer `sku` within its season, and a live-event `code` within its season, on season creation, player creation, offer creation, and live-event creation respectively (`ERR_SEASON_CODE_DUPLICATE`, `ERR_PLAYER_HANDLE_DUPLICATE`, `ERR_OFFER_SKU_DUPLICATE`, `ERR_EVENT_CODE_DUPLICATE`)."

    Design: Corner/entities/corner_entity_required_fields_missing_rejected
    """
    reset_clock()
    season = create_planned_season()

    no_target_xp = {
        "code": "S8",
        "title": "Season 8",
        "starts_at": "2026-11-01T00:00:00Z",
        "ends_at": "2027-01-30T00:00:00Z",
        "planned_episode_count": 6,
        "pass_price_minor": 1000,
    }
    validate_error(
        api.create_season(no_target_xp, PRODUCER), ApiErrorId.ERR_INVALID_REQUEST.value, 400
    )

    no_lines = {
        "season_id": season["id"],
        "offer_type": "BUNDLE",
        "sku": "NO_LINES",
        "price_tier": "T1",
        "list_price_minor": 499,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-10T00:00:00Z",
    }
    validate_error(
        api.create_offer(no_lines, DESIGNER), ApiErrorId.ERR_INVALID_REQUEST.value, 400
    )

    # Nothing was stored: sku NO_LINES is absent from the season's offers, and the code
    # S8 is still free, so an otherwise identical complete payload is accepted.
    rows, meta = validate_paginated(api.list_offers(DESIGNER, params={"season_id": season["id"]}))
    assert meta["total_count"] == 0
    assert all(row["sku"] != "NO_LINES" for row in rows)

    complete_s8 = dict(no_target_xp)
    complete_s8["target_xp_total"] = 9000
    validate_success(api.create_season(complete_s8, PRODUCER), 201)


def test_optional_input_keys_fall_back_to_their_declared_defaults(api):
    """PRD §3.3: "Live events consume server headroom, and headroom is modelled as a **CapacityCluster**, registered by a `LiveOpsCommander` with a `name`, a `region_code` of `NA`, `EU`, `LATAM`, or `APAC`, a `ccu_capacity` of at least 1 concurrent users, and an optional `maintenance_buffer_minutes` cool-down that defaults to 30 minutes and must fall between 0 and 240 inclusive."
    PRD §3.5: "An `EconomyDesigner` authors an **Offer** — the unit of monetization — by supplying the `season_id` it is merchandised in, an `offer_type` of `BATTLE_PASS`, `BUNDLE`, `LIMITED_TIME`, or `LOOT_BOX`, a storefront `sku` that must be unique within the season (a collision yielding `ERR_OFFER_SKU_DUPLICATE`), a `price_tier` of `T1`, `T2`, `T3`, or `T4`, a `list_price_minor` of at least 1 minor unit that serves as the North-American reference price, a `line_items` array of between 1 and 8 entries, an optional `personalization_discount_bp` defaulting to 0, an optional `minor_purchasable` flag defaulting to false, and an inclusive merchandising window bounded by `window_start` and a strictly later `window_end`."
    PRD §3.4: "A `LiveOpsCommander` provisions a **Player** with a `handle` that must be unique across all players (a collision yielding `ERR_PLAYER_HANDLE_DUPLICATE`), a price `region_code` of `NA`, `EU`, `LATAM`, or `APAC`, the `active_season_id` of the season the player is progressing through, and two optional protection flags: `is_minor`, which defaults to false and marks the account as belonging to a minor, and `guardian_verified`, which defaults to false and records that guardian consent is on file."
    PRD §3.4: "A new player starts with `spend_state` `UNRESTRICTED`, `retention_band` `HEALTHY`, `pacing_bp_realized` at 10000, `last_active_at` null, and `season_xp_total`, `session_count`, `spend_30d_minor`, `pending_spend_minor` and `lifetime_spend_minor` all at 0."
    PRD §3.8: "An `EconomyDesigner` authors a **BalanceChange** naming the `season_id` whose tuning is changed, a `target_kind` of `SINK_RATE`, `FAUCET_RATE`, `DROP_RATE`, or `PRICE`, a signed `delta_bp` between -3000 and 3000 basis points inclusive that must not be zero, a `rationale` recording the data-driven justification, and an optional `canary_cohort_pct` between 1 and 50 that defaults to 5 and states what percentage of players are exposed during the canary stage."
    PRD §3.8: "The change is stored in `DRAFT` with the authoring operator recorded as `authored_by_user_id`, `promoted_by_user_id` and `pre_live_sink_rate_bp` null, and `comms_state` at `MISSING`."
    PRD §3.1: "The season is stored in `PLANNED`, with `economy_health` at `HEALTHY`, `content_posture` at `ON_TRACK`, `version` at 1, and every derived counter at its opening value: `scheduled_episode_count`, `released_episode_count`, `cadence_debt_days`, `gross_faucet_minor`, `gross_sink_minor`, `pending_revenue_minor`, `settled_revenue_minor`, `live_offer_count`, `active_tuning_count` and `tuning_stage_epoch` all at 0, and `lifetime_ratio_bp` and `effective_sink_rate_bp` both at 10000."

    Design: Corner/entities/corner_entity_defaults_applied_when_optionals_omitted
    """
    reset_clock()
    season = create_planned_season()
    season_id = season["id"]

    cluster = validate_success(
        api.create_cluster({"name": "EU-1", "region_code": "EU", "ccu_capacity": 8000}, LIVEOPS),
        201,
    )
    assert cluster["maintenance_buffer_minutes"] == 30

    offer = validate_success(
        api.create_offer(
            _single_line_offer_body(season_id, "PACK_A", 499, 700, "COIN_PACK_A", "SOFT_COIN", 700),
            DESIGNER,
        ),
        201,
    )
    assert offer["personalization_discount_bp"] == 0
    assert offer["minor_purchasable"] is False

    player = validate_success(
        api.create_player(
            {"handle": "tide_default", "region_code": "NA", "active_season_id": season_id}, LIVEOPS
        ),
        201,
    )
    assert player["is_minor"] is False
    assert player["guardian_verified"] is False
    assert player["spend_state"] == "UNRESTRICTED"
    assert player["pacing_bp_realized"] == 10000
    assert player["retention_band"] == "HEALTHY"

    change = validate_success(
        api.create_balance_change(
            {
                "season_id": season_id,
                "target_kind": "DROP_RATE",
                "delta_bp": -250,
                "rationale": "Drop rate is 3 percent above target",
            },
            DESIGNER,
        ),
        201,
    )
    assert change["canary_cohort_pct"] == 5
    assert change["comms_state"] == "MISSING"

    stored_season = validate_success(api.get_season(season_id, LIVEOPS), 200)
    assert stored_season["lifetime_ratio_bp"] == 10000
    assert stored_season["effective_sink_rate_bp"] == 10000


def test_computed_fields_originate_from_the_formulas_not_from_client_input(api):
    """PRD §3.5: "Two figures are computed and stored on the table: `total_probability_bp`, the sum of the entries' `probability_bp`, which must come to exactly 10000 basis points or the request is refused with `ERR_DISCLOSURE_PROBABILITY_SUM`; and `expected_value_minor`, the sum over all entries of each entry's `probability_bp` multiplied by its `item_value_minor`, that total divided by 10000, and the result rounded half up."
    PRD §3.5: "A drafted table is `DRAFT` with `published_at` and `published_by_user_id` both null, and it does not yet change the offer's `disclosure_state`."
    PRD §3.5: "The value ratio in basis points is that declared value multiplied by 10000, divided by the offer's `list_price_minor`, rounded half up — so an offer that declares exactly the value it charges for scores 10000."
    PRD §3.5: "The index is the value ratio minus all three penalties, then clamped into the range 0 through 15000 — negative results become 0 and results above 15000 become 15000."
    PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."

    Design: Corner/entities/corner_entity_computed_fields_not_client_supplied
    """
    reset_clock()
    season = create_planned_season()

    crate = validate_success(
        api.create_offer(
            _single_line_offer_body(
                season["id"],
                "CRATE_A",
                300,
                400,
                "CRATE_KEY",
                "HARD_GEM",
                300,
                offer_type="LOOT_BOX",
                window_end="2026-08-20T00:00:00Z",
            ),
            DESIGNER,
        ),
        201,
    )

    disclosure = validate_success(
        api.create_disclosure(
            crate["id"],
            {
                "entries": [
                    {
                        "item_sku": "C_COMMON",
                        "probability_bp": 8500,
                        "item_value_minor": 200,
                        "is_rare": False,
                    },
                    {
                        "item_sku": "C_RARE",
                        "probability_bp": 1400,
                        "item_value_minor": 1500,
                        "is_rare": False,
                    },
                    {
                        "item_sku": "C_MYTHIC",
                        "probability_bp": 100,
                        "item_value_minor": 9000,
                        "is_rare": True,
                    },
                ]
            },
            DESIGNER,
        ),
        201,
    )

    assert disclosure["total_probability_bp"] == 10000
    assert disclosure["expected_value_minor"] == 470
    assert disclosure["status"] == "DRAFT"
    assert disclosure["published_at"] is None

    stored_offer = validate_success(api.get_offer(crate["id"], DESIGNER), 200)
    assert stored_offer["fairness_index_bp"] == 13333
    assert stored_offer["disclosure_state"] == "REQUIRED_MISSING"


def test_identity_audit_and_actor_fields_are_issued_by_the_server(api):
    """PRD §2.4: "Every resource the API mints carries an `id`, which is a server-generated UUID rendered as a plain string with no type prefix or other decoration."
    PRD §2.4: "Clients never supply an `id`."
    PRD §2.4: "Seasons, episodes, capacity clusters, live events, players, currency accounts, offers, probability disclosures, purchases, refund requests, balance changes, community notices and monitoring runs each expose `created_at` (an ISO 8601 UTC timestamp with three fractional digits, recording when the record was first stored), `updated_at` (the same format, refreshed on every mutation of the record), and `version` (an integer that starts at 1 on creation and increases by exactly 1 on every accepted mutation of that record, including mutations caused indirectly by a cascade from another resource)."
    PRD §2.4: "The logical clock starts at exactly `2026-08-01T00:00:00Z` and stays there until an operator moves it; the server never falls back to real wall-clock time."
    PRD §2.8: "The server stamps each entry with the logical-clock instant as `occurred_at`, attributes it to a season through `season_id`, and — when the flow belongs to a purchase grant, a purchase-attributed spend, or a refund reversal — records the `purchase_id` it belongs to."
    PRD §3.4: "On success a ledger entry is appended, attributed to the owning player's `active_season_id` as its `season_id`, and the full ledger fan-out of §2.8 runs: the account's lifetime totals and `balance_minor` move, the season's `gross_faucet_minor` or `gross_sink_minor` moves, the season's `lifetime_ratio_bp` is recomputed, and the account's `version` moves by 1."
    PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."

    Design: Corner/entities/corner_entity_system_fields_generated_by_server
    """
    set_clock("2026-08-04T00:00:00Z")
    season = create_planned_season()
    player = create_player(season["id"])
    account = open_account(player["id"], "SOFT_COIN")

    offer = validate_success(
        api.create_offer(
            _single_line_offer_body(
                season["id"],
                "PACK_A",
                499,
                700,
                "COIN_PACK_A",
                "SOFT_COIN",
                700,
                window_start="2026-08-04T00:00:00Z",
                window_end="2026-08-14T00:00:00Z",
            ),
            DESIGNER,
        ),
        201,
    )

    assert isinstance(offer["id"], str) and offer["id"], "id must be server-issued and non-empty"
    assert _same_instant(offer["created_at"], "2026-08-04T00:00:00Z")
    assert _same_instant(offer["updated_at"], "2026-08-04T00:00:00Z")
    assert offer["version"] == 1
    assert offer["created_by_user_id"] == "u_designer_1"
    assert offer["reviewed_by_user_id"] is None

    validate_success(
        api.create_adjustment(
            account["id"],
            {"direction": "FAUCET", "amount_minor": 1000, "source_kind": "EVENT_REWARD"},
            LIVEOPS,
        ),
        201,
    )

    rows, _meta = validate_paginated(
        api.list_ledger_entries(LIVEOPS, params={"currency_account_id": account["id"]})
    )
    entry = rows[0]
    assert_ledger_entry(entry)
    assert _same_instant(entry["occurred_at"], "2026-08-04T00:00:00Z")
    assert entry["season_id"] == season["id"]


def test_enum_range_and_window_violations_all_collapse_onto_invalid_request(api):
    """PRD §2.11: "Request-body schema conformance on every endpoint: required fields present, enum values in range, integers within their declared bounds, `window_end` strictly after `window_start`, `ends_at` strictly after `starts_at`, `list_price_minor` exactly equal to the sum of the line items' `base_price_minor`, line-item skus unique within the offer, `delta_bp` non-zero, disclosure entries well-formed, and pagination inside its bounds (`ERR_INVALID_REQUEST`)."
    PRD §3.4: "A `LiveOpsCommander` provisions a **Player** with a `handle` that must be unique across all players (a collision yielding `ERR_PLAYER_HANDLE_DUPLICATE`), a price `region_code` of `NA`, `EU`, `LATAM`, or `APAC`, the `active_season_id` of the season the player is progressing through, and two optional protection flags: `is_minor`, which defaults to false and marks the account as belonging to a minor, and `guardian_verified`, which defaults to false and records that guardian consent is on file."
    PRD §3.5: "Line skus must be unique within the offer, and the offer's `list_price_minor` must equal the sum of its lines' `base_price_minor` exactly — a mismatch, a duplicate line sku, a `personalization_discount_bp` outside the range 0 through 2000, or a line count outside 1 through 8 all being schema violations answered with `ERR_INVALID_REQUEST`."
    PRD §3.8: "An `EconomyDesigner` authors a **BalanceChange** naming the `season_id` whose tuning is changed, a `target_kind` of `SINK_RATE`, `FAUCET_RATE`, `DROP_RATE`, or `PRICE`, a signed `delta_bp` between -3000 and 3000 basis points inclusive that must not be zero, a `rationale` recording the data-driven justification, and an optional `canary_cohort_pct` between 1 and 50 that defaults to 5 and states what percentage of players are exposed during the canary stage."

    Design: Corner/entities/corner_entity_type_constraints_enums_ranges_windows
    """
    reset_clock()
    season = create_planned_season()
    season_id = season["id"]

    validate_error(
        api.create_player(
            {"handle": "tide_bad_region", "region_code": "MENA", "active_season_id": season_id},
            LIVEOPS,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api.create_offer(
            _single_line_offer_body(
                season_id,
                "PERS_TOO_HIGH",
                499,
                700,
                "COIN_PACK_A",
                "SOFT_COIN",
                700,
                personalization_discount_bp=2500,
            ),
            DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api.create_balance_change(
            {
                "season_id": season_id,
                "target_kind": "SINK_RATE",
                "delta_bp": 0,
                "rationale": "No-op tuning",
            },
            DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api.create_offer(
            _single_line_offer_body(
                season_id,
                "EMPTY_WINDOW",
                499,
                700,
                "COIN_PACK_B",
                "SOFT_COIN",
                700,
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-08-01T00:00:00Z",
            ),
            DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, player_meta = validate_paginated(
        api.list_players(LIVEOPS, params={"active_season_id": season_id})
    )
    assert player_meta["total_count"] == 0
    _rows, offer_meta = validate_paginated(api.list_offers(DESIGNER, params={"season_id": season_id}))
    assert offer_meta["total_count"] == 0
    _rows, change_meta = validate_paginated(
        api.list_balance_changes(DESIGNER, params={"season_id": season_id})
    )
    assert change_meta["total_count"] == 0


def test_ledger_row_is_corrected_by_appending_a_reversal_not_by_editing(api):
    """PRD §2.4: "Economy ledger entries are the exception."
    PRD §2.4: "A ledger entry is immutable once appended, so it exposes only `id` and `created_at`; it has no `updated_at` and no `version` field at all."
    PRD §2.8: "A compensating entry runs in the opposite `direction` from the entry it undoes, and it records that relationship in `reversal_of_entry_id`, which holds the `id` of the original entry."
    PRD §3.2: "For each recipient in that order a ledger entry is appended with `direction` `FAUCET`, `source_kind` `EPISODE_GRANT`, an `amount_minor` equal to the episode's `soft_currency_grant_minor` — every recipient receives exactly that amount, with no proration — and the episode's season as `season_id`; the episode's `grant_batch_size` records how many entries were appended."
    PRD §3.2: "First, for every ledger entry with `source_kind` `EPISODE_GRANT` that was appended by this episode's most recent release, taken in ascending `created_at` order, a compensating entry is appended with `direction` `SINK`, `source_kind` `EPISODE_ROLLBACK_REVERSAL`, the same `amount_minor` as the entry it undoes, and `reversal_of_entry_id` pointing at that entry's `id`."
    PRD §2.8: "The server stamps each entry with the logical-clock instant as `occurred_at`, attributes it to a season through `season_id`, and — when the flow belongs to a purchase grant, a purchase-attributed spend, or a refund reversal — records the `purchase_id` it belongs to."
    PRD §2.5: "Ledger reads accept `currency_account_id`, `season_id`, `purchase_id`, `reversal_of_entry_id`, `direction`, and `source_kind`."

    Design: Corner/entities/corner_entity_immutability_ledger_append_only
    """
    season = create_live_season()
    player = create_player(season["id"])
    account = open_account(player["id"], "SOFT_COIN")

    episode = create_scheduled_episode(season["id"])
    release_episode_at(episode["id"], "2026-08-02T00:00:00Z")

    grants = list_ledger(currency_account_id=account["id"], direction="FAUCET")
    grant_entry_id = grants[0]["id"]

    rollback_episode_at(episode["id"], "Bad grant table", "2026-08-03T00:00:00Z")

    original = validate_success(api.get_ledger_entry(grant_entry_id, LIVEOPS), 200)
    assert original["direction"] == "FAUCET"
    assert original["amount_minor"] == 1200
    assert original["source_kind"] == "EPISODE_GRANT"
    assert _same_instant(original["occurred_at"], "2026-08-02T00:00:00Z")
    assert original["reversal_of_entry_id"] is None
    assert "version" not in original, "an immutable ledger entry exposes no version field"
    assert "updated_at" not in original, "an immutable ledger entry exposes no updated_at field"

    reversals, meta = validate_paginated(
        api.list_ledger_entries(LIVEOPS, params={"reversal_of_entry_id": grant_entry_id})
    )
    assert meta["total_count"] == 1
    assert len(reversals) == 1
    assert reversals[0]["direction"] == "SINK"
    assert reversals[0]["amount_minor"] == 1200
    assert reversals[0]["source_kind"] == "EPISODE_ROLLBACK_REVERSAL"
    assert _same_instant(reversals[0]["occurred_at"], "2026-08-03T00:00:00Z")


def test_body_foreign_keys_are_resolved_to_entity_specific_not_found_codes(api):
    """PRD §2.11: "Existence of every foreign key carried in the request body — `season_id`, `capacity_cluster_id`, `active_season_id`, `player_id`, `offer_id`, `purchase_id` — on episode creation, live-event creation, player creation, offer creation, purchase creation, refund-request creation, tuning-change creation, monitoring-run creation, and currency-account adjustments (`ERR_SEASON_NOT_FOUND`, `ERR_CLUSTER_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_PURCHASE_NOT_FOUND`)."
    PRD §2.5: "Identifiers supplied in a request body are resolved after the path identifiers and produce the same not-found codes: `ERR_SEASON_NOT_FOUND`, `ERR_CLUSTER_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_PURCHASE_NOT_FOUND`."
    PRD §3.3: "The event is created in `PLANNED` with `reserved_ccu_at_approval` at 0 and `rollback_reason` null, and no capacity whatsoever is reserved until approval."
    PRD §2.5: "Live events accept `season_id`, `capacity_cluster_id`, and `status`."

    Design: Corner/entities/corner_entity_parent_relationship_and_fk_integrity
    """
    reset_clock()
    season = create_planned_season()
    cluster = validate_success(
        api.create_cluster({"name": "NA-1", "region_code": "NA", "ccu_capacity": 10000}, LIVEOPS),
        201,
    )

    validate_error(
        api.create_episode(
            {
                "season_id": "00000000-0000-0000-0000-0000000000aa",
                "sequence_no": 1,
                "title": "Orphan",
                "planned_release_at": "2026-08-02T00:00:00Z",
                "xp_grant": 600,
                "soft_currency_grant_minor": 0,
            },
            PRODUCER,
        ),
        ApiErrorId.ERR_SEASON_NOT_FOUND.value,
        404,
    )

    validate_error(
        api.create_live_event(
            {
                "season_id": season["id"],
                "capacity_cluster_id": "00000000-0000-0000-0000-0000000000bb",
                "code": "EVT_ORPHAN",
                "window_start": "2026-08-05T00:00:00Z",
                "window_end": "2026-08-05T02:00:00Z",
                "forecast_ccu": 1000,
            },
            PRODUCER,
        ),
        ApiErrorId.ERR_CLUSTER_NOT_FOUND.value,
        404,
    )

    event = validate_success(
        api.create_live_event(
            {
                "season_id": season["id"],
                "capacity_cluster_id": cluster["id"],
                "code": "EVT_A",
                "window_start": "2026-08-05T00:00:00Z",
                "window_end": "2026-08-05T02:00:00Z",
                "forecast_ccu": 1000,
            },
            PRODUCER,
        ),
        201,
    )
    assert event["status"] == "PLANNED"

    rows, meta = validate_paginated(
        api.list_live_events(LIVEOPS, params={"capacity_cluster_id": cluster["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["code"] == "EVT_A"

    _episodes, episode_meta = validate_paginated(
        api.list_season_episodes(season["id"], PRODUCER)
    )
    assert episode_meta["total_count"] == 0
    all_events, all_meta = validate_paginated(
        api.list_live_events(LIVEOPS, params={"season_id": season["id"]})
    )
    assert all_meta["total_count"] == 1
    assert all(row["code"] != "EVT_ORPHAN" for row in all_events)
