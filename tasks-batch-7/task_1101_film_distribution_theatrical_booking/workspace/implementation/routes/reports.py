"""BoxOfficeReport endpoints."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success_object
from errors import (
    err_invalid_request, err_invalid_state, err_report_outside_window,
)
from services.core import (
    serialize_box_office_report, get_box_office_report, get_booking, get_distributor,
    new_entity_common, touch,
)
from services.settlement import get_or_create_provisional_settlement, recompute_provisional_settlement
from util import parse_dt, iso_from_dt
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("reports", __name__)


def _report_week_index(report_date_dt):
    """Map a report_date to its box-office week index: 7-day weeks anchored at the
    logical clock's startup default 2026-05-01T00:00:00Z (PRD §2.5 — week_epoch 0
    aligns with the week starting at the clock default)."""
    from util import DEFAULT_LOGICAL_CLOCK
    delta = report_date_dt - DEFAULT_LOGICAL_CLOCK
    return delta.days // 7


def _report_window_ok(distributor, report_date_dt):
    """PRD §3.6: the report date must fall within the distributor's current or prior
    week_epoch. week_epoch is a counter advanced only by the weekly close, so the
    window is keyed to the epoch (via the week index of the date), not to the
    logical clock. No prior epoch exists when week_epoch is 0."""
    idx = _report_week_index(report_date_dt)
    epoch = distributor["week_epoch"]
    if idx < 0:
        return False
    return (epoch - 1) <= idx <= epoch


@bp.route("/distributors/<did>/booking-agreements/<baid>/box-office-reports", methods=["POST"])
@require_roles("Exhibitor")
def create_report(did, baid, _user_id, _role):
    d = get_distributor(did)
    b = get_booking(did, baid)
    body = get_json_body()
    require_fields(body, ["report_date", "gross_cents", "admissions"])
    rd = parse_dt(body["report_date"])
    if rd is None:
        raise err_invalid_request("report_date must be ISO 8601")
    if not isinstance(body["gross_cents"], int) or body["gross_cents"] < 0:
        raise err_invalid_request("gross_cents must be non-negative integer")
    if not isinstance(body["admissions"], int) or body["admissions"] < 0:
        raise err_invalid_request("admissions must be non-negative integer")
    # 19 REPORT_OUTSIDE_WINDOW
    if not _report_window_ok(d, rd):
        raise err_report_outside_window()
    common = new_entity_common()
    r = {
        **common,
        "booking_agreement_id": baid,
        "report_date": iso_from_dt(rd),
        "gross_cents": body["gross_cents"],
        "admissions": body["admissions"],
        "week_index": None,  # stamped when locked
        "status": "DRAFT",
    }
    db.box_office_reports[r["id"]] = r
    # Trigger provisional settlement recompute
    s = get_or_create_provisional_settlement(b)
    if s:
        recompute_provisional_settlement(s)
    return success_object(serialize_box_office_report(r), 201)


@bp.route("/distributors/<did>/booking-agreements/<baid>/box-office-reports/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "SettlementClerk", "Auditor")
def read_report(did, baid, rid, _user_id, _role):
    return success_object(serialize_box_office_report(get_box_office_report(did, baid, rid)))


@bp.route("/distributors/<did>/booking-agreements/<baid>/box-office-reports", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "SettlementClerk", "Auditor")
def list_reports(did, baid, _user_id, _role):
    get_booking(did, baid)
    items = [r for r in db.box_office_reports.values() if r["booking_agreement_id"] == baid]
    filters = {}
    for k in ("status", "week_index", "booking_agreement_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_box_office_report, filters)


@bp.route("/distributors/<did>/booking-agreements/<baid>/box-office-reports/<rid>/submit", methods=["POST"])
@require_roles("Exhibitor")
def submit_report(did, baid, rid, _user_id, _role):
    b = get_booking(did, baid)
    r = get_box_office_report(did, baid, rid)
    if r["status"] != "DRAFT":
        raise err_invalid_state("Report must be DRAFT")
    if b["deal_status"] not in ("IN_PLAY", "HELD_OVER"):
        raise err_invalid_state("Booking must be IN_PLAY or HELD_OVER")
    rd = parse_dt(r["report_date"])
    if rd is not None:
        # PRD §3.6: the same window is re-checked on submit, against the
        # distributor's current epoch at submit time.
        d = get_distributor(did)
        if not _report_window_ok(d, rd):
            raise err_report_outside_window()
    r["status"] = "SUBMITTED"
    touch(r)
    s = get_or_create_provisional_settlement(b)
    if s:
        recompute_provisional_settlement(s)
    return success_object(serialize_box_office_report(r))


@bp.route("/distributors/<did>/booking-agreements/<baid>/box-office-reports/<rid>/void", methods=["POST"])
@require_roles("Exhibitor", "Booker")
def void_report(did, baid, rid, _user_id, _role):
    b = get_booking(did, baid)
    r = get_box_office_report(did, baid, rid)
    if r["status"] == "DRAFT":
        # Exhibitor only
        if _role != "Exhibitor":
            from errors import err_role_forbidden
            raise err_role_forbidden()
    elif r["status"] == "SUBMITTED":
        # Booker only, while settlement for this week is still PROVISIONAL
        if _role != "Booker":
            from errors import err_role_forbidden
            raise err_role_forbidden()
        # Find latest settlement for this week — need to infer week
        # For simplicity: any settlement for this booking still in PROVISIONAL
        # Check latest settlement (any week) is PROVISIONAL
        settlements = [s for s in db.settlements.values() if s["booking_agreement_id"] == b["id"]]
        if settlements:
            settlements.sort(key=lambda s: s["created_at"])
            latest = settlements[-1]
            if latest["status"] != "PROVISIONAL":
                raise err_invalid_state("Settlement no longer PROVISIONAL")
    else:
        raise err_invalid_state("Report must be DRAFT or SUBMITTED")
    r["status"] = "VOIDED"
    touch(r)
    # Recompute provisional settlement gross
    s = get_or_create_provisional_settlement(b)
    if s:
        recompute_provisional_settlement(s)
    return success_object(serialize_box_office_report(r))
