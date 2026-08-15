"""VendorContract endpoints."""

from flask import Blueprint

from db import base_record, store, touch
from errors import (
    ApiError,
    ERR_CONTRACT_STREAM_OVERLAP,
    ERR_INVALID_STATE,
    ERR_REBATE_RATE_CAP_EXCEEDED,
    ERR_VENDOR_NOT_ACTIVE,
    ERR_WINDOW_INVALID,
    not_found,
)
from middleware import (
    no_input,
    ALL_ROLES,
    authenticate,
    check_unknown,
    f_date,
    f_enum,
    f_int,
    f_str,
    get_body,
)
from response import success_list, success_object
from services.lifecycle import pub_contract, reject_ticket
from util import (
    CONTRACT_STATUSES,
    MATERIAL_STREAMS,
    apply_filters,
    paginate,
    sort_items,
)

bp = Blueprint("contracts", __name__)


@bp.route("/contracts", methods=["POST"])
def create_contract():
    authenticate(["SustainabilityManager"])
    b = get_body()
    check_unknown(b, ["site_id", "vendor_id", "material_stream",
                      "rebate_per_ton_cents", "contamination_penalty_per_ton_cents",
                      "window_start", "window_end"])
    site_id = f_str(b, "site_id")
    vendor_id = f_str(b, "vendor_id")
    stream = f_enum(b, "material_stream", MATERIAL_STREAMS)
    rebate = f_int(b, "rebate_per_ton_cents")
    penalty = f_int(b, "contamination_penalty_per_ton_cents")
    ws = f_date(b, "window_start")
    we = f_date(b, "window_end")

    if site_id not in store.sites:
        raise not_found("Site not found")
    if vendor_id not in store.vendors:
        raise not_found("Vendor not found")

    # Closed interval: window_start must be on or before window_end.
    if ws > we:
        raise ApiError(ERR_WINDOW_INVALID, 422,
                       "window_start must be on or before window_end")

    rec = base_record({
        "site_id": site_id,
        "vendor_id": vendor_id,
        "material_stream": stream,
        "rebate_per_ton_cents": rebate,
        "contamination_penalty_per_ton_cents": penalty,
        "window_start": ws,
        "window_end": we,
        "status": "DRAFT",
    })
    store.contracts[rec["id"]] = rec
    return success_object(pub_contract(rec), 201)


@bp.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    authenticate(ALL_ROLES)
    rec = store.contracts.get(contract_id)
    if rec is None:
        raise not_found("Contract not found")
    return success_object(pub_contract(rec))


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    authenticate(ALL_ROLES)
    items = apply_filters(store.contracts.values(), [
        ("site_id", "site_id", None),
        ("vendor_id", "vendor_id", None),
        ("status", "status", CONTRACT_STATUSES),
        ("material_stream", "material_stream", MATERIAL_STREAMS),
    ])
    page, meta = paginate(sort_items(items))
    return success_list([pub_contract(c) for c in page], meta)


@bp.route("/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    authenticate(["SustainabilityManager"])
    no_input(get_body())
    c = store.contracts.get(contract_id)
    if c is None:
        raise not_found("Contract not found")

    # Gate 1: must be DRAFT.
    if c["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Contract is not DRAFT")
    # Gate 2: no overlapping ACTIVE contract for same site+stream (closed
    # intervals; touching at an endpoint counts as overlap).
    for o in store.contracts.values():
        if (o["id"] != c["id"] and o["status"] == "ACTIVE"
                and o["site_id"] == c["site_id"]
                and o["material_stream"] == c["material_stream"]
                and o["window_start"] <= c["window_end"]
                and c["window_start"] <= o["window_end"]):
            raise ApiError(ERR_CONTRACT_STREAM_OVERLAP, 409,
                           "An ACTIVE contract overlaps this site and stream window")
    # Gate 3: vendor must be ACTIVE.
    vendor = store.vendors.get(c["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_NOT_ACTIVE, 409, "Vendor is not ACTIVE")
    # Gate 4: fiscal cap.
    site = store.sites.get(c["site_id"])
    if site is not None and c["rebate_per_ton_cents"] > site["max_rebate_rate_per_ton_cents"]:
        raise ApiError(ERR_REBATE_RATE_CAP_EXCEEDED, 422,
                       "rebate_per_ton_cents exceeds the site policy cap")

    c["status"] = "ACTIVE"
    touch(c)
    return success_object(pub_contract(c))


@bp.route("/contracts/<contract_id>/terminate", methods=["POST"])
def terminate_contract(contract_id):
    authenticate(["SustainabilityManager"])
    no_input(get_body())
    c = store.contracts.get(contract_id)
    if c is None:
        raise not_found("Contract not found")
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE or SUSPENDED contract can be terminated")

    c["status"] = "TERMINATED"
    touch(c)
    for t in store.tickets.values():
        if t["contract_id"] == c["id"] and t["validation_status"] == "PENDING":
            reject_ticket(t, "CONTRACT_TERMINATED")
    return success_object(pub_contract(c))
