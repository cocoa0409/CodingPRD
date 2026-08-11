"""Two multi-hop cascades: voiding a certified appraisal all the way down to a
claim line's settlement hold, and a billing lapse voiding only the
full-redaction share links."""
from test_helpers import (
    add_appraiser,
    add_cataloged_item,
    add_claim_line,
    add_generated_package,
    add_policy,
    add_room,
    add_share_grant,
    billing_event,
    bootstrap_household,
    certify_appraisal,
    open_claim,
    request_appraisal,
    schedule_item,
    set_clock,
    validate_success,
    void_appraisal,
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


def _setup_certified_appraisal_under_a_packaged_claim():
    """A JEWELRY item certified at 900000 and individually scheduled, a GENERATED
    package built on that policy, and a PENDING claim line on the item under a
    claim whose affected rooms deliberately exclude the item's room."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[JEWELRY_SCHEDULE])
    room_a = add_room(ctx, name="Room A", floor_label="1")
    room_b = add_room(ctx, name="Room B", floor_label="1")
    appraiser = add_appraiser(
        display_name="Iris Vale", credential_id="CRED-JW-1", scope_categories=["JEWELRY"]
    )
    item = add_cataloged_item(
        ctx,
        room_a["id"],
        600000,
        photo_bytes=50000,
        name="Emerald Brooch",
        category="JEWELRY",
        acquired_at="2024-01-01T00:00:00Z",
        quantity=1,
        serial_number="JW-9",
    )
    appraisal = request_appraisal(
        ctx,
        item["id"],
        appraiser["id"],
        inspection_start_at="2026-05-10T09:00:00Z",
        inspection_end_at="2026-05-10T17:00:00Z",
    )
    set_clock("2026-05-11T00:00:00Z")
    certify_appraisal(appraisal["id"], appraiser["id"], 900000)

    policy = add_policy(
        ctx,
        policy_number="NW-7007",
        deductible_cents=100000,
        scheduled_allowance_cents=1000000,
    )
    schedule_item(ctx, item["id"], policy["id"], 900000)
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room_b["id"]],
        loss_date="2026-05-11T00:00:00Z",
        peril="THEFT",
        settlement_basis="ACV",
        deductible_mode="PRO_RATA",
    )
    line = add_claim_line(ctx, claim["id"], item["id"])
    ctx.update(
        {
            "room_a": room_a,
            "room_b": room_b,
            "appraiser": appraiser,
            "item": item,
            "appraisal": appraisal,
            "policy": policy,
            "package": package,
            "claim": claim,
            "line": line,
        }
    )
    return ctx


def test_voiding_a_certified_appraisal_restrips_the_item_and_the_policy_totals(api):
    """PRD 3.4: "Hop 2, caused by hop 1, strips the appraisal basis from the item:
    `effective_value_cents`, `effective_value_basis` and `valuation_state` are all
    recomputed by the ordinary precedence, so the item falls back to `ACV`, to
    `DECLARED`, or to `APPRAISAL_REQUIRED` when its declared value is at or above
    the threshold."
    PRD 3.4: "Hop 3, caused by hop 2, recomputes `total_effective_value_cents` and
    `coverage_gap_cents` on every policy of the item's household — this hop does
    **not** require the item to have been scheduled."

    Design: Difficulty/transitive_cascade/void_certified_appraisal_cascades_five_hops_to_claim_line_hold
    """
    ctx = _setup_certified_appraisal_under_a_packaged_claim()

    voided = void_appraisal(ctx["appraisal"]["id"], "VALUE_DISPUTED")
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "VALUE_DISPUTED"

    item = validate_success(api.get_item(ctx["item"]["id"], ctx["owner_headers"]))
    assert item["effective_value_basis"] == "DECLARED", (
        "with no purchase price the ACV regime is unavailable, so the fallback is "
        f"DECLARED; got {item['effective_value_basis']}"
    )
    assert item["effective_value_cents"] == 600000
    assert item["valuation_state"] == "DECLARED_ONLY"

    policy = validate_success(api.get_policy(ctx["policy"]["id"], ctx["owner_headers"]))
    assert policy["total_effective_value_cents"] == 600000
    assert policy["scheduled_consumed_cents"] == 900000, (
        "a valuation change never disturbs the scheduling ledger"
    )


def test_voiding_a_certified_appraisal_expires_the_package_and_holds_the_claim_line(api):
    """PRD 3.4: "Hop 4, caused by hop 3, moves every documentation package with one
    of those policy ids whose `status` is `GENERATED` to `EXPIRED`,
    **unconditionally**: the trigger is that hop 3 executed at all, not whether the
    recomputed `coverage_gap_cents` actually changed"
    PRD 3.4: "In the same hop, every package line — in any package, whatever its
    status — that references the affected item has its `stale` flag set to true,
    and the owning package's `stale_line_count` is recomputed."
    PRD 3.4: "Hop 5, caused by hop 4, sets `settlement_hold` to true on every claim
    line still in `PENDING` whose claim's `package_id` is one of the packages hop 4
    just expired, and recomputes `blocked_line_count` on each of those claims."

    Design: Difficulty/transitive_cascade/void_certified_appraisal_cascades_five_hops_to_claim_line_hold
    """
    ctx = _setup_certified_appraisal_under_a_packaged_claim()

    void_appraisal(ctx["appraisal"]["id"], "VALUE_DISPUTED")

    package = validate_success(api.get_package(ctx["package"]["id"], ctx["owner_headers"]))
    assert package["status"] == "EXPIRED"
    assert package["stale_line_count"] == 1
    assert package["snapshot_total_effective_cents"] == 900000, (
        "the frozen snapshot is never recomputed, even as the item moves under it"
    )

    line = validate_success(api.get_claim_line(ctx["line"]["id"], ctx["owner_headers"]))
    assert line["settlement_hold"] is True

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ctx["owner_headers"]))
    assert claim["blocked_line_count"] == 1
    assert claim["status"] == "OPEN"


def _setup_lapsing_household_with_two_share_grants():
    """A PLUS household holding one FULL and one SERIALS_HIDDEN share grant, with
    its subscription parked in PAST_DUE past the 10-day grace."""
    ctx = bootstrap_household(tier="PLUS", activate=True)
    grant_full = add_share_grant(
        ctx,
        scope_kind="HOUSEHOLD",
        recipient_ref="agent1@carrier.example",
        redaction_level="FULL",
        starts_at="2026-05-01T00:00:00Z",
        expires_at="2026-07-01T00:00:00Z",
        access_cap=10,
    )
    grant_partial = add_share_grant(
        ctx,
        scope_kind="HOUSEHOLD",
        recipient_ref="agent2@carrier.example",
        redaction_level="SERIALS_HIDDEN",
        starts_at="2026-05-01T00:00:00Z",
        expires_at="2026-07-01T00:00:00Z",
        access_cap=10,
    )
    billing_event(ctx, "PAYMENT_FAILED")
    set_clock("2026-05-12T00:00:00Z")
    ctx.update({"grant_full": grant_full, "grant_partial": grant_partial})
    return ctx


def test_lapse_flips_the_subscription_and_closes_the_global_write_gate(api):
    """PRD 3.2: "From `PAST_DUE`, a `LAPSE` outcome moves `PAST_DUE → LAPSED`, but
    only once the clock has reached or passed `past_due_since_at` plus the 10-day
    past-due grace. This is a four-hop cascade. Hop 1 sets `status` to `LAPSED`.
    Hop 2, caused by hop 1, sets the household's `write_gate_state` to `READ_ONLY`
    — the global write gate."

    Design: Difficulty/transitive_cascade/subscription_lapse_cascades_four_hops_voiding_full_redaction_shares
    """
    ctx = _setup_lapsing_household_with_two_share_grants()

    lapsed = billing_event(ctx, "LAPSE")
    assert lapsed["status"] == "LAPSED"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["write_gate_state"] == "READ_ONLY"


def test_lapse_voids_only_the_full_redaction_share_grant(api):
    """PRD 3.2: "Hop 3, caused by hop 2, moves every share grant on that household
    with `status` `ACTIVE` and `redaction_level` `FULL` to `VOIDED_BY_SCOPE` with
    `voided_reason` `SUBSCRIPTION_LAPSED`; grants at the two partial redaction
    levels do not fire this hop. Hop 4, caused by hop 3, recomputes
    `active_share_count` as the count of grants still `ACTIVE`."

    Design: Difficulty/transitive_cascade/subscription_lapse_cascades_four_hops_voiding_full_redaction_shares
    """
    ctx = _setup_lapsing_household_with_two_share_grants()

    billing_event(ctx, "LAPSE")

    full_grant = validate_success(
        api.get_share_grant(ctx["grant_full"]["id"], ctx["owner_headers"])
    )
    assert full_grant["status"] == "VOIDED_BY_SCOPE"
    assert full_grant["voided_reason"] == "SUBSCRIPTION_LAPSED"

    partial_grant = validate_success(
        api.get_share_grant(ctx["grant_partial"]["id"], ctx["owner_headers"])
    )
    assert partial_grant["status"] == "ACTIVE", (
        "a SERIALS_HIDDEN grant must survive the lapse cascade untouched"
    )

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["active_share_count"] == 1
