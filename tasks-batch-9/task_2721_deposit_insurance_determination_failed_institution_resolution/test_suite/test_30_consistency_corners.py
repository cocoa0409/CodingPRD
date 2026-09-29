"""Consistency corners: every cascade is complete before the response is written.

Operations in this API are cascading, and the cascade is applied in full within the
request or not at all — there is no background settlement to wait for.  Each test
here fires one multi-level cascade and then reads every entity family it touched,
including from roles that took no part in the operation, asserting that the first
read already carries the final value and that reading again does not change it.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_bid_costs,
    assert_certificate,
    assert_conservation_identities_hold,
    assert_determination_amounts,
    assert_fields_equal,
    assert_instant,
    assert_page,
    assert_summary,
)
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLAIMS_CERTIFIER,
    RECEIVERSHIP_TRUSTEE,
    RESOLUTION_ANALYST,
    make_bidder_headers,
    make_claims_agent_headers,
    make_claims_certifier_headers,
    make_depositor_headers,
)


def test_certify_publishes_every_derived_field_in_the_same_request_with_no_read_delay(
    client,
):
    """Certification writes across the determination, the account, a new receivership
    certificate, the depositor's denormalized totals and notice, and the institution's
    aggregates, and every one of those writes is already visible to the very next read;
    repeating the read returns identical values, so the read is not what settles them.

    PRD: "There is no eventual consistency and no background settlement — a read issued immediately after a mutation observes every consequence of that mutation."

    Design: Corner/consistency_model/certify_publishes_every_derived_field_in_the_same_request_with_no_read_delay
    """
    estate = X.single_account_estate(
        client,
        30000000,
        account_number="IC-0001",
        cert_number="61088",
        legal_name="Immediate Certify Bank",
        charter_state="OK",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
        depositor_name="Cora Lindqvist",
    )
    institution_id = estate["institution"]["id"]
    depositor_id = estate["depositor"]["id"]
    account_id = estate["account"]["id"]

    determination = X.open_determination(
        client, depositor_id, headers=make_claims_agent_headers("U-AGENT-AE")
    )
    X.prepare(client, determination["id"], "AGGREGATE_BY_CATEGORY", user_id="U-AGENT-AE")
    X.submit_review(client, determination["id"], user_id="U-AGENT-AE")

    # One request fires the whole cascade, and its own response already carries the
    # certified position.
    certified = validate_success(
        client.certify_determination(
            determination["id"], make_claims_certifier_headers("U-CERT-AE")
        ),
        200,
    )
    assert_fields_equal(
        certified, {"status": "CERTIFIED", "certified_by_user_id": "U-CERT-AE"}
    )
    assert_determination_amounts(certified, 25000000, 5000000, 30000000)
    assert_instant(certified["certified_at"], C.SETUP_CLOCK)

    # The account's determination and hold dimensions on the first read after certify.
    account = X.get_account(client, account_id)
    assert_account_dimensions(
        account,
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=5000000,
        attributed_amount_cents=30000000,
    )

    # The certificate the cascade issued is discoverable immediately.
    rows, _ = assert_page(
        client.list_certificates(
            CLAIMS_AGENT, params={"depositor_record_id": depositor_id}
        ),
        expected_total=1,
    )
    certificate = rows[0]
    assert_certificate(certificate, "ISSUED", 5000000)
    assert_instant(certificate["issued_at"], C.SETUP_CLOCK)

    # The depositor's denormalized totals and queued notice, read by the depositor itself.
    depositor = validate_success(
        client.get_depositor_record(depositor_id, make_depositor_headers(depositor_id)),
        200,
    )
    assert_fields_equal(
        depositor,
        {
            "certified_insured_cents": 25000000,
            "certified_uninsured_cents": 5000000,
            "notice_status": "SENT",
            "notice_template_code": "PARTIALLY_UNINSURED",
        },
    )
    assert_instant(depositor["notice_sent_at"], C.SETUP_CLOCK)

    # The institution's aggregates reconcile, recomputed from the underlying rows.
    summary = X.insurance_summary(client, institution_id, RECEIVERSHIP_TRUSTEE)
    assert_summary(
        summary,
        aggregate_insured_cents=25000000,
        aggregate_certificate_face_cents=5000000,
        uninsured_claim_count=1,
        held_amount_total_cents=5000000,
    )
    assert_conservation_identities_hold(summary)

    # The certificate is issued but untouched by any dividend.
    certificate_again = validate_success(
        client.get_certificate(certificate["id"], CLAIMS_CERTIFIER), 200
    )
    assert_certificate(
        certificate_again,
        "ISSUED",
        5000000,
        cumulative_dividends_cents=0,
        last_dividend_amount_cents=0,
        last_dividend_round=0,
    )

    # Reading the recomputed summary a second time returns the same figures: repeated
    # reads neither settle nor drift the aggregates.
    assert (
        X.insurance_summary(client, institution_id, RECEIVERSHIP_TRUSTEE) == summary
    ), "the recomputed insurance summary drifted between two consecutive reads"


def test_the_award_cascade_is_visible_to_every_role_immediately_after_the_awarding_request(
    client,
):
    """The award mutates the winning bid, the institution's lifecycle and least-cost
    dimensions, the transferred deposit account and the planned branch reopening in one
    request, and each of those is readable by the role that owns it — and by a role that
    took no part in it — on the very next call, with no read-after-write lag.

    PRD: "There is no eventual consistency and no background settlement — a read issued immediately after a mutation observes every consequence of that mutation."

    Design: Corner/consistency_model/the_award_cascade_is_visible_to_every_role_immediately_after_the_awarding_request
    """
    estate = X.single_account_estate(
        client,
        20000000,
        account_number="IA-0001",
        cert_number="61089",
        legal_name="Immediate Award Bank",
        charter_state="UT",
        book_asset_value_cents=12000000,
        estimated_liquidation_recovery_cents=6000000,
        depositor_name="Dmitri Kovalenko",
    )
    institution_id = estate["institution"]["id"]
    depositor_id = estate["depositor"]["id"]
    account_id = estate["account"]["id"]

    # A fully insured depositor: 20000000 sits under one standard maximum, so no hold
    # is placed and the account is eligible for the transition cascade.
    X.certified_determination(client, depositor_id)
    branch = X.new_branch_reopening(
        client,
        institution_id,
        branch_code="BR-A01",
        reopen_window_start="2026-08-14T09:00:00Z",
        reopen_window_end="2026-08-14T17:00:00Z",
        staffing_headcount=6,
    )
    X.open_marketing(client, institution_id, "2026-08-12T00:00:00Z")
    bidder = X.new_qualified_bidder(
        client,
        legal_name="Halcyon Acquirer",
        cert_number="62016",
        tier1_capital_ratio_bps=2300,
        camels_composite=1,
    )
    bid = X.new_bid(
        client,
        institution_id,
        bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1500,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-06T09:00:00Z",
        data_room_window_end="2026-08-06T10:00:00Z",
    )
    X.evaluate_least_cost(client, institution_id, "EXPECTED_LOSS_SHARE")

    # The awarding response already reflects the whole cascade.
    awarded = validate_success(
        client.award_least_cost_test(institution_id, RESOLUTION_ANALYST), 200
    )
    assert_fields_equal(
        awarded,
        {
            "status": "RESOLUTION_COMPLETE",
            "least_cost_status": "AWARDED",
            "resolution_method": "WHOLE_BANK_PA",
            "liquidation_baseline_cents": 14150000,
            "conforming_bid_count": 1,
        },
    )

    # The analyst's own view of the bid it awarded.
    won = X.get_bid(client, bid["id"])
    assert won["status"] == "WINNER", won
    assert_bid_costs(won, 20000000, 9400000, 0, 0, 9400000)

    # The branch was flipped by the same request that transferred the account.
    ready_branch = X.get_branch_reopening(client, branch["id"])
    assert_fields_equal(
        ready_branch, {"status": "READY", "reschedule_count": 0, "reopened_at": None}
    )

    # The claims side sees the transition dimension advance without touching the others.
    account = X.get_account(client, account_id)
    assert_account_dimensions(account, "DETERMINED", "NONE", "TRANSFERRED")

    # The trustee sees the pinned variant and the completed lifecycle.
    institution = X.get_institution(client, institution_id, RECEIVERSHIP_TRUSTEE)
    assert_fields_equal(
        institution,
        {
            "status": "RESOLUTION_COMPLETE",
            "least_cost_test_variant": "EXPECTED_LOSS_SHARE",
        },
    )

    # The cascade is equally visible to a role that took no part in it.
    rows, _ = assert_page(
        client.list_branch_reopenings(
            institution_id,
            make_depositor_headers(depositor_id),
            params={"status": "READY"},
        ),
        expected_total=1,
    )
    assert [row["id"] for row in rows] == [branch["id"]], rows

    # And the conservation identities still hold for the estate.
    summary = validate_success(
        client.get_insurance_summary(institution_id, make_bidder_headers(bidder["id"])),
        200,
    )
    assert_summary(
        summary,
        aggregate_insured_cents=20000000,
        uninsured_claim_count=0,
        held_amount_total_cents=0,
    )
    assert_conservation_identities_hold(summary)
