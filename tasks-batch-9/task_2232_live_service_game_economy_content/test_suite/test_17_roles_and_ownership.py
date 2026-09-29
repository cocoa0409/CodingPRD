"""Role-based access control, per-role exclusive operations, player ownership scoping and
segregation of duties."""

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE,
    DESIGNER,
    LIVEOPS,
    OPERATOR_IDS,
    PRODUCER,
    ApiErrorId,
    api_client,
    create_approved_offer,
    create_draft_balance_change,
    create_live_season,
    create_player,
    disclosure_entry,
    draft_comms_notice,
    make_headers,
    make_player_headers,
    offer_line_item,
    open_account,
    publish_offer,
    read_balance_change,
    read_offer,
    read_player,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _ok(response) -> Dict[str, Any]:
    """Assert a 2XX answer and hand back its data payload."""
    assert 200 <= response.status_code < 300, (
        f"Expected a 2XX status, got {response.status_code}: {response.text}"
    )
    return validate_success(response, response.status_code)


def test_undeclared_role_header_is_unauthenticated():
    """A role string outside the five declared roles fails authentication rather than
    authorization, so it never reaches the endpoint's role list.

    PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. Five roles exist, and their names are spelled exactly as follows: `ContentProducer`, `EconomyDesigner`, `LiveOpsCommander`, `ComplianceOfficer`, and `Player`. If either header is absent, or if `X-User-Role` carries a value that is not one of those five, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the acting role does not appear in the authorized-role list for the endpoint being called (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_unknown_role_header_unauthenticated
    """
    season = create_live_season()

    response = api_client.get_season(season["id"], make_headers("u_press_1", "GameJournalist"))
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value


def test_every_role_performs_its_exclusive_operations():
    """One end-to-end pass in which each of the five roles drives the operations reserved to it,
    from season and episode authoring through offer governance to the player's own refund.

    PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. Five roles exist, and their names are spelled exactly as follows: `ContentProducer`, `EconomyDesigner`, `LiveOpsCommander`, `ComplianceOfficer`, and `Player`. If either header is absent, or if `X-User-Role` carries a value that is not one of those five, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the acting role does not appear in the authorized-role list for the endpoint being called (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.2: "A successful schedule raises the season's `scheduled_episode_count` by 1, recomputes the season's `cadence_debt_days` and `content_posture`, and moves the season's `version` by 1."
    PRD §3.3: "On success the event's `forecast_ccu` is snapshotted into `reserved_ccu_at_approval`, the cluster's `reserved_ccu` grows by that same figure, and the cluster's `version` moves by 1."
    PRD §3.5: "Approving carries the offer `IN_REVIEW → APPROVED`, records the reviewer as `reviewed_by_user_id`, and moves the offer's `version` by 1."
    PRD §3.5: "Publishing an offer to the storefront carries it `OFFLINE → LIVE` and is open to an `EconomyDesigner` or a `LiveOpsCommander`."
    PRD §3.7: "**Step three** selects the restocking fee tier, and it is keyed on the Step-two figure and on nothing else: the tier is 0 basis points when `refund_base_minor` is strictly below 1000 minor units, 500 basis points when it is at least 1000 but strictly below 5000, and 1000 basis points at 5000 or above."
    PRD §3.7: "**Step five** computes `refund_amount_minor`: `refund_base_minor` minus `restock_fee_minor`, floored at 0."
    PRD §3.7: "The purchase itself is carried `SETTLED → REFUNDED`, which is terminal for it, and its `version` moves by 1."
    PRD §3.7: "Finally the request's `executed_at` is stamped with the clock, the request lands in `EXECUTED`, and its `version` moves by 1."
    PRD §3.7: "Locking is a cascade: every currency account of the player is moved to `FROZEN` with each account's `version` moving by 1, every purchase of the player still in `PENDING` is denied with the `deny_reason` `SPEND_LOCKED` while the season's `pending_revenue_minor` and the player's `pending_spend_minor` are each lowered by that purchase's `quoted_price_minor`, and the player's own `version` moves by 1."

    Design: Corner/rbac/corner_rbac_every_role_performs_its_exclusive_operations
    """
    set_clock("2026-08-01T00:00:00Z")

    season = _ok(
        api_client.create_season(
            {
                "code": "S7",
                "title": "Season 7 Tidebreak",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-10-30T00:00:00Z",
                "planned_episode_count": 6,
                "target_xp_total": 9000,
                "pass_price_minor": 1000,
            },
            PRODUCER,
        )
    )
    _ok(api_client.set_season_status(season["id"], {"to_status": "LIVE"}, PRODUCER))

    episode = _ok(
        api_client.create_episode(
            {
                "season_id": season["id"],
                "sequence_no": 1,
                "title": "E1 Tidefall",
                "planned_release_at": "2026-08-02T00:00:00Z",
                "xp_grant": 600,
                "soft_currency_grant_minor": 0,
            },
            PRODUCER,
        )
    )
    _ok(api_client.schedule_episode(episode["id"], PRODUCER))

    cluster = _ok(
        api_client.create_cluster({"name": "NA-1", "region_code": "NA", "ccu_capacity": 10000}, LIVEOPS)
    )
    event = _ok(
        api_client.create_live_event(
            {
                "season_id": season["id"],
                "capacity_cluster_id": cluster["id"],
                "code": "EVT_ROLE",
                "window_start": "2026-08-05T00:00:00Z",
                "window_end": "2026-08-05T02:00:00Z",
                "forecast_ccu": 1000,
            },
            PRODUCER,
        )
    )
    _ok(api_client.approve_live_event(event["id"], LIVEOPS))

    player = _ok(
        api_client.create_player(
            {"handle": "tide_prole", "region_code": "NA", "active_season_id": season["id"]}, LIVEOPS
        )
    )
    account = _ok(
        api_client.create_currency_account(player["id"], {"currency_code": "HARD_GEM"}, LIVEOPS)
    )
    _ok(
        api_client.ingest_engagement_event(
            player["id"], {"xp_delta": 300, "sessions_delta": 2}, LIVEOPS
        )
    )

    offer = _ok(
        api_client.create_offer(
            {
                "season_id": season["id"],
                "offer_type": "LOOT_BOX",
                "sku": "ROLE_PACK",
                "price_tier": "T1",
                "list_price_minor": 300,
                "line_items": [offer_line_item("ROLE_KEY", 300, 400, "HARD_GEM", 300)],
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-20T00:00:00Z",
            },
            DESIGNER,
        )
    )
    disclosure = _ok(
        api_client.create_disclosure(
            offer["id"],
            {
                "entries": [
                    disclosure_entry("COMMON_SKIN", 8500, 200, False),
                    disclosure_entry("RARE_SKIN", 1400, 1500, True),
                    disclosure_entry("MYTHIC_SKIN", 100, 9000, True),
                ]
            },
            DESIGNER,
        )
    )
    _ok(api_client.publish_disclosure(offer["id"], disclosure["id"], COMPLIANCE))
    _ok(api_client.submit_offer(offer["id"], DESIGNER))
    _ok(
        api_client.review_offer(
            offer["id"], {"decision": "APPROVE", "note": "Table published, value fair"}, COMPLIANCE
        )
    )

    season_v1 = _ok(api_client.get_season(season["id"], LIVEOPS))["version"]
    published = _ok(
        api_client.publish_offer(offer["id"], {"expected_season_version": season_v1}, DESIGNER)
    )

    purchase = _ok(
        api_client.create_purchase(
            {
                "player_id": player["id"],
                "offer_id": offer["id"],
                "expected_offer_version": published["version"],
            },
            make_player_headers(player["id"]),
        )
    )
    _ok(api_client.settle_purchase(purchase["id"], {"outcome": "SETTLED"}, LIVEOPS))

    request = _ok(
        api_client.create_refund_request(
            {"purchase_id": purchase["id"], "reason_code": "ACCIDENTAL"},
            make_player_headers(player["id"]),
        )
    )
    _ok(
        api_client.decide_refund_request(
            request["id"], {"decision": "APPROVE", "decision_note": "Within window"}, COMPLIANCE
        )
    )
    _ok(api_client.execute_refund_request(request["id"], LIVEOPS))
    _ok(
        api_client.set_spend_guard(
            player["id"], {"action": "LOCK", "note": "Post-refund cooling off"}, COMPLIANCE
        )
    )

    assert validate_success(api_client.get_season(season["id"], LIVEOPS))["status"] == "LIVE"
    assert validate_success(api_client.get_episode(episode["id"], LIVEOPS))["status"] == "SCHEDULED"
    assert validate_success(api_client.get_live_event(event["id"], LIVEOPS))["status"] == "APPROVED"

    stored_offer = read_offer(offer["id"])
    assert stored_offer["approval_status"] == "APPROVED"
    assert stored_offer["availability_status"] == "LIVE"

    assert validate_success(api_client.get_purchase(purchase["id"], LIVEOPS))["status"] == "REFUNDED"
    stored_request = validate_success(api_client.get_refund_request(request["id"], LIVEOPS))
    assert stored_request["status"] == "EXECUTED"
    assert stored_request["refund_amount_minor"] == 300

    assert read_player(player["id"])["spend_state"] == "LOCKED"
    assert validate_success(api_client.get_currency_account(account["id"], LIVEOPS))[
        "status"
    ] == "FROZEN"


def test_cross_role_exclusive_operations_are_rejected():
    """Reaching across the role boundary is refused with ERR_UNAUTHORIZED and changes nothing:
    no offer is authored, no review lands, no season is opened and no spend guard moves.

    PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. Five roles exist, and their names are spelled exactly as follows: `ContentProducer`, `EconomyDesigner`, `LiveOpsCommander`, `ComplianceOfficer`, and `Player`. If either header is absent, or if `X-User-Role` carries a value that is not one of those five, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the acting role does not appear in the authorized-role list for the endpoint being called (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "A `ContentProducer` opens one by supplying a `code` — a human-readable label of between 1 and 16 characters that must be unique across all seasons, a collision being answered with `ERR_SEASON_CODE_DUPLICATE` — together with a marketing `title`, an inclusive window bounded by `starts_at` and `ends_at` where the end must be strictly later than the start, a roadmap target of `planned_episode_count` episodes (at least 1), a full-season `target_xp_total` of at least 1 that serves as the denominator for progression pacing, and a `pass_price_minor` battle-pass reference price of zero or more minor units."
    PRD §3.5: "Review is a `ComplianceOfficer` responsibility."
    PRD §3.5: "The reviewing officer then supplies a `decision` of either `APPROVE` or `REVISE`, plus an optional `note`."
    PRD §3.7: "The system moves a player `UNRESTRICTED → LOCKED` or `COOLDOWN → LOCKED` when a settlement recompute pushes `spend_30d_minor` into the lock band, and a `ComplianceOfficer` can force the same landing at any time by supplying an `action` of `LOCK`, optionally with a `note`."

    Design: Corner/rbac/corner_rbac_cross_role_exclusive_operations_rejected
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_px", region_code="NA")

    offer = validate_success(
        api_client.create_offer(
            {
                "season_id": season["id"],
                "offer_type": "BUNDLE",
                "sku": "XR_PACK",
                "price_tier": "T1",
                "list_price_minor": 900,
                "line_items": [offer_line_item("XR_COINS", 900, 1200, "SOFT_COIN", 1200)],
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-20T00:00:00Z",
            },
            DESIGNER,
        ),
        201,
    )
    validate_success(api_client.submit_offer(offer["id"], DESIGNER))

    producer_authoring = api_client.create_offer(
        {
            "season_id": season["id"],
            "offer_type": "BUNDLE",
            "sku": "CP_PACK",
            "price_tier": "T1",
            "list_price_minor": 900,
            "line_items": [offer_line_item("CP_COINS", 900, 1200, "SOFT_COIN", 1200)],
            "window_start": "2026-08-01T00:00:00Z",
            "window_end": "2026-08-20T00:00:00Z",
        },
        PRODUCER,
    )
    validate_error(producer_authoring, ApiErrorId.ERR_UNAUTHORIZED)

    designer_review = api_client.review_offer(offer["id"], {"decision": "APPROVE"}, DESIGNER)
    validate_error(designer_review, ApiErrorId.ERR_UNAUTHORIZED)

    liveops_review = api_client.review_offer(offer["id"], {"decision": "APPROVE"}, LIVEOPS)
    validate_error(liveops_review, ApiErrorId.ERR_UNAUTHORIZED)

    compliance_season = api_client.create_season(
        {
            "code": "S9",
            "title": "Compliance Season",
            "starts_at": "2026-11-01T00:00:00Z",
            "ends_at": "2027-01-30T00:00:00Z",
            "planned_episode_count": 6,
            "target_xp_total": 9000,
            "pass_price_minor": 1000,
        },
        COMPLIANCE,
    )
    validate_error(compliance_season, ApiErrorId.ERR_UNAUTHORIZED)

    player_guard = api_client.set_spend_guard(
        player["id"], {"action": "LOCK", "note": "Self service"}, make_player_headers(player["id"])
    )
    validate_error(player_guard, ApiErrorId.ERR_UNAUTHORIZED)

    _, meta = validate_paginated(
        api_client.list_offers(DESIGNER, params={"season_id": season["id"]})
    )
    assert meta["total_count"] == 1
    assert read_offer(offer["id"])["approval_status"] == "IN_REVIEW"
    assert read_player(player["id"])["spend_state"] == "UNRESTRICTED"


def test_player_is_scoped_to_its_own_resources():
    """Player calls are scoped by X-User-ID: pacing, account listing and purchasing against
    another player are refused, while the identical calls against its own id succeed.

    PRD §2.1: "The fifth role is different. When `X-User-Role` is `Player`, `X-User-ID` is the `id` of the acting `Player` entity, and ownership checks on any resource that references a player compare the resource's player foreign-key field to `X-User-ID`. Concretely: creating a purchase requires that the submitted `player_id` equal `X-User-ID`; requesting a refund requires that the target purchase's `player_id` equal `X-User-ID`; reading a player record, that player's currency accounts, or that player's pacing figures requires that the `player_id` in the path equal `X-User-ID`; reading a single purchase requires that its `player_id` equal `X-User-ID`; reading a single refund request requires that the purchase behind it belong to `X-User-ID`; and requesting a personalized quote requires that the `player_id` supplied with the quote equal `X-User-ID`. Any of those eight operations attempted by a `Player` against somebody else's resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Operator roles are not subject to this check."
    PRD §3.4: "The **realized** reading is attainment against that schedule to date. When the expected-to-date figure is 0 — which is the case on the season's opening day — the realized pacing is exactly 10000 basis points."
    PRD §3.4: "It answers with the `player_id`, the `variant` evaluated, the `elapsed_days` and `season_total_days` it derived, the `expected_to_date_xp` denominator, the `eligible_scheduled_xp` it summed (relevant to the projected reading), the player's current `season_xp_total`, the resulting `pacing_bp`, and the `retention_band` that figure maps to."
    PRD §3.6: "The offer's `pending_purchase_count` rises by 1 and its `version` moves by 1; the season's `pending_revenue_minor` and the player's `pending_spend_minor` each rise by the quoted price."
    PRD §2.5: "The purchase list accepts `player_id`, `offer_id`, and `status`."

    Design: Corner/rbac/corner_rbac_player_scoped_to_own_resources
    """
    season = create_live_season()
    po1 = create_player(season["id"], handle="tide_po1", region_code="NA")
    open_account(po1["id"], "HARD_GEM")
    po2 = create_player(season["id"], handle="tide_po2", region_code="NA")
    open_account(po2["id"], "HARD_GEM")

    offer = create_approved_offer(
        season["id"],
        offer_type="LIMITED_TIME",
        sku="OWN_PACK",
        price_tier="T1",
        list_price_minor=300,
        line_items=[offer_line_item("OWN_COINS", 300, 400, "HARD_GEM", 300)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    published = publish_offer(offer["id"], season["id"])
    offer_v1 = published["version"]

    po1_headers = make_player_headers(po1["id"])

    other_pacing = api_client.get_pacing(po2["id"], po1_headers, params={"variant": "REALIZED"})
    validate_error(other_pacing, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    other_accounts = api_client.list_currency_accounts(
        po2["id"], po1_headers, params={"limit": 10, "offset": 0}
    )
    validate_error(other_accounts, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    other_purchase = api_client.create_purchase(
        {"player_id": po2["id"], "offer_id": offer["id"], "expected_offer_version": offer_v1},
        po1_headers,
    )
    validate_error(other_purchase, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    own_pacing = validate_success(
        api_client.get_pacing(po1["id"], po1_headers, params={"variant": "REALIZED"})
    )
    assert own_pacing["pacing_bp"] == 10000

    own_purchase = validate_success(
        api_client.create_purchase(
            {"player_id": po1["id"], "offer_id": offer["id"], "expected_offer_version": offer_v1},
            po1_headers,
        ),
        201,
    )
    assert own_purchase["player_id"] == po1["id"]

    _, meta = validate_paginated(
        api_client.list_purchases(LIVEOPS, params={"player_id": po2["id"]})
    )
    assert meta["total_count"] == 0
    assert read_player(po2["id"])["pending_spend_minor"] == 0


def test_offer_author_cannot_review_their_own_offer():
    """Offer review is blocked by acting identity rather than role: the authoring user acting as
    a compliance officer is refused, and an independent officer then approves the same offer.

    PRD §2.10: "Two governance decisions may not be taken by the person whose work they govern, and the check is on `X-User-ID`, not on role. Reviewing an offer requires that the acting `X-User-ID` differ from the offer's `created_by_user_id`. Publishing a community notice requires that the acting `X-User-ID` differ from the `authored_by_user_id` of the tuning change the notice describes. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and those two operations are the only places this check applies."
    PRD §3.5: "Both decisions require the offer to be `IN_REVIEW` and both require the acting `X-User-ID` to differ from the offer's `created_by_user_id`, the segregation check of §2.10 failing with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."
    PRD §3.5: "Approving carries the offer `IN_REVIEW → APPROVED`, records the reviewer as `reviewed_by_user_id`, and moves the offer's `version` by 1."

    Design: Corner/rbac/corner_rbac_sod_offer_author_cannot_review_own_offer
    """
    season = create_live_season()
    author_id = OPERATOR_IDS["EconomyDesigner"]

    offer = validate_success(
        api_client.create_offer(
            {
                "season_id": season["id"],
                "offer_type": "BUNDLE",
                "sku": "SOD_PACK",
                "price_tier": "T1",
                "list_price_minor": 900,
                "line_items": [offer_line_item("SOD_COINS", 900, 1200, "SOFT_COIN", 1200)],
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-20T00:00:00Z",
            },
            DESIGNER,
        ),
        201,
    )
    validate_success(api_client.submit_offer(offer["id"], DESIGNER))

    self_review = api_client.review_offer(
        offer["id"],
        {"decision": "APPROVE", "note": "Self approval attempt"},
        make_headers(author_id, "ComplianceOfficer"),
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    blocked_state = read_offer(offer["id"])
    assert blocked_state["created_by_user_id"] == author_id
    assert blocked_state["approval_status"] == "IN_REVIEW"

    independent = validate_success(
        api_client.review_offer(
            offer["id"], {"decision": "APPROVE", "note": "Independent review"}, COMPLIANCE
        )
    )
    assert independent["approval_status"] == "APPROVED"
    assert read_offer(offer["id"])["approval_status"] == "APPROVED"


def test_tuning_change_author_cannot_publish_their_own_notice():
    """The community notice for a tuning change cannot be published by the change's author, even
    with an authorized role, while a different operator publishes it unchanged.

    PRD §2.10: "Two governance decisions may not be taken by the person whose work they govern, and the check is on `X-User-ID`, not on role. Reviewing an offer requires that the acting `X-User-ID` differ from the offer's `created_by_user_id`. Publishing a community notice requires that the acting `X-User-ID` differ from the `authored_by_user_id` of the tuning change the notice describes. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and those two operations are the only places this check applies."
    PRD §3.8: "Publishing carries the notice `DRAFT → PUBLISHED` and may be performed by a `ComplianceOfficer` or a `LiveOpsCommander`. It requires the notice to still be `DRAFT` and the owning change to be in one of the stages `DRAFT`, `SHADOW`, `CANARY`, or `LIVE` — a notice against a change that has already reverted or retired is refused with `ERR_COMMS_NOTICE_INVALID_STATE`, the same code used for a notice that is already published — and it requires the acting `X-User-ID` to differ from the change's `authored_by_user_id`, that segregation failure being `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "The change is stored in `DRAFT` with the authoring operator recorded as `authored_by_user_id`, `promoted_by_user_id` and `pre_live_sink_rate_bp` null, and `comms_state` at `MISSING`."

    Design: Corner/rbac/corner_rbac_sod_change_author_cannot_publish_own_notice
    """
    season = create_live_season()
    author_id = OPERATOR_IDS["EconomyDesigner"]

    change = create_draft_balance_change(
        season["id"], target_kind="SINK_RATE", delta_bp=500, rationale="Crafting sink up"
    )
    notice = draft_comms_notice(
        change["id"],
        channel="PATCH_NOTES",
        headline="Crafting costs rise 5 percent",
        body="Sink rate moves from 10000 to 10500 basis points next week.",
    )

    author_publish = api_client.publish_comms_notice(
        change["id"], notice["id"], make_headers(author_id, "LiveOpsCommander")
    )
    validate_error(author_publish, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    assert read_balance_change(change["id"])["authored_by_user_id"] == author_id
    blocked_notices, _ = validate_paginated(api_client.list_comms_notices(change["id"], LIVEOPS))
    assert blocked_notices[0]["status"] == "DRAFT"

    published = validate_success(
        api_client.publish_comms_notice(change["id"], notice["id"], LIVEOPS)
    )
    assert published["status"] == "PUBLISHED"

    final_notices, _ = validate_paginated(api_client.list_comms_notices(change["id"], LIVEOPS))
    assert final_notices[0]["status"] == "PUBLISHED"
    assert read_balance_change(change["id"])["stage"] == "DRAFT"
