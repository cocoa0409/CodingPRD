"""Invoice endpoints: open, issue (aggregation), pay, dispute, resolve (PRD 3.6)."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from clock import CLOCK, format_iso, parse_iso
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import (
    PEAK_SURCHARGE_BP,
    invoice_line_view,
    invoice_view,
    new_common,
    recompute_owner_standing,
    touch,
)
from util import (
    as_int,
    as_str,
    body,
    paginate_sorted,
    required,
    round_half_up_cents,
    to_decimal,
)

bp = Blueprint("invoices", __name__)


def _get_invoice(iid):
    inv = db.invoices.get(iid)
    if not inv:
        raise ApiError("ERR_NOT_FOUND", 404, "Invoice not found")
    return inv


def _period_bounds(period):
    """Half-open [start, end) datetimes for a YYYY-MM billing period."""
    year, month = int(period[:4]), int(period[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _new_line(invoice_id, kind, booking_id, share_id, qty_hours, amount_cents):
    rec = {
        "id": db.new_id(),
        "created_at": CLOCK.now_iso(),
        "invoice_id": invoice_id,
        "line_kind": kind,
        "booking_id": booking_id,
        "share_id": share_id,
        "quantity_hours": round(float(qty_hours), 2),
        "amount_cents": int(amount_cents),
    }
    db.invoice_lines[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Create / reads
# ---------------------------------------------------------------------------

@bp.route("/invoices", methods=["POST"])
def create_invoice():
    require_roles("FinanceOps")
    data = body()
    owner_id = as_str(required(data, "owner_id"), "owner_id")
    owner = db.owners.get(owner_id)
    if not owner:
        raise ApiError("ERR_NOT_FOUND", 404, "Owner not found")
    period = as_str(required(data, "billing_period"), "billing_period")
    try:
        _period_bounds(period)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "billing_period must be YYYY-MM")
    if len(period) != 7 or period[4] != "-":
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "billing_period must be YYYY-MM")
    for inv in db.invoices.values():
        if inv["owner_id"] == owner_id and inv["billing_period"] == period:
            raise ApiError("ERR_DUPLICATE_INVOICE_PERIOD", 409,
                           "Invoice already exists for owner and period")

    rec = new_common()
    rec.update({
        "owner_id": owner_id,
        "billing_period": period,
        "invoice_status": "OPEN",
        "management_fee_cents": 0,
        "occupied_hours_fee_cents": 0,
        "total_due_cents": 0,
        "tax_adjustment_cents": 0,
        "issued_at": None,
    })
    db.invoices[rec["id"]] = rec
    return ok(invoice_view(rec), status=201)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require_roles(*ALL_ROLES)
    return ok(invoice_view(_get_invoice(iid)))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    require_roles(*ALL_ROLES)
    owner_id = request.args.get("owner_id")
    status = request.args.get("invoice_status")
    period = request.args.get("billing_period")
    items = list(db.invoices.values())
    if owner_id is not None:
        items = [i for i in items if i["owner_id"] == owner_id]
    if status is not None:
        items = [i for i in items if i["invoice_status"] == status]
    if period is not None:
        items = [i for i in items if i["billing_period"] == period]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([invoice_view(i) for i in page], total, limit, offset)


@bp.route("/invoices/<iid>/lines", methods=["GET"])
def list_invoice_lines(iid):
    require_roles(*ALL_ROLES)
    inv = _get_invoice(iid)
    items = [l for l in db.invoice_lines.values() if l["invoice_id"] == inv["id"]]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([invoice_line_view(l) for l in page], total, limit, offset)


@bp.route("/invoice-lines", methods=["GET"])
def list_all_invoice_lines():
    require_roles(*ALL_ROLES)
    invoice_id = request.args.get("invoice_id")
    booking_id = request.args.get("booking_id")
    share_id = request.args.get("share_id")
    line_kind = request.args.get("line_kind")
    items = list(db.invoice_lines.values())
    if invoice_id is not None:
        items = [l for l in items if l["invoice_id"] == invoice_id]
    if booking_id is not None:
        items = [l for l in items if l["booking_id"] == booking_id]
    if share_id is not None:
        items = [l for l in items if l["share_id"] == share_id]
    if line_kind is not None:
        items = [l for l in items if l["line_kind"] == line_kind]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([invoice_line_view(l) for l in page], total, limit, offset)


@bp.route("/invoice-lines/<lid>", methods=["GET"])
def get_invoice_line(lid):
    require_roles(*ALL_ROLES)
    line = db.invoice_lines.get(lid)
    if not line:
        raise ApiError("ERR_NOT_FOUND", 404, "Invoice line not found")
    return ok(invoice_line_view(line))


# ---------------------------------------------------------------------------
# Issue: full aggregation
# ---------------------------------------------------------------------------

@bp.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    require_roles("FinanceOps")
    inv = _get_invoice(iid)
    if inv["invoice_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Invoice must be OPEN to issue")
    start, end = _period_bounds(inv["billing_period"])
    if CLOCK.now() < end:
        raise ApiError("ERR_INVOICE_PERIOD_OPEN", 422,
                       "Billing period has not ended")
    owner = db.owners[inv["owner_id"]]
    if owner["owner_standing"] == "EXITED":
        raise ApiError("ERR_OWNER_STANDING_BLOCKS", 422,
                       "Owner EXITED blocks issuance")

    # --- Management fee lines ---
    # Shares of the owner in ACTIVE/LISTED/IN_EXIT at period end instant.
    mgmt_total = 0
    for s in db.shares.values():
        if s["owner_id"] != owner["id"]:
            continue
        if s["share_status"] not in ("ACTIVE", "LISTED", "IN_EXIT"):
            continue
        cls = db.aircraft_classes[s["class_id"]]
        fee = round_half_up_cents(
            Decimal(cls["monthly_fee_base_cents"])
            * Decimal(s["fraction_numerator"])
            / Decimal(s["fraction_denominator"])
        )
        _new_line(inv["id"], "MANAGEMENT_FEE", None, s["id"], 0, fee)
        mgmt_total += fee

    # --- Occupied hours / peak surcharge / interchange lines ---
    occ_total = 0
    for fl in db.flight_legs.values():
        b = db.bookings.get(fl["booking_id"])
        if not b or b["billing_status"] != "FINALLY_BILLED":
            continue
        share = db.shares[b["share_id"]]
        if share["owner_id"] != owner["id"]:
            continue
        completed = parse_iso(fl["completed_at"])
        if not (start <= completed < end):
            continue
        req_cls = db.aircraft_classes[b["requested_class_id"]]
        actual = to_decimal(fl["actual_block_hours"])
        base = round_half_up_cents(actual * req_cls["hourly_rate_cents"])
        _new_line(inv["id"], "OCCUPIED_HOURS", b["id"], share["id"],
                  fl["actual_block_hours"], base)
        occ_total += base
        if fl["peak_day_flag"]:
            peak = round_half_up_cents(
                Decimal(base) * Decimal(PEAK_SURCHARGE_BP) / Decimal(10000)
            )
            _new_line(inv["id"], "PEAK_SURCHARGE", b["id"], share["id"],
                      fl["actual_block_hours"], peak)
            occ_total += peak
        # Interchange adjustment (assignment-time class divergence).
        if b["assigned_aircraft_id"]:
            fly_cls = db.aircraft_classes[
                db.aircraft[b["assigned_aircraft_id"]]["class_id"]
            ]
            if fly_cls["id"] != req_cls["id"]:
                req_rate = req_cls["hourly_rate_cents"]
                fly_rate = fly_cls["hourly_rate_cents"]
                if b["interchange_direction"] == "UPGRADE":
                    scaled = round_half_up_cents(
                        Decimal(req_rate)
                        * Decimal(fly_cls["interchange_upgrade_multiplier_bp"])
                        / Decimal(10000)
                    )
                    effective = min(fly_rate, scaled)
                else:  # DOWNGRADE
                    effective = fly_rate
                adj = round_half_up_cents(
                    Decimal(effective - req_rate) * actual
                )
                _new_line(inv["id"], "INTERCHANGE_ADJUSTMENT", b["id"],
                          share["id"], fl["actual_block_hours"], adj)
                occ_total += adj

    # --- Maintenance allocation lines (completed events in this period) ---
    for m in db.maintenance_events.values():
        if m["event_status"] != "COMPLETED":
            continue
        completed_at = m.get("completed_at")
        if not completed_at:
            continue
        cdt = parse_iso(completed_at)
        if not (start <= cdt < end):
            continue
        allocs = m.get("allocations") or {}
        if owner["id"] in allocs:
            amount = allocs[owner["id"]]
            aircraft = db.aircraft[m["aircraft_id"]]
            # Attribute the line to the owner's first ACTIVE share of the class
            # (any share of that class for referential completeness).
            share_id = None
            for s in db.shares.values():
                if (s["owner_id"] == owner["id"]
                        and s["class_id"] == aircraft["class_id"]
                        and s["share_status"] in ("ACTIVE", "LISTED", "IN_EXIT")):
                    share_id = s["id"]
                    break
            _new_line(inv["id"], "MAINTENANCE_ALLOCATION", None, share_id,
                      0, amount)
            occ_total += amount

    # --- Depreciation pass-through (December periods only) ---
    tax_adjustment = 0
    period_year, period_month = int(inv["billing_period"][:4]), int(inv["billing_period"][5:7])
    if period_month == 12:
        # Compute all allowances against pre-posting accumulated balances first.
        pending = []
        for s in db.shares.values():
            if s["owner_id"] != owner["id"]:
                continue
            sched = next(
                (d for d in db.depreciation_schedules.values()
                 if d["share_id"] == s["id"]),
                None,
            )
            if not sched:
                continue
            # Skip shares in terminal CLOSED-with-settled-exit state.
            if s["share_status"] == "CLOSED":
                settled = any(
                    x["share_id"] == s["id"] and x["exit_status"] == "SETTLED"
                    for x in db.exit_requests.values()
                )
                if settled:
                    continue
            basis = sched["basis_cents"]
            accum = sched["accumulated_depreciation_cents"]
            remaining = basis - accum
            if remaining <= 0:
                allowance = 0
            elif sched["schedule_method"] == "STRAIGHT_LINE":
                allowance = round_half_up_cents(
                    Decimal(basis) / Decimal(sched["recovery_years"])
                )
                allowance = min(allowance, remaining)
            else:  # DOUBLE_DECLINING
                ddb = round_half_up_cents(
                    Decimal(2) * Decimal(remaining)
                    / Decimal(sched["recovery_years"])
                )
                allowance = min(ddb, remaining)
            pending.append((sched, s, allowance))
        # Only after all shares are computed, post the updates.
        for sched, s, allowance in pending:
            if allowance <= 0:
                continue
            _new_line(inv["id"], "DEPRECIATION_PASSTHROUGH", None, s["id"],
                      0, -allowance)
            sched["accumulated_depreciation_cents"] += allowance
            sched["current_year_allowance_cents"] = allowance
            tax_adjustment += -allowance

    inv["management_fee_cents"] = mgmt_total
    inv["occupied_hours_fee_cents"] = occ_total
    inv["tax_adjustment_cents"] = tax_adjustment
    inv["total_due_cents"] = mgmt_total + occ_total + tax_adjustment
    inv["issued_at"] = CLOCK.now_iso()
    inv["invoice_status"] = "ISSUED"
    touch(inv)
    return ok(invoice_view(inv))


# ---------------------------------------------------------------------------
# Pay / dispute / resolve
# ---------------------------------------------------------------------------

@bp.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    user_id, role = require_roles("Owner")
    inv = _get_invoice(iid)
    if inv["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the billed owner may pay this invoice")
    if inv["invoice_status"] in ("PAID", "SETTLED_AFTER_DISPUTE"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Invoice is already {inv['invoice_status']}")
    if inv["invoice_status"] not in ("ISSUED", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Invoice must be ISSUED or PAST_DUE to pay")
    data = body()
    amount = as_int(required(data, "amount_cents"), "amount_cents")
    if amount != inv["total_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                       "Payment amount must equal total_due_cents exactly")
    inv["invoice_status"] = "PAID"
    touch(inv)
    recompute_owner_standing(db.owners[inv["owner_id"]])
    return ok(invoice_view(inv))


@bp.route("/invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    user_id, role = require_roles("Owner")
    inv = _get_invoice(iid)
    if inv["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the billed owner may dispute this invoice")
    if inv["invoice_status"] in ("PAID", "SETTLED_AFTER_DISPUTE"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Invoice is already {inv['invoice_status']}")
    if inv["invoice_status"] not in ("ISSUED", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Invoice must be ISSUED or PAST_DUE to dispute")
    inv["_pre_dispute_status"] = inv["invoice_status"]
    inv["invoice_status"] = "DISPUTED"
    touch(inv)
    return ok(invoice_view(inv))


@bp.route("/invoices/<iid>/resolve-dispute", methods=["POST"])
def resolve_dispute(iid):
    require_roles("FinanceOps")
    inv = _get_invoice(iid)
    if inv["invoice_status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Invoice must be DISPUTED to resolve")
    data = body()
    reject = data.get("reject_adjustment", False)
    if reject:
        # Return to the pre-dispute standing.
        prev = inv.pop("_pre_dispute_status", "ISSUED")
        inv["invoice_status"] = prev
        touch(inv)
        recompute_owner_standing(db.owners[inv["owner_id"]])
        return ok(invoice_view(inv))
    adjusted = as_int(required(data, "adjusted_total_cents"), "adjusted_total_cents")
    if adjusted < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "adjusted_total_cents must be >= 0")
    inv.pop("_pre_dispute_status", None)
    inv["total_due_cents"] = adjusted
    inv["invoice_status"] = "SETTLED_AFTER_DISPUTE"
    touch(inv)
    recompute_owner_standing(db.owners[inv["owner_id"]])
    return ok(invoice_view(inv))
