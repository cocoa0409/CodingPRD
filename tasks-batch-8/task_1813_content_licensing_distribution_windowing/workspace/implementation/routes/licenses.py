"""License agreements: direct deals, lifecycle, revenue reports (PRD §3.6, §3.8)."""
from flask import Blueprint, request

from auth import (
    check_buyer_owns,
    require_roles,
    ROLE_RIGHTS_MANAGER,
    ROLE_PLATFORM_BUYER,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
)
from domain import (
    FEE_MODELS,
    PRORATION_MODES,
    book_report,
    check_conflicts,
    create_license,
    create_notice,
    derive_holdback_until,
    guaranteed_value,
    list_page,
    ser_license,
    ser_report,
    terminate_license,
    validate_fee_structure,
)
from errors import (
    err,
    ERR_LICENSE_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_PLATFORM_NOT_FOUND,
    ERR_SLOT_NOT_AVAILABLE,
    ERR_WINDOW_OUTSIDE_RIGHTS,
    ERR_LICENSE_NOT_EXECUTABLE,
    ERR_LICENSE_NOT_STARTED,
    ERR_DELIVERY_INCOMPLETE,
    ERR_LICENSE_NOT_EXTENDABLE,
    ERR_LICENSE_ALREADY_TERMINAL,
    ERR_LICENSE_NOT_REPORTABLE,
    ERR_STALE_VERSION,
    ERR_REPORT_PERIOD_FUTURE,
    ERR_NONPOSITIVE_REVENUE,
    ERR_FORBIDDEN,
)
from response import ok_list, ok_object
from store import DB, mutate
from util import CLOCK
from validate import (
    check_window_order,
    field_bool,
    field_dt,
    field_enum,
    field_int,
    field_num,
    field_str,
    json_body,
)

bp = Blueprint("licenses", __name__)

_READERS = (
    ROLE_RIGHTS_MANAGER,
    ROLE_PLATFORM_BUYER,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
)


def _get_license_or_404(lid):
    rec = DB.get("licenses", lid)
    if rec is None:
        err(ERR_LICENSE_NOT_FOUND, "referenced license does not exist")
    return rec


@bp.route("/licensing/license-agreements", methods=["POST"])
def create_direct_license():
    require_roles(ROLE_RIGHTS_MANAGER)
    body = json_body()
    slot_id = field_str(body, "slot_id")
    platform_id = field_str(body, "platform_id")
    license_start = field_dt(body, "license_start")
    license_end = field_dt(body, "license_end")
    check_window_order(license_start, license_end, "license window")
    exclusive = field_bool(body, "exclusive")
    fee_model = field_enum(body, "fee_model", FEE_MODELS)
    flat_fee_cents = field_int(body, "flat_fee_cents", required=False, default=0)
    revenue_share_pct = field_num(body, "revenue_share_pct", required=False, default=0)
    minimum_guarantee_cents = field_int(body, "minimum_guarantee_cents", required=False, default=0)
    proration_mode = field_enum(
        body, "proration_mode", PRORATION_MODES, required=False, default="DAILY_PRORATION"
    )

    # Existence (body ids in declaration order): slot, then platform.
    slot = DB.get("slots", slot_id)
    if slot is None:
        err(ERR_SLOT_NOT_FOUND, "referenced rights slot does not exist")
    if DB.get("platforms", platform_id) is None:
        err(ERR_PLATFORM_NOT_FOUND, "referenced platform does not exist")

    # State: the slot must not be WITHDRAWN or EXPIRED (ENCUMBERED is allowed).
    if slot["slot_status"] in ("WITHDRAWN", "EXPIRED"):
        err(ERR_SLOT_NOT_AVAILABLE, "slot is not available for licensing")

    # Temporal: window containment in the slot's rights period.
    if not (slot["sellable_from"] <= license_start and license_end <= slot["sellable_to"]):
        err(ERR_WINDOW_OUTSIDE_RIGHTS, "license window is outside the slot's rights period")

    # Constraint: same-cell exclusivity, then cross-window holdback.
    check_conflicts(slot, license_start, license_end, slot["window_type"], exclusive)

    # Fiscal: fee structure; non-applicable fee fields coerce to 0.
    flat, share, mg = validate_fee_structure(
        fee_model, flat_fee_cents, revenue_share_pct, minimum_guarantee_cents
    )

    lic = create_license(
        slot,
        platform_id,
        license_start,
        license_end,
        exclusive,
        fee_model,
        flat,
        share,
        mg,
        proration_mode,
        package_id=None,
        allocated_fee_cents=guaranteed_value(fee_model, flat, mg),
    )
    return ok_object(ser_license(lic), status=201)


@bp.route("/licensing/license-agreements", methods=["GET"])
def list_licenses():
    user_id, role = require_roles(*_READERS)
    if role == ROLE_PLATFORM_BUYER:
        supplied = request.args.get("platform_id")
        if supplied is not None and supplied != user_id:
            err(ERR_FORBIDDEN, "PlatformBuyer may only list its own platform's licenses")
        platform_filter = user_id
    else:
        platform_filter = request.args.get("platform_id")
    records = DB.all("licenses")
    if platform_filter is not None:
        records = [l for l in records if l["platform_id"] == platform_filter]
    for param in ("slot_id", "package_id", "license_status"):
        v = request.args.get(param)
        if v is not None:
            records = [l for l in records if l[param] == v]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_license(l) for l in page], limit, offset, total)


@bp.route("/licensing/license-agreements/<lid>", methods=["GET"])
def get_license(lid):
    user_id, role = require_roles(*_READERS)
    rec = _get_license_or_404(lid)
    check_buyer_owns(user_id, role, rec["platform_id"])
    return ok_object(ser_license(rec))


@bp.route("/licensing/license-agreements/<lid>/activate", methods=["POST"])
def activate_license(lid):
    require_roles(ROLE_RIGHTS_MANAGER)
    lic = _get_license_or_404(lid)
    if lic["license_status"] != "EXECUTED":
        err(ERR_LICENSE_NOT_EXECUTABLE, "only an EXECUTED license can be activated")
    if CLOCK.now() < lic["license_start"]:
        err(ERR_LICENSE_NOT_STARTED, "the license window has not started yet")
    delivered = any(
        b["license_id"] == lid and b["delivery_status"] == "DELIVERED"
        for b in DB.all("batches")
    )
    if not delivered:
        err(ERR_DELIVERY_INCOMPLETE, "no DELIVERED delivery batch exists for this license")
    lic["license_status"] = "ACTIVE"
    lic["activated_at"] = CLOCK.now()
    mutate(lic)
    return ok_object(ser_license(lic))


@bp.route("/licensing/license-agreements/<lid>/extend", methods=["POST"])
def extend_license(lid):
    require_roles(ROLE_RIGHTS_MANAGER)
    lic = _get_license_or_404(lid)
    body = json_body()
    new_end = field_dt(body, "new_license_end")
    expected_version = field_int(body, "expected_license_version")
    # The extended window must remain a valid window (schema-level order rule).
    check_window_order(lic["license_start"], new_end, "license window")
    # State gate runs before/alongside OCC.
    if lic["license_status"] not in ("EXECUTED", "ACTIVE"):
        err(ERR_LICENSE_NOT_EXTENDABLE, "only an EXECUTED or ACTIVE license can be extended")
    if expected_version != lic["version"]:
        err(ERR_STALE_VERSION, "expected_license_version does not match the license version")
    slot = DB.get("slots", lic["slot_id"])
    # Temporal: the new end must be strictly after the current end and at or
    # before the slot's sellable_to (containment re-validated).
    if not (new_end > lic["license_end"] and new_end <= slot["sellable_to"]):
        err(
            ERR_WINDOW_OUTSIDE_RIGHTS,
            "new_license_end must be after the current license_end and within rights",
        )
    # Constraint: both conflict checks re-validated for the extended window.
    check_conflicts(
        slot,
        lic["license_start"],
        new_end,
        lic["window_type"],
        lic["exclusive"],
        exclude_license_id=lic["id"],
    )
    lic["license_end"] = new_end
    lic["holdback_until"] = (
        derive_holdback_until(lic["window_type"], new_end) if lic["exclusive"] else None
    )
    mutate(lic)
    # Reschedule the takedown: cancel the SCHEDULED notice, create a replacement.
    for n in DB.all("notices"):
        if n["license_id"] == lic["id"] and n["notice_status"] == "SCHEDULED":
            n["notice_status"] = "CANCELLED"
            mutate(n)
    create_notice(lic)
    return ok_object(ser_license(lic))


@bp.route("/licensing/license-agreements/<lid>/terminate", methods=["POST"])
def terminate_license_endpoint(lid):
    require_roles(ROLE_RIGHTS_MANAGER)
    lic = _get_license_or_404(lid)
    if lic["license_status"] not in ("EXECUTED", "ACTIVE"):
        err(ERR_LICENSE_ALREADY_TERMINAL, "license is already in a terminal state")
    terminate_license(lic, CLOCK.now())
    return ok_object(ser_license(lic))


@bp.route("/licensing/license-agreements/<lid>/revenue-reports", methods=["POST"])
def submit_revenue_report(lid):
    user_id, role = require_roles(ROLE_PLATFORM_BUYER)
    lic = _get_license_or_404(lid)
    check_buyer_owns(user_id, role, lic["platform_id"])
    body = json_body()
    period_start = field_dt(body, "period_start")
    period_end = field_dt(body, "period_end")
    check_window_order(period_start, period_end, "report period")
    gross_revenue_cents = field_int(body, "gross_revenue_cents")
    expected_version = field_int(body, "expected_license_version")
    # State gate: reportable licenses are EXECUTED/ACTIVE and not FLAT_FEE.
    if lic["license_status"] not in ("EXECUTED", "ACTIVE") or lic["fee_model"] == "FLAT_FEE":
        err(ERR_LICENSE_NOT_REPORTABLE, "license cannot receive revenue reports")
    # OCC.
    if expected_version != lic["version"]:
        err(ERR_STALE_VERSION, "expected_license_version does not match the license version")
    # Temporal: no future-dated revenue.
    if period_end > CLOCK.now():
        err(ERR_REPORT_PERIOD_FUTURE, "period_end is after the logical clock")
    # Fiscal.
    if gross_revenue_cents <= 0:
        err(ERR_NONPOSITIVE_REVENUE, "gross_revenue_cents must be > 0")
    report = DB.insert(
        "reports",
        {
            "license_id": lic["id"],
            "period_start": period_start,
            "period_end": period_end,
            "gross_revenue_cents": gross_revenue_cents,
            "royalty_accrued_cents": 0,
            "recoupment_applied_cents": 0,
            "payable_cents": 0,
            "report_status": "SUBMITTED",
            "submitted_at": CLOCK.now(),
        },
    )
    book_report(lic, report)
    return ok_object(ser_report(report), status=201)
