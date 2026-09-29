"""Validation-order precedence when one request violates several ranks at once."""
from test_helpers import (
    api_client, validate_error, ApiErrorId, get_success_data,
    setup_frozen_and_ruleless_scenario, setup_stale_item_over_markup_limit_scenario,
    read_item, read_facility, file_lifecycle, reprice_item,
    ANALYST, APPROVER,
)


def test_frozen_posture_masks_both_the_price_freeze_and_the_empty_rule_set():
    """PRD §2.9: "The full evaluation order for any request is fixed, and the **first** failing
    check determines the returned `error_id` — later checks are never allowed to mask an
    earlier one"
    PRD §2.9: "14. `FROZEN` posture gate — `ERR_FACILITY_FROZEN` (409)."
    PRD §2.7: "A `FROZEN` posture rejects six write operations with `ERR_FACILITY_FROZEN`
    (HTTP 409): creating a charge item, driving a charge item's lifecycle, repricing a charge
    item, creating a price rule, implementing an approved change request, and — for the
    code-update cycle — the `ACTIVATE` and `ROLL_BACK` actions."
    PRD §3.10: "The `FAIL` action from `VALIDATED` requires only that the file be in
    `VALIDATED`; it sets `status` to `FAILED`, thaws every `PRICE_FROZEN` item of the facility
    back to `PRICED_CURRENT` with each item's `version` advancing by 1, re-derives the
    facility's posture and advances `Facility.version` by 1, leaving the facility without a
    published file."
    PRD §3.2: "If the candidate set is empty, the operation fails with
    `ERR_NO_APPLICABLE_PRICE_RULE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_validation_conflict__state_facility_frozen_beats_constraint_price_frozen_and_fiscal_no_rule
    """
    s = setup_frozen_and_ruleless_scenario()
    assert s["facility"]["chargemaster_posture"] == "FROZEN"
    assert s["item"]["price_status"] == "PRICE_FROZEN"
    assert s["item"]["gross_charge_cents"] == 240000

    resp = api_client.reprice_charge_item(s["item"]["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_FACILITY_FROZEN.value, 409)
    reported = (resp.json().get("data") or {}).get("error_id")
    assert reported not in (
        ApiErrorId.ERR_ITEM_PRICE_FROZEN.value,
        ApiErrorId.ERR_NO_APPLICABLE_PRICE_RULE.value,
    ), f"rank 14 must mask ranks 50 and 53, but the response reported {reported}"

    unchanged = read_item(s["item"]["id"])
    assert unchanged["price_status"] == "PRICE_FROZEN"
    assert unchanged["gross_charge_cents"] == 240000
    assert unchanged["applied_price_rule_id"] == s["price_rule"]["id"]

    failed = file_lifecycle(s["transparency_file"]["id"], "FAIL",
                            note="withdraw the pending publication")
    assert failed["status"] == "FAILED"
    thawed = read_item(s["item"]["id"])
    assert thawed["price_status"] == "PRICED_CURRENT", (
        "the VALIDATED -> FAILED thaw clears the rank-50 constraint"
    )
    assert read_facility(s["facility"]["id"])["chargemaster_posture"] == "OPEN"

    validate_error(
        api_client.reprice_charge_item(s["item"]["id"], ANALYST),
        ApiErrorId.ERR_NO_APPLICABLE_PRICE_RULE.value,
        422,
    )
    assert read_item(s["item"]["id"])["gross_charge_cents"] == 240000, (
        "the fiscal rule was already violated on the first attempt, merely masked"
    )


def test_price_state_constraint_masks_the_aggregate_markup_limit_on_item_approval():
    """PRD §2.9: "`ERR_DUPLICATE_SIMILARITY_TOO_LOW` (422), `ERR_ITEM_PRICE_NOT_CURRENT` (409),
    `ERR_ITEM_PRICE_FROZEN` (409), `ERR_ITEM_RETIRED_AS_DUPLICATE` (409), and the batch-state
    rule for finding dispositions which also reports `ERR_INVALID_BATCH_STATE` (409)."
    PRD §2.9: "53–54. Fiscal rules, last of all: `ERR_NO_APPLICABLE_PRICE_RULE` (422), then
    `ERR_AGGREGATE_MARKUP_LIMIT` (422)."
    PRD §3.3: "Two additional preconditions apply beyond posture, evaluated in this order: the
    pricing dimension must already be settled, meaning `price_status` must equal
    `PRICED_CURRENT`, otherwise `ERR_ITEM_PRICE_NOT_CURRENT` (409); and the markup-compliance
    projection of §3.2 must land at or below the facility's `aggregate_markup_limit_bp`,
    otherwise `ERR_AGGREGATE_MARKUP_LIMIT` (422)."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_validation_conflict__constraint_price_not_current_beats_fiscal_markup_limit_on_item_approve
    """
    s = setup_stale_item_over_markup_limit_scenario()
    rule_a = get_success_data(api_client.get_price_rule(s["price_rule"]["id"], ANALYST))
    assert rule_a["status"] == "SUPERSEDED"
    assert rule_a["superseded_by_rule_id"] == s["price_rule_2"]["id"]
    assert rule_a["effective_to"].startswith("2026-08-05T00:00:00")

    before = read_item(s["item"]["id"])
    assert before["price_status"] == "PRICE_STALE"
    assert before["gross_charge_cents"] == 240000
    assert before["lifecycle_status"] == "PENDING_REVIEW"

    resp = api_client.charge_item_lifecycle(
        s["item"]["id"], {"action": "APPROVE", "note": "committee approval attempt 1"},
        APPROVER,
    )
    validate_error(resp, ApiErrorId.ERR_ITEM_PRICE_NOT_CURRENT.value, 409)
    reported = (resp.json().get("data") or {}).get("error_id")
    assert reported != ApiErrorId.ERR_AGGREGATE_MARKUP_LIMIT.value, (
        "the rank-49 constraint must mask the rank-54 fiscal rule"
    )
    after1 = read_item(s["item"]["id"])
    assert after1["lifecycle_status"] == "PENDING_REVIEW"
    assert after1["approved_by_user_id"] is None

    repriced = reprice_item(s["item"]["id"])
    assert repriced["price_status"] == "PRICED_CURRENT"
    assert repriced["gross_charge_cents"] == 240000
    assert repriced["applied_price_rule_id"] == s["price_rule_2"]["id"]

    validate_error(
        api_client.charge_item_lifecycle(
            s["item"]["id"], {"action": "APPROVE", "note": "committee approval attempt 2"},
            APPROVER,
        ),
        ApiErrorId.ERR_AGGREGATE_MARKUP_LIMIT.value,
        422,
    )
    assert read_item(s["item"]["id"])["lifecycle_status"] == "PENDING_REVIEW"
    assert read_facility(s["facility"]["id"])["active_item_count"] == 0
