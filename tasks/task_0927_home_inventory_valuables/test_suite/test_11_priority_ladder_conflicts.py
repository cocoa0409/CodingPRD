"""Two requests that violate several rules at once, and the single rung the
ladder says must answer."""
from test_helpers import (
    ApiErrorId,
    add_appraiser,
    add_cataloged_item,
    add_generated_package,
    add_policy,
    add_room,
    bootstrap_household,
    drive_subscription_to_lapsed,
    open_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

GENERAL_SCHEDULE = {
    "category": "GENERAL",
    "useful_life_months": 120,
    "annual_depreciation_pct": 8.0,
    "salvage_floor_pct": 20.0,
    "blanket_sublimit_cents": 900000,
    "appraisal_scope": "GENERAL",
    "serial_required": False,
}

JEWELRY_SCHEDULE = {
    "category": "JEWELRY",
    "useful_life_months": 240,
    "annual_depreciation_pct": 4.0,
    "salvage_floor_pct": 40.0,
    "blanket_sublimit_cents": 300000,
    "appraisal_scope": "JEWELRY",
    "serial_required": False,
}


def _setup_frozen_item_under_an_open_claim():
    """One CATALOGED item in room R, a GENERATED package and an OPEN claim whose
    affected rooms are exactly [R], so the item sits in FROZEN."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Room R", floor_label="1")
    item = add_cataloged_item(
        ctx,
        room["id"],
        200000,
        photo_bytes=40000,
        name="Studio Lamp",
        category="GENERAL",
        acquired_at="2025-05-01T00:00:00Z",
        quantity=1,
        serial_number="GN-L1",
    )
    policy = add_policy(
        ctx, policy_number="NW-8008", deductible_cents=50000, scheduled_allowance_cents=0
    )
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="STORM",
        settlement_basis="ACV",
        deductible_mode="PRO_RATA",
    )
    ctx.update({"room": room, "item": item, "policy": policy, "package": package, "claim": claim})
    return ctx


def test_item_patch_on_a_frozen_item_reports_the_records_freeze(api):
    """PRD 2.8 rung 12: "**`ERR_ITEM_FROZEN` (409)** — the records freeze of §2.7:
    the target item, or the item behind the target appraisal or allocation, has
    `lifecycle_state` `FROZEN`. Applies to `PATCH /vault/items/{item_id}`, `DELETE
    /vault/assets/{asset_id}`, `POST /vault/items/{item_id}/assets`, `POST
    /vault/items/{item_id}/declare-value`, `POST /vault/items/{item_id}/schedule`,
    `POST /vault/items/{item_id}/unschedule`, `POST /vault/items/{item_id}/replace`,
    `POST /vault/appraisals` and `POST /vault/appraisals/{appraisal_id}/certify`."
    PRD 3.7: "Every item of the household whose `lifecycle_state` is `CATALOGED`
    **and** whose `room_id` appears in `affected_room_ids` moves `CATALOGED →
    FROZEN` with `frozen_by_claim_id` set to the new claim's id"

    Design: Difficulty/priority_pair_validation_conflict/read_only_write_gate_preempts_records_freeze_on_item_patch
    """
    ctx = _setup_frozen_item_under_an_open_claim()

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["write_gate_state"] == "OPEN", (
        "the read-only gate must be shut for this leg so only rung 12 can fire"
    )

    response = api.patch_item(
        ctx["item"]["id"], {"name": "Renamed While Frozen"}, ctx["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_ITEM_FROZEN.value, 409)

    item = validate_success(api.get_item(ctx["item"]["id"], ctx["owner_headers"]))
    assert item["name"] == "Studio Lamp"
    assert item["lifecycle_state"] == "FROZEN"


def test_read_only_vault_preempts_the_records_freeze_on_the_same_patch(api):
    """PRD 2.7: "Rung 10 pre-empts rungs 11 through 38 for the endpoints it
    governs."
    PRD 2.8 rung 10: "**`ERR_VAULT_READ_ONLY` (403)** — the global write gate of
    §2.7: the household is `READ_ONLY` and the endpoint is a mutating `/vault`
    endpoint that is not on the exclusion list."
    PRD 2.8: "The three posture rungs — 10, 11 and 12 — sit deliberately **above**
    the two ordinary state rungs 13 and 14."

    Design: Difficulty/priority_pair_validation_conflict/read_only_write_gate_preempts_records_freeze_on_item_patch
    """
    ctx = _setup_frozen_item_under_an_open_claim()
    drive_subscription_to_lapsed(ctx, "2026-05-12T00:00:00Z")

    response = api.patch_item(
        ctx["item"]["id"], {"name": "Renamed While Read Only"}, ctx["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_VAULT_READ_ONLY.value, 403)

    item = validate_success(api.get_item(ctx["item"]["id"], ctx["owner_headers"]))
    assert item["name"] == "Studio Lamp"
    assert item["lifecycle_state"] == "FROZEN", (
        "both violations are live; the lower-numbered rung is the one reported"
    )

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["write_gate_state"] == "READ_ONLY"


def _setup_basic_household_with_two_appraisers():
    """A BASIC household — zero included appraisal credits — with one CATALOGED
    JEWELRY item, an out-of-scope appraiser and an in-scope one."""
    ctx = bootstrap_household(tier="BASIC", activate=True, categories=[JEWELRY_SCHEDULE])
    room = add_room(ctx, name="Safe Room", floor_label="0")
    item = add_cataloged_item(
        ctx,
        room["id"],
        200000,
        photo_bytes=30000,
        name="Ruby Pendant",
        category="JEWELRY",
        acquired_at="2024-03-01T00:00:00Z",
        quantity=1,
        serial_number="JW-RP1",
    )
    appraiser_out_of_scope = add_appraiser(
        display_name="Xavier Art",
        credential_id="CRED-FA-9",
        scope_categories=["FINE_ART"],
    )
    appraiser_in_scope = add_appraiser(
        display_name="Yolanda Gem",
        credential_id="CRED-JW-9",
        scope_categories=["JEWELRY"],
    )
    ctx.update(
        {
            "room": room,
            "item": item,
            "appraiser_out_of_scope": appraiser_out_of_scope,
            "appraiser_in_scope": appraiser_in_scope,
        }
    )
    return ctx


def test_appraiser_scope_mismatch_wins_over_the_exhausted_credit_balance(api):
    """PRD 3.4: "The appraiser's `scope_categories` must contain the
    `appraisal_scope` of the category schedule governing the item's `category`, or
    the request fails with `ERR_APPRAISER_SCOPE_MISMATCH`."
    PRD 2.8 rung 15: "**`ERR_APPRAISER_SCOPE_MISMATCH` (422)** — the appraiser's
    `scope_categories` array does not contain the `appraisal_scope` of the
    `CategorySchedule` governing the target item's `category`. Applies to appraisal
    requests."

    Design: Difficulty/priority_pair_validation_conflict/appraiser_scope_mismatch_preempts_exhausted_appraisal_credits
    """
    ctx = _setup_basic_household_with_two_appraisers()

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["appraisal_credits_remaining"] == 0, (
        "BASIC includes zero credits, so both rules are violated by this request"
    )

    response = api.create_appraisal(
        {
            "item_id": ctx["item"]["id"],
            "appraiser_id": ctx["appraiser_out_of_scope"]["id"],
            "inspection_start_at": "2026-06-10T09:00:00Z",
            "inspection_end_at": "2026-06-10T17:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_APPRAISER_SCOPE_MISMATCH.value, 422)


def test_in_scope_request_falls_through_to_the_credit_check(api):
    """PRD 3.4: "Finally the subscription must have at least one credit:
    `appraisal_credits_remaining` is decremented by one and the appraisal's
    `credit_consumed` is set true, or, when the balance is already zero, the
    request fails with `ERR_NO_APPRAISAL_CREDITS`. A `BASIC` household has zero
    included credits, so its very first appraisal request is refused."
    PRD 2.8 rung 34: "**`ERR_NO_APPRAISAL_CREDITS` (402)** — the subscription's
    `appraisal_credits_remaining` is zero. Applies to appraisal requests."

    Design: Difficulty/priority_pair_validation_conflict/appraiser_scope_mismatch_preempts_exhausted_appraisal_credits
    """
    ctx = _setup_basic_household_with_two_appraisers()

    response = api.create_appraisal(
        {
            "item_id": ctx["item"]["id"],
            "appraiser_id": ctx["appraiser_in_scope"]["id"],
            "inspection_start_at": "2026-06-10T09:00:00Z",
            "inspection_end_at": "2026-06-10T17:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_NO_APPRAISAL_CREDITS.value, 402)

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["appraisal_credits_remaining"] == 0

    rows, meta = validate_paginated(
        api.list_appraisals(ctx["owner_headers"], params={"item_id": ctx["item"]["id"]})
    )
    assert rows == [], "neither refused request may leave an Appraisal row behind"
    assert meta["total_count"] == 0
