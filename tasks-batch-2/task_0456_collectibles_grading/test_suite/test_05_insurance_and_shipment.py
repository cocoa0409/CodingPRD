"""Insurance coverage and premium, intake-driven coverage recompute, shipment
dispatch precondition, the lost-shipment compensation cascade, and the
store-credit conservation invariant.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_shipment_payload,
    make_customer_headers, TEST_USERS,
    setup_submitted_submission, setup_item_intake_logged, setup_item_encapsulated,
    setup_shipment_in_transit, setup_multi_item_shipment_in_transit,
    log_intake, carry_item_to_encapsulated,
    get_insurance_policy, create_shipment,
)


LAB = TEST_USERS["lab_admin_headers"]
RECEIVER = TEST_USERS["receiver_headers"]


# ---------------------------------------------------------------------------
# Coverage and premium at submit
# ---------------------------------------------------------------------------
def test_covered_value_and_premium_sum_then_ceil(api):
    """PRD §3.9: "The policy's `covered_value_cents` is the sum, over every item
    whose status is not `REJECTED_RETURNED`, of that item's declared value capped at
    the tier's `max_declared_value_cents`"
    PRD §3.9: "The policy's `premium_cents` is computed by multiplying the aggregate
    `covered_value_cents` by the tier's `insurance_rate_bps`, dividing by 10000, and
    rounding the single aggregate result up to the next whole cent (ceiling)."

    Design: Corner/calculations/covered_value_premium_sum_then_ceil
    """
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[
            {"declared_value_cents": 30000, "title": "U1"},
            {"declared_value_cents": 30000, "title": "U2"},
        ],
        email="e11@x.com",
    )
    policy = get_insurance_policy(sub["id"], customer["id"])
    assert policy["covered_value_cents"] == 60000, "two 30000 items -> covered 60000"
    # premium = ceil(60000 * 200 / 10000) = 1200
    assert policy["premium_cents"] == 1200, "sum-then-ceil premium must be 1200"


# ---------------------------------------------------------------------------
# Reject recomputes coverage
# ---------------------------------------------------------------------------
def test_reject_item_recomputes_coverage_to_exclude_it(api):
    """PRD §3.3: "A rejected item advances `INTAKE_LOGGED → REJECTED_RETURNED`: it
    is excluded from grading and from insurance coverage, the submission's
    insurance covered value is recomputed to drop it (see §3.9)"
    PRD §3.9: "When an item is rejected at intake, the policy's covered value is
    recomputed to exclude it."

    Design: Corner/state_machines/reject_item_recomputes_coverage_and_excludes_value
    """
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[
            {"declared_value_cents": 30000, "title": "R1"},
            {"declared_value_cents": 30000, "title": "R2"},
        ],
        email="e8@x.com",
    )
    item1, item2 = items
    log_intake(item1["id"], matches_declaration=True)
    log_intake(item2["id"], matches_declaration=False)
    resp = api.reject_item(item2["id"], RECEIVER)
    rejected = validate_success(resp)
    assert rejected["status"] == "REJECTED_RETURNED"
    policy = get_insurance_policy(sub["id"], customer["id"])
    assert policy["covered_value_cents"] == 30000, "rejected item must be dropped from coverage"


# ---------------------------------------------------------------------------
# Dispatch / shipment-create precondition: submission must be READY_TO_SHIP
# ---------------------------------------------------------------------------
def test_shipment_create_blocked_when_submission_in_grading(api):
    """PRD §3.11: "Creating a shipment requires the parent submission to be
    `READY_TO_SHIP`."
    PRD §2.6: "then whether the target resource is in a valid state for the
    requested transition (`ERR_INVALID_STATE`)"

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_submission_ready_to_ship
    """
    # Two items: item1 carried to ENCAPSULATED, item2 only INTAKE_LOGGED ->
    # submission posture is IN_GRADING, so no shipment may be created yet.
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[
            {"declared_value_cents": 30000, "title": "Card K1"},
            {"declared_value_cents": 30000, "title": "Card K2"},
        ],
        email="c13@x.com",
    )
    item1, item2 = items
    log_intake(item1["id"], matches_declaration=True)
    log_intake(item2["id"], matches_declaration=True)
    carry_item_to_encapsulated(item1["id"], gs["id"], subgrades=(9, 9, 9, 9))
    cust_headers = make_customer_headers(customer["id"])
    sub_now = validate_success(api.get_submission(sub["id"], cust_headers))
    assert sub_now["status"] == "IN_GRADING", "with one item un-encapsulated posture stays IN_GRADING"
    resp = api.create_shipment(sub["id"], create_shipment_payload(carrier="UPS", tracking_number="1Z111"), LAB)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_shipment_create_allowed_once_submission_ready_to_ship(api):
    """PRD §3.11: "When a submission is `READY_TO_SHIP`, a `LabAdmin` creates a
    **return shipment** for it"
    PRD §3.11: "Creating a shipment requires the parent submission to be
    `READY_TO_SHIP`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_submission_ready_to_ship
    """
    # Both items encapsulated -> submission READY_TO_SHIP -> shipment create allowed.
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[
            {"declared_value_cents": 30000, "title": "K1b"},
            {"declared_value_cents": 30000, "title": "K2b"},
        ],
        email="c13b@x.com",
    )
    # PRD §3.3: intake is permitted only while the submission is SUBMITTED/RECEIVING.
    # Log intake on every item first (before any item advances the posture to
    # IN_GRADING), then carry each to ENCAPSULATED.
    for it in items:
        log_intake(it["id"], matches_declaration=True)
    for it in items:
        carry_item_to_encapsulated(it["id"], gs["id"], subgrades=(9, 9, 9, 9))
    cust_headers = make_customer_headers(customer["id"])
    sub_now = validate_success(api.get_submission(sub["id"], cust_headers))
    assert sub_now["status"] == "READY_TO_SHIP"
    resp = api.create_shipment(sub["id"], create_shipment_payload(carrier="UPS", tracking_number="1Z222"), LAB)
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Lost-shipment compensation cascade
# ---------------------------------------------------------------------------
def test_report_lost_files_pays_claim_and_credits_store_credit(api):
    """PRD §3.9: "If a dispatched shipment is reported lost, the policy's
    `claim_status` first moves to `FILED`, then the payout is computed as exactly
    the policy's `covered_value_cents`, that amount is recorded in `payout_cents`,
    the `claim_status` advances to `PAID`, and the customer's wallet
    `store_credit_cents` is increased by exactly that payout."

    Design: Difficulty/transitive_cascade/lost_shipment_cascade_claim_payout_store_credit
    """
    # PRD §3.2 forbids submitting an item whose declared value exceeds the tier cap
    # (ERR_DECLARED_VALUE_EXCEEDS_TIER), so the over-cap path is unreachable. A
    # within-cap item of 50000 (cap is inclusive) yields covered 50000 -> payout 50000.
    customer, sl, gs, sub, item, ship = setup_shipment_in_transit(
        declared_value_cents=50000, carrier="UPS", tracking_number="1Z999", email="c8@x.com",
    )
    resp = api.report_lost_shipment(ship["id"], LAB)
    ship_after = validate_success(resp)
    assert ship_after["status"] == "LOST"
    cust = validate_success(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
    assert cust["store_credit_cents"] == 50000, "store credit must be credited by the covered value 50000"


def test_report_lost_sets_policy_claim_paid_with_payout(api):
    """PRD §3.9: "the policy's `claim_status` first moves to `FILED`, then the
    payout is computed as exactly the policy's `covered_value_cents`, that amount
    is recorded in `payout_cents`, the `claim_status` advances to `PAID`"

    Design: Difficulty/transitive_cascade/lost_shipment_cascade_claim_payout_store_credit
    """
    # Within-cap item of 50000 (PRD §3.2 forbids over-cap submission) -> covered 50000.
    customer, sl, gs, sub, item, ship = setup_shipment_in_transit(
        declared_value_cents=50000, carrier="UPS", tracking_number="1Z998", email="c8b@x.com",
    )
    validate_success(api.report_lost_shipment(ship["id"], LAB))
    policy = get_insurance_policy(sub["id"], customer["id"])
    assert policy["claim_status"] == "PAID", "claim must advance to PAID after a reported loss"
    assert policy["payout_cents"] == 50000, "payout must equal the covered value (50000)"


def test_lost_payout_conserves_store_credit_equals_covered(api):
    """PRD §3.9: "The invariant is strict: the customer's `store_credit_cents` rises
    by exactly the policy's `covered_value_cents` — no more and no less."

    Design: Difficulty/compensating_invariant/lost_shipment_payout_conserves_store_credit_equals_covered
    """
    # Two within-cap items 50000+30000 -> covered 80000 -> credit delta 80000.
    # (PRD §3.2 forbids submitting an item whose declared value exceeds the cap.)
    customer, sl, gs, sub, items, ship = setup_multi_item_shipment_in_transit(
        item_specs=[
            {"declared_value_cents": 50000, "title": "Card O1"},
            {"declared_value_cents": 30000, "title": "Card O2"},
        ],
        carrier="FEDEX", tracking_number="FX222", email="c17@x.com",
    )
    policy = get_insurance_policy(sub["id"], customer["id"])
    assert policy["covered_value_cents"] == 80000
    validate_success(api.report_lost_shipment(ship["id"], LAB))
    cust = validate_success(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
    assert cust["store_credit_cents"] == 80000, "credit delta must equal covered value exactly"


def test_lost_payout_amount_equals_covered_value_on_policy(api):
    """PRD §3.9: "the payout is computed as exactly the policy's
    `covered_value_cents`, that amount is recorded in `payout_cents`"

    Design: Difficulty/compensating_invariant/lost_shipment_payout_conserves_store_credit_equals_covered
    """
    # Two within-cap items 50000+30000 -> covered 80000; the payout recorded on the
    # policy must equal that covered value exactly (no over/under-payment drift).
    # (PRD §3.2 forbids submitting an item whose declared value exceeds the cap.)
    customer, sl, gs, sub, items, ship = setup_multi_item_shipment_in_transit(
        item_specs=[
            {"declared_value_cents": 50000, "title": "Card Q1"},
            {"declared_value_cents": 30000, "title": "Card Q2"},
        ],
        carrier="FEDEX", tracking_number="FX223", email="c17b@x.com",
    )
    validate_success(api.report_lost_shipment(ship["id"], LAB))
    policy = get_insurance_policy(sub["id"], customer["id"])
    assert policy["payout_cents"] == policy["covered_value_cents"] == 80000, (
        "payout_cents must equal covered_value_cents exactly"
    )
