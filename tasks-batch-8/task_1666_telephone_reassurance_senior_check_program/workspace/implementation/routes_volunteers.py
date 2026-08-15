"""Volunteer roster: lifecycle, availability windows, training records,
confidentiality agreements."""
from flask import Blueprint, request

from auth import endpoint, get_body
from db import store, now, new_entity, touch
from envelope import ok, ok_list
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_OWN_RESOURCE,
                    ERR_VOLUNTEER_NOT_CERTIFIED, ERR_CONFIDENTIALITY_NOT_CURRENT,
                    ERR_AVAILABILITY_OVERLAP)
from validate import Field, validate_payload, parse_pagination, sort_items
import calc
import cascade
import serialize
from timeutil import parse_hm

bp = Blueprint("volunteers", __name__)

PC = ["ProgramCoordinator"]
PC_QR = ["ProgramCoordinator", "QualityReviewer"]
PC_QR_VC = ["ProgramCoordinator", "QualityReviewer", "VolunteerCaller"]
WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
MODULES = {"SAFETY_PROTOCOL", "LISTENING_SKILLS", "MANDATED_REPORTING",
           "CONFIDENTIALITY_BASICS"}


def get_volunteer_or_404(vid):
    v = store.volunteers.get(vid)
    if not v:
        raise_err(ERR_NOT_FOUND, "Volunteer not found")
    return v


def sole_program_or_404():
    g = calc.sole_program()
    if not g:
        raise_err(ERR_NOT_FOUND, "Program not found")
    return g


@bp.route("/api/volunteers", methods=["POST"])
@endpoint(PC)
def create_volunteer(uid, role):
    data = validate_payload(get_body(), [
        Field("full_name", "str", required=True, allow_empty_str=False),
        Field("phone", "str", required=True, allow_empty_str=False),
        Field("languages", "list_str", default=lambda: ["en"]),
        Field("max_weekly_minutes", "int", default=240, minv=60, maxv=600),
    ])
    if not data.get("languages"):
        data["languages"] = ["en"]
    v = new_entity()
    v.update({
        "full_name": data["full_name"],
        "phone": data["phone"],
        "languages": data["languages"],
        "max_weekly_minutes": data.get("max_weekly_minutes", 240),
        "status": "APPLICANT",
    })
    store.volunteers[v["id"]] = v
    return ok(serialize.volunteer(v), 201)


@bp.route("/api/volunteers", methods=["GET"])
@endpoint(PC_QR)
def list_volunteers(uid, role):
    limit, offset = parse_pagination(request.args)
    items = list(store.volunteers.values())
    if "status" in request.args:
        items = [v for v in items if v["status"] == request.args["status"]]
    if "reliability_tier" in request.args:
        want = request.args["reliability_tier"]
        items = [v for v in items if calc.reliability(v)[2] == want]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.volunteer(v) for v in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/volunteers/<vid>", methods=["GET"])
@endpoint(PC_QR_VC)
def get_volunteer(vid, uid, role):
    return ok(serialize.volunteer(get_volunteer_or_404(vid)))


@bp.route("/api/volunteers/<vid>/begin-training", methods=["POST"])
@endpoint(PC)
def begin_training(vid, uid, role):
    v = get_volunteer_or_404(vid)
    if v["status"] != "APPLICANT":
        raise_err(ERR_INVALID_STATE, "Volunteer is not APPLICANT")
    v["status"] = "IN_TRAINING"
    touch(v)
    return ok(serialize.volunteer(v))


def check_currency(v, g):
    if not calc.training_current(v):
        raise_err(ERR_VOLUNTEER_NOT_CERTIFIED,
                  "Required training modules are not all VALID")
    if not calc.agreement_current(v, g):
        raise_err(ERR_CONFIDENTIALITY_NOT_CURRENT,
                  "No ACTIVE confidentiality agreement matching current policy")


@bp.route("/api/volunteers/<vid>/certify", methods=["POST"])
@endpoint(PC)
def certify(vid, uid, role):
    v = get_volunteer_or_404(vid)
    if v["status"] not in ("IN_TRAINING", "LAPSED"):
        raise_err(ERR_INVALID_STATE, "Volunteer is not IN_TRAINING or LAPSED")
    g = sole_program_or_404()
    check_currency(v, g)
    v["status"] = "ACTIVE"
    touch(v)
    return ok(serialize.volunteer(v))


@bp.route("/api/volunteers/<vid>/deactivate", methods=["POST"])
@endpoint(PC)
def deactivate(vid, uid, role):
    v = get_volunteer_or_404(vid)
    if v["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Volunteer is not ACTIVE")
    v["status"] = "INACTIVE"
    touch(v)
    return ok(serialize.volunteer(v))


@bp.route("/api/volunteers/<vid>/reactivate", methods=["POST"])
@endpoint(PC)
def reactivate(vid, uid, role):
    v = get_volunteer_or_404(vid)
    if v["status"] != "INACTIVE":
        raise_err(ERR_INVALID_STATE, "Volunteer is not INACTIVE")
    g = sole_program_or_404()
    check_currency(v, g)
    v["status"] = "ACTIVE"
    touch(v)
    return ok(serialize.volunteer(v))


@bp.route("/api/volunteers/<vid>/separate", methods=["POST"])
@endpoint(PC)
def separate(vid, uid, role):
    v = get_volunteer_or_404(vid)
    if v["status"] == "SEPARATED":
        raise_err(ERR_INVALID_STATE, "Volunteer already SEPARATED")
    v["status"] = "SEPARATED"
    touch(v)
    for a in list(store.assignments.values()):
        if a.get("volunteer_id") == v["id"] and cascade.future_dated(a):
            cascade.cancel_assignment(a, "MANUAL")
    return ok(serialize.volunteer(v))


# ---------------- availability windows ----------------

@bp.route("/api/volunteers/<vid>/availability-windows", methods=["GET"])
@endpoint(PC_QR_VC)
def list_windows(vid, uid, role):
    v = get_volunteer_or_404(vid)
    limit, offset = parse_pagination(request.args)
    items = [w for w in store.windows.values() if w["volunteer_id"] == v["id"]]
    if "weekday" in request.args:
        items = [w for w in items if w["weekday"] == request.args["weekday"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.availability_window(w) for w in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/volunteers/<vid>/availability-windows", methods=["POST"])
@endpoint(["ProgramCoordinator", "VolunteerCaller"])
def create_window(vid, uid, role):
    v = get_volunteer_or_404(vid)
    if role == "VolunteerCaller" and uid != v["id"]:
        raise_err(ERR_NOT_OWN_RESOURCE, "Volunteers manage only their own availability")
    data = validate_payload(get_body(), [
        Field("weekday", "enum", required=True, enum=WEEKDAYS),
        Field("window_start", "hm", required=True),
        Field("window_end", "hm", required=True),
        Field("effective_from", "date", required=True),
        Field("effective_to", "date"),
    ])
    ws, we = parse_hm(data["window_start"]), parse_hm(data["window_end"])
    if ws >= we:
        raise_err(ERR_INVALID_REQUEST, "window_start must be before window_end")
    eff_from = data["effective_from"]
    eff_to = data.get("effective_to")
    if eff_to is not None and eff_to < eff_from:
        raise_err(ERR_INVALID_REQUEST, "effective_to must not precede effective_from")
    for w in store.windows.values():
        if w["volunteer_id"] != v["id"] or w["weekday"] != data["weekday"]:
            continue
        # effective-range overlap required as well
        other_from, other_to = w["effective_from"], w["effective_to"]
        if eff_to is not None and other_from > eff_to:
            continue
        if other_to is not None and eff_from > other_to:
            continue
        # half-open time overlap
        ows, owe = parse_hm(w["window_start"]), parse_hm(w["window_end"])
        if ws < owe and ows < we:
            raise_err(ERR_AVAILABILITY_OVERLAP,
                      "Window overlaps an existing same-weekday window")
    w = new_entity()
    w.update({
        "volunteer_id": v["id"],
        "weekday": data["weekday"],
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "effective_from": eff_from,
        "effective_to": eff_to,
    })
    store.windows[w["id"]] = w
    return ok(serialize.availability_window(w), 201)


@bp.route("/api/availability-windows/<wid>", methods=["DELETE"])
@endpoint(["ProgramCoordinator", "VolunteerCaller"])
def delete_window(wid, uid, role):
    w = store.windows.get(wid)
    if not w:
        raise_err(ERR_NOT_FOUND, "Availability window not found")
    if role == "VolunteerCaller" and uid != w["volunteer_id"]:
        raise_err(ERR_NOT_OWN_RESOURCE, "Volunteers manage only their own availability")
    del store.windows[wid]
    return "", 204


# ---------------- training records ----------------

@bp.route("/api/volunteers/<vid>/training-records", methods=["GET"])
@endpoint(PC_QR)
def list_training(vid, uid, role):
    v = get_volunteer_or_404(vid)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.training.values() if r["volunteer_id"] == v["id"]]
    if "module" in request.args:
        items = [r for r in items if r["module"] == request.args["module"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.training_record(r) for r in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/volunteers/<vid>/training-records", methods=["POST"])
@endpoint(PC)
def create_training(vid, uid, role):
    v = get_volunteer_or_404(vid)
    data = validate_payload(get_body(), [
        Field("module", "enum", required=True, enum=MODULES),
        Field("completed_at", "dt", required=True),
        Field("valid_until", "dt", required=True),
    ])
    r = new_entity()
    r.update({
        "volunteer_id": v["id"],
        "module": data["module"],
        "completed_at": data["completed_at"],
        "valid_until": data["valid_until"],
    })
    store.training[r["id"]] = r
    return ok(serialize.training_record(r), 201)


# ---------------- confidentiality agreements ----------------

@bp.route("/api/volunteers/<vid>/confidentiality-agreements", methods=["GET"])
@endpoint(PC_QR_VC)
def list_agreements(vid, uid, role):
    v = get_volunteer_or_404(vid)
    limit, offset = parse_pagination(request.args)
    items = [a for a in store.agreements.values() if a["volunteer_id"] == v["id"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.agreement(a) for a in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/volunteers/<vid>/confidentiality-agreements", methods=["POST"])
@endpoint(["VolunteerCaller"])
def sign_agreement(vid, uid, role):
    v = get_volunteer_or_404(vid)
    if uid != v["id"]:
        raise_err(ERR_NOT_OWN_RESOURCE, "Volunteers sign only their own agreement")
    data = validate_payload(get_body(), [
        Field("policy_version", "str", required=True, allow_empty_str=False),
        Field("valid_until", "dt", required=True),
    ])
    for a in store.agreements.values():
        if a["volunteer_id"] == v["id"] and a["status"] == "ACTIVE":
            a["status"] = "SUPERSEDED"
            touch(a)
    a = new_entity()
    a.update({
        "volunteer_id": v["id"],
        "policy_version": data["policy_version"],
        "signed_at": now(),
        "valid_until": data["valid_until"],
        "status": "ACTIVE",
    })
    store.agreements[a["id"]] = a
    return ok(serialize.agreement(a), 201)


@bp.route("/api/confidentiality-agreements/<aid>/revoke", methods=["POST"])
@endpoint(["QualityReviewer"])
def revoke_agreement(aid, uid, role):
    a = store.agreements.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "Confidentiality agreement not found")
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Agreement is not ACTIVE")
    a["status"] = "REVOKED"
    touch(a)
    return ok(serialize.agreement(a))
