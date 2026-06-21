"""Signup endpoints — the seat-claim eligibility chain and the signup lifecycle
(PRD §3.4, §3.5, §3.6)."""
from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role
from response import object_response, array_response
from services.common import (base_record, touch, get_or_404, find_fk_or_404,
                             get_json, require_field, require_int, require_number,
                             list_collection)
from services.serialize import serialize, serialize_list
from services import calc
from services.domain import (SEAT_HOLDING, apply_bg_expiry, occupy_seat,
                            release_seat, sync_shift_full_state, no_show_cascade,
                            verify_hours_cascade)
from timeutil import now_iso, parse_dt

bp = Blueprint("signups", __name__)
COLL = "signups"


def _owner_check(signup):
    """A volunteer acting on a signup must own it (PRD §2.1). Operator roles do
    not reach these endpoints (RBAC restricts to Volunteer)."""
    if g.role == "Volunteer" and signup["volunteer_id"] != g.user_id:
        raise ApiError("ERR_NOT_SIGNUP_OWNER", "acting volunteer does not own this signup")


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


# ---- create (the eligibility chain) ---------------------------------------
@bp.post("/vm/shifts/<shift_id>/signups")
@require_role("Volunteer")
def create_signup(shift_id):
    body = get_json()
    volunteer_id = require_field(body, "volunteer_id", str)
    expected_shift_version = require_int(body, "expected_shift_version")
    with store.lock:
        # path existence
        shift = get_or_404("shifts", shift_id)
        # body FK existence
        volunteer = find_fk_or_404("volunteers", volunteer_id)
        opp = store.opportunities.get(shift["opportunity_id"])

        # OCC: expected_shift_version must match (PRD §2.6). This is a write-path
        # concurrency guard; it precedes seat handout.
        if shift["version"] != expected_shift_version:
            raise ApiError("ERR_STALE_SHIFT_VERSION",
                           "expected_shift_version does not match")

        # Lazy bg-tier expiry against the current clock before tier comparison.
        apply_bg_expiry(volunteer)

        # --- ordered eligibility chain (PRD §3.4) ---
        # 2. Volunteer eligibility
        if volunteer["status"] != "ACTIVE":
            raise ApiError("ERR_VOLUNTEER_NOT_ELIGIBLE",
                           "volunteer is not ACTIVE")

        # 3. Time conflict — half-open interval overlap with another seat-holding
        #    signup of this volunteer.
        s_start = parse_dt(shift["starts_at"])
        s_end = parse_dt(shift["ends_at"])
        for other in store.signups.values():
            if other["volunteer_id"] != volunteer_id:
                continue
            if other["status"] not in SEAT_HOLDING:
                continue
            other_shift = store.shifts.get(other["shift_id"])
            if other_shift is None or other_shift["id"] == shift_id:
                continue
            o_start = parse_dt(other_shift["starts_at"])
            o_end = parse_dt(other_shift["ends_at"])
            if _intervals_overlap(s_start, s_end, o_start, o_end):
                raise ApiError("ERR_SHIFT_TIME_CONFLICT",
                               "volunteer has an overlapping seat-occupying signup")

        # 4. Background-check tier gate
        required_tier = opp["required_bg_tier"] if opp else "NONE"
        if calc.BG_TIER_RANK[volunteer["bg_check_tier"]] < calc.BG_TIER_RANK[required_tier]:
            raise ApiError("ERR_BG_TIER_INSUFFICIENT",
                           "volunteer bg_check_tier insufficient")

        # 5. Skill gate
        if opp:
            for sid in opp["required_skill_ids"]:
                has = any(vs["volunteer_id"] == volunteer_id
                          and vs["skill_id"] == sid
                          and vs["proficiency"] == "VERIFIED"
                          for vs in store.volunteer_skills.values())
                if not has:
                    raise ApiError("ERR_SKILL_REQUIREMENT_NOT_MET",
                                   "missing a required VERIFIED skill")

        # 6. Waiver prerequisite
        if opp and opp["required_waiver_template_id"]:
            template = store.waiver_templates.get(opp["required_waiver_template_id"])
            req_rev = template["revision"] if template else None
            accepted = any(wa["volunteer_id"] == volunteer_id
                           and wa["waiver_template_id"] == opp["required_waiver_template_id"]
                           and wa["accepted_revision"] == req_rev
                           for wa in store.waiver_acceptances.values())
            if not accepted:
                raise ApiError("ERR_WAIVER_NOT_ACCEPTED",
                               "required waiver not accepted at current revision")

        # 7. Training prerequisite
        if opp and opp["required_training_module_id"]:
            now = store.now()
            ok = False
            for tc in store.training_completions.values():
                if (tc["volunteer_id"] == volunteer_id
                        and tc["training_module_id"] == opp["required_training_module_id"]):
                    if parse_dt(tc["expires_at"]) >= now:
                        ok = True
                        break
            if not ok:
                raise ApiError("ERR_TRAINING_NOT_COMPLETED",
                               "required training not completed / lapsed")

        # 8. Duplicate signup
        for other in store.signups.values():
            if (other["volunteer_id"] == volunteer_id
                    and other["shift_id"] == shift_id
                    and other["status"] in SEAT_HOLDING):
                raise ApiError("ERR_DUPLICATE_SIGNUP",
                               "volunteer already holds a seat on this shift")

        # 9. Capacity
        if shift["reserved_count"] >= shift["capacity"]:
            raise ApiError("ERR_SHIFT_FULL", "shift is full")

        # --- create ---
        rec = base_record(COLL)
        rec.update({
            "shift_id": shift_id,
            "volunteer_id": volunteer_id,
            "corporate_group_id": None,
            "status": "RESERVED",
            "logged_hours": None,
            "verified_hours": None,
            "provisional_hours": 0,
        })
        store.signups[rec["id"]] = rec
        occupy_seat(shift)
        touch(shift)
    return object_response(serialize(COLL, rec), status=201)


# ---- list / get -----------------------------------------------------------
@bp.get("/vm/signups")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def list_signups():
    shift_id = request.args.get("shift_id")
    volunteer_id = request.args.get("volunteer_id")
    corporate_group_id = request.args.get("corporate_group_id")
    status = request.args.get("status")

    def pred(r):
        if shift_id is not None and r["shift_id"] != shift_id:
            return False
        if volunteer_id is not None and r["volunteer_id"] != volunteer_id:
            return False
        if corporate_group_id is not None and r["corporate_group_id"] != corporate_group_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    page, limit, offset, total = list_collection(COLL, pred)
    return array_response(serialize_list(COLL, page), limit, offset, total)


@bp.get("/vm/signups/<signup_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def get_signup(signup_id):
    rec = get_or_404(COLL, signup_id)
    return object_response(serialize(COLL, rec))


# ---- volunteer-driven transitions -----------------------------------------
@bp.post("/vm/signups/<signup_id>/confirm")
@require_role("Volunteer")
def confirm_signup(signup_id):
    with store.lock:
        rec = get_or_404(COLL, signup_id)
        if rec["status"] != "RESERVED":
            raise ApiError("ERR_SIGNUP_NOT_RESERVED", "confirm requires RESERVED")
        _owner_check(rec)
        rec["status"] = "CONFIRMED"
        touch(rec)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/signups/<signup_id>/cancel")
@require_role("Volunteer")
def cancel_signup(signup_id):
    with store.lock:
        rec = get_or_404(COLL, signup_id)
        if rec["status"] not in ("RESERVED", "CONFIRMED"):
            raise ApiError("ERR_SIGNUP_NOT_CANCELLABLE", "cancel requires RESERVED/CONFIRMED")
        _owner_check(rec)
        rec["status"] = "CANCELLED"
        touch(rec)
        shift = store.shifts.get(rec["shift_id"])
        if shift is not None:
            release_seat(shift)
            touch(shift)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/signups/<signup_id>/log-hours")
@require_role("Volunteer")
def log_hours(signup_id):
    body = get_json()
    logged = require_number(body, "logged_hours")
    with store.lock:
        rec = get_or_404(COLL, signup_id)
        if rec["status"] != "ATTENDED":
            raise ApiError("ERR_SIGNUP_NOT_ATTENDED", "log-hours requires ATTENDED")
        _owner_check(rec)
        if logged <= 0:
            raise ApiError("ERR_INVALID_HOURS", "logged_hours must be > 0")
        shift = store.shifts.get(rec["shift_id"])
        duration = calc.duration_hours(parse_dt(shift["starts_at"]), parse_dt(shift["ends_at"]))
        if logged > duration:
            raise ApiError("ERR_HOURS_EXCEED_SHIFT", "logged_hours exceeds shift duration")
        rec["logged_hours"] = logged
        rec["status"] = "HOURS_LOGGED"
        touch(rec)
    return object_response(serialize(COLL, rec))


# ---- coordinator-driven transitions ---------------------------------------
@bp.post("/vm/signups/<signup_id>/check-in")
@require_role("ShiftCoordinator")
def check_in(signup_id):
    with store.lock:
        rec = get_or_404(COLL, signup_id)
        if rec["status"] != "CONFIRMED":
            raise ApiError("ERR_SIGNUP_NOT_CONFIRMED", "check-in requires CONFIRMED")
        shift = store.shifts.get(rec["shift_id"])
        now = store.now()
        if now < parse_dt(shift["starts_at"]):
            raise ApiError("ERR_SHIFT_NOT_STARTED", "shift has not started")
        rec["provisional_hours"] = calc.provisional_hours(
            parse_dt(shift["starts_at"]), parse_dt(shift["ends_at"]))
        rec["status"] = "ATTENDED"
        touch(rec)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/signups/<signup_id>/mark-no-show")
@require_role("ShiftCoordinator")
def mark_no_show(signup_id):
    with store.lock:
        rec = get_or_404(COLL, signup_id)
        if rec["status"] != "CONFIRMED":
            raise ApiError("ERR_SIGNUP_NOT_CONFIRMED", "mark-no-show requires CONFIRMED")
        rec["status"] = "NO_SHOW"
        touch(rec)
        no_show_cascade(rec)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/signups/<signup_id>/verify-hours")
@require_role("ShiftCoordinator")
def verify_hours(signup_id):
    with store.lock:
        rec = get_or_404(COLL, signup_id)
        if rec["status"] != "HOURS_LOGGED":
            raise ApiError("ERR_SIGNUP_NOT_LOGGED", "verify-hours requires HOURS_LOGGED")
        rec["verified_hours"] = calc.verified_hours(rec["logged_hours"], rec["provisional_hours"])
        rec["status"] = "HOURS_VERIFIED"
        touch(rec)
        volunteer = store.volunteers.get(rec["volunteer_id"])
        if volunteer is not None:
            verify_hours_cascade(volunteer)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/signups/<signup_id>/reject-hours")
@require_role("ShiftCoordinator")
def reject_hours(signup_id):
    with store.lock:
        rec = get_or_404(COLL, signup_id)
        if rec["status"] != "HOURS_LOGGED":
            raise ApiError("ERR_SIGNUP_NOT_LOGGED", "reject-hours requires HOURS_LOGGED")
        rec["logged_hours"] = None
        rec["status"] = "ATTENDED"
        touch(rec)
    return object_response(serialize(COLL, rec))
