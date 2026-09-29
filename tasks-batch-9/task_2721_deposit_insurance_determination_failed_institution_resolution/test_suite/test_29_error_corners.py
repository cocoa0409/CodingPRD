"""Error corners of the Deposit Insurance Resolution API.

These tests drive the catalogued failures that the rest of the suite does not
reach on its way through a happy resolution: the per-entity not-found codes on
both the read surface and the write surface, the two mirror-image determination
lifecycle codes around the prepare / review cycle, the uniqueness guard over a
depositor's open determination set, and the dividend priority-class ordering
guard.  Each test builds its own rows against an empty database whose logical
clock reads the instant the service started at.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ACTIVE_DETERMINATION_EXISTS,
    ERR_BID_NOT_FOUND,
    ERR_BIDDER_NOT_FOUND,
    ERR_BRANCH_REOPENING_NOT_FOUND,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_DEPOSITOR_NOT_FOUND,
    ERR_DETERMINATION_NOT_FOUND,
    ERR_DETERMINATION_NOT_PREPARABLE,
    ERR_DETERMINATION_NOT_PREPARED,
    ERR_DISTRIBUTION_NOT_FOUND,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_PRIORITY_CLASS_OUT_OF_ORDER,
    ERR_SUBMISSION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_certificate,
    assert_determination_amounts,
    assert_fields_equal,
    assert_page,
    assert_summary,
)
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLOSING_MANAGER,
    RECEIVERSHIP_TRUSTEE,
    RESOLUTION_ANALYST,
)

# A well-formed UUID that matches no row, since every id is server-minted at
# creation and never reused.
MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _assert_error_envelope(response):
    """An error response carries only `api_request_id` and `api_request_timestamp`."""
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str), meta
    assert meta["api_request_id"].startswith("req_"), meta
    assert isinstance(meta.get("api_request_timestamp"), str), meta
    assert response.json()["response_type"] == "error", response.text


def test_every_read_endpoint_returns_its_own_not_found_code_for_an_unknown_uuid(client):
    """Each detail read answers with the not-found code of the entity named in its own
    path rather than one shared 404, and the computed insurance summary resolves its
    parent institution first.

    PRD: "Each entity has its own not-found code: `ERR_INSTITUTION_NOT_FOUND` when an institution id in a path or in an `institution_id` body field does not resolve, `ERR_SUBMISSION_NOT_FOUND` for a readiness submission, `ERR_DEPOSITOR_NOT_FOUND` when a depositor id in a path or in a `depositor_record_id` or `primary_depositor_id` body field does not resolve, `ERR_ACCOUNT_NOT_FOUND` for a deposit account, `ERR_DETERMINATION_NOT_FOUND` for an insurance determination, `ERR_CERTIFICATE_NOT_FOUND` for a receivership certificate, `ERR_BIDDER_NOT_FOUND` when a bidder id in a path or in a `bidder_id` body field does not resolve, `ERR_BID_NOT_FOUND` for a bid, `ERR_BRANCH_REOPENING_NOT_FOUND` for a branch reopening, and `ERR_DISTRIBUTION_NOT_FOUND` for a dividend round."

    Design: Corner/errors/every_read_endpoint_returns_its_own_not_found_code_for_an_unknown_uuid
    """
    X.open_at_setup_clock(client)

    reads = [
        (client.get_depositor_record(MISSING_ID, CLAIMS_AGENT), ERR_DEPOSITOR_NOT_FOUND),
        (client.get_determination(MISSING_ID, CLAIMS_AGENT), ERR_DETERMINATION_NOT_FOUND),
        (client.get_certificate(MISSING_ID, CLAIMS_AGENT), ERR_CERTIFICATE_NOT_FOUND),
        (client.get_bidder(MISSING_ID, RESOLUTION_ANALYST), ERR_BIDDER_NOT_FOUND),
        (client.get_bid(MISSING_ID, RESOLUTION_ANALYST), ERR_BID_NOT_FOUND),
        (
            client.get_branch_reopening(MISSING_ID, CLOSING_MANAGER),
            ERR_BRANCH_REOPENING_NOT_FOUND,
        ),
        (
            client.get_dividend(MISSING_ID, RECEIVERSHIP_TRUSTEE),
            ERR_DISTRIBUTION_NOT_FOUND,
        ),
        (
            client.get_insurance_summary(MISSING_ID, RECEIVERSHIP_TRUSTEE),
            ERR_INSTITUTION_NOT_FOUND,
        ),
    ]
    for response, expected_error in reads:
        validate_error(response, expected_error, 404)
        _assert_error_envelope(response)


def test_action_endpoints_and_fk_payloads_return_the_not_found_code_of_the_row_they_cannot_resolve(
    client,
):
    """An unresolvable path id or body foreign key is reported with the referenced
    entity's own not-found code rather than as a request-shape failure, and none of
    the refused writes leaves a row behind.

    PRD: "When a path carries an identifier, that identifier is resolved before any body field is inspected, and where a path carries more than one identifier they are resolved strictly left to right — the first identifier that does not resolve determines the 404 that comes back."

    Design: Corner/errors/action_endpoints_and_fk_payloads_return_the_not_found_code_of_the_row_they_cannot_resolve
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61075",
        legal_name="Unknown Ref Bank",
        charter_state="ME",
        book_asset_value_cents=9000000,
        estimated_liquidation_recovery_cents=3000000,
    )
    quinn = X.new_depositor(
        client, institution["id"], tin_hash="TIN-UR-1", legal_name="Quinn Alvarez"
    )

    validate_error(
        client.standardize_submission(MISSING_ID, CLOSING_MANAGER),
        ERR_SUBMISSION_NOT_FOUND,
        404,
    )

    # The body foreign keys resolve in the declared entity order: institution first,
    # then the depositor record.
    validate_error(
        client.create_deposit_account(
            F.deposit_account_payload(
                MISSING_ID,
                quinn["id"],
                account_number="UR-0001",
                ownership_category="SINGLE",
                balance_cents=100000,
            ),
            CLAIMS_AGENT,
        ),
        ERR_INSTITUTION_NOT_FOUND,
        404,
    )
    validate_error(
        client.create_deposit_account(
            F.deposit_account_payload(
                institution["id"],
                MISSING_ID,
                account_number="UR-0002",
                ownership_category="SINGLE",
                balance_cents=100000,
            ),
            CLAIMS_AGENT,
        ),
        ERR_DEPOSITOR_NOT_FOUND,
        404,
    )

    # The path parent is resolved before the body is inspected at all.
    validate_error(
        client.create_depositor_record(
            MISSING_ID,
            F.depositor_record_payload(
                tin_hash="TIN-UR-9", legal_name="Ghost Depositor"
            ),
            CLAIMS_AGENT,
        ),
        ERR_INSTITUTION_NOT_FOUND,
        404,
    )
    validate_error(
        client.decide_qualification(
            MISSING_ID, F.qualification_payload("QUALIFY"), RESOLUTION_ANALYST
        ),
        ERR_BIDDER_NOT_FOUND,
        404,
    )
    validate_error(
        client.settle_dividend(MISSING_ID, RECEIVERSHIP_TRUSTEE),
        ERR_DISTRIBUTION_NOT_FOUND,
        404,
    )

    rows, _ = assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT, params={"institution_id": institution["id"]}
        ),
        expected_total=0,
    )
    assert rows == [], rows


def test_determination_lifecycle_rejects_prepare_and_submit_review_out_of_order(client):
    """Handing a determination to review demands that it be `PREPARED`, while preparing
    it demands `DRAFT` or `REVISION_REQUESTED`, so the two lifecycle refusals mirror
    each other across the review cycle and a send-back reopens preparation only.

    PRD: "A `ClaimsAgent` submits a prepared determination for independent review, which requires the determination to be at `PREPARED` — otherwise `ERR_DETERMINATION_NOT_PREPARED` — and requires `prepared_by_user_id` to have been recorded, moving it `PREPARED` → `UNDER_REVIEW`."

    Design: Corner/errors/determination_lifecycle_rejects_prepare_and_submit_review_out_of_order
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61076",
        legal_name="Lifecycle Order Bank",
        charter_state="VT",
        book_asset_value_cents=14000000,
        estimated_liquidation_recovery_cents=6000000,
    )
    rosa = X.new_depositor(
        client, institution["id"], tin_hash="TIN-LO-1", legal_name="Rosa Bianchi"
    )
    X.new_account(
        client,
        institution["id"],
        rosa["id"],
        account_number="LO-0001",
        ownership_category="SINGLE",
        balance_cents=10000000,
    )
    X.make_resolution_ready(client, institution["id"], 10000000)
    X.close_charter(client, institution["id"])
    determination = X.open_determination(client, rosa["id"])
    assert_fields_equal(determination, {"status": "DRAFT", "revision_round": 0})

    # A DRAFT document has nothing to review yet.
    validate_error(
        client.submit_determination_review(determination["id"], CLAIMS_AGENT),
        ERR_DETERMINATION_NOT_PREPARED,
        409,
    )

    prepared = X.prepare(client, determination["id"], "AGGREGATE_BY_CATEGORY")
    assert_fields_equal(prepared, {"status": "PREPARED"})
    assert_determination_amounts(prepared, 10000000, 0, 10000000)

    # Preparation requires DRAFT or REVISION_REQUESTED, so PREPARED is not re-preparable.
    validate_error(
        client.prepare_determination(
            determination["id"], F.prepare_payload("AGGREGATE_BY_CATEGORY"), CLAIMS_AGENT
        ),
        ERR_DETERMINATION_NOT_PREPARABLE,
        409,
    )

    under_review = X.submit_review(client, determination["id"])
    assert_fields_equal(under_review, {"status": "UNDER_REVIEW"})

    validate_error(
        client.submit_determination_review(determination["id"], CLAIMS_AGENT),
        ERR_DETERMINATION_NOT_PREPARED,
        409,
    )
    validate_error(
        client.prepare_determination(
            determination["id"], F.prepare_payload("AGGREGATE_BY_CATEGORY"), CLAIMS_AGENT
        ),
        ERR_DETERMINATION_NOT_PREPARABLE,
        409,
    )

    sent_back = X.request_revision(
        client, determination["id"], "Confirm the account is titled to Rosa alone."
    )
    assert_fields_equal(sent_back, {"status": "REVISION_REQUESTED", "revision_round": 1})

    # The send-back reopens preparation, not review.
    validate_error(
        client.submit_determination_review(determination["id"], CLAIMS_AGENT),
        ERR_DETERMINATION_NOT_PREPARED,
        409,
    )

    re_prepared = X.prepare(client, determination["id"], "AGGREGATE_BY_CATEGORY")
    assert_fields_equal(re_prepared, {"status": "PREPARED"})
    assert_determination_amounts(re_prepared, 10000000, 0, 10000000)


def test_a_second_open_determination_for_the_same_depositor_is_refused_in_every_non_terminal_state(
    client,
):
    """A depositor may hold only one live determination, so a second opening is refused
    while the first sits at `DRAFT`, `PREPARED` or `UNDER_REVIEW` — and re-reading the
    depositor's version before each attempt rules out a stale-view refusal instead.

    PRD: "An opening attempted while that depositor already has a determination at `DRAFT`, `PREPARED`, `UNDER_REVIEW` or `REVISION_REQUESTED` is refused with `ERR_ACTIVE_DETERMINATION_EXISTS`."

    Design: Corner/errors/a_second_open_determination_for_the_same_depositor_is_refused_in_every_non_terminal_state
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61077",
        legal_name="Open Set Bank",
        charter_state="NH",
        book_asset_value_cents=16000000,
        estimated_liquidation_recovery_cents=7000000,
    )
    tomas = X.new_depositor(
        client, institution["id"], tin_hash="TIN-OS-1", legal_name="Tomas Nowak"
    )
    X.new_account(
        client,
        institution["id"],
        tomas["id"],
        account_number="OS-0001",
        ownership_category="SINGLE",
        balance_cents=12000000,
    )
    X.make_resolution_ready(client, institution["id"], 12000000)
    X.close_charter(client, institution["id"])
    determination = X.open_determination(client, tomas["id"])
    assert_fields_equal(determination, {"status": "DRAFT"})

    def _refuse_second_opening():
        """A create carrying the depositor's freshly observed `version`."""
        version = X.depositor_version(client, tomas["id"])
        validate_error(
            client.create_determination(
                F.determination_payload(tomas["id"], version), CLAIMS_AGENT
            ),
            ERR_ACTIVE_DETERMINATION_EXISTS,
            409,
        )

    _refuse_second_opening()

    prepared = X.prepare(client, determination["id"], "AGGREGATE_BY_CATEGORY")
    assert_fields_equal(prepared, {"status": "PREPARED"})
    _refuse_second_opening()

    under_review = X.submit_review(client, determination["id"])
    assert_fields_equal(under_review, {"status": "UNDER_REVIEW"})
    _refuse_second_opening()

    # The three refused creates left exactly one determination on the depositor.
    assert_page(
        client.list_determinations(
            CLAIMS_AGENT, params={"depositor_record_id": tomas["id"]}
        ),
        expected_total=1,
        expected_ids=[determination["id"]],
    )


def test_insured_subrogation_cannot_be_declared_after_a_general_unsecured_round_settles(
    client,
):
    """The insurer's subrogated round is declarable while no depositor class has been
    paid, but once a `GENERAL_UNSECURED` round settles the ladder closes behind it,
    while further `GENERAL_UNSECURED` rounds stay declarable and the refused
    declaration consumes no round number.

    PRD: "Priority classes may not be paid out of order: once any `GENERAL_UNSECURED` round for the institution has reached `SETTLED`, an attempt to declare an `INSURED_SUBROGATION` round is refused with `ERR_PRIORITY_CLASS_OUT_OF_ORDER`."

    Design: Corner/errors/insured_subrogation_cannot_be_declared_after_a_general_unsecured_round_settles
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61078",
        legal_name="Class Order Bank",
        charter_state="RI",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    ursula = X.new_depositor(
        client, institution["id"], tin_hash="TIN-CO-1", legal_name="Ursula Berg"
    )
    X.new_account(
        client,
        institution["id"],
        ursula["id"],
        account_number="CO-0001",
        ownership_category="SINGLE",
        balance_cents=30000000,
    )
    X.make_resolution_ready(client, institution["id"], 30000000)
    X.close_charter(client, institution["id"])

    # 30000000 against one standard maximum leaves a 5000000 uninsured claim.
    determination = X.certified_determination(client, ursula["id"])
    certificate = X.certificate_for(client, determination["id"])
    assert_certificate(certificate, "ISSUED", 5000000, cumulative_dividends_cents=0)

    X.post_proceeds(
        client,
        institution["id"],
        asset_pool_code="POOL-CO-A",
        gross_proceeds_cents=10000000,
        disposition_expense_cents=0,
    )

    def _declare(priority_class, declared_rate_bps, expected_version):
        return client.declare_dividend(
            institution["id"],
            F.dividend_payload(priority_class, declared_rate_bps, expected_version),
            RECEIVERSHIP_TRUSTEE,
        )

    version = X.institution_version(client, institution["id"])
    subrogation = validate_success(
        _declare("INSURED_SUBROGATION", 100, version), 201
    )
    assert_fields_equal(
        subrogation,
        {"distribution_round": 1, "priority_class": "INSURED_SUBROGATION"},
    )

    # A subrogation round pays the insurance fund, so no certificate participates.
    settled_subrogation = X.settle_dividend(client, subrogation["id"])
    assert_fields_equal(
        settled_subrogation,
        {"status": "SETTLED", "total_distributed_cents": 250000, "certificate_count": 0},
    )

    version = X.institution_version(client, institution["id"])
    general = validate_success(_declare("GENERAL_UNSECURED", 1000, version), 201)
    assert_fields_equal(
        general, {"distribution_round": 2, "priority_class": "GENERAL_UNSECURED"}
    )

    settled_general = X.settle_dividend(client, general["id"])
    assert_fields_equal(
        settled_general,
        {"status": "SETTLED", "total_distributed_cents": 500000, "certificate_count": 1},
    )

    version = X.institution_version(client, institution["id"])
    validate_error(
        _declare("INSURED_SUBROGATION", 100, version),
        ERR_PRIORITY_CLASS_OUT_OF_ORDER,
        409,
    )

    # The refusal wrote nothing, so the same observed version still declares the next
    # depositor-class round and it takes the round number the refusal did not consume.
    further_general = validate_success(_declare("GENERAL_UNSECURED", 1000, version), 201)
    assert_fields_equal(
        further_general,
        {"distribution_round": 3, "priority_class": "GENERAL_UNSECURED", "status": "DECLARED"},
    )

    assert_summary(
        X.insurance_summary(client, institution["id"]),
        gross_disposition_proceeds_cents=10000000,
        disposition_expense_total_cents=0,
        receivership_cash_cents=9250000,
        dividends_paid_cents=750000,
        cash_conservation_delta_cents=0,
        conservation_delta_cents=0,
    )
