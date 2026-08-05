"""Placements, referral invoices, ledger, surveys, caseload, reports."""
from datetime import date

from flask import Blueprint, request

import store
import calc
import services as svc
import validate as V
import envelope as E
import constants as C
from rbac import guard, deny_ownership
from errors import ApiError
from serialize import dump
from protected import PROTECTED

bp = Blueprint("place", __name__)


def _parse_date_field(value, field):
    try:
        return date.fromisoformat(value)
    except Exception:
        raise ApiError("ERR_VALIDATION", "%s must be a calendar date." % field)


# ===========================================================================
# Placements
# ===========================================================================
@bp.post("/placements")
def create_placement():
    uid, role = guard(["Advisor"])
    body = V.get_body()
    V.reject_protected(body, {"match_id", "inventory_id", "agreed_move_in_date",
                              "contracted_monthly_rate_cents", "expected_inventory_version"},
                       PROTECTED["placement"])
    match_id = V.req_str(body, "match_id")
    inventory_id = V.req_str(body, "inventory_id")
    agreed = V.req_date(body, "agreed_move_in_date")
    rate = V.req_int(body, "contracted_monthly_rate_cents", 1)
    expected_version = V.req_int(body, "expected_inventory_version")
    match = V.lookup("matches", match_id, "ERR_MATCH_NOT_FOUND")
    inv = V.lookup("inventories", inventory_id, "ERR_INVENTORY_NOT_FOUND")
    if match["status"] != "SELECTED":
        raise ApiError("ERR_MATCH_INVALID_STATE", "Match must be SELECTED to reserve a unit.")
    community = store.DB["communities"][match["community_id"]]
    if community["status"] != "ACTIVE":
        raise ApiError("ERR_COMMUNITY_NOT_ACTIVE", "Community is not active.")
    if expected_version != inv["version"]:
        raise ApiError("ERR_STALE_VERSION", "Inventory version is stale.")
    for p in store.DB["placements"].values():
        if (p["inquiry_id"] == match["inquiry_id"]
                and p["residency_status"] not in ("CANCELLED", "MOVED_OUT")):
            raise ApiError("ERR_PLACEMENT_EXISTS", "Inquiry already has an active placement.")
    if inv["available_units"] < 1:
        raise ApiError("ERR_NO_UNITS_AVAILABLE", "No available units in the pool.")
    estimated = calc.referral_fee(match["quoted_monthly_rate_cents"],
                                  community["referral_fee_pct"], calc.Decimal("1.0"),
                                  match["care_level"], community["contract_tier"])
    row = svc.new_row("placements", {
        "match_id": match_id, "inquiry_id": match["inquiry_id"],
        "community_id": match["community_id"], "inventory_id": inventory_id,
        "care_level": match["care_level"], "agreed_move_in_date": agreed.isoformat(),
        "actual_move_in_date": None, "actual_care_level": None,
        "contracted_monthly_rate_cents": rate, "estimated_fee_cents": estimated,
        "final_fee_cents": None, "clawback_amount_cents": 0,
        "residency_status": "PENDING_MOVE_IN", "billing_status": "NOT_INVOICED",
        "move_out_date": None, "days_resided": None,
    })
    svc.recompute_inventory_fields(inv)
    svc.touch(inv)
    return E.created(dump(row))


@bp.get("/placements/<placement_id>")
def get_placement(placement_id):
    guard(C.ALL_ROLES)
    p = V.lookup("placements", placement_id, "ERR_PLACEMENT_NOT_FOUND")
    return E.ok(dump(p))


@bp.get("/placements")
def list_placements():
    guard(C.ALL_ROLES)
    rows = list(store.DB["placements"].values())
    for key in ("inquiry_id", "community_id", "match_id", "inventory_id",
                "residency_status", "billing_status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


@bp.post("/placements/<placement_id>/confirm-move-in")
def confirm_move_in(placement_id):
    uid, role = guard(["CommunityManager"])
    p = V.lookup("placements", placement_id, "ERR_PLACEMENT_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"actual_move_in_date", "actual_care_level"}, PROTECTED["placement"])
    move_in = V.req_date(body, "actual_move_in_date")
    actual_care = V.req_enum(body, "actual_care_level", C.CARE_LEVELS)
    if uid != p["community_id"]:
        deny_ownership()
    if p["residency_status"] != "PENDING_MOVE_IN":
        raise ApiError("ERR_PLACEMENT_INVALID_STATE", "Placement is not pending move-in.")
    if move_in > store.now_date():
        raise ApiError("ERR_MOVE_IN_DATE_INVALID", "actual_move_in_date is in the future.")
    community = store.DB["communities"][p["community_id"]]
    # L1
    p["actual_move_in_date"] = move_in.isoformat()
    p["actual_care_level"] = actual_care
    ratio = calc.proration_ratio(move_in)
    p["final_fee_cents"] = calc.referral_fee(
        p["contracted_monthly_rate_cents"], community["referral_fee_pct"], ratio,
        actual_care, community["contract_tier"])
    p["residency_status"] = "MOVED_IN"
    inv = store.DB["inventories"][p["inventory_id"]]
    svc.recompute_inventory_fields(inv)
    svc.touch(inv)
    invoice = svc.new_row("invoices", {
        "placement_id": p["id"], "community_id": p["community_id"],
        "final_fee_cents": p["final_fee_cents"], "paid_amount_cents": 0,
        "net_recognized_fee_cents": 0, "status": "DRAFT", "dispute_reason": None,
        "claimed_rate_cents": None, "adjustment_count": 0, "issued_at": None,
    })
    p["billing_status"] = "INVOICE_DRAFTED"
    svc.touch(p)
    # L2/L3/L4
    inquiry = store.DB["inquiries"][p["inquiry_id"]]
    if inquiry["status"] not in ("PLACED", "CLOSED_LOST"):
        inquiry["status"] = "PLACED"
        for match in svc.matches_of_inquiry(inquiry["id"]):
            if match["status"] in ("PROPOSED", "SHORTLISTED", "TOUR_SCHEDULED", "TOURED"):
                svc.withdraw_match(match, inquiry)
        svc.release_active_caseload(inquiry, "PLACED")
        svc.touch(inquiry)
    return E.ok(dump(p))


@bp.post("/placements/<placement_id>/confirm-residency")
def confirm_residency(placement_id):
    uid, role = guard(["Advisor"])
    p = V.lookup("placements", placement_id, "ERR_PLACEMENT_NOT_FOUND")
    V.get_body()
    if p["residency_status"] != "MOVED_IN":
        raise ApiError("ERR_PLACEMENT_INVALID_STATE", "Placement is not MOVED_IN.")
    move_in = date.fromisoformat(p["actual_move_in_date"])
    if (store.now_date() - move_in).days < C.RESIDENCY_CONFIRM_DAYS:
        raise ApiError("ERR_RESIDENCY_CONFIRM_TOO_EARLY", "Residency confirmation is too early.")
    p["residency_status"] = "RESIDENT_CONFIRMED"
    svc.touch(p)
    return E.ok(dump(p))


@bp.post("/placements/<placement_id>/move-out")
def move_out(placement_id):
    uid, role = guard(["CommunityManager", "PlatformAdmin"])
    p = V.lookup("placements", placement_id, "ERR_PLACEMENT_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"move_out_date", "reason_code"}, PROTECTED["placement"])
    out_date = V.req_date(body, "move_out_date")
    reason_code = V.req_str(body, "reason_code")
    if role == "CommunityManager" and uid != p["community_id"]:
        deny_ownership()
    if p["residency_status"] not in ("MOVED_IN", "RESIDENT_CONFIRMED"):
        raise ApiError("ERR_PLACEMENT_INVALID_STATE", "Placement is not moved in.")
    move_in = date.fromisoformat(p["actual_move_in_date"])
    if out_date < move_in or out_date > store.now_date():
        raise ApiError("ERR_MOVE_OUT_DATE_INVALID", "move_out_date is out of range.")
    community = store.DB["communities"][p["community_id"]]
    # L1
    p["move_out_date"] = out_date.isoformat()
    days = (out_date - move_in).days
    p["days_resided"] = days
    p["residency_status"] = "MOVED_OUT"
    inv = store.DB["inventories"][p["inventory_id"]]
    svc.recompute_inventory_fields(inv)
    svc.touch(inv)
    # L2
    invoice = _invoice_of_placement(p["id"])
    has_recognized = invoice is not None and invoice["status"] in ("ISSUED", "ACCEPTED", "PAID")
    clawback = calc.clawback_amount(p["final_fee_cents"], days, has_recognized)
    p["clawback_amount_cents"] = clawback
    if clawback > 0:
        invoice["status"] = "CLAWED_BACK"
        p["billing_status"] = "CLAWED_BACK"
        # L3
        svc.append_ledger_entry(invoice, p, community, "CLAWBACK", -clawback,
                                "Move-out clawback: %s" % reason_code)
        svc.touch(invoice)
    svc.touch(p)
    return E.ok(dump(p))


@bp.post("/placements/<placement_id>/cancel")
def cancel_placement(placement_id):
    uid, role = guard(["Advisor", "CommunityManager"])
    p = V.lookup("placements", placement_id, "ERR_PLACEMENT_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"reason_code"}, PROTECTED["placement"])
    V.req_str(body, "reason_code")
    if role == "CommunityManager" and uid != p["community_id"]:
        deny_ownership()
    if p["residency_status"] != "PENDING_MOVE_IN":
        raise ApiError("ERR_PLACEMENT_INVALID_STATE", "Placement is not pending move-in.")
    p["residency_status"] = "CANCELLED"
    svc.touch(p)
    inv = store.DB["inventories"][p["inventory_id"]]
    svc.recompute_inventory_fields(inv)
    svc.touch(inv)
    return E.ok(dump(p))


def _invoice_of_placement(placement_id):
    for inv in store.DB["invoices"].values():
        if inv["placement_id"] == placement_id:
            return inv
    return None


# ===========================================================================
# Referral invoices
# ===========================================================================
@bp.get("/referral-invoices/<invoice_id>")
def get_invoice(invoice_id):
    guard(C.ALL_ROLES)
    inv = V.lookup("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    return E.ok(dump(inv))


@bp.get("/referral-invoices")
def list_invoices():
    guard(C.ALL_ROLES)
    rows = list(store.DB["invoices"].values())
    for key in ("placement_id", "community_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


@bp.post("/referral-invoices/<invoice_id>/issue")
def issue_invoice(invoice_id):
    uid, role = guard(["BillingSpecialist"])
    inv = V.lookup("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    V.get_body()
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_INVALID_STATE", "Invoice is not DRAFT.")
    placement = store.DB["placements"][inv["placement_id"]]
    if placement["residency_status"] not in ("MOVED_IN", "RESIDENT_CONFIRMED"):
        raise ApiError("ERR_PLACEMENT_NOT_MOVED_IN", "Placement has not moved in.")
    community = store.DB["communities"][inv["community_id"]]
    svc.append_ledger_entry(inv, placement, community, "ACCRUAL",
                            inv["final_fee_cents"], "Invoice issued")
    inv["issued_at"] = store.now_iso()
    inv["status"] = "ISSUED"
    placement["billing_status"] = "INVOICED"
    svc.touch(placement)
    svc.touch(inv)
    return E.ok(dump(inv))


@bp.post("/referral-invoices/<invoice_id>/accept")
def accept_invoice(invoice_id):
    uid, role = guard(["CommunityManager"])
    inv = V.lookup("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    V.get_body()
    if uid != inv["community_id"]:
        deny_ownership()
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_INVALID_STATE", "Invoice is not ISSUED.")
    inv["status"] = "ACCEPTED"
    svc.touch(inv)
    return E.ok(dump(inv))


@bp.post("/referral-invoices/<invoice_id>/dispute")
def dispute_invoice(invoice_id):
    uid, role = guard(["CommunityManager"])
    inv = V.lookup("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"dispute_reason", "claimed_rate_cents"}, PROTECTED["invoice"])
    dispute_reason = V.req_str(body, "dispute_reason")
    claimed_rate = V.req_int(body, "claimed_rate_cents", 1)
    if uid != inv["community_id"]:
        deny_ownership()
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_INVALID_STATE", "Invoice is not ISSUED.")
    if inv["adjustment_count"] >= C.MAX_DISPUTE_ROUNDS:
        raise ApiError("ERR_DISPUTE_LIMIT_EXCEEDED", "Dispute round limit reached.")
    inv["dispute_reason"] = dispute_reason
    inv["claimed_rate_cents"] = claimed_rate
    inv["status"] = "DISPUTED"
    svc.touch(inv)
    return E.ok(dump(inv))


@bp.post("/referral-invoices/<invoice_id>/adjust")
def adjust_invoice(invoice_id):
    uid, role = guard(["BillingSpecialist"])
    inv = V.lookup("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"adjusted_rate_cents", "note"}, PROTECTED["invoice"])
    adjusted_rate = V.req_int(body, "adjusted_rate_cents", 1)
    note = V.req_str(body, "note")
    if inv["status"] != "DISPUTED":
        raise ApiError("ERR_INVOICE_INVALID_STATE", "Invoice is not DISPUTED.")
    placement = store.DB["placements"][inv["placement_id"]]
    community = store.DB["communities"][inv["community_id"]]
    move_in = date.fromisoformat(placement["actual_move_in_date"])
    ratio = calc.proration_ratio(move_in)
    new_final = calc.referral_fee(adjusted_rate, community["referral_fee_pct"], ratio,
                                  placement["actual_care_level"], community["contract_tier"])
    delta = new_final - inv["final_fee_cents"]
    inv["final_fee_cents"] = new_final
    svc.append_ledger_entry(inv, placement, community, "ADJUSTMENT", delta, note)
    inv["adjustment_count"] = inv["adjustment_count"] + 1
    inv["issued_at"] = store.now_iso()
    inv["status"] = "ISSUED"
    svc.touch(inv)
    return E.ok(dump(inv))


@bp.post("/referral-invoices/<invoice_id>/pay")
def pay_invoice(invoice_id):
    uid, role = guard(["CommunityManager"])
    inv = V.lookup("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"amount_cents"}, PROTECTED["invoice"])
    amount = V.req_int(body, "amount_cents", 1)
    if uid != inv["community_id"]:
        deny_ownership()
    if inv["status"] != "ACCEPTED":
        raise ApiError("ERR_INVOICE_INVALID_STATE", "Invoice is not ACCEPTED.")
    if amount != inv["final_fee_cents"]:
        raise ApiError("ERR_INVOICE_AMOUNT_MISMATCH", "Payment amount does not match the fee.")
    placement = store.DB["placements"][inv["placement_id"]]
    community = store.DB["communities"][inv["community_id"]]
    svc.append_ledger_entry(inv, placement, community, "PAYMENT", -amount, "Payment received")
    inv["paid_amount_cents"] = amount
    inv["status"] = "PAID"
    placement["billing_status"] = "PAID"
    svc.touch(placement)
    svc.touch(inv)
    return E.ok(dump(inv))


@bp.post("/referral-invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    uid, role = guard(["BillingSpecialist"])
    inv = V.lookup("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"reason_code"}, PROTECTED["invoice"])
    reason_code = V.req_str(body, "reason_code")
    if inv["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError("ERR_INVOICE_INVALID_STATE", "Invoice cannot be voided in its state.")
    placement = store.DB["placements"][inv["placement_id"]]
    community = store.DB["communities"][inv["community_id"]]
    svc.append_ledger_entry(inv, placement, community, "WRITE_OFF",
                            -inv["final_fee_cents"], "Void: %s" % reason_code)
    inv["status"] = "VOIDED"
    placement["billing_status"] = "VOIDED"
    svc.touch(placement)
    svc.touch(inv)
    return E.ok(dump(inv))


# ===========================================================================
# Ledger entries
# ===========================================================================
@bp.get("/ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    guard(C.ALL_ROLES)
    e = V.lookup("ledger_entries", entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")
    return E.ok(dump(e))


@bp.get("/ledger-entries")
def list_ledger_entries():
    guard(C.ALL_ROLES)
    rows = list(store.DB["ledger_entries"].values())
    for key in ("invoice_id", "placement_id", "community_id", "entry_type"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


# ===========================================================================
# Satisfaction surveys
# ===========================================================================
@bp.post("/surveys")
def create_survey():
    uid, role = guard(["Family"])
    body = V.get_body()
    V.reject_protected(body, {"placement_id", "nps_score", "care_rating", "value_rating"},
                       PROTECTED["survey"])
    placement_id = V.req_str(body, "placement_id")
    nps = V.req_int(body, "nps_score", 0, 10)
    care = V.req_int(body, "care_rating", 1, 5)
    value = V.req_int(body, "value_rating", 1, 5)
    p = V.lookup("placements", placement_id, "ERR_PLACEMENT_NOT_FOUND")
    inquiry = store.DB["inquiries"][p["inquiry_id"]]
    if inquiry["family_id"] != uid:
        deny_ownership()
    for s in store.DB["surveys"].values():
        if s["placement_id"] == placement_id:
            raise ApiError("ERR_DUPLICATE_SURVEY", "A survey already exists for this placement.")
    if p["actual_move_in_date"] is None:
        raise ApiError("ERR_SURVEY_TOO_EARLY", "Placement has not moved in.")
    move_in = date.fromisoformat(p["actual_move_in_date"])
    days_after = (store.now_date() - move_in).days
    if days_after < C.SURVEY_ELIGIBLE_DAYS:
        raise ApiError("ERR_SURVEY_TOO_EARLY", "Survey submitted too early.")
    composite = calc.satisfaction_composite(nps, care, value)
    row = svc.new_row("surveys", {
        "placement_id": placement_id, "respondent_family_id": inquiry["family_id"],
        "community_id": p["community_id"], "days_after_move_in": days_after,
        "nps_score": nps, "care_rating": care, "value_rating": value,
        "composite_score": composite,
    }, versioned=False)
    community = store.DB["communities"][p["community_id"]]
    svc.recompute_community_rollup(community)
    return E.created(dump(row))


@bp.get("/surveys/<survey_id>")
def get_survey(survey_id):
    guard(C.ALL_ROLES)
    s = V.lookup("surveys", survey_id, "ERR_SURVEY_NOT_FOUND")
    return E.ok(dump(s))


@bp.get("/surveys")
def list_surveys():
    guard(C.ALL_ROLES)
    rows = list(store.DB["surveys"].values())
    for key in ("placement_id", "respondent_family_id", "community_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


# ===========================================================================
# Caseload assignments
# ===========================================================================
@bp.get("/caseload-assignments/<assignment_id>")
def get_assignment(assignment_id):
    guard(C.ALL_ROLES)
    a = V.lookup("assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    return E.ok(dump(a))


@bp.get("/caseload-assignments")
def list_assignments():
    guard(C.ALL_ROLES)
    rows = list(store.DB["assignments"].values())
    for key in ("advisor_id", "inquiry_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


# ===========================================================================
# Reports
# ===========================================================================
def _advisor_report(a):
    svc.recompute_advisor_fields(a)
    return {
        "advisor_id": a["id"],
        "active_caseload_count": a["active_caseload_count"],
        "caseload_capacity": a["caseload_capacity"],
        "headcount_load_index": float(a["headcount_load_index"]),
        "weighted_load_index": float(a["weighted_load_index"]),
        "total_active_assignments": a["active_caseload_count"],
    }


@bp.get("/reports/advisor-caseload")
def report_advisor_caseload():
    guard(["PlatformAdmin", "Advisor"])
    advisor_id = request.args.get("advisor_id")
    region_code = request.args.get("region_code")
    if advisor_id is not None:
        a = V.lookup("advisors", advisor_id, "ERR_ADVISOR_NOT_FOUND")
        return E.ok(_advisor_report(a))
    rows = list(store.DB["advisors"].values())
    if region_code is not None:
        rows = [r for r in rows if r["region_code"] == region_code]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    return E.ok_array([_advisor_report(a) for a in rows])


def _community_report(c):
    entries = [e for e in store.DB["ledger_entries"].values()
               if e["community_id"] == c["id"]]

    def total(kind):
        return sum(e["amount_cents"] for e in entries if e["entry_type"] == kind)

    placement_count = sum(1 for p in store.DB["placements"].values()
                          if p["community_id"] == c["id"])
    svc.recompute_community_rollup(c)
    return {
        "community_id": c["id"],
        "placement_count": placement_count,
        "accrued_fee_cents": total("ACCRUAL"),
        "payment_cents": total("PAYMENT"),
        "clawback_cents": total("CLAWBACK"),
        "write_off_cents": total("WRITE_OFF"),
        "fee_balance_cents": c["fee_balance_cents"],
        "avg_satisfaction_score": float(c["avg_satisfaction_score"]),
    }


@bp.get("/reports/community-referrals")
def report_community_referrals():
    uid, role = guard(["PlatformAdmin", "BillingSpecialist", "CommunityManager"])
    community_id = request.args.get("community_id")
    if role == "CommunityManager":
        if community_id is not None and community_id != uid:
            deny_ownership()
        community_id = community_id or uid
    if community_id is not None:
        c = V.lookup("communities", community_id, "ERR_COMMUNITY_NOT_FOUND")
        return E.ok(_community_report(c))
    rows = sorted(store.DB["communities"].values(), key=lambda r: (r["created_at"], r["_seq"]))
    return E.ok_array([_community_report(c) for c in rows])
