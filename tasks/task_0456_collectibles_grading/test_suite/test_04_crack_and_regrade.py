"""Crack-and-regrade: the cyclic state machine, the crack cascade
(slab/assessment/population/version), optimistic concurrency on item version,
the regrade surcharge, population conservation, and the shipped lockdown.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_regrade_request_payload,
    make_customer_headers, TEST_USERS,
    setup_item_encapsulated, setup_item_cracked, setup_item_regraded_and_reencapsulated,
    setup_ready_to_ship,
    grade_item, finalize_assessment, authenticate_item, encapsulate_item,
    get_item_version, open_regrade_request, get_population_bucket, create_shipment,
)


GRADER = TEST_USERS["grader_headers"]
AUTH = TEST_USERS["authenticator_headers"]
LAB = TEST_USERS["lab_admin_headers"]


# ---------------------------------------------------------------------------
# Cyclic crack-and-regrade loop
# ---------------------------------------------------------------------------
def test_regrade_returns_item_to_grading_and_increments_count(api):
    """PRD §3.7: "Creating that new assessment advances the item `CRACK_PENDING →
    GRADING`, computes a fresh `provisional_overall`, sets the regrade request's
    status to `COMPLETED`, and increments the item's `regrade_count` by one."

    Design: Difficulty/non_linear_state_machine/submission_item_cyclic_crack_and_regrade_loop
    """
    customer, sl, gs, sub, item, ga1, slab1, rr = setup_item_cracked(
        subgrades=(7, 8, 8, 8), email="c5@x.com", title="Card D",
    )
    # CRACK_PENDING -> GRADING via a fresh assessment.
    ga2 = grade_item(item["id"], gs["id"], 9, 9, 9, 9)
    cust_headers = make_customer_headers(customer["id"])
    after = validate_success(api.get_item(item["id"], cust_headers))
    assert after["status"] == "GRADING", "item must return to GRADING after regrade re-entry"
    assert after["regrade_count"] == 1, "regrade_count must increment to 1"


def test_regrade_request_marks_item_crack_pending(api):
    """PRD §3.7: "When the request is accepted, the item advances `ENCAPSULATED →
    CRACK_PENDING` and a cascade fires."

    Design: Difficulty/non_linear_state_machine/submission_item_cyclic_crack_and_regrade_loop
    """
    customer, sl, gs, sub, item, ga1, slab1, rr = setup_item_cracked(email="c5b@x.com", title="Card D2")
    cust_headers = make_customer_headers(customer["id"])
    after = validate_success(api.get_item(item["id"], cust_headers))
    assert after["status"] == "CRACK_PENDING"


# ---------------------------------------------------------------------------
# Crack cascade: slab inactive, assessment superseded, item CRACK_PENDING
# ---------------------------------------------------------------------------
def test_crack_cascade_deactivates_slab_and_supersedes_assessment(api):
    """PRD §3.7: "the prior slab is marked cracked by setting its `active` flag to
    false, and the request transitions to `CRACKED`."
    PRD §3.7: "The item's previously active grade assessment is marked superseded
    by setting its `superseded` flag to true."

    Design: Difficulty/transitive_cascade/crack_cascade_slab_assessment_population_version
    """
    customer, sl, gs, sub, item, ga1, slab1, rr = setup_item_cracked(email="c7@x.com", title="Card F")
    slab_after = validate_success(api.get_slab(slab1["id"], AUTH))
    assert slab_after["active"] is False, "cracked slab must be active=false"
    ga_after = validate_success(api.get_grade_assessment(ga1["id"], GRADER))
    assert ga_after["superseded"] is True, "prior assessment must be superseded=true"
    cust_headers = make_customer_headers(customer["id"])
    item_after = validate_success(api.get_item(item["id"], cust_headers))
    assert item_after["status"] == "CRACK_PENDING"


def test_crack_decrements_population_bucket(api):
    """PRD §3.7: "The population census bucket that counted the cracked slab is
    decremented by one (see §3.10)."
    PRD §3.10: "On crack, the system finds the bucket the cracked slab was counted
    in"
    PRD §3.10: "and decrements its `pop_count` by one; a count never falls below
    zero."

    Design: Difficulty/transitive_cascade/crack_cascade_slab_assessment_population_version
    """
    # Encapsulated at 9/9/9/9 -> bucket grade 9.0 pop 1; crack decrements to 0.
    customer, sl, gs, sub, item, ga1, slab1, rr = setup_item_cracked(
        subgrades=(9, 9, 9, 9), email="c7b@x.com", title="Card F2",
    )
    bucket = get_population_bucket(gs["id"], "Card F2", 9.0)
    assert bucket is not None and bucket["pop_count"] == 0, "crack must decrement the bucket to 0"


# ---------------------------------------------------------------------------
# Optimistic concurrency on item version
# ---------------------------------------------------------------------------
def test_regrade_with_current_version_succeeds_and_advances_state(api):
    """PRD §2.8: "Opening a regrade request against a submission item must carry
    `expected_item_version`, a non-optional field whose value is the `version` of
    the target `SubmissionItem` that the client last observed. The server compares
    `expected_item_version` against that item's current `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_regrade_succeeds_and_bumps_version
    """
    customer, sl, gs, sub, item, ga, slab = setup_item_encapsulated(email="e24@x.com", title="AI")
    item_v = get_item_version(item["id"], customer["id"])
    cust_headers = make_customer_headers(customer["id"])
    resp = api.create_regrade_request(
        item["id"], create_regrade_request_payload(slab["id"], item_v, reason="ok"), cust_headers,
    )
    validate_success(resp, expected_status=201)
    after = validate_success(api.get_item(item["id"], cust_headers))
    assert after["status"] == "CRACK_PENDING"


def test_regrade_with_stale_version_rejected_412(api):
    """PRD §2.8: "If another writer has already opened a regrade request against
    the same item — cracking its active slab and advancing the item's `version` —
    the value the current client holds is stale and no longer matches, so the
    request is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_item_version_on_regrade_returns_412
    """
    customer, sl, gs, sub, item, ga, slab = setup_item_encapsulated(email="e21@x.com", title="AF")
    item_v = get_item_version(item["id"], customer["id"])
    cust_headers = make_customer_headers(customer["id"])
    # Carry a version one below the current value -> stale.
    resp = api.create_regrade_request(
        item["id"], create_regrade_request_payload(slab["id"], item_v - 1, reason="stale"), cust_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ITEM_VERSION.value)


# ---------------------------------------------------------------------------
# Regrade surcharge on final fee
# ---------------------------------------------------------------------------
def test_regrade_surcharge_added_to_final_fee(api):
    """PRD §3.8: "The regrade surcharge is the item's `regrade_count` multiplied by
    1500 cents per completed regrade cycle. The final fee therefore equals base
    plus final insurance plus surcharge."

    Design: Corner/calculations/regrade_surcharge_added_to_final_fee
    """
    # 30000 @ EXPRESS, one regrade: final = 5000 + ceil(30000*200/10000)=600 + 1*1500 = 7100.
    customer, sl, gs, sub, item, slab1, ga2, slab2 = setup_item_regraded_and_reencapsulated(
        declared_value_cents=30000, email="e14@x.com", title="X",
    )
    cust_headers = make_customer_headers(customer["id"])
    after = validate_success(api.get_item(item["id"], cust_headers))
    assert after["regrade_count"] == 1
    assert after["final_fee_cents"] == 7100, "final fee must include the 1500 regrade surcharge"


# ---------------------------------------------------------------------------
# Population conservation across a full crack-and-regrade cycle
# ---------------------------------------------------------------------------
def test_crack_regrade_same_grade_conserves_population_net_zero(api):
    """PRD §3.10: "Sealing an item into a slab increments exactly one bucket by
    one; cracking that slab in a regrade decrements exactly that same bucket by
    one."
    PRD §2.10: "the net effect across a full crack-and-regrade cycle is zero only
    once the item has been re-sealed."

    Design: Difficulty/compensating_invariant/crack_regrade_conserves_population_count_net_zero
    """
    # Encapsulate at 9.0 (pop 1), crack (0), regrade to same 9.0, re-encapsulate (1).
    customer, sl, gs, sub, item, slab1, ga2, slab2 = setup_item_regraded_and_reencapsulated(
        first_subgrades=(9, 9, 9, 9), second_subgrades=(9, 9, 9, 9), email="c18@x.com", title="Card P",
    )
    bucket = get_population_bucket(gs["id"], "Card P", 9.0)
    assert bucket is not None and bucket["pop_count"] == 1, "net population must be 1 after re-seal"
    slab2_after = validate_success(api.get_slab(slab2["id"], AUTH))
    assert slab2_after["active"] is True, "the re-encapsulated slab must be active"


def test_crack_regrade_repopulates_active_slab_count(api):
    """PRD §3.10: "Each bucket's `pop_count` counts the active, non-cracked slabs
    in it."

    Design: Difficulty/compensating_invariant/crack_regrade_conserves_population_count_net_zero
    """
    customer, sl, gs, sub, item, slab1, ga2, slab2 = setup_item_regraded_and_reencapsulated(
        first_subgrades=(9, 9, 9, 9), second_subgrades=(9, 9, 9, 9), email="c18b@x.com", title="Card P2",
    )
    slab1_after = validate_success(api.get_slab(slab1["id"], AUTH))
    assert slab1_after["active"] is False, "the original cracked slab stays inactive"
    bucket = get_population_bucket(gs["id"], "Card P2", 9.0)
    assert bucket["pop_count"] == 1, "only the active re-encapsulated slab counts"


