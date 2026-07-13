"""Lost-and-damage claims: the approval cascade across claim, media item,
order, and customer; the payment-captured precondition; the payout policy;
and the money/item-count conservation invariants."""
from test_helpers import (
    ApiErrorId, validate_error, validate_success,
    create_customer, create_order, authorize_payment, capture_payment,
    receive_order, create_bin, create_machine, create_batch, log_media_item,
    load_item, run_batch, complete_scan, qc_pass, file_claim, approve_claim,
    get_order_admin, get_item_admin, get_customer_admin,
    assert_refund_conserves_cents, TEST_USERS, make_customer_headers,
    setup_ready_order,
)


# ===========================================================================
# transitive_cascade / claim_approval_writeoff_refund_wallet_depth3
# ===========================================================================
def test_claim_approval_writeoff_refund_and_wallet_cascade(api):
    """PRD §3.7: "The affected media item is written off, advancing it to
    `WRITTEN_OFF`, and the owning order's `written_off_count` is increased by
    one."
    PRD §3.7: "The order's `refunded_total_cents` is increased by the payout, the
    order's `payment_status` advances from `CAPTURED` to `PARTIALLY_REFUNDED`,
    and the order's `final_total_cents` is recomputed as the **final** variant of
    the order total."
    PRD §3.7: "The owning customer's `wallet_credit_cents` is increased by the
    payout, the customer's `approved_claim_count` increases by one as the claim
    joins the approved set (and it correspondingly leaves the pending set), and
    the customer's `risk_score` is recomputed."
    PRD §3.7: "When the owning order's `lost_damage_protection` was purchased, the
    payout honors the declared value up to a cap of 10000 cents — that is, the
    smaller of the declared value and 10000 cents."

    Protection order, tape item, declared value omitted -> declared defaults to
    the tape base 4000; payout min(4000, 10000) = 4000 flows through all links.

    Design: Difficulty/transitive_cascade/claim_approval_writeoff_refund_wallet_depth3
    """
    ready = setup_ready_order(api, items=("TAPE",), declared={"declared_tape_count": 3},
                              protection=True, capture=True, customer_email="tc-c1@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="LOST")
    approve_claim(api, claim["id"])
    item = get_item_admin(api, ready["item_ids"][0])
    order = get_order_admin(api, ready["order_id"])
    customer = get_customer_admin(api, ready["customer_id"])
    assert item["status"] == "WRITTEN_OFF", item
    assert order["refunded_total_cents"] == 4000, order
    assert order["payment_status"] == "PARTIALLY_REFUNDED", order
    assert customer["wallet_credit_cents"] == 4000, customer


def test_claim_approval_sets_payout_and_approved_count(api):
    """PRD §3.7: "The claim's `payout_cents` is computed by policy (below), and
    the claim advances from `SUBMITTED` to `APPROVED`."
    PRD §3.7: "The customer's `approved_claim_count` is the number of that
    customer's claims in `APPROVED` status, and the `pending_claim_count` is the
    number in `SUBMITTED` or `UNDER_REVIEW` status."
    PRD §3.7: "When the owning order's `lost_damage_protection` was purchased, the
    payout honors the declared value up to a cap of 10000 cents — that is, the
    smaller of the declared value and 10000 cents."

    Design: Difficulty/transitive_cascade/claim_approval_writeoff_refund_wallet_depth3
    """
    ready = setup_ready_order(api, items=("TAPE",), declared={"declared_tape_count": 3},
                              protection=True, capture=True, customer_email="tc-c2@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="LOST")
    reviewed = approve_claim(api, claim["id"])
    assert reviewed["status"] == "APPROVED", reviewed
    assert reviewed["payout_cents"] == 4000, reviewed
    customer = get_customer_admin(api, ready["customer_id"])
    assert customer["approved_claim_count"] == 1, customer


# ===========================================================================
# cross_entity_state_dependency / claim_approve_requires_order_captured
# ===========================================================================
def test_claim_approval_blocked_when_order_not_captured(api):
    """PRD §3.7: "Approval is permitted only when the claim is `SUBMITTED` and the
    owning order's `payment_status` is `CAPTURED`; if the order's payment is not
    captured, approval is rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 402)."

    The order is authorized but never captured, so approving its claim is
    refused.

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_order_captured
    """
    ready = setup_ready_order(api, items=("TAPE",), capture=False,
                              customer_email="ce-cap1@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="LOST")
    resp = api.review_claim(claim["id"], {"decision": "APPROVE"}, TEST_USERS["claims_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED)


def test_claim_approval_succeeds_once_order_captured(api):
    """PRD §3.7: "Approval is permitted only when the claim is `SUBMITTED` and the
    owning order's `payment_status` is `CAPTURED`; if the order's payment is not
    captured, approval is rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 402)."
    PRD §3.7: "The claim's `payout_cents` is computed by policy (below), and the
    claim advances from `SUBMITTED` to `APPROVED`."

    Capturing the authorized payment satisfies the precondition, so the same
    approval now succeeds.

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_order_captured
    """
    ready = setup_ready_order(api, items=("TAPE",), capture=False,
                              customer_email="ce-cap2@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="LOST")
    capture_payment(api, ready["order_id"])
    reviewed = approve_claim(api, claim["id"])
    assert reviewed["status"] == "APPROVED", reviewed


# ===========================================================================
# compensating_invariant / claim_refund_conserves_cents
# ===========================================================================
def test_claim_payout_conserves_cents_tape(api):
    """PRD §3.7: "The order's `refunded_total_cents` is increased by the payout,
    the order's `payment_status` advances from `CAPTURED` to
    `PARTIALLY_REFUNDED`, and the order's `final_total_cents` is recomputed as
    the **final** variant of the order total."
    PRD §3.7: "The owning customer's `wallet_credit_cents` is increased by the
    payout, the customer's `approved_claim_count` increases by one as the claim
    joins the approved set (and it correspondingly leaves the pending set), and
    the customer's `risk_score` is recomputed."

    The single payout is conserved: wallet credit == order refund == payout.

    Design: Difficulty/compensating_invariant/claim_refund_conserves_cents
    """
    ready = setup_ready_order(api, items=("TAPE",), declared={"declared_tape_count": 3},
                              protection=True, capture=True, customer_email="ci-c1@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="LOST")
    reviewed = approve_claim(api, claim["id"])
    order = get_order_admin(api, ready["order_id"])
    customer = get_customer_admin(api, ready["customer_id"])
    assert reviewed["payout_cents"] == 4000, reviewed
    assert_refund_conserves_cents(
        reviewed["payout_cents"], order["refunded_total_cents"],
        customer["wallet_credit_cents"],
    )


def test_claim_payout_conserves_cents_film_declared(api):
    """PRD §3.7: "The order's `refunded_total_cents` is increased by the payout,
    the order's `payment_status` advances from `CAPTURED` to
    `PARTIALLY_REFUNDED`, and the order's `final_total_cents` is recomputed as
    the **final** variant of the order total."
    PRD §3.7: "The owning customer's `wallet_credit_cents` is increased by the
    payout, the customer's `approved_claim_count` increases by one as the claim
    joins the approved set (and it correspondingly leaves the pending set), and
    the customer's `risk_score` is recomputed."
    PRD §3.7: "When the owning order's `lost_damage_protection` was purchased, the
    payout honors the declared value up to a cap of 10000 cents — that is, the
    smaller of the declared value and 10000 cents."

    A film claim declaring 5000 (under the 10000 cap) pays 5000, conserved
    equally into wallet and refund.

    Design: Difficulty/compensating_invariant/claim_refund_conserves_cents
    """
    ready = setup_ready_order(api, items=("FILM",), protection=True, capture=True,
                              customer_email="ci-c2@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="DAMAGED", declared_value_cents=5000)
    reviewed = approve_claim(api, claim["id"])
    order = get_order_admin(api, ready["order_id"])
    customer = get_customer_admin(api, ready["customer_id"])
    assert reviewed["payout_cents"] == 5000, reviewed
    assert_refund_conserves_cents(
        reviewed["payout_cents"], order["refunded_total_cents"],
        customer["wallet_credit_cents"],
    )


# ===========================================================================
# compensating_invariant / writeoff_conserves_item_count
# ===========================================================================
def test_writeoff_preserves_received_count_and_marks_item(api):
    """PRD §3.7: "The affected media item is written off, advancing it to
    `WRITTEN_OFF`, and the owning order's `written_off_count` is increased by
    one."
    PRD §3.3: "Logging an item increments the owning order's
    `received_item_count` by one and increments the order's `version`."

    Two items received (received_item_count 2); writing one off leaves
    received_item_count at 2 and written_off_count at 1.

    Design: Difficulty/compensating_invariant/writeoff_conserves_item_count
    """
    ready = setup_ready_order(api, items=("TAPE", "TAPE"), protection=True, capture=True,
                              customer_email="ci-w1@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="DAMAGED")
    approve_claim(api, claim["id"])
    order = get_order_admin(api, ready["order_id"])
    assert order["received_item_count"] == 2, order
    assert order["written_off_count"] == 1, order
    assert get_item_admin(api, ready["item_ids"][0])["status"] == "WRITTEN_OFF"


def test_writeoff_leaves_surviving_item_untouched(api):
    """PRD §3.7: "The affected media item is written off, advancing it to
    `WRITTEN_OFF`, and the owning order's `written_off_count` is increased by
    one."
    PRD §3.3: "Logging an item increments the owning order's
    `received_item_count` by one and increments the order's `version`."

    Writing off one of two items conserves the total: received stays 2, one item
    is WRITTEN_OFF, and the other survives at OUTPUT_READY (2 == 1 active + 1
    written off).

    Design: Difficulty/compensating_invariant/writeoff_conserves_item_count
    """
    ready = setup_ready_order(api, items=("TAPE", "TAPE"), protection=True, capture=True,
                              customer_email="ci-w2@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="DAMAGED")
    approve_claim(api, claim["id"])
    order = get_order_admin(api, ready["order_id"])
    assert order["received_item_count"] == 2, order
    assert order["written_off_count"] == 1, order
    assert get_item_admin(api, ready["item_ids"][1])["status"] == "OUTPUT_READY"


# ===========================================================================
# calculations / damage_payout_no_protection_limited_liability (corner)
# ===========================================================================
def test_payout_no_protection_limited_to_thousand(api):
    """PRD §3.7: "When protection was not purchased, liability is limited and the
    declared value is ignored: the payout is the smaller of the item's base
    value and 1000 cents."

    A tape claim on an unprotected order, declaring 5000, pays min(4000, 1000) =
    1000 (declared value ignored).

    Design: Corner/calculations/damage_payout_no_protection_limited_liability
    """
    ready = setup_ready_order(api, items=("TAPE",), protection=False, capture=True,
                              customer_email="np@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="DAMAGED", declared_value_cents=5000)
    reviewed = approve_claim(api, claim["id"])
    assert reviewed["payout_cents"] == 1000, reviewed


# ===========================================================================
# calculations / damage_payout_protection_honors_declared_to_cap (corner)
# ===========================================================================
def test_payout_with_protection_honors_declared_up_to_cap(api):
    """PRD §3.7: "When the owning order's `lost_damage_protection` was purchased,
    the payout honors the declared value up to a cap of 10000 cents — that is,
    the smaller of the declared value and 10000 cents."

    A film claim declaring 20000 on a protected order pays min(20000, 10000) =
    10000.

    Design: Corner/calculations/damage_payout_protection_honors_declared_to_cap
    """
    ready = setup_ready_order(api, items=("FILM",), protection=True, capture=True,
                              customer_email="pp@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="LOST", declared_value_cents=20000)
    reviewed = approve_claim(api, claim["id"])
    assert reviewed["payout_cents"] == 10000, reviewed
