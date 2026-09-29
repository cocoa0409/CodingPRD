"""The facility-level markup gate: exclusive snapshot first, then an inclusive comparison."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_base, create_item, create_active_item, create_change_request,
    review_change_request, approve_change_request, item_lifecycle, reprice_item,
    read_item, read_facility, read_change_request, patch_facility, set_clock,
    APPROVER,
)


def _scope(code: str, ccn: str, facility_extra=None) -> dict:
    facility_overrides = {"name": f"Hospital {ccn}", "cms_certification_number": ccn,
                          "rounding_mode": "NEAREST_CENT"}
    facility_overrides.update(facility_extra or {})
    return setup_base(
        facility_overrides=facility_overrides,
        revenue_code_overrides={
            "code": code, "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
            "allowed_revenue_code_values": [],
        },
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
    )


ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def test_the_live_item_is_excluded_before_its_proposal_is_added_back():
    """PRD §3.2: "First, the item under evaluation is *excluded* from the facility snapshot: the
    snapshot numerator is the facility's `aggregate_gross_charge_cents` less the item's own
    `gross_charge_cents` if and only if the item's `lifecycle_status` is `ACTIVE` (and less nothing
    otherwise), and the snapshot denominator is the facility's `aggregate_cost_basis_cents` less the
    item's own `cost_basis_cents` under the same condition."
    PRD §3.2: "Excluding the item first is what stops a repriced `ACTIVE` item from being counted
    twice; naively adding proposed values on top of the live aggregate inflates the ratio and would
    reject legitimate changes. The ratio is computed before any field is written, and once the write
    does occur the stored facility aggregates are recomputed from the persisted items rather than
    from this projection."
    PRD §3.5: "For `PRICE_CHANGE` and `NEW_ITEM`, the target item's `price_status` moves to
    `REPRICE_PENDING` and `ChargeItem.version` advances by 1; `pinned_charge_item_version` is set to
    the *post-bump* version so that the later implementation can match it."

    Design: Corner/calculations/markup_exclusive_snapshot_lets_a_repriced_active_item_pass_a_limit_naive_math_would_breach
    """
    set_clock("2026-09-01T00:00:00Z")
    base = _scope("0300", "CCN-2193-SNAPSHOT", facility_extra={"aggregate_markup_limit_bp": 40000})
    item = create_active_item(base, **ITEM)
    assert item["gross_charge_cents"] == 240000

    before = read_facility(base["facility"]["id"])
    assert before["aggregate_markup_ratio_bp"] == 24000
    assert before["aggregate_gross_charge_cents"] == 240000
    assert before["aggregate_cost_basis_cents"] == 100000

    tightened = patch_facility(base["facility"]["id"], aggregate_markup_limit_bp=19000)
    assert tightened["aggregate_markup_limit_bp"] == 19000

    request = create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="Supply cost increase from the new catheter contract",
        proposed_cost_basis_cents=300000,
    )
    assert request["projected_gross_charge_cents"] == 540000, "300000 of cost at 18000 bp"
    assert request["projected_markup_ratio_bp"] == 18000, (
        "the snapshot empties to (0, 0) so the ratio is 540000 over 300000, not 19500"
    )

    review_change_request(request["id"])
    live_version = read_item(item["id"])["version"]
    approved = approve_change_request(request["id"], live_version, APPROVER,
                                     decision_note="Within the tightened ceiling")
    assert approved["projected_markup_ratio_bp"] == 18000
    assert approved["status"] == "APPROVED"

    item_after = read_item(item["id"])
    assert read_change_request(request["id"])["pinned_charge_item_version"] == (
        item_after["version"]
    ), "the pin takes the post-bump version so implementation can match it"
    assert item_after["price_status"] == "REPRICE_PENDING"
    assert item_after["gross_charge_cents"] == 240000, "approval writes no price"

    facility = read_facility(base["facility"]["id"])
    assert facility["aggregate_markup_limit_bp"] == 19000
    assert facility["aggregate_markup_ratio_bp"] == 24000, (
        "the stored aggregate still reflects the persisted item, not the projection"
    )
    assert facility["aggregate_gross_charge_cents"] == 240000


def test_the_markup_ceiling_comparison_admits_equality_but_nothing_above_it():
    """PRD §3.2: "The check passes when `projected_markup_ratio_bp` is at or below the facility's
    `aggregate_markup_limit_bp`; equality passes. Failure is `ERR_AGGREGATE_MARKUP_LIMIT` (HTTP
    422)."
    PRD §3.3: "Two additional preconditions apply beyond posture, evaluated in this order: the
    pricing dimension must already be settled, meaning `price_status` must equal `PRICED_CURRENT`,
    otherwise `ERR_ITEM_PRICE_NOT_CURRENT` (409); and the markup-compliance projection of §3.2 must
    land at or below the facility's `aggregate_markup_limit_bp`, otherwise
    `ERR_AGGREGATE_MARKUP_LIMIT` (422)."
    PRD §3.2: "Third, `projected_markup_ratio_bp` is the sum of snapshot and proposed gross charge,
    multiplied by 10000, divided by the sum of snapshot and proposed cost, rounded half up — and
    defined as 0 when that denominator is 0."

    Design: Corner/calculations/markup_limit_comparison_is_inclusive_so_24000_bp_passes_while_a_23999_bp_limit_blocks_approval
    """
    set_clock("2026-09-01T00:00:00Z")
    equal = _scope("0300", "CCN-2193-EQUAL",
                   facility_extra={"aggregate_markup_limit_bp": 24000})
    under = _scope("0301", "CCN-2193-UNDER",
                   facility_extra={"aggregate_markup_limit_bp": 23999})

    item_e = create_item(equal, **ITEM)
    item_f = create_item(under, **ITEM)
    for item in (item_e, item_f):
        assert reprice_item(item["id"])["gross_charge_cents"] == 240000
        item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW")

    approved = item_lifecycle(item_e["id"], "APPROVE", note="Exactly at the ceiling")
    assert approved["lifecycle_status"] == "APPROVED", "24000 bp against a 24000 bp limit passes"

    validate_error(
        api_client.charge_item_lifecycle(
            item_f["id"], {"action": "APPROVE", "note": "One basis point too far"}, APPROVER
        ),
        ApiErrorId.ERR_AGGREGATE_MARKUP_LIMIT.value, 422,
    )

    stored_e = read_item(item_e["id"])
    assert stored_e["lifecycle_status"] == "APPROVED"
    assert stored_e["version"] == 4, "create, reprice, submit, approve"
    stored_f = read_item(item_f["id"])
    assert stored_f["lifecycle_status"] == "PENDING_REVIEW", "the refusal moved nothing"
    assert stored_f["version"] == 3

    assert read_facility(equal["facility"]["id"])["active_item_count"] == 0, (
        "approval is not activation, so no aggregate moved"
    )
    assert read_facility(under["facility"]["id"])["aggregate_gross_charge_cents"] == 0
