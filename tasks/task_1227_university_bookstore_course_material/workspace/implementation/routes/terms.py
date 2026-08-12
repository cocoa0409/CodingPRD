"""AcademicTerm lifecycle (PRD §3.1) including CASCADE-1 at adoption close,
the IA census-billing cascade, and the term-close sweeps."""

from flask import Blueprint, request

from db import store, now, new_entity, touch, pub
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_CENSUS_NOT_REACHED,
)
from middleware import (
    require_roles, body, get_str, get_int, get_dt, get_or_404, ALL_ROLES,
)
from response import success, list_response

bp = Blueprint("terms", __name__)

TERM_DT_FIELDS = [
    "registration_open_at", "price_posting_deadline_at", "adoption_deadline_at",
    "aid_charge_window_start_at", "aid_charge_window_end_at",
    "add_drop_return_deadline_at", "census_at", "ia_opt_out_deadline_at",
    "buyback_window_start_at", "buyback_window_end_at",
]


@bp.post("/bookstore/terms")
def create_term():
    require_roles("PlatformAdmin")
    data = body()
    code = get_str(data, "code")
    length_weeks = get_int(data, "length_weeks", min_val=1)
    dts = {k: get_dt(data, k) for k in TERM_DT_FIELDS}
    buy_budget_cents = get_int(data, "buy_budget_cents", min_val=0)
    if any(t["code"] == code for t in store.terms.values()):
        raise ApiError(ERR_VALIDATION, 400, "code must be unique")
    term = new_entity()
    term.update({
        "code": code,
        "length_weeks": length_weeks,
        "buy_budget_cents": buy_budget_cents,
        "status": "SETUP",
        "noncompliant_section_count": 0,
        "compliance_posture": "CLEAR",
    })
    term.update(dts)
    store.terms[term["id"]] = term
    return success(pub(term), status=201)


@bp.get("/bookstore/terms")
def list_terms():
    require_roles(*ALL_ROLES)
    status = request.args.get("status")
    items = [t for t in store.terms.values()
             if status is None or t["status"] == status]
    return list_response(items)


@bp.get("/bookstore/terms/<tid>")
def get_term(tid):
    require_roles(*ALL_ROLES)
    return success(pub(get_or_404(store.terms, tid, "term")))


def _transition(tid, roles, from_state, to_state):
    uid_role = require_roles(*roles)
    term = get_or_404(store.terms, tid, "term")
    if term["status"] != from_state:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "term not in {} for this transition".format(from_state))
    return uid_role, term


@bp.post("/bookstore/terms/<tid>/open-adoption")
def open_adoption(tid):
    _, term = _transition(tid, ("PlatformAdmin",), "SETUP", "ADOPTION_OPEN")
    term["status"] = "ADOPTION_OPEN"
    touch(term)
    return success(pub(term))


@bp.post("/bookstore/terms/<tid>/close-adoption")
def close_adoption(tid):
    _, term = _transition(tid, ("BookstoreManager",), "ADOPTION_OPEN", "ADOPTION_CLOSED")
    # CASCADE-1 hop 1: sweep DRAFT/RETURNED adoptions of this term's sections
    # to EXPIRED; each flip recomputes its section's compliance (hop 2); each
    # section flip recomputes the term count/posture (hop 3).
    affected_section_ids = []
    for ad in store.adoptions.values():
        sec = store.sections.get(ad["section_id"])
        if sec is None or sec["term_id"] != term["id"]:
            continue
        if ad["status"] in ("DRAFT", "RETURNED"):
            ad["status"] = "EXPIRED"
            touch(ad)
            if sec["id"] not in affected_section_ids:
                affected_section_ids.append(sec["id"])
    for sid in affected_section_ids:
        sec = store.sections[sid]
        ads = [a for a in store.adoptions.values() if a["section_id"] == sid]
        has_approved = any(a["status"] == "APPROVED" for a in ads)
        has_late = any(a["late_flag"] for a in ads)
        new_status = "NON_COMPLIANT" if (not has_approved or has_late) else "COMPLIANT"
        if sec["compliance_status"] != new_status:
            sec["compliance_status"] = new_status
            touch(sec)
    count = sum(
        1 for s in store.sections.values()
        if s["term_id"] == term["id"] and s["compliance_status"] == "NON_COMPLIANT"
    )
    term["noncompliant_section_count"] = count
    term["compliance_posture"] = "RESTRICTED" if count > 0 else "CLEAR"
    term["status"] = "ADOPTION_CLOSED"
    touch(term)
    return success(pub(term))


@bp.post("/bookstore/terms/<tid>/open-sales")
def open_sales(tid):
    _, term = _transition(tid, ("BookstoreManager",), "ADOPTION_CLOSED", "SALES_OPEN")
    term["status"] = "SALES_OPEN"
    touch(term)
    return success(pub(term))


@bp.post("/bookstore/terms/<tid>/run-census-billing")
def run_census_billing(tid):
    _, term = _transition(tid, ("BookstoreManager",), "SALES_OPEN", "CENSUS_DONE")
    n = now()
    if n < term["census_at"]:
        raise ApiError(ERR_CENSUS_NOT_REACHED, 422, "census instant not reached")
    in_window = (term["aid_charge_window_start_at"] <= n
                 <= term["aid_charge_window_end_at"])
    for ch in store.ia_charges.values():
        if ch["term_id"] != term["id"] or ch["status"] != "PENDING":
            continue
        sec = store.sections[ch["section_id"]]
        if sec["status"] != "LOCKED":
            continue
        # calculations.ia_billing_split
        student = store.students[ch["student_id"]]
        aid_applied = (min(ch["fee_cents"], student["aid_balance_cents"])
                       if in_window else 0)
        ch["aid_applied_cents"] = aid_applied
        ch["balance_due_cents"] = ch["fee_cents"] - aid_applied
        ch["status"] = "BILLED"
        student["aid_balance_cents"] -= aid_applied
        touch(student)
        touch(ch)
    term["status"] = "CENSUS_DONE"
    touch(term)
    return success(pub(term))


@bp.post("/bookstore/terms/<tid>/open-buyback")
def open_buyback(tid):
    _, term = _transition(tid, ("BookstoreManager",), "CENSUS_DONE", "BUYBACK_OPEN")
    term["status"] = "BUYBACK_OPEN"
    touch(term)
    return success(pub(term))


@bp.post("/bookstore/terms/<tid>/close")
def close_term(tid):
    _, term = _transition(tid, ("BookstoreManager",), "BUYBACK_OPEN", "TERM_CLOSED")
    n = now()
    # expire stale QUOTED buyback tickets
    for t in store.buyback_tickets.values():
        if t["status"] == "QUOTED" and t["quote_valid_until"] <= n:
            t["status"] = "EXPIRED"
            touch(t)
    # close this term's open orders
    for o in store.orders.values():
        if o["term_id"] == term["id"] and o["status"] in ("SETTLED", "PARTIALLY_REFUNDED"):
            o["status"] = "CLOSED"
            touch(o)
    # close this term's LOCKED sections
    for s in store.sections.values():
        if s["term_id"] == term["id"] and s["status"] == "LOCKED":
            s["status"] = "CLOSED"
            touch(s)
    term["status"] = "TERM_CLOSED"
    touch(term)
    return success(pub(term))
