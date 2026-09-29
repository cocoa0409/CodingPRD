"""Tiers, members, memberships, dues invoices and the dues operations runs."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import clock
import engine
import guards
import response
import serializers
import store
import validators as v
from auth import CLUB_ADMIN, MEMBER, PARK_MANAGER, COMPLIANCE_OFFICER
from errors import fail

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# membership tiers
# ---------------------------------------------------------------------------
@bp.post("/membership-tiers")
def create_tier():
    auth.authorize(CLUB_ADMIN)
    data = v.body()
    row = store.base_row()
    row.update({
        "code": v.req_str(data, "code", min_len=2, max_len=24),
        "name": v.req_str(data, "name"),
        "tier_rank": v.req_int(data, "tier_rank", minimum=1, maximum=5),
        "upfront_cost_cents": v.req_int(data, "upfront_cost_cents", minimum=0),
        "annual_dues_cents": v.req_int(data, "annual_dues_cents", minimum=0),
        "entitlement_nights_class_a": v.req_int(data, "entitlement_nights_class_a", minimum=0),
        "entitlement_nights_class_b": v.req_int(data, "entitlement_nights_class_b", minimum=0),
        "entitlement_nights_class_c": v.req_int(data, "entitlement_nights_class_c", minimum=0),
        "annual_total_night_cap": v.req_int(data, "annual_total_night_cap", minimum=1),
        "advance_window_days": v.req_int(data, "advance_window_days", minimum=1, maximum=365),
        "max_consecutive_stay_nights": v.req_int(data, "max_consecutive_stay_nights",
                                                 minimum=1, maximum=45),
        "min_out_nights_between_stays": v.req_int(data, "min_out_nights_between_stays",
                                                  minimum=0, maximum=30),
        "affiliate_access_enabled": v.req_bool(data, "affiliate_access_enabled"),
        "resale_allowed": v.req_bool(data, "resale_allowed"),
        "transfer_fee_cents": v.req_int(data, "transfer_fee_cents", minimum=0),
    })
    store.insert("membership_tiers", row)
    return response.created(serializers.tier(row))


@bp.get("/membership-tiers/<tier_id>")
def read_tier(tier_id):
    auth.authorize(CLUB_ADMIN, MEMBER, PARK_MANAGER, COMPLIANCE_OFFICER)
    row = guards.fetch("membership_tiers", tier_id)
    return response.ok(serializers.tier(row))


@bp.get("/membership-tiers")
def list_tiers():
    auth.authorize(CLUB_ADMIN, MEMBER, PARK_MANAGER, COMPLIANCE_OFFICER)
    rows = store.ordered(store.all_rows("membership_tiers"))
    code = request.args.get("code")
    if code:
        rows = [r for r in rows if r["code"] == code]
    return response.paginate(rows, serializers.tier)


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------
@bp.post("/members")
def create_member():
    auth.authorize(CLUB_ADMIN)
    data = v.body()
    row = store.base_row()
    row.update({
        "full_name": v.req_str(data, "full_name"),
        "email": v.req_str(data, "email"),
        "home_region": v.opt_str(data, "home_region"),
        "status": "ACTIVE",
    })
    store.insert("members", row)
    return response.created(serializers.member(row))


@bp.get("/members/<member_id>")
def read_member(member_id):
    auth.authorize(CLUB_ADMIN, MEMBER)
    row = guards.fetch("members", member_id)
    return response.ok(serializers.member(row))


# ---------------------------------------------------------------------------
# memberships
# ---------------------------------------------------------------------------
@bp.post("/memberships")
def sell_membership():
    auth.authorize(CLUB_ADMIN)
    data = v.body()
    tier = guards.maybe("membership_tiers", v.raw_id(data, "tier_id"))
    guards.maybe("members", v.raw_id(data, "member_id"))
    member_id = v.req_id(data, "member_id")
    v.req_id(data, "tier_id")
    upfront = v.req_int(data, "upfront_paid_cents", minimum=0)
    if tier is None:
        fail("ERR_INVALID_REQUEST", "tier_id is required")

    stamp = clock.now_iso()
    row = store.base_row()
    row.update({
        "member_id": member_id,
        "tier_id": tier["id"],
        "transferred_from_membership_id": None,
        "membership_status": "ACTIVE",
        "dues_status": "CURRENT",
        "suspension_reason": None,
        "purchased_at": stamp,
        "tenure_origin_at": stamp,
        "upfront_paid_cents": upfront,
        "entitlement_year_start": clock.fmt_date(clock.today()),
        "nights_used_class_a": 0,
        "nights_used_class_b": 0,
        "nights_used_class_c": 0,
        "annual_nights_used": 0,
        "dues_balance_cents": 0,
        "dues_paid_through": None,
        "transfer_count": 0,
        "resale_eligible_at": clock.fmt_instant(
            clock.now() + timedelta(days=calc.RESALE_HOLD_DAYS)),
        "tenure_years": 0,
    })
    store.insert("memberships", row)
    engine.recompute_tenure(row)
    engine.issue_invoice(row, clock.today().year)
    return response.created(serializers.membership(row))


@bp.get("/memberships/<membership_id>")
def read_membership(membership_id):
    actor = auth.authorize(CLUB_ADMIN, MEMBER)
    row = guards.find("memberships", membership_id)
    auth.require_member_owner(actor, row)
    row = guards.fetch("memberships", membership_id)
    return response.ok(serializers.membership(row))


@bp.get("/memberships")
def list_memberships():
    auth.authorize(CLUB_ADMIN)
    rows = store.ordered(store.all_rows("memberships"))
    for field in ("member_id", "tier_id", "transferred_from_membership_id",
                  "membership_status", "dues_status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    return response.paginate(rows, serializers.membership)


@bp.get("/memberships/<membership_id>/dues-invoices")
def list_membership_invoices(membership_id):
    actor = auth.authorize(CLUB_ADMIN, MEMBER)
    row = guards.find("memberships", membership_id)
    auth.require_member_owner(actor, row)
    guards.fetch("memberships", membership_id)
    rows = engine.invoices_of_membership(membership_id)
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    cycle_year = request.args.get("cycle_year")
    if cycle_year:
        try:
            wanted = int(cycle_year)
        except Exception:
            wanted = None
        rows = [r for r in rows if r["cycle_year"] == wanted]
    return response.paginate(rows, serializers.invoice)


@bp.get("/memberships/<membership_id>/satisfaction-surveys")
def list_membership_surveys(membership_id):
    auth.authorize(CLUB_ADMIN, MEMBER)
    guards.fetch("memberships", membership_id)
    rows = store.ordered([s for s in store.all_rows("satisfaction_surveys")
                          if s.get("membership_id") == membership_id])
    return response.paginate(rows, serializers.survey)


@bp.post("/memberships/<membership_id>/suspension")
def suspend_membership(membership_id):
    auth.authorize(CLUB_ADMIN)
    membership = guards.fetch("memberships", membership_id)
    data = v.body()
    reason_key = "suspension_reason" if v.present(data, "suspension_reason") else "reason"
    reason = v.req_enum(data, reason_key, ("ADMIN_ACTION", "OCCUPANCY_POLICY"))
    if membership["membership_status"] != "ACTIVE":
        fail("ERR_MEMBERSHIP_NOT_ACTIVE", "only an ACTIVE membership may be suspended")

    membership["membership_status"] = "SUSPENDED"
    membership["suspension_reason"] = reason
    engine.suspend_cascade(membership, reason, "membership suspended")
    engine.recompute_dues_balance(membership)
    store.touch(membership)
    return response.ok(serializers.membership(membership))


@bp.post("/memberships/<membership_id>/reinstatement")
def reinstate_membership(membership_id):
    auth.authorize(CLUB_ADMIN)
    membership = guards.fetch("memberships", membership_id)
    data = v.body()
    fee = v.req_int(data, "reinstatement_fee_paid_cents", minimum=0)
    engine.recompute_dues_balance(membership)
    if (membership["membership_status"] != "SUSPENDED"
            or membership["dues_status"] != "CURRENT"
            or membership["dues_balance_cents"] != 0
            or fee < calc.REINSTATEMENT_FEE_CENTS):
        fail("ERR_REINSTATEMENT_FEE_REQUIRED",
             "reinstatement requires a SUSPENDED membership, CURRENT dues, a zero "
             "balance and a fee of at least %d cents" % calc.REINSTATEMENT_FEE_CENTS)
    membership["membership_status"] = "ACTIVE"
    membership["suspension_reason"] = None
    store.touch(membership)
    return response.ok(serializers.membership(membership))


# ---------------------------------------------------------------------------
# dues invoices
# ---------------------------------------------------------------------------
@bp.get("/dues-invoices/<invoice_id>")
def read_invoice(invoice_id):
    auth.authorize(CLUB_ADMIN, MEMBER)
    invoice = guards.fetch("dues_invoices", invoice_id)
    return response.ok(serializers.invoice(invoice))


@bp.post("/dues-invoices/<invoice_id>/payments")
def pay_invoice(invoice_id):
    actor = auth.authorize(MEMBER, CLUB_ADMIN)
    invoice = guards.find("dues_invoices", invoice_id)
    if invoice is not None:
        auth.require_member_owner(actor, store.get("memberships", invoice["membership_id"]))
    invoice = guards.fetch("dues_invoices", invoice_id)
    data = v.body()
    amount = v.req_int(data, "amount_cents", minimum=0)
    if invoice["status"] not in ("OPEN", "PAST_DUE"):
        fail("ERR_DUES_INVOICE_NOT_PAYABLE", "invoice is not payable")
    outstanding = (invoice["amount_cents"] + invoice["late_fee_cents"]
                   - invoice["paid_amount_cents"])
    if amount != outstanding:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH",
             "payment must equal the outstanding balance of %d cents" % outstanding)

    membership = store.get("memberships", invoice["membership_id"])
    invoice["status"] = "PAID"
    invoice["paid_amount_cents"] = amount
    invoice["paid_at"] = clock.now_iso()
    invoice["_pre_payment_dues_paid_through"] = (membership.get("dues_paid_through")
                                                if membership else None)
    store.touch(invoice)

    if membership is not None:
        still_past_due = any(i["status"] == "PAST_DUE"
                             for i in engine.invoices_of_membership(membership["id"]))
        if membership["dues_status"] in ("GRACE", "DELINQUENT") and not still_past_due:
            membership["dues_status"] = "CURRENT"
        membership["dues_paid_through"] = clock.fmt_date(
            clock.add_days(engine.as_date(invoice["due_date"]), calc.DUES_CYCLE_DAYS))
        engine.recompute_dues_balance(membership)
        store.touch(membership)
    return response.ok(serializers.invoice(invoice))


@bp.post("/dues-invoices/<invoice_id>/payment-reversals")
def reverse_payment(invoice_id):
    auth.authorize(CLUB_ADMIN)
    invoice = guards.fetch("dues_invoices", invoice_id)
    data = v.body()
    v.req_str(data, "reason")
    if invoice["status"] != "PAID":
        fail("ERR_DUES_INVOICE_NOT_PAYABLE", "only a PAID invoice may be reversed")

    membership = store.get("memberships", invoice["membership_id"])
    invoice["paid_amount_cents"] = 0
    invoice["paid_at"] = None
    due_date = engine.as_date(invoice["due_date"])
    today = clock.today()
    if today <= due_date:
        invoice["status"] = "OPEN"
        invoice["late_fee_cents"] = 0
    else:
        invoice["status"] = "PAST_DUE"
        invoice["late_fee_cents"] = calc.dues_late_fee(invoice["amount_cents"],
                                                      (today - due_date).days)
        if membership is not None and membership["dues_status"] == "CURRENT":
            membership["dues_status"] = "GRACE"
    store.touch(invoice)

    if membership is not None:
        membership["dues_paid_through"] = invoice.get("_pre_payment_dues_paid_through")
        engine.recompute_dues_balance(membership)
        store.touch(membership)
    return response.ok(serializers.invoice(invoice))


# ---------------------------------------------------------------------------
# operations runs
# ---------------------------------------------------------------------------
@bp.post("/ops/annual-dues-run")
def annual_dues_run():
    auth.authorize(CLUB_ADMIN)
    data = v.body()
    cycle_year = v.req_int(data, "cycle_year", minimum=0)
    today = clock.today()
    issued = 0
    billed = 0
    for membership in store.ordered(store.all_rows("memberships")):
        if membership["membership_status"] == "TERMINATED":
            continue
        if membership["dues_status"] == "WRITTEN_OFF":
            continue
        start = engine.as_date(membership["entitlement_year_start"])
        if today < clock.add_days(start, calc.ENTITLEMENT_YEAR_DAYS):
            continue
        membership["entitlement_year_start"] = clock.fmt_date(
            clock.add_days(start, calc.ENTITLEMENT_YEAR_DAYS))
        membership["nights_used_class_a"] = 0
        membership["nights_used_class_b"] = 0
        membership["nights_used_class_c"] = 0
        membership["annual_nights_used"] = 0
        invoice = engine.issue_invoice(membership, cycle_year)
        issued += 1
        billed += invoice["amount_cents"]
        engine.recompute_dues_balance(membership)
        engine.recompute_tenure(membership)
        store.touch(membership)
    return response.ok({
        "cycle_year": cycle_year,
        "invoices_issued": issued,
        "total_billed_cents": billed,
    })


def _delinquency_cascade(membership, stats):
    """Links 2-6 of the delinquency cascade plus the transfer-request void."""
    membership["dues_status"] = "DELINQUENT"
    stats["memberships_to_delinquent"] += 1
    if membership["membership_status"] in ("ACTIVE", "TRANSFER_PENDING"):
        membership["membership_status"] = "SUSPENDED"
        membership["suspension_reason"] = "DUES_DELINQUENCY"
        result = engine.suspend_cascade(membership, "DUES_DELINQUENCY", "dues delinquency")
        stats["reservations_cancelled"] += result["cancelled"]
        stats["waitlist_promotions"] += result["promotions"]
    else:
        engine.void_submitted_transfers(membership, "dues delinquency")


def _write_off(membership, invoice, stats):
    invoice["status"] = "WRITTEN_OFF"
    store.touch(invoice)
    membership["dues_status"] = "WRITTEN_OFF"
    stats["memberships_written_off"] += 1
    if membership["membership_status"] == "SUSPENDED":
        membership["membership_status"] = "TERMINATED"
    for res in store.ordered(engine.reservations_of_membership(membership["id"])):
        if res["status"] in ("PENDING", "CONFIRMED", "WAITLISTED"):
            engine.force_cancel(res, "MEMBERSHIP_SUSPENDED")
            stats["reservations_cancelled"] += 1


def _content_changed(before, row):
    """True when any business column moved; the audit columns are ignored."""
    ignored = ("version", "updated_at")
    keys = set(before) | set(row)
    return any(before.get(k) != row.get(k) for k in keys if k not in ignored)


@bp.post("/ops/dues-delinquency-run")
def dues_delinquency_run():
    auth.authorize(CLUB_ADMIN)
    today = clock.today()
    stats = {
        "invoices_swept": 0,
        "memberships_to_grace": 0,
        "memberships_to_delinquent": 0,
        "memberships_written_off": 0,
        "reservations_cancelled": 0,
        "waitlist_promotions": 0,
    }
    # PRD 2.4: `version` increments by exactly 1 on every mutation of that row, so a
    # membership the sweep leaves byte-identical must not be rewritten at all. Snapshot
    # the content up front and compare after the derived counters are recomputed.
    before_sweep = {
        row["id"]: dict(row) for row in store.all_rows("memberships")
    }
    touched = []
    for invoice in store.ordered(store.all_rows("dues_invoices")):
        if invoice["status"] not in ("OPEN", "PAST_DUE"):
            continue
        stats["invoices_swept"] += 1
        due_date = engine.as_date(invoice["due_date"])
        dpd = max(0, (today - due_date).days)
        invoice["days_past_due"] = dpd
        if dpd >= calc.DUES_GRACE_START_DAYS:
            invoice["status"] = "PAST_DUE"
            invoice["late_fee_cents"] = calc.dues_late_fee(invoice["amount_cents"], dpd)
        store.touch(invoice)

        membership = store.get("memberships", invoice["membership_id"])
        if membership is None or membership["dues_status"] == "WRITTEN_OFF":
            continue
        if membership not in touched:
            touched.append(membership)
        if dpd >= calc.DUES_WRITE_OFF_DAYS:
            if membership["dues_status"] in ("CURRENT", "GRACE"):
                _delinquency_cascade(membership, stats)
            if membership["dues_status"] == "DELINQUENT":
                _write_off(membership, invoice, stats)
        elif dpd >= calc.DUES_DELINQUENT_DAYS:
            if membership["dues_status"] in ("CURRENT", "GRACE"):
                _delinquency_cascade(membership, stats)
        elif dpd >= calc.DUES_GRACE_START_DAYS:
            if membership["dues_status"] == "CURRENT":
                membership["dues_status"] = "GRACE"
                stats["memberships_to_grace"] += 1

    for res in store.ordered(store.all_rows("reservations")):
        if res["status"] == "WAITLISTED" and engine.as_date(res["arrival_date"]) < today:
            res["status"] = "EXPIRED"
            store.touch(res)

    for membership in touched:
        engine.recompute_dues_balance(membership)
        engine.recompute_tenure(membership)
        before = before_sweep.get(membership["id"])
        if before is None or _content_changed(before, membership):
            store.touch(membership)
    return response.ok(stats)
