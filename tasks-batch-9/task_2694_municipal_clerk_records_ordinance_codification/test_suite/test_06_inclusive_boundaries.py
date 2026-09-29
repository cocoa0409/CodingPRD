"""Three thresholds tested from both sides: the notice deadline instant, the free
page allowance, and the volume-discount tier on a newspaper invoice.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CITY_CLERK


def _two_packets_ready_to_post():
    """Two council meetings starting at the same instant in different rooms, each
    with a one-item DRAFT packet whose deadline is 2026-09-12T18:00:00Z."""
    on_time = fx.scheduled_meeting(
        venue_overrides={"name": "Council Chamber", "address": "1 Civic Plaza"}
    )
    late = fx.scheduled_meeting(
        venue_overrides={"name": "Annex Hall", "address": "3 Civic Plaza", "capacity": 80}
    )
    on_time_packet = fx.draft_packet(on_time["meeting"]["id"])
    fx.add_item(on_time_packet["id"], 1, "REPORT", title="Report, on-time notice")
    late_packet = fx.draft_packet(late["meeting"]["id"])
    fx.add_item(late_packet["id"], 1, "REPORT", title="Report, one second late")
    return {
        "on_time_meeting": on_time["meeting"],
        "late_meeting": late["meeting"],
        "on_time_packet": on_time_packet,
        "late_packet": late_packet,
    }


def test_posting_at_the_very_deadline_instant_is_still_compliant():
    """Posting at exactly 2026-09-12T18:00:00Z, the deadline instant itself, stores
    notice_compliant true.

    PRD 3.2: "The logical clock instant is then stored as `posted_at`, and
    `notice_compliant` is set to true when `posted_at` falls at or before
    `notice_deadline_at` and false otherwise — posting at exactly the deadline
    instant is compliant, comparison being at second granularity."

    Design: Difficulty/boundary_precision_check/notice_compliance_inclusive_at_the_deadline_instant_and_false_one_second_later
    """
    ctx = _two_packets_ready_to_post()
    fx.set_clock("2026-09-12T18:00:00Z")

    posted = validate_success(
        api_client.post_agenda_packet(ctx["on_time_packet"]["id"], CITY_CLERK)
    )

    a.assert_fields(
        posted,
        notice_deadline_at="2026-09-12T18:00:00Z",
        posted_at="2026-09-12T18:00:00Z",
        notice_compliant=True,
        status="POSTED",
    )
    meeting = fx.read_meeting(ctx["on_time_meeting"]["id"])
    a.assert_fields(meeting, notice_compliant=True, status="NOTICED")


def test_one_second_past_the_deadline_notices_the_meeting_anyway_but_not_compliantly():
    """Posting at 2026-09-12T18:00:01Z still succeeds and still notices the
    meeting; only the stored boolean changes.

    PRD 3.2: "Posting late is not an error. A packet that misses its deadline still
    posts, still notices the meeting, and still answers 200 — it simply records
    `notice_compliant` as false, and the consequence surfaces later, when the
    meeting cannot be called to order and when a reschedule is refused."

    Design: Difficulty/boundary_precision_check/notice_compliance_inclusive_at_the_deadline_instant_and_false_one_second_later
    """
    ctx = _two_packets_ready_to_post()
    fx.set_clock("2026-09-12T18:00:00Z")
    fx.post_packet(ctx["on_time_packet"]["id"])
    fx.set_clock("2026-09-12T18:00:01Z")

    posted_late = validate_success(
        api_client.post_agenda_packet(ctx["late_packet"]["id"], CITY_CLERK)
    )

    a.assert_fields(
        posted_late,
        notice_deadline_at="2026-09-12T18:00:00Z",
        posted_at="2026-09-12T18:00:01Z",
        notice_compliant=False,
        status="POSTED",
    )
    late_meeting = fx.read_meeting(ctx["late_meeting"]["id"])
    a.assert_fields(late_meeting, notice_compliant=False, status="NOTICED")
    on_time_meeting = fx.read_meeting(ctx["on_time_meeting"]["id"])
    assert on_time_meeting["notice_compliant"] is True
    assert on_time_meeting["status"] == "NOTICED"


def _request_for_permits(subject):
    fx.set_clock("2026-08-03T09:00:00Z")
    return fx.request_under_review(
        requester_name="Ben Oyelaran",
        requester_email="ben@example.org",
        subject_description=subject,
        commercial_purpose=False,
    )


def test_exactly_twenty_pages_are_all_free_and_still_leave_the_fee_assessed():
    """The allowance is inclusive at 20, so a single 20-page paper line with no
    staff time assesses nothing at all while the money axis still moves.

    PRD 3.8: "A free allowance of 20 pages is carried into the first line and
    consumed line by line in the order the lines were supplied: a line's billable
    pages are its `page_count` less whatever allowance remains, floored at zero,
    and the remaining allowance is then reduced by that line's full `page_count`,
    floored at zero."

    Design: Difficulty/boundary_precision_check/free_page_allowance_boundary_at_twenty_and_twenty_one_pages
    """
    request = _request_for_permits("Twenty pages of permits")

    assessed = validate_success(
        api_client.assess_fee(
            request["id"],
            f.assess_fee_payload(
                [f.fee_line(page_count=20, staff_minutes=0, delivery_medium="PAPER")],
                "ACTUAL_COST",
            ),
            CITY_CLERK,
        )
    )

    a.assert_fee_ledger(
        assessed,
        assessed=0,
        waived=0,
        collected=0,
        refunded=0,
        balance=0,
        net_cash=0,
    )
    a.assert_axes(assessed, fulfillment_status="UNDER_REVIEW", fee_status="ASSESSED")
    a.assert_fields(assessed, due_on="2026-08-10")


def test_the_twenty_first_page_costs_fifteen_cents_and_nothing_more():
    """One page past the allowance is billed at the copy rate, so the same request
    shape assesses exactly 15 cents.

    PRD 3.8: "Each line's billable pages are charged at 15 cents per page, and if
    that line's `delivery_medium` is `ELECTRONIC` its own charge is then halved and
    rounded half up to a whole cent."

    Design: Difficulty/boundary_precision_check/free_page_allowance_boundary_at_twenty_and_twenty_one_pages
    """
    free = _request_for_permits("Twenty pages of permits")
    billable = _request_for_permits("Twenty-one pages of permits")
    priced_free = validate_success(
        api_client.assess_fee(
            free["id"],
            f.assess_fee_payload(
                [f.fee_line(page_count=20, staff_minutes=0, delivery_medium="PAPER")],
                "ACTUAL_COST",
            ),
            CITY_CLERK,
        )
    )

    priced_billable = validate_success(
        api_client.assess_fee(
            billable["id"],
            f.assess_fee_payload(
                [f.fee_line(page_count=21, staff_minutes=0, delivery_medium="PAPER")],
                "ACTUAL_COST",
            ),
            CITY_CLERK,
        )
    )

    a.assert_cents(priced_billable, "total_assessed_cents", 15)
    a.assert_cents(priced_billable, "fee_balance_cents", 15)
    assert (
        priced_billable["total_assessed_cents"] - priced_free["total_assessed_cents"] == 15
    )
    a.assert_fields(priced_billable, due_on="2026-08-10")


def _two_agenda_notices_ready_to_order():
    """Two DRAFT MEETING_AGENDA notices, each owing one insertion by 2026-09-14."""
    ctx = _two_packets_ready_to_post()
    fx.set_clock("2026-09-12T18:00:00Z")
    fx.post_packet(ctx["on_time_packet"]["id"])
    fx.post_packet(ctx["late_packet"]["id"])
    return {
        "below": fx.sole_notice_for_meeting(ctx["on_time_meeting"]["id"]),
        "at": fx.sole_notice_for_meeting(ctx["late_meeting"]["id"]),
    }


def test_a_gross_one_cent_short_of_the_tier_earns_no_discount_at_all():
    """99.99 column inches gross 49995 cents, which does not reach the 50,000-cent
    tier, so the city pays the whole 49995.

    PRD 3.6: "`discount_pct` is a volume discount keyed on `gross_cost_cents`: a
    gross below 50,000 cents earns no discount at all; a gross from 50,000 cents up
    to but not including 150,000 cents earns 0.05; and a gross of 150,000 cents or
    more earns 0.10."

    Design: Difficulty/boundary_precision_check/publication_volume_tier_boundary_inverts_the_billing_order_at_fifty_thousand_cents
    """
    notices = _two_agenda_notices_ready_to_order()

    ordered = validate_success(
        api_client.order_publication(
            notices["below"]["id"],
            f.publication_order_payload(
                ["2026-09-14"], column_inches=99.99, affidavit_required=False
            ),
            CITY_CLERK,
        )
    )

    a.assert_invoice(
        ordered, gross_cost_cents=49995, discount_pct=0.0, invoice_total_cents=49995
    )
    a.assert_status(ordered, "ORDERED")


def test_the_larger_advertisement_at_the_tier_boundary_bills_less_than_the_smaller():
    """100.00 column inches gross exactly 50000 and earn 0.05, invoicing 47500 —
    less than the 49995 billed for the marginally smaller notice.

    PRD 3.6: "Because the tier is keyed on a gross that excludes the affidavit,
    buying affidavits can never purchase a better discount tier; and because the
    tier boundary is a step rather than a slope, a slightly *smaller* advertisement
    whose gross falls just under a boundary can bill *more* than a slightly larger
    one whose gross clears it."

    Design: Difficulty/boundary_precision_check/publication_volume_tier_boundary_inverts_the_billing_order_at_fifty_thousand_cents
    """
    notices = _two_agenda_notices_ready_to_order()
    below = fx.ordered_notice(
        notices["below"]["id"], ["2026-09-14"], column_inches=99.99
    )

    at_tier = validate_success(
        api_client.order_publication(
            notices["at"]["id"],
            f.publication_order_payload(
                ["2026-09-14"], column_inches=100.00, affidavit_required=False
            ),
            CITY_CLERK,
        )
    )

    a.assert_invoice(
        at_tier, gross_cost_cents=50000, discount_pct=0.05, invoice_total_cents=47500
    )
    a.assert_status(at_tier, "ORDERED")
    assert at_tier["invoice_total_cents"] < below["invoice_total_cents"]
