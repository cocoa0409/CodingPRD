"""Access-code batch pricing, the ledger debit and the void refund waterfall."""
from test_helpers import (
    ApiErrorId,
    assert_inventory_conservation,
    assert_provider_ledger_identity,
    create_access_code_batch_payload,
    create_void_payload,
    purchase_batch,
    setup_landscape,
    validate_error,
    validate_success,
)

TWO_LINE_MIXED = [
    {"bundle_type": "EXAM_ONLY", "quantity": 25},
    {"bundle_type": "COURSE_PLUS_EXAM", "quantity": 1},
]
VOID_TIER_BOUNDARY_LINES = [
    {"bundle_type": "EXAM_ONLY", "quantity": 11},
    {"bundle_type": "COURSE_PLUS_EXAM", "quantity": 1},
]


def _purchase(api, env, line_items):
    payload = create_access_code_batch_payload(
        env["provider"]["id"], env["exam_form"]["id"],
        line_items=line_items, expires_at="2027-06-30T00:00:00Z")
    return api.create_access_code_batch(payload, env["provider_headers"])


def test_batch_total_price_rounds_each_line_before_any_summation(api):
    """PRD §3.3: "The batch's `total_price_cents` is the sum, across all lines, of each line's rounded subtotal plus that line's rounded surcharge."
    PRD §3.3: "Rounding happens per line and per component before any summation; summing raw amounts first and rounding a single surcharge at the end produces a different total, differing by cents, and is not what this platform computes."

    Design: Difficulty/combinatorial_formula/batch_purchase_price_per_line_rounding_order_mode_b
    """
    env = setup_landscape()
    batch = validate_success(_purchase(api, env, TWO_LINE_MIXED), 201)
    assert batch["total_price_cents"] == 98649, (
        "line 1 is 85500 + 3848 and line 2 is 8900 + 401; the sum-then-round "
        f"reading 98648 is not the pinned order, got {batch['total_price_cents']}"
    )
    assert batch["total_price_cents"] != 98648


def test_batch_purchase_debits_the_provider_ledger_by_the_rounded_total(api):
    """PRD §3.3: "On success `total_price_cents` is added to `lifetime_charged_cents` and `credit_balance_cents` is recomputed."
    PRD §2.7: "`lifetime_charged_cents` accumulates every debit ever posted (batch purchases and certificate issuance fees), and `credit_balance_cents` is always exactly `lifetime_credited_cents` minus `lifetime_charged_cents`."

    Design: Difficulty/combinatorial_formula/batch_purchase_price_per_line_rounding_order_mode_b
    """
    env = setup_landscape()
    validate_success(_purchase(api, env, TWO_LINE_MIXED), 201)
    provider = validate_success(
        api.get_training_provider(env["provider"]["id"], env["provider_headers"]))
    assert provider["lifetime_charged_cents"] == 98649
    assert provider["lifetime_credited_cents"] == 500000
    assert provider["credit_balance_cents"] == 401351
    assert_provider_ledger_identity(provider)


def test_batch_mints_one_available_code_per_purchased_unit(api):
    """PRD §3.3: "The batch's `quantity_purchased` is the plain sum of the `quantity` values across all lines."
    PRD §3.3: "The batch opens with `available_count` equal to `quantity_purchased`, `assigned_count`, `consumed_count` and `voided_count` all at zero, `status` `ACTIVE`, and `void_gross_credit_cents`, `void_restock_fee_cents` and `void_net_credit_cents` all null."

    Design: Difficulty/combinatorial_formula/batch_purchase_price_per_line_rounding_order_mode_b
    """
    env = setup_landscape()
    batch = validate_success(_purchase(api, env, TWO_LINE_MIXED), 201)
    assert batch["quantity_purchased"] == 26
    assert batch["available_count"] == 26
    assert batch["assigned_count"] == 0
    assert batch["consumed_count"] == 0
    assert batch["voided_count"] == 0
    assert batch["status"] == "ACTIVE"
    assert batch["void_gross_credit_cents"] is None
    assert batch["void_restock_fee_cents"] is None
    assert batch["void_net_credit_cents"] is None
    assert_inventory_conservation(batch)


def test_void_restock_tier_is_keyed_on_the_gross_credit_not_the_net(api):
    """PRD §3.3: "Step three chooses the restock fee rate **from that gross credit, not from the net**: five percent when the gross credit is 50,000 cents (five hundred dollars) or more, otherwise ten percent when it is 10,000 cents (one hundred dollars) or more, otherwise fifteen percent."
    PRD §3.3: "Step four computes the retained fee as the gross credit multiplied by that rate, rounded half up to a whole number of cents, storing it in `void_restock_fee_cents`, and computes the net credit as the gross credit minus the retained fee, storing it in `void_net_credit_cents`."

    Design: Difficulty/combinatorial_formula/batch_void_refund_tier_keyed_on_gross_mode_c
    """
    env = setup_landscape()
    batch = validate_success(_purchase(api, env, VOID_TIER_BOUNDARY_LINES), 201)
    assert batch["total_price_cents"] == 50683
    assert batch["quantity_purchased"] == 12

    voided = validate_success(api.void_access_code_batch(
        batch["id"], create_void_payload(batch["version"],
                                        reason="Provider cancelled the training cohort"),
        env["provider_headers"]))
    assert voided["void_gross_credit_cents"] == 50683
    assert voided["void_restock_fee_cents"] == 2534, (
        "gross 50683 sits above the 50,000-cent boundary, so the five percent tier "
        f"applies, got {voided['void_restock_fee_cents']}"
    )
    assert voided["void_net_credit_cents"] == 48149
    assert voided["void_net_credit_cents"] != 45615


def test_void_credits_the_net_refund_and_voids_every_available_code(api):
    """PRD §3.3: "Both buckets post to the same ledger field, so the observable effect is that `lifetime_credited_cents` grows by exactly the net credit and `credit_balance_cents` is recomputed; the bucket split is what the audit trail records."
    PRD §3.3: "Every still-`AVAILABLE` child code moves `AVAILABLE → VOIDED`, the batch's `available_count` falls to zero while `voided_count` absorbs exactly the number of codes voided, the batch moves `ACTIVE → VOIDED`, and the batch's `version` increments by one."

    Design: Difficulty/combinatorial_formula/batch_void_refund_tier_keyed_on_gross_mode_c
    """
    env = setup_landscape()
    batch = validate_success(_purchase(api, env, VOID_TIER_BOUNDARY_LINES), 201)
    voided = validate_success(api.void_access_code_batch(
        batch["id"], create_void_payload(batch["version"]), env["provider_headers"]))

    assert voided["status"] == "VOIDED"
    assert voided["available_count"] == 0
    assert voided["voided_count"] == 12
    assert voided["version"] == batch["version"] + 1
    assert_inventory_conservation(voided)

    provider = validate_success(
        api.get_training_provider(env["provider"]["id"], env["provider_headers"]))
    assert provider["lifetime_credited_cents"] == 548149
    assert provider["lifetime_charged_cents"] == 50683
    assert provider["credit_balance_cents"] == 497466
    assert_provider_ledger_identity(provider)


def test_void_is_rejected_when_the_batch_version_is_stale(api):
    """PRD §2.6: "Voiding a batch is guarded by the same field and the same rejection code."
    PRD §2.6: "If that value does not equal the batch's current `version`, the assignment is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412)."

    Design: Difficulty/combinatorial_formula/batch_void_refund_tier_keyed_on_gross_mode_c
    """
    env = setup_landscape()
    batch = purchase_batch(env, line_items=VOID_TIER_BOUNDARY_LINES)
    resp = api.void_access_code_batch(
        batch["id"], create_void_payload(batch["version"] + 7), env["provider_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION.value)
