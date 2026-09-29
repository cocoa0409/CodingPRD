"""The admission gauntlet shared by named booking, reassignment and the selector.

Gate order follows the numbered ladder of PRD 2.9 exactly: 14, 16, 18, 19, 20,
21, 22, 23, 29, 31, 32, 33, 34.  Stages 4-13 are endpoint-specific and run in the
route before this module is entered.
"""

from datetime import timedelta

import db
from errors import ApiError
from services import calc

ONSHORE = "ONSHORE_STANDARD"
OFFSHORE = "OFFSHORE_SHARED_SERVICE"


def rate_model_for(staff):
    return OFFSHORE if staff["service_center"] == "OFFSHORE" else ONSHORE


def gauntlet(phase, engagement, staff, review_owner, start_date, end_date, allocated_hours):
    """Run stages 14 through 34 for a booking that is about to be written.

    ``review_owner`` is the resolved StaffMember row of ``review_owner_staff_id``
    or None when the field was not supplied.
    """
    # --- 14: independence perimeter ---------------------------------------
    if calc.independence_conflict(engagement["client_id"], staff["id"], start_date, end_date):
        raise ApiError(
            "ERR_INDEPENDENCE_RESTRICTED",
            "An active independence restriction covers this staff member for this client.",
        )

    # --- 16: segregation of duties ----------------------------------------
    if review_owner is not None and review_owner["id"] == staff["id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The review owner may not be the staff member executing the work.",
        )

    # --- 18/19/20: skill profile ------------------------------------------
    if staff["level"] != phase["required_level"]:
        raise ApiError(
            "ERR_LEVEL_MISMATCH",
            "The phase requires level %s." % phase["required_level"],
        )
    required_spec = phase["required_industry_specialization"]
    if required_spec is not None and staff["industry_specialization"] != required_spec:
        raise ApiError(
            "ERR_SPECIALIZATION_MISMATCH",
            "The phase requires industry specialization %s." % required_spec,
        )
    if phase["requires_cpa_licensed"] and not staff["cpa_licensed"]:
        raise ApiError("ERR_LICENSURE_REQUIRED", "The phase requires an active CPA licence.")

    # --- 21/22/23: the review dimension -----------------------------------
    rate_model = rate_model_for(staff)
    offshore = rate_model == OFFSHORE
    if offshore and review_owner is None:
        raise ApiError(
            "ERR_REVIEW_OWNER_REQUIRED",
            "An offshore / shared-service booking must nominate a review owner.",
        )
    if not offshore and review_owner is not None:
        raise ApiError(
            "ERR_REVIEW_OWNER_REQUIRED",
            "An onshore booking must not nominate a review owner.",
        )

    charge = calc.ZERO
    window = None
    if offshore:
        if not calc.review_capable(review_owner):
            raise ApiError(
                "ERR_REVIEW_OWNER_NOT_ELIGIBLE",
                "The nominated review owner is not review-capable.",
            )
        charge = calc.review_hours_for(allocated_hours, 0)
        charge_week = calc.iso_week_start(end_date - timedelta(days=1))
        window = calc.find_review_window(review_owner["id"], charge_week)
        if window is None:
            raise ApiError(
                "ERR_REVIEW_WINDOW_MISSING",
                "No review capacity window exists for the reviewer in the charge week %s."
                % charge_week.isoformat(),
            )

    # --- 29: window containment -------------------------------------------
    if not (
        phase["window_start_date"] <= start_date
        and (end_date - timedelta(days=1)) <= phase["window_end_date"]
    ):
        raise ApiError(
            "ERR_ASSIGNMENT_OUTSIDE_PHASE_WINDOW",
            "The booking does not sit inside its phase window.",
        )

    # --- 31: fully-unavailable date ---------------------------------------
    blocked = calc.fully_unavailable_date(staff["id"], start_date, end_date)
    if blocked is not None:
        raise ApiError(
            "ERR_STAFF_UNAVAILABLE",
            "The staff member is fully unavailable on %s." % blocked.isoformat(),
        )

    day_count = calc.calendar_day_count(start_date, end_date)
    daily = calc.assignment_daily_hours(allocated_hours, day_count)

    # --- 32: per-date aggregate capacity ----------------------------------
    if not calc.daily_capacity_admissible(staff, start_date, end_date, daily):
        raise ApiError(
            "ERR_DAILY_CAPACITY_EXCEEDED",
            "The booking exceeds the staff member's capacity on at least one date.",
        )

    # --- 33: per-week effective cap ---------------------------------------
    if not calc.weekly_cap_admissible(staff, start_date, end_date, daily):
        raise ApiError(
            "ERR_WORKLOAD_CAP_EXCEEDED",
            "The booking exceeds the staff member's effective weekly cap.",
        )

    # --- 34: reviewer weekly review capacity ------------------------------
    if window is not None:
        committed = calc.committed_review_hours(window["id"])
        if committed + charge > calc.D(window["review_capacity_hours"]):
            raise ApiError(
                "ERR_REVIEW_CAPACITY_EXCEEDED",
                "The reviewer's weekly review capacity would be exceeded.",
            )

    return {
        "daily_hours": daily,
        "calendar_day_count": day_count,
        "rate_model": rate_model,
        "review_status": "PENDING_REVIEW" if offshore else "NOT_REQUIRED",
        "review_hours_charged": calc.r2(charge),
        "review_capacity_window_id": None if window is None else window["id"],
    }


def onshore_plan(start_date, end_date, allocated_hours):
    """The derived block for a selector booking, which is always domestic."""
    day_count = calc.calendar_day_count(start_date, end_date)
    return {
        "daily_hours": calc.assignment_daily_hours(allocated_hours, day_count),
        "calendar_day_count": day_count,
        "rate_model": ONSHORE,
        "review_status": "NOT_REQUIRED",
        "review_hours_charged": calc.ZERO,
        "review_capacity_window_id": None,
    }


def write_assignment(phase, staff, start_date, end_date, allocated_hours, review_owner, plan, fit_score):
    row = db.new_row()
    row.update(
        {
            "engagement_phase_id": phase["id"],
            "staff_member_id": staff["id"],
            "start_date": start_date,
            "end_date": end_date,
            "allocated_hours": calc.r2(allocated_hours),
            "review_owner_staff_id": None if review_owner is None else review_owner["id"],
            "review_capacity_window_id": plan["review_capacity_window_id"],
            "daily_hours": plan["daily_hours"],
            "calendar_day_count": plan["calendar_day_count"],
            "rate_model": plan["rate_model"],
            "review_hours_charged": plan["review_hours_charged"],
            "fit_score": calc.r2(fit_score),
            "staffing_status": "PROPOSED",
            "review_status": plan["review_status"],
            "rework_cycles": 0,
            "superseded_by_assignment_id": None,
        }
    )
    db.assignments[row["id"]] = row
    return row
