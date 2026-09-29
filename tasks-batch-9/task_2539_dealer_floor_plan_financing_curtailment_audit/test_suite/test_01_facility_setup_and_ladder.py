"""Facility establishment: the activation join and the curtailment ladder geometry."""
from test_helpers import (
    ApiErrorId,
    activate_credit_line,
    add_tier,
    api_client,
    assert_credit_line,
    assert_curtailment_tier,
    assert_inventory_unit,
    assert_utc_millisecond_timestamp,
    create_curtailment_tier_payload,
    create_unit_payload,
    make_vin,
    read_dealer,
    setup_active_line,
    setup_pending_line,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    CO,
)

NEW_90_180 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": 180,
    "cumulative_paydown_bps": 1000,
}


def test_registration_is_refused_while_the_governing_line_is_still_pending():
    """A unit cannot be recorded against a facility that has not been switched on yet.

    PRD: "Registration also requires the governing line to be `ACTIVE` (`ERR_CREDIT_LINE_NOT_ACTIVE`) and the dealership to be `ACTIVE` (`ERR_DEALER_NOT_ACTIVE`) — a `PROSPECT` dealership cannot floor inventory, and neither can a suspended, defaulted or terminated one."

    Design: Difficulty/cross_entity_state_dependency/unit_registration_blocked_until_the_governing_credit_line_is_activated
    """
    ctx = setup_pending_line(tiers=[NEW_90_180])
    dealer = ctx["dealer"]
    line = ctx["credit_line"]
    assert line["status"] == "PENDING"
    assert dealer["status"] == "PROSPECT"

    payload = create_unit_payload(dealer["id"], line["id"], make_vin("PENDLINEUNIT0001"))
    response = api_client.create_unit(payload, ctx["dealer_headers"])
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_CREDIT_LINE_NOT_ACTIVE, ApiErrorId.ERR_DEALER_NOT_ACTIVE],
    )

    listed = api_client.list_units(ctx["dealer_headers"], params={"dealer_id": dealer["id"]})
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 0
    assert rows == []


def test_activation_unblocks_registration_and_stamps_the_first_audit_due_date():
    """Activating the line moves the dealership to ACTIVE and lets the same payload through.

    PRD: "Activation stamps `activated_at` from the logical clock, recomputes the capacity figures of §2.11, advances the line `PENDING → ACTIVE`, and cascades: the dealership moves `PROSPECT → ACTIVE` and its `next_audit_due_at` is set to `activated_at` plus its current `audit_frequency_days` — 180 days out for a brand-new `A`-rated dealer."

    Design: Difficulty/cross_entity_state_dependency/unit_registration_blocked_until_the_governing_credit_line_is_activated
    """
    ctx = setup_pending_line(tiers=[NEW_90_180])
    dealer = ctx["dealer"]
    line = ctx["credit_line"]

    activated = activate_credit_line(line["id"])
    assert activated["status"] == "ACTIVE"
    assert_utc_millisecond_timestamp(activated["activated_at"], "activated_at")
    assert str(activated["activated_at"]).startswith("2026-08-01T00:00:00")
    assert_credit_line(activated)

    dealer_after = read_dealer(dealer["id"])
    assert dealer_after["status"] == "ACTIVE"
    assert dealer_after["risk_rating"] == "A"
    assert dealer_after["audit_frequency_days"] == 180
    assert_utc_millisecond_timestamp(dealer_after["next_audit_due_at"], "next_audit_due_at")
    assert str(dealer_after["next_audit_due_at"]).startswith("2027-01-28T00:00:00")

    payload = create_unit_payload(dealer["id"], line["id"], make_vin("PENDLINEUNIT0001"))
    unit = validate_success(
        api_client.create_unit(payload, ctx["dealer_headers"]), expected_status=201
    )
    assert_inventory_unit(unit)
    assert unit["funding_status"] == "REGISTERED"
    assert unit["title_custody_status"] == "NOT_RECEIVED"
    assert unit["eligibility_status"] == "ELIGIBLE"
    assert unit["version"] == 1


def test_half_open_ladder_rungs_with_touching_endpoints_coexist_on_one_class():
    """Rungs ending and starting on the same day are accepted, and the ladder reads back in age order.

    PRD: "Because the intervals are half-open, touching endpoints do not collide: a rung covering days 90 up to 180 coexists happily with a rung covering days 180 up to 270, while a rung covering days 150 up to 200 intersects both and is refused with `ERR_TIER_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/curtailment_tier_half_open_intervals_allow_touching_endpoints_per_class
    """
    ctx = setup_active_line(tiers=[NEW_90_180])
    line_id = ctx["credit_line"]["id"]

    second = validate_success(
        api_client.create_curtailment_tier(
            line_id,
            create_curtailment_tier_payload("NEW", 180, 270, 2500),
            CO,
        ),
        expected_status=201,
    )
    assert_curtailment_tier(second)
    assert second["age_days_from"] == 180
    assert second["age_days_to"] == 270
    assert second["cumulative_paydown_bps"] == 2500

    third = validate_success(
        api_client.create_curtailment_tier(
            line_id,
            create_curtailment_tier_payload("NEW", 270, None, 5000),
            CO,
        ),
        expected_status=201,
    )
    assert third["age_days_from"] == 270
    assert third["age_days_to"] is None

    rows, meta = validate_paginated(
        api_client.list_curtailment_tiers(line_id, CO, params={"inventory_class": "NEW"})
    )
    assert meta["total_count"] == 3
    assert [row["age_days_from"] for row in rows] == [90, 180, 270]
    assert [row["id"] for row in rows] == [ctx["tiers"][0]["id"], second["id"], third["id"]]


def test_a_straddling_rung_and_a_second_unbounded_rung_are_both_refused():
    """An interval intersecting two existing rungs, and a second open-ended rung, share one refusal.

    PRD: "At most one unbounded rung may exist per line-and-class pair, and a second attempt is refused with the same code."

    Design: Difficulty/resource_temporal_overlap/curtailment_tier_half_open_intervals_allow_touching_endpoints_per_class
    """
    ctx = setup_active_line(tiers=[NEW_90_180])
    line_id = ctx["credit_line"]["id"]
    add_tier(line_id, inventory_class="NEW", age_days_from=180, age_days_to=270,
             cumulative_paydown_bps=2500)
    add_tier(line_id, inventory_class="NEW", age_days_from=270, age_days_to=None,
             cumulative_paydown_bps=5000)

    straddling = api_client.create_curtailment_tier(
        line_id, create_curtailment_tier_payload("NEW", 170, 200, 3000), CO
    )
    validate_error(straddling, ApiErrorId.ERR_TIER_INTERVAL_OVERLAP, 409)

    second_unbounded = api_client.create_curtailment_tier(
        line_id, create_curtailment_tier_payload("NEW", 400, None, 7500), CO
    )
    validate_error(second_unbounded, ApiErrorId.ERR_TIER_INTERVAL_OVERLAP, 409)

    rows, meta = validate_paginated(
        api_client.list_curtailment_tiers(line_id, CO, params={"inventory_class": "NEW"})
    )
    assert meta["total_count"] == 3


def test_the_ladder_is_keyed_on_class_and_rejects_a_non_increasing_interval():
    """The same day span is free under another inventory class, but an inverted span is invalid.

    PRD: "Separately, `age_days_to` must be either null or strictly greater than `age_days_from`, and the ladder must climb: a new rung's `cumulative_paydown_bps` must be strictly greater than the `cumulative_paydown_bps` of every existing rung of the same line and class whose `age_days_from` is smaller."

    Design: Difficulty/resource_temporal_overlap/curtailment_tier_half_open_intervals_allow_touching_endpoints_per_class
    """
    ctx = setup_active_line(tiers=[NEW_90_180])
    line_id = ctx["credit_line"]["id"]

    used_rung = validate_success(
        api_client.create_curtailment_tier(
            line_id, create_curtailment_tier_payload("USED", 90, 180, 1500), CO
        ),
        expected_status=201,
    )
    assert used_rung["inventory_class"] == "USED"
    assert used_rung["age_days_from"] == 90
    assert used_rung["age_days_to"] == 180

    inverted = api_client.create_curtailment_tier(
        line_id, create_curtailment_tier_payload("USED", 200, 150, 2000), CO
    )
    validate_error(inverted, ApiErrorId.ERR_TIER_INTERVAL_INVALID, 422)

    used_rows, used_meta = validate_paginated(
        api_client.list_curtailment_tiers(line_id, CO, params={"inventory_class": "USED"})
    )
    assert used_meta["total_count"] == 1
    assert used_rows[0]["id"] == used_rung["id"]
