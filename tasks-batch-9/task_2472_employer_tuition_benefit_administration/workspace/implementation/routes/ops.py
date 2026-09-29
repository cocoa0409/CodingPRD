"""The logical clock and the term-close operator batch."""

import domain
from auth import endpoint
from store import by_created, db, iso_ms, touch
from validate import body, bool_field, int_field, parse_iso_instant, string_field

from .common import object_response


def register(app):
    @app.post("/_clock/set_current_utc")
    @endpoint(["PlatformAdmin"])
    def set_clock():
        data = body()
        instant = parse_iso_instant(data, "to_iso8601")
        db.clock = instant
        domain.refresh_all_employees()
        return object_response({"current_utc": iso_ms(db.clock)})

    @app.post("/_ops/term-close")
    @endpoint(["PlatformAdmin"])
    def term_close():
        data = body()
        term_code = string_field(data, "term_code", max_len=16)
        run_annual_true_up = bool_field(
            data, "run_annual_true_up", required=False, default=False
        )
        tax_year = int_field(data, "tax_year", required=False, default=None)

        # step 1 — supersede elapsed policy versions
        superseded_policy_count = domain.supersede_elapsed_policies()

        term_enrollments = by_created(
            [e for e in db.enrollments.values() if e["term_code"] == term_code]
        )

        # step 2 — close unreported coursework
        newly_incomplete = []
        for enrollment in term_enrollments:
            if enrollment["academic_status"] != "IN_PROGRESS":
                continue
            if domain.outcomes_of(enrollment["id"]):
                continue
            enrollment["academic_status"] = "INCOMPLETE"
            domain.append_system_outcome(enrollment, "INCOMPLETE")
            touch(enrollment)
            newly_incomplete.append(enrollment)

        # step 3 — the clawback chain on newly incomplete settled money
        obligation_assessed_count = 0
        for enrollment in newly_incomplete:
            if enrollment["funding_status"] != "SETTLED":
                continue
            if domain.assess_obligation(enrollment, "ACADEMIC_FAILURE") is not None:
                obligation_assessed_count += 1

        # step 4 — refresh persistence for the whole term and the coaching holds
        employees = []
        for enrollment in term_enrollments:
            domain.recompute_persistence(enrollment)
            touch(enrollment)
            employee = db.employees[enrollment["employee_id"]]
            if employee not in employees:
                employees.append(employee)
        coaching_hold_employee_count = 0
        for employee in by_created(employees):
            domain.refresh_and_touch(employee)
            if employee["coaching_hold"]:
                coaching_hold_employee_count += 1

        # step 5 — the annual aggregate true-up
        true_up_entry_count = 0
        if run_annual_true_up:
            year = tax_year if tax_year is not None else domain.clock_year()
            true_up_entry_count = domain.annual_true_up(year)

        return object_response(
            {
                "superseded_policy_count": superseded_policy_count,
                "closed_enrollment_count": len(newly_incomplete),
                "obligation_assessed_count": obligation_assessed_count,
                "true_up_entry_count": true_up_entry_count,
                "coaching_hold_employee_count": coaching_hold_employee_count,
            }
        )
