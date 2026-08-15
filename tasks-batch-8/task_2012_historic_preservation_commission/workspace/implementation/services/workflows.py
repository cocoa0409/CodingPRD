"""Cross-aggregate cascades (PRD 2.10): each commits atomically inside the
triggering request; every cascaded resource gets its own updated_at/version bump."""
from db import db
from errors import raise_error, ERR_DEMOLITION_DELAY_OVERLAP
from services.core import (
    new_record, touch, recompute_district_census, recompute_property_enforcement,
    refresh_meeting_count, hearing_for_application,
)
from services.calculations import (
    BASE_DELAY_DAYS, DEFAULT_BASE_DELAY_DAYS, provisional_delay_end,
    effective_delay_end, delay_windows_overlap, lazy_expire_delay, final_penalty,
    withdrawal_refund,
)
from util import CLOCK, parse_dt, fmt_dt, add_days


def check_demolition_delay_overlap(prop, decided_dt):
    """The overlap gate runs BEFORE a demolition approval commits: the new
    half-open window [decided_at, decided_at + base) must not overlap any other
    ACTIVE delay on the same property. Adjacency is permitted."""
    district = db["districts"].get(prop.get("district_id")) if prop.get("district_id") else None
    base_days = BASE_DELAY_DAYS.get(district["significance_tier"]) if district else DEFAULT_BASE_DELAY_DAYS
    new_start = decided_dt
    new_end = add_days(decided_dt, base_days)
    for other in db["demolition_delays"].values():
        if other.get("property_id") != prop["id"]:
            continue
        lazy_expire_delay(other)  # consulting a delay evaluates its lazy expiry
        if other.get("status") != "ACTIVE":
            continue
        other_start = parse_dt(other["delay_start_at"])
        other_end = effective_delay_end(other)
        if delay_windows_overlap(new_start, new_end, other_start, other_end):
            raise_error(ERR_DEMOLITION_DELAY_OVERLAP,
                        "new demolition delay window overlaps an ACTIVE delay on the property")
    return base_days


def demolition_approval_side_effects(app, decided_dt, base_days):
    """On any approval of a DEMOLITION application (staff or commission track):
    property INVENTORY -> DEMOLITION_PENDING; DemolitionDelay created ACTIVE."""
    prop = db["properties"].get(app["property_id"])
    if prop is not None and prop.get("listing_status") != "DEMOLITION_PENDING":
        prop["listing_status"] = "DEMOLITION_PENDING"
        touch(prop)
    new_record("demolition_delays", {
        "application_id": app["id"],
        "property_id": app["property_id"],
        "base_delay_days": base_days,
        "postponement_count": 0,
        "delay_start_at": fmt_dt(decided_dt),
        "provisional_delay_end": fmt_dt(add_days(decided_dt, base_days)),
        "final_delay_end": None,
        "status": "ACTIVE",
    })


def after_the_fact_resolution(app, stop_dt):
    """On any approval of an after_the_fact application (incl. APPROVED_ON_APPEAL):
    linked violation -> COMPLIANCE_VERIFIED with accrual stopped at stop_dt."""
    violation = db["violations"].get(app.get("violation_id"))
    if violation is None:
        return
    if violation.get("status") not in ("NOTICE_ISSUED", "AFTER_THE_FACT_PENDING"):
        return
    violation["status"] = "COMPLIANCE_VERIFIED"
    violation["compliance_verified_at"] = fmt_dt(stop_dt)
    prop = db["properties"].get(violation["property_id"])
    if prop is not None:
        penalty, capped = final_penalty(violation, prop, stop_dt)
        violation["final_penalty_cents"] = penalty
        violation["penalty_capped"] = capped
    touch(violation)
    if prop is not None:
        recompute_property_enforcement(prop["id"])


def withdrawal_cascade(app):
    """Stage-based refund, then release of the public process: the non-terminal
    hearing (if any) -> WITHDRAWN, freeing the agenda slot when it occupied one."""
    app["refunded_fee_cents"] = withdrawal_refund(app["status"], app["paid_fee_cents"])
    app["fee_balance_cents"] = 0
    hearing = hearing_for_application(app["id"], statuses={"SCHEDULED", "OPENED", "CONTINUED"})
    if hearing is not None:
        meeting_id = hearing["meeting_id"]
        hearing["status"] = "WITHDRAWN"
        touch(hearing)
        refresh_meeting_count(meeting_id)


def demolition_completion_cascade(cert):
    """On completing a demolition certificate: property DEMOLITION_PENDING ->
    DEMOLISHED; district census + posture recomputed."""
    app = db["applications"].get(cert["application_id"])
    if app is None or app.get("application_type") != "DEMOLITION":
        return
    prop = db["properties"].get(app["property_id"])
    if prop is None:
        return
    if prop.get("listing_status") == "DEMOLITION_PENDING":
        prop["listing_status"] = "DEMOLISHED"
        touch(prop)
    recompute_district_census(prop.get("district_id"))
