"""PortCall endpoints: CRUD, ops transitions, and the cancel/sail cascades."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.domain import DA_EDITABLE_STATUSES
from services.serializers import serialize, serialize_many
from utils import (days_between, is_int, new_entity, paginate, pagination_args,
                   parse_dt, sort_created, touch)

bp = Blueprint("port_calls", __name__)


def _get_call_or_404(cid):
    call = domain.get("port_calls", cid)
    if call is None:
        not_found("port call")
    return call


@bp.post("/port-calls")
def create_port_call():
    require_roles(["AgencyOps"])
    body = request.get_json(silent=True) or {}
    # Stage 4: payload reference existence
    principal_id = body.get("principal_id")
    principal = None
    if isinstance(principal_id, str):
        principal = domain.get("principals", principal_id)
        if principal is None:
            not_found("principal")
    # Stage 10: principal must be ACTIVE
    if principal is not None and principal["status"] != "ACTIVE":
        raise_err("ERR_PRINCIPAL_SUSPENDED", "The principal is not ACTIVE")
    # Stage 11: credit gate on forward exposure
    if principal is not None and principal["credit_limit_cents"] != 0:
        forward, _cash = domain.principal_exposure(principal["id"])
        if forward >= principal["credit_limit_cents"]:
            raise_err("ERR_CREDIT_LIMIT_EXCEEDED",
                      "Forward exposure meets or exceeds the principal credit limit")
    # Stage 13: request shape
    eta = parse_dt(body.get("eta"))
    etd = parse_dt(body.get("etd"))
    hazmat = body.get("hazmat_flag", False)
    if (principal is None
            or not isinstance(body.get("vessel_name"), str) or not body.get("vessel_name")
            or not isinstance(body.get("imo_number"), str) or not body.get("imo_number")
            or not is_int(body.get("vessel_gt")) or body.get("vessel_gt", 0) <= 0
            or not isinstance(body.get("flag_state"), str) or not body.get("flag_state")
            or not isinstance(body.get("port_code"), str) or not body.get("port_code")
            or eta is None or etd is None or etd <= eta
            or not isinstance(body.get("cargo_description"), str)
            or not isinstance(hazmat, bool)):
        invalid_request("invalid port call payload")
    ent = new_entity("port_calls", {
        "principal_id": principal_id,
        "vessel_name": body["vessel_name"],
        "imo_number": body["imo_number"],
        "vessel_gt": body["vessel_gt"],
        "flag_state": body["flag_state"],
        "port_code": body["port_code"],
        "eta": eta,
        "etd": etd,
        "hazmat_flag": hazmat,
        "cargo_description": body["cargo_description"],
        "ops_status": "NOMINATED",
        "actual_arrival_at": None,
        "actual_sailed_at": None,
        "alongside_days_estimated": days_between(eta, etd),
        "alongside_days_actual": None,
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/port-calls")
def list_port_calls():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("port_calls"))
    for param, field in (("principal_id", "principal_id"),
                         ("ops_status", "ops_status"),
                         ("port_code", "port_code")):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[field] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/port-calls/<cid>")
def get_port_call(cid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_call_or_404(cid)))


@bp.patch("/port-calls/<cid>")
def patch_port_call(cid):
    require_roles(["AgencyOps"])
    call = _get_call_or_404(cid)
    body = request.get_json(silent=True) or {}
    # Stage 6: phase restriction
    if call["ops_status"] not in ("NOMINATED", "PRE_ARRIVAL_FILED"):
        invalid_state("Port call schedule may only be patched while NOMINATED or PRE_ARRIVAL_FILED")
    # Stage 12: optimistic concurrency
    expected = body.get("expected_port_call_version")
    if expected is not None and expected != call["version"]:
        raise_err("ERR_STALE_VERSION", "expected_port_call_version does not match the current version")
    # Stage 13: shape of supplied fields
    new_eta = call["eta"]
    new_etd = call["etd"]
    if "eta" in body:
        new_eta = parse_dt(body.get("eta"))
        if new_eta is None:
            invalid_request("eta must be an ISO-8601 datetime")
    if "etd" in body:
        new_etd = parse_dt(body.get("etd"))
        if new_etd is None:
            invalid_request("etd must be an ISO-8601 datetime")
    if new_etd <= new_eta:
        invalid_request("etd must be strictly later than eta")
    if "vessel_gt" in body and (not is_int(body["vessel_gt"]) or body["vessel_gt"] <= 0):
        invalid_request("vessel_gt must be a positive integer")
    if "hazmat_flag" in body and not isinstance(body["hazmat_flag"], bool):
        invalid_request("hazmat_flag must be a boolean")
    if "cargo_description" in body and not isinstance(body["cargo_description"], str):
        invalid_request("cargo_description must be a string")
    if expected is None:
        invalid_request("expected_port_call_version is required")
    # Apply
    if "eta" in body:
        call["eta"] = new_eta
    if "etd" in body:
        call["etd"] = new_etd
    if "cargo_description" in body:
        call["cargo_description"] = body["cargo_description"]
    if "hazmat_flag" in body:
        call["hazmat_flag"] = body["hazmat_flag"]
    if "vessel_gt" in body:
        call["vessel_gt"] = body["vessel_gt"]
    call["alongside_days_estimated"] = days_between(call["eta"], call["etd"])
    touch(call)
    # Estimate re-derivation on the pro-forma account, when one exists
    da = domain.current_da_for_call(call["id"])
    if da is not None and da["status"] == "PRO_FORMA":
        for line in domain.lines_of_da(da["id"]):
            if line["source_type"] == "TARIFF" and line["category"] == "PORT_DUES":
                tariff = domain.get("tariffs", line["tariff_id"])
                if tariff is not None:
                    line["estimated_cents"] = domain.port_dues_estimate(tariff, call)
                    touch(line)
        domain.recompute_da_totals(da)
    return ok_object(serialize(call))


@bp.post("/port-calls/<cid>/file-pre-arrival")
def file_pre_arrival(cid):
    require_roles(["AgencyOps"])
    call = _get_call_or_404(cid)
    if call["ops_status"] != "NOMINATED":
        invalid_state("Pre-arrival may only be filed from NOMINATED")
    # Temporal gate: no later than eta - 24h
    if db.now() > call["eta"] - timedelta(hours=24):
        raise_err("ERR_PRE_ARRIVAL_DEADLINE_MISSED",
                  "The pre-arrival filing deadline (eta - 24h) has passed")
    # Notification coverage: one of each type SUBMITTED or ACKNOWLEDGED
    covered = set()
    for n in domain.all_of("authority_notifications"):
        if n["port_call_id"] == cid and n["status"] in ("SUBMITTED", "ACKNOWLEDGED"):
            covered.add(n["authority_type"])
    if not domain.AUTHORITY_TYPES.issubset(covered):
        raise_err("ERR_NOTIFICATIONS_OUTSTANDING",
                  "Notifications of all four authority types must be SUBMITTED or ACKNOWLEDGED")
    call["ops_status"] = "PRE_ARRIVAL_FILED"
    touch(call)
    return ok_object(serialize(call))


@bp.post("/port-calls/<cid>/grant-clearance")
def grant_clearance(cid):
    require_roles(["PortAuthority"])
    call = _get_call_or_404(cid)
    if call["ops_status"] != "PRE_ARRIVAL_FILED":
        invalid_state("Clearance may only be granted from PRE_ARRIVAL_FILED")
    notes = [n for n in domain.all_of("authority_notifications") if n["port_call_id"] == cid]
    covered = {n["authority_type"] for n in notes if n["status"] == "ACKNOWLEDGED"}
    if (not domain.AUTHORITY_TYPES.issubset(covered)
            or any(n["status"] != "ACKNOWLEDGED" for n in notes)):
        raise_err("ERR_NOTIFICATIONS_OUTSTANDING",
                  "Every authority notification must be ACKNOWLEDGED, one per type")
    call["ops_status"] = "CLEARED_TO_ENTER"
    touch(call)
    return ok_object(serialize(call))


@bp.post("/port-calls/<cid>/record-arrival")
def record_arrival(cid):
    require_roles(["AgencyOps"])
    call = _get_call_or_404(cid)
    body = request.get_json(silent=True) or {}
    window = None
    bw_id = body.get("berth_window_id")
    if isinstance(bw_id, str):
        window = domain.get("berth_windows", bw_id)
        if window is None:
            not_found("berth window")
    if call["ops_status"] != "CLEARED_TO_ENTER":
        invalid_state("Arrival may only be recorded from CLEARED_TO_ENTER")
    if window is not None and window["port_call_id"] != cid:
        raise_err("ERR_BERTH_WINDOW_MISMATCH", "The berth window belongs to a different port call")
    if window is not None and window["status"] != "OCCUPIED":
        raise_err("ERR_BERTH_NOT_OCCUPIED", "The referenced berth window is not OCCUPIED")
    if window is None:
        invalid_request("berth_window_id is required")
    call["actual_arrival_at"] = db.now()
    call["ops_status"] = "ALONGSIDE"
    touch(call)
    return ok_object(serialize(call))


@bp.post("/port-calls/<cid>/record-sailing")
def record_sailing(cid):
    require_roles(["AgencyOps"])
    call = _get_call_or_404(cid)
    body = request.get_json(silent=True) or {}
    window = None
    bw_id = body.get("berth_window_id")
    if isinstance(bw_id, str):
        window = domain.get("berth_windows", bw_id)
        if window is None:
            not_found("berth window")
    # Stage 6: state
    if call["ops_status"] != "ALONGSIDE":
        invalid_state("Sailing may only be recorded from ALONGSIDE")
    # Stage 7: safety gate
    for case in domain.all_of("husbandry_cases"):
        if (case["port_call_id"] == cid and case["severity"] == "CRITICAL"
                and case["status"] in ("OPEN", "IN_TREATMENT")
                and not case["departure_waiver_granted"]):
            raise_err("ERR_OPEN_CRITICAL_HUSBANDRY",
                      "An unwaived open CRITICAL husbandry case blocks sailing")
    # Stage 9: berth / crew / cargo / DA gates
    if window is not None and window["port_call_id"] != cid:
        raise_err("ERR_BERTH_WINDOW_MISMATCH", "The berth window belongs to a different port call")
    if window is not None and window["status"] != "OCCUPIED":
        raise_err("ERR_BERTH_NOT_OCCUPIED", "The referenced berth window is not OCCUPIED")
    domain.lazy_expire_all_crew()
    for crew in domain.all_of("crew_changes"):
        if (crew["port_call_id"] == cid and crew["status"] in
                ("REQUESTED", "DOCS_VERIFIED", "VISA_PENDING", "VISA_GRANTED", "PASS_EXPIRED")):
            raise_err("ERR_OPEN_CREW_CHANGES", "A crew change in a blocking status remains open")
    for doc in domain.all_of("cargo_documents"):
        if doc["port_call_id"] == cid and doc["status"] == "ON_HOLD":
            raise_err("ERR_CARGO_DOCS_ON_HOLD", "A cargo document is ON_HOLD")
    da = domain.current_da_for_call(cid)
    if da is None or da["status"] not in ("SENT_TO_PRINCIPAL", "FUNDED", "FINAL", "DISPUTED", "SETTLED"):
        raise_err("ERR_DA_NOT_SENT", "No sent disbursement account exists for this call")
    # Stage 11: funding gate
    net = da["advances_received_cents"] - da["advances_refunded_cents"]
    if net < da["advance_required_cents"]:
        raise_err("ERR_FUNDING_SHORTFALL", "Net funding is below advance_required_cents")
    if window is None:
        invalid_request("berth_window_id is required")
    # Effects
    now = db.now()
    call["actual_sailed_at"] = now
    call["alongside_days_actual"] = days_between(call["actual_arrival_at"], now)
    call["ops_status"] = "SAILED"
    touch(call)
    # Cascade link 1: release the berth window
    window["status"] = "RELEASED"
    window["released_at"] = now
    touch(window)
    # Cascade link 2: actualize the TARIFF PORT_DUES line via the FINAL variant
    for line in domain.lines_of_da(da["id"]):
        if line["source_type"] == "TARIFF" and line["category"] == "PORT_DUES":
            tariff = domain.published_tariff(call["port_code"], "PORT_DUES")
            if tariff is None:
                tariff = domain.get("tariffs", line["tariff_id"])
            if tariff is not None:
                line["actual_cents"] = domain.port_dues_final(tariff, call)
                line["status"] = "ACTUALIZED"
                touch(line)
    # Cascade link 3: recompute totals (a PRO_FORMA account is not advanced)
    domain.recompute_da_totals(da)
    return ok_object(serialize(call))


@bp.post("/port-calls/<cid>/close")
def close_port_call(cid):
    require_roles(["AgencyFinance"])
    call = _get_call_or_404(cid)
    if call["ops_status"] != "SAILED":
        invalid_state("Only a SAILED port call can be closed")
    da = domain.current_da_for_call(cid)
    if da is None or da["status"] != "SETTLED":
        raise_err("ERR_DA_NOT_SETTLED", "The disbursement account is not SETTLED")
    call["ops_status"] = "CLOSED"
    touch(call)
    return ok_object(serialize(call))


@bp.post("/port-calls/<cid>/cancel")
def cancel_port_call(cid):
    require_roles(["AgencyOps", "AgencyAdmin"])
    call = _get_call_or_404(cid)
    if call["ops_status"] not in ("NOMINATED", "PRE_ARRIVAL_FILED", "CLEARED_TO_ENTER", "ALONGSIDE"):
        invalid_state("The port call cannot be cancelled from its current state")
    domain.lazy_expire_all_crew()
    # Cascade link 1: child state transitions
    for window in domain.all_of("berth_windows"):
        if window["port_call_id"] == cid and window["status"] in ("REQUESTED", "CONFIRMED"):
            window["status"] = "CANCELLED"
            touch(window)
    for note in domain.all_of("authority_notifications"):
        if note["port_call_id"] == cid and note["status"] in ("DRAFT", "SUBMITTED", "REJECTED"):
            note["status"] = "WITHDRAWN"
            touch(note)
    for crew in domain.all_of("crew_changes"):
        if (crew["port_call_id"] == cid and crew["status"] in
                ("REQUESTED", "DOCS_VERIFIED", "VISA_PENDING", "VISA_GRANTED",
                 "SHORE_PASS_ISSUED", "PASS_EXPIRED")):
            crew["status"] = "CANCELLED"
            touch(crew)
    reversed_refs = []
    for po in domain.all_of("purchase_orders"):
        if po["port_call_id"] == cid and po["status"] in ("DRAFT", "SENT", "ACKNOWLEDGED"):
            po["status"] = "CANCELLED"
            touch(po)
            reversed_refs.append("PurchaseOrder:%s" % po["id"])
    for so in domain.all_of("service_orders"):
        if so["port_call_id"] == cid and so["status"] in ("ORDERED", "CONFIRMED"):
            so["status"] = "CANCELLED"
            so["cancellation_fee_cents"] = 0
            touch(so)
            reversed_refs.append("ServiceOrder:%s" % so["id"])
    # Cascade link 2: reverse mirrored DA lines
    da = domain.current_da_for_call(cid)
    if da is not None:
        for ref in reversed_refs:
            line = domain.mirror_line(da["id"], ref)
            if line is not None and line["estimated_cents"] != 0:
                line["estimated_cents"] = 0
                touch(line)
        # Cascade link 3: totals recomputed; funding gates re-derive
        domain.recompute_da_totals(da)
    call["ops_status"] = "CANCELLED"
    touch(call)
    return ok_object(serialize(call))
