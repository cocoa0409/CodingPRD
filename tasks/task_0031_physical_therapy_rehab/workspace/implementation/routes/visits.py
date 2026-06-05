"""Visit routes (scaffold §1.5 — Visits; PRD §3.5)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_AUTHORIZATION_EXHAUSTED,
    ERR_CAPPED_POC_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_PLAN_VERSION,
    ERR_THERAPIST_DOUBLE_BOOKED,
    ERR_THERAPIST_LICENSE_INVALID,
    ERR_VA_VISIT_CAP_EXCEEDED,
    ERR_VISIT_OUT_OF_WINDOW,
)
from middleware import current_role, get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services import calculations as calc
from services.cascades import (
    refresh_grant_units_consumed,
    refresh_grant_units_finalized,
    refresh_poc_after_visit_finalize,
)
from services.validation import (
    clock_today_utc,
    lookup_or_404,
    require_datetime,
    require_enum,
    require_fields,
    require_int,
    require_string,
)


bp = Blueprint("visits", __name__)


CPT_CODES = {
    "CPT_97110_THER_EX",
    "CPT_97112_NEURO_REED",
    "CPT_97140_MANUAL",
    "CPT_97530_THER_ACT",
}


@bp.post("/rehab/visits")
def schedule_visit():
    require_auth(["Therapist", "CaseManager"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "authorization_grant_id",
            "therapist_id",
            "scheduled_start_utc",
            "scheduled_end_utc",
            "planned_minutes",
            "cpt_code",
        ],
    )
    grant_id = require_string(body["authorization_grant_id"], "authorization_grant_id")
    therapist_id = require_string(body["therapist_id"], "therapist_id")
    start_dt = require_datetime(body["scheduled_start_utc"], "scheduled_start_utc")
    end_dt = require_datetime(body["scheduled_end_utc"], "scheduled_end_utc")
    planned_minutes = require_int(
        body["planned_minutes"], "planned_minutes", min_value=8, max_value=240
    )
    cpt_code = require_enum(body["cpt_code"], CPT_CODES, "cpt_code")

    if end_dt <= start_dt:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "scheduled_end_utc must be strictly after scheduled_start_utc",
        )

    grant = lookup_or_404(db.authorization_grants, grant_id, "AuthorizationGrant")
    therapist = lookup_or_404(db.therapists, therapist_id, "Therapist")
    poc = db.plans_of_care[grant["plan_of_care_id"]]
    patient = db.patients[poc["patient_id"]]

    # PRD §3.10 demo licensing policy (priority 420)
    if patient["insurance_type"] != "VA_TRICARE" and therapist["license_state"] != "CA":
        raise APIError(
            ERR_THERAPIST_LICENSE_INVALID,
            422,
            f"Therapist.license_state={therapist['license_state']} not valid "
            f"for patient.insurance_type={patient['insurance_type']}",
        )

    # priority 425 — VeteranReferral cap: count of Visit rows already linked
    # (via grant) to the same referral + this new one must be <=
    # referral.max_authorized_visits.
    referral_id = poc.get("veteran_referral_id")
    if referral_id:
        referral = db.veteran_referrals.get(referral_id)
        if referral is not None:
            # Count existing Visit rows whose grant chains back to this referral.
            grant_ids_for_referral = {
                g["id"]
                for g in db.authorization_grants.values()
                if db.plans_of_care.get(g["plan_of_care_id"], {}).get("veteran_referral_id")
                == referral_id
            }
            existing_count = sum(
                1
                for v in db.visits.values()
                if v["authorization_grant_id"] in grant_ids_for_referral
            )
            if existing_count + 1 > referral["max_authorized_visits"]:
                raise APIError(
                    ERR_VA_VISIT_CAP_EXCEEDED,
                    409,
                    "VeteranReferral max_authorized_visits would be exceeded",
                )

    # priority 430 — windows: visit interval fully within grant.[from,to] AND poc.[start,end]
    grant_from = db.parse_iso_date(grant["effective_from"])
    grant_to = db.parse_iso_date(grant["effective_to"])
    poc_start = db.parse_iso_date(poc["certified_start_date"])
    poc_end = db.parse_iso_date(poc["certified_end_date"])
    sd_date = start_dt.date()
    ed_date = end_dt.date()
    if grant_from is None or grant_to is None or poc_start is None or poc_end is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "grant/POC dates malformed")
    if not (grant_from <= sd_date <= grant_to and grant_from <= ed_date <= grant_to):
        raise APIError(
            ERR_VISIT_OUT_OF_WINDOW,
            422,
            "scheduled times must fall within AuthorizationGrant window",
        )
    if not (poc_start <= sd_date <= poc_end and poc_start <= ed_date <= poc_end):
        raise APIError(
            ERR_VISIT_OUT_OF_WINDOW,
            422,
            "scheduled times must fall within PlanOfCare certification window",
        )

    # priority 435 — half-open overlap with other SCHEDULED/COMPLETED visits on same therapist
    for v in db.visits.values():
        if v["therapist_id"] != therapist_id:
            continue
        if v["status"] not in {"SCHEDULED", "COMPLETED"}:
            continue
        other_start = db.parse_iso_dt(v["scheduled_start_utc"])
        other_end = db.parse_iso_dt(v["scheduled_end_utc"])
        if other_start is None or other_end is None:
            continue
        # [a,b) overlaps [c,d) iff a < d AND c < b
        if start_dt < other_end and other_start < end_dt:
            raise APIError(
                ERR_THERAPIST_DOUBLE_BOOKED,
                409,
                "Therapist already booked in this interval",
            )

    # priority 440 — fiscal: pre-allocated planned_units mustn't push consumed past total
    planned_units = calc.eight_minute_units(planned_minutes)
    projected_consumed = calc.grant_units_consumed(grant_id) + planned_units
    if projected_consumed > grant["total_units_granted"]:
        raise APIError(
            ERR_AUTHORIZATION_EXHAUSTED,
            409,
            "Scheduling this Visit would exceed AuthorizationGrant.total_units_granted",
        )

    with db.mutation_lock:
        visit = {
            "authorization_grant_id": grant_id,
            "therapist_id": therapist_id,
            "scheduled_start_utc": db.iso_format(start_dt),
            "scheduled_end_utc": db.iso_format(end_dt),
            "planned_minutes": planned_minutes,
            "actual_minutes": None,
            "planned_units": planned_units,
            "billable_units": 0,
            "billed_cents": 0,
            "cpt_code": cpt_code,
            "status": "SCHEDULED",
        }
        db.stamp_common(visit)
        db.visits[visit["id"]] = visit
        refresh_grant_units_consumed(grant)
        return ok_object(visit, 201)


@bp.get("/rehab/visits/<vid>")
def get_visit(vid: str):
    require_auth(["PlatformAdmin", "Therapist", "BillingClerk", "CaseManager"])()
    v = lookup_or_404(db.visits, vid, "Visit")
    return ok_object(v, 200)


@bp.get("/rehab/visits")
def list_visits():
    require_auth(["PlatformAdmin", "Therapist", "BillingClerk", "CaseManager"])()
    limit, offset = paginate_params(request.args)
    items = list(db.visits.values())
    for key in ("authorization_grant_id", "therapist_id", "status"):
        if key in request.args:
            items = [v for v in items if v.get(key) == request.args.get(key)]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/rehab/visits/<vid>/complete")
def complete_visit(vid: str):
    require_auth(["Therapist"])()
    visit = lookup_or_404(db.visits, vid, "Visit")
    body = get_json_body()
    require_fields(body, ["actual_minutes"])
    actual_minutes = require_int(
        body["actual_minutes"], "actual_minutes", min_value=8, max_value=240
    )

    # State precondition (priority 300)
    if visit["status"] != "SCHEDULED":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"Visit must be SCHEDULED to complete; current={visit['status']}",
        )

    # Cross-entity guards: parent POC ACTIVE/RECERT_DUE, grant ACTIVE
    grant = db.authorization_grants[visit["authorization_grant_id"]]
    poc = db.plans_of_care[grant["plan_of_care_id"]]
    if poc["status"] not in {"ACTIVE", "RECERT_DUE"}:
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"PlanOfCare status must be ACTIVE or RECERT_DUE to complete a Visit; current={poc['status']}",
        )
    if grant["status"] != "ACTIVE":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"AuthorizationGrant status must be ACTIVE to complete a Visit; current={grant['status']}",
        )

    # today (UTC) >= scheduled_start_utc date
    sched_dt = db.parse_iso_dt(visit["scheduled_start_utc"])
    if sched_dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Visit.scheduled_start_utc malformed")
    today = clock_today_utc()
    if today < sched_dt.date():
        raise APIError(
            ERR_INVALID_STATE,
            409,
            "Today (UTC) must be on or after scheduled_start_utc date",
        )

    # Compute prospective new billable_units and check fiscal cap (priority 440)
    new_billable = calc.eight_minute_units(actual_minutes)
    # The grant's units_consumed after this transition would be
    # (current_consumed - this visit's planned_units + new_billable).
    current_consumed = calc.grant_units_consumed(grant["id"])
    projected = current_consumed - (visit.get("planned_units") or 0) + new_billable
    if projected > grant["total_units_granted"]:
        raise APIError(
            ERR_AUTHORIZATION_EXHAUSTED,
            409,
            "Completing this Visit would exceed AuthorizationGrant.total_units_granted",
        )

    with db.mutation_lock:
        visit["actual_minutes"] = actual_minutes
        visit["billable_units"] = new_billable
        visit["status"] = "COMPLETED"
        db.bump(visit)
        refresh_grant_units_consumed(grant)
        return ok_object(visit, 200)


@bp.post("/rehab/visits/<vid>/finalize")
def finalize_visit(vid: str):
    require_auth(["BillingClerk"])()
    visit = lookup_or_404(db.visits, vid, "Visit")
    body = get_json_body()
    require_fields(body, ["expected_plan_of_care_version"])
    expected_version = require_int(
        body["expected_plan_of_care_version"],
        "expected_plan_of_care_version",
        min_value=0,
    )

    if visit["status"] != "COMPLETED":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"Visit must be COMPLETED to finalize; current={visit['status']}",
        )

    grant = db.authorization_grants[visit["authorization_grant_id"]]
    poc = db.plans_of_care[grant["plan_of_care_id"]]

    # OCC (priority 305)
    if expected_version != poc["version"]:
        raise APIError(
            ERR_STALE_PLAN_VERSION,
            412,
            "expected_plan_of_care_version does not match current PlanOfCare.version",
        )

    # priority 410: cap gate
    if poc["capped_status"] == "EXCEEDED":
        raise APIError(
            ERR_CAPPED_POC_EXCEEDED,
            409,
            "PlanOfCare.capped_status is EXCEEDED — finalize is blocked",
        )

    with db.mutation_lock:
        visit["billed_cents"] = calc.visit_billed_cents(
            visit["cpt_code"], visit["billable_units"]
        )
        visit["status"] = "FINALIZED"
        db.bump(visit)
        # grant.units_finalized refresh
        refresh_grant_units_finalized(grant)
        # POC.cumulative_billed + capped_status + version bump
        refresh_poc_after_visit_finalize(poc)
        return ok_object(visit, 200)


@bp.post("/rehab/visits/<vid>/cancel")
def cancel_visit(vid: str):
    require_auth(["Therapist", "PlatformAdmin"])()
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "SCHEDULED":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"Visit must be SCHEDULED to cancel; current={visit['status']}",
        )
    # priority 300 (state-precondition): today <= scheduled_start_utc.date - 1 day,
    # UNLESS caller is PlatformAdmin who may cancel at any time.
    if current_role() != "PlatformAdmin":
        sched_dt = db.parse_iso_dt(visit["scheduled_start_utc"])
        today = clock_today_utc()
        if sched_dt is not None:
            if today > sched_dt.date() - timedelta(days=1):
                raise APIError(
                    ERR_INVALID_STATE,
                    409,
                    "Today (UTC) must be on or before scheduled_start_utc date - 1 day to cancel",
                )

    with db.mutation_lock:
        visit["status"] = "CANCELLED"
        db.bump(visit)
        grant = db.authorization_grants[visit["authorization_grant_id"]]
        refresh_grant_units_consumed(grant)
        return ok_object(visit, 200)


@bp.post("/rehab/visits/<vid>/no-show")
def no_show_visit(vid: str):
    require_auth(["Therapist"])()
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "SCHEDULED":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"Visit must be SCHEDULED to mark NO_SHOW; current={visit['status']}",
        )
    sched_dt = db.parse_iso_dt(visit["scheduled_start_utc"])
    today = clock_today_utc()
    if sched_dt is not None and today <= sched_dt.date():
        raise APIError(
            ERR_INVALID_STATE,
            409,
            "Today (UTC) must be strictly after scheduled_start_utc date for NO_SHOW",
        )

    with db.mutation_lock:
        visit["status"] = "NO_SHOW"
        db.bump(visit)
        grant = db.authorization_grants[visit["authorization_grant_id"]]
        refresh_grant_units_consumed(grant)
        return ok_object(visit, 200)
