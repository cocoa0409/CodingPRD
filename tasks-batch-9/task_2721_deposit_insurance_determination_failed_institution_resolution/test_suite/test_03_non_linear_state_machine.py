"""Lifecycles that are not straight lines.

A determination can be sent back and re-prepared any number of times, so its row
visits `PREPARED` and `UNDER_REVIEW` repeatedly and only the last preparation's
figures survive certification.  A deposit account carries three dimensions that
each move under their own triggers, so releasing one account's hold must leave its
sibling, its own other dimensions and its claim exactly where they were.
"""
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_certificate,
    assert_determination_amounts,
    assert_fields_equal,
)

LOOP_ONE_REASON = "Loop 1: verify the provisional per-account read"
LOOP_TWO_REASON = "Loop 2: revert to the statutory aggregate method"


def _dana_estate(client):
    return X.pooled_estate(
        client,
        cert_number="34569",
        legal_name="Olympic Peninsula Bank",
        depositor_name="Dana Whitfield",
    )


# ---------------------------------------------------------------------------
# The revision cycle: PREPARED -> UNDER_REVIEW -> REVISION_REQUESTED -> PREPARED
# ---------------------------------------------------------------------------
def test_two_revision_loops_leave_revision_round_at_two(client):
    """Each send-back increments `revision_round` and the re-prepare that closes the
    loop does not, so two completed loops read 2.

    PRD: "The document may therefore loop `PREPARED` → `UNDER_REVIEW` → `REVISION_REQUESTED` → `PREPARED` any number of times, with `revision_round` counting the completed loops."

    Design: Difficulty/non_linear_state_machine/determination_two_revision_loops_then_certify_last_prepare_wins
    """
    estate = _dana_estate(client)
    determination = X.determination_under_review(client, estate["depositor"]["id"])
    determination_id = determination["id"]
    assert determination["revision_round"] == 0

    sent_back = X.request_revision(client, determination_id, revision_reason=LOOP_ONE_REASON)
    assert_fields_equal(
        sent_back,
        {
            "status": "REVISION_REQUESTED",
            "revision_round": 1,
            "revision_reason": LOOP_ONE_REASON,
        },
    )

    reprepared = X.prepare(client, determination_id, "PER_ACCOUNT_PROVISIONAL")
    assert_fields_equal(reprepared, {"status": "PREPARED", "revision_round": 1})

    X.submit_review(client, determination_id)
    sent_back_again = X.request_revision(
        client, determination_id, revision_reason=LOOP_TWO_REASON
    )
    assert_fields_equal(
        sent_back_again,
        {
            "status": "REVISION_REQUESTED",
            "revision_round": 2,
            "revision_reason": LOOP_TWO_REASON,
        },
    )

    final_prepare = X.prepare(client, determination_id, "AGGREGATE_BY_CATEGORY")
    assert_fields_equal(final_prepare, {"status": "PREPARED", "revision_round": 2})


def test_certification_carries_the_amounts_from_the_last_prepare(client):
    """The final aggregate re-prepare overwrites the provisional figures, so the
    certified position reads 25000000 insured and 4000001 uninsured.

    PRD: "A determination at `REVISION_REQUESTED` can be prepared again by a `ClaimsAgent`, which recomputes every amount from scratch and overwrites the prior figures — and the `method_variant` may legitimately change on the re-prepare — moving it back to `PREPARED`."

    Design: Difficulty/non_linear_state_machine/determination_two_revision_loops_then_certify_last_prepare_wins
    """
    estate = _dana_estate(client)
    determination = X.determination_under_review(client, estate["depositor"]["id"])
    determination_id = determination["id"]

    X.request_revision(client, determination_id, revision_reason=LOOP_ONE_REASON)
    provisional = X.prepare(client, determination_id, "PER_ACCOUNT_PROVISIONAL")
    assert provisional["insured_amount_cents"] == C.POOLED_ATTRIBUTED_CENTS
    X.submit_review(client, determination_id)
    X.request_revision(client, determination_id, revision_reason=LOOP_TWO_REASON)
    X.prepare(client, determination_id, "AGGREGATE_BY_CATEGORY")
    X.submit_review(client, determination_id)

    certified = X.certify(client, determination_id)
    assert_fields_equal(
        certified,
        {
            "status": "CERTIFIED",
            "revision_round": 2,
            "method_variant": "AGGREGATE_BY_CATEGORY",
            "prepared_by_user_id": C.PREPARER_USER_ID,
            "certified_by_user_id": C.CERTIFIER_USER_ID,
        },
    )
    assert_determination_amounts(
        certified,
        C.POOLED_INSURED_CENTS,
        C.POOLED_UNINSURED_CENTS,
        C.POOLED_ATTRIBUTED_CENTS,
    )

    depositor = X.get_depositor(client, estate["depositor"]["id"])
    assert_fields_equal(
        depositor,
        {
            "certified_insured_cents": C.POOLED_INSURED_CENTS,
            "certified_uninsured_cents": C.POOLED_UNINSURED_CENTS,
        },
    )
    institution = X.get_institution(client, estate["institution"]["id"])
    assert_fields_equal(
        institution,
        {
            "aggregate_insured_cents": C.POOLED_INSURED_CENTS,
            "aggregate_certificate_face_cents": C.POOLED_UNINSURED_CENTS,
            "uninsured_claim_count": 1,
        },
    )
    for account_key in ("account_a", "account_b"):
        account = X.get_account(client, estate[account_key]["id"])
        assert account["insurance_status"] == "DETERMINED"


# ---------------------------------------------------------------------------
# Three dimensions on one account row, advancing independently
# ---------------------------------------------------------------------------
def test_release_hold_on_one_account_leaves_its_sibling_held(client):
    """Releasing the hold on the first account moves only that account's hold
    dimension, leaving the sibling at `HELD` for 1241379 cents and both accounts
    `DETERMINED` with their transition dimension still `PENDING`.

    PRD: "Each dimension advances under its own triggers and none of them gates another dimension's transition table; where one dimension's value matters to another dimension's transition, this document says so explicitly."

    Design: Difficulty/non_linear_state_machine/deposit_account_three_parallel_dimensions_advance_independently
    """
    estate = X.certified_pooled_estate(
        client,
        cert_number="34570",
        legal_name="Chinook Harbor Bank",
        depositor_name="Elena Duarte",
    )
    assert_account_dimensions(
        estate["account_a"],
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=C.HOLD_ACCOUNT_A_CENTS,
    )
    assert_account_dimensions(
        estate["account_b"],
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=C.HOLD_ACCOUNT_B_CENTS,
    )

    X.acknowledge_notice(client, estate["depositor"]["id"])
    released = X.release_hold(client, estate["account_a"]["id"])

    assert_account_dimensions(
        released,
        "DETERMINED",
        "RELEASED",
        "PENDING",
        held_amount_cents=0,
        attributed_amount_cents=C.ACCOUNT_A_BALANCE_CENTS,
    )
    sibling = X.get_account(client, estate["account_b"]["id"])
    assert_account_dimensions(
        sibling,
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=C.HOLD_ACCOUNT_B_CENTS,
        attributed_amount_cents=C.ACCOUNT_B_BALANCE_CENTS,
    )


def test_releasing_a_hold_leaves_the_uninsured_claim_standing(client):
    """The receivership certificate keeps its `ISSUED` status and its full face of
    4000001 cents after the hold is released.

    PRD: "Critically, the receivership certificate is left completely untouched: releasing an operational hold does not extinguish the uninsured claim, which continues to sit against the estate and continues to be paid dividends."

    Design: Difficulty/non_linear_state_machine/deposit_account_three_parallel_dimensions_advance_independently
    """
    estate = X.certified_pooled_estate(
        client,
        cert_number="34570",
        legal_name="Chinook Harbor Bank",
        depositor_name="Elena Duarte",
    )
    certificate_id = estate["certificate"]["id"]

    acknowledged = X.acknowledge_notice(client, estate["depositor"]["id"])
    assert acknowledged["notice_status"] == "ACKNOWLEDGED"
    X.release_hold(client, estate["account_a"]["id"])

    certificate = X.get_certificate(client, certificate_id)
    assert_certificate(
        certificate,
        "ISSUED",
        C.CERT_FACE_LARGE_CENTS,
        cumulative_dividends_cents=0,
    )
    institution = X.get_institution(client, estate["institution"]["id"])
    assert_fields_equal(
        institution,
        {
            "aggregate_certificate_face_cents": C.CERT_FACE_LARGE_CENTS,
            "uninsured_claim_count": 1,
        },
    )
