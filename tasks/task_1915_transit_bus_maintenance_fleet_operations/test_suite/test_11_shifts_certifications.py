"""Shifts, assignments, and certifications: half-open overlap, duplicate
guards, coverage computation, publish gating, and epoch cert expiry."""
from test_helpers import (
    ApiErrorId,
    add_labor,
    assert_shift,
    assert_shift_assignment,
    assign_mechanic,
    confirm_assignment,
    create_in_progress_wo,
    create_shift_assignment_payload,
    get_success_data,
    grant_cert,
    new_bus,
    new_mechanic,
    new_mechanic_with_certs,
    new_published_shift,
    new_qa_mechanic,
    new_shift,
    publish_shift,
    run_epoch,
    validate_error,
    validate_success,
    wo_event,
)
from test_helpers import fixtures as fx


class TestShiftAssignmentOverlap:
    """Half-open interval semantics for one mechanic's same-date shifts."""

    def test_adjacent_am_then_pm_assignment_allowed(self, api):
        """PRD §3.12: "The three shift types are fixed half-open intervals on
        the clock: `AM` covers 06:00 up to but not including 14:00; `PM` covers
        14:00 up to but not including 22:00; and `NIGHT` covers 22:00 up to but
        not including 06:00 the following day."
        PRD §3.12: "the mechanic's fixed half-open shift intervals on the same
        `shift_date` must not overlap any existing `SCHEDULED` or `CONFIRMED`
        assignment — adjacency, where one interval's end equals the other's
        start, is allowed (otherwise `ERR_SHIFT_OVERLAP`)."

        AM [06:00,14:00) and PM [14:00,22:00) touch at 14:00: adjacency.

        Design: Difficulty/resource_temporal_overlap/shift_assignment_half_open_adjacency_vs_overlap
        """
        mech = new_mechanic(name="Tech", employee_ref="E100")
        am = new_published_shift(shift_date="2026-08-05", shift_type="AM")
        pm = new_published_shift(shift_date="2026-08-05", shift_type="PM")
        first = assign_mechanic(am["id"], mech["id"])
        assert first["status"] == "SCHEDULED"

        second = validate_success(
            api.create_shift_assignment(
                pm["id"], create_shift_assignment_payload(mech["id"]), fx.SUP
            ),
            201,
        )
        assert_shift_assignment(second)
        assert second["status"] == "SCHEDULED", "14:00 adjacency is not an overlap"

    def test_second_am_assignment_overlaps(self, api):
        """PRD §3.12: "the mechanic's fixed half-open shift intervals on the
        same `shift_date` must not overlap any existing `SCHEDULED` or
        `CONFIRMED` assignment — adjacency, where one interval's end equals the
        other's start, is allowed (otherwise `ERR_SHIFT_OVERLAP`)."

        Two AM shifts on the same date both cover [06:00,14:00).

        Design: Difficulty/resource_temporal_overlap/shift_assignment_half_open_adjacency_vs_overlap
        """
        mech = new_mechanic(name="Tech", employee_ref="E100")
        am1 = new_published_shift(shift_date="2026-08-05", shift_type="AM")
        am2 = new_published_shift(shift_date="2026-08-05", shift_type="AM")
        assign_mechanic(am1["id"], mech["id"])

        res = api.create_shift_assignment(
            am2["id"], create_shift_assignment_payload(mech["id"]), fx.SUP
        )
        validate_error(res, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestDuplicateAssignmentPriority:
    """Referential duplicate guard beats the temporal overlap rule."""

    def test_duplicate_on_same_shift_reports_duplicate_assignment(self, api):
        """PRD §3.12: "Two uniqueness checks run at assign: no other
        non-`REMOVED` assignment may exist for the same shift and mechanic
        (otherwise `ERR_DUPLICATE_ASSIGNMENT`), and the mechanic's fixed
        half-open shift intervals on the same `shift_date` must not overlap any
        existing `SCHEDULED` or `CONFIRMED` assignment"
        PRD §2.10: "The band order is: authentication, then authorization and
        ownership, then existence of path and body references, then
        schema/format, then state-machine legality, then optimistic
        concurrency, then safety (certification, segregation-of-duties,
        safety-defect handling, on-shift dispatch), then referential
        uniqueness, then temporal windows, then business constraint, then
        fiscal."

        Re-assigning the same mechanic to the same AM shift violates both the
        duplicate rule and the overlap rule; referential uniqueness precedes
        temporal windows, so ERR_DUPLICATE_ASSIGNMENT surfaces.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_duplicate_shift_assignment
        """
        mech = new_mechanic(name="Tech", employee_ref="E70")
        shift = new_published_shift(shift_date="2026-08-05", shift_type="AM")
        assign_mechanic(shift["id"], mech["id"])

        res = api.create_shift_assignment(
            shift["id"], create_shift_assignment_payload(mech["id"]), fx.SUP
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)
        assignments = get_success_data(api.list_shift_assignments(shift["id"], fx.SUP))
        assert len(assignments) == 1, "the shift still has exactly one assignment"

    def test_duplicate_rule_covers_confirmed_assignments(self, api):
        """PRD §3.12: "Two uniqueness checks run at assign: no other
        non-`REMOVED` assignment may exist for the same shift and mechanic
        (otherwise `ERR_DUPLICATE_ASSIGNMENT`)"

        A CONFIRMED assignment is non-REMOVED, so re-assigning still reports
        ERR_DUPLICATE_ASSIGNMENT.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_duplicate_shift_assignment
        """
        mech = new_mechanic(name="Tech", employee_ref="E70B")
        shift = new_published_shift(shift_date="2026-08-05", shift_type="AM")
        first = assign_mechanic(shift["id"], mech["id"])
        confirm_assignment(first["id"], mech["id"])

        res = api.create_shift_assignment(
            shift["id"], create_shift_assignment_payload(mech["id"]), fx.SUP
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)


def test_shift_coverage_vacuous_full_and_zero_coverage_short(api):
    """PRD §3.12: "Publishing a shift moves it to `PUBLISHED` and computes its
    initial `coverage_by_cert`; with zero assignments yet, every required cert
    starts short unless `required_headcount` is empty, in which case coverage
    is vacuously `FULL`."
    PRD §3.12: "The shift's `coverage_status` is `FULL` when every required
    cert meets its headcount (vacuously `FULL` when `required_headcount` is
    empty) and `SHORT` otherwise."
    PRD §3.12: "For each cert type in `required_headcount`, the covered count
    is the number of assignments in `CONFIRMED` status whose mechanic holds a
    certification of that type with status `VALID` or `EXPIRING_SOON`."

    Design: Corner/calculations/shift_coverage_vacuous_full_and_zero_coverage_short
    """
    mech = new_mechanic_with_certs("ENGINE", name="Tech")
    open_shift = new_shift(shift_date="2026-08-10", shift_type="AM",
                           required_headcount={})
    published_open = publish_shift(open_shift["id"])
    assert_shift(published_open)
    assert published_open["coverage_status"] == "FULL", "empty requirements are vacuously FULL"

    short_shift = new_shift(shift_date="2026-08-10", shift_type="PM",
                            required_headcount={"ENGINE": 1})
    published_short = publish_shift(short_shift["id"])
    assert published_short["coverage_status"] == "SHORT", (
        "zero assignments leave the ENGINE requirement short"
    )

    assignment = assign_mechanic(published_short["id"], mech["id"])
    confirm_assignment(assignment["id"], mech["id"])
    after = get_success_data(api.get_shift(published_short["id"], fx.SUP))
    assert after["coverage_status"] == "FULL", (
        "one CONFIRMED ENGINE-certified assignment meets {ENGINE: 1}"
    )
    assert after["coverage_by_cert"]["ENGINE"] == 1


def test_assignment_on_draft_shift_rejected(api):
    """PRD §3.12: "A supervisor assigns a mechanic by `mechanic_id` and a
    `role_in_shift` of `LEAD`, `TECH`, or `QA`; the assignment's `shift_id`
    references the parent shift, which must be `PUBLISHED` (otherwise
    `ERR_SHIFT_NOT_PUBLISHED`)."

    Design: Corner/validations/assignment_on_draft_shift_rejected
    """
    mech = new_mechanic(name="Tech", employee_ref="Y31A")
    shift = new_shift(shift_date="2026-08-10", shift_type="AM")
    assert shift["status"] == "DRAFT"

    res = api.create_shift_assignment(
        shift["id"], create_shift_assignment_payload(mech["id"]), fx.SUP
    )
    validate_error(res, ApiErrorId.ERR_SHIFT_NOT_PUBLISHED)


def test_expired_cert_blocks_qa_certify_after_epoch(api):
    """PRD §3.12: "A certification's `status` is recomputed by the epoch sweep
    against the logical clock: `VALID` moves to `EXPIRING_SOON` when the expiry
    date is between 0 and 30 days out inclusive, and either `VALID` or
    `EXPIRING_SOON` moves to `EXPIRED` once the expiry date is strictly before
    the clock date."
    PRD §3.12: "A mechanic whose certification has expired no longer counts
    toward shift coverage and fails every certification gate described in §3.3
    and §3.4."
    PRD §3.4: "A QA decision is made by a mechanic holding `QA_AUTHORITY` with
    status `VALID` or `EXPIRING_SOON` (otherwise `ERR_CERT_REQUIRED` or
    `ERR_CERT_EXPIRED`)."

    Expiry 2026-07-01 is strictly before the clock date 2026-08-01.

    Design: Corner/validations/expired_cert_blocks_qa_certify_after_epoch
    """
    bus = new_bus(fleet_number="Y20", vin="VINY20", model_year=2021,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    lead = new_mechanic(name="Lead", employee_ref="Y20A")
    qa = new_mechanic(name="QA", employee_ref="Y20B")
    cert = grant_cert(qa["id"], "QA_AUTHORITY", issued_date="2026-01-01",
                      expiry_date="2026-07-01")
    wo = create_in_progress_wo(bus["id"], lead)
    add_labor(wo["id"], lead, hours=1)
    wo_event(wo["id"], "SUBMIT_QA", headers=fx.make_mechanic_headers(lead["id"]))

    summary = run_epoch()
    assert summary["certifications_expired"] == 1, (
        f"exactly one certification expires; summary: {summary}"
    )
    cert_after = get_success_data(api.get_certification(cert["id"], fx.SUP))
    assert cert_after["status"] == "EXPIRED"

    res = wo_event(wo["id"], "QA_CERTIFY",
                   headers=fx.make_mechanic_headers(qa["id"]))
    validate_error(res, ApiErrorId.ERR_CERT_EXPIRED)
    after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
    assert after["status"] == "PENDING_QA"
