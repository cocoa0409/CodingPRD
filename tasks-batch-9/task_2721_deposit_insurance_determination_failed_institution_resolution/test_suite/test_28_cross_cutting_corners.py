"""Cross-cutting corners: stale-view protection, the version counter and re-armed gates.

Two writes in this API are guarded by optimistic concurrency against a parent's
`version`, and the guard is only as good as the counter it reads, so the counter's
own discipline — one increment per accepted mutation, none for a read and none for
a refusal — is pinned here alongside both guards.  The readiness gates are the
other cross-cutting layer: they are re-armed by every newly delivered package, so
an attestation earned once has to be earned again.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ACTIVE_DETERMINATION_EXISTS,
    ERR_BRANCH_NOT_READY,
    ERR_INSTITUTION_NOT_READY,
    ERR_STALE_DEPOSITOR_VERSION,
    ERR_STALE_INSTITUTION_VERSION,
)
from test_helpers.assertions import (
    assert_determination_amounts,
    assert_fields_equal,
    assert_instant,
    assert_page,
    assert_submission_scored,
    assert_summary,
)
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLOSING_MANAGER,
    RECEIVERSHIP_TRUSTEE,
    make_claims_agent_headers,
)


def test_occ_stale_depositor_version_blocks_the_determination_create_and_outranks_the_uniqueness_check(
    client,
):
    """Opening a determination requires the depositor record's `version` exactly as the
    client last observed it: any other value is a precondition failure that writes
    nothing, the freshly read value is accepted, and once the create has bumped the
    version the replayed value still fails on the version rather than on the live
    determination.

    PRD: "If the depositor record's `version` has advanced since that observation, the create is rejected with `ERR_STALE_DEPOSITOR_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_depositor_version_blocks_the_determination_create_and_outranks_the_uniqueness_check
    """
    estate = X.single_account_estate(
        client,
        8000000,
        account_number="DO-0001",
        cert_number="61084",
        legal_name="Depositor OCC Bank",
        charter_state="MS",
        book_asset_value_cents=11000000,
        estimated_liquidation_recovery_cents=4000000,
        depositor_name="Yara Haddad",
    )
    depositor_id = estate["depositor"]["id"]
    agent = make_claims_agent_headers("U-AGENT-AC")
    observed_version = X.depositor_version(client, depositor_id)

    # Any value that does not equal the depositor record's current version is a
    # precondition failure on the concurrency guard.
    validate_error(
        client.create_determination(
            F.determination_payload(depositor_id, observed_version + 1), agent
        ),
        ERR_STALE_DEPOSITOR_VERSION,
    )
    # The refused create wrote nothing.
    rows, _ = assert_page(
        client.list_determinations(
            CLAIMS_AGENT, params={"depositor_record_id": depositor_id}
        ),
        expected_total=0,
    )
    assert rows == [], rows

    # The freshly read version is accepted.
    determination = validate_success(
        client.create_determination(
            F.determination_payload(depositor_id, observed_version), agent
        ),
        201,
    )
    assert determination["status"] == "DRAFT", determination

    prepared = validate_success(
        client.prepare_determination(
            determination["id"], F.prepare_payload("AGGREGATE_BY_CATEGORY"), agent
        ),
        200,
    )
    assert prepared["status"] == "PREPARED", prepared
    assert_determination_amounts(prepared, 8000000, 0, 8000000)

    # A successful create bumps the depositor record's version, and preparation writes
    # `attributed_total_cents` onto the same row, so the captured value is now stale.
    current_version = X.depositor_version(client, depositor_id)
    assert current_version > observed_version, current_version

    # Replaying the stale version reports the version failure, not the live-determination
    # guard, because the concurrency check is settled first.
    validate_error(
        client.create_determination(
            F.determination_payload(depositor_id, observed_version), agent
        ),
        ERR_STALE_DEPOSITOR_VERSION,
    )
    # With a current version the only-one-live-determination guard is finally reached.
    validate_error(
        client.create_determination(
            F.determination_payload(depositor_id, current_version), agent
        ),
        ERR_ACTIVE_DETERMINATION_EXISTS,
    )


def test_occ_stale_institution_version_blocks_the_dividend_declaration_after_any_intervening_write(
    client,
):
    """Declaring a dividend round requires the institution's `version` as last observed,
    so a trustee working from a stale cash-and-round picture is refused; booking further
    proceeds after the read invalidates the capture, and the next declaration must
    re-read the version even though nothing about the dividend itself changed.

    PRD: "If the institution's `version` has advanced, the declaration is rejected with `ERR_STALE_INSTITUTION_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_institution_version_blocks_the_dividend_declaration_after_any_intervening_write
    """
    estate = X.single_account_estate(
        client,
        30000000,
        account_number="IO-0001",
        cert_number="61085",
        legal_name="Institution OCC Bank",
        charter_state="IA",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
        depositor_name="Zoya Petrova",
    )
    institution_id = estate["institution"]["id"]
    X.certified_determination(client, estate["depositor"]["id"])
    X.post_proceeds(
        client,
        institution_id,
        asset_pool_code="POOL-IO-A",
        gross_proceeds_cents=10000000,
        disposition_expense_cents=0,
    )
    observed_version = X.institution_version(client, institution_id)

    # One behind the institution's current version.
    validate_error(
        client.declare_dividend(
            institution_id,
            F.dividend_payload("GENERAL_UNSECURED", 1000, observed_version - 1),
            RECEIVERSHIP_TRUSTEE,
        ),
        ERR_STALE_INSTITUTION_VERSION,
    )
    rows, _ = assert_page(
        client.list_dividends(
            RECEIVERSHIP_TRUSTEE, params={"institution_id": institution_id}
        ),
        expected_total=0,
    )
    assert rows == [], rows

    # The current version is accepted, and the round takes the next ordinal.
    first_round = validate_success(
        client.declare_dividend(
            institution_id,
            F.dividend_payload("GENERAL_UNSECURED", 1000, observed_version),
            RECEIVERSHIP_TRUSTEE,
        ),
        201,
    )
    assert_fields_equal(
        first_round,
        {"distribution_round": 1, "declared_rate_bps": 1000, "status": "DECLARED"},
    )

    # Booking more proceeds moves the cash picture under the trustee's feet.
    X.post_proceeds(
        client,
        institution_id,
        asset_pool_code="POOL-IO-B",
        gross_proceeds_cents=2000000,
        disposition_expense_cents=0,
    )
    after_proceeds = X.get_institution(client, institution_id, RECEIVERSHIP_TRUSTEE)
    assert after_proceeds["receivership_cash_cents"] == 12000000, after_proceeds

    validate_error(
        client.declare_dividend(
            institution_id,
            F.dividend_payload("GENERAL_UNSECURED", 500, observed_version),
            RECEIVERSHIP_TRUSTEE,
        ),
        ERR_STALE_INSTITUTION_VERSION,
    )

    # Re-reading the version lets the second round through.
    refreshed_version = X.institution_version(client, institution_id)
    second_round = validate_success(
        client.declare_dividend(
            institution_id,
            F.dividend_payload("GENERAL_UNSECURED", 500, refreshed_version),
            RECEIVERSHIP_TRUSTEE,
        ),
        201,
    )
    assert second_round["distribution_round"] == 2, second_round

    # Declarations alone move no cash.
    summary = X.insurance_summary(client, institution_id, RECEIVERSHIP_TRUSTEE)
    assert_summary(
        summary,
        receivership_cash_cents=12000000,
        dividends_paid_cents=0,
        cash_conservation_delta_cents=0,
    )


def test_version_advances_on_every_accepted_write_and_never_on_reads_or_refusals(client):
    """A resource's `version` counts accepted mutations and nothing else: repeated reads
    of the same branch reopening return an identical version, a refused reopening leaves
    it untouched, and only the two accepted reschedules advance it by exactly one each.

    PRD: "The `version` of a resource starts at 1 and increments by one on every server-side mutation of that resource"

    Design: Corner/cross_cutting_complexity_layers/version_advances_on_every_accepted_write_and_never_on_reads_or_refusals
    """
    X.open_at_setup_clock(client)
    institution = X.deposit_free_closed_institution(
        client,
        cert_number="61086",
        legal_name="Version Counter Bank",
        charter_state="ND",
        book_asset_value_cents=9000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    branch = X.new_branch_reopening(
        client,
        institution["id"],
        branch_code="BR-N01",
        reopen_window_start="2026-08-10T09:00:00Z",
        reopen_window_end="2026-08-10T17:00:00Z",
        staffing_headcount=3,
    )

    # A freshly created resource opens at version 1.
    first_read = X.get_branch_reopening(client, branch["id"])
    assert_fields_equal(first_read, {"version": 1, "reschedule_count": 0, "status": "PLANNED"})

    # A read never advances the counter, whoever issues it.
    second_read = validate_success(
        client.get_branch_reopening(branch["id"], CLAIMS_AGENT), 200
    )
    assert second_read["version"] == first_read["version"], second_read
    rows, _ = assert_page(
        client.list_branch_reopenings(institution["id"], RECEIVERSHIP_TRUSTEE),
        expected_total=1,
    )
    assert rows[0]["version"] == first_read["version"], rows[0]

    # `READY` is conferred only by the award cascade, so this reopening is refused.
    validate_error(
        client.reopen_branch(branch["id"], CLOSING_MANAGER), ERR_BRANCH_NOT_READY
    )
    after_refusal = X.get_branch_reopening(client, branch["id"])
    assert after_refusal["version"] == first_read["version"], after_refusal

    # One increment per accepted write, with no gaps.
    rescheduled = validate_success(
        client.reschedule_branch_reopening(
            branch["id"],
            F.reschedule_payload("2026-08-11T09:00:00Z", "2026-08-11T17:00:00Z"),
            CLOSING_MANAGER,
        ),
        200,
    )
    assert_fields_equal(rescheduled, {"version": 2, "reschedule_count": 1})
    rescheduled_again = validate_success(
        client.reschedule_branch_reopening(
            branch["id"],
            F.reschedule_payload("2026-08-12T09:00:00Z", "2026-08-12T17:00:00Z"),
            CLOSING_MANAGER,
        ),
        200,
    )
    assert_fields_equal(rescheduled_again, {"version": 3, "reschedule_count": 2})


def test_readiness_threshold_resets_when_a_further_submission_reopens_collection(client):
    """A newly delivered deposit file revokes the standing readiness attestation before
    it is even scored, a package below the score floor is rejected and leaves the
    institution un-closeable, and only a package clearing the floor on equality
    re-earns resolution readiness and lets the charter close.

    PRD: "an institution at `RESOLUTION_READY` drops back to `READINESS_COLLECTION` and `readiness_standardized` is lowered to false, on the principle that readiness is only as good as the newest delivered file."

    Design: Corner/cross_cutting_complexity_layers/readiness_threshold_resets_when_a_further_submission_reopens_collection
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61087",
        legal_name="Threshold Reset Bank",
        charter_state="SD",
        book_asset_value_cents=14000000,
        estimated_liquidation_recovery_cents=6000000,
    )
    depositor = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-TR-1",
        legal_name="Bela Kovacs",
        contact_email="bela@example.com",
    )
    # One account of 10000000 fixes the booked total for every variance computation.
    X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="TR-0001",
        ownership_category="SINGLE",
        balance_cents=10000000,
    )
    first = X.file_readiness(
        client,
        institution["id"],
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=10000000,
    )
    X.standardize(client, first["id"])
    ready = X.get_institution(client, institution["id"])
    assert_fields_equal(
        ready, {"status": "RESOLUTION_READY", "readiness_standardized": True}
    )

    # A further package revokes the attestation before any scoring happens.
    second = X.file_readiness(
        client,
        institution["id"],
        record_count=100,
        malformed_record_count=3,
        reported_deposit_total_cents=10000000,
    )
    assert second["status"] == "RECEIVED", second
    reverted = X.get_institution(client, institution["id"])
    assert_fields_equal(
        reverted, {"status": "READINESS_COLLECTION", "readiness_standardized": False}
    )
    validate_error(
        client.close_institution(institution["id"], CLOSING_MANAGER),
        ERR_INSTITUTION_NOT_READY,
    )

    # 97 of 100 records parse cleanly, which is below the floor of 9800 basis points.
    rejected = validate_success(
        client.standardize_submission(second["id"], CLOSING_MANAGER), 200
    )
    assert_submission_scored(rejected, "REJECTED", 9700, 0, "SCORE_BELOW_FLOOR")
    # A rejected package leaves the institution exactly where it was.
    validate_error(
        client.close_institution(institution["id"], CLOSING_MANAGER),
        ERR_INSTITUTION_NOT_READY,
    )

    # 98 of 100 records is exactly the floor, which the PRD says clears it.
    third = X.file_readiness(
        client,
        institution["id"],
        record_count=100,
        malformed_record_count=2,
        reported_deposit_total_cents=10000000,
    )
    standardized = validate_success(
        client.standardize_submission(third["id"], CLOSING_MANAGER), 200
    )
    assert_submission_scored(
        standardized, "STANDARDIZED", C.READINESS_SCORE_FLOOR_BPS, 0, None
    )

    closed = validate_success(
        client.close_institution(institution["id"], CLOSING_MANAGER), 200
    )
    assert_fields_equal(
        closed, {"status": "CLOSED_IN_RECEIVERSHIP", "readiness_standardized": True}
    )
    assert_instant(closed["failure_datetime"], C.SETUP_CLOCK)

    # Terminal submissions are never rewritten.
    rows, _ = assert_page(
        client.list_readiness_submissions(institution["id"], CLOSING_MANAGER),
        expected_total=3,
    )
    assert [row["status"] for row in rows] == [
        "STANDARDIZED",
        "REJECTED",
        "STANDARDIZED",
    ], rows
