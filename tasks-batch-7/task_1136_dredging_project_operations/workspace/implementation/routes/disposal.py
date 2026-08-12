"""DisposalSite and PlacementTicket endpoints (PRD 3.7): capacity accounting
(INV-1), per-ticket in-situ rounding, segregation on adjudication."""
import uuid
from decimal import Decimal

from flask import Blueprint, g

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_EVENT_NOT_COMPLETED,
    ERR_DISPOSAL_SITE_NOT_OPEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_PLACEMENT_OUT_OF_WINDOW,
    ERR_DISPOSAL_CAPACITY_EXCEEDED,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import serialize_site, serialize_ticket
from util import (
    as_enum,
    as_int,
    as_num,
    as_str,
    check,
    get_body,
    new_entity,
    parse_dt,
    req_present,
    r2,
    touch,
)

bp = Blueprint("disposal", __name__)


# --- DisposalSite -----------------------------------------------------------

@bp.post("/disposal-sites")
@require_roles("OwnerEngineer")
def create_site():
    body = get_body()
    name = as_str(req_present(body, "name"), "name")
    site_type = as_enum(
        req_present(body, "site_type"),
        "site_type",
        ["UPLAND_CONFINED", "OPEN_WATER", "BEACH_NOURISHMENT"],
    )
    capacity = as_int(req_present(body, "capacity_cy"), "capacity_cy")
    check(capacity > 0, "capacity_cy must be > 0")
    bulking = as_num(req_present(body, "bulking_factor"), "bulking_factor")
    check(bulking > 0, "bulking_factor must be > 0")
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "site_type": site_type,
            "capacity_cy": capacity,
            "bulking_factor": bulking,
            "used_cy": Decimal("0"),
            "status": "OPEN",
        }
    )
    store.sites[rec["id"]] = rec
    return ok(serialize_site(rec), 201)


def _get_site(sid):
    site = store.sites.get(sid)
    if site is None:
        raise ApiError(ERR_NOT_FOUND, "DisposalSite not found", 404)
    return site


@bp.get("/disposal-sites/<sid>")
@require_roles(*ALL_ROLES)
def get_site(sid):
    return ok(serialize_site(_get_site(sid)))


@bp.get("/disposal-sites")
@require_roles(*ALL_ROLES)
def list_sites():
    return list_response(store.sites, serialize_site, ["status"])


@bp.post("/disposal-sites/<sid>/close")
@require_roles("OwnerEngineer")
def close_site(sid):
    site = _get_site(sid)
    if site["status"] not in ("OPEN", "FULL"):
        raise ApiError(ERR_INVALID_STATE, "Only an OPEN or FULL site can be closed", 409)
    if any(
        t["disposal_site_id"] == sid and t["status"] == "REPORTED"
        for t in store.tickets.values()
    ):
        raise ApiError(
            ERR_INVALID_STATE, "Site has placement tickets in REPORTED", 409
        )
    site["status"] = "CLOSED"
    touch(site)
    return ok(serialize_site(site))


# --- PlacementTicket --------------------------------------------------------

@bp.post("/placement-tickets")
@require_roles("ContractorOps")
def create_ticket():
    body = get_body()
    # Existence (class 3): dredge_event_id then disposal_site_id.
    event_id = body.get("dredge_event_id")
    if event_id is not None and event_id not in store.events:
        raise ApiError(ERR_NOT_FOUND, "DredgeEvent not found", 404)
    site_id = body.get("disposal_site_id")
    if site_id is not None and site_id not in store.sites:
        raise ApiError(ERR_NOT_FOUND, "DisposalSite not found", 404)
    event_id = as_str(req_present(body, "dredge_event_id"), "dredge_event_id")
    site_id = as_str(req_present(body, "disposal_site_id"), "disposal_site_id")
    placed = parse_dt(req_present(body, "placed_utc"), "placed_utc")
    declared = as_int(req_present(body, "declared_volume_cy"), "declared_volume_cy")
    check(declared > 0, "declared_volume_cy must be > 0")
    event = store.events[event_id]
    site = store.sites[site_id]
    # State gate (class 6): event must be COMPLETED.
    if event["status"] != "COMPLETED":
        raise ApiError(ERR_EVENT_NOT_COMPLETED, "DredgeEvent is not COMPLETED", 409)
    # Referenced-entity state (class 11): site must be OPEN.
    if site["status"] != "OPEN":
        raise ApiError(ERR_DISPOSAL_SITE_NOT_OPEN, "DisposalSite is not OPEN", 409)
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "dredge_event_id": event_id,
            "disposal_site_id": site_id,
            "placed_utc": placed,
            "declared_volume_cy": declared,
            "witnessed_volume_cy": None,
            "reported_by_user_id": g.user_id,
            "in_situ_volume_cy": None,
            "status": "REPORTED",
            "_project_id": event["_project_id"],
        }
    )
    store.tickets[rec["id"]] = rec
    return ok(serialize_ticket(rec), 201)


def _get_ticket(tid):
    ticket = store.tickets.get(tid)
    if ticket is None:
        raise ApiError(ERR_NOT_FOUND, "PlacementTicket not found", 404)
    return ticket


@bp.get("/placement-tickets/<tid>")
@require_roles(*ALL_ROLES)
def get_ticket(tid):
    return ok(serialize_ticket(_get_ticket(tid)))


@bp.get("/placement-tickets")
@require_roles(*ALL_ROLES)
def list_tickets():
    return list_response(
        store.tickets, serialize_ticket, ["dredge_event_id", "disposal_site_id", "status"]
    )


@bp.post("/placement-tickets/<tid>/confirm")
@require_roles("SiteOperator")
def confirm_ticket(tid):
    ticket = _get_ticket(tid)
    body = get_body()
    # Shape (class 5): witnessed volume is the required input of confirm.
    witnessed = as_int(req_present(body, "witnessed_volume_cy"), "witnessed_volume_cy")
    check(witnessed > 0, "witnessed_volume_cy must be > 0")
    # State gate (class 6).
    if ticket["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, "Only a REPORTED ticket can be confirmed", 409)
    # Segregation of duties (class 8).
    if g.user_id == ticket["reported_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, "The ticket reporter cannot confirm it", 403
        )
    # Temporal (class 9): placed_utc inside an ISSUED permit CLOSED window of
    # the event's project at confirm time.
    project_id = ticket["_project_id"]
    if not any(
        p["project_id"] == project_id
        and p["status"] == "ISSUED"
        and p["window_start_utc"] <= ticket["placed_utc"] <= p["window_end_utc"]
        for p in store.permits.values()
    ):
        raise ApiError(
            ERR_PLACEMENT_OUT_OF_WINDOW,
            "placed_utc is outside every ISSUED permit window of the project",
            409,
        )
    # Capacity gate (class 10): exact fill allowed (<=).
    site = store.sites[ticket["disposal_site_id"]]
    if site["used_cy"] + Decimal(witnessed) > Decimal(site["capacity_cy"]):
        raise ApiError(
            ERR_DISPOSAL_CAPACITY_EXCEEDED,
            "Confirm would exceed the disposal site capacity",
            409,
        )
    # Effects: per-ticket in-situ rounding (pinned before any summation),
    # capacity debit, automatic OPEN -> FULL on exact fill.
    ticket["witnessed_volume_cy"] = witnessed
    ticket["in_situ_volume_cy"] = r2(Decimal(witnessed) / site["bulking_factor"])
    ticket["status"] = "CONFIRMED"
    touch(ticket)
    site["used_cy"] += Decimal(witnessed)
    if Decimal(site["capacity_cy"]) - site["used_cy"] == 0 and site["status"] == "OPEN":
        site["status"] = "FULL"
    touch(site)
    return ok(serialize_ticket(ticket))


@bp.post("/placement-tickets/<tid>/reject")
@require_roles("SiteOperator")
def reject_ticket(tid):
    ticket = _get_ticket(tid)
    if ticket["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, "Only a REPORTED ticket can be rejected", 409)
    if g.user_id == ticket["reported_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, "The ticket reporter cannot reject it", 403
        )
    ticket["status"] = "REJECTED"
    touch(ticket)
    return ok(serialize_ticket(ticket))


@bp.post("/placement-tickets/<tid>/void")
@require_roles("SiteOperator")
def void_ticket(tid):
    ticket = _get_ticket(tid)
    if ticket["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "Only a CONFIRMED ticket can be voided", 409)
    ticket["status"] = "VOIDED"
    touch(ticket)
    # Compensation of the confirm: restore capacity; a FULL site reopens.
    site = store.sites[ticket["disposal_site_id"]]
    site["used_cy"] -= Decimal(ticket["witnessed_volume_cy"])
    if site["status"] == "FULL" and Decimal(site["capacity_cy"]) - site["used_cy"] > 0:
        site["status"] = "OPEN"
    touch(site)
    return ok(serialize_ticket(ticket))
