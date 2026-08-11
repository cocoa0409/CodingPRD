"""Two interval rules with deliberately opposite semantics: the appraisal hold
is a closed interval widened by 24 hours on both sides, while the share window
is half-open with no buffer at all."""
from test_helpers import (
    ApiErrorId,
    add_appraiser,
    add_cataloged_item,
    add_room,
    add_share_grant,
    bootstrap_household,
    request_appraisal,
    validate_error,
    validate_paginated,
    validate_success,
)

JEWELRY_SCHEDULE = {
    "category": "JEWELRY",
    "useful_life_months": 240,
    "annual_depreciation_pct": 4.0,
    "salvage_floor_pct": 40.0,
    "blanket_sublimit_cents": 300000,
    "appraisal_scope": "JEWELRY",
    "serial_required": False,
}


def _setup_item_with_one_requested_appraisal():
    """A PLUS household (two included credits) whose only JEWELRY item already
    carries a REQUESTED appraisal occupying 2026-06-10 09:00 to 17:00."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[JEWELRY_SCHEDULE])
    room = add_room(ctx, name="Closet", floor_label="2")
    appraiser = add_appraiser(
        display_name="Otto Gem", credential_id="CRED-JW-3", scope_categories=["JEWELRY"]
    )
    item = add_cataloged_item(
        ctx,
        room["id"],
        200000,
        photo_bytes=18000,
        name="Opal Bracelet",
        category="JEWELRY",
        acquired_at="2024-04-01T00:00:00Z",
        quantity=1,
        serial_number="JW-T1",
    )
    first = request_appraisal(
        ctx,
        item["id"],
        appraiser["id"],
        inspection_start_at="2026-06-10T09:00:00Z",
        inspection_end_at="2026-06-10T17:00:00Z",
    )
    ctx.update({"room": room, "appraiser": appraiser, "item": item, "first": first})
    return ctx


def test_appraisal_window_inside_the_24_hour_buffer_collides(api):
    """PRD 3.4: "The requested inspection window must not collide with an existing
    hold: taking the new window as a **closed** interval from `inspection_start_at`
    to `inspection_end_at` and widening it by 24 hours on **both** sides, it must
    not intersect the un-widened closed interval of any other appraisal on the same
    item whose `status` is `REQUESTED` or `CERTIFIED`; touching endpoints count as
    intersecting, and a collision fails with `ERR_APPRAISAL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/appraisal_inspection_hold_uses_closed_interval_with_symmetric_24h_buffer
    """
    ctx = _setup_item_with_one_requested_appraisal()

    response = api.create_appraisal(
        {
            "item_id": ctx["item"]["id"],
            "appraiser_id": ctx["appraiser"]["id"],
            "inspection_start_at": "2026-06-11T09:00:00Z",
            "inspection_end_at": "2026-06-11T17:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_APPRAISAL_WINDOW_CONFLICT.value, 409)

    first = validate_success(api.get_appraisal(ctx["first"]["id"], ctx["owner_headers"]))
    assert first["status"] == "REQUESTED"

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["appraisal_credits_remaining"] == 1, (
        "the window check sits above the credit check, so no credit is spent"
    )


def test_appraisal_window_clear_of_the_24_hour_buffer_is_accepted(api):
    """PRD 3.4: "The requested inspection window must not collide with an existing
    hold: taking the new window as a **closed** interval from `inspection_start_at`
    to `inspection_end_at` and widening it by 24 hours on **both** sides, it must
    not intersect the un-widened closed interval of any other appraisal on the same
    item whose `status` is `REQUESTED` or `CERTIFIED`; touching endpoints count as
    intersecting, and a collision fails with `ERR_APPRAISAL_WINDOW_CONFLICT`."
    PRD 3.4: "Finally the subscription must have at least one credit:
    `appraisal_credits_remaining` is decremented by one and the appraisal's
    `credit_consumed` is set true"

    Design: Difficulty/resource_temporal_overlap/appraisal_inspection_hold_uses_closed_interval_with_symmetric_24h_buffer
    """
    ctx = _setup_item_with_one_requested_appraisal()

    response = api.create_appraisal(
        {
            "item_id": ctx["item"]["id"],
            "appraiser_id": ctx["appraiser"]["id"],
            "inspection_start_at": "2026-06-12T09:00:00Z",
            "inspection_end_at": "2026-06-12T17:00:00Z",
        },
        ctx["owner_headers"],
    )
    third = validate_success(response, 201)
    assert third["status"] == "REQUESTED"

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["appraisal_credits_remaining"] == 0

    rows, meta = validate_paginated(
        api.list_appraisals(ctx["owner_headers"], params={"item_id": ctx["item"]["id"]})
    )
    assert meta["total_count"] == 2, (
        f"exactly two appraisals may exist on this item, got {meta['total_count']}"
    )
    assert len(rows) == 2


def _setup_household_with_one_active_share_grant():
    """A PLUS household holding one ACTIVE grant to agent@carrier.example over
    2026-05-01 to 2026-06-01."""
    ctx = bootstrap_household(tier="PLUS", activate=True)
    grant = add_share_grant(
        ctx,
        scope_kind="HOUSEHOLD",
        recipient_ref="agent@carrier.example",
        redaction_level="SERIALS_HIDDEN",
        starts_at="2026-05-01T00:00:00Z",
        expires_at="2026-06-01T00:00:00Z",
        access_cap=10,
    )
    ctx["grant"] = grant
    return ctx


def test_share_window_starting_inside_an_incumbent_grant_collides(api):
    """PRD 3.9: "First, the window must not collide with another live link to the
    same person: a new grant is refused with `ERR_SHARE_WINDOW_OVERLAP` when another
    share grant with `status` `ACTIVE` shares the same `household_id` and
    `recipient_ref` pair and its half-open window intersects the new one's."

    Design: Difficulty/resource_temporal_overlap/share_grant_window_is_half_open_so_exact_adjacency_is_allowed
    """
    ctx = _setup_household_with_one_active_share_grant()

    response = api.create_share_grant(
        {
            "household_id": ctx["household_id"],
            "scope_kind": "HOUSEHOLD",
            "recipient_ref": "agent@carrier.example",
            "redaction_level": "SERIALS_HIDDEN",
            "starts_at": "2026-05-15T00:00:00Z",
            "expires_at": "2026-06-15T00:00:00Z",
            "access_cap": 10,
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_SHARE_WINDOW_OVERLAP.value, 409)

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["active_share_count"] == 1


def test_share_window_exactly_adjacent_to_an_incumbent_grant_is_allowed(api):
    """PRD 3.9: "Because both windows are half-open, exact adjacency — a new
    `starts_at` equal to an existing `expires_at` — does not intersect and is
    allowed. There is no buffer of any kind on this check, in deliberate contrast
    with the appraisal hold of §3.4, which is a closed interval widened by 24 hours
    on both sides."
    PRD 3.9: "On success the server mints an opaque `share_token`, the grant opens
    in `status` `ACTIVE` with `access_count` 0 and `voided_reason` null, and the
    household's `active_share_count` rises."

    Design: Difficulty/resource_temporal_overlap/share_grant_window_is_half_open_so_exact_adjacency_is_allowed
    """
    ctx = _setup_household_with_one_active_share_grant()

    response = api.create_share_grant(
        {
            "household_id": ctx["household_id"],
            "scope_kind": "HOUSEHOLD",
            "recipient_ref": "agent@carrier.example",
            "redaction_level": "SERIALS_HIDDEN",
            "starts_at": "2026-06-01T00:00:00Z",
            "expires_at": "2026-07-01T00:00:00Z",
            "access_cap": 10,
        },
        ctx["owner_headers"],
    )
    adjacent = validate_success(response, 201)
    assert adjacent["status"] == "ACTIVE"
    assert adjacent["access_count"] == 0

    incumbent = validate_success(
        api.get_share_grant(ctx["grant"]["id"], ctx["owner_headers"])
    )
    assert incumbent["status"] == "ACTIVE"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["active_share_count"] == 2
