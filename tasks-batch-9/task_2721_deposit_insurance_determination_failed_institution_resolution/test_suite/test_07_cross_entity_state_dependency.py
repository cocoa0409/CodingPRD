"""Operations gated on another entity's state, not their own.

In both pairs the acted-on row is already in a perfectly legal state and the caller
holds the right role; only a second entity blocks the request.  Each pair runs the
identical request twice, before and after that other entity moves, so the outcome
can only be attributed to the cross-entity dependency.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_INSTITUTION_NOT_CLOSED,
    ERR_NOTICE_NOT_ACKNOWLEDGED,
)
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_certificate,
    assert_determination_amounts,
    assert_fields_equal,
    assert_instant,
)
from test_helpers.test_users import CLAIMS_AGENT, CLAIMS_CERTIFIER

LENA_BALANCE_CENTS = 30000000
LENA_UNINSURED_CENTS = 5000000


def _standardized_but_open_estate(client):
    """A standardized, not yet closed institution with a `DRAFT` determination waiting.

    The determination's own state is legal for preparation; the only obstacle is that
    the charter has not been closed.
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="34578",
        legal_name="Snake River Guaranty Bank",
        charter_state="ID",
    )
    depositor = X.new_depositor(client, institution["id"], legal_name="Lena Okafor")
    account = X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="L-0001",
        ownership_category="SINGLE",
        balance_cents=LENA_BALANCE_CENTS,
        opened_at="2024-05-01T00:00:00Z",
    )
    X.make_resolution_ready(client, institution["id"], LENA_BALANCE_CENTS)
    institution = X.get_institution(client, institution["id"])
    assert_fields_equal(
        institution, {"status": "RESOLUTION_READY", "readiness_standardized": True}
    )
    determination = X.open_determination(client, depositor["id"])
    assert_fields_equal(
        determination, {"status": "DRAFT", "method_variant": None, "revision_round": 0}
    )
    return {
        "institution": institution,
        "depositor": depositor,
        "account": account,
        "determination": determination,
    }


def test_prepare_is_refused_while_the_charter_is_still_open(client):
    """Preparing a legal `DRAFT` determination is refused because the depositor's
    institution has not been closed into receivership, and nothing is written.

    PRD: "the determination must be at `DRAFT` or `REVISION_REQUESTED`, else `ERR_DETERMINATION_NOT_PREPARABLE`; the depositor's institution must be at `CLOSED_IN_RECEIVERSHIP`, else `ERR_INSTITUTION_NOT_CLOSED`"

    Design: Difficulty/cross_entity_state_dependency/prepare_blocked_until_institution_closed_in_receivership
    """
    estate = _standardized_but_open_estate(client)
    determination = estate["determination"]

    validate_error(
        client.prepare_determination(
            determination["id"], {"method_variant": "AGGREGATE_BY_CATEGORY"}, CLAIMS_AGENT
        ),
        ERR_INSTITUTION_NOT_CLOSED,
        409,
    )

    assert X.get_institution(client, estate["institution"]["id"])["status"] == "RESOLUTION_READY"
    unchanged = X.get_determination(client, determination["id"])
    assert_fields_equal(
        unchanged,
        {
            "status": "DRAFT",
            "method_variant": None,
            "insured_amount_cents": 0,
            "uninsured_amount_cents": 0,
            "prepared_by_user_id": None,
            "prepared_at": None,
        },
    )
    assert X.get_account(client, estate["account"]["id"])["attributed_amount_cents"] == 0


def test_the_same_prepare_succeeds_once_the_charter_is_closed(client):
    """Closing the charter freezes the account and lets the identical prepare request
    through, attributing 30000000 cents and capping the insured figure at 25000000.

    PRD: "the depositor's institution must be at `CLOSED_IN_RECEIVERSHIP`, else `ERR_INSTITUTION_NOT_CLOSED`"

    Design: Difficulty/cross_entity_state_dependency/prepare_blocked_until_institution_closed_in_receivership
    """
    estate = _standardized_but_open_estate(client)

    closed = X.close_charter(client, estate["institution"]["id"])
    assert closed["status"] == "CLOSED_IN_RECEIVERSHIP"
    assert (
        X.get_account(client, estate["account"]["id"])["insurance_status"]
        == "FROZEN_FOR_DETERMINATION"
    )

    prepared = X.prepare(client, estate["determination"]["id"])
    assert_fields_equal(
        prepared, {"status": "PREPARED", "method_variant": "AGGREGATE_BY_CATEGORY"}
    )
    assert_determination_amounts(
        prepared, C.SMDIA_CENTS, LENA_UNINSURED_CENTS, LENA_BALANCE_CENTS
    )


# ---------------------------------------------------------------------------
# Hold release gated on the parent depositor's notice, not on the account
# ---------------------------------------------------------------------------
def _certified_unacknowledged_estate(client):
    """Mira's estate, certified and held, with her notice sent but not acknowledged."""
    estate = X.certified_pooled_estate(
        client,
        cert_number="34579",
        legal_name="Willamette Depositors Bank",
        charter_state="OR",
        depositor_name="Mira Solano",
    )
    assert_fields_equal(
        estate["depositor"],
        {"notice_status": "SENT", "notice_template_code": "PARTIALLY_UNINSURED"},
    )
    return estate


def test_release_hold_is_refused_while_the_notice_is_only_sent(client):
    """The account's hold is placed and the caller is a certifier, yet the release is
    refused because the parent depositor has not acknowledged her notice.

    PRD: "A `ClaimsCertifier` releases the hold on a single account, and two guards apply in order: the account's `hold_status` must be `HELD`, else `ERR_HOLD_NOT_PLACED`, and the account's primary depositor must be at `notice_status` `ACKNOWLEDGED`, else `ERR_NOTICE_NOT_ACKNOWLEDGED`."

    Design: Difficulty/cross_entity_state_dependency/release_hold_blocked_until_depositor_acknowledges_notice
    """
    estate = _certified_unacknowledged_estate(client)
    account_a = estate["account_a"]

    validate_error(
        client.release_hold(account_a["id"], CLAIMS_CERTIFIER),
        ERR_NOTICE_NOT_ACKNOWLEDGED,
        409,
    )

    assert X.get_depositor(client, estate["depositor"]["id"])["notice_status"] == "SENT"
    unchanged = X.get_account(client, account_a["id"])
    assert_account_dimensions(
        unchanged,
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=C.HOLD_ACCOUNT_A_CENTS,
    )
    assert unchanged["version"] == account_a["version"]


def test_the_same_release_succeeds_after_the_depositor_acknowledges(client):
    """Once the depositor acknowledges, the identical release request clears the hold on
    that one account only, and the uninsured claim stands regardless.

    PRD: "Release moves `hold_status` `HELD` → `RELEASED` and sets `held_amount_cents` back to zero. Critically, the receivership certificate is left completely untouched: releasing an operational hold does not extinguish the uninsured claim, which continues to sit against the estate and continues to be paid dividends."

    Design: Difficulty/cross_entity_state_dependency/release_hold_blocked_until_depositor_acknowledges_notice
    """
    estate = _certified_unacknowledged_estate(client)

    acknowledged = X.acknowledge_notice(client, estate["depositor"]["id"])
    assert acknowledged["notice_status"] == "ACKNOWLEDGED"
    assert_instant(acknowledged["acknowledged_at"], C.SETUP_CLOCK)

    released = X.release_hold(client, estate["account_a"]["id"])
    assert_account_dimensions(
        released, "DETERMINED", "RELEASED", "PENDING", held_amount_cents=0
    )

    # Acknowledging a notice releases nothing by itself: the sibling is still held.
    assert_account_dimensions(
        X.get_account(client, estate["account_b"]["id"]),
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=C.HOLD_ACCOUNT_B_CENTS,
    )
    assert_certificate(
        X.get_certificate(client, estate["certificate"]["id"]),
        "ISSUED",
        C.CERT_FACE_LARGE_CENTS,
    )
