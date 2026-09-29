"""Service visits: booking, arrival, calibration evidence, adjudication."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from middleware import (
    ROLE_ACCOUNT_MANAGER, ROLE_QUALITY_AUDITOR, ROLE_SERVICE_TECHNICIAN,
)
from routes import common
from services import calc, derive

bp = Blueprint("visits", __name__)

BUFFER = timedelta(minutes=30)


def _site_of_ticket(ticket):
    placement = db.get("machine_placements", ticket["placement_id"])
    if placement is None:
        return None, None
    return placement, db.get("sites", placement["site_id"])


@bp.route("/service-visits", methods=["POST"])
def create_visit():
    user_id, role = middleware.require_roles(ROLE_SERVICE_TECHNICIAN)
    raw = middleware.raw_body()
    claimed = raw.get("technician_id")
    if isinstance(claimed, str) and claimed != user_id:
        middleware.deny_owner("A technician may only act as itself")

    body = middleware.body_object()
    ticket_id = middleware.f_str(body, "ticket_id", required=True)
    technician_id = middleware.f_str(body, "technician_id", required=True)
    start_at = middleware.f_dt(body, "scheduled_start_at", required=True)
    end_at = middleware.f_dt(body, "scheduled_end_at", required=True)
    follow_up_id = middleware.f_str(body, "follow_up_to_visit_id")
    if not start_at < end_at:
        middleware.bad(
            "scheduled_start_at must be earlier than scheduled_end_at"
        )
    if technician_id != user_id:
        middleware.deny_owner("A technician may only act as itself")

    ticket = middleware.must_reference(
        "service_tickets", ticket_id, "ticket_id"
    )
    technician = middleware.must_reference(
        "technicians", technician_id, "technician_id"
    )
    if follow_up_id is not None:
        earlier = middleware.must_reference(
            "service_visits", follow_up_id, "follow_up_to_visit_id"
        )
        if (earlier["ticket_id"] != ticket_id
                or earlier["visit_status"] != "REJECTED"):
            raise ApiError(
                "ERR_UNKNOWN_REFERENCE",
                "follow_up_to_visit_id must name a REJECTED visit of this "
                "ticket",
            )

    if (ticket["status"] != "DISPATCHED"
            or ticket["assigned_technician_id"] != technician_id):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The ticket is not DISPATCHED to this technician",
        )

    placement, site = _site_of_ticket(ticket)
    if site is None or technician["region_code"] != site["region_code"]:
        raise ApiError(
            "ERR_TECHNICIAN_REGION_MISMATCH",
            "The technician's region does not match the site's",
        )

    for other in db.rows("service_visits"):
        if other["technician_id"] != technician_id:
            continue
        if other["visit_status"] not in derive.LIVE_VISIT_STATUSES:
            continue
        if (start_at < other["scheduled_end_at"] + BUFFER
                and other["scheduled_start_at"] < end_at + BUFFER):
            raise ApiError(
                "ERR_TECHNICIAN_SCHEDULE_CONFLICT",
                "The window collides with another booking of this technician",
            )

    row = db.insert("service_visits", {
        "ticket_id": ticket_id,
        "technician_id": technician_id,
        "scheduled_start_at": start_at,
        "scheduled_end_at": end_at,
        "follow_up_to_visit_id": follow_up_id,
        "visit_status": "SCHEDULED",
        "arrival_at": None,
        "calibration_record_count": 0,
        "repair_confirmed": False,
        "rejection_reason": None,
        "verified_by_user_id": None,
    })
    return response.created(response.serialize(row))


@bp.route("/service-visits/<visit_id>", methods=["GET"])
def read_visit(visit_id):
    middleware.require_roles(
        ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER
    )
    row = middleware.must_exist("service_visits", visit_id, "ServiceVisit")
    return response.ok(response.serialize(row))


@bp.route("/service-visits", methods=["GET"])
def list_visits():
    middleware.require_roles(
        ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER
    )
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("service_visits"), (
        ("ticket_id", "ticket_id"),
        ("technician_id", "technician_id"),
        ("follow_up_to_visit_id", "follow_up_to_visit_id"),
        ("visit_status", "visit_status"),
        ("status", "visit_status"),
    ))
    return common.listing(rows, limit, offset)


@bp.route("/service-visits/<visit_id>/arrive", methods=["POST"])
def arrive(visit_id):
    user_id, _role = middleware.require_roles(ROLE_SERVICE_TECHNICIAN)
    visit = middleware.must_exist("service_visits", visit_id, "ServiceVisit")
    if visit["technician_id"] != user_id:
        middleware.deny_owner("The visit belongs to another technician")
    middleware.body_object()

    if visit["visit_status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The visit is %s, not SCHEDULED" % visit["visit_status"],
        )
    ticket = db.get("service_tickets", visit["ticket_id"])
    if (ticket is None or ticket["status"] != "DISPATCHED"
            or ticket["assigned_technician_id"] != visit["technician_id"]):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The ticket is not DISPATCHED to this technician",
        )

    visit["visit_status"] = "IN_PROGRESS"
    visit["arrival_at"] = db.now()
    db.mark(visit)
    ticket["status"] = "ON_SITE"
    db.mark(ticket)
    placement, site = _site_of_ticket(ticket)
    derive.recompute_site(site)
    derive.recompute_technician(db.get("technicians", visit["technician_id"]))
    return response.ok(response.serialize(visit))


def _records_by_dispenser(visit_id):
    grouped = {}
    for record in derive.records_of_visit(visit_id):
        grouped.setdefault(record["dispenser_id"], []).append(record)
    return grouped


@bp.route("/service-visits/<visit_id>/submit", methods=["POST"])
def submit(visit_id):
    user_id, _role = middleware.require_roles(ROLE_SERVICE_TECHNICIAN)
    visit = middleware.must_exist("service_visits", visit_id, "ServiceVisit")
    if visit["technician_id"] != user_id:
        middleware.deny_owner("The visit belongs to another technician")
    body = middleware.body_object()
    repair_confirmed = middleware.f_bool(body, "repair_confirmed", default=False)

    # PRD 2.8 rung 9 makes ERR_INVALID_STATE_TRANSITION the generic state-legality
    # failure. ERR_VISIT_NOT_IN_PROGRESS is introduced in PRD 3.6 for one situation
    # only -- the nested calibration-record write ("While a visit is IN_PROGRESS --
    # and only then, with any other visit_status refused as
    # ERR_VISIT_NOT_IN_PROGRESS"). Submission merely "requires visit_status
    # IN_PROGRESS" with no specific code named, so it reports the generic one.
    if visit["visit_status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The visit is %s, not IN_PROGRESS" % visit["visit_status"],
        )
    if visit["calibration_record_count"] < 1:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A visit with no calibration record cannot be submitted",
        )
    for records in _records_by_dispenser(visit_id).values():
        if records[-1]["efficacy_result"] == "FAIL":
            raise ApiError(
                "ERR_EFFICACY_FAILURE_UNRESOLVED",
                "A dispenser's latest record in this visit still fails",
            )

    visit["visit_status"] = "SUBMITTED"
    visit["repair_confirmed"] = bool(repair_confirmed)
    db.mark(visit)
    ticket = db.get("service_tickets", visit["ticket_id"])
    if ticket is not None and ticket["status"] == "ON_SITE":
        ticket["status"] = "PENDING_VERIFICATION"
        db.mark(ticket)
        placement, site = _site_of_ticket(ticket)
        derive.recompute_site(site)
        derive.recompute_technician(
            db.get("technicians", visit["technician_id"])
        )
    return response.ok(response.serialize(visit))


# --------------------------------------------------------------------------
# adjudication (PRD 3.6)
# --------------------------------------------------------------------------

def _apply_verified(visit, grouped):
    now = db.now()
    touched_placements = []
    for dispenser_id, records in grouped.items():
        dispenser = db.get("dispensers", dispenser_id)
        if dispenser is None:
            continue
        applied = [
            r for r in records
            if r["calibration_verdict"] in ("PASS", "ADJUSTED")
        ]
        latest = records[-1]
        if applied:
            last = applied[-1]
            prior = dispenser["calibrated_dose_ml_per_rack"]
            if last["calibration_verdict"] == "ADJUSTED":
                new_dose = last["adjusted_dose_ml_per_rack"]
            else:
                new_dose = prior
            for record in applied:
                record["applied"] = True
                record["_applied_at"] = now
                record["_applied_dose"] = new_dose
            dispenser["prior_dose_ml_per_rack"] = prior
            dispenser["calibrated_dose_ml_per_rack"] = new_dose
            dispenser["dose_effective_at"] = now
            dispenser["last_calibrated_at"] = now
            dispenser["last_drift_pct"] = last["drift_pct"]
            db.mark(dispenser)
            placement = db.get("machine_placements", dispenser["placement_id"])
            if placement is not None:
                placement["_calibration_baseline"] = placement["last_cycle_count"]
                derive.recompute_cycles(placement)
                if placement not in touched_placements:
                    touched_placements.append(placement)
        if (dispenser["dispenser_status"] == "LOCKED_OUT"
                and dispenser["lockout_reason"] == "EFFICACY_FAILURE"
                and latest["efficacy_result"] == "PASS"):
            dispenser["dispenser_status"] = "ACTIVE"
            dispenser["lockout_reason"] = None
            db.mark(dispenser)
    return touched_placements


@bp.route("/service-visits/<visit_id>/verify", methods=["POST"])
def verify(visit_id):
    user_id, _role = middleware.require_roles(ROLE_QUALITY_AUDITOR)
    body = middleware.body_object()
    decision = middleware.f_enum(
        body, "decision", ("VERIFIED", "REJECTED"), required=True
    )
    reason = middleware.f_str(body, "rejection_reason", max_len=500)
    if decision == "REJECTED" and (reason is None or not reason.strip()):
        middleware.bad("rejection_reason is required when rejecting a visit")

    visit = middleware.must_exist("service_visits", visit_id, "ServiceVisit")
    if visit["visit_status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The visit is %s, not SUBMITTED" % visit["visit_status"],
        )
    ticket = db.get("service_tickets", visit["ticket_id"])
    if ticket is None or ticket["status"] != "PENDING_VERIFICATION":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The ticket is not PENDING_VERIFICATION",
        )

    placement, site = _site_of_ticket(ticket)
    technician = db.get("technicians", visit["technician_id"])
    grouped = _records_by_dispenser(visit_id)

    if decision == "VERIFIED":
        visit["visit_status"] = "VERIFIED"
        visit["verified_by_user_id"] = user_id
        visit["_verified_at"] = db.now()
        db.mark(visit)
        _apply_verified(visit, grouped)
        if visit["repair_confirmed"] and placement is not None:
            derive.resolve_open_alerts(placement)
            derive.rederive_health(placement)
        ticket["status"] = "CLOSED"
        db.mark(ticket)
    else:
        visit["visit_status"] = "REJECTED"
        visit["verified_by_user_id"] = user_id
        visit["rejection_reason"] = reason
        db.mark(visit)
        # A rejected visit applies nothing: every record stays applied=false,
        # every dispenser keeps its pre-visit dose, and alerts are untouched.
        ticket["status"] = "QUEUED"
        ticket["assigned_technician_id"] = None
        db.mark(ticket)

    derive.recompute_technician(technician)
    derive.recompute_site(site)
    return response.ok(response.serialize(visit))


# --------------------------------------------------------------------------
# concentration evidence (nested immutable write, PRD 3.6)
# --------------------------------------------------------------------------

HARD_LOCKOUTS = ("AGREEMENT_ENDED", "INVESTIGATION_HOLD")


@bp.route("/service-visits/<visit_id>/calibration-records", methods=["POST"])
def create_record(visit_id):
    user_id, _role = middleware.require_roles(ROLE_SERVICE_TECHNICIAN)
    visit = middleware.must_exist("service_visits", visit_id, "ServiceVisit")
    if visit["technician_id"] != user_id:
        middleware.deny_owner("The visit belongs to another technician")

    body = middleware.body_object()
    dispenser_id = middleware.f_str(body, "dispenser_id", required=True)
    measured_ppm = middleware.f_int(
        body, "measured_ppm", required=True, minimum=1
    )
    measured_dose = middleware.f_num(
        body, "measured_dose_ml_per_rack", required=True, gt=0
    )
    expected_version = middleware.f_int(
        body, "expected_dispenser_version", required=True, minimum=0
    )
    adjusted_dose = middleware.f_num(body, "adjusted_dose_ml_per_rack", gt=0)
    contact_seconds = middleware.f_int(body, "contact_seconds", minimum=0)
    contact_given = middleware.present(body, "contact_seconds")

    dispenser = middleware.must_reference(
        "dispensers", dispenser_id, "dispenser_id"
    )
    middleware.check_parent_version(dispenser, expected_version, "Dispenser")

    if visit["visit_status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_VISIT_NOT_IN_PROGRESS",
            "The visit is %s, not IN_PROGRESS" % visit["visit_status"],
        )
    if (dispenser["dispenser_status"] == "LOCKED_OUT"
            and dispenser["lockout_reason"] in HARD_LOCKOUTS):
        raise ApiError(
            "ERR_SANITIZER_LOCKOUT_ACTIVE",
            "The dispenser is locked out for %s and accepts no calibration"
            % dispenser["lockout_reason"],
        )

    ticket = db.get("service_tickets", visit["ticket_id"])
    ticket_placement_id = ticket["placement_id"] if ticket else None
    if dispenser["placement_id"] != ticket_placement_id:
        raise ApiError(
            "ERR_DISPENSER_PLACEMENT_MISMATCH",
            "The dispenser is not fitted to this visit's placement",
        )

    product = db.get("chemical_products", dispenser["product_id"])
    is_sanitizer = product is not None and product["product_type"] == "SANITIZER"
    if is_sanitizer and not contact_given:
        middleware.bad("contact_seconds is required for a sanitizer dispenser")
    if not is_sanitizer and contact_given:
        middleware.bad(
            "contact_seconds must be omitted for a non-sanitizer dispenser"
        )

    placement = db.get("machine_placements", dispenser["placement_id"])
    model = derive.model_of_placement(placement) if placement else None
    efficacy = calc.efficacy_verdict(
        product, model, dispenser["placement_id"], measured_ppm,
        contact_seconds,
    )
    drift = calc.drift_pct(measured_ppm, product["concentration_target_ppm"])
    verdict = calc.calibration_verdict(
        drift, product["concentration_tolerance_pct"], efficacy
    )
    if verdict == "ADJUSTED" and adjusted_dose is None:
        raise ApiError(
            "ERR_ADJUSTED_DOSE_REQUIRED",
            "An ADJUSTED verdict requires adjusted_dose_ml_per_rack",
        )

    record = db.insert("calibration_records", {
        "visit_id": visit_id,
        "dispenser_id": dispenser_id,
        "measured_ppm": measured_ppm,
        "measured_dose_ml_per_rack": measured_dose,
        "adjusted_dose_ml_per_rack": adjusted_dose,
        "contact_seconds": contact_seconds,
        "drift_pct": drift,
        "calibration_verdict": verdict,
        "efficacy_result": efficacy,
        "applied": False,
        "recorded_by_user_id": user_id,
        "_applied_at": None,
        "_applied_dose": None,
    }, common=False)

    visit["calibration_record_count"] = visit["calibration_record_count"] + 1
    db.mark(visit)
    db.mark(dispenser)

    if efficacy == "FAIL":
        if dispenser["dispenser_status"] == "ACTIVE":
            derive.lock_out(dispenser, "EFFICACY_FAILURE")
        if placement is not None:
            derive.drive_down(placement)
    return response.created(response.serialize(record))
