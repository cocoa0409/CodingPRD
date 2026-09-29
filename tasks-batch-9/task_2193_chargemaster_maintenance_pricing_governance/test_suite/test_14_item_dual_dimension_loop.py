"""The charge item's two parallel status dimensions and the DRAFT/PENDING_REVIEW loop."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    setup_northgate_item_scenario,
    item_lifecycle, reprice_item, read_item, read_facility,
    ANALYST, APPROVER,
)


def test_lifecycle_loop_and_price_advance_move_independently_before_approval():
    """PRD §3.3: "It sets `lifecycle_status` to `PENDING_REVIEW` and touches nothing in the
    pricing dimension: the two dimensions are independent and this transition does not read
    or write `price_status`."
    PRD §3.3: "An item may cycle `DRAFT → PENDING_REVIEW → DRAFT` any number of times."
    PRD §3.4: "Because the two dimensions are independent, a `DRAFT` item and an `ACTIVE`
    item are both repriceable, and the lifecycle actions of §3.3 never write `price_status`
    except where explicitly stated."
    PRD §3.3: "A newly created item lands in `DRAFT` in the lifecycle dimension and
    `PRICE_STALE` in the pricing dimension, with `gross_charge_cents` at 0,
    `prior_gross_charge_cents` at 0, `price_conflict` false, `applied_price_rule_id` null
    (nothing has been priced yet), `duplicate_of_item_id` null, `approved_by_user_id` null,
    `last_code_cycle_id` null, and `version` 1."

    Design: Difficulty/non_linear_state_machine/non_linear_state_machine__charge_item_parallel_dimensions_double_revision_loop
    """
    s = setup_northgate_item_scenario()
    item = s["item"]
    assert item["lifecycle_status"] == "DRAFT"
    assert item["price_status"] == "PRICE_STALE"
    assert item["version"] == 1

    submitted = item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST,
                               note="first submission")
    assert submitted["lifecycle_status"] == "PENDING_REVIEW"
    assert submitted["price_status"] == "PRICE_STALE", (
        "submission must not touch the pricing dimension"
    )

    bounced = item_lifecycle(item["id"], "RETURN_TO_DRAFT", ANALYST,
                             note="cost basis needs a second look")
    assert bounced["lifecycle_status"] == "DRAFT"
    assert bounced["price_status"] == "PRICE_STALE"

    repriced = reprice_item(item["id"])
    assert repriced["lifecycle_status"] == "DRAFT", (
        "repricing a DRAFT item must leave the lifecycle dimension alone"
    )
    assert repriced["price_status"] == "PRICED_CURRENT"
    assert repriced["gross_charge_cents"] == 144000, (
        "cost 60000 selects the 24000bp band: expected 144000, got "
        f"{repriced['gross_charge_cents']}"
    )
    assert repriced["prior_gross_charge_cents"] == 0
    assert repriced["price_conflict"] is False
    assert repriced["applied_price_rule_id"] == s["price_rule"]["id"]


def test_approval_is_admissible_only_once_the_other_dimension_is_priced_current():
    """PRD §3.3: "Two additional preconditions apply beyond posture, evaluated in this order:
    the pricing dimension must already be settled, meaning `price_status` must equal
    `PRICED_CURRENT`, otherwise `ERR_ITEM_PRICE_NOT_CURRENT` (409); and the
    markup-compliance projection of §3.2 must land at or below the facility's
    `aggregate_markup_limit_bp`, otherwise `ERR_AGGREGATE_MARKUP_LIMIT` (422)."
    PRD §3.3: "Every one of them is gated on the facility not being `FROZEN`, and every one
    of them advances the item's `version` by 1."
    PRD §2.11: "Items in `DRAFT`, `PENDING_REVIEW`, `APPROVED`, `INACTIVE` or `ARCHIVED`
    never contribute to any facility aggregate."

    Design: Difficulty/non_linear_state_machine/non_linear_state_machine__charge_item_parallel_dimensions_double_revision_loop
    """
    s = setup_northgate_item_scenario()
    item_id = s["item"]["id"]

    item_lifecycle(item_id, "SUBMIT_FOR_REVIEW", ANALYST, note="first submission")
    validate_error(
        api_client.charge_item_lifecycle(
            item_id, {"action": "APPROVE", "note": "premature"}, APPROVER
        ),
        ApiErrorId.ERR_ITEM_PRICE_NOT_CURRENT.value,
    )

    item_lifecycle(item_id, "RETURN_TO_DRAFT", ANALYST, note="cost basis needs a look")
    reprice_item(item_id)
    item_lifecycle(item_id, "SUBMIT_FOR_REVIEW", ANALYST, note="second submission")

    approved = validate_success(
        api_client.charge_item_lifecycle(
            item_id, {"action": "APPROVE", "note": "committee approval"}, APPROVER
        ),
        200,
    )
    assert approved["lifecycle_status"] == "APPROVED"
    assert approved["price_status"] == "PRICED_CURRENT"
    assert approved["version"] == 6, (
        "create 1, submit 2, return-to-draft 3, reprice 4, submit 5, approve 6 — the "
        f"refused approval bumps nothing: got {approved['version']}"
    )

    final = read_item(item_id)
    assert final["lifecycle_status"] == "APPROVED"
    assert final["gross_charge_cents"] == 144000

    facility = read_facility(s["facility"]["id"])
    assert facility["active_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 0
    assert facility["stale_price_item_count"] == 0
    assert facility["chargemaster_posture"] == "OPEN"
