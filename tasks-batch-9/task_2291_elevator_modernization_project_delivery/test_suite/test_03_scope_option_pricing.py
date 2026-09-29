"""The pinned pricing chain: per-trigger surcharge rounding, escalation, discount."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_procurement_order,
    list_code_triggers,
    price_code_trigger,
    read_car,
    read_code_trigger,
    read_scope_option,
    setup_scoped_car,
    validate_error,
    waive_code_trigger,
)
from test_helpers.fixtures import PM

MARLOW_SURCHARGE = {
    "name": "County of Marlow",
    "code_edition_year": 2019,
    "fire_service_required": True,
    "seismic_zone": 3,
    "door_protection_required": False,
    "permit_surcharge_pct": 0.0250,
}

ASHFIELD = {
    "name": "City of Ashfield",
    "code_edition_year": 2019,
    "fire_service_required": True,
    "seismic_zone": 0,
    "door_protection_required": False,
    "permit_surcharge_pct": 0.0000,
}


def _surcharged_option():
    """A machine-tier option in a surcharge-bearing jurisdiction, triggers unpriced."""
    return setup_scoped_car(
        tier="CONTROLLER_MACHINE",
        base_price_cents=8_000_000,
        controller_condition="POOR",
        machine_condition="POOR",
        door_equipment_condition="GOOD",
        car_overrides=[{"rated_load_lbs": 4000, "machine_type": "GEARLESS"}],
        jurisdiction_overrides=MARLOW_SURCHARGE,
        building_name="Marlow Center",
    )


def test_permit_surcharge_is_rounded_per_trigger_before_the_lines_are_summed():
    """For each contributing trigger, its `cost_cents` is multiplied by one plus the
    jurisdiction's `permit_surcharge_pct`, and **that per-trigger product is rounded
    half-up to whole cents before anything is added**. Only then are the rounded
    per-trigger lines summed. The alternative order — summing the unrounded surcharged
    amounts and rounding the single total once — is not the rule and can differ by one
    cent for each pair of half-cent residues; it is explicitly rejected.

    Design: Difficulty/combinatorial_formula/code_upgrade_permit_surcharge_rounded_per_trigger_then_summed
    """
    ctx = _surcharged_option()
    option_id = ctx["scope_option"]["id"]
    triggers = list_code_triggers(option_id)

    assert len(triggers) == 2
    assert triggers[0]["trigger_type"] == "FIRE_SERVICE_PHASE_I_II"
    assert triggers[1]["trigger_type"] == "SEISMIC_RESTRAINT"

    price_code_trigger(triggers[0]["id"], 1_099_970)
    price_code_trigger(triggers[1]["id"], 899_970)

    assert read_code_trigger(triggers[0]["id"])["status"] == "PRICED"
    assert read_code_trigger(triggers[1]["id"])["status"] == "PRICED"

    option = read_scope_option(option_id)
    assert option["code_upgrade_cents"] == 2_049_938
    assert option["code_upgrade_cents"] != 2_049_939


def test_the_surcharged_option_total_carries_the_per_line_rounded_code_upgrade():
    """**Step eight: the total.** `total_price_cents` is the post-escalation subtotal minus
    `volume_discount_cents` — equivalently, `base_price_cents` plus `code_upgrade_cents`
    plus `escalation_fee_cents` less `volume_discount_cents`.

    An option with no live procurement orders is a fully priced option, not an unpriced
    one: its `max_lead_time_days` is the empty-set fallback of 0, its `escalation_pct` is
    0.0000, its `escalation_fee_cents` is 0, and its discount tier is keyed on base plus
    code upgrades alone.

    Design: Difficulty/combinatorial_formula/code_upgrade_permit_surcharge_rounded_per_trigger_then_summed
    """
    ctx = _surcharged_option()
    option_id = ctx["scope_option"]["id"]
    car = read_car(ctx["car"]["id"])
    assert car["condition_score"] == 38.75
    assert car["recommended_scope_tier"] == "CONTROLLER_MACHINE"

    triggers = list_code_triggers(option_id)
    price_code_trigger(triggers[0]["id"], 1_099_970)
    price_code_trigger(triggers[1]["id"], 899_970)

    option = read_scope_option(option_id)
    assert option["escalation_pct"] == 0.0000
    assert option["escalation_fee_cents"] == 0
    assert option["volume_discount_pct"] == 0.0000
    assert option["volume_discount_cents"] == 0
    assert option["total_price_cents"] == 10_049_938

    assert read_car(ctx["car"]["id"])["compliance_status"] == "TRIGGERS_CLEARED"


def test_volume_discount_is_keyed_on_the_post_escalation_subtotal():
    """`volume_discount_pct` is keyed on the **post-escalation subtotal** — not on
    `base_price_cents`, and not on the pre-escalation amount. A subtotal below 15,000,000
    cents (that is, below one hundred fifty thousand dollars) earns 0.0000. A subtotal at
    or above that line but below 30,000,000 cents earns 0.0200.

    The pinned keying is observable whenever escalation carries the amount across a
    discount breakpoint: an option whose pre-escalation amount sits just under a
    breakpoint but whose subtotal lands at or above it earns the higher discount tier,
    where keying on the pre-escalation amount instead would award no discount or a lower
    one and produce a strictly larger total.

    Design: Difficulty/combinatorial_formula/pricing_volume_discount_keyed_on_post_escalation_subtotal
    """
    ctx = setup_scoped_car(
        tier="CONTROLLER_ONLY",
        base_price_cents=14_200_000,
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
        car_overrides=[{"controller_type_legacy": "SOLID_STATE_ANALOG"}],
        jurisdiction_overrides=ASHFIELD,
        building_name="Ashfield Plaza",
    )
    option_id = ctx["scope_option"]["id"]
    triggers = list_code_triggers(option_id)
    price_code_trigger(triggers[0]["id"], 600_000)

    before = read_scope_option(option_id)
    assert before["code_upgrade_cents"] == 600_000
    assert before["total_price_cents"] == 14_800_000
    assert before["volume_discount_pct"] == 0.0000

    create_procurement_order(
        option_id, item_type="CONTROLLER", lead_time_days=150, required_staging_sqft=400
    )

    after = read_scope_option(option_id)
    assert after["volume_discount_pct"] == 0.0200
    assert after["volume_discount_cents"] == 315_240
    assert after["total_price_cents"] == 15_446_760
    assert after["total_price_cents"] != 15_762_000


def test_a_long_lead_order_re_tiers_the_escalation_of_a_draft_option():
    """`max_lead_time_days` is the largest `lead_time_days` across this option's
    procurement orders whose status is anything other than `CANCELLED`; when that set is
    empty — no order was ever raised, or every order has been cancelled —
    `max_lead_time_days` is 0. The rate `escalation_pct` is then selected by which bucket
    the longest lead falls into: at most 60 days carries 0.0000; from 61 through 120 days
    inclusive carries 0.0300; from 121 through 180 days inclusive carries 0.0650; and 181
    days or more carries 0.1100.

    **Step four: the escalation fee.** `escalation_fee_cents` is the pre-escalation amount
    multiplied by `escalation_pct`, rounded half-up to whole cents.

    Design: Difficulty/combinatorial_formula/pricing_volume_discount_keyed_on_post_escalation_subtotal
    """
    ctx = setup_scoped_car(
        tier="CONTROLLER_ONLY",
        base_price_cents=14_200_000,
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
        car_overrides=[{"controller_type_legacy": "SOLID_STATE_ANALOG"}],
        jurisdiction_overrides=ASHFIELD,
        building_name="Ashfield Plaza",
    )
    option_id = ctx["scope_option"]["id"]
    price_code_trigger(list_code_triggers(option_id)[0]["id"], 600_000)

    create_procurement_order(
        option_id, item_type="CONTROLLER", lead_time_days=150, required_staging_sqft=400
    )

    option = read_scope_option(option_id)
    assert option["max_lead_time_days"] == 150
    assert option["escalation_pct"] == 0.0650
    assert option["escalation_fee_cents"] == 962_000


def test_code_upgrade_cents_ranges_over_priced_triggers_only():
    """**Step one: the code-upgrade total.** `code_upgrade_cents` aggregates only those
    code triggers of this option whose status is `PRICED`. Triggers still in `REQUIRED`
    contribute nothing (they also block approval outright), triggers in `WAIVED`
    contribute nothing regardless of the `cost_cents` they may be carrying, and triggers
    in `SATISFIED` retain the contribution they last had when priced.

    After a pricing or a waiver, if zero triggers of the car's live scope option remain in
    status `REQUIRED`, the car moves `TRIGGERS_OPEN → TRIGGERS_CLEARED` with its
    `work_status` untouched.

    Design: Corner/calculations/code_upgrade_cents_sums_priced_triggers_only
    """
    ctx = setup_scoped_car(
        tier="CONTROLLER_DOOR",
        base_price_cents=6_000_000,
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="FAIR",
        marlow=True,
        jurisdiction_overrides={"code_edition_year": 2022, "permit_surcharge_pct": 0.0000},
        building_name="Marlow Center",
    )
    option_id = ctx["scope_option"]["id"]
    triggers = list_code_triggers(option_id)

    assert len(triggers) == 2
    assert triggers[0]["trigger_type"] == "FIRE_SERVICE_PHASE_I_II"
    assert triggers[1]["trigger_type"] == "DOOR_PROTECTION_REOPENING"
    assert all(trigger["status"] == "REQUIRED" for trigger in triggers)
    assert all(trigger["cost_cents"] == 0 for trigger in triggers)

    before = read_scope_option(option_id)
    assert before["code_upgrade_cents"] == 0
    assert before["total_price_cents"] == 6_000_000

    price_code_trigger(triggers[0]["id"], 500_000)

    fire = read_code_trigger(triggers[0]["id"])
    assert fire["status"] == "PRICED"
    assert fire["cost_cents"] == 500_000

    priced = read_scope_option(option_id)
    assert priced["code_upgrade_cents"] == 500_000
    assert priced["total_price_cents"] == 6_500_000
    assert read_car(ctx["car"]["id"])["compliance_status"] == "TRIGGERS_OPEN"

    waive_code_trigger(
        ctx["jurisdiction"]["id"], triggers[1]["id"], "AHJ-WVR-2026-0044"
    )

    door = read_code_trigger(triggers[1]["id"])
    assert door["status"] == "WAIVED"
    assert door["waiver_reference"] == "AHJ-WVR-2026-0044"
    assert door["cost_cents"] == 0

    waived = read_scope_option(option_id)
    assert waived["code_upgrade_cents"] == 500_000
    assert waived["total_price_cents"] == 6_500_000
    assert read_car(ctx["car"]["id"])["compliance_status"] == "TRIGGERS_CLEARED"


def test_pricing_a_waived_code_trigger_is_refused():
    """The trigger must be in status `REQUIRED`; pricing a trigger that is not `REQUIRED`
    is refused with `ERR_CODE_TRIGGER_STATE_INVALID`.

    A waiver is accepted on a trigger in status `REQUIRED` or in status `PRICED`; waiving
    a trigger that is already `WAIVED` or already `SATISFIED` is refused with
    `ERR_CODE_TRIGGER_STATE_INVALID`.

    Design: Corner/endpoints/pricing_a_waived_code_trigger_is_not_an_allowed_action
    """
    ctx = setup_scoped_car(
        tier="CONTROLLER_ONLY",
        base_price_cents=5_000_000,
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
        marlow=True,
        building_name="Marlow Center",
    )
    option_id = ctx["scope_option"]["id"]
    trigger = list_code_triggers(option_id)[0]
    assert trigger["trigger_type"] == "FIRE_SERVICE_PHASE_I_II"

    waived = waive_code_trigger(
        ctx["jurisdiction"]["id"], trigger["id"], "AHJ-WVR-2026-0101"
    )
    assert waived["status"] == "WAIVED"
    assert read_car(ctx["car"]["id"])["compliance_status"] == "TRIGGERS_CLEARED"

    response = api_client.price_code_trigger(trigger["id"], {"cost_cents": 900_000}, PM)
    validate_error(
        response, ApiErrorId.ERR_CODE_TRIGGER_STATE_INVALID, expected_status=409
    )

    stored = read_code_trigger(trigger["id"])
    assert stored["status"] == "WAIVED"
    assert stored["cost_cents"] == 0
    assert stored["waiver_reference"] == "AHJ-WVR-2026-0101"

    option = read_scope_option(option_id)
    assert option["code_upgrade_cents"] == 0
    assert option["total_price_cents"] == 5_000_000
    assert read_car(ctx["car"]["id"])["compliance_status"] == "TRIGGERS_CLEARED"
