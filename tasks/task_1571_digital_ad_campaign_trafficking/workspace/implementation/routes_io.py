"""Routes: logical clock + insertion orders."""
from flask import Blueprint

from core import (
    db, envelope_ok, require_role, ANY_ROLE, get_body,
    req_str, req_int, req_enum, opt_decimal, req_date,
    err_not_found, err_invalid_state, stamp_new, touch,
    render_instant, parse_dt_value, err_invalid_request,
    Decimal,
)
from domain import io_view, get_io, line_items_of_io, cancel_line_item

bp = Blueprint("io", __name__)

BILLING_BASES = ("AGENCY_PLATFORM", "THIRD_PARTY_TAG", "LOWER_OF")
IO_ACTIONS = ("APPROVE", "ACTIVATE", "COMPLETE", "CANCEL")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("AdOpsManager")
    body = get_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise err_invalid_request("Field 'to_iso8601' is required")
    dt = parse_dt_value(raw, "to_iso8601")
    db.clock = dt
    return envelope_ok({"current_utc": render_instant(db.clock)}, status=200)


@bp.route("/insertion-orders", methods=["POST"])
def create_io():
    require_role("AdOpsManager")
    body = get_body()
    advertiser_name = req_str(body, "advertiser_name")
    total_budget_cents = req_int(body, "total_budget_cents", minimum=1)
    fs_raw, fs = req_date(body, "flight_start")
    fe_raw, fe = req_date(body, "flight_end")
    billing_basis = req_enum(body, "billing_basis", BILLING_BASES)
    vt_raw, vt_dec = opt_decimal(body, "viewability_threshold_pct",
                                 lo=Decimal(0), hi=Decimal(1),
                                 default_raw=0.70, default_dec=Decimal("0.70"))
    it_raw, it_dec = opt_decimal(body, "ivt_threshold_pct",
                                 lo=Decimal(0), hi=Decimal(1),
                                 default_raw=0.02, default_dec=Decimal("0.02"))
    if fe < fs:
        raise err_invalid_request("flight_end must be on or after flight_start")
    io = {
        "advertiser_name": advertiser_name,
        "total_budget_cents": total_budget_cents,
        "flight_start": fs_raw,
        "flight_end": fe_raw,
        "_flight_start": fs,
        "_flight_end": fe,
        "billing_basis": billing_basis,
        "viewability_threshold_pct": vt_raw,
        "ivt_threshold_pct": it_raw,
        "_v_threshold": vt_dec,
        "_i_threshold": it_dec,
        "status": "DRAFT",
    }
    stamp_new(io)
    db.insertion_orders[io["id"]] = io
    return envelope_ok(io_view(io), status=201)


@bp.route("/insertion-orders/<io_id>", methods=["GET"])
def get_one_io(io_id):
    require_role(*ANY_ROLE)
    io = get_io(io_id)
    if io is None:
        raise err_not_found("Insertion order not found")
    return envelope_ok(io_view(io), status=200)


@bp.route("/insertion-orders/<io_id>/transition", methods=["POST"])
def io_transition(io_id):
    require_role("AdOpsManager")
    body = get_body()
    action = req_enum(body, "action", IO_ACTIONS)
    io = get_io(io_id)
    if io is None:
        raise err_not_found("Insertion order not found")
    status = io["status"]

    if action == "APPROVE":
        if status != "DRAFT":
            raise err_invalid_state("APPROVE requires status DRAFT")
        if not any(li["status"] != "CANCELLED" for li in line_items_of_io(io["id"])):
            raise err_invalid_state("APPROVE requires at least one non-CANCELLED line item")
        io["status"] = "APPROVED"
    elif action == "ACTIVATE":
        if status != "APPROVED":
            raise err_invalid_state("ACTIVATE requires status APPROVED")
        if not any(li["status"] == "LIVE" for li in line_items_of_io(io["id"])):
            raise err_invalid_state("ACTIVATE requires at least one LIVE line item")
        io["status"] = "ACTIVE"
    elif action == "COMPLETE":
        if status != "ACTIVE":
            raise err_invalid_state("COMPLETE requires status ACTIVE")
        from core import today as _today
        lis = line_items_of_io(io["id"])
        if not (_today() > io["_flight_end"]):
            raise err_invalid_state("COMPLETE requires the current date to be after flight_end")
        if not all(li["status"] in ("COMPLETED", "CANCELLED") for li in lis):
            raise err_invalid_state("COMPLETE requires every line item to be COMPLETED or CANCELLED")
        io["status"] = "COMPLETED"
    elif action == "CANCEL":
        if status not in ("DRAFT", "APPROVED", "ACTIVE"):
            raise err_invalid_state("CANCEL not allowed from status %s" % status)
        for li in line_items_of_io(io["id"]):
            if li["status"] not in ("COMPLETED", "CANCELLED"):
                cancel_line_item(li)
        io["status"] = "CANCELLED"

    touch(io)
    return envelope_ok(io_view(io), status=200)
