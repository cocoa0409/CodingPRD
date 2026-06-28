"""Sample receipt, the re-test cycle, kit-state dependencies, and slot overlap.

Covers queue A (non_linear_state_machine sample fork, cross_entity_state_dependency
sample/kit, resource_temporal_overlap kit slot) and queue B (validations re-test,
state_machines void kit).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    TEST_USERS,
    setup_received_sample,
    create_account,
    create_pet,
    create_kit,
    create_activated_kit,
)
from test_helpers.factories import (
    create_sample_payload,
    create_genotyping_run_payload,
    pass_run_payload,
)
from test_helpers.test_users import make_account_headers

LAB = TEST_USERS["lab_technician_headers"]


# =========================================================================
# non_linear_state_machine: sample fork QNS -> retest cycle (queue A)
# =========================================================================

def test_qns_run_yields_qns_score_and_outcome(api):
    """PRD §3.3: "otherwise, if the `qc_score` is below the QNS floor of 60.00
    the outcome is `QNS`"

    Design: Difficulty/non_linear_state_machine/sample_genotyping_fork_qns_then_retest_cycle
    """
    base = setup_received_sample(product_tier="BREED")
    resp = api.create_genotyping_run(
        base["sample"]["id"],
        create_genotyping_run_payload(call_rate=0.85, het_rate=0.0, contamination=0.9),
        LAB,
    )
    run = validate_success(resp, expected_status=201)
    assert run["qc_score"] == 54.00, f"expected qc 54.00, got {run['qc_score']}"
    assert run["outcome"] == "QNS", f"expected QNS, got {run['outcome']}"


def test_retest_marks_prior_retested_and_creates_received_successor(api):
    """PRD §3.3: "Creating the re-test marks the prior sample `RETESTED`
    (advancing it from `QNS` to `RETESTED`, or from `FAILED` to `RETESTED`) and
    creates a successor sample in `RECEIVED` on the same kit, incrementing the
    prior sample's `version`."

    Design: Difficulty/non_linear_state_machine/sample_genotyping_fork_qns_then_retest_cycle
    """
    base = setup_received_sample(product_tier="BREED")
    api.create_genotyping_run(
        base["sample"]["id"],
        create_genotyping_run_payload(call_rate=0.85, het_rate=0.0, contamination=0.9),
        LAB,
    )
    resp = api.create_sample(
        create_sample_payload(base["kit"]["id"], retest_of_sample_id=base["sample"]["id"]),
        LAB,
    )
    successor = validate_success(resp, expected_status=201)
    assert successor["status"] == "RECEIVED", \
        f"successor must be RECEIVED, got {successor['status']}"
    assert successor["retest_of_sample_id"] == base["sample"]["id"], \
        "successor must reference the prior sample"

    prior = validate_success(api.get_sample(base["sample"]["id"], LAB))
    assert prior["status"] == "RETESTED", f"prior must be RETESTED, got {prior['status']}"


# =========================================================================
# cross_entity_state_dependency: sample receipt requires kit ACTIVATED (queue A)
# =========================================================================

def test_sample_receipt_against_ordered_kit_rejected(api):
    """PRD §3.3: "Receiving a sample is done by supplying the `kit_id` of the
    activated kit; this is allowed only while the kit is `ACTIVATED`."
    PRD §2.8: "fifth, that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/sample_receipt_requires_kit_activated_state
    """
    account = create_account()
    pet = create_pet(account["id"])
    kit = create_kit(account["id"], product_tier="BREED")  # never activated -> ORDERED

    resp = api.create_sample(create_sample_payload(kit["id"]), LAB)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_sample_receipt_against_ordered_kit_leaves_kit_ordered(api):
    """PRD §3.2: "the kit enters the `ORDERED` state — its `status` being one of
    `ORDERED`, `ACTIVATED`, `RECEIVED`, `CONSUMED`, or `VOIDED`."
    PRD §3.3: "this is allowed only while the kit is `ACTIVATED`."

    Design: Difficulty/cross_entity_state_dependency/sample_receipt_requires_kit_activated_state
    """
    account = create_account()
    pet = create_pet(account["id"])
    kit = create_kit(account["id"], product_tier="BREED")

    api.create_sample(create_sample_payload(kit["id"]), LAB)
    fetched = validate_success(api.get_kit(kit["id"], LAB))
    assert fetched["status"] == "ORDERED", f"kit must stay ORDERED, got {fetched['status']}"


# =========================================================================
# resource_temporal_overlap: kit single non-terminal sample slot (queue A)
# =========================================================================

def test_second_sample_on_kit_with_live_sample_rejected(api):
    """PRD §3.3: "the same kit may not hold two non-terminal samples at once; a
    run requested against a sample in any other state, or a second live sample
    on the same kit, is rejected with `ERR_SAMPLE_NOT_GENOTYPABLE`."
    PRD §3.3: "this is allowed only while the kit is `ACTIVATED`."

    Design: Difficulty/resource_temporal_overlap/kit_single_non_terminal_sample_slot_overlap
    """
    base = setup_received_sample(product_tier="BREED")
    # First sample is RECEIVED; kit is now RECEIVED (not ACTIVATED). A second
    # receipt collides on the kit's genotyping slot.
    resp = api.create_sample(create_sample_payload(base["kit"]["id"]), LAB)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_SAMPLE_NOT_GENOTYPABLE.value],
    )


def test_kit_with_live_sample_second_receipt_does_not_create_sample(api):
    """PRD §3.3: "the same kit may not hold two non-terminal samples at once"

    Design: Difficulty/resource_temporal_overlap/kit_single_non_terminal_sample_slot_overlap
    """
    base = setup_received_sample(product_tier="BREED")
    api.create_sample(create_sample_payload(base["kit"]["id"]), LAB)
    samples = validate_success(api.list_samples(LAB, params={"kit_id": base["kit"]["id"]}))
    assert len(samples) == 1, f"kit must hold only one sample, got {len(samples)}"


# =========================================================================
# Corner: re-test eligibility & void invalid state
# =========================================================================

def test_retest_of_pass_sample_rejected(api):
    """PRD §3.3: "The referenced sample may only be one whose `status` is `QNS`
    or `FAILED`; pointing a re-test at a `PASS` or `RECEIVED` sample (or any
    other state) is rejected with `ERR_RETEST_NOT_ELIGIBLE`."

    Design: Corner/validations/retest_pass_sample_returns_not_eligible
    """
    base = setup_received_sample(product_tier="BREED")
    api.create_genotyping_run(base["sample"]["id"], pass_run_payload(), LAB)  # -> PASS

    resp = api.create_sample(
        create_sample_payload(base["kit"]["id"], retest_of_sample_id=base["sample"]["id"]),
        LAB,
    )
    validate_error(resp, ApiErrorId.ERR_RETEST_NOT_ELIGIBLE.value)


def test_void_activated_kit_rejected(api):
    """PRD §3.2: "only a kit still in `ORDERED` may be voided, and an attempt to
    void a kit in any other state is rejected as an invalid state transition with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/void_activated_kit_returns_invalid_state
    """
    account = create_account()
    pet = create_pet(account["id"])
    kit = create_activated_kit(account["id"], pet["id"], product_tier="BREED")

    resp = api.void_kit(kit["id"], make_account_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    fetched = validate_success(api.get_kit(kit["id"], make_account_headers(account["id"])))
    assert fetched["status"] == "ACTIVATED", f"kit must stay ACTIVATED, got {fetched['status']}"
