"""
Provisional projection versus final billing on a published sync run.

A run projects its seat charge at transform time from the dates the source system
asked for, and bills it at publish time from the dates the adds actually took
effect. When a September add is only published in October the two figures
disagree, and the district's reconciliation delta is the whole point of the
exercise — while the licence's own ledger stays untouched by either figure.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_integer_cents,
    assert_iso_date,
)
from test_helpers.types import (
    EnrollmentSource,
    GradeBand,
    RosteringStandard,
    RosterStatus,
    RunType,
    SeatModel,
    Subject,
    SyncRunState,
)

REQUESTED_ADD_DATE = "2026-09-01"
PUBLISH_CLOCK = "2026-10-01T00:00:00Z"
PUBLISH_DATE = "2026-10-01"
FULL_PRICE_PER_SEAT = 1000
PRORATED_PRICE_PER_SEAT = 604  # ceil(1000 * 79 remaining / 131 total days)


def _transformed_run_world(api):
    """
    Three students requested into one teacher-matched section for 1 September,
    under an ACTIVE per-student licence at 1000 cents a seat, with the run
    already transformed and the clock then moved to 1 October.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    school = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
    )
    term = fx.create_active_term(api)
    teacher = fx.create_teacher(
        api,
        school["id"],
        sis_staff_id="STF-1001",
        full_name="Dana Reed",
        email="dana.reed@district.k12",
    )
    students = [
        fx.create_student(
            api, school["id"], grade_level=4, sis_student_id="STU-2001",
            first_name="Alex", last_name="Nakamura", date_of_birth="2016-05-04",
        ),
        fx.create_student(
            api, school["id"], grade_level=4, sis_student_id="STU-2002",
            first_name="Priya", last_name="Rao", date_of_birth="2016-07-11",
        ),
        fx.create_student(
            api, school["id"], grade_level=4, sis_student_id="STU-2003",
            first_name="Liam", last_name="Osei", date_of_birth="2016-09-23",
        ),
    ]
    section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=3,
        meeting_days=["MON", "WED", "FRI"],
        max_seats=5,
        sis_section_id="SEC-3001",
        course_code="MATH4",
        subject=Subject.MATH,
    )
    enrollments = [
        fx.create_enrollment(
            api, section["id"], student["id"], REQUESTED_ADD_DATE,
            source=EnrollmentSource.SIS_EXTRACT,
        )
        for student in students
    ]
    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=10,
        price_per_seat_cents=FULL_PRICE_PER_SEAT,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="MathBlast",
        vendor_code="MBX",
        rostering_standard=RosteringStandard.ONEROSTER_REST_1P2,
        seat_model=SeatModel.PER_STUDENT,
        overage_policy="POOL_FALLBACK",
    )
    vendor_app = fx.activate_license(api, vendor_app["id"])
    run = fx.open_sync_run(api, vendor_app["id"], run_type=RunType.FULL)
    run = fx.transform_run(api, run["id"])
    fx.set_clock(api, PUBLISH_CLOCK)
    return {
        "school": school,
        "term": term,
        "students": students,
        "section": section,
        "enrollments": enrollments,
        "vendor_app": vendor_app,
        "run": run,
    }


def test_transform_projects_requested_dates_and_publish_bills_effective_dates(api):
    """The provisional projection and the final billing of one run disagree by design.

    The provisional variant "dates a student subject by the earliest
    `requested_effective_date`" — 1 September, on or before the 15 September
    add/drop cutoff, so each of the three seats is billed at the full 1000-cent
    list price for a projection of 3000. The final variant, evaluated at publish,
    "dates a student subject by the earliest `effective_date`" — stamped as the
    publish clock date of 1 October, after the cutoff, so each seat prorates to
    the ceiling of 603.0534, which is 604 cents, for a published figure of 1812.
    Each subject is priced exactly once and the seat delta counts the three
    genuinely new seats in both variants.

    Design: Difficulty/dual_variant_calc/seat_charge_provisional_vs_final_on_sync_run
    """
    world = _transformed_run_world(api)
    run = world["run"]

    assert run["projected_charge_cents"] == 3 * FULL_PRICE_PER_SEAT == 3000
    assert run["projected_seat_delta"] == 3

    response = api.publish_sync_run(run["id"], users.DATA_GOVERNANCE_OFFICER)
    published = validate_success(response, 200)

    assert published["state"] == SyncRunState.PUBLISHED
    assert published["published_charge_cents"] == 3 * PRORATED_PRICE_PER_SEAT == 1812
    assert published["published_seat_delta"] == 3
    assert published["projected_charge_cents"] == 3000, (
        "publishing must not rewrite the provisional projection"
    )
    assert_integer_cents(published["published_charge_cents"], "published_charge_cents")


def test_reconciliation_delta_is_observable_on_the_published_run(api):
    """The reconciliation figure is an observation on the run, not a posting.

    The contract defines the reconciliation figure as "the run's
    `published_charge_cents` minus its `projected_charge_cents`, and nothing
    else moves as a result of it": 1812 minus 3000 is negative 1188 cents.

    Design: Difficulty/dual_variant_calc/seat_charge_provisional_vs_final_on_sync_run
    """
    world = _transformed_run_world(api)

    published = validate_success(
        api.publish_sync_run(world["run"]["id"], users.DATA_GOVERNANCE_OFFICER), 200
    )

    delta = published["published_charge_cents"] - published["projected_charge_cents"]
    assert delta == -1188


def test_publish_stamps_effective_date_without_reclassifying_the_add_window(api):
    """A published mid-year add takes effect on the publish date but keeps its class.

    Publish takes a `PENDING_ADD` row whose requested date has arrived to
    `ACTIVE` "with `effective_date` stamped as the later of
    `requested_effective_date` and the clock date", leaving the requested date
    itself untouched. The add/drop classification was fixed at creation against
    the term's cutoff — 1 September is on or before 15 September, so the row
    stays `IN_WINDOW` even though it only took effect in October.

    Design: Difficulty/dual_variant_calc/seat_charge_provisional_vs_final_on_sync_run
    """
    world = _transformed_run_world(api)
    fx.publish_run(api, world["run"]["id"])

    enrollment = validate_success(
        api.get_enrollment(world["enrollments"][0]["id"], users.ROSTER_OPERATOR), 200
    )

    assert enrollment["roster_status"] == RosterStatus.ACTIVE
    assert_iso_date(enrollment["effective_date"], "effective_date")
    assert enrollment["effective_date"] == PUBLISH_DATE
    assert enrollment["requested_effective_date"] == REQUESTED_ADD_DATE
    assert enrollment["add_drop_class"] == "IN_WINDOW"


def test_no_sync_run_charge_figure_reaches_the_licence_ledger(api):
    """Neither the projection nor the final billing is posted onto the licence.

    `committed_charge_cents` "remains defined solely as the summed
    `seat_charge_cents` of the license's app accounts less their summed
    `refunded_charge_cents`, and no sync-run charge figure is ever written into
    it." This licence has no app accounts at all, so it stays at zero across a
    transform that projected 3000 cents and a publish that billed 1812.

    Design: Difficulty/dual_variant_calc/seat_charge_provisional_vs_final_on_sync_run
    """
    world = _transformed_run_world(api)
    fx.publish_run(api, world["run"]["id"])

    vendor_app = validate_success(
        api.get_vendor_app(world["vendor_app"]["id"], users.ROSTER_OPERATOR), 200
    )

    assert vendor_app["committed_charge_cents"] == 0
