"""Price-rule supersession: stale items, the fifth-item posture flip, and its gate."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    get_success_data, factories,
    setup_five_active_items_scenario,
    read_item, read_facility,
    ANALYST,
)


def _supersede(s):
    payload = factories.create_price_rule_payload(
        s["facility"]["id"], s["revenue_code"]["id"],
        pricing_method="FLAT_FEE", flat_fee_cents=150000,
        min_medicare_multiple_bp=12000, market_cap_multiple_bp=11000,
        effective_from="2026-09-15T00:00:00Z",
        supersede_rule_id=s["price_rule"]["id"],
    )
    return validate_success(api_client.create_price_rule(payload, ANALYST), 201)


def test_supersession_stales_every_applied_item_and_truncates_the_old_interval():
    """PRD §3.2: "The named rule transitions `ACTIVE → SUPERSEDED`, its `effective_to` is
    truncated to the new rule's `effective_from`, and its `superseded_by_rule_id` is set to
    the new rule's identifier."
    PRD §3.2: "Every `ChargeItem` whose `applied_price_rule_id` names the superseded rule
    transitions in the pricing dimension from `PRICED_CURRENT` to `PRICE_STALE`, with each
    such item's `version` advancing by 1."
    PRD §3.2: "Each rule exposes `applied_item_count`, the number of charge items whose
    `applied_price_rule_id` names it."
    PRD §3.4: "It fires when the `PriceRule` named by the item's `applied_price_rule_id`
    transitions `ACTIVE → SUPERSEDED`; the precondition is precisely that the item's
    `applied_price_rule_id` equals the superseded rule's identifier."

    Design: Difficulty/transitive_cascade/transitive_cascade__price_rule_supersession_stales_five_items_restricts_facility
    """
    s = setup_five_active_items_scenario()
    facility = s["facility"]
    assert facility["chargemaster_posture"] == "OPEN"
    assert facility["stale_price_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 720000
    assert s["items"][4]["version"] == 5, (
        f"create, reprice, submit, approve, activate is five writes, got {s['items'][4]['version']}"
    )

    rule_b = _supersede(s)
    assert rule_b["status"] == "ACTIVE"

    rule_a = get_success_data(api_client.get_price_rule(s["price_rule"]["id"], ANALYST))
    assert rule_a["status"] == "SUPERSEDED"
    assert rule_a["superseded_by_rule_id"] == rule_b["id"]
    assert rule_a["effective_to"].startswith("2026-09-15T00:00:00"), (
        f"the old interval is truncated to the new effective_from, got {rule_a['effective_to']}"
    )
    assert rule_a["applied_item_count"] == 5

    for item in s["items"]:
        fresh = read_item(item["id"])
        assert fresh["price_status"] == "PRICE_STALE"
        assert fresh["lifecycle_status"] == "ACTIVE", (
            "supersession only touches the pricing dimension"
        )
        assert fresh["gross_charge_cents"] == 144000, (
            "the stale price is retained verbatim, not recomputed"
        )
        assert fresh["applied_price_rule_id"] == s["price_rule"]["id"]
        assert fresh["version"] == item["version"] + 1


def test_the_fifth_stale_item_flips_the_facility_to_restricted_and_blocks_a_cpt_item():
    """PRD §3.2: "The facility's `stale_price_item_count` is then recomputed, and if it has
    reached 5 the facility's `chargemaster_posture` becomes `RESTRICTED`; `Facility.version`
    advances by 1."
    PRD §2.7: "A `RESTRICTED` posture rejects exactly two things with
    `ERR_FACILITY_RESTRICTED` (HTTP 409): creating a charge item whose `code_type` is `CPT` or
    `HCPCS`, and approving a change request whose `request_type` is `REVENUE_CODE_REMAP`."
    PRD §2.7: "`RESTRICTED`, when the facility's `stale_price_item_count` is 5 or more (five
    exactly qualifies)."
    PRD §3.3: "Creation is refused outright while the facility's posture is `FROZEN`
    (`ERR_FACILITY_FROZEN`), and refused for a `CPT` or `HCPCS` item while the posture is
    `RESTRICTED` (`ERR_FACILITY_RESTRICTED`)."
    PRD §2.11: "`stale_price_item_count` (the number of its charge items that are
    simultaneously `ACTIVE` in the lifecycle dimension and `PRICE_STALE` in the pricing
    dimension)"

    Design: Difficulty/transitive_cascade/transitive_cascade__price_rule_supersession_stales_five_items_restricts_facility
    """
    s = setup_five_active_items_scenario()
    _supersede(s)

    facility = read_facility(s["facility"]["id"])
    assert facility["stale_price_item_count"] == 5
    assert facility["chargemaster_posture"] == "RESTRICTED", (
        "the boundary is at or above 5, not strictly above 4"
    )
    assert facility["active_item_count"] == 5
    assert facility["aggregate_gross_charge_cents"] == 720000
    assert facility["aggregate_cost_basis_cents"] == 300000
    assert facility["aggregate_markup_ratio_bp"] == 24000

    payload = factories.create_charge_item_payload(
        s["facility"]["id"], s["department"]["id"], s["revenue_code"]["id"],
        cdm_number="CDM-40006", description="Vitamin D assay",
        code_type="CPT", code_value="82306",
        cost_basis_cents=60000, medicare_rate_cents=18000, market_p75_cents=200000,
        effective_from="2026-09-01T00:00:00Z",
    )
    validate_error(
        api_client.create_charge_item(payload, ANALYST),
        ApiErrorId.ERR_FACILITY_RESTRICTED.value,
    )

    rows, _meta = validate_paginated(
        api_client.list_charge_items(
            ANALYST, params={"facility_id": s["facility"]["id"], "cdm_number": "CDM-40006"}
        )
    )
    assert len(rows) == 0, "the refused creation must not have persisted a row"
