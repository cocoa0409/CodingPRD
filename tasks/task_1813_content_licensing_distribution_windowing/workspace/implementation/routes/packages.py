"""Avail packages / offers (PRD §3.3–§3.5)."""
from flask import Blueprint, request

from auth import (
    check_buyer_owns,
    require_roles,
    ROLE_RIGHTS_MANAGER,
    ROLE_PLATFORM_BUYER,
)
from domain import (
    FEE_MODELS,
    PRORATION_MODES,
    apply_volume_discount,
    check_conflicts,
    check_pairwise_line_conflicts,
    create_license,
    guaranteed_value,
    list_page,
    ser_package,
    validate_fee_structure,
)
from errors import (
    err,
    ERR_PACKAGE_NOT_FOUND,
    ERR_PLATFORM_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PACKAGE_NOT_DRAFT,
    ERR_PACKAGE_NOT_OFFERED,
    ERR_PACKAGE_NOT_WITHDRAWABLE,
    ERR_SLOT_NOT_AVAILABLE,
    ERR_WINDOW_OUTSIDE_RIGHTS,
    ERR_OFFER_WINDOW_PAST,
    ERR_LINE_NOT_IN_PACKAGE,
    ERR_DUPLICATE_LINE_SLOT,
    ERR_EMPTY_ACCEPTANCE,
    ERR_LINE_BLOCKED,
    ERR_FORBIDDEN,
)
from response import ok_list, ok_object
from store import DB, mutate
from util import CLOCK
from validate import (
    check_window_order,
    field_arr,
    field_bool,
    field_dt,
    field_enum,
    field_int,
    field_num,
    field_str,
    json_body,
)

bp = Blueprint("packages", __name__)


def _parse_line(raw, idx):
    if not isinstance(raw, dict):
        err(ERR_INVALID_REQUEST, f"lines[{idx}] must be an object")
    slot_id = field_str(raw, "slot_id")
    license_start = field_dt(raw, "license_start")
    license_end = field_dt(raw, "license_end")
    check_window_order(license_start, license_end, f"lines[{idx}] window")
    exclusive = field_bool(raw, "exclusive")
    fee_model = field_enum(raw, "fee_model", FEE_MODELS)
    flat_fee_cents = field_int(raw, "flat_fee_cents", required=False, default=0)
    revenue_share_pct = field_num(raw, "revenue_share_pct", required=False, default=0)
    minimum_guarantee_cents = field_int(raw, "minimum_guarantee_cents", required=False, default=0)
    proration_mode = field_enum(
        raw, "proration_mode", PRORATION_MODES, required=False, default="DAILY_PRORATION"
    )
    return {
        "slot_id": slot_id,
        "license_start": license_start,
        "license_end": license_end,
        "exclusive": exclusive,
        "fee_model": fee_model,
        "flat_fee_cents": flat_fee_cents,
        "revenue_share_pct": revenue_share_pct,
        "minimum_guarantee_cents": minimum_guarantee_cents,
        "proration_mode": proration_mode,
    }


@bp.route("/licensing/avail-packages", methods=["POST"])
def create_package():
    require_roles(ROLE_RIGHTS_MANAGER)
    body = json_body()
    platform_id = field_str(body, "platform_id")
    name = field_str(body, "name")
    offer_expires_at = field_dt(body, "offer_expires_at")
    raw_lines = field_arr(body, "lines", min_len=1)
    lines = [_parse_line(raw, i) for i, raw in enumerate(raw_lines)]

    # Existence: platform first, then each line's slot in declaration order.
    platform = DB.get("platforms", platform_id)
    if platform is None:
        err(ERR_PLATFORM_NOT_FOUND, "referenced platform does not exist")
    for line in lines:
        if DB.get("slots", line["slot_id"]) is None:
            err(ERR_SLOT_NOT_FOUND, "a line references a rights slot that does not exist")

    # Business-referential: distinct slot_ids within one package.
    seen = set()
    for line in lines:
        if line["slot_id"] in seen:
            err(ERR_DUPLICATE_LINE_SLOT, "two lines reference the same slot")
        seen.add(line["slot_id"])

    # Business-fiscal: per-line fee structure; non-applicable fee fields -> 0.
    total = 0
    for line in lines:
        flat, share, mg = validate_fee_structure(
            line["fee_model"],
            line["flat_fee_cents"],
            line["revenue_share_pct"],
            line["minimum_guarantee_cents"],
        )
        line["flat_fee_cents"] = flat
        line["revenue_share_pct"] = share
        line["minimum_guarantee_cents"] = mg
        line["line_status"] = "PENDING"
        line["created_license_id"] = None
        total += guaranteed_value(line["fee_model"], flat, mg)

    rec = DB.insert(
        "packages",
        {
            "platform_id": platform_id,
            "name": name,
            "offer_expires_at": offer_expires_at,
            "package_status": "DRAFT",
            "lines": lines,
            "guaranteed_total_cents": total,
            "discount_pct": None,
            "discount_cents": None,
            "net_total_cents": None,
            "offered_at": None,
        },
    )
    return ok_object(ser_package(rec), status=201)


def _buyer_list_scope(user_id, role):
    """PlatformBuyer list scoping: a platform_id filter must equal the caller's
    own id; when omitted it defaults to the caller's own platform."""
    if role != ROLE_PLATFORM_BUYER:
        return request.args.get("platform_id")
    supplied = request.args.get("platform_id")
    if supplied is not None and supplied != user_id:
        err(ERR_FORBIDDEN, "PlatformBuyer may only list its own platform's packages")
    return user_id


@bp.route("/licensing/avail-packages", methods=["GET"])
def list_packages():
    user_id, role = require_roles(ROLE_RIGHTS_MANAGER, ROLE_PLATFORM_BUYER)
    platform_filter = _buyer_list_scope(user_id, role)
    records = DB.all("packages")
    if platform_filter is not None:
        records = [p for p in records if p["platform_id"] == platform_filter]
    status = request.args.get("package_status")
    if status is not None:
        records = [p for p in records if p["package_status"] == status]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_package(p) for p in page], limit, offset, total)


def _get_package_or_404(pid):
    rec = DB.get("packages", pid)
    if rec is None:
        err(ERR_PACKAGE_NOT_FOUND, "referenced avail package does not exist")
    return rec


@bp.route("/licensing/avail-packages/<pid>", methods=["GET"])
def get_package(pid):
    user_id, role = require_roles(ROLE_RIGHTS_MANAGER, ROLE_PLATFORM_BUYER)
    rec = _get_package_or_404(pid)
    check_buyer_owns(user_id, role, rec["platform_id"])
    return ok_object(ser_package(rec))


def _validate_line_against_live_state(pkg, indices):
    """Window containment, then conflict checks (vs EXECUTED/ACTIVE licenses,
    then pairwise within the given line set)."""
    cands = []
    for i in indices:
        line = pkg["lines"][i]
        slot = DB.get("slots", line["slot_id"])
        # Window containment (business-temporal, priority 7).
        if not (
            slot["sellable_from"] <= line["license_start"]
            and line["license_end"] <= slot["sellable_to"]
        ):
            err(ERR_WINDOW_OUTSIDE_RIGHTS, "line window is outside the slot's rights period")
        cands.append(
            {
                "slot": slot,
                "license_start": line["license_start"],
                "license_end": line["license_end"],
                "exclusive": line["exclusive"],
            }
        )
    # Business-constraint (priority 8): same-cell exclusivity before holdback.
    for c in cands:
        check_conflicts(
            c["slot"],
            c["license_start"],
            c["license_end"],
            c["slot"]["window_type"],
            c["exclusive"],
        )
    check_pairwise_line_conflicts(cands)


@bp.route("/licensing/avail-packages/<pid>/offer", methods=["POST"])
def offer_package(pid):
    require_roles(ROLE_RIGHTS_MANAGER)
    pkg = _get_package_or_404(pid)
    if pkg["package_status"] != "DRAFT":
        err(ERR_PACKAGE_NOT_DRAFT, "only a DRAFT package can be offered")
    # Every line's slot must exist and be AVAILABLE.
    for line in pkg["lines"]:
        slot = DB.get("slots", line["slot_id"])
        if slot is None or slot["slot_status"] != "AVAILABLE":
            err(ERR_SLOT_NOT_AVAILABLE, "every offered line's slot must be AVAILABLE")
    # Window containment (temporal), then offer expiry (temporal).
    for line in pkg["lines"]:
        slot = DB.get("slots", line["slot_id"])
        if not (
            slot["sellable_from"] <= line["license_start"]
            and line["license_end"] <= slot["sellable_to"]
        ):
            err(ERR_WINDOW_OUTSIDE_RIGHTS, "line window is outside the slot's rights period")
    if not (pkg["offer_expires_at"] > CLOCK.now()):
        err(ERR_OFFER_WINDOW_PAST, "offer_expires_at must be strictly after the logical clock")
    # Conflicts (constraint): vs live licenses and pairwise within the package.
    _validate_line_against_live_state(pkg, range(len(pkg["lines"])))

    for line in pkg["lines"]:
        line["line_status"] = "OFFERED"
    pkg["package_status"] = "OFFERED"
    pkg["offered_at"] = CLOCK.now()
    mutate(pkg)
    return ok_object(ser_package(pkg))


@bp.route("/licensing/avail-packages/<pid>/accept", methods=["POST"])
def accept_package(pid):
    user_id, role = require_roles(ROLE_PLATFORM_BUYER)
    pkg = _get_package_or_404(pid)
    check_buyer_owns(user_id, role, pkg["platform_id"])
    body = json_body()
    accepted_slot_ids = field_arr(body, "accepted_slot_ids", elem_str=True)
    # State gate.
    if pkg["package_status"] != "OFFERED":
        err(ERR_PACKAGE_NOT_OFFERED, "only an OFFERED package can be accepted")
    # Referential: every element must be the slot_id of some line.
    slot_to_index = {l["slot_id"]: i for i, l in enumerate(pkg["lines"])}
    for sid in accepted_slot_ids:
        if sid not in slot_to_index:
            err(ERR_LINE_NOT_IN_PACKAGE, "accepted_slot_ids names a slot not in the package")
    if len(accepted_slot_ids) == 0:
        err(ERR_EMPTY_ACCEPTANCE, "accepted_slot_ids must be non-empty")
    accepted_indices = []
    seen = set()
    for sid in accepted_slot_ids:
        i = slot_to_index[sid]
        if i not in seen:
            seen.add(i)
            accepted_indices.append(i)

    # Temporal re-validation: window containment for accepted lines.
    for i in accepted_indices:
        line = pkg["lines"][i]
        slot = DB.get("slots", line["slot_id"])
        if not (
            slot["sellable_from"] <= line["license_start"]
            and line["license_end"] <= slot["sellable_to"]
        ):
            err(ERR_WINDOW_OUTSIDE_RIGHTS, "line window is outside the slot's rights period")
    # Constraint: accepted lines must be OFFERED (BLOCKED lines cannot accept).
    for i in accepted_indices:
        if pkg["lines"][i]["line_status"] != "OFFERED":
            err(ERR_LINE_BLOCKED, "an accepted line is not OFFERED")
    # Constraint: conflict re-validation vs live licenses and pairwise.
    _validate_line_against_live_state(pkg, accepted_indices)

    # Side effects: discount, licenses, line statuses, notices, encumbrance.
    allocated = apply_volume_discount(pkg, accepted_indices)
    created = {}
    for i in sorted(accepted_indices):
        line = pkg["lines"][i]
        slot = DB.get("slots", line["slot_id"])
        lic = create_license(
            slot,
            pkg["platform_id"],
            line["license_start"],
            line["license_end"],
            line["exclusive"],
            line["fee_model"],
            line["flat_fee_cents"],
            line["revenue_share_pct"],
            line["minimum_guarantee_cents"],
            line["proration_mode"],
            pkg["id"],
            allocated[i],
        )
        created[i] = lic
    for i, line in enumerate(pkg["lines"]):
        if i in created:
            line["line_status"] = "LICENSED"
            line["created_license_id"] = created[i]["id"]
        else:
            line["line_status"] = "NOT_SELECTED"
    pkg["package_status"] = (
        "ACCEPTED" if len(accepted_indices) == len(pkg["lines"]) else "PARTIALLY_ACCEPTED"
    )
    mutate(pkg)
    return ok_object(ser_package(pkg))


@bp.route("/licensing/avail-packages/<pid>/decline", methods=["POST"])
def decline_package(pid):
    user_id, role = require_roles(ROLE_PLATFORM_BUYER)
    pkg = _get_package_or_404(pid)
    check_buyer_owns(user_id, role, pkg["platform_id"])
    if pkg["package_status"] != "OFFERED":
        err(ERR_PACKAGE_NOT_OFFERED, "only an OFFERED package can be declined")
    for line in pkg["lines"]:
        if line["line_status"] != "LICENSED":
            line["line_status"] = "NOT_SELECTED"
    pkg["package_status"] = "DECLINED"
    mutate(pkg)
    return ok_object(ser_package(pkg))


@bp.route("/licensing/avail-packages/<pid>/withdraw", methods=["POST"])
def withdraw_package(pid):
    require_roles(ROLE_RIGHTS_MANAGER)
    pkg = _get_package_or_404(pid)
    if pkg["package_status"] not in ("DRAFT", "OFFERED"):
        err(ERR_PACKAGE_NOT_WITHDRAWABLE, "only a DRAFT or OFFERED package can be withdrawn")
    for line in pkg["lines"]:
        if line["line_status"] != "LICENSED":
            line["line_status"] = "NOT_SELECTED"
    pkg["package_status"] = "WITHDRAWN"
    mutate(pkg)
    return ok_object(ser_package(pkg))
