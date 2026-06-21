"""Case routes (PRD §3.1, §3.3, §3.8, §3.9)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from db import (
    cases, clients, damages_items, demand_letters, settlement_offers,
    medical_liens, court_events, stamp_common, bump, parse_iso_dt,
    current_clock_dt, now_iso,
)
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CROSS_ENTITY_STATE,
    ERR_RETAINER_MISSING,
)
from middleware import require_auth, get_json_body, current_role
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_str, require_enum, require_iso8601,
    get_or_404_path, get_or_fk_404, assert_sol_not_expired, sol_iso,
)
from services.calculations import compute_damages_summary
from services.cascades import expire_pending_offers


bp = Blueprint("cases", __name__)


VALID_JURISDICTIONS = {"CA", "NY", "TX", "FL", "IL"}
VALID_CASE_STATUSES = {
    "INTAKE", "ACTIVE", "DEMAND_SENT", "IN_NEGOTIATION",
    "LITIGATION", "SETTLED", "CLOSED", "ABANDONED",
}


def case_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "client_id": c["client_id"],
        "accident_date": c["accident_date"],
        "jurisdiction": c["jurisdiction"],
        "status": c["status"],
        "statute_of_limitations_date": c["statute_of_limitations_date"],
        "sol_tolled_days": c["sol_tolled_days"],
        "filed_in_court": c.get("filed_in_court", False),
        "included_damages_total_cents": c.get("included_damages_total_cents", 0),
        "gross_settlement_cents": c.get("gross_settlement_cents"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def recompute_included_damages_total(case_id: str) -> int:
    total = 0
    for di in damages_items.values():
        if di["case_id"] == case_id and di["status"] == "INCLUDED":
            total += int(di["amount_cents"])
    if case_id in cases:
        cases[case_id]["included_damages_total_cents"] = total
    return total


@bp.post("/cases")
def create_case():
    require_auth({"Paralegal"})()
    body = get_json_body()
    client_id = require_str(body, "client_id")
    accident_date = require_iso8601(body, "accident_date")
    jurisdiction = require_enum(body, "jurisdiction", VALID_JURISDICTIONS)

    # sol_tolled_days optional, default 0; must be >= 0.
    sol_tolled = body.get("sol_tolled_days", 0)
    if isinstance(sol_tolled, bool) or not isinstance(sol_tolled, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "sol_tolled_days must be an integer")
    if sol_tolled < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "sol_tolled_days must be >= 0")

    # FK existence
    get_or_fk_404(clients, client_id, "Client")

    # accident_date must be in the past (PRD §3.1: "must already be in the past")
    accident_dt = parse_iso_dt(accident_date)
    if accident_dt >= current_clock_dt():
        raise APIError(ERR_INVALID_REQUEST, 400, "accident_date must be in the past")

    c: dict = {
        "client_id": client_id,
        "accident_date": accident_date,
        "jurisdiction": jurisdiction,
        "sol_tolled_days": sol_tolled,
        "status": "INTAKE",
        "filed_in_court": False,
        "included_damages_total_cents": 0,
        "gross_settlement_cents": None,
        "statute_of_limitations_date": None,  # filled in below
    }
    stamp_common(c)
    c["statute_of_limitations_date"] = sol_iso(c)
    cases[c["id"]] = c
    return ok_object(case_view(c), 201)


@bp.get("/cases/<cid>")
def get_case(cid):
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    c = get_or_404_path(cases, cid, "Case")
    # Side effect: sweep PENDING offers on this case past 30 days.
    expire_pending_offers(case_id_filter=cid)
    return ok_object(case_view(c), 200)


@bp.get("/cases")
def list_cases():
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    limit, offset = paginate_params(request.args)
    status_filter = request.args.get("status")
    client_filter = request.args.get("client_id")
    jur_filter = request.args.get("jurisdiction")

    items = list(cases.values())
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    if client_filter is not None:
        items = [c for c in items if c["client_id"] == client_filter]
    if jur_filter is not None:
        items = [c for c in items if c["jurisdiction"] == jur_filter]
    items.sort(key=lambda c: c["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([case_view(c) for c in page], limit, offset, total, 200)


@bp.post("/cases/<cid>/activate")
def activate_case(cid):
    require_auth({"Attorney"})()
    c = get_or_404_path(cases, cid, "Case")
    if c["status"] != "INTAKE":
        raise APIError(ERR_INVALID_STATE, 409, "Case must be in INTAKE to activate")
    # SOL check before retainer check? Priority table:
    #   priority 7: ERR_STATUTE_EXPIRED
    #   priority 9: ERR_RETAINER_MISSING
    # So SOL fires first.
    assert_sol_not_expired(c)
    client = clients.get(c["client_id"])
    if client is None or not client.get("retainer_signed"):
        raise APIError(ERR_RETAINER_MISSING, 422, "Client retainer has not been signed")
    c["status"] = "ACTIVE"
    bump(c)
    return ok_object(case_view(c), 200)


@bp.post("/cases/<cid>/abandon")
def abandon_case(cid):
    require_auth({"Attorney", "ManagingPartner"})()
    c = get_or_404_path(cases, cid, "Case")
    role = current_role()
    if c["status"] == "INTAKE":
        # Either Attorney or ManagingPartner may abandon from INTAKE per PRD
        # §3.1: "from INTAKE by an Attorney, or from ACTIVE by a ManagingPartner".
        # PRD says INTAKE -> ABANDONED is Attorney's path; scaffold lists
        # only Attorney in §1.2 transition. RBAC table says shared
        # operation between Attorney and ManagingPartner. PRD is the
        # authority — INTAKE actor is Attorney only.
        if role != "Attorney":
            raise APIError(
                ERR_INVALID_STATE, 409,
                "Only an Attorney can abandon an INTAKE case",
            )
    elif c["status"] == "ACTIVE":
        # PRD §3.1: from ACTIVE only a ManagingPartner abandons.
        if role != "ManagingPartner":
            raise APIError(
                ERR_INVALID_STATE, 409,
                "Only a ManagingPartner can abandon an ACTIVE case",
            )
    else:
        raise APIError(ERR_INVALID_STATE, 409,
                       "Case must be INTAKE or ACTIVE to abandon")
    c["status"] = "ABANDONED"
    bump(c)
    return ok_object(case_view(c), 200)


@bp.post("/cases/<cid>/file-suit")
def file_suit(cid):
    require_auth({"ManagingPartner"})()
    c = get_or_404_path(cases, cid, "Case")
    if c["status"] != "IN_NEGOTIATION":
        raise APIError(ERR_INVALID_STATE, 409, "Case must be in IN_NEGOTIATION to file suit")
    if c.get("filed_in_court", False):
        raise APIError(ERR_INVALID_STATE, 409, "Case has already been filed in court")
    assert_sol_not_expired(c)

    c["status"] = "LITIGATION"
    c["filed_in_court"] = True

    # Create a FILING court event with status=OCCURRED at the current clock.
    ev: dict = {
        "case_id": cid,
        "event_type": "FILING",
        "scheduled_at": db.get_current_utc(),
        "duration_minutes": 60,
        "status": "OCCURRED",
    }
    stamp_common(ev)
    court_events[ev["id"]] = ev

    bump(c)
    return ok_object(case_view(c), 200)


@bp.post("/cases/<cid>/close")
def close_case(cid):
    require_auth({"ManagingPartner"})()
    c = get_or_404_path(cases, cid, "Case")
    if c["status"] != "SETTLED":
        raise APIError(ERR_INVALID_STATE, 409, "Case must be SETTLED to close")
    # Cross-entity: disbursement RELEASED + every lien PAID.
    from db import disbursements
    disb = next((d for d in disbursements.values() if d["case_id"] == cid), None)
    if disb is None or disb["status"] != "RELEASED":
        raise APIError(ERR_CROSS_ENTITY_STATE, 409,
                       "Disbursement for this case must be RELEASED")
    liens = [l for l in medical_liens.values() if l["case_id"] == cid]
    for l in liens:
        if l["status"] != "PAID":
            raise APIError(ERR_CROSS_ENTITY_STATE, 409,
                           "Every MedicalLien on this case must be PAID")
    c["status"] = "CLOSED"
    bump(c)
    return ok_object(case_view(c), 200)


@bp.get("/cases/<cid>/damages-summary")
def damages_summary(cid):
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    c = get_or_404_path(cases, cid, "Case")
    included = [
        di for di in damages_items.values()
        if di["case_id"] == cid and di["status"] == "INCLUDED"
    ]
    sums = compute_damages_summary(included)
    return ok_object({
        "case_id": cid,
        "included_damages_total_cents": sums["included_total"],
        "gross_economic_only_cents": sums["economic_only"],
        "gross_full_model_cents": sums["full_model"],
    }, 200)
