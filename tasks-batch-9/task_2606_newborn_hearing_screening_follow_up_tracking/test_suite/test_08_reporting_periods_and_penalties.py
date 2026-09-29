"""Reporting windows, attestation review, penalty assessment and waivers."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    OPERATOR_ONE_ID,
    OPERATOR_TWO_ID,
    make_facility_admin_headers,
    make_program_admin_headers,
    make_program_auditor_headers,
)

ADMIN = make_program_admin_headers()
AUDITOR = make_program_auditor_headers()
OPERATOR_ONE = make_program_auditor_headers(OPERATOR_ONE_ID)
OPERATOR_ONE_ADMIN = make_program_admin_headers(OPERATOR_ONE_ID)
OPERATOR_TWO_ADMIN = make_program_admin_headers(OPERATOR_TWO_ID)

AUGUST_END = "2026-09-01T00:00:00Z"
AUGUST_DUE = "2026-09-05T00:00:00Z"


def _august(client):
    """The August window with its due date four days past the period end."""
    return fixtures.open_period(client, CLOCK_START, AUGUST_END, AUGUST_DUE)


def test_a_closed_period_refuses_a_second_close(client):
    """The ops-run checkpoint is not replayable: the counters cannot be applied twice.

    PRD: "Penalties are assessed only at period close, once per assessed facility,
    and the arithmetic is order-sensitive."

    Design: Corner/state_machines/second_close_of_a_period_is_rejected_as_already_closed
    """
    period = _august(client)
    fixtures.set_clock(client, AUGUST_END)

    closed = fixtures.close_period(client, period["id"])
    assert closed["status"] == "CLOSED"
    check.assert_instant_equals(closed["closed_at"], AUGUST_END)
    assert closed["facilities_assessed_count"] == 0
    assert closed["episodes_escalated_count"] == 0
    assert closed["episodes_lost_count"] == 0

    replay = client.close_period(period["id"], {}, headers=ADMIN)
    check.assert_error_envelope(replay, errors.ERR_PERIOD_ALREADY_CLOSED)

    unchanged = fixtures.read_period(client, period["id"])
    assert unchanged["status"] == "CLOSED"
    assert unchanged["facilities_assessed_count"] == 0
    check.assert_instant_equals(unchanged["closed_at"], AUGUST_END)


def test_periods_that_touch_at_the_boundary_do_not_overlap(client):
    """September may start on the instant August ends, because the window is half-open.

    PRD: "The window is half-open: `period_start` is inclusive and `period_end` is
    exclusive, `period_end` must be strictly after `period_start`, and
    `submission_due_datetime` must be at or after `period_end`".

    Design: Corner/validations/adjacent_reporting_periods_touching_at_the_boundary_are_both_accepted
    """
    august = check.assert_created(
        client.create_period(
            factories.period_payload(
                period_start=CLOCK_START,
                period_end=AUGUST_END,
                submission_due_datetime=AUGUST_DUE,
            ),
            headers=ADMIN,
        )
    )
    september = check.assert_created(
        client.create_period(
            factories.period_payload(
                period_start=AUGUST_END,
                period_end="2026-10-01T00:00:00Z",
                submission_due_datetime="2026-10-05T00:00:00Z",
            ),
            headers=ADMIN,
        )
    )

    assert august["status"] == "OPEN"
    assert august["closed_at"] is None
    assert august["facilities_assessed_count"] == 0
    check.assert_instant_equals(september["period_start"], AUGUST_END)
    assert september["status"] == "OPEN"
    assert september["closed_at"] is None


def test_one_close_sweeps_every_facility_in_registration_order(client):
    """Both facilities are minted a non-filing report and charged the same way.

    PRD: "First, every facility whose `facility_type` is `BIRTH_HOSPITAL`,
    `BIRTHING_CENTER`, `MIDWIFE_PRACTICE`, or `AUDIOLOGY_CLINIC` is assessed in
    ascending `Facility.created_at` order — early intervention programs are not
    assessed and are not counted."

    Design: Corner/endpoints/period_close_assesses_every_facility_in_created_at_order
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    center = fixtures.create_facility(client, "BC1", "BIRTHING_CENTER", "R1")
    period = _august(client)
    fixtures.set_clock(client, AUGUST_END)

    closed = fixtures.close_period(client, period["id"])
    assert closed["status"] == "CLOSED"
    check.assert_instant_equals(closed["closed_at"], AUGUST_END)
    assert closed["facilities_assessed_count"] == 2
    assert closed["episodes_escalated_count"] == 0
    assert closed["episodes_lost_count"] == 0

    rows = check.assert_total_count(
        client.list_reports(headers=AUDITOR, reporting_period_id=period["id"]), 2
    )
    check.assert_created_at_ascending(rows)
    assert rows[0]["facility_id"] == hospital["id"]
    assert rows[1]["facility_id"] == center["id"]

    for report in rows:
        assert report["auto_generated"] is True
        assert report["status"] == "ACCEPTED"
        assert report["accepted_by_user_id"] is None
        check.assert_nulls(report, ["attested_screened_count", "attested_refer_count"])
        assert report["actual_screened_count"] == 0
        assert report["actual_refer_count"] == 0
        assert report["variance_case_count"] == 0
        check.assert_instant_equals(report["submitted_at"], AUGUST_END)
        assert report["submitted_late"] is False
        # No attestation at all: base points are twice the nil variance plus the
        # flat 5 for the missing report, and a pre-surcharge total of 5 attracts
        # the 25 percent tier, so 5 * 1.25 rounds half-up to 6.
        assert report["assessed_penalty_points"] == 6

    for facility_id in (hospital["id"], center["id"]):
        stored = fixtures.read_facility(client, facility_id)
        check.assert_facility_ledger(
            stored, penalty_points_balance=6, reporting_compliance_status="WATCH"
        )
        check.assert_nulls(
            stored, ["performance_score", "encounter_basis_performance_score"]
        )
        assert stored["last_closed_period_label"] is not None


def test_the_window_and_ordering_rules_around_a_period_are_all_enforced(client):
    """Overlap, an unfinished window and an older open period each block their call.

    PRD: "A new window must not intersect the half-open window of any existing
    period, else `ERR_PERIOD_OVERLAP`."

    Design: Corner/errors/period_creation_and_close_enforce_window_and_ordering_rules
    """
    august = _august(client)

    overlapping = client.create_period(
        factories.period_payload(
            period_start="2026-08-15T00:00:00Z",
            period_end="2026-09-15T00:00:00Z",
            submission_due_datetime="2026-09-20T00:00:00Z",
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(overlapping, errors.ERR_PERIOD_OVERLAP)

    september = fixtures.open_period(
        client, AUGUST_END, "2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"
    )
    assert september["status"] == "OPEN"

    too_early = client.close_period(august["id"], {}, headers=ADMIN)
    check.assert_error_envelope(too_early, errors.ERR_PERIOD_NOT_ENDED)
    assert fixtures.read_period(client, august["id"])["status"] == "OPEN"

    fixtures.set_clock(client, "2026-10-01T00:00:00Z")
    out_of_order = client.close_period(september["id"], {}, headers=ADMIN)
    check.assert_error_envelope(out_of_order, errors.ERR_EARLIER_PERIOD_OPEN)
    assert fixtures.read_period(client, september["id"])["status"] == "OPEN"

    closed = fixtures.close_period(client, august["id"])
    assert closed["status"] == "CLOSED"
    check.assert_instant_equals(closed["closed_at"], "2026-10-01T00:00:00Z")
    assert closed["facilities_assessed_count"] == 0


def test_a_second_filing_and_a_second_review_are_both_refused(client):
    """One live report per facility and period, and one acceptance of it.

    PRD: "At most one non-`SUPERSEDED` report may exist per facility and period: a
    second filing that does not name the incumbent in `supersedes_report_id` is
    rejected with `ERR_DUPLICATE_REPORT`".

    Design: Corner/errors/second_report_for_the_same_facility_period_pair_is_rejected_as_duplicate
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    period = _august(client)
    fixtures.set_clock(client, "2026-08-15T00:00:00Z")
    hospital_admin = make_facility_admin_headers(hospital["id"])
    report = fixtures.file_report(client, hospital["id"], period["id"], 0, 0)
    assert report["status"] == "SUBMITTED"

    duplicate = client.create_report(
        factories.report_payload(
            facility_id=hospital["id"],
            reporting_period_id=period["id"],
            attested_screened_count=1,
            attested_refer_count=0,
            expected_facility_version=fixtures.facility_version(client, hospital["id"]),
        ),
        headers=hospital_admin,
    )
    check.assert_error_envelope(duplicate, errors.ERR_DUPLICATE_REPORT)
    check.assert_total_count(
        client.list_reports(headers=AUDITOR, reporting_period_id=period["id"]), 1
    )

    premature_waiver = client.waive_report_penalty(
        report["id"], {"waiver_reason": "premature waiver attempt"}, headers=ADMIN
    )
    check.assert_error_envelope(premature_waiver, errors.ERR_REPORT_INVALID_STATE)
    assert fixtures.read_report(client, report["id"])["status"] == "SUBMITTED"

    accepted = fixtures.review_report(client, report["id"], "ACCEPT", headers=OPERATOR_ONE)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == OPERATOR_ONE_ID

    again = client.review_report(report["id"], {"decision": "ACCEPT"}, headers=OPERATOR_ONE)
    check.assert_error_envelope(again, errors.ERR_REPORT_INVALID_STATE)
    assert fixtures.read_report(client, report["id"])["status"] == "ACCEPTED"


def test_an_adjustment_may_not_drive_the_balance_below_zero(client):
    """The guard reads the resulting balance, not the sign of the delta.

    PRD: "An adjustment that would drive the balance below 0 is rejected with
    `ERR_NEGATIVE_PENALTY_BALANCE`."

    Design: Corner/errors/penalty_adjustment_cannot_drive_the_balance_below_zero
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    opening_version = hospital["version"]

    below_zero = client.create_penalty_adjustment(
        hospital["id"], {"points_delta": -1, "reason": "remit below zero"}, headers=ADMIN
    )
    check.assert_error_envelope(below_zero, errors.ERR_NEGATIVE_PENALTY_BALANCE)
    untouched = fixtures.read_facility(client, hospital["id"])
    check.assert_facility_ledger(
        untouched,
        penalty_points_balance=0,
        manual_adjustment_points_total=0,
        reporting_compliance_status="COMPLIANT",
    )
    check.assert_versioned(untouched, opening_version)

    sanctioned = fixtures.adjust_penalty(client, hospital["id"], 6, "late submission sanction")
    check.assert_facility_ledger(
        sanctioned,
        penalty_points_balance=6,
        manual_adjustment_points_total=6,
        reporting_compliance_status="WATCH",
    )

    over_remit = client.create_penalty_adjustment(
        hospital["id"], {"points_delta": -7, "reason": "over-remit"}, headers=ADMIN
    )
    check.assert_error_envelope(over_remit, errors.ERR_NEGATIVE_PENALTY_BALANCE)
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]),
        penalty_points_balance=6,
        reporting_compliance_status="WATCH",
    )

    remitted = fixtures.adjust_penalty(client, hospital["id"], -6, "full remission")
    check.assert_facility_ledger(
        remitted,
        penalty_points_balance=0,
        manual_adjustment_points_total=0,
        reporting_compliance_status="COMPLIANT",
    )


def test_the_accepting_operator_cannot_waive_the_penalty(client):
    """The waiver is barred for the operator recorded on the acceptance, not for the role.

    PRD: "Crucially, the waiving `X-User-ID` must differ from the report's
    `accepted_by_user_id`: the operator who accepted a filing may not later forgive
    its penalty, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_operator_who_accepted_a_report_cannot_waive_its_penalty
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    period = _august(client)
    fixtures.set_clock(client, "2026-08-15T00:00:00Z")
    report = fixtures.file_report(client, hospital["id"], period["id"], 3, 1)
    fixtures.review_report(
        client, report["id"], "ACCEPT", note="counts reconciled", headers=OPERATOR_ONE
    )
    fixtures.set_clock(client, AUGUST_END)
    fixtures.close_period(client, period["id"])

    assessed = fixtures.read_report(client, report["id"])
    # Three screens and one refer were attested where nothing was observed, so the
    # variance is 4 and the base is 2 * 4 with no lateness surcharge; a
    # pre-surcharge total of 8 sits in the 25 percent tier, giving exactly 10.
    assert assessed["variance_case_count"] == 4
    assert assessed["assessed_penalty_points"] == 10
    assert assessed["status"] == "ACCEPTED"
    assert assessed["accepted_by_user_id"] == OPERATOR_ONE_ID
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]),
        penalty_points_balance=10,
        reporting_compliance_status="PROBATION",
    )

    self_waiver = client.waive_report_penalty(
        report["id"],
        {"waiver_reason": "self-waiver by the accepting operator"},
        headers=OPERATOR_ONE_ADMIN,
    )
    check.assert_error_envelope(self_waiver, errors.ERR_SEGREGATION_OF_DUTIES)
    assert fixtures.read_report(client, report["id"])["status"] == "ACCEPTED"
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), penalty_points_balance=10
    )

    waived = fixtures.waive_penalty(
        client,
        report["id"],
        "documented data-entry error at the facility",
        headers=OPERATOR_TWO_ADMIN,
    )
    assert waived["status"] == "PENALTY_WAIVED"
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]),
        penalty_points_balance=0,
        reporting_compliance_status="COMPLIANT",
    )
