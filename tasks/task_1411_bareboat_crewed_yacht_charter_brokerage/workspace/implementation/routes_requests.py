"""Routes: charter requests and the negotiation round (PRD §3.3)."""

from flask import Blueprint, g, request

from httpkit import (api_err, as_date, as_int, as_nonneg_int, as_number,
                     as_pos_int, body_json, get_or_404, req_field,
                     require_roles, respond_object, respond_paginated,
                     sort_created)
from serializers import ser_agreement, ser_request
from services import (MAX_NEGOTIATION_ROUNDS, RESUME_RANK, accept_cascade,
                      calendar_check, duplicate_request_check, offer_expiry,
                      resolve_offer_terms)
from store import clock, db, mutate, new_record
from util import date_obj

bp = Blueprint("requests", __name__)

TERMINAL_REQUEST_STATES = ("DECLINED", "EXPIRED", "CANCELLED")


def _party_or_403(req):
    """Caller must be the request's client (as Client) or its retail broker
    (as RetailBroker)."""
    if g.role == "Client":
        if g.user_id != req["client_id"]:
            raise api_err("ERR_FORBIDDEN", "Caller is not the request's client")
    elif g.role == "RetailBroker":
        if g.user_id != req["retail_broker_id"]:
            raise api_err(
                "ERR_FORBIDDEN", "Caller is not the request's retail broker"
            )
    else:
        raise api_err("ERR_FORBIDDEN", "Role not authorized for this endpoint")


def _occ_check(req, body):
    expected = as_int(
        req_field(body, "expected_charter_request_version"),
        "expected_charter_request_version",
    )
    if expected != req["version"]:
        raise api_err(
            "ERR_STALE_VERSION",
            "CharterRequest version has advanced; re-read before acting",
        )


def _lazy_expiry_check(req):
    """If the offer has lapsed, transition to EXPIRED and reject."""
    expires = req["offer_expires_at"]
    if expires is not None and clock.now() > expires:
        req["status"] = "EXPIRED"
        mutate(req)
        raise api_err("ERR_OFFER_EXPIRED", "The offer has expired")


def _create_request_record(client_id, yacht_id, start, end, guests,
                           retail_broker_id, rebooked_from):
    r = new_record()
    r.update({
        "client_id": client_id,
        "yacht_id": yacht_id,
        "retail_broker_id": retail_broker_id,
        "rebooked_from_request_id": rebooked_from,
        "start_date": start,
        "end_date": end,
        "guests_count": guests,
        "quoted_charter_fee_cents": None,
        "apa_pct": None,
        "gratuity_pledged_cents": None,
        "retail_pct_bps": None,
        "round_count": 0,
        "offer_expires_at": None,
        "status": "DRAFT",
    })
    db["charter_requests"][r["id"]] = r
    return r


@bp.route("/charter-requests", methods=["POST"])
def create_request():
    require_roles("Client", "RetailBroker")
    body = body_json()
    client_id = body.get("client_id")
    yacht_id = body.get("yacht_id")
    retail_in = body.get("retail_broker_id")

    # Ownership (tier 2): a Client creates only for themselves
    if g.role == "Client" and client_id is not None and client_id != g.user_id:
        raise api_err("ERR_FORBIDDEN", "client_id must be the calling client")

    # Existence (tier 3): body foreign keys
    if client_id is not None:
        get_or_404("clients", client_id, "Client")
    yacht = None
    if yacht_id is not None:
        yacht = get_or_404("yachts", yacht_id, "Yacht")
    if g.role == "Client" and retail_in is not None:
        get_or_404("brokers", retail_in, "Broker")

    # Segregation of duties (tier 5), ahead of the field-level gates
    effective_retail = g.user_id if g.role == "RetailBroker" else retail_in
    if (
        yacht is not None
        and effective_retail is not None
        and effective_retail == yacht["listing_central_agent_id"]
    ):
        raise api_err(
            "ERR_BROKER_CONFLICT_OF_INTEREST",
            "Retail broker may not also be the listing central agent",
        )

    # Field-level constraints (tier 7)
    client_id = req_field(body, "client_id")
    yacht_id = req_field(body, "yacht_id")
    start = as_date(req_field(body, "start_date"), "start_date")
    end = as_date(req_field(body, "end_date"), "end_date")
    if end <= start:
        raise api_err("ERR_INVALID_REQUEST", "end_date must be after start_date")
    guests = as_int(req_field(body, "guests_count"), "guests_count")
    if guests < 1:
        raise api_err("ERR_INVALID_REQUEST", "guests_count must be at least 1")
    if guests > yacht["capacity_berths"]:
        raise api_err(
            "ERR_CAPACITY_EXCEEDED", "guests_count exceeds yacht capacity_berths"
        )
    days = (date_obj(end) - date_obj(start)).days
    if days < yacht["min_charter_days"]:
        raise api_err(
            "ERR_CHARTER_DURATION_INVALID",
            "Charter length is below the yacht's min_charter_days",
        )
    duplicate_request_check(client_id, yacht_id, start, end)

    r = _create_request_record(client_id, yacht_id, start, end, guests,
                               effective_retail, None)
    return respond_object(ser_request(r), 201)


@bp.route("/charter-requests/<rid>", methods=["GET"])
def get_request(rid):
    r = get_or_404("charter_requests", rid, "CharterRequest")
    return respond_object(ser_request(r))


@bp.route("/charter-requests", methods=["GET"])
def list_requests():
    items = list(db["charter_requests"].values())
    for f in ("client_id", "yacht_id", "retail_broker_id",
              "rebooked_from_request_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    return respond_paginated([ser_request(r) for r in sort_created(items)])


@bp.route("/charter-requests/<rid>/submit", methods=["POST"])
def submit_request(rid):
    require_roles("Client", "RetailBroker")
    r = get_or_404("charter_requests", rid, "CharterRequest")
    _party_or_403(r)
    if r["status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE", "CharterRequest is not DRAFT")
    yacht = db["yachts"][r["yacht_id"]]
    if yacht["status"] != "LISTED":
        raise api_err("ERR_YACHT_NOT_LISTED", "Yacht is not LISTED")
    operator = db["operators"][yacht["operator_id"]]
    if operator["status"] != "ACTIVE":
        raise api_err("ERR_OPERATOR_SUSPENDED", "Operator is SUSPENDED")
    if yacht["charter_type"] == "BAREBOAT":
        client = db["clients"][r["client_id"]]
        if client["qualification_status"] != "QUALIFIED":
            raise api_err(
                "ERR_CLIENT_NOT_QUALIFIED", "Client is not QUALIFIED for bareboat"
            )
        if RESUME_RANK.get(client["resume_class"], -1) < RESUME_RANK[
            yacht["required_resume_class"]
        ]:
            raise api_err(
                "ERR_RESUME_CLASS_INSUFFICIENT",
                "Client resume class ranks below the yacht's requirement",
            )
    calendar_check(r["yacht_id"], r["start_date"], r["end_date"])
    duplicate_request_check(r["client_id"], r["yacht_id"], r["start_date"],
                            r["end_date"], exclude_id=r["id"])
    r["status"] = "SUBMITTED"
    mutate(r)
    return respond_object(ser_request(r))


@bp.route("/charter-requests/<rid>/offer", methods=["POST"])
def offer_request(rid):
    require_roles("CentralAgent")
    r = get_or_404("charter_requests", rid, "CharterRequest")
    yacht = db["yachts"][r["yacht_id"]]
    if g.user_id != yacht["listing_central_agent_id"]:
        raise api_err(
            "ERR_FORBIDDEN", "Caller is not the listing central agent for this yacht"
        )
    if r["status"] not in ("SUBMITTED", "COUNTERED"):
        raise api_err(
            "ERR_INVALID_STATE", "Offers issue only from SUBMITTED or COUNTERED"
        )
    # Operator standing is checked on the first offer only (PRD §3.3)
    if r["status"] == "SUBMITTED":
        operator = db["operators"][yacht["operator_id"]]
        if operator["status"] != "ACTIVE":
            raise api_err("ERR_OPERATOR_SUSPENDED", "Operator is SUSPENDED")
    body = body_json()
    fee_override = apa_override = gratuity_override = bps_override = None
    if body.get("quoted_charter_fee_cents") is not None:
        fee_override = as_pos_int(
            body["quoted_charter_fee_cents"], "quoted_charter_fee_cents"
        )
    if body.get("apa_pct") is not None:
        apa_override = as_number(body["apa_pct"], "apa_pct")
        if apa_override < 0:
            raise api_err("ERR_INVALID_REQUEST", "apa_pct must be non-negative")
    if body.get("gratuity_pledged_cents") is not None:
        gratuity_override = as_nonneg_int(
            body["gratuity_pledged_cents"], "gratuity_pledged_cents"
        )
    if body.get("retail_pct_bps") is not None:
        bps_override = as_int(body["retail_pct_bps"], "retail_pct_bps")
        if bps_override < 0 or bps_override > 10000:
            raise api_err(
                "ERR_INVALID_REQUEST", "retail_pct_bps must be between 0 and 10000"
            )
    fee, pct, gratuity, bps = resolve_offer_terms(
        yacht, r, fee_override, apa_override, gratuity_override, bps_override
    )
    r["quoted_charter_fee_cents"] = fee
    r["apa_pct"] = pct
    r["gratuity_pledged_cents"] = gratuity
    r["retail_pct_bps"] = bps
    from store import clock as _clock
    from datetime import timedelta
    r["offer_expires_at"] = _clock.now() + timedelta(days=7)
    r["status"] = "OFFERED"
    mutate(r)
    return respond_object(ser_request(r))


@bp.route("/charter-requests/<rid>/counter", methods=["POST"])
def counter_request(rid):
    require_roles("Client", "RetailBroker")
    r = get_or_404("charter_requests", rid, "CharterRequest")
    _party_or_403(r)
    if r["status"] != "OFFERED":
        raise api_err("ERR_INVALID_STATE", "CharterRequest is not OFFERED")
    body = body_json()
    _occ_check(r, body)
    _lazy_expiry_check(r)
    if r["round_count"] >= MAX_NEGOTIATION_ROUNDS:
        raise api_err(
            "ERR_NEGOTIATION_ROUND_LIMIT", "Negotiation round limit reached"
        )
    if body.get("counter_charter_fee_cents") is not None:
        as_pos_int(body["counter_charter_fee_cents"], "counter_charter_fee_cents")
    r["round_count"] += 1
    r["offer_expires_at"] = None
    r["status"] = "COUNTERED"
    mutate(r)
    return respond_object(ser_request(r))


@bp.route("/charter-requests/<rid>/accept", methods=["POST"])
def accept_request(rid):
    require_roles("Client", "RetailBroker")
    r = get_or_404("charter_requests", rid, "CharterRequest")
    _party_or_403(r)
    if r["status"] != "OFFERED":
        raise api_err("ERR_INVALID_STATE", "CharterRequest is not OFFERED")
    body = body_json()
    _occ_check(r, body)
    _lazy_expiry_check(r)
    # Final gate: calendar rules run once more against current blocks
    calendar_check(r["yacht_id"], r["start_date"], r["end_date"])
    agr = accept_cascade(r)
    return respond_object(ser_agreement(agr), 201)


@bp.route("/charter-requests/<rid>/decline", methods=["POST"])
def decline_request(rid):
    require_roles("Client", "RetailBroker")
    r = get_or_404("charter_requests", rid, "CharterRequest")
    _party_or_403(r)
    if r["status"] != "OFFERED":
        raise api_err("ERR_INVALID_STATE", "CharterRequest is not OFFERED")
    r["status"] = "DECLINED"
    mutate(r)
    return respond_object(ser_request(r))


@bp.route("/charter-requests/<rid>/rebook", methods=["POST"])
def rebook_request(rid):
    require_roles("Client", "RetailBroker")
    src = get_or_404("charter_requests", rid, "CharterRequest")
    _party_or_403(src)
    if src["status"] not in TERMINAL_REQUEST_STATES:
        raise api_err(
            "ERR_INVALID_STATE", "Rebook requires a terminal source request"
        )
    body = body_json()
    yacht_id = body.get("yacht_id")
    retail_in = body.get("retail_broker_id")
    yacht = None
    if yacht_id is not None:
        yacht = get_or_404("yachts", yacht_id, "Yacht")
    if g.role == "Client" and retail_in is not None:
        get_or_404("brokers", retail_in, "Broker")

    yacht_id = req_field(body, "yacht_id")
    start = as_date(req_field(body, "start_date"), "start_date")
    end = as_date(req_field(body, "end_date"), "end_date")
    if end <= start:
        raise api_err("ERR_INVALID_REQUEST", "end_date must be after start_date")
    guests = as_int(req_field(body, "guests_count"), "guests_count")
    if guests < 1:
        raise api_err("ERR_INVALID_REQUEST", "guests_count must be at least 1")
    # Duplicate guard (third enforcement point)
    duplicate_request_check(src["client_id"], yacht_id, start, end)

    effective_retail = g.user_id if g.role == "RetailBroker" else retail_in
    r = _create_request_record(src["client_id"], yacht_id, start, end, guests,
                               effective_retail, src["id"])
    return respond_object(ser_request(r), 201)
