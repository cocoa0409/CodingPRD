"""Markup compliance: the exclusive-snapshot evaluation order and its consequences."""
from test_helpers import (
    api_client, validate_success,
    setup_markup_snapshot_scenario,
    create_change_request, review_change_request, read_change_request,
    read_item, read_facility, implement_change_request,
    ANALYST, APPROVER, ANALYST_USER_ID, APPROVER_USER_ID,
)


def _submit_price_change(s):
    return create_change_request(
        s, s["item_b"]["id"], "PRICE_CHANGE",
        justification="reagent contract renegotiated upward",
        proposed_cost_basis_cents=45000,
    )


def test_projected_ratio_excludes_the_target_item_before_adding_the_proposal():
    """PRD §3.2: "First, the item under evaluation is *excluded* from the facility snapshot:
    the snapshot numerator is the facility's `aggregate_gross_charge_cents` less the item's
    own `gross_charge_cents` if and only if the item's `lifecycle_status` is `ACTIVE` (and
    less nothing otherwise), and the snapshot denominator is the facility's
    `aggregate_cost_basis_cents` less the item's own `cost_basis_cents` under the same
    condition."
    PRD §3.2: "Third, `projected_markup_ratio_bp` is the sum of snapshot and proposed gross
    charge, multiplied by 10000, divided by the sum of snapshot and proposed cost, rounded
    half up — and defined as 0 when that denominator is 0."
    PRD §3.2: "Excluding the item first is what stops a repriced `ACTIVE` item from being
    counted twice; naively adding proposed values on top of the live aggregate inflates the
    ratio and would reject legitimate changes."
    PRD §3.2: "The check passes when `projected_markup_ratio_bp` is at or below the
    facility's `aggregate_markup_limit_bp`; equality passes."

    Design: Difficulty/combinatorial_formula/combinatorial_formula__mode_c_exclusive_snapshot_evaluation_order_on_markup_ratio
    """
    s = setup_markup_snapshot_scenario()
    facility = read_facility(s["facility"]["id"])
    assert facility["aggregate_gross_charge_cents"] == 1128000
    assert facility["aggregate_cost_basis_cents"] == 1040000
    assert facility["aggregate_markup_ratio_bp"] == 10846
    assert facility["aggregate_markup_limit_bp"] == 11000

    cr = _submit_price_change(s)
    assert cr["projected_gross_charge_cents"] == 144000, (
        "45000 cents falls in the 32000bp tier, giving 144000: "
        f"got {cr['projected_gross_charge_cents']}"
    )
    assert cr["projected_markup_ratio_bp"] == 10947, (
        "the exclusive snapshot is 1000000/1000000, so the projection is "
        f"1144000 * 10000 / 1045000 = 10947, got {cr['projected_markup_ratio_bp']}"
    )
    assert cr["projected_markup_ratio_bp"] != 11724, (
        "11724 is the forbidden add-onto-the-live-aggregate order"
    )

    review_change_request(cr["id"], ANALYST, decision_note="cost documentation attached")
    b_version = read_item(s["item_b"]["id"])["version"]
    approved = validate_success(
        api_client.approve_change_request(
            cr["id"],
            {"expected_charge_item_version": b_version,
             "decision_note": "within aggregate markup limit"},
            APPROVER,
        ),
        200,
    )
    assert approved["status"] == "APPROVED", (
        "10947 is at or below the 11000 limit, so the approval must not be refused"
    )
    assert approved["approved_by_user_id"] == APPROVER_USER_ID
    assert approved["reviewed_by_user_id"] == ANALYST_USER_ID
    assert approved["submitted_by_user_id"] == s["manager_user_id"]
    assert approved["pinned_charge_item_version"] == b_version + 1, (
        "approval bumps the item into REPRICE_PENDING and pins the post-bump version"
    )
    assert read_item(s["item_b"]["id"])["price_status"] == "REPRICE_PENDING"


def test_implementation_makes_the_stored_aggregate_ratio_match_the_projection():
    """PRD §3.4: "On success the item's `cost_basis_cents`, `description` and
    `revenue_code_id` are updated according to the request's `request_type`,
    `prior_gross_charge_cents` takes the outgoing `gross_charge_cents`,
    `gross_charge_cents` is recomputed from the rule selector and pricing arithmetic,
    `price_status` becomes `PRICED_CURRENT`, and the item's `version` advances by 1."
    PRD §3.2: "The ratio is computed before any field is written, and once the write does
    occur the stored facility aggregates are recomputed from the persisted items rather than
    from this projection."
    PRD §2.11: "Aggregates in this system are always derived from persisted rows, never from
    projections."

    Design: Difficulty/combinatorial_formula/combinatorial_formula__mode_c_exclusive_snapshot_evaluation_order_on_markup_ratio
    """
    s = setup_markup_snapshot_scenario()
    cr = _submit_price_change(s)
    review_change_request(cr["id"], ANALYST, decision_note="cost documentation attached")
    b_version = read_item(s["item_b"]["id"])["version"]
    validate_success(
        api_client.approve_change_request(
            cr["id"], {"expected_charge_item_version": b_version}, APPROVER
        ),
        200,
    )

    implemented = implement_change_request(cr["id"], implementation_note="applied")
    assert implemented["status"] == "IMPLEMENTED"
    assert read_change_request(cr["id"])["status"] == "IMPLEMENTED"

    b = read_item(s["item_b"]["id"])
    assert b["cost_basis_cents"] == 45000
    assert b["gross_charge_cents"] == 144000
    assert b["prior_gross_charge_cents"] == 128000
    assert b["price_status"] == "PRICED_CURRENT"

    facility = read_facility(s["facility"]["id"])
    assert facility["aggregate_gross_charge_cents"] == 1144000
    assert facility["aggregate_cost_basis_cents"] == 1045000
    assert facility["aggregate_markup_ratio_bp"] == 10947, (
        "the persisted aggregate must land exactly on the projected ratio, got "
        f"{facility['aggregate_markup_ratio_bp']}"
    )
