"""Two reversals that unwind by compensation rather than by erasure: a withdrawn
records request that keeps its history while holding no money, and a rescinded
certificate of destruction that returns the custody triple exactly.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CITY_CLERK_ID,
    RECORDS_OFFICER,
    make_requester_headers,
)

FLAT_LINE = [f.fee_line(page_count=60, staff_minutes=45, delivery_medium="PAPER")]
RESCIND_REASON = "The cutoff date was applied to the wrong accession block."


def _request_holding_a_thousand_cent_deposit():
    """A FLAT_SCHEDULE fee of 1875 cents assessed, 1000 cents paid by the
    requester, leaving the money axis at DEPOSIT_HELD."""
    fx.set_clock("2026-08-03T09:00:00Z")
    request = fx.assessed_request(
        FLAT_LINE,
        fee_schedule_variant="FLAT_SCHEDULE",
        requester_name="Dara Nwosu",
        requester_email="dara@example.org",
        subject_description="Planning file for 44 Elm Street",
    )
    paid = validate_success(
        api_client.record_payment(
            request["id"], f.payment_payload(1000), make_requester_headers(request["id"])
        )
    )
    return paid


def test_the_deposit_leaves_the_city_holding_cash_against_an_open_balance():
    """Before any reversal, the ledger reads 1875 assessed against 1000 collected,
    so 875 is still owed and the cash position is 1000.

    PRD 3.8: "A payment that leaves a balance behind moves `fee_status` to
    `DEPOSIT_HELD`; a payment that settles the balance exactly moves it to
    `PAID`."

    Design: Difficulty/compensating_invariant/withdrawing_a_paid_records_request_waives_and_refunds_to_zero_cash
    """
    paid = _request_holding_a_thousand_cent_deposit()

    a.assert_fee_ledger(
        paid,
        assessed=1875,
        waived=0,
        collected=1000,
        refunded=0,
        balance=875,
        net_cash=1000,
    )
    a.assert_axes(paid, fulfillment_status="UNDER_REVIEW", fee_status="DEPOSIT_HELD")


def test_withdrawal_waives_and_refunds_to_zero_without_erasing_the_history():
    """The four stored counters end at 1875 / 1875 / 1000 / 1000, which drives both
    derived readings to exactly zero while what was charged and taken is still on
    the file.

    PRD 3.8: "`fulfillment_status` becomes `WITHDRAWN`, and the fee ledger is
    unwound by compensation rather than by deletion: `total_waived_cents` is set
    equal to `total_assessed_cents` and `refunded_cents` is set equal to
    `total_collected_cents`, which drives both derived money fields to exactly 0."

    Design: Difficulty/compensating_invariant/withdrawing_a_paid_records_request_waives_and_refunds_to_zero_cash
    """
    paid = _request_holding_a_thousand_cent_deposit()

    withdrawn = validate_success(
        api_client.withdraw_records_request(
            paid["id"], make_requester_headers(paid["id"])
        )
    )

    a.assert_fee_ledger(
        withdrawn,
        assessed=1875,
        waived=1875,
        collected=1000,
        refunded=1000,
        balance=0,
        net_cash=0,
    )
    a.assert_axes(withdrawn, fulfillment_status="WITHDRAWN", fee_status="REFUNDED")
    a.assert_nulls(withdrawn, "closed_on")


def _certified_batch_of_forty_off_a_series_of_one_fifty():
    """Two accessions totalling 150 items, anchored on the later date, with 40 of
    them already certified for destruction."""
    fx.set_clock("2026-08-03T09:00:00Z")
    series = fx.create_record_series(retention_years=5, retention_trigger="CREATION")
    for item_count, accessioned_on in ((100, "2019-06-15"), (50, "2019-07-20")):
        validate_success(
            api_client.create_accession(
                series["id"],
                f.accession_payload(item_count, accessioned_on),
                RECORDS_OFFICER,
            )
        )
    batch = fx.certified_destruction_batch(
        series["id"], item_count=40, cutoff_on="2024-07-20", certified_on="2026-08-03"
    )
    return {"series": fx.read_record_series(series["id"]), "batch": batch}


def test_certification_moves_forty_items_across_without_touching_the_total():
    """The anchor is the later accession, eligibility falls five years after it,
    and destruction shifts items between the two sub-counters only.

    PRD 3.9: "Destruction moves items between the two sub-counters and **never**
    changes the custody total, which is why an oversized batch is refused outright
    rather than driving `active_item_count` below zero."

    Design: Difficulty/compensating_invariant/rescinding_a_certified_destruction_batch_restores_the_custody_triple_with_zero_drift
    """
    ctx = _certified_batch_of_forty_off_a_series_of_one_fifty()

    a.assert_fields(
        ctx["series"],
        last_accessioned_on="2019-07-20",
        eligible_through_on="2024-07-20",
    )
    a.assert_custody_triple(ctx["series"], total=150, active=110, destroyed=40)
    a.assert_fields(
        ctx["batch"], status="CERTIFIED", certifying_officer_id=CITY_CLERK_ID
    )


def test_rescission_returns_the_triple_exactly_and_keeps_the_signature_on_file():
    """The counters come back to 150 / 150 / 0 with no drift in either direction,
    while the signer and the certificate date are deliberately retained.

    PRD 3.9: "The officer supplies a `rescind_reason`, the batch moves `CERTIFIED
    → RESCINDED`, and the counter movement is undone exactly: `active_item_count`
    rises by the batch's `item_count` and `destroyed_item_count` falls by the same
    amount, returning the series to precisely the three counter values it held
    before the certification, with no drift in either direction and again no change
    to `total_accessioned_count`."

    Design: Difficulty/compensating_invariant/rescinding_a_certified_destruction_batch_restores_the_custody_triple_with_zero_drift
    """
    ctx = _certified_batch_of_forty_off_a_series_of_one_fifty()

    rescinded = validate_success(
        api_client.rescind_destruction_batch(
            ctx["batch"]["id"], f.rescind_batch_payload(rescind_reason=RESCIND_REASON),
            RECORDS_OFFICER,
        )
    )

    a.assert_fields(
        rescinded,
        status="RESCINDED",
        rescind_reason=RESCIND_REASON,
        certifying_officer_id=CITY_CLERK_ID,
        certified_on="2026-08-03",
        item_count=40,
    )
    series = fx.read_record_series(ctx["series"]["id"])
    a.assert_custody_triple(series, total=150, active=150, destroyed=0)
    a.assert_fields(series, eligible_through_on="2024-07-20")
