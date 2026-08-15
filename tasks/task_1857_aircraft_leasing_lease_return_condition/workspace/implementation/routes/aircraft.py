"""Aircraft, records documents, and transition slots."""
from datetime import datetime

from flask import Blueprint

from db import STORE, base_entity, touch
from errors import (
    ApiError,
    ERR_DEFAULT_CASE_OPEN,
    ERR_SLOT_WINDOW_CONFLICT,
    bad_request,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, require_roles
from response import paginated, success
from services.calculations import TRANSITION_BUFFER_DAYS, records_completeness
from services.cascades import open_default_case
from validators import get_body, opt_str, req_date, req_enum, req_str

bp = Blueprint("aircraft", __name__)

DOC_TYPES = {"BIRTH_RECORD", "AIRWORTHINESS_CERT", "ENGINE_LOG", "LLP_STATUS", "OTHER"}

LEASE_HOLDING_STATUSES = ("ACTIVE", "RETURN_INITIATED", "DEFAULTED")


def serialize_aircraft(a):
    out = dict(a)
    _, score = records_completeness(a["id"])
    out["records_completeness_score"] = score
    return out


def get_aircraft_or_404(aircraft_id):
    a = STORE["aircraft"].get(aircraft_id)
    if a is None:
        raise not_found("Aircraft not found")
    return a


# ---------------------------------------------------------------------------
# Aircraft
# ---------------------------------------------------------------------------
@bp.post("/leasing/aircraft")
@require_roles("LessorAdmin")
def create_aircraft():
    b = get_body()
    msn = req_str(b, "msn")
    model = req_str(b, "model")
    manufacture_date = req_date(b, "manufacture_date")
    if any(a["msn"] == msn for a in STORE["aircraft"].values()):
        raise bad_request("msn must be unique across all aircraft")
    a = base_entity()
    a.update(
        {
            "msn": msn,
            "model": model,
            "manufacture_date": manufacture_date,
            "status": "AVAILABLE",
            "total_flight_hours": 0,
            "total_flight_cycles": 0,
        }
    )
    STORE["aircraft"][a["id"]] = a
    return success(serialize_aircraft(a), status=201)


@bp.get("/leasing/aircraft/<aircraft_id>")
@require_roles(*ALL_ROLES)
def get_aircraft(aircraft_id):
    a = get_aircraft_or_404(aircraft_id)
    return success(serialize_aircraft(a))


# ---------------------------------------------------------------------------
# Records documents
# ---------------------------------------------------------------------------
@bp.post("/leasing/aircraft/<aircraft_id>/documents")
@require_roles("LessorAdmin")
def create_document(aircraft_id):
    a = get_aircraft_or_404(aircraft_id)
    b = get_body()
    doc_type = req_enum(b, "doc_type", DOC_TYPES)
    doc_reference = req_str(b, "doc_reference")
    d = base_entity()
    d.update(
        {
            "aircraft_id": a["id"],
            "doc_type": doc_type,
            "doc_reference": doc_reference,
            "status": "SUBMITTED",
        }
    )
    STORE["aircraft_documents"][d["id"]] = d
    return success(d, status=201)


@bp.get("/leasing/aircraft/<aircraft_id>/documents")
@require_roles(*ALL_ROLES)
def list_documents(aircraft_id):
    a = get_aircraft_or_404(aircraft_id)
    docs = [d for d in STORE["aircraft_documents"].values() if d["aircraft_id"] == a["id"]]
    docs.sort(key=lambda d: d["created_at"])
    return paginated(docs)


@bp.post("/leasing/documents/<doc_id>/review")
@require_roles("LessorAdmin")
def review_document(doc_id):
    d = STORE["aircraft_documents"].get(doc_id)
    if d is None:
        raise not_found("Document not found")
    b = get_body()
    decision = req_enum(b, "decision", {"VERIFIED", "REJECT"})
    if d["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED document can be reviewed")
    d["status"] = "VERIFIED" if decision == "VERIFIED" else "REJECTED"
    touch(d)
    return success(d)


# ---------------------------------------------------------------------------
# Transition slots
# ---------------------------------------------------------------------------
def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


@bp.post("/leasing/aircraft/<aircraft_id>/transition-slots")
@require_roles("LessorAdmin")
def create_transition_slot(aircraft_id):
    a = get_aircraft_or_404(aircraft_id)
    b = get_body()
    window_start = req_date(b, "window_start")
    window_end = req_date(b, "window_end")
    next_operator_ref = opt_str(b, "next_operator_ref", None)
    if _parse_date(window_end) < _parse_date(window_start):
        raise bad_request("window_end must be on or after window_start")

    # Buffer rule (priority 7): conflict unless the new window clears every
    # other TENTATIVE/CONFIRMED window on this aircraft by MORE than
    # TRANSITION_BUFFER_DAYS whole days on one side or the other.
    ns, ne = _parse_date(window_start), _parse_date(window_end)
    for s in STORE["transition_slots"].values():
        if s["aircraft_id"] != a["id"] or s["status"] not in ("TENTATIVE", "CONFIRMED"):
            continue
        es, ee = _parse_date(s["window_start"]), _parse_date(s["window_end"])
        clears_after = (ns - ee).days > TRANSITION_BUFFER_DAYS
        clears_before = (es - ne).days > TRANSITION_BUFFER_DAYS
        if not (clears_after or clears_before):
            raise ApiError(
                ERR_SLOT_WINDOW_CONFLICT,
                "Transition window fails the 2-day buffer rule against an existing slot",
                409,
            )

    # Open-default rule (priority 9).
    for lease in STORE["leases"].values():
        if lease["aircraft_id"] == a["id"] and lease["status"] in LEASE_HOLDING_STATUSES:
            if open_default_case(lease["id"]) is not None:
                raise ApiError(
                    ERR_DEFAULT_CASE_OPEN,
                    "The aircraft's current lease has an open default case",
                    409,
                )

    s = base_entity()
    s.update(
        {
            "aircraft_id": a["id"],
            "window_start": window_start,
            "window_end": window_end,
            "next_operator_ref": next_operator_ref,
            "status": "TENTATIVE",
        }
    )
    STORE["transition_slots"][s["id"]] = s
    return success(s, status=201)


@bp.get("/leasing/aircraft/<aircraft_id>/transition-slots")
@require_roles(*ALL_ROLES)
def list_transition_slots(aircraft_id):
    a = get_aircraft_or_404(aircraft_id)
    slots = [s for s in STORE["transition_slots"].values() if s["aircraft_id"] == a["id"]]
    slots.sort(key=lambda s: (s["window_start"], s["created_at"]))
    return paginated(slots)


@bp.post("/leasing/transition-slots/<slot_id>/advance")
@require_roles("LessorAdmin")
def advance_transition_slot(slot_id):
    s = STORE["transition_slots"].get(slot_id)
    if s is None:
        raise not_found("Transition slot not found")
    b = get_body()
    to = req_enum(b, "to", {"CONFIRMED", "COMPLETED", "RELEASED"})
    aircraft = STORE["aircraft"].get(s["aircraft_id"])

    if to == "CONFIRMED":
        if s["status"] != "TENTATIVE":
            raise invalid_state("Only a TENTATIVE slot can be confirmed")
        if aircraft is None or aircraft["status"] not in ("IN_TRANSITION", "REPOSSESSED"):
            raise invalid_state(
                "Aircraft must be IN_TRANSITION or REPOSSESSED to confirm a slot"
            )
        s["status"] = "CONFIRMED"
        touch(s)
    elif to == "COMPLETED":
        if s["status"] != "CONFIRMED":
            raise invalid_state("Only a CONFIRMED slot can be completed")
        s["status"] = "COMPLETED"
        touch(s)
        if aircraft is not None and aircraft["status"] in ("IN_TRANSITION", "REPOSSESSED"):
            aircraft["status"] = "AVAILABLE"
            touch(aircraft)
        # The aircraft's RETURNED lease (at most one) closes.
        for lease in STORE["leases"].values():
            if lease["aircraft_id"] == s["aircraft_id"] and lease["status"] == "RETURNED":
                lease["status"] = "CLOSED"
                touch(lease)
                break
    else:  # RELEASED
        if s["status"] not in ("TENTATIVE", "CONFIRMED"):
            raise invalid_state("Only a TENTATIVE or CONFIRMED slot can be released")
        s["status"] = "RELEASED"
        touch(s)
    return success(s)
