"""Implementation rewrites the item and strands every sibling approval whose pin no longer fits."""
from test_helpers import (
    setup_base, create_active_item, create_change_request, read_change_request,
    review_change_request, approve_change_request, implement_change_request,
    read_item, read_facility, read_department, set_clock,
    ANALYST, APPROVER,
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

ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def _setup():
    """An ACTIVE item at version 5, a DEACTIVATION approval pinned at 5, a PRICE_CHANGE pinned at 6."""
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_active_item(base, **ITEM)
    assert item["version"] == 5

    deactivation = create_change_request(
        base, item["id"], "DEACTIVATION",
        justification="Line is being consolidated into the new tray code",
    )
    review_change_request(deactivation["id"], ANALYST)
    deactivation = approve_change_request(deactivation["id"], 5, APPROVER)

    price_change = create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="Catheter supply contract repriced for FY27",
        proposed_cost_basis_cents=300000,
        proposed_description="CARDIAC CATH BASIC FY27",
    )
    review_change_request(price_change["id"], ANALYST)
    price_change = approve_change_request(price_change["id"], 5, APPROVER)

    base["item"] = item
    base["deactivation"] = deactivation
    base["price_change"] = price_change
    return base


def test_implementation_rewrites_the_item_and_voids_the_stranded_sibling():
    """PRD §3.5: "For `PRICE_CHANGE` and `NEW_ITEM`, the item's `cost_basis_cents` takes
    `proposed_cost_basis_cents`, its `description` takes `proposed_description` when that field is
    non-null, `prior_gross_charge_cents` takes the outgoing `gross_charge_cents`,
    `gross_charge_cents` is recomputed, `price_status` moves to `PRICED_CURRENT`, and
    `ChargeItem.version` advances by 1."
    PRD §3.5: "And every *other* change request with `status` `APPROVED` that targets the same
    `charge_item_id` and whose `pinned_charge_item_version` no longer equals the item's new version
    transitions `APPROVED → VOIDED_STALE`, advancing its own `version` by 1 and prompting a
    recomputation of the department's `open_request_count`."
    PRD §3.5: "For `DEACTIVATION` and `REVENUE_CODE_REMAP`, the item is not mutated at all and
    `pinned_charge_item_version` simply equals the version that was observed."

    Design: Corner/state_machines/change_request_implement_cascades_item_facility_and_voids_sibling_request
    """
    base = _setup()
    assert base["deactivation"]["pinned_charge_item_version"] == 5, (
        "a DEACTIVATION approval mutates nothing, so its pin is the observed version"
    )
    assert base["price_change"]["pinned_charge_item_version"] == 6

    implemented = implement_change_request(
        base["price_change"]["id"], implementation_note="Applied to the chargemaster"
    )
    assert implemented["status"] == "IMPLEMENTED"
    assert implemented["version"] == 4, "create, review, approve, implement"

    item = read_item(base["item"]["id"])
    assert item["version"] == 7
    assert item["cost_basis_cents"] == 300000
    assert item["gross_charge_cents"] == 540000, "300000 of cost reaches the 18000bp band"
    assert item["prior_gross_charge_cents"] == 240000
    assert item["description"] == "CARDIAC CATH BASIC FY27"
    assert item["price_status"] == "PRICED_CURRENT"
    assert item["lifecycle_status"] == "ACTIVE"

    stranded = read_change_request(base["deactivation"]["id"])
    assert stranded["status"] == "VOIDED_STALE", (
        "its pin of 5 no longer matches the item's new version 7"
    )
    assert stranded["pinned_charge_item_version"] == 5, "the stale pin is preserved, not refreshed"

    department = read_department(base["department"]["id"])
    assert department["open_request_count"] == 0, (
        "IMPLEMENTED and VOIDED_STALE are both terminal and neither counts as open"
    )


def test_implementation_recomputes_the_facility_and_demands_a_fresh_transparency_file():
    """PRD §3.5: "The facility's `published_transparency_file_id` is cleared to null, its
    `transparency_status` set to `NEEDS_REFRESH`, its aggregates and `chargemaster_posture`
    recomputed, and `Facility.version` advanced by 1."
    PRD §2.11: "`aggregate_markup_ratio_bp` (the aggregate gross charge multiplied by 10000, divided
    by the aggregate cost basis, rounded half up — and defined as 0 when the aggregate cost basis is
    0)"
    PRD §2.11: "Aggregates in this system are always derived from persisted rows, never from
    projections."

    Design: Corner/state_machines/change_request_implement_cascades_item_facility_and_voids_sibling_request
    """
    base = _setup()
    before = read_facility(base["facility"]["id"])
    assert before["aggregate_gross_charge_cents"] == 240000
    assert before["aggregate_cost_basis_cents"] == 100000

    implement_change_request(
        base["price_change"]["id"], implementation_note="Applied to the chargemaster"
    )

    facility = read_facility(base["facility"]["id"])
    assert facility["aggregate_gross_charge_cents"] == 540000
    assert facility["aggregate_cost_basis_cents"] == 300000
    assert facility["aggregate_markup_ratio_bp"] == 18000, "540000 * 10000 / 300000"
    assert facility["active_item_count"] == 1
    assert facility["transparency_status"] == "NEEDS_REFRESH"
    assert facility["published_transparency_file_id"] is None
    assert facility["version"] > before["version"]
