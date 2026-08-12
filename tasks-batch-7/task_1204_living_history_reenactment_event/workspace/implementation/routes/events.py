"""Event lifecycle endpoints + logical clock endpoint."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import authenticate, get_event
from response import success
from services import cascades, derived
from services.common import new_record, touch
from util import body, opt_dt, opt_int, opt_str, req_dt, req_int, req_num, req_str
from util import is_int


def body_from():
    return body(request)

bp = Blueprint("events", __name__)

ALL_ROLES = [
    "EventOrganizer",
    "AuthenticityOfficer",
    "SafetyOfficer",
    "UnitCommander",
    "Participant",
    "Vendor",
    "Spectator",
]

_PRICE_FIELDS = (
    "adult_day_price_cents",
    "child_day_price_cents",
    "adult_weekend_price_cents",
    "child_weekend_price_cents",
    "service_fee_cents",
    "required_liability_cents",
    "vendor_frontage_rate_cents",
    "vendor_min_fee_cents",
    "vendor_late_insurance_surcharge_cents",
)


@bp.post("/events")
def create_event():
    authenticate(["EventOrganizer"], creation=True)
    data = body_from()
    rec = new_record()
    rec.update(
        name=req_str(data, "name"),
        site_name=req_str(data, "site_name"),
        event_starts_at=req_dt(data, "event_starts_at"),
        event_ends_at=req_dt(data, "event_ends_at"),
        early_bird_pct=req_num(data, "early_bird_pct", minimum=0, maximum=1),
        early_bird_cutoff_at=req_dt(data, "early_bird_cutoff_at"),
        refund_retain_pct=req_num(data, "refund_retain_pct", minimum=0, maximum=1),
        max_minor_per_adult=opt_int(data, "max_minor_per_adult", 4, minimum=0),
        vendor_multi_day_discount_pct=req_num(
            data, "vendor_multi_day_discount_pct", minimum=0, maximum=1
        ),
        vendor_insurance_deadline_at=req_dt(data, "vendor_insurance_deadline_at"),
        event_posture="PLANNING",
        cancelled_at=None,
    )
    for f in _PRICE_FIELDS:
        rec[f] = req_int(data, f, minimum=0)
    db.events[rec["id"]] = rec
    return success(serializers.event(rec), 201)


@bp.get("/events/<event_id>")
def read_event(event_id):
    authenticate(ALL_ROLES)
    return success(serializers.event(get_event(event_id)), 200)


_MUTABLE_FIELDS_STR = ("name", "site_name")
_MUTABLE_FIELDS_DT = ("event_starts_at", "event_ends_at")
_MUTABLE_FIELDS_INT = ("required_liability_cents", "max_minor_per_adult")


@bp.patch("/events/<event_id>")
def patch_event(event_id):
    authenticate(["EventOrganizer"])
    ev = get_event(event_id)
    data = body_from()
    # OCC (priority 4): a present, integer expected_event_version must match.
    eev = data.get("expected_event_version")
    if is_int(eev) and eev != ev["version"]:
        fail("ERR_STALE_VERSION", "expected_event_version does not match current version")
    # Posture (priority 5)
    if ev["event_posture"] not in ("PLANNING", "REGISTRATION_OPEN"):
        fail("ERR_INVALID_EVENT_POSTURE", "event settings are mutable only in PLANNING or REGISTRATION_OPEN")
    # Body shape (priority 7)
    if "expected_event_version" not in data or not is_int(eev):
        fail("ERR_VALIDATION", "expected_event_version is required")
    updates = {}
    for f in _MUTABLE_FIELDS_STR:
        if f in data and data[f] is not None:
            updates[f] = opt_str(data, f)
    for f in _MUTABLE_FIELDS_DT:
        if f in data and data[f] is not None:
            updates[f] = opt_dt(data, f)
    for f in _MUTABLE_FIELDS_INT:
        if f in data and data[f] is not None:
            updates[f] = opt_int(data, f, None, minimum=0)
    ev.update(updates)
    touch(ev)
    return success(serializers.event(ev), 200)


def _lifecycle(event_id, from_postures, roles=("EventOrganizer",)):
    authenticate(list(roles))
    ev = get_event(event_id)
    if ev["event_posture"] not in from_postures:
        fail(
            "ERR_INVALID_EVENT_POSTURE",
            f"event posture {ev['event_posture']} does not permit this operation",
        )
    return ev


@bp.post("/events/<event_id>/open-registration")
def open_registration(event_id):
    ev = _lifecycle(event_id, ("PLANNING",))
    ev["event_posture"] = "REGISTRATION_OPEN"
    touch(ev)
    return success(serializers.event(ev), 200)


@bp.post("/events/<event_id>/publish")
def publish(event_id):
    ev = _lifecycle(event_id, ("REGISTRATION_OPEN",))
    # Landowner agreement must be SIGNED and cover the whole event window.
    landowner_ok = False
    insurance_ok = False
    for a in db.agreements.values():
        if a["event_id"] != ev["id"] or a["status"] != "SIGNED":
            continue
        covers = (
            a["effective_from"] <= ev["event_starts_at"]
            and a["effective_until"] >= ev["event_ends_at"]
        )
        if a["agreement_type"] == "LANDOWNER_USE" and covers:
            landowner_ok = True
        if (
            a["agreement_type"] == "INSURANCE_LIABILITY"
            and covers
            and a["coverage_amount_cents"] is not None
            and a["coverage_amount_cents"] >= ev["required_liability_cents"]
        ):
            insurance_ok = True
    if not landowner_ok:
        fail("ERR_AGREEMENT_NOT_IN_FORCE", "no SIGNED LANDOWNER_USE agreement covers the event window")
    if not insurance_ok:
        fail("ERR_INSURANCE_COVERAGE_INSUFFICIENT", "no sufficient SIGNED INSURANCE_LIABILITY agreement covers the event")
    ev["event_posture"] = "PUBLISHED"
    touch(ev)
    return success(serializers.event(ev), 200)


@bp.post("/events/<event_id>/open-gates")
def open_gates(event_id):
    ev = _lifecycle(event_id, ("PUBLISHED",))
    if derived.open_red_flag_exists(ev):
        fail("ERR_RED_ALERTS_OPEN", "an OPEN RED_FLAG alert blocks opening the gates")
    ev["event_posture"] = "EVENT_OPEN"
    touch(ev)
    return success(serializers.event(ev), 200)


@bp.post("/events/<event_id>/restrict")
def restrict(event_id):
    ev = _lifecycle(event_id, ("EVENT_OPEN",), roles=("EventOrganizer", "SafetyOfficer"))
    cascades.restrict_event(ev)
    return success(serializers.event(ev), 200)


@bp.post("/events/<event_id>/lift-restriction")
def lift_restriction(event_id):
    ev = _lifecycle(event_id, ("RESTRICTED",), roles=("EventOrganizer", "SafetyOfficer"))
    if derived.open_red_flag_exists(ev):
        fail("ERR_RED_ALERTS_OPEN", "an OPEN RED_FLAG alert blocks lifting the restriction")
    ev["event_posture"] = "EVENT_OPEN"
    touch(ev)
    return success(serializers.event(ev), 200)


@bp.post("/events/<event_id>/complete")
def complete(event_id):
    ev = _lifecycle(event_id, ("EVENT_OPEN", "RESTRICTED"))
    ev["event_posture"] = "COMPLETED"
    touch(ev)
    for s in db.slots.values():
        if s["event_id"] == ev["id"] and s["status"] == "CONFIRMED":
            s["status"] = "DONE"
            touch(s)
    return success(serializers.event(ev), 200)


@bp.post("/events/<event_id>/cancel")
def cancel(event_id):
    authenticate(["EventOrganizer"])
    ev = get_event(event_id)
    if ev["event_posture"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_INVALID_EVENT_POSTURE", "a terminal event cannot be cancelled")
    cascades.cancel_event(ev)
    return success(serializers.event(ev), 200)
