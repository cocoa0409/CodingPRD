"""Quote-request lifecycle: file → quote → accept|reject."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_QUOTE_EXPIRED,
    ERR_QUOTE_NOT_OPEN,
    ERR_QUOTE_NOT_QUOTED,
    ERR_QUOTE_REQUEST_NOT_FOUND,
    ERR_RATE_CONTRACT_NOT_FOUND,
    ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED,
    ERR_SHIPPER_NOT_FOUND,
    ERR_SHIPPER_SUSPENDED,
)
from ..helpers import (
    check_version,
    ensure_shipper_self_access,
    get_body,
    get_brokerage_or_404,
    get_scoped,
    optional_field,
    require_field,
    require_iso,
)
from ..services.calc import quote_linehaul
from ..services.quotes import expire_quotes
from ..store import store
from ..timeutil import iso_now, parse_iso


quote_requests_bp = Blueprint("quote_requests", __name__, url_prefix="/brokerages")


VALID_EQUIPMENT = {"DRY_VAN", "REEFER", "FLATBED"}


@quote_requests_bp.post("/<brokerage_id>/shippers/<shipper_id>/quote-requests")
@require_auth(["ShipperUser"])
def file_quote_request(brokerage_id, shipper_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        s = get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ensure_shipper_self_access(shipper_id)

        if s.get("status") != "ACTIVE":
            raise ApiError(ERR_SHIPPER_SUSPENDED, 409, "Shipper is suspended.")

        origin_zip = require_field(body, "origin_zip", str)
        destination_zip = require_field(body, "destination_zip", str)
        equipment_type = require_field(body, "equipment_type", str)
        if equipment_type not in VALID_EQUIPMENT:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid equipment_type.")
        pickup_start = require_iso(body, "pickup_window_start")
        pickup_end = require_iso(body, "pickup_window_end")
        if pickup_end <= pickup_start:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "pickup_window_end must be strictly after pickup_window_start.",
            )

        rate_contract_id = optional_field(body, "rate_contract_id", str, default=None)
        if rate_contract_id is not None:
            # Existence check is deferred to /quote — body-referenced id validation
            # at filing keeps this endpoint forgiving when the broker hasn't yet
            # established a contract.  PRD §2.8 allows body-id validation at use.
            pass

        q = {
            "shipper_id": shipper_id,
            "brokerage_id": brokerage_id,
            "origin_zip": origin_zip,
            "destination_zip": destination_zip,
            "equipment_type": equipment_type,
            "pickup_window_start": iso_now(pickup_start),
            "pickup_window_end": iso_now(pickup_end),
            "rate_contract_id": rate_contract_id,
            "rate_source": None,
            "quoted_linehaul_cents": None,
            "status": "OPEN",
        }
        store.stamp_create(q)
        store.quote_requests[q["id"]] = q
    return ok_object(q, status=201)


@quote_requests_bp.get("/<brokerage_id>/shippers/<shipper_id>/quote-requests/<quote_id>")
@require_auth(["BrokerOps", "ShipperUser"])
def get_quote_request(brokerage_id, shipper_id, quote_id):
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ensure_shipper_self_access(shipper_id)
        q = get_scoped(store.quote_requests, quote_id, brokerage_id, ERR_QUOTE_REQUEST_NOT_FOUND)
        if q.get("shipper_id") != shipper_id:
            raise ApiError(ERR_QUOTE_REQUEST_NOT_FOUND, 404, "Quote request not found.")
    return ok_object(q)


@quote_requests_bp.post("/<brokerage_id>/shippers/<shipper_id>/quote-requests/<quote_id>/quote")
@require_auth(["BrokerOps"])
def broker_quote(brokerage_id, shipper_id, quote_id):
    body = get_body()
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        s = get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        q = get_scoped(store.quote_requests, quote_id, brokerage_id, ERR_QUOTE_REQUEST_NOT_FOUND)
        if q.get("shipper_id") != shipper_id:
            raise ApiError(ERR_QUOTE_REQUEST_NOT_FOUND, 404, "Quote request not found.")
        check_version(q, body)

        # PRD §3.1 / §3.5: quote-expiry sweep runs ONLY on clock-advance or
        # the standalone admin /_sweep call — not on every operation.  No
        # passive sweep here.
        clock_now = parse_iso(bk["clock_now_iso"])

        if q.get("status") != "OPEN":
            raise ApiError(ERR_QUOTE_NOT_OPEN, 409, "Quote request not in OPEN.")

        if s.get("status") != "ACTIVE":
            raise ApiError(ERR_SHIPPER_SUSPENDED, 409, "Shipper is suspended.")

        # If a rate_contract_id was specified at filing, ensure it exists in
        # this brokerage now (body-ref existence — PRD §2.8 priority 4).
        rcid = q.get("rate_contract_id")
        if rcid is not None:
            r = store.rate_contracts.get(rcid)
            if r is None or r.get("brokerage_id") != brokerage_id:
                raise ApiError(ERR_RATE_CONTRACT_NOT_FOUND, 404, "RateContract not found.")

        rate_source, quoted_cents = quote_linehaul(quote=q, brokerage=bk, clock_now=clock_now)
        q["rate_source"] = rate_source
        q["quoted_linehaul_cents"] = int(quoted_cents)
        q["status"] = "QUOTED"
        store.bump(q)
    return ok_object(q)


@quote_requests_bp.post("/<brokerage_id>/shippers/<shipper_id>/quote-requests/<quote_id>/accept")
@require_auth(["ShipperUser"])
def accept_quote(brokerage_id, shipper_id, quote_id):
    body = get_body()
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        s = get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ensure_shipper_self_access(shipper_id)
        q = get_scoped(store.quote_requests, quote_id, brokerage_id, ERR_QUOTE_REQUEST_NOT_FOUND)
        if q.get("shipper_id") != shipper_id:
            raise ApiError(ERR_QUOTE_REQUEST_NOT_FOUND, 404, "Quote request not found.")
        check_version(q, body)

        # PRD §3.1 / §3.5: quote-expiry sweep runs ONLY on clock-advance or
        # the standalone admin /_sweep call.  At /accept we still consult
        # the clock for the expiry check (priority 16) but we do not mutate
        # status here.
        clock_now = parse_iso(bk["clock_now_iso"])

        if q.get("status") != "QUOTED":
            raise ApiError(ERR_QUOTE_NOT_QUOTED, 409, "Quote request not in QUOTED.")

        # Validation order per PRD §2.9:
        # priority 15 = credit-limit, priority 16 = quote-expiry. So credit
        # is evaluated *before* expiry.
        outstanding = int(s.get("outstanding_invoiced_cents", 0))
        linehaul = int(q.get("quoted_linehaul_cents", 0))
        credit_limit = int(s.get("credit_limit_cents", 0))
        if outstanding + linehaul > credit_limit:
            raise ApiError(
                ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED,
                402,
                "Shipper credit limit exceeded.",
            )

        if clock_now > parse_iso(q["pickup_window_end"]):
            raise ApiError(ERR_QUOTE_EXPIRED, 409, "Quote pickup window has passed.")

        q["status"] = "ACCEPTED"
        store.bump(q)
    return ok_object(q)


@quote_requests_bp.post("/<brokerage_id>/shippers/<shipper_id>/quote-requests/<quote_id>/reject")
@require_auth(["ShipperUser"])
def reject_quote(brokerage_id, shipper_id, quote_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ensure_shipper_self_access(shipper_id)
        q = get_scoped(store.quote_requests, quote_id, brokerage_id, ERR_QUOTE_REQUEST_NOT_FOUND)
        if q.get("shipper_id") != shipper_id:
            raise ApiError(ERR_QUOTE_REQUEST_NOT_FOUND, 404, "Quote request not found.")
        check_version(q, body)

        if q.get("status") != "QUOTED":
            raise ApiError(ERR_QUOTE_NOT_QUOTED, 409, "Quote request not in QUOTED.")
        q["status"] = "REJECTED"
        store.bump(q)
    return ok_object(q)
