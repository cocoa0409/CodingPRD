"""One page, one cent and one second either side of three pinned boundaries."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    Instant,
    assert_event_count,
    assert_facility_money,
    assert_line,
    assert_line_sequence_contiguous,
    assert_no_event,
    assert_no_line_type,
    assert_page_ledger,
    line_types,
)
from test_helpers.test_users import BILLING_1


# --------------------------------------------------------------------------
# page_tier_boundary_at_exact_tier1_limit
# --------------------------------------------------------------------------
def _twenty_five_and_twenty_six_page_requests(api):
    """Two third-party retail requests on disjoint date ranges, one straddling the
    tier1_page_limit of 25 from below and one from one page above."""
    world = fx.third_party_world(api)
    request_a = fx.simple_third_party_request_at_release_ready(
        api, world, 25, date_range_start="2024-01-01", date_range_end="2024-12-31"
    )
    request_b = fx.simple_third_party_request_at_release_ready(
        api, world, 26, date_range_start="2025-01-01", date_range_end="2025-12-31"
    )
    invoice_a = fx.create_invoice(api, request_a["request_id"])
    invoice_b = fx.create_invoice(api, request_b["request_id"])
    return {
        "world": world,
        "request_a": request_a["request_id"],
        "request_b": request_b["request_id"],
        "invoice_a": invoice_a["id"],
        "invoice_b": invoice_b["id"],
    }


def test_at_exactly_the_tier_limit_the_tier2_line_is_absent_not_zero(api):
    """25 pages leave two lines whose sequences close up to 1 and 2.

    PRD: "Third, a `PER_PAGE_TIER2` line whose `quantity` is the priced page count less `tier1_page_limit` but never below 0, at a `unit_millicents` of `tier2_per_page_millicents`, omitted entirely when that quantity is 0."

    Design: Difficulty/boundary_precision_check/page_tier_boundary_at_exact_tier1_limit
    """
    scenario = _twenty_five_and_twenty_six_page_requests(api)
    lines = fx.read_lines(api, scenario["invoice_a"])

    assert len(lines) == 2, line_types(lines)
    assert_no_line_type(lines, "PER_PAGE_TIER2")
    assert_line_sequence_contiguous(lines)
    assert_line(lines[0], "BASE_RETRIEVAL", 1, 1500000, 1500)
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)

    invoice = fx.read_invoice(api, scenario["invoice_a"])
    assert invoice["subtotal_cents"] == 2188
    assert invoice["amount_due_cents"] == 2188


def test_one_page_past_the_limit_rounds_twelve_point_five_up_to_thirteen(api):
    """26 pages add a third line whose single page costs 13 cents, never 12.

    PRD: "Each emitted line's `amount_cents` is its own `quantity` multiplied by its own `unit_millicents`, divided by 1000, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/page_tier_boundary_at_exact_tier1_limit
    """
    scenario = _twenty_five_and_twenty_six_page_requests(api)
    lines = fx.read_lines(api, scenario["invoice_b"])

    assert len(lines) == 3, line_types(lines)
    assert_line_sequence_contiguous(lines)
    assert lines[2]["sequence"] == 3
    assert_line(lines[2], "PER_PAGE_TIER2", 1, 12500, 13)
    assert lines[2]["amount_cents"] != 12

    invoice = fx.read_invoice(api, scenario["invoice_b"])
    assert invoice["subtotal_cents"] == 2201
    assert invoice["amount_due_cents"] == 2201


def test_the_electronic_cap_is_selected_but_bites_on_neither_side_of_the_step(api):
    """Both invoices carry the 6500 electronic cap unadjusted, so the step is exactly 13.

    PRD: "For an electronic delivery the invoice's `applicable_cap_cents` is the smaller of the fee rule's `electronic_delivery_total_cap_cents` and its `total_fee_cap_cents`; for any other format it is simply `total_fee_cap_cents`."

    Design: Difficulty/boundary_precision_check/page_tier_boundary_at_exact_tier1_limit
    """
    scenario = _twenty_five_and_twenty_six_page_requests(api)
    invoice_a = fx.read_invoice(api, scenario["invoice_a"])
    invoice_b = fx.read_invoice(api, scenario["invoice_b"])

    for invoice in (invoice_a, invoice_b):
        assert invoice["applicable_cap_cents"] == 6500
        assert invoice["cap_adjustment_cents"] == 0

    assert invoice_b["subtotal_cents"] - invoice_a["subtotal_cents"] == 13


# --------------------------------------------------------------------------
# zero_billable_pages_makes_patient_access_not_billable
# --------------------------------------------------------------------------
def _zero_page_and_one_page_patient_access_requests(api):
    """Request A retrieves nothing at all — its only segment is a legacy chart that no
    longer exists — while request B retrieves a single page."""
    world = fx.patient_access_world(api)
    request_a = fx.open_patient_access_request(
        api, world, date_range_start="2019-01-01", date_range_end="2019-12-31"
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request_a["id"],
        [
            {
                "label": "legacy",
                "category": "GENERAL_MEDICAL",
                "source_system": "LEGACY_ARCHIVE",
                "page_count": 0,
                "disposition": "UNAVAILABLE",
                "unavailable_reason": "1990s chart was destroyed under the retention schedule",
                "legacy_job_start_at": "2026-08-02T09:00:00Z",
            }
        ],
    )
    fx.run_sensitive_review(api, request_a["id"], [])
    request_b = fx.simple_patient_access_request_at_release_ready(
        api, world, 1, date_range_start="2025-01-01", date_range_end="2025-12-31"
    )
    return {
        "world": world,
        "request_a": request_a["id"],
        "segment_a": ids["legacy"],
        "request_b": request_b["request_id"],
    }


def test_the_unavailable_disposition_forces_the_page_count_to_zero(api):
    """An unavailable segment leaves the request's whole page ledger at 0.

    PRD: "A `disposition` of `UNAVAILABLE` moves the segment from `PENDING` to `UNAVAILABLE`, also requires the parent request to be in `COMPILATION`, records the supplied free-text `unavailable_reason`, forces `page_count` to 0, and leaves `sensitivity_status` at `UNCLASSIFIED`."

    Design: Difficulty/boundary_precision_check/zero_billable_pages_makes_patient_access_not_billable
    """
    scenario = _zero_page_and_one_page_patient_access_requests(api)

    segment = fx.read_segment(api, scenario["segment_a"])
    assert segment["retrieval_status"] == "UNAVAILABLE"
    assert segment["page_count"] == 0
    assert segment["sensitivity_status"] == "UNCLASSIFIED"

    assert_page_ledger(fx.read_request(api, scenario["request_a"]), 0, 0, 0, 0)


def test_the_legacy_job_window_end_is_derived_from_the_job_length(api):
    """A 09:00 legacy job on a 30-minute gateway ends at 09:30.

    PRD: "When `legacy_job_start_at` is supplied the system derives `legacy_job_end_at` by adding the facility's `legacy_gateway_job_minutes` to it; `legacy_job_end_at` stays null whenever `legacy_job_start_at` is null."

    Design: Difficulty/boundary_precision_check/zero_billable_pages_makes_patient_access_not_billable
    """
    scenario = _zero_page_and_one_page_patient_access_requests(api)
    segment = fx.read_segment(api, scenario["segment_a"])

    assert segment["legacy_job_start_at"] == Instant("2026-08-02T09:00:00Z")
    assert segment["legacy_job_end_at"] == Instant("2026-08-02T09:30:00Z")


def test_a_zero_prospective_subtotal_flips_the_request_to_not_billable(api):
    """The flag is set on entry into RELEASE_READY and closes billing permanently.

    PRD: "If that prospective subtotal is exactly 0 cents, the request's `billing_status` moves from `PENDING_INVOICE` to `NOT_BILLABLE`, and no invoice may be created for the request afterwards: the attempt reports `ERR_NOTHING_TO_INVOICE`."

    Design: Difficulty/boundary_precision_check/zero_billable_pages_makes_patient_access_not_billable
    """
    scenario = _zero_page_and_one_page_patient_access_requests(api)
    request_id = scenario["request_a"]

    before = fx.read_request(api, request_id)
    assert before["fulfillment_status"] == "RELEASE_READY"
    assert before["billing_status"] == "NOT_BILLABLE"

    response = api.create_invoice(
        f.invoice_payload(request_id, before["version"]), BILLING_1
    )
    validate_error(response, e.ERR_NOTHING_TO_INVOICE, 422)

    rows, _meta = fx.list_invoices_for(api, request_id)
    assert rows == []


def test_release_proceeds_because_not_billable_satisfies_the_prepayment_gate(api):
    """Nothing to bill is not the same as money outstanding.

    PRD: "The request's `billing_status` must be `PAID`, `WAIVED` or `NOT_BILLABLE`; a `billing_status` of `PENDING_INVOICE` or `INVOICED` means the money is still outstanding and the release is refused with `ERR_INVOICE_UNSETTLED` (HTTP 402), because prepayment is required before records leave the building."

    Design: Difficulty/boundary_precision_check/zero_billable_pages_makes_patient_access_not_billable
    """
    scenario = _zero_page_and_one_page_patient_access_requests(api)

    fx.release_request(api, scenario["request_a"])

    released = fx.read_request(api, scenario["request_a"])
    assert released["fulfillment_status"] == "RELEASED"
    assert released["billing_status"] == "NOT_BILLABLE"


def test_one_billable_page_prices_an_ordinary_ten_cent_invoice(api):
    """P == 1 is a different code path from P == 0, not a smaller version of it.

    PRD: "First, a `PER_PAGE_FLAT` line whose `quantity` is the priced page count at a `unit_millicents` of `patient_access_per_page_millicents`, omitted entirely when the priced page count is 0."

    Design: Difficulty/boundary_precision_check/zero_billable_pages_makes_patient_access_not_billable
    """
    scenario = _zero_page_and_one_page_patient_access_requests(api)
    assert fx.read_request(api, scenario["request_b"])["billing_status"] == "PENDING_INVOICE"

    invoice = fx.create_invoice(api, scenario["request_b"])
    lines = fx.read_lines(api, invoice["id"])

    assert len(lines) == 1, line_types(lines)
    assert_line(lines[0], "PER_PAGE_FLAT", 1, 10000, 10)
    assert invoice["subtotal_cents"] == 10
    assert invoice["amount_due_cents"] == 10


# --------------------------------------------------------------------------
# release_exactly_at_statutory_due_accrues_nothing
# --------------------------------------------------------------------------
def _two_waived_requests_due_at_the_end_of_august(api):
    """Two 62-page third-party requests, each priced at 2651 and waived so the release
    gate is open, both due at 2026-08-31T00:00:00Z."""
    world = fx.third_party_world(api)
    request_a = fx.simple_third_party_request_at_release_ready(
        api, world, 62, date_range_start="2024-01-01", date_range_end="2024-12-31"
    )
    invoice_a = fx.invoice_and_waive(api, request_a["request_id"])
    request_b = fx.simple_third_party_request_at_release_ready(
        api, world, 62, date_range_start="2025-01-01", date_range_end="2025-12-31"
    )
    invoice_b = fx.invoice_and_waive(api, request_b["request_id"])
    return {
        "world": world,
        "request_a": request_a["request_id"],
        "request_b": request_b["request_id"],
        "invoice_a": invoice_a["id"],
        "invoice_b": invoice_b["id"],
    }


def _release_one_on_the_instant_and_one_a_second_late(api, scenario):
    """Request A is released at exactly statutory_due_at, request B one second later."""
    fx.set_clock(api, "2026-08-31T00:00:00Z")
    fx.release_request(api, scenario["request_a"])
    fx.set_clock(api, "2026-08-31T00:00:01Z")
    fx.release_request(api, scenario["request_b"])
    return scenario


def test_two_waived_invoices_land_wholly_in_the_written_off_bucket(api):
    """2651 twice waived is 5302 written off and nothing receivable.

    PRD: "`written_off_cents` is the sum, over those whose `status` is `WAIVED`, of `amount_due_cents`."

    Design: Difficulty/boundary_precision_check/release_exactly_at_statutory_due_accrues_nothing
    """
    scenario = _two_waived_requests_due_at_the_end_of_august(api)

    for invoice_id in (scenario["invoice_a"], scenario["invoice_b"]):
        invoice = fx.read_invoice(api, invoice_id)
        assert invoice["status"] == "WAIVED"
        assert invoice["subtotal_cents"] == 2651
        assert invoice["amount_due_cents"] == 2651

    assert_facility_money(fx.read_facility(api, scenario["world"]["facility_id"]), 0, 0, 5302)


def test_releasing_on_the_deadline_instant_accrues_no_penalty_at_all(api):
    """The lateness predicate is strict, so equality is on time.

    PRD: "When the effective completion instant is strictly later than `statutory_due_at`, the statutory measure, reported as `penalty_exposure_cents`, counts raw elapsed time with no grace: take the seconds between `statutory_due_at` and the effective completion instant, divide by 86400 seconds per day, and round the quotient **up** to the next whole day to obtain the strict days-late figure; multiply that figure by the fee rule's `penalty_per_day_cents`; and take the smaller of that product and the rule's `penalty_cap_cents`."

    Design: Difficulty/boundary_precision_check/release_exactly_at_statutory_due_accrues_nothing
    """
    scenario = _release_one_on_the_instant_and_one_a_second_late(
        api, _two_waived_requests_due_at_the_end_of_august(api)
    )
    request = fx.read_request(api, scenario["request_a"])

    assert request["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")
    assert request["released_at"] == Instant("2026-08-31T00:00:00Z")
    assert request["penalty_exposure_cents"] == 0
    assert request["safe_harbor_penalty_cents"] == 0


def test_the_turnaround_read_reports_the_on_time_request_as_unbreached(api):
    """Every day count on the computed read is 0 when completion equals the deadline.

    PRD: "A non-persisting computed read exposes the whole calculation for one request: it returns `statutory_due_at`, `effective_completion_at`, `tolled_seconds`, `extension_applied`, a `breached` boolean that is true exactly when the effective completion instant is strictly later than `statutory_due_at`, `days_late_strict`, `days_late_business`, `chargeable_days`, `penalty_exposure_cents` and `safe_harbor_penalty_cents`."

    Design: Difficulty/boundary_precision_check/release_exactly_at_statutory_due_accrues_nothing
    """
    scenario = _release_one_on_the_instant_and_one_a_second_late(
        api, _two_waived_requests_due_at_the_end_of_august(api)
    )
    turnaround = get_success_data(api.get_turnaround(scenario["request_a"], BILLING_1))

    assert turnaround["breached"] is False
    assert turnaround["days_late_strict"] == 0
    assert turnaround["days_late_business"] == 0
    assert turnaround["chargeable_days"] == 0
    assert turnaround["effective_completion_at"] == Instant("2026-08-31T00:00:00Z")


def test_one_second_of_overrun_costs_a_whole_strict_day(api):
    """Rounding up means a single second buys 2500 cents of statutory exposure.

    PRD: "Five and a quarter days overrun therefore counts as six late days."

    Design: Difficulty/boundary_precision_check/release_exactly_at_statutory_due_accrues_nothing
    """
    scenario = _release_one_on_the_instant_and_one_a_second_late(
        api, _two_waived_requests_due_at_the_end_of_august(api)
    )
    request = fx.read_request(api, scenario["request_b"])
    turnaround = get_success_data(api.get_turnaround(scenario["request_b"], BILLING_1))

    assert request["released_at"] == Instant("2026-08-31T00:00:01Z")
    assert request["penalty_exposure_cents"] == 2500
    assert turnaround["breached"] is True
    assert turnaround["days_late_strict"] == 1


def test_the_safe_harbour_measure_still_forgives_the_one_second_overrun(api):
    """No UTC business date has yet passed the deadline date, so nothing is chargeable.

    PRD: "Count the UTC calendar dates that fall strictly after the calendar date of `statutory_due_at` and at or before the calendar date of the effective completion instant, keeping only those that are a Monday, Tuesday, Wednesday, Thursday or Friday; that count is the business days-late figure."

    Design: Difficulty/boundary_precision_check/release_exactly_at_statutory_due_accrues_nothing
    """
    scenario = _release_one_on_the_instant_and_one_a_second_late(
        api, _two_waived_requests_due_at_the_end_of_august(api)
    )
    request = fx.read_request(api, scenario["request_b"])
    turnaround = get_success_data(api.get_turnaround(scenario["request_b"], BILLING_1))

    assert request["safe_harbor_penalty_cents"] == 0
    assert turnaround["days_late_business"] == 0
    assert turnaround["chargeable_days"] == 0
    assert turnaround["safe_harbor_penalty_cents"] == 0


def test_only_the_late_release_leaves_a_breach_event(api):
    """The evidentiary record separates the two releases by one second.

    PRD: "When `released_at` is strictly later than `statutory_due_at`, a `STATUTORY_DEADLINE_BREACHED` compliance event is appended."

    Design: Difficulty/boundary_precision_check/release_exactly_at_statutory_due_accrues_nothing
    """
    scenario = _release_one_on_the_instant_and_one_a_second_late(
        api, _two_waived_requests_due_at_the_end_of_august(api)
    )

    assert_no_event(fx.read_events(api, scenario["request_a"]), "STATUTORY_DEADLINE_BREACHED")
    assert_event_count(
        fx.read_events(api, scenario["request_b"]), "STATUTORY_DEADLINE_BREACHED", 1
    )


def test_the_facility_exposure_sums_only_the_late_request(api):
    """The facility roll-up is a plain sum over its requests, and only one is late.

    PRD: "The fourth field, `penalty_exposure_cents` on the facility, is the sum of `penalty_exposure_cents` over every request whose `facility_id` names this facility, and it is refreshed whenever any request's penalty exposure moves."

    Design: Difficulty/boundary_precision_check/release_exactly_at_statutory_due_accrues_nothing
    """
    scenario = _release_one_on_the_instant_and_one_a_second_late(
        api, _two_waived_requests_due_at_the_end_of_august(api)
    )
    facility = fx.read_facility(api, scenario["world"]["facility_id"])

    assert facility["penalty_exposure_cents"] == 2500
    assert_facility_money(facility, 0, 0, 5302)
