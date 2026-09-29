"""The declared arithmetic, exercised one formula at a time: business-day walks,
anchor selection, the notice constants, half-up rounding on an exact decimal, and
a fee ledger drawn down from both sides.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ANONYMOUS,
    ANONYMOUS_ALT,
    CITY_CLERK,
    DEPUTY_CLERK,
    RECORDS_OFFICER,
    make_requester_headers,
)

ONE_LINE = [f.fee_line(page_count=40, staff_minutes=40, delivery_medium="PAPER")]


def test_a_saturday_intake_does_not_spend_a_business_day():
    """Filed on Saturday 1 August, the request owes its answer by Friday 7 August —
    six calendar days later, because neither weekend day consumes a count.

    PRD 3.8: "It is five **business days** after intake, counted by walking the
    calendar forward one day at a time from `intake_on` and decrementing the count
    only on days that are Monday through Friday; Saturdays and Sundays are skipped
    and never consume a count."

    Design: Corner/calculations/a_saturday_intake_yields_a_friday_due_date_five_business_days_later
    """
    filed = validate_success(
        api_client.create_records_request(
            f.records_request_payload(subject_description="All 2026 council agendas"),
            ANONYMOUS,
        ),
        201,
    )

    a.assert_fields(
        filed,
        intake_on="2026-08-01",
        due_on="2026-08-07",
        commercial_purpose=False,
    )
    a.assert_axes(filed, fulfillment_status="RECEIVED", fee_status="NOT_ASSESSED")


def test_the_request_closure_anchor_ignores_the_accession_date_entirely():
    """A series holding an accession date still has no anchor while its requests are
    withdrawn or merely released, and the shredder is refused; the close is what
    supplies the date.

    PRD 3.9: "Under `REQUEST_CLOSURE` the anchor is the latest `closed_on` among the
    closed public records requests whose `target_series_id` is this series, and where
    no such request exists the anchor is simply **unresolved**."

    Design: Corner/calculations/the_request_closure_anchor_reads_only_closed_requests_and_ignores_the_accession_date
    """
    series = fx.create_record_series(
        series_code="CC-03",
        name="Disclosure working files",
        retention_years=0,
        retention_trigger="REQUEST_CLOSURE",
    )
    validate_success(
        api_client.create_accession(
            series["id"], f.accession_payload(40, "2019-06-15"), RECORDS_OFFICER
        )
    )
    abandoned = fx.create_records_request(
        ANONYMOUS,
        requester_name="A. Osei",
        requester_email="a.osei@example.org",
        subject_description="Working files A",
        target_series_id=series["id"],
    )
    validate_success(
        api_client.withdraw_records_request(
            abandoned["id"], make_requester_headers(abandoned["id"])
        )
    )
    released = fx.create_records_request(
        ANONYMOUS_ALT,
        requester_name="B. Larsen",
        requester_email="b.larsen@example.org",
        subject_description="Working files B",
        target_series_id=series["id"],
    )
    validate_success(api_client.begin_review(released["id"], CITY_CLERK))
    validate_success(
        api_client.record_disposition(
            released["id"], f.disposition_payload("FULL_RELEASE"), CITY_CLERK
        )
    )
    fx.set_clock("2026-08-20T00:00:00Z")

    refused = api_client.create_destruction_batch(
        f.destruction_batch_payload(series["id"], 10, "2019-12-31"), RECORDS_OFFICER
    )

    validate_error(refused, ApiErrorId.RETENTION_ANCHOR_UNRESOLVED.value, 409)
    before = fx.read_record_series(series["id"])
    a.assert_fields(before, last_accessioned_on="2019-06-15")
    a.assert_nulls(before, "eligible_through_on")

    validate_success(api_client.close_records_request(released["id"], CITY_CLERK))
    accepted = validate_success(
        api_client.create_destruction_batch(
            f.destruction_batch_payload(series["id"], 10, "2019-12-31"), RECORDS_OFFICER
        ),
        201,
    )

    a.assert_fields(
        fx.read_record_series(series["id"]), eligible_through_on="2026-08-20"
    )
    a.assert_fields(accepted, status="PROPOSED", eligible_through_on="2026-08-20")
    a.assert_nulls(accepted, "blocking_request_id")


def test_the_statutory_class_alone_separates_the_two_notice_requirements():
    """Two council meetings starting at the same instant with identical one-item
    packets owe 72 and 48 hours purely because one is regular and the other special.

    PRD 3.2: "The base requirement comes from the statutory meeting class: a
    `REGULAR` meeting owes 72 hours — three full days — while `SPECIAL` and
    `WORKSHOP` meetings each owe 48 hours and an `EMERGENCY` meeting owes only 24
    hours."

    Design: Corner/calculations/the_base_notice_hours_constant_is_keyed_on_meeting_type_alone
    """
    regular = fx.noticed_meeting(
        item_types=["REPORT"],
        venue_overrides={"name": "Council Chamber", "address": "1 Civic Plaza"},
        meeting_type="REGULAR",
    )
    special = fx.noticed_meeting(
        item_types=["REPORT"],
        venue_overrides={
            "name": "Hearing Room B",
            "address": "1 Civic Plaza",
            "capacity": 60,
        },
        meeting_type="SPECIAL",
    )

    a.assert_fields(
        regular["packet"],
        required_notice_hours=72,
        notice_deadline_at="2026-09-12T18:00:00Z",
        status="POSTED",
        notice_compliant=True,
    )
    a.assert_fields(
        special["packet"],
        required_notice_hours=48,
        notice_deadline_at="2026-09-13T18:00:00Z",
        status="POSTED",
        notice_compliant=True,
    )


def test_an_exact_half_cent_per_insertion_rounds_up_rather_than_away():
    """12.501 column inches price at exactly 6250.5 cents, and the per-insertion
    rounding must land on 6251 before the gross is ever multiplied out.

    PRD 3.6: "First the per-insertion charge is computed: `column_inches` is
    multiplied by 500 cents — five dollars per column inch — and that product is
    rounded half up to a whole cent **per insertion**, before anything is multiplied
    out."

    Design: Corner/calculations/the_publication_rate_is_rounded_half_up_on_the_exact_decimal_product
    """
    ctx = fx.noticed_meeting(item_types=["REPORT"])

    ordered = validate_success(
        api_client.order_publication(
            ctx["agenda_notice"]["id"],
            f.publication_order_payload(
                ["2026-09-14"], column_inches=12.501, affidavit_required=False
            ),
            CITY_CLERK,
        )
    )

    a.assert_status(ordered, "ORDERED")
    a.assert_invoice(
        ordered, gross_cost_cents=6251, discount_pct=0.0, invoice_total_cents=6251
    )


def test_the_hearing_supplement_is_added_once_however_many_hearings_are_printed():
    """A packet opens owing the bare 72 hours, and one public-hearing item lifts the
    requirement to 240; a second hearing item on another agenda leaves it at 240.

    PRD 3.2: "If the packet contains at least one public-hearing item, a further 168
    hours — a full week — is added."

    Design: Corner/calculations/one_public_hearing_item_crosses_the_hearing_threshold_and_a_second_adds_nothing
    """
    one_hearing = fx.scheduled_meeting(
        venue_overrides={"name": "Council Chamber", "address": "1 Civic Plaza"}
    )
    two_hearings = fx.scheduled_meeting(
        venue_overrides={
            "name": "Hearing Room B",
            "address": "1 Civic Plaza",
            "capacity": 60,
        }
    )
    single = fx.draft_packet(one_hearing["meeting"]["id"])
    double = fx.draft_packet(two_hearings["meeting"]["id"])
    a.assert_fields(
        single,
        required_notice_hours=72,
        notice_deadline_at="2026-09-12T18:00:00Z",
        contains_public_hearing=False,
    )
    fx.add_item(single["id"], 1, "REPORT", title="Quarterly finance report")
    fx.add_item(
        single["id"], 2, "PUBLIC_HEARING", title="Hearing on the Elm Street rezoning"
    )
    fx.add_item(double["id"], 1, "REPORT", title="Quarterly finance report")
    fx.add_item(
        double["id"], 2, "PUBLIC_HEARING", title="Hearing on the Elm Street rezoning"
    )
    fx.add_item(
        double["id"], 3, "PUBLIC_HEARING", title="Hearing on the utility rate schedule"
    )

    posted_single = fx.post_packet(single["id"])
    posted_double = fx.post_packet(double["id"])

    a.assert_fields(
        posted_single,
        required_notice_hours=240,
        notice_deadline_at="2026-09-05T18:00:00Z",
        contains_public_hearing=True,
        item_count=2,
        notice_compliant=True,
    )
    a.assert_fields(
        posted_double,
        required_notice_hours=240,
        notice_deadline_at="2026-09-05T18:00:00Z",
        contains_public_hearing=True,
        item_count=3,
        notice_compliant=True,
    )
    a.assert_fields(
        fx.read_meeting(two_hearings["meeting"]["id"]), required_notice_hours=240
    )


def test_a_backdated_accession_does_not_drag_the_anchor_backwards():
    """The anchor is the maximum accession date rather than the most recent write, so
    filing an older block afterwards leaves the eligibility date alone.

    PRD 3.9: "The accession advances `total_accessioned_count` by that count and
    `active_item_count` by the same count, and sets `last_accessioned_on` to the
    later of its existing value and the supplied date, so the anchor only ever moves
    forward."

    Design: Corner/calculations/an_out_of_order_accession_does_not_move_the_retention_anchor_backwards
    """
    series = fx.create_record_series(
        series_code="CC-04", name="Oath and bond files", retention_years=5
    )

    newer = validate_success(
        api_client.create_accession(
            series["id"], f.accession_payload(100, "2019-07-20"), RECORDS_OFFICER
        )
    )
    older = validate_success(
        api_client.create_accession(
            series["id"], f.accession_payload(50, "2019-06-15"), RECORDS_OFFICER
        )
    )

    a.assert_fields(
        newer, last_accessioned_on="2019-07-20", eligible_through_on="2024-07-20"
    )
    a.assert_fields(
        older, last_accessioned_on="2019-07-20", eligible_through_on="2024-07-20"
    )
    a.assert_custody_triple(older, total=150, active=150, destroyed=0)


def test_the_balance_is_recomputed_from_the_counters_and_never_goes_negative():
    """A 1175-cent assessment is drawn down by a waiver and then a payment, and the
    cent that would take either counter past the balance is refused from both sides.

    PRD 3.8: "`fee_balance_cents` is `total_assessed_cents`, less
    `total_waived_cents`, less that net cash position."

    Design: Corner/calculations/the_fee_ledger_recomputes_from_counters_after_a_waiver_and_a_payment
    """
    request = fx.request_under_review(
        subject_description="Planning commission packets 2025"
    )

    assessed = validate_success(
        api_client.assess_fee(
            request["id"], f.assess_fee_payload(ONE_LINE, "ACTUAL_COST"), CITY_CLERK
        )
    )
    waived = validate_success(
        api_client.waive_fee(
            request["id"], f.waive_fee_payload(175), RECORDS_OFFICER
        )
    )
    paid = validate_success(
        api_client.record_payment(
            request["id"], f.payment_payload(1000), make_requester_headers(request["id"])
        )
    )
    extra_payment = api_client.record_payment(
        request["id"], f.payment_payload(1), make_requester_headers(request["id"])
    )
    extra_waiver = api_client.waive_fee(
        request["id"], f.waive_fee_payload(1, waiver_reason="Overshoot"), RECORDS_OFFICER
    )

    a.assert_fee_ledger(
        assessed,
        assessed=1175,
        waived=0,
        collected=0,
        refunded=0,
        balance=1175,
        net_cash=0,
    )
    a.assert_fee_ledger(
        waived,
        assessed=1175,
        waived=175,
        collected=0,
        refunded=0,
        balance=1000,
        net_cash=0,
    )
    a.assert_fields(waived, fee_status="ASSESSED")
    a.assert_fee_ledger(
        paid,
        assessed=1175,
        waived=175,
        collected=1000,
        refunded=0,
        balance=0,
        net_cash=1000,
    )
    a.assert_fields(paid, fee_status="PAID")
    validate_error(extra_payment, ApiErrorId.PAYMENT_EXCEEDS_BALANCE.value, 422)
    validate_error(extra_waiver, ApiErrorId.WAIVER_EXCEEDS_BALANCE.value, 422)
    final = fx.read_records_request(request["id"])
    a.assert_fee_ledger(
        final,
        assessed=1175,
        waived=175,
        collected=1000,
        refunded=0,
        balance=0,
        net_cash=1000,
    )


def test_the_variant_chosen_at_assessment_prices_the_file_and_cannot_be_reselected():
    """The same line billed under the flat schedule comes to 1375 cents, and because
    a fee is assessed once there is no way to re-price it under the other variant.

    PRD 3.8: "A second attempt against a request whose `fee_status` has already left
    `NOT_ASSESSED` is refused with `ERR_FEE_ALREADY_ASSESSED` (HTTP 422)."

    Design: Corner/calculations/the_recorded_fee_variant_is_the_one_supplied_at_assessment_and_cannot_be_reselected
    """
    request = fx.request_under_review(
        reviewer=DEPUTY_CLERK,
        requester_name="T. Nkemelu",
        requester_email="t.nkemelu@example.org",
        subject_description="Ordinance files 2024",
    )

    flat = validate_success(
        api_client.assess_fee(
            request["id"], f.assess_fee_payload(ONE_LINE, "FLAT_SCHEDULE"), DEPUTY_CLERK
        )
    )
    reselection = api_client.assess_fee(
        request["id"], f.assess_fee_payload(ONE_LINE, "ACTUAL_COST"), CITY_CLERK
    )

    a.assert_fields(flat, fee_schedule_variant="FLAT_SCHEDULE")
    a.assert_cents(flat, "total_assessed_cents", 1375)
    validate_error(reselection, ApiErrorId.FEE_ALREADY_ASSESSED.value, 422)
    stood = fx.read_records_request(request["id"])
    a.assert_fields(stood, fee_schedule_variant="FLAT_SCHEDULE")
    a.assert_cents(stood, "total_assessed_cents", 1375)
    a.assert_cents(stood, "fee_balance_cents", 1375)
    requests_seen, meta = validate_paginated(
        api_client.list_records_requests(CITY_CLERK, {"fee_status": "ASSESSED"})
    )
    a.assert_pagination_meta(meta, total_count=1)
    a.assert_ids_equal(requests_seen, [request["id"]])
