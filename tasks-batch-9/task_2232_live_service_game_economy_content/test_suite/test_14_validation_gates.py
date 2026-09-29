"""Validation gates: sum rules, cross-entity gates, conditional gates and rejection precedence."""

from typing import Any, Dict, List

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    approve_offer,
    create_live_season,
    create_player,
    create_single_line_offer,
    disclosure_entry,
    make_player_headers,
    open_account,
    publish_disclosure,
    publish_offer,
    read_account,
    read_offer,
    read_player,
    read_season,
    season_version,
    submit_offer,
    validate_error,
    validate_paginated,
    validate_success,
)


def _crate_entries(first_probability_bp: int) -> List[Dict[str, Any]]:
    """Three randomized-item rows whose first probability is the caller's choice."""
    return [
        disclosure_entry("COMMON_SKIN", first_probability_bp, 200),
        disclosure_entry("RARE_SKIN", 1400, 1500),
        disclosure_entry("MYTHIC_SKIN", 100, 9000),
    ]


def _draft_loot_box(season_id: str, sku: str = "CRATE_A") -> Dict[str, Any]:
    """A randomized offer priced 300 whose single line declares 400."""
    return create_single_line_offer(
        season_id,
        sku,
        300,
        400,
        offer_type="LOOT_BOX",
        granted_currency_code="HARD_GEM",
        granted_amount_minor=300,
    )


def test_disclosure_probabilities_must_total_exactly_10000(api, designer_headers):
    """PRD §3.5: "Two figures are computed and stored on the table: `total_probability_bp`, the sum of the entries' `probability_bp`, which must come to exactly 10000 basis points or the request is refused with `ERR_DISCLOSURE_PROBABILITY_SUM`; and `expected_value_minor`, the sum over all entries of each entry's `probability_bp` multiplied by its `item_value_minor`, that total divided by 10000, and the result rounded half up."

    PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."

    Design: Corner/validations/corner_val_disclosure_probability_sum_violation
    """
    season = create_live_season()
    crate = _draft_loot_box(season["id"])

    response = api.create_disclosure(
        crate["id"], {"entries": _crate_entries(8400)}, designer_headers
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_PROBABILITY_SUM)

    tables, meta = validate_paginated(api.list_disclosures(crate["id"], designer_headers))
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert tables == [], "A refused table must not be stored"
    assert read_offer(crate["id"])["disclosure_state"] == "REQUIRED_MISSING"


def test_publish_succeeds_when_every_gate_is_satisfied(api, designer_headers):
    """PRD §3.5: "Two figures are computed and stored on the table: `total_probability_bp`, the sum of the entries' `probability_bp`, which must come to exactly 10000 basis points or the request is refused with `ERR_DISCLOSURE_PROBABILITY_SUM`; and `expected_value_minor`, the sum over all entries of each entry's `probability_bp` multiplied by its `item_value_minor`, that total divided by 10000, and the result rounded half up."

    PRD §3.5: "On success the table's `published_at` is stamped with the clock and `published_by_user_id` with the acting `X-User-ID`; any other table of the same offer that was `PUBLISHED` is carried `PUBLISHED → SUPERSEDED`, its own `version` moving by 1; and the offer's `disclosure_state` becomes `PUBLISHED` with the offer's `version` moving by 1."

    PRD §3.5: "The declared value of the offer is the sum of its lines' `declared_value_minor`."

    PRD §3.5: "The value ratio in basis points is that declared value multiplied by 10000, divided by the offer's `list_price_minor`, rounded half up — so an offer that declares exactly the value it charges for scores 10000."

    PRD §3.5: "The offer's `availability_status` must be `OFFLINE` and its `approval_status` must be `APPROVED`; the season must be `LIVE`; the pinned `expected_season_version` must match the season's current `version`, as §2.7 describes; the logical clock must be at or before the offer's `window_end`, a closed window yielding `ERR_OFFER_WINDOW_CLOSED`; the offer's `disclosure_state` must not be `REQUIRED_MISSING`, a randomized offer without a published table being refused with `ERR_DISCLOSURE_NOT_PUBLISHED`; the freshly recomputed `fairness_index_bp` must be at least 8000 basis points, a lower index being refused with `ERR_FAIRNESS_FLOOR_BREACH`; there must be no sku-window collision; the season's `economy_health` must not be `INFLATED`; and if the `offer_type` is `LIMITED_TIME`, the season's `content_posture` must not be `BEHIND`."

    PRD §3.5: "A successful publish raises the season's `live_offer_count` by 1 and moves both the season's and the offer's `version` by 1."

    Design: Corner/validations/corner_val_publish_satisfies_every_gate
    """
    season = create_live_season()
    crate = _draft_loot_box(season["id"])

    table = validate_success(
        api.create_disclosure(crate["id"], {"entries": _crate_entries(8500)}, designer_headers),
        201,
    )
    publish_disclosure(crate["id"], table["id"])
    submit_offer(crate["id"])
    approve_offer(crate["id"])

    pinned_version = season_version(season["id"])
    published = validate_success(
        api.publish_offer(
            crate["id"], {"expected_season_version": pinned_version}, designer_headers
        ),
        200,
    )

    tables, _ = validate_paginated(api.list_disclosures(crate["id"], designer_headers))
    stored = next(row for row in tables if row["id"] == table["id"])
    assert stored["total_probability_bp"] == 10000, (
        f"Expected total_probability_bp 10000, got {stored['total_probability_bp']}"
    )
    assert stored["expected_value_minor"] == 470, (
        f"Expected expected_value_minor 470, got {stored['expected_value_minor']}"
    )

    offer = read_offer(crate["id"])
    assert offer["disclosure_state"] == "PUBLISHED"
    assert offer["fairness_index_bp"] == 13333, (
        f"Expected fairness_index_bp 13333, got {offer['fairness_index_bp']}"
    )
    assert offer["approval_status"] == "APPROVED"
    assert offer["availability_status"] == "LIVE"
    assert published["availability_status"] == "LIVE"
    assert read_season(season["id"])["live_offer_count"] == 1


def test_role_screening_precedes_season_existence(api):
    """PRD §2.11: "When a single request violates more than one rule, exactly one error is returned, and which one is determined by a fixed global precedence."

    PRD §2.11: "2. Role authorization — the acting role appears in the endpoint's authorized list — on every endpoint (`ERR_UNAUTHORIZED`)."

    PRD §2.11: "3. Existence of every path-addressed resource, left to right, on every path-parameterised endpoint (the family of 404 codes listed in §2.5)."

    PRD §2.1: "If the headers are well-formed but the acting role does not appear in the authorized-role list for the endpoint being called (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/corner_val_unauthorized_role_precedes_not_found
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pz")

    response = api.set_season_status(
        NON_EXISTENT_UUID, {"to_status": "LIVE"}, make_player_headers(player["id"])
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert error["error_id"] != "ERR_SEASON_NOT_FOUND", (
        "Role screening must win over existence resolution"
    )


def test_stale_offer_version_precedes_closed_window_on_purchase(api, liveops_headers):
    """PRD §2.11: "When a single request violates more than one rule, exactly one error is returned, and which one is determined by a fixed global precedence."

    PRD §2.11: "7. Version pinning on offer publish, tuning-change advance and purchase creation (`ERR_STALE_SEASON_VERSION`, `ERR_STALE_OFFER_VERSION`)."

    PRD §2.11: "9. Cross-entity state gates — the owning season is `LIVE` where required, the capacity cluster is `ACTIVE` where required, the currency account is not frozen, the offer is purchasable, the merchandising window is still open — on episode release, offer submit, offer publish, offer availability change, live-event approval, purchase creation, purchase settlement, currency-account adjustment, and tuning-change advance (`ERR_SEASON_NOT_LIVE`, `ERR_CLUSTER_NOT_ACTIVE`, `ERR_CURRENCY_ACCOUNT_FROZEN`, `ERR_OFFER_NOT_PURCHASABLE`, `ERR_OFFER_WINDOW_CLOSED`)."

    PRD §2.7: "If that number does not equal the offer's current `version`, the purchase creation is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412)."

    PRD §3.6: "Beyond the ownership and pin checks, the offer must actually be sellable: its `availability_status` must be `LIVE`, anything else being refused with `ERR_OFFER_NOT_PURCHASABLE`, and the clock must be at or before its `window_end`, a closed window yielding `ERR_OFFER_WINDOW_CLOSED`."

    PRD §3.4: "Each account records its owner as `player_id`, opens `ACTIVE` with `balance_minor`, `lifetime_faucet_minor` and `lifetime_sink_minor` all at 0, and its `status` thereafter tracks the owning player: an account is `FROZEN` for exactly as long as its player's `spend_state` is `LOCKED`."

    Design: Corner/validations/corner_val_stale_version_precedes_window_gate
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pw")
    account = open_account(player["id"], "HARD_GEM")

    offer = create_single_line_offer(
        season["id"],
        "WIN_PACK",
        900,
        1200,
        granted_currency_code="HARD_GEM",
        granted_amount_minor=900,
    )
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    published = publish_offer(offer["id"], season["id"])
    stale_version = published["version"]

    validate_success(
        api.set_offer_availability(
            offer["id"], {"to_status": "SUSPENDED", "reason": "Art fix"}, liveops_headers
        )
    )
    validate_success(
        api.set_offer_availability(
            offer["id"], {"to_status": "LIVE", "reason": "Art fix shipped"}, liveops_headers
        )
    )
    validate_success(api.set_clock("2026-08-25T00:00:00Z", liveops_headers))

    response = api.create_purchase(
        {
            "player_id": player["id"],
            "offer_id": offer["id"],
            "expected_offer_version": stale_version,
        },
        make_player_headers(player["id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_STALE_OFFER_VERSION)
    assert error["error_id"] != "ERR_OFFER_WINDOW_CLOSED", (
        "The concurrency pin must be reported ahead of the window gate"
    )

    _, meta = validate_paginated(
        api.list_purchases(liveops_headers, params={"player_id": player["id"]})
    )
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert read_account(account["id"])["balance_minor"] == 0


def test_locking_the_owner_freezes_the_account_against_adjustments(
    api, liveops_headers, compliance_headers
):
    """PRD §3.4: "Each account records its owner as `player_id`, opens `ACTIVE` with `balance_minor`, `lifetime_faucet_minor` and `lifetime_sink_minor` all at 0, and its `status` thereafter tracks the owning player: an account is `FROZEN` for exactly as long as its player's `spend_state` is `LOCKED`."

    PRD §3.4: "The account must exist and must not be `FROZEN`, a frozen account being refused with `ERR_CURRENCY_ACCOUNT_FROZEN`, and a supplied `purchase_id` must resolve or the request fails with `ERR_PURCHASE_NOT_FOUND`."

    PRD §3.7: "Locking is a cascade: every currency account of the player is moved to `FROZEN` with each account's `version` moving by 1, every purchase of the player still in `PENDING` is denied with the `deny_reason` `SPEND_LOCKED` while the season's `pending_revenue_minor` and the player's `pending_spend_minor` are each lowered by that purchase's `quoted_price_minor`, and the player's own `version` moves by 1."

    PRD §3.4: "On success a ledger entry is appended, attributed to the owning player's `active_season_id` as its `season_id`, and the full ledger fan-out of §2.8 runs: the account's lifetime totals and `balance_minor` move, the season's `gross_faucet_minor` or `gross_sink_minor` moves, the season's `lifetime_ratio_bp` is recomputed, and the account's `version` moves by 1."

    Design: Corner/validations/corner_val_cross_entity_frozen_account_blocks_adjustment
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pf")
    account = open_account(player["id"], "SOFT_COIN")

    faucet = {"direction": "FAUCET", "amount_minor": 500, "source_kind": "ADMIN_ADJUSTMENT"}
    validate_success(api.create_adjustment(account["id"], faucet, liveops_headers), 201)

    validate_success(
        api.set_spend_guard(
            player["id"],
            {"action": "LOCK", "note": "Chargeback investigation"},
            compliance_headers,
        )
    )

    blocked = api.create_adjustment(account["id"], faucet, liveops_headers)
    validate_error(blocked, ApiErrorId.ERR_CURRENCY_ACCOUNT_FROZEN)

    assert read_player(player["id"])["spend_state"] == "LOCKED"
    stored_account = read_account(account["id"])
    assert stored_account["status"] == "FROZEN"
    assert stored_account["balance_minor"] == 500

    _, meta = validate_paginated(
        api.list_ledger_entries(liveops_headers, params={"currency_account_id": account["id"]})
    )
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"


def test_guardian_gate_applies_only_to_minors(api, liveops_headers):
    """PRD §3.7: "A player flagged `is_minor` whose `guardian_verified` flag is false may not transact at all, and the attempt is refused with `ERR_GUARDIAN_VERIFICATION_REQUIRED`."

    PRD §3.6: "On success the purchase is stored in `PENDING` with `quoted_price_minor` and `applied_personalization_bp` pinned from the quote just computed, `price_paid_minor` and `granted_total_minor` and `granted_consumed_minor` at 0, `settled_at` and `deny_reason` null, and `is_minor_purchase` snapshotted from the buyer's `is_minor` flag at this moment so that a later change to the account's minor status cannot rewrite history."

    Design: Corner/validations/corner_val_conditional_guardian_flag_only_for_minors
    """
    season = create_live_season()
    minor = create_player(
        season["id"], handle="tide_pk", is_minor=True, guardian_verified=False
    )
    open_account(minor["id"], "HARD_GEM")
    adult = create_player(
        season["id"], handle="tide_pa", is_minor=False, guardian_verified=False
    )
    open_account(adult["id"], "HARD_GEM")

    offer = create_single_line_offer(
        season["id"],
        "KID_PACK",
        300,
        400,
        granted_currency_code="HARD_GEM",
        granted_amount_minor=300,
        minor_purchasable=True,
    )
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    live = publish_offer(offer["id"], season["id"])
    pinned = live["version"]

    refused = api.create_purchase(
        {"player_id": minor["id"], "offer_id": offer["id"], "expected_offer_version": pinned},
        make_player_headers(minor["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_GUARDIAN_VERIFICATION_REQUIRED)

    accepted = api.create_purchase(
        {"player_id": adult["id"], "offer_id": offer["id"], "expected_offer_version": pinned},
        make_player_headers(adult["id"]),
    )
    validate_success(accepted, 201)

    _, minor_meta = validate_paginated(
        api.list_purchases(liveops_headers, params={"player_id": minor["id"]})
    )
    assert minor_meta["total_count"] == 0, (
        f"Expected total_count 0, got {minor_meta['total_count']}"
    )
    _, adult_meta = validate_paginated(
        api.list_purchases(liveops_headers, params={"player_id": adult["id"]})
    )
    assert adult_meta["total_count"] == 1, (
        f"Expected total_count 1, got {adult_meta['total_count']}"
    )


def test_sequence_continuity_is_checked_before_the_season_window(api, producer_headers):
    """PRD §2.11: "When a single request violates more than one rule, exactly one error is returned, and which one is determined by a fixed global precedence."

    PRD §2.11: "19. Episode sequence continuity on episode creation and episode scheduling (`ERR_EPISODE_SEQUENCE_GAP`)."

    PRD §2.11: "22. Episode release instant inside the season window, on episode creation and episode scheduling (`ERR_SEASON_WINDOW_VIOLATION`)."

    PRD §3.2: "Two constraints bind at creation: the `sequence_no` must be exactly one greater than the highest `sequence_no` already used in that season (the first episode of a season therefore being 1), and any gap or reuse is refused with `ERR_EPISODE_SEQUENCE_GAP`; and `planned_release_at` must fall inside the season's inclusive window from `starts_at` to `ends_at`, an instant outside it being refused with `ERR_SEASON_WINDOW_VIOLATION`."

    Design: Corner/validations/corner_val_sequence_gap_checked_before_season_window
    """
    season = create_live_season()
    validate_success(
        api.create_episode(
            {
                "season_id": season["id"],
                "sequence_no": 1,
                "title": "E1 Tidefall",
                "planned_release_at": "2026-08-02T00:00:00Z",
                "xp_grant": 600,
                "soft_currency_grant_minor": 0,
            },
            producer_headers,
        ),
        201,
    )

    response = api.create_episode(
        {
            "season_id": season["id"],
            "sequence_no": 3,
            "title": "E3 Out Of Band",
            "planned_release_at": "2026-12-01T00:00:00Z",
            "xp_grant": 600,
            "soft_currency_grant_minor": 0,
        },
        producer_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_EPISODE_SEQUENCE_GAP)
    assert error["error_id"] != "ERR_SEASON_WINDOW_VIOLATION", (
        "The roadmap slot is resolved before the window check"
    )

    _, meta = validate_paginated(api.list_season_episodes(season["id"], producer_headers))
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"


def test_sink_may_drain_an_account_to_zero_but_never_below(api, liveops_headers):
    """PRD §3.4: "A `SINK` adjustment may never remove more than the account currently holds: an `amount_minor` exceeding `balance_minor` is refused with `ERR_INSUFFICIENT_BALANCE`."

    PRD §2.8: "The credited or debited account's `lifetime_faucet_minor` or `lifetime_sink_minor` grows by the entry's `amount_minor`, and its `balance_minor` is then recomputed as lifetime faucet total minus lifetime sink total — a quantity that is never allowed to go negative."

    PRD §2.8: "The owning season's `gross_faucet_minor` or `gross_sink_minor` grows by the same amount, and because those season totals changed, the season's `lifetime_ratio_bp` is recomputed."

    PRD §3.9: "In both readings the candidate rows are the ledger entries attributed to the season, and the ratio itself is formed the same way: when the faucet total and the sink total are both zero the ratio is exactly 10000 basis points; when the faucet total is zero but sinks exist the ratio is 20000 basis points; otherwise it is the sink total multiplied by 10000, divided by the faucet total, rounded half up, and then capped at 20000."

    Design: Corner/validations/corner_val_insufficient_balance_blocks_sink
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pb")
    account = open_account(player["id"], "SOFT_COIN")

    validate_success(
        api.create_adjustment(
            account["id"],
            {"direction": "FAUCET", "amount_minor": 1000, "source_kind": "ADMIN_ADJUSTMENT"},
            liveops_headers,
        ),
        201,
    )

    over_sink = api.create_adjustment(
        account["id"],
        {"direction": "SINK", "amount_minor": 1500, "source_kind": "OFFER_SPEND"},
        liveops_headers,
    )
    validate_error(over_sink, ApiErrorId.ERR_INSUFFICIENT_BALANCE)

    exact_sink = api.create_adjustment(
        account["id"],
        {"direction": "SINK", "amount_minor": 1000, "source_kind": "OFFER_SPEND"},
        liveops_headers,
    )
    validate_success(exact_sink, 201)

    assert read_account(account["id"])["balance_minor"] == 0

    _, meta = validate_paginated(
        api.list_ledger_entries(liveops_headers, params={"currency_account_id": account["id"]})
    )
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"

    stored_season = read_season(season["id"])
    assert stored_season["gross_sink_minor"] == 1000
    assert stored_season["gross_faucet_minor"] == 1000
    assert stored_season["lifetime_ratio_bp"] == 10000
