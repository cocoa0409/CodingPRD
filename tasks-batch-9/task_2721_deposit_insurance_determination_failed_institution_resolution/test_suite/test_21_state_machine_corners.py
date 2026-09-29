"""State-machine corners of the Deposit Insurance Resolution API.

Every resource in the resolution arc opens at a declared initial state and moves
only through the transitions the specification names.  The tests here pin those
edges one at a time: the values a freshly created row carries before anything has
happened to it, the two arms a readiness package can leave `RECEIVED` by, the
preconditions that refuse a closing, the cascades a closing and a certification
fan out, the fork and the join of the least-cost test, the self-loop a branch
window may take repeatedly, and the lockdown a terminated receivership imposes.

Each test builds its own rows against an empty database whose logical clock reads
the instant the service started at, and advances the clock itself when a stamped
field has to be distinguishable from that start.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_INSTITUTION_ALREADY_CLOSED,
    ERR_INSTITUTION_NOT_READY,
    ERR_RECEIVERSHIP_NOT_TERMINABLE,
    ERR_SUBMISSION_NOT_PENDING,
)
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_bid_costs,
    assert_conservation_identities_hold,
    assert_determination_amounts,
    assert_fields_equal,
    assert_instant,
    assert_no_cost_calculation,
    assert_page,
    assert_submission_scored,
    assert_summary,
    total_count,
)
from test_helpers.test_users import (
    CLAIMS_CERTIFIER,
    CLOSING_MANAGER,
    RECEIVERSHIP_TRUSTEE,
    RESOLUTION_ANALYST,
)

# The instant this file builds its resolutions at, and a later instant used where
# a second stamp would otherwise be indistinguishable from the first.
BUILD_CLOCK = C.SETUP_CLOCK
LATE_CLOCK = "2026-08-03T17:00:00Z"

BID_DEADLINE = "2026-08-10T00:00:00Z"


def _assert_unset(row, *fields):
    """Every named field is still unrecorded on the row."""
    for field in fields:
        assert row.get(field) is None, (
            f"{field} must still be unset, got {row.get(field)!r}"
        )


# ---------------------------------------------------------------------------
# Initial states
# ---------------------------------------------------------------------------
def test_new_entities_open_in_their_declared_initial_states(client):
    """A freshly registered institution, deposit account, readiness package and
    bidder each open at the state the specification declares, and it is the first
    package rather than the institution create that starts readiness collection.

    PRD: "A newly registered institution opens at `status` `PRE_FAILURE_MONITORING`, with `readiness_standardized` false, `franchise_marketing_status` `NOT_STARTED`, `least_cost_status` `NOT_STARTED`, and no `failure_datetime`, `bid_deadline_at`, `least_cost_test_variant`, `liquidation_baseline_cents` or `resolution_method` yet recorded."

    Design: Corner/state_machines/initial_state_new_entities_start_in_declared_initial_states
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution = X.new_institution(
        client,
        cert_number="61001",
        legal_name="Initial State Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    depositor = X.new_depositor(
        client, institution["id"], tin_hash="TIN-IS-1", legal_name="Aliyah Cross"
    )

    fresh = X.get_institution(client, institution["id"])
    assert_fields_equal(
        fresh,
        {
            "status": "PRE_FAILURE_MONITORING",
            "franchise_marketing_status": "NOT_STARTED",
            "least_cost_status": "NOT_STARTED",
            "readiness_standardized": False,
        },
    )
    _assert_unset(
        fresh,
        "failure_datetime",
        "bid_deadline_at",
        "least_cost_test_variant",
        "liquidation_baseline_cents",
        "resolution_method",
    )

    account = X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="IS-0001",
        ownership_category="SINGLE",
        balance_cents=1000000,
        accrued_interest_cents=0,
    )
    assert_account_dimensions(
        account,
        "PENDING",
        "NONE",
        "PENDING",
        held_amount_cents=0,
        attributed_amount_cents=0,
    )

    submission = X.file_readiness(
        client,
        institution["id"],
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=1000000,
    )
    assert submission["status"] == "RECEIVED"
    _assert_unset(
        submission,
        "standardization_score_bps",
        "deposit_total_variance_bps",
        "rejection_reason",
    )

    bidder = X.new_bidder(
        client,
        legal_name="Initial Bidder",
        cert_number="61002",
        tier1_capital_ratio_bps=1400,
        camels_composite=2,
    )
    assert bidder["qualification_status"] == "PENDING"
    _assert_unset(bidder, "qualified_at", "disqualification_reason")

    collecting = X.get_institution(client, institution["id"])
    assert collecting["status"] == "READINESS_COLLECTION"


# ---------------------------------------------------------------------------
# The readiness package: RECEIVED -> STANDARDIZED and RECEIVED -> REJECTED
# ---------------------------------------------------------------------------
def _bank_with_one_account(
    client,
    cert_number,
    legal_name,
    tin_hash,
    depositor_name,
    account_number,
    balance_cents,
    ownership_category="SINGLE",
    book_asset_value_cents=10000000,
    estimated_liquidation_recovery_cents=4000000,
):
    """A registered institution holding one depositor with one loaded account."""
    institution = X.new_institution(
        client,
        cert_number=cert_number,
        legal_name=legal_name,
        book_asset_value_cents=book_asset_value_cents,
        estimated_liquidation_recovery_cents=estimated_liquidation_recovery_cents,
    )
    depositor = X.new_depositor(
        client, institution["id"], tin_hash=tin_hash, legal_name=depositor_name
    )
    account = X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number=account_number,
        ownership_category=ownership_category,
        balance_cents=balance_cents,
        accrued_interest_cents=0,
    )
    return institution, depositor, account


def test_standardizing_a_clean_package_promotes_it_and_its_institution(client):
    """A package whose records all parse and whose asserted total reconciles to the
    booked total reaches `STANDARDIZED` and carries its institution to
    `RESOLUTION_READY` with the deposit aggregates recomputed in the same request.

    PRD: "A `STANDARDIZED` package raises `readiness_standardized` to true, advances the institution from `READINESS_COLLECTION` to `RESOLUTION_READY`, and triggers a recompute of `total_deposit_balance_cents` and `depositor_record_count`, bumping the institution's `version`."

    Design: Corner/state_machines/valid_transition_standardize_promotes_submission_and_institution_to_resolution_ready
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution, _, _ = _bank_with_one_account(
        client,
        "61003",
        "Standardize Bank",
        "TIN-ST-1",
        "Bela Ortiz",
        "ST-0001",
        1000000,
    )
    submission = X.file_readiness(
        client,
        institution["id"],
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=1000000,
    )

    scored = X.standardize(client, submission["id"])
    assert_submission_scored(scored, "STANDARDIZED", 10000, 0, None)
    assert scored["version"] == 2

    ready = X.get_institution(client, institution["id"])
    assert_fields_equal(
        ready,
        {
            "status": "RESOLUTION_READY",
            "readiness_standardized": True,
            "total_deposit_balance_cents": 1000000,
            "depositor_record_count": 1,
        },
    )


def test_score_floor_rejection_beats_a_clean_variance(client):
    """A package with three malformed records in a hundred scores 9700 basis points
    and is rejected for the score floor even though its asserted total reconciles
    exactly, and the rejection leaves the institution untouched.

    PRD: "**First** the score floor: a `standardization_score_bps` below 9800 — that is, fewer than 98 percent of the delivered records parsing cleanly — rejects the package with `rejection_reason` `SCORE_BELOW_FLOOR`."

    Design: Corner/state_machines/fork_standardize_rejects_on_score_floor_and_on_total_variance
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution, _, _ = _bank_with_one_account(
        client,
        "61004",
        "Score Floor Bank",
        "TIN-RJ-1",
        "Cora Duval",
        "RJ-0001",
        1000000,
    )
    submission = X.file_readiness(
        client,
        institution["id"],
        file_format="VENDOR_CSV",
        record_count=100,
        malformed_record_count=3,
        reported_deposit_total_cents=1000000,
    )

    rejected = X.standardize(client, submission["id"])
    assert_submission_scored(rejected, "REJECTED", 9700, 0, "SCORE_BELOW_FLOOR")

    untouched = X.get_institution(client, institution["id"])
    assert_fields_equal(
        untouched,
        {"status": "READINESS_COLLECTION", "readiness_standardized": False},
    )


def test_variance_ceiling_rejects_a_cleanly_parsing_package(client):
    """A package every record of which parses is still rejected when the total it
    asserts overstates the booked total by a full percent, and the diagnostics are
    written before the gate fires.

    PRD: "**Then** the variance ceiling: a `deposit_total_variance_bps` above 25 — a discrepancy larger than a quarter of one percent of the booked total — rejects the package with `rejection_reason` `TOTAL_VARIANCE_EXCEEDED`."

    Design: Corner/state_machines/fork_standardize_rejects_on_score_floor_and_on_total_variance
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution, _, _ = _bank_with_one_account(
        client,
        "61005",
        "Variance Bank",
        "TIN-RJ-2",
        "Dane Whitlock",
        "RJ-0002",
        1000000,
    )
    submission = X.file_readiness(
        client,
        institution["id"],
        file_format="LEGACY_FIXED_WIDTH",
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=1010000,
    )

    rejected = X.standardize(client, submission["id"])
    assert_submission_scored(rejected, "REJECTED", 10000, 100, "TOTAL_VARIANCE_EXCEEDED")

    untouched = X.get_institution(client, institution["id"])
    assert_fields_equal(
        untouched,
        {"status": "READINESS_COLLECTION", "readiness_standardized": False},
    )


def test_second_standardize_on_a_standardized_package_is_refused(client):
    """`STANDARDIZED` is terminal for a readiness package, so a repeated scoring
    call is refused and neither re-runs the computation nor bumps the row.

    PRD: "Scoring a package that is no longer at `RECEIVED` is refused with `ERR_SUBMISSION_NOT_PENDING`; scoring is meaningful only while the institution is in `READINESS_COLLECTION`, since that is the phase the score is supposed to adjudicate."

    Design: Corner/state_machines/invalid_transition_standardize_on_already_standardized_submission_rejected
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution, _, _ = _bank_with_one_account(
        client,
        "61008",
        "Terminal Submission Bank",
        "TIN-TS-1",
        "Gustav Lind",
        "TS-0001",
        1000000,
    )
    submission = X.file_readiness(
        client,
        institution["id"],
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=1000000,
    )
    X.standardize(client, submission["id"])

    validate_error(
        client.standardize_submission(submission["id"], CLOSING_MANAGER),
        ERR_SUBMISSION_NOT_PENDING,
    )

    rows, _ = assert_page(
        client.list_readiness_submissions(
            institution["id"], CLOSING_MANAGER, params={"status": "STANDARDIZED"}
        ),
        expected_total=1,
    )
    assert rows[0]["version"] == 2


# ---------------------------------------------------------------------------
# Closing the charter: preconditions, idempotency and the freeze cascade
# ---------------------------------------------------------------------------
def test_close_without_a_standardized_package_is_refused(client):
    """An institution still collecting readiness cannot be closed, and the refused
    closing runs no part of the deposit-freeze cascade.

    PRD: "The institution must be at `status` `RESOLUTION_READY` with `readiness_standardized` true; an institution that is still at `PRE_FAILURE_MONITORING` or `READINESS_COLLECTION`, or whose standing readiness attestation has been lowered by a later package, is refused with `ERR_INSTITUTION_NOT_READY`"

    Design: Corner/state_machines/precondition_close_without_standardized_readiness_returns_not_ready
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution, _, account = _bank_with_one_account(
        client,
        "61006",
        "Not Ready Bank",
        "TIN-NR-1",
        "Efua Mensah",
        "NR-0001",
        1000000,
    )
    X.file_readiness(
        client,
        institution["id"],
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=1000000,
    )

    validate_error(
        client.close_institution(institution["id"], CLOSING_MANAGER),
        ERR_INSTITUTION_NOT_READY,
    )

    frozen_nothing = X.get_account(client, account["id"])
    assert frozen_nothing["insurance_status"] == "PENDING"

    still_collecting = X.get_institution(client, institution["id"])
    assert still_collecting["status"] == "READINESS_COLLECTION"
    _assert_unset(still_collecting, "failure_datetime")


def test_second_close_is_refused_and_keeps_the_first_failure_stamp(client):
    """Closing an institution that is already in receivership is refused, and the
    failure instant recorded by the first closing survives a later clock.

    PRD: "while an institution already at `CLOSED_IN_RECEIVERSHIP`, `RESOLUTION_COMPLETE` or `RECEIVERSHIP_TERMINATED` is refused with `ERR_INSTITUTION_ALREADY_CLOSED` — the guard that makes a repeated closing safe."

    Design: Corner/state_machines/idempotency_second_close_returns_institution_already_closed
    """
    estate = X.single_account_estate(
        client,
        1000000,
        account_number="DC-0001",
        clock=BUILD_CLOCK,
        depositor_name="Fatima Noor",
        cert_number="61007",
        legal_name="Double Close Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    closed = estate["institution"]
    assert closed["status"] == "CLOSED_IN_RECEIVERSHIP"
    assert_instant(closed["failure_datetime"], BUILD_CLOCK)
    version_after_close = closed["version"]

    X.advance_clock(client, LATE_CLOCK)
    validate_error(
        client.close_institution(closed["id"], CLOSING_MANAGER),
        ERR_INSTITUTION_ALREADY_CLOSED,
    )

    reread = X.get_institution(client, closed["id"])
    assert_instant(reread["failure_datetime"], BUILD_CLOCK)
    assert reread["status"] == "CLOSED_IN_RECEIVERSHIP"
    assert reread["version"] == version_after_close


def test_close_freezes_only_the_closing_institutions_pending_accounts(client):
    """The closing cascade flips every pending account of the closing institution
    whatever its ownership category, and reaches no account of another institution.

    PRD: "Because the institution closed, the closing then cascades into the deposit file: every deposit account of that institution whose `insurance_status` is `PENDING` flips to `FROZEN_FOR_DETERMINATION`, each such account having its own `updated_at` refreshed and its own `version` bumped, and the institution's `version` is bumped once for the closing itself."

    Design: Corner/state_machines/cascade_down_close_freezes_only_this_institutions_pending_accounts
    """
    X.advance_clock(client, BUILD_CLOCK)
    closing, closing_depositor, _ = _bank_with_one_account(
        client,
        "61009",
        "Cascade Source Bank",
        "TIN-CS-1",
        "Hina Sato",
        "CS-0001",
        500000,
    )
    X.new_account(
        client,
        closing["id"],
        closing_depositor["id"],
        account_number="CS-0002",
        ownership_category="RETIREMENT",
        balance_cents=300000,
        accrued_interest_cents=0,
        opened_at="2024-04-01T00:00:00Z",
    )
    submission = X.file_readiness(
        client,
        closing["id"],
        record_count=2,
        malformed_record_count=0,
        reported_deposit_total_cents=800000,
    )
    X.standardize(client, submission["id"])

    _, _, outsider_account = _bank_with_one_account(
        client,
        "61010",
        "Untouched Bank",
        "TIN-CS-2",
        "Ivan Petrov",
        "CS-0003",
        900000,
        book_asset_value_cents=5000000,
        estimated_liquidation_recovery_cents=2000000,
    )

    closed = X.close_charter(client, closing["id"])
    assert_fields_equal(
        closed,
        {
            "status": "CLOSED_IN_RECEIVERSHIP",
            "total_deposit_balance_cents": 800000,
            "depositor_record_count": 1,
        },
    )
    assert_instant(closed["failure_datetime"], BUILD_CLOCK)

    assert (
        total_count(
            client.list_deposit_accounts(
                CLOSING_MANAGER,
                params={
                    "institution_id": closing["id"],
                    "insurance_status": "FROZEN_FOR_DETERMINATION",
                },
            )
        )
        == 2
    )

    outsider = X.get_account(client, outsider_account["id"])
    assert outsider["insurance_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Certification: the conditional cascade and the aggregate it recomputes
# ---------------------------------------------------------------------------
def test_certifying_a_fully_insured_depositor_skips_holds_and_the_certificate(client):
    """A depositor whose whole balance sits below the standard maximum is certified
    without a hold and without a receivership certificate, and the notice goes out
    under the fully insured template.

    PRD: "When the determination's `uninsured_amount_cents` is exactly zero, the third and fourth levels are skipped entirely — no account is touched, every `hold_status` stays `NONE`, and no receivership certificate is created at all — while the fifth level still runs, sending the notice with `notice_template_code` `FULLY_INSURED` instead."

    Design: Corner/state_machines/conditional_cascade_zero_uninsured_certify_skips_holds_and_certificate
    """
    estate = X.single_account_estate(
        client,
        1000000,
        account_number="FI-0001",
        clock=BUILD_CLOCK,
        depositor_name="Jonas Weber",
        cert_number="61011",
        legal_name="Fully Insured Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )

    certified = X.certified_determination(client, estate["depositor"]["id"])
    assert certified["status"] == "CERTIFIED"
    assert_determination_amounts(certified, 1000000, 0, 1000000)
    assert certified["certified_by_user_id"] == C.CERTIFIER_USER_ID
    assert_instant(certified["certified_at"], BUILD_CLOCK)

    account = X.get_account(client, estate["account"]["id"])
    assert_account_dimensions(
        account, "DETERMINED", "NONE", "PENDING", held_amount_cents=0
    )

    assert (
        total_count(
            client.list_certificates(
                CLAIMS_CERTIFIER, params={"institution_id": estate["institution"]["id"]}
            )
        )
        == 0
    )

    depositor = X.get_depositor(client, estate["depositor"]["id"])
    assert_fields_equal(
        depositor,
        {
            "notice_status": "SENT",
            "notice_template_code": "FULLY_INSURED",
            "certified_insured_cents": 1000000,
            "certified_uninsured_cents": 0,
        },
    )
    assert_instant(depositor["notice_sent_at"], BUILD_CLOCK)

    institution = X.get_institution(client, estate["institution"]["id"])
    assert_fields_equal(
        institution,
        {"aggregate_certificate_face_cents": 0, "uninsured_claim_count": 0},
    )


def test_aggregate_insured_counts_only_certified_determinations(client):
    """The institution's aggregate insured figure reads zero while the determination
    is still under review and the depositor's full balance the instant it is
    certified, with both conservation deltas staying at zero across the write.

    PRD: "`aggregate_insured_cents` is the sum of `insured_amount_cents` over the institution's determinations that are currently certified, and only those."

    Design: Corner/state_machines/ledger_sync_certify_recomputes_institution_aggregate_insured
    """
    estate = X.single_account_estate(
        client,
        1200000,
        account_number="LS-0001",
        clock=BUILD_CLOCK,
        depositor_name="Kira Novak",
        cert_number="61012",
        legal_name="Ledger Sync Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    institution_id = estate["institution"]["id"]
    determination = X.determination_under_review(client, estate["depositor"]["id"])
    assert determination["status"] == "UNDER_REVIEW"

    before = X.insurance_summary(client, institution_id, RESOLUTION_ANALYST)
    assert_summary(
        before,
        aggregate_insured_cents=0,
        total_deposit_balance_cents=1200000,
        attributed_total_cents=1200000,
        unattributed_balance_cents=0,
    )
    assert_conservation_identities_hold(before)

    X.certify(client, determination["id"])

    after = X.insurance_summary(client, institution_id, RESOLUTION_ANALYST)
    assert_summary(
        after,
        aggregate_insured_cents=1200000,
        held_amount_total_cents=0,
        aggregate_certificate_face_cents=0,
    )
    assert_conservation_identities_hold(after)


# ---------------------------------------------------------------------------
# The least-cost test: the screening fork and the award join
# ---------------------------------------------------------------------------
def _marketed_bank_with_one_account(
    client, cert_number, legal_name, tin_hash, depositor_name, account_number, balance_cents
):
    """A closed institution holding one account, with its franchise marketing open."""
    institution, depositor, account = _bank_with_one_account(
        client,
        cert_number,
        legal_name,
        tin_hash,
        depositor_name,
        account_number,
        balance_cents,
        book_asset_value_cents=12000000,
        estimated_liquidation_recovery_cents=6000000,
    )
    submission = X.file_readiness(
        client,
        institution["id"],
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=balance_cents,
    )
    X.standardize(client, submission["id"])
    X.close_charter(client, institution["id"])
    return institution, depositor, account


def test_evaluation_forks_submitted_bids_into_conforming_and_non_conforming(client):
    """One evaluation prices the clean bid, screens the over-retained bid out for
    breaching the retention cap and the insured-only bid out for an estate with no
    certified insured deposits, and computes the liquidation baseline.

    PRD: "A bid failing any screen moves `SUBMITTED` → `NON_CONFORMING`, stores its `non_conformance_reason`, has **no** cost calculation run at all so that `evaluated_cost_cents` stays unset, and does not increment `conforming_bid_count`."

    Design: Corner/state_machines/branching_fork_evaluate_splits_bids_into_conforming_and_non_conforming
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution, _, _ = _marketed_bank_with_one_account(
        client, "61013", "Fork Bank", "TIN-FK2-1", "Lena Farrow", "FK2-0001", 20000000
    )
    X.open_marketing(client, institution["id"], BID_DEADLINE)

    clean_bidder = X.new_qualified_bidder(
        client,
        legal_name="Cascadia Acquirer",
        cert_number="61014",
        tier1_capital_ratio_bps=1400,
        camels_composite=2,
    )
    retention_bidder = X.new_qualified_bidder(
        client,
        legal_name="Retention Heavy Acquirer",
        cert_number="61015",
        tier1_capital_ratio_bps=1500,
        camels_composite=1,
    )
    insured_only_bidder = X.new_qualified_bidder(
        client,
        legal_name="Insured Only Acquirer",
        cert_number="61016",
        tier1_capital_ratio_bps=1300,
        camels_composite=2,
    )

    clean_bid = X.new_bid(
        client,
        institution["id"],
        clean_bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1500,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-04T09:00:00Z",
        data_room_window_end="2026-08-04T10:00:00Z",
    )
    over_retained_bid = X.new_bid(
        client,
        institution["id"],
        retention_bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=300,
        asset_discount_bps=1500,
        asset_retention_pool_cents=6000001,
        data_room_window_start="2026-08-04T12:00:00Z",
        data_room_window_end="2026-08-04T13:00:00Z",
    )
    insured_only_bid = X.new_bid(
        client,
        institution["id"],
        insured_only_bidder["id"],
        structure="INSURED_DEPOSITS_ONLY_PA",
        deposit_premium_bps=250,
        asset_discount_bps=1500,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-04T15:00:00Z",
        data_room_window_end="2026-08-04T16:00:00Z",
    )

    evaluated = X.evaluate_least_cost(client, institution["id"], "EXPECTED_LOSS_SHARE")
    assert_fields_equal(
        evaluated,
        {
            "least_cost_status": "EVALUATED",
            "least_cost_test_variant": "EXPECTED_LOSS_SHARE",
            "liquidation_baseline_cents": 150000,
            "conforming_bid_count": 1,
        },
    )

    priced = X.get_bid(client, clean_bid["id"])
    assert priced["status"] == "CONFORMING"
    _assert_unset(priced, "non_conformance_reason")
    assert_bid_costs(priced, 20000000, 9400000, 0, 0, 9400000)

    screened_retention = X.get_bid(client, over_retained_bid["id"])
    assert_fields_equal(
        screened_retention,
        {"status": "NON_CONFORMING", "non_conformance_reason": "RETENTION_POOL_ABOVE_CAP"},
    )
    assert_no_cost_calculation(screened_retention)
    _assert_unset(screened_retention, "pre_fee_cost_cents")

    screened_insured_only = X.get_bid(client, insured_only_bid["id"])
    assert_fields_equal(
        screened_insured_only,
        {
            "status": "NON_CONFORMING",
            "non_conformance_reason": "INSURED_ONLY_WITHOUT_CERTIFIED_DETERMINATIONS",
        },
    )
    assert_no_cost_calculation(screened_insured_only)


def test_award_picks_the_cheapest_conforming_bid_and_rejects_every_sibling(client):
    """The award joins the priced bids into one winner, rejects the pricier
    conforming bid and the screened-out bid alike, transfers the determined
    unheld account, and readies the planned branch, which may then cycle back.

    PRD: "**Second**, because a winner now exists, every other bid still at `CONFORMING` or `NON_CONFORMING` moves to `REJECTED`."

    Design: Corner/state_machines/join_award_selects_least_cost_bid_and_rejects_every_sibling
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution, depositor, account = _marketed_bank_with_one_account(
        client, "61017", "Join Bank", "TIN-JN-1", "Marek Dvorak", "JN-0001", 20000000
    )
    X.certified_determination(client, depositor["id"])

    branch = X.new_branch_reopening(
        client,
        institution["id"],
        branch_code="BR-1",
        reopen_window_start="2026-08-05T09:00:00Z",
        reopen_window_end="2026-08-05T17:00:00Z",
        staffing_headcount=12,
    )
    X.open_marketing(client, institution["id"], BID_DEADLINE)

    cheapest = X.new_qualified_bidder(
        client,
        legal_name="Cheapest Acquirer",
        cert_number="61018",
        tier1_capital_ratio_bps=1400,
        camels_composite=2,
    )
    pricier = X.new_qualified_bidder(
        client,
        legal_name="Pricier Acquirer",
        cert_number="61019",
        tier1_capital_ratio_bps=1500,
        camels_composite=1,
    )
    screened = X.new_qualified_bidder(
        client,
        legal_name="Screened Out Acquirer",
        cert_number="61020",
        tier1_capital_ratio_bps=1600,
        camels_composite=2,
    )

    cheapest_bid = X.new_bid(
        client,
        institution["id"],
        cheapest["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1500,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-04T09:00:00Z",
        data_room_window_end="2026-08-04T10:00:00Z",
    )
    pricier_bid = X.new_bid(
        client,
        institution["id"],
        pricier["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=100,
        asset_discount_bps=1500,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-04T12:00:00Z",
        data_room_window_end="2026-08-04T13:00:00Z",
    )
    X.new_bid(
        client,
        institution["id"],
        screened["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=300,
        asset_discount_bps=1500,
        asset_retention_pool_cents=6000001,
        data_room_window_start="2026-08-04T15:00:00Z",
        data_room_window_end="2026-08-04T16:00:00Z",
    )
    X.evaluate_least_cost(client, institution["id"], "EXPECTED_LOSS_SHARE")

    awarded = X.award_least_cost(client, institution["id"])
    assert_fields_equal(
        awarded,
        {
            "least_cost_status": "AWARDED",
            "resolution_method": "WHOLE_BANK_PA",
            "status": "RESOLUTION_COMPLETE",
            "liquidation_baseline_cents": 14150000,
            "conforming_bid_count": 2,
        },
    )

    winner = X.get_bid(client, cheapest_bid["id"])
    assert_fields_equal(
        winner, {"status": "WINNER", "evaluated_cost_cents": 9400000}
    )
    loser = X.get_bid(client, pricier_bid["id"])
    assert_fields_equal(
        loser, {"status": "REJECTED", "evaluated_cost_cents": 9600000}
    )
    assert (
        total_count(
            client.list_bids(
                RESOLUTION_ANALYST,
                params={"institution_id": institution["id"], "status": "REJECTED"},
            )
        )
        == 2
    )

    transferred = X.get_account(client, account["id"])
    assert_account_dimensions(transferred, "DETERMINED", "NONE", "TRANSFERRED")

    readied = X.get_branch_reopening(client, branch["id"])
    assert_fields_equal(readied, {"status": "READY", "reschedule_count": 0})

    cycled = validate_success(
        client.reschedule_branch_reopening(
            branch["id"],
            F.reschedule_payload("2026-08-06T09:00:00Z", "2026-08-06T17:00:00Z"),
            CLOSING_MANAGER,
        ),
        200,
    )
    assert_fields_equal(cycled, {"status": "PLANNED", "reschedule_count": 1})


# ---------------------------------------------------------------------------
# The branch window self-loop
# ---------------------------------------------------------------------------
def test_rescheduling_twice_keeps_the_branch_planned_and_counts_both_moves(client):
    """A planned branch window may be moved again and again: each move overwrites
    both endpoints, increments the reschedule count and leaves the row planned,
    never reopened, and the row never collides with its own former window.

    PRD: "It overwrites both endpoints, increments `reschedule_count` by one, bumps the `version`, and returns the reopening to `status` `PLANNED` — including from `READY`, which is the cycle `PLANNED` → `READY` → `PLANNED`."

    Design: Corner/state_machines/cyclic_reschedule_self_loop_accumulates_reschedule_count
    """
    X.advance_clock(client, BUILD_CLOCK)
    institution = X.new_institution(
        client,
        cert_number="61021",
        legal_name="Reschedule Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    branch = X.new_branch_reopening(
        client,
        institution["id"],
        branch_code="BR-9",
        reopen_window_start="2026-08-05T09:00:00Z",
        reopen_window_end="2026-08-05T17:00:00Z",
        staffing_headcount=8,
    )
    assert_fields_equal(branch, {"status": "PLANNED", "reschedule_count": 0})

    first = validate_success(
        client.reschedule_branch_reopening(
            branch["id"],
            F.reschedule_payload("2026-08-06T09:00:00Z", "2026-08-06T17:00:00Z"),
            CLOSING_MANAGER,
        ),
        200,
    )
    assert_fields_equal(first, {"status": "PLANNED", "reschedule_count": 1})
    assert_instant(first["reopen_window_start"], "2026-08-06T09:00:00Z")

    second = validate_success(
        client.reschedule_branch_reopening(
            branch["id"],
            F.reschedule_payload("2026-08-07T09:00:00Z", "2026-08-07T17:00:00Z"),
            CLOSING_MANAGER,
        ),
        200,
    )
    assert_fields_equal(second, {"status": "PLANNED", "reschedule_count": 2})
    assert_instant(second["reopen_window_start"], "2026-08-07T09:00:00Z")
    assert_instant(second["reopen_window_end"], "2026-08-07T17:00:00Z")
    _assert_unset(second, "reopened_at")


# ---------------------------------------------------------------------------
# The terminated estate
# ---------------------------------------------------------------------------
def test_a_terminated_receivership_refuses_close_and_a_second_termination(client):
    """An estate walked all the way to a terminated receivership offers no further
    transition: closing it again is refused as already closed and terminating it
    again is refused as no longer terminable.

    PRD: "Termination moves the institution's `status` `RESOLUTION_COMPLETE` → the terminal `RECEIVERSHIP_TERMINATED` and bumps its `version`."

    Design: Corner/state_machines/terminal_state_lockdown_terminated_receivership_refuses_close_and_second_terminate
    """
    estate = X.single_account_estate(
        client,
        1000000,
        account_number="TT-0001",
        clock=BUILD_CLOCK,
        depositor_name="Nadia Rahman",
        cert_number="61022",
        legal_name="Terminated Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    institution_id = estate["institution"]["id"]
    X.open_marketing(client, institution_id, BID_DEADLINE)
    X.evaluate_least_cost(client, institution_id, "RETENTION_ADJUSTED")

    failed = X.award_least_cost(client, institution_id)
    assert_fields_equal(
        failed,
        {
            "least_cost_status": "FAILED_ALL_BIDS",
            "resolution_method": "DEPOSIT_PAYOFF",
            "status": "RESOLUTION_COMPLETE",
            "conforming_bid_count": 0,
            "liquidation_baseline_cents": 150000,
        },
    )

    terminated = validate_success(
        client.terminate_receivership(institution_id, RECEIVERSHIP_TRUSTEE), 200
    )
    assert terminated["status"] == "RECEIVERSHIP_TERMINATED"

    validate_error(
        client.close_institution(institution_id, CLOSING_MANAGER),
        ERR_INSTITUTION_ALREADY_CLOSED,
    )
    validate_error(
        client.terminate_receivership(institution_id, RECEIVERSHIP_TRUSTEE),
        ERR_RECEIVERSHIP_NOT_TERMINABLE,
    )

    unchanged = X.get_institution(client, institution_id)
    assert unchanged["status"] == "RECEIVERSHIP_TERMINATED"
