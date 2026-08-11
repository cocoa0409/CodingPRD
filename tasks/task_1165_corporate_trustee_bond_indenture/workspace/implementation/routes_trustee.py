"""Routes: TrusteeAppointment (PRD 3.9)."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from envelope import ok, list_response, get_body, public
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_NOT_YET_EFFECTIVE,
                    ERR_STALE_VERSION, ERR_INVALID_REQUEST)
from store import DB, LOCK, new_entity, now, mutate, touch
from validate import req_str, req_enum, req_date, parse_date_strict, is_int

bp = Blueprint("trustee", __name__)

APPOINTMENT_TERMINAL = ("EFFECTIVE", "RESCINDED", "SUPERSEDED")


@bp.route("/trustee-appointments", methods=["POST"])
@require_roles("PlatformAdmin")
def create_appointment():
    body = get_body()
    with LOCK:
        indenture_id = body.get("indenture_id")
        ind = DB["indentures"].get(indenture_id) if isinstance(indenture_id, str) else None
        if ind is None:
            raise_err(ERR_NOT_FOUND, "Indenture not found")
        # OCC: expected_indenture_version must match the indenture's version.
        expected = body.get("expected_indenture_version")
        if is_int(expected) and expected != ind["version"]:
            raise_err(ERR_STALE_VERSION, "expected_indenture_version is stale")
        # Rule 26: shape.
        req_str(body, "indenture_id")
        incoming = req_str(body, "incoming_trustee_ref")
        reason = req_enum(body, "reason",
                          ["RESIGNATION", "REMOVAL", "CONSOLIDATION"])
        eff_date = req_date(body, "proposed_effective_date")
        if not is_int(body.get("expected_indenture_version")):
            raise_err(ERR_INVALID_REQUEST,
                      "expected_indenture_version is required")
        # Supersede in-flight (PROPOSED/ACCEPTED) siblings on the indenture.
        for a in DB["trustee_appointments"].values():
            if (a["indenture_id"] == ind["id"]
                    and a["status"] in ("PROPOSED", "ACCEPTED")):
                mutate(a, status="SUPERSEDED")
        e = new_entity("trustee_appointments")
        e.update({
            "indenture_id": indenture_id,
            "outgoing_trustee_ref": ind["current_trustee_ref"],
            "incoming_trustee_ref": incoming,
            "reason": reason,
            "proposed_effective_date": eff_date,
            "status": "PROPOSED",
        })
        touch(ind)  # creation advances the parent indenture version
    return ok(public(e), 201)


@bp.route("/trustee-appointments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_appointments():
    return list_response(DB["trustee_appointments"].values(), {
        "indenture_id": request.args.get("indenture_id"),
        "status": request.args.get("status"),
    })


@bp.route("/trustee-appointments/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_appointment(aid):
    e = DB["trustee_appointments"].get(aid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "TrusteeAppointment not found")
    return ok(public(e))


@bp.route("/trustee-appointments/<aid>/accept", methods=["POST"])
@require_roles("PlatformAdmin")
def accept_appointment(aid):
    with LOCK:
        appt = DB["trustee_appointments"].get(aid)
        if appt is None:
            raise_err(ERR_NOT_FOUND, "TrusteeAppointment not found")
        if appt["status"] in APPOINTMENT_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Appointment is terminal (%s)" % appt["status"])
        if appt["status"] != "PROPOSED":
            raise_err(ERR_INVALID_STATE,
                      "Only a PROPOSED appointment can be accepted")
        mutate(appt, status="ACCEPTED")
    return ok(public(appt))


@bp.route("/trustee-appointments/<aid>/effect", methods=["POST"])
@require_roles("PlatformAdmin")
def effect_appointment(aid):
    with LOCK:
        appt = DB["trustee_appointments"].get(aid)
        if appt is None:
            raise_err(ERR_NOT_FOUND, "TrusteeAppointment not found")
        if appt["status"] in APPOINTMENT_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Appointment is terminal (%s)" % appt["status"])
        if appt["status"] != "ACCEPTED":
            raise_err(ERR_INVALID_STATE,
                      "Only an ACCEPTED appointment can be effected")
        # Rule 19: logical clock date must be on/after proposed_effective_date.
        ped = parse_date_strict(appt["proposed_effective_date"])
        if ped is not None and now().date() < ped:
            raise_err(ERR_NOT_YET_EFFECTIVE,
                      "The proposed effective date has not arrived")
        mutate(appt, status="EFFECTIVE")
        ind = DB["indentures"].get(appt["indenture_id"])
        if ind is not None:
            mutate(ind, current_trustee_ref=appt["incoming_trustee_ref"])
            # Trustee succession voids DRAFT fee invoices of the indenture.
            for inv in DB["fee_invoices"].values():
                if inv["indenture_id"] == ind["id"] and inv["status"] == "DRAFT":
                    mutate(inv, status="VOID")
    return ok(public(appt))


@bp.route("/trustee-appointments/<aid>/rescind", methods=["POST"])
@require_roles("PlatformAdmin")
def rescind_appointment(aid):
    with LOCK:
        appt = DB["trustee_appointments"].get(aid)
        if appt is None:
            raise_err(ERR_NOT_FOUND, "TrusteeAppointment not found")
        if appt["status"] in APPOINTMENT_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Appointment is terminal (%s)" % appt["status"])
        if appt["status"] not in ("PROPOSED", "ACCEPTED"):
            raise_err(ERR_INVALID_STATE, "Appointment cannot be rescinded")
        mutate(appt, status="RESCINDED")
    return ok(public(appt))
