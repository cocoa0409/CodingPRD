"""When one request breaks two rules, the global precedence decides the single error returned."""

from typing import Any, Dict

from test_helpers import (
    DESIGNER,
    ApiErrorId,
    api_client,
    approve_offer,
    create_draft_offer,
    create_live_season,
    create_player,
    disclosure_entry,
    draft_disclosure,
    make_player_headers,
    offer_line_item,
    offer_version,
    open_account,
    publish_disclosure,
    publish_offer,
    read_offer,
    read_player,
    read_season,
    season_version,
    set_clock,
    submit_offer,
    validate_error,
)


def _setup_closed_window_over_cap_purchase() -> Dict[str, Any]:
    """A minor buyer, a LIVE offer quoted at 6000, and a clock parked past the offer window.

    The projected minor exposure is 0 + 0 + 6000, which breaches the 5000 ceiling, while the
    clock standing on 2026-08-15 is also past the offer's 2026-08-10 window end.
    """
    season = create_live_season()
    season_id = season["id"]

    player = create_player(
        season_id, handle="tide_p9_minor", is_minor=True, guardian_verified=True
    )
    open_account(player["id"], "HARD_GEM")

    offer = create_draft_offer(
        season_id,
        offer_type="LIMITED_TIME",
        sku="TEEN_PACK",
        price_tier="T1",
        list_price_minor=6000,
        line_items=[offer_line_item("TEEN_BUNDLE", 6000, 7500, "HARD_GEM", 6000)],
        personalization_discount_bp=0,
        minor_purchasable=True,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-10T00:00:00Z",
    )
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    publish_offer(offer["id"], season_id)

    set_clock("2026-08-15T00:00:00Z")

    return {
        "season_id": season_id,
        "player_id": player["id"],
        "offer_id": offer["id"],
        "pinned_offer_version": offer_version(offer["id"]),
    }


def _attempt_closed_window_purchase(ctx: Dict[str, Any]):
    return api_client.create_purchase(
        {
            "player_id": ctx["player_id"],
            "offer_id": ctx["offer_id"],
            "expected_offer_version": ctx["pinned_offer_version"],
        },
        make_player_headers(ctx["player_id"]),
    )


def _setup_missing_disclosure_and_sku_conflict() -> Dict[str, Any]:
    """Two loot boxes sharing the line sku CRATE_KEY; the second has no disclosure at all.

    GEM_CRATE_A is LIVE over 2026-08-01 to 2026-08-20, and GEM_CRATE_B opens on
    2026-08-21, exactly on A's window end plus the 24-hour cooldown.
    """
    season = create_live_season()
    season_id = season["id"]

    crate_a = create_draft_offer(
        season_id,
        offer_type="LOOT_BOX",
        sku="GEM_CRATE_A",
        price_tier="T1",
        list_price_minor=300,
        line_items=[offer_line_item("CRATE_KEY", 300, 400, "HARD_GEM", 300)],
        personalization_discount_bp=0,
        minor_purchasable=False,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    disclosure_a = draft_disclosure(
        crate_a["id"],
        entries=[
            disclosure_entry("C_COMMON", 8500, 200, False),
            disclosure_entry("C_RARE", 1400, 1500, False),
            disclosure_entry("C_MYTHIC", 100, 9000, True),
        ],
    )
    publish_disclosure(crate_a["id"], disclosure_a["id"])
    submit_offer(crate_a["id"])
    approve_offer(crate_a["id"])
    publish_offer(crate_a["id"], season_id)

    crate_b = create_draft_offer(
        season_id,
        offer_type="LOOT_BOX",
        sku="GEM_CRATE_B",
        price_tier="T1",
        list_price_minor=300,
        line_items=[offer_line_item("CRATE_KEY", 300, 400, "HARD_GEM", 300)],
        personalization_discount_bp=0,
        minor_purchasable=False,
        window_start="2026-08-21T00:00:00Z",
        window_end="2026-08-25T00:00:00Z",
    )
    submit_offer(crate_b["id"])
    approve_offer(crate_b["id"])

    return {
        "season_id": season_id,
        "crate_a_id": crate_a["id"],
        "crate_b_id": crate_b["id"],
        "pinned_season_version": season_version(season_id),
    }


def _attempt_conflicting_publish(ctx: Dict[str, Any]):
    return api_client.publish_offer(
        ctx["crate_b_id"],
        {"expected_season_version": ctx["pinned_season_version"]},
        DESIGNER,
    )


class TestPurchaseWindowClosedBeatsMinorSpendCap:
    def test_closed_offer_window_is_the_single_reported_error(self):
        """PRD §2.11: "When a single request violates more than one rule, exactly one error is returned, and which one is determined by a fixed global precedence."
        PRD §2.11: "Checks are evaluated in the following order, and the first failure short-circuits the request:"
        PRD §2.11: "Cross-entity state gates — the owning season is `LIVE` where required, the capacity cluster is `ACTIVE` where required, the currency account is not frozen, the offer is purchasable, the merchandising window is still open — on episode release, offer submit, offer publish, offer availability change, live-event approval, purchase creation, purchase settlement, currency-account adjustment, and tuning-change advance (`ERR_SEASON_NOT_LIVE`, `ERR_CLUSTER_NOT_ACTIVE`, `ERR_CURRENCY_ACCOUNT_FROZEN`, `ERR_OFFER_NOT_PURCHASABLE`, `ERR_OFFER_WINDOW_CLOSED`)."
        PRD §2.11: "The minor monthly spend ceiling on purchase creation (`ERR_MINOR_SPEND_CAP_EXCEEDED`)."
        PRD §3.6: "Beyond the ownership and pin checks, the offer must actually be sellable: its `availability_status` must be `LIVE`, anything else being refused with `ERR_OFFER_NOT_PURCHASABLE`, and the clock must be at or before its `window_end`, a closed window yielding `ERR_OFFER_WINDOW_CLOSED`."
        PRD §3.7: "The minor spend ceiling behaves the other way round: at purchase creation, a player whose `is_minor` flag is true has a projected exposure formed as the sum of their current `spend_30d_minor`, their outstanding `pending_spend_minor`, and the `quoted_price_minor` of the purchase being created, and the purchase is refused with `ERR_MINOR_SPEND_CAP_EXCEEDED` only when that projected total is strictly greater than 5000 minor units — landing exactly on 5000 is allowed."

        Design: Difficulty/priority_pair_validation_conflict/purchase_window_closed_beats_minor_spend_cap
        """
        ctx = _setup_closed_window_over_cap_purchase()

        error = validate_error(
            _attempt_closed_window_purchase(ctx),
            ApiErrorId.ERR_OFFER_WINDOW_CLOSED.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_MINOR_SPEND_CAP_EXCEEDED.value, (
            "the merchandising-window gate is evaluated before the minor monthly ceiling, so the "
            f"spend-cap error must never win, got {error['error_id']}"
        )

    def test_rejected_purchase_leaves_no_pending_exposure(self):
        """PRD §2.11: "Checks are evaluated in the following order, and the first failure short-circuits the request:"
        PRD §3.6: "Beyond the ownership and pin checks, the offer must actually be sellable: its `availability_status` must be `LIVE`, anything else being refused with `ERR_OFFER_NOT_PURCHASABLE`, and the clock must be at or before its `window_end`, a closed window yielding `ERR_OFFER_WINDOW_CLOSED`."
        PRD §3.6: "The offer's `pending_purchase_count` rises by 1 and its `version` moves by 1; the season's `pending_revenue_minor` and the player's `pending_spend_minor` each rise by the quoted price."

        Design: Difficulty/priority_pair_validation_conflict/purchase_window_closed_beats_minor_spend_cap
        """
        ctx = _setup_closed_window_over_cap_purchase()

        validate_error(
            _attempt_closed_window_purchase(ctx),
            ApiErrorId.ERR_OFFER_WINDOW_CLOSED.value,
            409,
        )

        offer = read_offer(ctx["offer_id"])
        assert offer["pending_purchase_count"] == 0, (
            "a short-circuited purchase creation must not raise the offer's pending count, got "
            f"{offer['pending_purchase_count']}"
        )
        assert offer["availability_status"] == "LIVE", (
            "a closed window does not itself move the storefront dimension, got "
            f"{offer['availability_status']}"
        )

        player = read_player(ctx["player_id"])
        assert player["pending_spend_minor"] == 0, (
            f"the buyer's pending spend must stay at 0, got {player['pending_spend_minor']}"
        )

        season = read_season(ctx["season_id"])
        assert season["pending_revenue_minor"] == 0, (
            f"the season's pending revenue must stay at 0, got {season['pending_revenue_minor']}"
        )


class TestDisclosureMissingBeatsSkuWindowConflict:
    def test_missing_probability_table_is_the_single_reported_error(self):
        """PRD §2.11: "When a single request violates more than one rule, exactly one error is returned, and which one is determined by a fixed global precedence."
        PRD §2.11: "Checks are evaluated in the following order, and the first failure short-circuits the request:"
        PRD §2.11: "Randomized-item disclosure state on offer publish, offer availability change, and purchase creation (`ERR_DISCLOSURE_NOT_PUBLISHED`)."
        PRD §2.11: "Sku-window collision on offer publish (`ERR_OFFER_SKU_WINDOW_CONFLICT`)."
        PRD §3.5: "The offer's `availability_status` must be `OFFLINE` and its `approval_status` must be `APPROVED`; the season must be `LIVE`; the pinned `expected_season_version` must match the season's current `version`, as §2.7 describes; the logical clock must be at or before the offer's `window_end`, a closed window yielding `ERR_OFFER_WINDOW_CLOSED`; the offer's `disclosure_state` must not be `REQUIRED_MISSING`, a randomized offer without a published table being refused with `ERR_DISCLOSURE_NOT_PUBLISHED`; the freshly recomputed `fairness_index_bp` must be at least 8000 basis points, a lower index being refused with `ERR_FAIRNESS_FLOOR_BREACH`; there must be no sku-window collision; the season's `economy_health` must not be `INFLATED`; and if the `offer_type` is `LIMITED_TIME`, the season's `content_posture` must not be `BEHIND`."
        PRD §3.5: "A sibling conflicts when the candidate's `window_start` is at or before that sibling's `window_end` plus the cooldown **and** the sibling's `window_start` is at or before the candidate's `window_end` plus the cooldown — closed comparisons on both sides, so exact adjacency counts as a conflict, as does any gap shorter than 24 hours."
        PRD §3.5: "There is no aggregate allowance here: a single conflicting sibling is fatal, and the publish is refused with `ERR_OFFER_SKU_WINDOW_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/offer_publish_disclosure_missing_beats_sku_window_conflict
        """
        ctx = _setup_missing_disclosure_and_sku_conflict()

        error = validate_error(
            _attempt_conflicting_publish(ctx),
            ApiErrorId.ERR_DISCLOSURE_NOT_PUBLISHED.value,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_OFFER_SKU_WINDOW_CONFLICT.value, (
            "the randomized-item disclosure gate is evaluated before the sku-window collision, so "
            f"the collision error must never win, got {error['error_id']}"
        )

    def test_rejected_publish_leaves_offer_offline_with_unpublished_table(self):
        """PRD §2.11: "Checks are evaluated in the following order, and the first failure short-circuits the request:"
        PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."
        PRD §3.5: "The declared value of the offer is the sum of its lines' `declared_value_minor`."
        PRD §3.5: "The value ratio in basis points is that declared value multiplied by 10000, divided by the offer's `list_price_minor`, rounded half up — so an offer that declares exactly the value it charges for scores 10000."
        PRD §3.5: "The scarcity penalty looks at the length of the merchandising window in whole hours, taken as the difference between `window_end` and `window_start` divided by 3600 and truncated downward: a window of 72 hours or longer draws no penalty, a window of at least 24 hours but shorter than 72 draws 500 basis points, and anything shorter than 24 hours draws 1200."
        PRD §3.5: "The minor-safety penalty is 800 basis points when the offer is a `LOOT_BOX` whose `minor_purchasable` flag is true, and 0 in every other case."
        PRD §3.5: "The personalization penalty is the offer's `personalization_discount_bp` divided by 5, rounded half up, then capped at 600 basis points."
        PRD §3.5: "The index is the value ratio minus all three penalties, then clamped into the range 0 through 15000 — negative results become 0 and results above 15000 become 15000."
        PRD §3.5: "A successful publish raises the season's `live_offer_count` by 1 and moves both the season's and the offer's `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/offer_publish_disclosure_missing_beats_sku_window_conflict
        """
        ctx = _setup_missing_disclosure_and_sku_conflict()

        validate_error(
            _attempt_conflicting_publish(ctx),
            ApiErrorId.ERR_DISCLOSURE_NOT_PUBLISHED.value,
            422,
        )

        crate_b = read_offer(ctx["crate_b_id"])
        assert crate_b["availability_status"] == "OFFLINE", (
            f"the refused publish must leave the offer OFFLINE, got {crate_b['availability_status']}"
        )
        assert crate_b["disclosure_state"] == "REQUIRED_MISSING", (
            "a loot box with no published table stays at REQUIRED_MISSING, got "
            f"{crate_b['disclosure_state']}"
        )
        assert crate_b["fairness_index_bp"] == 13333, (
            "declared 400 over list 300 is 13333 bp with no scarcity, minor-safety or "
            f"personalization penalty, got {crate_b['fairness_index_bp']}"
        )

        season = read_season(ctx["season_id"])
        assert season["live_offer_count"] == 1, (
            "only the first loot box reached the storefront, so live_offer_count stays at 1, got "
            f"{season['live_offer_count']}"
        )
