"""Compliance-period derivation: the flat requirement, the proration anchor,
the group filing deadline and the exemption short-circuit.

Each test builds its own register through the declared endpoints, because the
board's data is empty when the test begins.
"""
from datetime import datetime, timezone

from test_helpers import (
    assert_whole_hour_requirement,
    change_attorney_status,
    create_attorney,
    create_compliance_cycle_payload,
    read_attorney,
    read_cycle,
    validate_success,
)

FULL_PERIOD_START = "2026-01-01T00:00:00Z"
FULL_PERIOD_END = "2028-01-01T00:00:00Z"


def as_instant(value):
    """Reads an ISO 8601 UTC timestamp, so a pinned literal and the rendered
    value compare as the same instant however many fractional digits it
    carries."""
    assert isinstance(value, str), f"expected an ISO 8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_same_instant(actual, expected, label):
    assert as_instant(actual) == as_instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


def open_period(api, board_headers, attorney_id, period_start, period_end, **extra):
    """Opens one compliance period through the declared creation endpoint."""
    payload = create_compliance_cycle_payload(
        period_start=period_start, period_end=period_end, **extra
    )
    response = api.create_compliance_cycle(attorney_id, payload, board_headers)
    return validate_success(response, expected_status=201)


def test_full_length_period_derives_the_flat_thirty_hour_requirement(api, board_headers):
    """PRD §3.4: "A full 24-month cycle therefore requires exactly 1800 minutes, and a shortened one requires a whole number of hours' worth of minutes and never a fraction of an hour."
    PRD §3.4: "When the cycle is not prorated at all, or when the month count is 12 or more, they apply in full: `required_ethics_minutes` is 180 minutes (3 hours), `required_technology_minutes` is 60 minutes (1 hour) and `required_bias_minutes` is 120 minutes (2 hours)."
    PRD §3.4: "Otherwise, `prorated` is true exactly when the attorney's `admission_date` falls inside the cycle's half-open window — that is, when it is at or after `period_start` and strictly before `period_end`."

    Design: Corner/calculations/a_full_length_cycle_takes_the_flat_requirement_and_its_group_filing_deadline
    """
    for group in ("GROUP_1", "GROUP_2", "GROUP_3"):
        attorney = create_attorney(
            admission_date="2004-01-01T00:00:00Z", compliance_group=group
        )
        cycle = open_period(
            api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
        )

        assert cycle["prorated"] is False, (
            f"an attorney admitted long before {FULL_PERIOD_START} is not prorated, "
            f"got prorated={cycle['prorated']!r} for {group}"
        )
        assert cycle["required_total_minutes"] == 1800, (
            "a full 24-month period requires exactly 1800 minutes, got "
            f"{cycle['required_total_minutes']} for {group}"
        )
        assert_whole_hour_requirement(cycle["required_total_minutes"])
        assert cycle["required_ethics_minutes"] == 180, (
            f"required_ethics_minutes must be 180, got {cycle['required_ethics_minutes']}"
        )
        assert cycle["required_technology_minutes"] == 60, (
            "required_technology_minutes must be 60, got "
            f"{cycle['required_technology_minutes']}"
        )
        assert cycle["required_bias_minutes"] == 120, (
            f"required_bias_minutes must be 120, got {cycle['required_bias_minutes']}"
        )


def test_filing_deadline_offset_is_drawn_from_the_compliance_group(api, board_headers):
    """PRD §3.4: "Finally, `filing_deadline` is `period_end` plus an offset drawn from the attorney's `compliance_group`: 31 days for `GROUP_1`, 61 days for `GROUP_2` and 91 days for `GROUP_3`."
    PRD §2.4: "Day arithmetic — the roster due date, the appeal window, the suspension interval, the grace window, the filing-deadline offsets — is UTC calendar-day arithmetic against the logical clock."

    Design: Corner/calculations/a_full_length_cycle_takes_the_flat_requirement_and_its_group_filing_deadline
    """
    expected_deadlines = {
        "GROUP_1": "2028-02-01T00:00:00Z",
        "GROUP_2": "2028-03-02T00:00:00Z",
        "GROUP_3": "2028-04-01T00:00:00Z",
    }
    for group, expected in expected_deadlines.items():
        attorney = create_attorney(
            admission_date="2004-01-01T00:00:00Z", compliance_group=group
        )
        cycle = open_period(
            api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
        )
        assert_same_instant(
            cycle["filing_deadline"], expected, f"the {group} filing_deadline"
        )


def test_a_fresh_period_opens_with_no_credit_and_no_carried_in_minutes(api, board_headers):
    """PRD §2.10: "`credit_status` tracks the credit picture and takes `OPEN`, `SATISFIED`, `DEFICIENT` or `CLOSED_COMITY`, starting at `OPEN`."
    PRD §2.10: "`administrative_status` tracks the filing picture and takes `GOOD_STANDING`, `DELINQUENT`, `ADMIN_SUSPENDED` or `REINSTATED`, starting at `GOOD_STANDING`."
    PRD §3.4: "Where it is omitted, both carried-in figures are zero."
    PRD §3.6: "Four running category totals and two running overall totals — countable minutes and live minutes — likewise start at zero."
    PRD §3.6: "When every record in the input set has been processed, the overall countable total becomes `earned_countable_minutes`, the three specialty running totals become `earned_ethics_minutes`, `earned_technology_minutes` and `earned_bias_minutes`, and the running live total becomes `earned_live_minutes`."

    Design: Corner/calculations/a_full_length_cycle_takes_the_flat_requirement_and_its_group_filing_deadline
    """
    attorney = create_attorney(
        admission_date="2004-01-01T00:00:00Z", compliance_group="GROUP_1"
    )
    cycle = open_period(
        api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
    )

    assert cycle["credit_status"] == "OPEN", (
        f"a new period starts at OPEN, got {cycle['credit_status']}"
    )
    assert cycle["administrative_status"] == "GOOD_STANDING", (
        f"a new period starts at GOOD_STANDING, got {cycle['administrative_status']}"
    )
    assert cycle["carryover_in_general_minutes"] == 0, (
        "an omitted carryover leaves carryover_in_general_minutes at zero, got "
        f"{cycle['carryover_in_general_minutes']}"
    )
    assert cycle["carryover_in_ethics_minutes"] == 0, (
        "an omitted carryover leaves carryover_in_ethics_minutes at zero, got "
        f"{cycle['carryover_in_ethics_minutes']}"
    )
    assert cycle["earned_countable_minutes"] == 0, (
        "a period with no credit records has earned no countable minutes, got "
        f"{cycle['earned_countable_minutes']}"
    )


def test_admission_inside_the_period_prorates_from_the_month_after_admission(
    api, board_headers
):
    """PRD §3.4: "Otherwise, `prorated` is true exactly when the attorney's `admission_date` falls inside the cycle's half-open window — that is, when it is at or after `period_start` and strictly before `period_end`."
    PRD §3.4: "When `prorated` is true, the count is measured from an anchor rather than from the admission date itself: the anchor is UTC midnight on the first day of the calendar month *after* the month containing `admission_date`, and the month count is the number of whole calendar months from that anchor to `period_end`, clamped so that it is never below 0 and never above 24."
    PRD §3.4: "Multiply 1800 by the month count, divide by 24, and divide by 60 to obtain an exact rational number of credit hours; round that number **up** to the next whole credit hour, and multiply by 60 to express it back in minutes."
    PRD §3.4: "A full 24-month cycle therefore requires exactly 1800 minutes, and a shortened one requires a whole number of hours' worth of minutes and never a fraction of an hour."

    Design: Corner/calculations/a_newly_admitted_attorney_is_prorated_from_the_month_after_admission
    """
    attorney = create_attorney(
        admission_date="2027-03-15T00:00:00Z", compliance_group="GROUP_1"
    )
    cycle = open_period(
        api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
    )

    assert cycle["prorated"] is True, (
        "an admission on 2027-03-15 falls inside the 2026-01-01..2028-01-01 window, "
        f"so the period is prorated, got prorated={cycle['prorated']!r}"
    )
    assert cycle["required_total_minutes"] == 720, (
        "the anchor is 2027-04-01, nine whole months short of 2028-01-01, so 1800 x 9 "
        "/ 24 is 675 minutes, 11.25 credit hours, which rounds up to 12 credit hours "
        f"of 720 minutes, got {cycle['required_total_minutes']}"
    )
    assert_whole_hour_requirement(cycle["required_total_minutes"])


def test_a_short_proration_reduces_the_specialty_minimums(api, board_headers):
    """PRD §3.4: "When the cycle is prorated to fewer than 12 months, the reduced floors apply: `required_ethics_minutes` is 90 minutes, `required_technology_minutes` remains 60 minutes, and `required_bias_minutes` is 60 minutes."
    PRD §3.4: "Finally, `filing_deadline` is `period_end` plus an offset drawn from the attorney's `compliance_group`: 31 days for `GROUP_1`, 61 days for `GROUP_2` and 91 days for `GROUP_3`."

    Design: Corner/calculations/a_newly_admitted_attorney_is_prorated_from_the_month_after_admission
    """
    attorney = create_attorney(
        admission_date="2027-03-15T00:00:00Z", compliance_group="GROUP_1"
    )
    cycle = open_period(
        api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
    )

    assert cycle["required_ethics_minutes"] == 90, (
        "a nine-month proration reduces the ethics floor to 90 minutes, got "
        f"{cycle['required_ethics_minutes']}"
    )
    assert cycle["required_technology_minutes"] == 60, (
        "the technology floor stays at 60 minutes under a short proration, got "
        f"{cycle['required_technology_minutes']}"
    )
    assert cycle["required_bias_minutes"] == 60, (
        "a nine-month proration reduces the elimination-of-bias floor to 60 minutes, "
        f"got {cycle['required_bias_minutes']}"
    )
    assert_same_instant(
        cycle["filing_deadline"],
        "2028-02-01T00:00:00Z",
        "the GROUP_1 filing_deadline of a prorated period",
    )


def test_a_twelve_month_proration_keeps_the_full_specialty_minimums(api, board_headers):
    """PRD §3.4: "When the cycle is not prorated at all, or when the month count is 12 or more, they apply in full: `required_ethics_minutes` is 180 minutes (3 hours), `required_technology_minutes` is 60 minutes (1 hour) and `required_bias_minutes` is 120 minutes (2 hours)."
    PRD §3.4: "When `prorated` is true, the count is measured from an anchor rather than from the admission date itself: the anchor is UTC midnight on the first day of the calendar month *after* the month containing `admission_date`, and the month count is the number of whole calendar months from that anchor to `period_end`, clamped so that it is never below 0 and never above 24."
    PRD §3.4: "Multiply 1800 by the month count, divide by 24, and divide by 60 to obtain an exact rational number of credit hours; round that number **up** to the next whole credit hour, and multiply by 60 to express it back in minutes."

    Design: Corner/calculations/the_proration_specialty_threshold_is_inclusive_at_exactly_twelve_months
    """
    attorney = create_attorney(
        admission_date="2026-12-05T00:00:00Z", compliance_group="GROUP_1"
    )
    cycle = open_period(
        api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
    )

    assert cycle["prorated"] is True, (
        "an admission on 2026-12-05 falls inside the period, so it is prorated, got "
        f"prorated={cycle['prorated']!r}"
    )
    assert cycle["required_total_minutes"] == 900, (
        "the anchor is 2027-01-01, exactly twelve whole months short of 2028-01-01, "
        f"so 1800 x 12 / 24 is 900 minutes, got {cycle['required_total_minutes']}"
    )
    assert cycle["required_ethics_minutes"] == 180, (
        "a month count of exactly 12 keeps the full 180-minute ethics floor, got "
        f"{cycle['required_ethics_minutes']}"
    )
    assert cycle["required_technology_minutes"] == 60, (
        f"required_technology_minutes must be 60, got {cycle['required_technology_minutes']}"
    )
    assert cycle["required_bias_minutes"] == 120, (
        "a month count of exactly 12 keeps the full 120-minute elimination-of-bias "
        f"floor, got {cycle['required_bias_minutes']}"
    )


def test_an_eleven_month_proration_reduces_the_specialty_minimums(api, board_headers):
    """PRD §3.4: "When the cycle is prorated to fewer than 12 months, the reduced floors apply: `required_ethics_minutes` is 90 minutes, `required_technology_minutes` remains 60 minutes, and `required_bias_minutes` is 60 minutes."
    PRD §3.4: "When `prorated` is true, the count is measured from an anchor rather than from the admission date itself: the anchor is UTC midnight on the first day of the calendar month *after* the month containing `admission_date`, and the month count is the number of whole calendar months from that anchor to `period_end`, clamped so that it is never below 0 and never above 24."
    PRD §3.4: "Multiply 1800 by the month count, divide by 24, and divide by 60 to obtain an exact rational number of credit hours; round that number **up** to the next whole credit hour, and multiply by 60 to express it back in minutes."

    Design: Corner/calculations/the_proration_specialty_threshold_is_inclusive_at_exactly_twelve_months
    """
    attorney = create_attorney(
        admission_date="2027-01-01T00:00:00Z", compliance_group="GROUP_1"
    )
    cycle = open_period(
        api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
    )

    assert cycle["prorated"] is True, (
        "an admission on 2027-01-01 falls inside the period, so it is prorated, got "
        f"prorated={cycle['prorated']!r}"
    )
    assert cycle["required_total_minutes"] == 840, (
        "the anchor is 2027-02-01, eleven whole months short of 2028-01-01, so 1800 x "
        "11 / 24 is 825 minutes, 13.75 credit hours, which rounds up to 14 credit "
        f"hours of 840 minutes, got {cycle['required_total_minutes']}"
    )
    assert_whole_hour_requirement(cycle["required_total_minutes"])
    assert cycle["required_ethics_minutes"] == 90, (
        "one month short of the threshold reduces the ethics floor to 90 minutes, got "
        f"{cycle['required_ethics_minutes']}"
    )
    assert cycle["required_technology_minutes"] == 60, (
        f"required_technology_minutes must be 60, got {cycle['required_technology_minutes']}"
    )
    assert cycle["required_bias_minutes"] == 60, (
        "one month short of the threshold reduces the elimination-of-bias floor to 60 "
        f"minutes, got {cycle['required_bias_minutes']}"
    )


def test_an_exempt_attorney_derives_a_zero_requirement(api, board_headers):
    """PRD §3.4: "If the attorney's `status` is `EXEMPT` at that instant, the derivation short-circuits: `required_total_minutes`, `required_ethics_minutes`, `required_technology_minutes` and `required_bias_minutes` are all zero and `prorated` is false."
    PRD §3.4: "Finally, `filing_deadline` is `period_end` plus an offset drawn from the attorney's `compliance_group`: 31 days for `GROUP_1`, 61 days for `GROUP_2` and 91 days for `GROUP_3`."
    PRD §3.4: "Board staff may move an attorney between `ACTIVE`, `EXEMPT` and `INACTIVE` by supplying the target `status` and an optional `reason`; this is the only actor-driven writer of that field."

    Design: Corner/calculations/an_exempt_attorney_gets_a_zero_requirement_that_is_never_re_derived
    """
    attorney = create_attorney(
        admission_date="2026-06-15T00:00:00Z", compliance_group="GROUP_2"
    )
    change_attorney_status(attorney["id"], "EXEMPT", reason="Full-time judicial service")

    cycle = open_period(
        api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
    )

    assert cycle["required_total_minutes"] == 0, (
        "an EXEMPT attorney's period requires no minutes at all, got "
        f"{cycle['required_total_minutes']}"
    )
    assert cycle["required_ethics_minutes"] == 0, (
        f"required_ethics_minutes must be zero, got {cycle['required_ethics_minutes']}"
    )
    assert cycle["required_technology_minutes"] == 0, (
        "required_technology_minutes must be zero, got "
        f"{cycle['required_technology_minutes']}"
    )
    assert cycle["required_bias_minutes"] == 0, (
        f"required_bias_minutes must be zero, got {cycle['required_bias_minutes']}"
    )
    assert cycle["prorated"] is False, (
        "the exemption short-circuit leaves prorated false even though the admission "
        f"date falls inside the period, got prorated={cycle['prorated']!r}"
    )
    assert_same_instant(
        cycle["filing_deadline"],
        "2028-03-02T00:00:00Z",
        "the GROUP_2 filing_deadline of an exempt attorney's period",
    )


def test_the_requirement_is_never_re_derived_after_the_exemption_ends(api, board_headers):
    """PRD §3.4: "The four requirement figures, the proration flag and the filing deadline are all computed once, at the instant the cycle is created, from the single attorney record named on it."
    PRD §3.4: "No credit record participates, and none of these figures is ever re-derived afterwards — not when the attorney's standing changes, not at certification, not by a batch run."
    PRD §3.4: "If the attorney's `status` is `EXEMPT` at that instant, the derivation short-circuits: `required_total_minutes`, `required_ethics_minutes`, `required_technology_minutes` and `required_bias_minutes` are all zero and `prorated` is false."
    PRD §3.4: "A full 24-month cycle therefore requires exactly 1800 minutes, and a shortened one requires a whole number of hours' worth of minutes and never a fraction of an hour."
    PRD §3.4: "Two periods of the same attorney may not intersect: an overlap is `ERR_CYCLE_PERIOD_OVERLAP`, while exact adjacency — a new period whose `period_start` equals an existing period's `period_end` — is explicitly allowed, because the half-open convention means the two share no instant."

    Design: Corner/calculations/an_exempt_attorney_gets_a_zero_requirement_that_is_never_re_derived
    """
    attorney = create_attorney(
        admission_date="2026-06-15T00:00:00Z", compliance_group="GROUP_2"
    )
    change_attorney_status(attorney["id"], "EXEMPT", reason="Full-time judicial service")
    exempt_cycle = open_period(
        api, board_headers, attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END
    )

    change_attorney_status(attorney["id"], "ACTIVE", reason="Returned to practice")

    restored = read_attorney(attorney["id"])
    assert restored["status"] == "ACTIVE", (
        f"the attorney must be back on ACTIVE, got {restored['status']}"
    )

    reread = read_cycle(exempt_cycle["id"])
    assert reread["required_total_minutes"] == 0, (
        "the zero requirement is computed once and never re-derived, so restoring the "
        f"attorney to ACTIVE must leave it at zero, got {reread['required_total_minutes']}"
    )
    assert reread["required_ethics_minutes"] == 0, (
        f"required_ethics_minutes must still be zero, got {reread['required_ethics_minutes']}"
    )
    assert reread["required_technology_minutes"] == 0, (
        "required_technology_minutes must still be zero, got "
        f"{reread['required_technology_minutes']}"
    )
    assert reread["required_bias_minutes"] == 0, (
        f"required_bias_minutes must still be zero, got {reread['required_bias_minutes']}"
    )
    assert reread["prorated"] is False, (
        f"prorated must still be false, got prorated={reread['prorated']!r}"
    )

    successor = open_period(
        api,
        board_headers,
        attorney["id"],
        "2028-01-01T00:00:00Z",
        "2030-01-01T00:00:00Z",
    )
    assert successor["required_total_minutes"] == 1800, (
        "the next period is derived from the now-ACTIVE attorney whose admission date "
        "sits outside its window, so it takes the flat 1800 minutes, got "
        f"{successor['required_total_minutes']}"
    )
    assert successor["required_bias_minutes"] == 120, (
        "the successor period takes the full 120-minute elimination-of-bias floor, got "
        f"{successor['required_bias_minutes']}"
    )
    assert successor["prorated"] is False, (
        "an admission date of 2026-06-15 sits before the 2028-01-01 period start, so "
        f"the successor is not prorated, got prorated={successor['prorated']!r}"
    )
