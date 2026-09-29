"""Rule supersession staling its applied items, and the two item dimensions moving apart."""
from test_helpers import (
    api_client, validate_success, factories,
    setup_base, create_active_item, create_item, item_lifecycle, reprice_item,
    read_item, read_facility, set_clock,
    assert_price_rule,
    ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
        "allowed_revenue_code_values": [],
    },
)


def _setup(price_rule_overrides=None):
    set_clock("2026-09-01T00:00:00Z")
    return setup_base(price_rule_overrides=price_rule_overrides, **MERCY)


def _read_rule(rule_id):
    return validate_success(api_client.get_price_rule(rule_id, ANALYST), 200)


def test_superseding_a_rule_stales_every_item_it_had_priced():
    """PRD §3.2: "The named rule transitions `ACTIVE → SUPERSEDED`, its `effective_to` is truncated
    to the new rule's `effective_from`, and its `superseded_by_rule_id` is set to the new rule's
    identifier. Every `ChargeItem` whose `applied_price_rule_id` names the superseded rule
    transitions in the pricing dimension from `PRICED_CURRENT` to `PRICE_STALE`, with each such
    item's `version` advancing by 1. The facility's `stale_price_item_count` is then recomputed,
    and if it has reached 5 the facility's `chargemaster_posture` becomes `RESTRICTED`;
    `Facility.version` advances by 1."
    PRD §3.2: "Each rule exposes `applied_item_count`, the number of charge items whose
    `applied_price_rule_id` names it."
    PRD §2.7: "3. `RESTRICTED`, when the facility's `stale_price_item_count` is 5 or more (five
    exactly qualifies)."

    Design: Corner/state_machines/price_rule_supersession_cascades_two_items_to_price_stale
    """
    base = _setup(price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"})
    old_rule = base["price_rule"]
    item1 = create_active_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item2 = create_active_item(
        base, cdm_number="CDM-1002", description="CARDIAC CATH ADD-ON",
        code_type="CPT", code_value="93462", cost_basis_cents=60000,
        medicare_rate_cents=30000, market_p75_cents=600000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item1["gross_charge_cents"] == 240000, "100000 of cost sits in the 24000bp band"
    assert item2["gross_charge_cents"] == 144000, "60000 of cost also sits in the 24000bp band"
    assert item1["applied_price_rule_id"] == old_rule["id"]
    assert item2["applied_price_rule_id"] == old_rule["id"]

    new_rule = validate_success(
        api_client.create_price_rule(
            factories.create_price_rule_payload(
                base["facility"]["id"], base["revenue_code"]["id"],
                effective_from="2026-10-01T00:00:00Z", effective_to=None,
                markup_tiers=[{"min_cost_basis_cents": 0, "markup_bp": 30000}],
                min_medicare_multiple_bp=12000, market_cap_multiple_bp=11000,
                supersede_rule_id=old_rule["id"],
            ),
            ANALYST,
        ),
        201,
    )
    assert_price_rule(new_rule)

    retired = _read_rule(old_rule["id"])
    assert retired["status"] == "SUPERSEDED"
    assert retired["superseded_by_rule_id"] == new_rule["id"]
    assert retired["effective_to"].startswith("2026-10-01T00:00:00"), (
        "truncated to the successor's effective_from"
    )
    assert retired["applied_item_count"] == 2, (
        "applied_item_count counts the items still pointing at the rule, staleness notwithstanding"
    )
    assert new_rule["status"] == "ACTIVE"
    assert _read_rule(new_rule["id"])["applied_item_count"] == 0, "it has priced nothing yet"

    for item in (read_item(item1["id"]), read_item(item2["id"])):
        assert item["price_status"] == "PRICE_STALE"
        assert item["lifecycle_status"] == "ACTIVE", "the lifecycle dimension is untouched"
    assert read_item(item1["id"])["gross_charge_cents"] == 240000, (
        "the stale price is retained verbatim; nothing is recomputed"
    )
    assert read_item(item2["id"])["gross_charge_cents"] == 144000

    facility = read_facility(base["facility"]["id"])
    assert facility["stale_price_item_count"] == 2
    assert facility["chargemaster_posture"] == "OPEN", "2 is short of the 5 that would restrict"
    assert facility["aggregate_gross_charge_cents"] == 384000
    assert facility["aggregate_cost_basis_cents"] == 160000


def test_repricing_a_pending_review_item_advances_only_the_pricing_dimension():
    """PRD §3.4: "Every charge item carries a second, fully independent state dimension,
    `price_status`, whose values are `PRICED_CURRENT`, `PRICE_STALE`, `REPRICE_PENDING` and
    `PRICE_FROZEN`. It begins at `PRICE_STALE` and has no terminal state — an item's price is never
    finished. Because the two dimensions are independent, a `DRAFT` item and an `ACTIVE` item are
    both repriceable, and the lifecycle actions of §3.3 never write `price_status` except where
    explicitly stated."
    PRD §3.4: "On success, in order: `prior_gross_charge_cents` takes the item's outgoing
    `gross_charge_cents` before it is overwritten; `gross_charge_cents` takes the computed output;
    `applied_price_rule_id` records the selected rule; `price_conflict` is set according to whether
    the Medicare floor exceeded the market cap; `price_status` becomes `PRICED_CURRENT`; and the
    item's `version` advances by 1."
    PRD §2.11: "`stale_price_item_count` (the number of its charge items that are simultaneously
    `ACTIVE` in the lifecycle dimension and `PRICE_STALE` in the pricing dimension)"

    Design: Corner/state_machines/parallel_dimensions_reprice_of_pending_review_item_leaves_lifecycle_untouched
    """
    base = _setup()
    item = create_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item["price_status"] == "PRICE_STALE" and item["version"] == 1

    submitted = item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    assert submitted["price_status"] == "PRICE_STALE", "the lifecycle action wrote no price_status"
    assert submitted["version"] == 2

    repriced = reprice_item(item["id"])
    assert repriced["lifecycle_status"] == "PENDING_REVIEW", (
        "the reprice wrote no lifecycle_status"
    )
    assert repriced["version"] == 3, "two writes on one row, one version each"
    assert repriced["price_status"] == "PRICED_CURRENT"
    assert repriced["gross_charge_cents"] == 240000
    assert repriced["prior_gross_charge_cents"] == 0, "the outgoing gross charge was 0"
    assert repriced["applied_price_rule_id"] == base["price_rule"]["id"]

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 0
    assert facility["stale_price_item_count"] == 0, (
        "a PENDING_REVIEW item is not ACTIVE, so it never counted as stale"
    )
