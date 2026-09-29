"""Endpoint corners of the Deposit Insurance Resolution API.

The tests here exercise the published read and action surface rather than the
arithmetic behind it: how the two heaviest list endpoints compose their filters
with the pagination contract, how the ownership-interest junction reads from both
of its sides, what a bid withdrawal frees up and what a branch reschedule counts,
and what the computed insurance-summary read reports at each stage of a
determination.  Every test builds its own rows against an empty database whose
logical clock reads the instant the service started at.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_BID_NOT_WITHDRAWABLE,
    ERR_BRANCH_NOT_READY,
    ERR_DATA_ROOM_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_determination_amounts,
    assert_fields_equal,
    assert_immutable_record_fields,
    assert_instant,
    assert_page,
    assert_summary,
    ids_of,
)
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLOSING_MANAGER,
    RESOLUTION_ANALYST,
    make_bidder_headers,
)


def test_institution_listing_composes_filters_with_limit_and_offset_pagination(client):
    """Listing institutions intersects the status and charter filters rather than
    letting one replace the other, and reports `total_count` for the filtered
    population while `has_more` tracks only the page boundary.

    PRD: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts every resource matching the request's filters — not merely those on the returned page — and `has_more` indicates whether any matching resource remains beyond the current page."

    Design: Corner/endpoints/institution_listing_composes_filters_with_limit_and_offset_pagination
    """
    X.open_at_setup_clock(client)

    charters = [("61066", "DE"), ("61067", "DE"), ("61068", "NY"), ("61069", "NY")]
    registered = [
        X.new_institution(
            client,
            cert_number=cert_number,
            legal_name=f"Page Bank {cert_number}",
            charter_state=charter_state,
            book_asset_value_cents=5000000,
            estimated_liquidation_recovery_cents=2000000,
        )
        for cert_number, charter_state in charters
    ]

    # Receiving the very first package advances that one institution out of
    # `PRE_FAILURE_MONITORING` and into `READINESS_COLLECTION` (PRD 3.1).
    X.file_readiness(
        client,
        registered[0]["id"],
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=0,
    )

    # The unfiltered default page: limit 10 and offset 0 are the declared defaults.
    rows, meta = assert_page(client.list_institutions(CLOSING_MANAGER), expected_total=4)
    assert len(rows) == 4, ids_of(rows)
    assert_fields_equal(meta, {"limit": 10, "offset": 0, "has_more": False})

    # A status filter drops the one institution now in readiness collection.
    rows, _ = assert_page(
        client.list_institutions(
            CLOSING_MANAGER, params={"status": "PRE_FAILURE_MONITORING"}
        ),
        expected_total=3,
    )
    assert len(rows) == 3, ids_of(rows)
    assert all(row["status"] == "PRE_FAILURE_MONITORING" for row in rows), rows

    rows, _ = assert_page(
        client.list_institutions(CLOSING_MANAGER, params={"charter_state": "DE"}),
        expected_total=2,
    )
    assert len(rows) == 2, ids_of(rows)

    # Both filters apply at once, so only the DE institution in readiness collection
    # survives.
    rows, _ = assert_page(
        client.list_institutions(
            CLOSING_MANAGER,
            params={"charter_state": "DE", "status": "READINESS_COLLECTION"},
        ),
        expected_total=1,
    )
    assert len(rows) == 1, ids_of(rows)
    assert rows[0]["cert_number"] == "61066", rows[0]

    head, head_meta = assert_page(
        client.list_institutions(CLOSING_MANAGER, params={"limit": 2, "offset": 0}),
        expected_total=4,
    )
    assert len(head) == 2, ids_of(head)
    assert head_meta["has_more"] is True, head_meta

    tail, tail_meta = assert_page(
        client.list_institutions(CLOSING_MANAGER, params={"limit": 2, "offset": 2}),
        expected_total=4,
    )
    assert len(tail) == 2, ids_of(tail)
    assert tail_meta["has_more"] is False, tail_meta
    assert not set(ids_of(head)) & set(ids_of(tail)), (ids_of(head), ids_of(tail))

    # total_count still reports the filtered population, not the returned page.
    rows, meta = assert_page(
        client.list_institutions(
            CLOSING_MANAGER, params={"charter_state": "NY", "limit": 1, "offset": 0}
        ),
        expected_total=2,
    )
    assert len(rows) == 1, ids_of(rows)
    assert meta["has_more"] is True, meta

    rows, meta = assert_page(
        client.list_institutions(CLOSING_MANAGER, params={"charter_state": "AK"}),
        expected_total=0,
    )
    assert rows == [], rows
    assert meta["has_more"] is False, meta


def test_deposit_account_listing_filters_across_the_three_independent_status_dimensions(
    client,
):
    """The deposit-account collection exposes each of the three independent status
    dimensions as its own filter axis, and a valid enum member that matches nothing
    answers with an empty page rather than an error.

    PRD: "Deposit accounts are listed with optional `institution_id`, `primary_depositor_id`, `ownership_category`, `insurance_status`, `hold_status`, `transition_status` and `recordkeeping_status` filters."

    Design: Corner/endpoints/deposit_account_listing_filters_across_the_three_independent_status_dimensions
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61070",
        legal_name="Filter Axis Bank",
        charter_state="IL",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    gita = X.new_depositor(
        client, institution["id"], tin_hash="TIN-FA-1", legal_name="Gita Raman"
    )
    hikaru = X.new_depositor(
        client, institution["id"], tin_hash="TIN-FA-2", legal_name="Hikaru Ito"
    )
    gita_account = X.new_account(
        client,
        institution["id"],
        gita["id"],
        account_number="AC-0001",
        ownership_category="SINGLE",
        balance_cents=30000000,
    )
    hikaru_account = X.new_account(
        client,
        institution["id"],
        hikaru["id"],
        account_number="AC-0002",
        ownership_category="SINGLE",
        balance_cents=5000000,
    )
    X.make_resolution_ready(client, institution["id"], 35000000)
    X.close_charter(client, institution["id"])

    # Only Gita is certified: 30000000 pooled against one standard maximum reads
    # 25000000 insured and 5000000 uninsured, which is the hold on AC-0001.
    X.certified_determination(client, gita["id"])

    assert_account_dimensions(
        X.get_account(client, gita_account["id"]),
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=5000000,
    )
    # Hikaru was never determined, so closing left AC-0002 frozen with no hold.
    assert_account_dimensions(
        X.get_account(client, hikaru_account["id"]),
        "FROZEN_FOR_DETERMINATION",
        "NONE",
        "PENDING",
        held_amount_cents=0,
    )

    rows, _ = assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT, params={"institution_id": institution["id"]}
        ),
        expected_total=2,
    )
    assert len(rows) == 2, ids_of(rows)

    rows, _ = assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT,
            params={
                "institution_id": institution["id"],
                "insurance_status": "DETERMINED",
            },
        ),
        expected_total=1,
        expected_ids=[gita_account["id"]],
    )
    assert rows[0]["held_amount_cents"] == 5000000, rows[0]

    assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT,
            params={"institution_id": institution["id"], "hold_status": "HELD"},
        ),
        expected_total=1,
        expected_ids=[gita_account["id"]],
    )

    rows, _ = assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT,
            params={
                "institution_id": institution["id"],
                "primary_depositor_id": hikaru["id"],
            },
        ),
        expected_total=1,
        expected_ids=[hikaru_account["id"]],
    )
    assert rows[0]["insurance_status"] == "FROZEN_FOR_DETERMINATION", rows[0]

    # The determination dimension and the hold dimension intersect.
    assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT,
            params={
                "institution_id": institution["id"],
                "insurance_status": "FROZEN_FOR_DETERMINATION",
                "hold_status": "NONE",
            },
        ),
        expected_total=1,
        expected_ids=[hikaru_account["id"]],
    )

    # A declared ownership category with no matching row is an empty page, not an error.
    rows, _ = assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT,
            params={"institution_id": institution["id"], "ownership_category": "JOINT"},
        ),
        expected_total=0,
    )
    assert rows == [], rows

    # No award has run, so the transition dimension still holds both accounts.
    rows, meta = assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT,
            params={
                "institution_id": institution["id"],
                "transition_status": "PENDING",
                "limit": 1,
                "offset": 1,
            },
        ),
        expected_total=2,
    )
    assert len(rows) == 1, ids_of(rows)
    assert meta["has_more"] is False, meta


def test_ownership_interests_are_readable_from_both_sides_of_the_junction(client):
    """The same ownership-interest rows are reachable from the account they sit on and
    from the depositor they name, each view narrowing independently by
    `interest_role`, and attaching one bumps the parent account's version.

    PRD: "Ownership interests are readable both from the account side and from the depositor side, each with an optional `interest_role` filter."

    Design: Corner/endpoints/ownership_interests_are_readable_from_both_sides_of_the_junction
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61071",
        legal_name="Junction Read Bank",
        charter_state="OR",
        book_asset_value_cents=25000000,
        estimated_liquidation_recovery_cents=9000000,
    )
    ilya = X.new_depositor(
        client, institution["id"], tin_hash="TIN-JR-1", legal_name="Ilya Volkov"
    )
    jun = X.new_depositor(
        client, institution["id"], tin_hash="TIN-JR-2", legal_name="Jun Park"
    )
    kemal = X.new_depositor(
        client, institution["id"], tin_hash="TIN-JR-3", legal_name="Kemal Aslan"
    )
    joint = X.new_account(
        client,
        institution["id"],
        kemal["id"],
        account_number="JN-0001",
        ownership_category="JOINT",
        balance_cents=12000000,
    )
    trust = X.new_account(
        client,
        institution["id"],
        kemal["id"],
        account_number="TR-0001",
        ownership_category="REVOCABLE_TRUST",
        balance_cents=8000000,
    )
    assert joint["version"] == 1, joint

    # Co-owner shares summing to exactly 10000 bps, plus one trust beneficiary.
    X.new_interest(client, joint["id"], ilya["id"], "CO_OWNER", 6000)
    X.new_interest(client, joint["id"], jun["id"], "CO_OWNER", 4000)
    X.new_interest(client, trust["id"], ilya["id"], "BENEFICIARY", 10000)

    rows, _ = assert_page(
        client.list_account_ownership_interests(joint["id"], CLAIMS_AGENT),
        expected_total=2,
    )
    assert len(rows) == 2, rows
    assert all(row["interest_role"] == "CO_OWNER" for row in rows), rows
    assert sorted(row["designated_share_bps"] for row in rows) == [4000, 6000], rows
    for row in rows:
        # An ownership interest is an immutable assertion: no updated_at, no version.
        assert_immutable_record_fields(row)

    rows, _ = assert_page(
        client.list_account_ownership_interests(
            joint["id"], CLAIMS_AGENT, params={"interest_role": "BENEFICIARY"}
        ),
        expected_total=0,
    )
    assert rows == [], rows

    # The junction reads from the depositor side too: Ilya holds one row on each account.
    rows, _ = assert_page(
        client.list_depositor_ownership_interests(ilya["id"], CLAIMS_AGENT),
        expected_total=2,
    )
    assert sorted(row["interest_role"] for row in rows) == [
        "BENEFICIARY",
        "CO_OWNER",
    ], rows
    assert sorted(row["deposit_account_id"] for row in rows) == sorted(
        [joint["id"], trust["id"]]
    ), rows

    rows, _ = assert_page(
        client.list_depositor_ownership_interests(
            ilya["id"], CLAIMS_AGENT, params={"interest_role": "CO_OWNER"}
        ),
        expected_total=1,
    )
    assert rows[0]["deposit_account_id"] == joint["id"], rows[0]

    rows, _ = assert_page(
        client.list_depositor_ownership_interests(jun["id"], CLAIMS_AGENT),
        expected_total=1,
    )
    assert rows[0]["designated_share_bps"] == 4000, rows[0]

    # Attaching an interest bumps the version of the account it sits on.
    assert X.get_account(client, joint["id"])["version"] == 3, X.get_account(
        client, joint["id"]
    )


def test_bid_withdrawal_frees_its_data_room_interval_for_a_later_bidder(client):
    """A live data-room reservation blocks an overlapping one, and withdrawing the bid
    that held it releases the interval so the identical request then succeeds; the
    withdrawal itself is not repeatable.

    PRD: "A bidder may withdraw its own bid while it is still at `SUBMITTED`, which moves it `SUBMITTED` → `WITHDRAWN`, bumps its `version`, and frees the data-room interval so later reservations on the institution stop colliding with it."

    Design: Corner/endpoints/bid_withdrawal_frees_its_data_room_interval_for_a_later_bidder
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61072",
        legal_name="Data Room Bank",
        charter_state="NV",
        book_asset_value_cents=12000000,
        estimated_liquidation_recovery_cents=5000000,
    )
    depositor = X.new_depositor(
        client, institution["id"], tin_hash="TIN-DR-1", legal_name="Nadia Haddad"
    )
    X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="DR-0001",
        ownership_category="SINGLE",
        balance_cents=8000000,
    )
    X.make_resolution_ready(client, institution["id"], 8000000)
    X.close_charter(client, institution["id"])
    X.open_marketing(client, institution["id"], bid_deadline_at="2026-08-12T00:00:00Z")

    marcus = X.new_qualified_bidder(
        client,
        legal_name="Marcus Trust",
        cert_number="62011",
        tier1_capital_ratio_bps=1800,
        camels_composite=2,
    )
    lena = X.new_qualified_bidder(
        client,
        legal_name="Lena Federal",
        cert_number="62012",
        tier1_capital_ratio_bps=2400,
        camels_composite=1,
    )

    marcus_bid = X.new_bid(
        client,
        institution["id"],
        marcus["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=150,
        asset_discount_bps=1000,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-06T09:00:00Z",
        data_room_window_end="2026-08-06T10:00:00Z",
    )

    lena_payload = F.bid_payload(
        institution["id"],
        lena["id"],
        structure="INSURED_DEPOSITS_ONLY_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1200,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-06T09:30:00Z",
        data_room_window_end="2026-08-06T10:30:00Z",
    )
    lena_headers = make_bidder_headers(lena["id"])

    # Marcus's reservation is live while his bid is at `SUBMITTED`, and the mandatory
    # 60-minute buffer makes Lena's overlapping interval a conflict.
    validate_error(
        client.create_bid(lena_payload, lena_headers),
        ERR_DATA_ROOM_WINDOW_CONFLICT,
        409,
    )

    withdrawn = X.withdraw_bid(client, marcus_bid["id"], marcus["id"])
    assert_fields_equal(withdrawn, {"status": "WITHDRAWN"})
    assert withdrawn["version"] > marcus_bid["version"], withdrawn

    # A withdrawn bid's reservation stops blocking anything, so the same request lands.
    lena_bid = validate_success(client.create_bid(lena_payload, lena_headers), 201)
    assert_fields_equal(
        lena_bid, {"status": "SUBMITTED", "bidder_id": lena["id"]}
    )

    # Withdrawal is not idempotent: the bid is no longer at `SUBMITTED`.
    validate_error(
        client.withdraw_bid(marcus_bid["id"], make_bidder_headers(marcus["id"])),
        ERR_BID_NOT_WITHDRAWABLE,
        409,
    )

    assert_page(
        client.list_bids(
            RESOLUTION_ANALYST,
            params={"institution_id": institution["id"], "status": "WITHDRAWN"},
        ),
        expected_total=1,
        expected_ids=[marcus_bid["id"]],
    )


def test_branch_reschedule_counts_every_loop_and_holds_the_planned_state(client):
    """Rescheduling a branch window is a self-loop: the status stays `PLANNED` while
    `reschedule_count` and `version` climb, both endpoints are replaced outright, and
    the branch never drifts toward being reopenable.

    PRD: "It overwrites both endpoints, increments `reschedule_count` by one, bumps the `version`, and returns the reopening to `status` `PLANNED` — including from `READY`, which is the cycle `PLANNED` → `READY` → `PLANNED`."

    Design: Corner/endpoints/branch_reschedule_counts_every_loop_and_holds_the_planned_state
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61073",
        legal_name="Reschedule Loop Bank",
        charter_state="NM",
        book_asset_value_cents=9000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    depositor = X.new_depositor(
        client, institution["id"], tin_hash="TIN-RL-1", legal_name="Omar Diallo"
    )
    X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="RL-0001",
        ownership_category="SINGLE",
        balance_cents=6000000,
    )
    X.make_resolution_ready(client, institution["id"], 6000000)
    X.close_charter(client, institution["id"])

    branch = X.new_branch_reopening(
        client,
        institution["id"],
        branch_code="BR-MAIN",
        reopen_window_start="2026-08-10T09:00:00Z",
        reopen_window_end="2026-08-10T17:00:00Z",
        staffing_headcount=4,
    )

    planned = X.get_branch_reopening(client, branch["id"])
    assert_fields_equal(
        planned,
        {
            "status": "PLANNED",
            "reschedule_count": 0,
            "staffing_headcount": 4,
            "version": 1,
        },
    )
    assert planned["reopened_at"] is None, planned

    first = validate_success(
        client.reschedule_branch_reopening(
            branch["id"],
            F.reschedule_payload("2026-08-11T09:00:00Z", "2026-08-11T17:00:00Z"),
            CLOSING_MANAGER,
        ),
        200,
    )
    assert_fields_equal(first, {"status": "PLANNED", "reschedule_count": 1, "version": 2})
    assert_instant(first["reopen_window_start"], "2026-08-11T09:00:00Z")
    assert_instant(first["reopen_window_end"], "2026-08-11T17:00:00Z")

    second = validate_success(
        client.reschedule_branch_reopening(
            branch["id"],
            F.reschedule_payload("2026-08-12T09:00:00Z", "2026-08-12T17:00:00Z"),
            CLOSING_MANAGER,
        ),
        200,
    )
    assert_fields_equal(
        second, {"status": "PLANNED", "reschedule_count": 2, "version": 3}
    )
    assert_instant(second["reopen_window_start"], "2026-08-12T09:00:00Z")
    assert_instant(second["reopen_window_end"], "2026-08-12T17:00:00Z")
    assert second["reopened_at"] is None, second

    rows, _ = assert_page(
        client.list_branch_reopenings(
            institution["id"],
            CLOSING_MANAGER,
            params={"branch_code": "BR-MAIN", "status": "PLANNED"},
        ),
        expected_total=1,
        expected_ids=[branch["id"]],
    )
    assert rows[0]["reschedule_count"] == 2, rows[0]

    # `READY` is only ever conferred by the award cascade, never by a reschedule.
    validate_error(
        client.reopen_branch(branch["id"], CLOSING_MANAGER), ERR_BRANCH_NOT_READY, 409
    )


def test_insurance_summary_computed_read_moves_balance_from_unattributed_to_attributed(
    client,
):
    """The insurance summary is recomputed from the underlying rows on every read:
    preparation moves the depositor's balance from unattributed into attributed, and
    only certification publishes the insured aggregate, the claim and the hold — with
    both conservation deltas reading zero throughout.

    PRD: "Two identities must hold at every observable instant, and the API exposes both as signed deltas through a computed read on the institution so that a client, an auditor or a test can assert them directly."

    Design: Corner/endpoints/insurance_summary_computed_read_moves_balance_from_unattributed_to_attributed
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61074",
        legal_name="Summary Read Bank",
        charter_state="AZ",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    priya = X.new_depositor(
        client, institution["id"], tin_hash="TIN-SR-1", legal_name="Priya Nair"
    )
    X.new_account(
        client,
        institution["id"],
        priya["id"],
        account_number="SR-0001",
        ownership_category="SINGLE",
        balance_cents=30000000,
    )
    X.make_resolution_ready(client, institution["id"], 30000000)
    X.close_charter(client, institution["id"])
    determination = X.open_determination(client, priya["id"])

    # Nothing has been attributed yet, so the whole booked balance is unattributed.
    summary = X.insurance_summary(client, institution["id"])
    assert_summary(
        summary,
        institution_id=institution["id"],
        total_deposit_balance_cents=30000000,
        attributed_total_cents=0,
        unattributed_balance_cents=30000000,
        conservation_delta_cents=0,
        aggregate_insured_cents=0,
        aggregate_certificate_face_cents=0,
        uninsured_claim_count=0,
        held_amount_total_cents=0,
        receivership_cash_cents=0,
        cash_conservation_delta_cents=0,
    )

    prepared = X.prepare(client, determination["id"], "AGGREGATE_BY_CATEGORY")
    assert_determination_amounts(prepared, 25000000, 5000000, 30000000)

    # Preparation attributes the balance but publishes no coverage of its own.
    summary = X.insurance_summary(client, institution["id"])
    assert_summary(
        summary,
        attributed_total_cents=30000000,
        unattributed_balance_cents=0,
        conservation_delta_cents=0,
        aggregate_insured_cents=0,
        aggregate_certificate_face_cents=0,
        uninsured_claim_count=0,
        held_amount_total_cents=0,
    )

    X.submit_review(client, determination["id"])
    certified = X.certify(client, determination["id"])
    assert_fields_equal(certified, {"status": "CERTIFIED"})

    # Certification publishes the insured aggregate, the uninsured claim and the hold
    # in the same request, with both identities still balancing.
    summary = X.insurance_summary(client, institution["id"])
    assert_summary(
        summary,
        total_deposit_balance_cents=30000000,
        attributed_total_cents=30000000,
        unattributed_balance_cents=0,
        aggregate_insured_cents=25000000,
        aggregate_certificate_face_cents=5000000,
        uninsured_claim_count=1,
        held_amount_total_cents=5000000,
        conservation_delta_cents=0,
        cash_conservation_delta_cents=0,
    )
