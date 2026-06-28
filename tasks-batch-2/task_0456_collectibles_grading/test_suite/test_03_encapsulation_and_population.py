"""Encapsulation: slab minting, the authentic-only label boundary, the
single-active-slab guard, the population census, the label snapshot, final-fee
divergence, and the auto-bubble to READY_TO_SHIP.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_encapsulate_payload, create_label_payload,
    make_customer_headers, TEST_USERS,
    setup_item_authenticated, setup_item_encapsulated, setup_item_intake_logged,
    carry_item_to_authenticated, encapsulate_item, get_population_bucket,
)


AUTH = TEST_USERS["authenticator_headers"]
LAB = TEST_USERS["lab_admin_headers"]


# ---------------------------------------------------------------------------
# Estimate equals final when declared value is within the tier cap
# ---------------------------------------------------------------------------
def test_estimate_equals_final_when_declared_within_cap(api):
    """PRD §3.8: "The final fee diverges from the estimate whenever the declared
    value exceeded the tier cap (final insurance is computed on the smaller capped
    value) or whenever the item was regraded (the surcharge applies)."

    Design: Difficulty/dual_variant_calc/insurance_estimate_vs_final_fee_diverge_over_tier_cap
    """
    # Declared 30000 is within the 50000 cap and never regraded: estimate and
    # final both insure 30000, so the two figures agree at 5600 — the converse of
    # the over-cap divergence case.
    customer, sl, gs, sub, item, ga, auth = setup_item_authenticated(
        declared_value_cents=30000, subgrades=(9, 9, 9, 9), email="c2b@x.com", title="Within",
    )
    cust_headers = make_customer_headers(customer["id"])
    pre = validate_success(api.get_item(item["id"], cust_headers))
    assert pre["estimated_fee_cents"] == 5600
    encapsulate_item(item["id"], ga["id"])
    post = validate_success(api.get_item(item["id"], cust_headers))
    assert post["final_fee_cents"] == 5600, "within-cap, unregraded item: final equals estimate"


# ---------------------------------------------------------------------------
# Authentic-only label boundary
# ---------------------------------------------------------------------------
def test_authentic_only_label_below_min_grade(api):
    """PRD §3.5: "If the verdict is `GENUINE` but the final overall is below
    `authentic_min_grade`, the item is gradeable-authentic without a number and the
    label reads "AUTHENTIC"."
    PRD §3.10: "when the item is authentic-only without a number, the bucket's
    `grade_value` is the sentinel -1, which denotes the AUTHENTIC-only bucket."

    Design: Corner/calculations/authentic_only_label_below_authentic_min_grade
    """
    # subgrades 0.5/0.5/0.5/0.5 -> final 0.5 < authentic_min 1.0 -> "AUTHENTIC".
    customer, sl, gs, sub, item, ga, auth = setup_item_authenticated(
        declared_value_cents=30000, subgrades=(0.5, 0.5, 0.5, 0.5), email="e13@x.com", title="W",
    )
    slab = encapsulate_item(item["id"], ga["id"])
    assert slab["label_grade_text"] == "AUTHENTIC", "below authentic_min must read AUTHENTIC"
    bucket = get_population_bucket(gs["id"], "W", -1)
    assert bucket is not None, "an AUTHENTIC-only (-1 sentinel) bucket must exist"
    assert bucket["pop_count"] == 1


# ---------------------------------------------------------------------------
# Single active slab per item
# ---------------------------------------------------------------------------
def test_single_active_slab_original_stays_active_after_blocked_second(api):
    """PRD §3.6: "because at most one active slab may exist per item, an
    encapsulation attempt on an item that already has an active slab is rejected
    with `ERR_ACTIVE_SLAB_EXISTS`."

    Design: Difficulty/resource_temporal_overlap/single_active_slab_per_item_blocks_second_encapsulation
    """
    customer, sl, gs, sub, item, ga, slab = setup_item_encapsulated(email="c15b@x.com", title="Card M2")
    api.encapsulate_item(item["id"], create_encapsulate_payload(ga["id"]), AUTH)
    original = validate_success(api.get_slab(slab["id"], AUTH))
    assert original["active"] is True, "the single existing slab must remain active and unchanged"


# ---------------------------------------------------------------------------
# Counterfeit cannot be encapsulated
# ---------------------------------------------------------------------------
def test_counterfeit_item_cannot_be_encapsulated(api):
    """PRD §3.6: "an item whose authentication verdict is `COUNTERFEIT` cannot be
    encapsulated as a graded slab and is rejected with
    `ERR_COUNTERFEIT_NOT_ENCAPSULATABLE`"

    Design: Corner/validations/counterfeit_cannot_be_encapsulated
    """
    customer, sl, gs, sub, item, ga, auth = setup_item_authenticated(
        verdict="COUNTERFEIT", alteration_note="fake holo", email="e16@x.com", title="Z",
    )
    resp = api.encapsulate_item(item["id"], create_encapsulate_payload(ga["id"]), AUTH)
    validate_error(resp, ApiErrorId.ERR_COUNTERFEIT_NOT_ENCAPSULATABLE.value)


def test_priority_state_beats_counterfeit_safety_check(api):
    """PRD §2.6: "then whether the target resource is in a valid state for the
    requested transition (`ERR_INVALID_STATE`)"
    PRD §2.6: "and finally the operation-specific business rules described
    throughout §2 and §3."
    PRD §3.6: "Encapsulation is permitted only on an item in `AUTHENTICATED` status
    that already has an authentication check"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_encapsulate_counterfeit_in_wrong_state
    """
    # Item only INTAKE_LOGGED then graded (status GRADING) — never authenticated.
    # The state check (P5) precedes the counterfeit safety check (P8), so an
    # encapsulate here returns ERR_INVALID_STATE, never the counterfeit error.
    customer, sl, gs, sub, item = setup_item_intake_logged(email="c9@x.com", title="Card H")
    from test_helpers import grade_item
    ga = grade_item(item["id"], gs["id"], 9, 9, 9, 9)
    resp = api.encapsulate_item(item["id"], create_encapsulate_payload(ga["id"]), AUTH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_encapsulate_wrong_state_does_not_mint_slab(api):
    """PRD §3.6: "Encapsulation is permitted only on an item in `AUTHENTICATED`
    status that already has an authentication check"
    PRD §2.6: "then whether the target resource is in a valid state for the
    requested transition (`ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_encapsulate_counterfeit_in_wrong_state
    """
    # Item in GRADING (graded, never authenticated). The state precondition fails
    # before any business-safety rule, so no slab is created and the item stays
    # in GRADING.
    from test_helpers import grade_item, make_customer_headers
    customer, sl, gs, sub, item = setup_item_intake_logged(email="c9b@x.com", title="Card H2")
    ga = grade_item(item["id"], gs["id"], 9, 9, 9, 9)
    resp = api.encapsulate_item(item["id"], create_encapsulate_payload(ga["id"]), AUTH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    cust_headers = make_customer_headers(customer["id"])
    after = validate_success(api.get_item(item["id"], cust_headers))
    assert after["status"] == "GRADING", "rejected encapsulate must leave item in GRADING"


# ---------------------------------------------------------------------------
# Bubble-up to READY_TO_SHIP + total_final_fee
# ---------------------------------------------------------------------------
def test_sole_item_encapsulated_bubbles_to_ready_to_ship(api):
    """PRD §3.6: "once every non-rejected item in the submission is `ENCAPSULATED`
    and no regrade request is still open, the submission moves `IN_GRADING →
    READY_TO_SHIP` and the submission's final fee total is computed"
    PRD §3.8: "When a submission reaches `READY_TO_SHIP`, the submission's
    `total_final_fee_cents` is computed as the sum of the `final_fee_cents` of only
    those items whose status is `ENCAPSULATED`"

    Design: Corner/state_machines/bubble_up_all_encapsulated_makes_submission_ready_to_ship
    """
    customer, sl, gs, sub, item, ga, auth = setup_item_authenticated(
        declared_value_cents=30000, email="e10@x.com", title="T",
    )
    encapsulate_item(item["id"], ga["id"])
    cust_headers = make_customer_headers(customer["id"])
    after = validate_success(api.get_submission(sub["id"], cust_headers))
    assert after["status"] == "READY_TO_SHIP"
    # final fee = 5000 + ceil(30000*200/10000)=600 + 0 surcharge -> 5600
    assert after["total_final_fee_cents"] == 5600


# ---------------------------------------------------------------------------
# Label snapshots population count
# ---------------------------------------------------------------------------
def test_label_snapshots_population_count(api):
    """PRD §3.6: "Printing a **label** records the slab through `slab_id` and the
    chosen population bucket through `population_report_id`, snapshots that
    bucket's `pop_count` at print time into `printed_pop_count` so the printed
    figure is immutable thereafter, and stamps `printed_at` from the logical
    clock."

    Design: Corner/endpoints/label_print_snapshots_population_count
    """
    customer, sl, gs, sub, item, ga, slab = setup_item_encapsulated(
        declared_value_cents=30000, subgrades=(9, 9, 9, 9), email="e18@x.com", title="AC",
    )
    bucket = get_population_bucket(gs["id"], "AC", 9.0)
    assert bucket is not None and bucket["pop_count"] == 1
    resp = api.print_label(slab["id"], create_label_payload(bucket["id"]), AUTH)
    label = validate_success(resp, expected_status=201)
    assert label["printed_pop_count"] == 1, "label must snapshot the current pop_count (1)"
