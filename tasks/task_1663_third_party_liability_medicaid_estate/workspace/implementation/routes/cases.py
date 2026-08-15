"""TplCase endpoints (PRD §3.2) plus the accounting summary (§3.5)."""

from datetime import timedelta

from flask import Blueprint, request

from db import CASES, EXPENSE_CLAIMS, MEMBERS, POSTINGS, SETTLEMENTS, new_entity, now_iso, pub, touch
from errors import (
    ApiError,
    ERR_DUPLICATE_EPISODE_CASE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import (
    TERMINAL_CASE_STATUSES,
    EPISODE_WINDOW_DAYS,
    SOL_YEARS,
    recompute_case_total_paid_claims,
)
from util import add_years, body, paginate, parse_date, req_date, req_enum, req_int, req_str

bp = Blueprint("cases", __name__)

LITIGATION_EVENTS = ("FILE_SUIT", "RECORD_JUDGMENT", "RECORD_DISMISSAL")


@bp.post("/recovery/cases")
@require_roles("RecoverySpecialist")
def create_case():
    b = body()
    member_id = req_str(b, "member_id")
    attorney_name = req_str(b, "attorney_name")
    attorney_email = req_str(b, "attorney_email")
    injury_date = req_date(b, "injury_date")
    third_party_insurer = req_str(b, "third_party_insurer")
    # Existence: the injured beneficiary must be a registered member.
    if member_id not in MEMBERS:
        raise ApiError(ERR_NOT_FOUND, "Member not found", 404)
    # §3.2: half-open episode window [existing.injury_date, +90 days) against
    # the member's non-terminal cases; the exact end date is permitted.
    new_injury = parse_date(injury_date)
    for existing in CASES.values():
        if existing["member_id"] != member_id:
            continue
        if existing["status"] in TERMINAL_CASE_STATUSES:
            continue
        start = parse_date(existing["injury_date"])
        if start <= new_injury < start + timedelta(days=EPISODE_WINDOW_DAYS):
            raise ApiError(
                ERR_DUPLICATE_EPISODE_CASE,
                "Injury date overlaps an existing non-terminal case episode window",
                409,
            )
    c = new_entity()
    c.update(
        {
            "member_id": member_id,
            "attorney_name": attorney_name,
            "attorney_email": attorney_email,
            "injury_date": injury_date,
            "third_party_insurer": third_party_insurer,
            "status": "IDENTIFIED",
            "litigation_status": "NO_SUIT",
            "sol_date": add_years(new_injury, SOL_YEARS).isoformat(),
            "attorney_notified_at": None,
            "total_paid_claims_cents": 0,
            "total_recovered_cents": 0,
        }
    )
    CASES[c["id"]] = c
    return success_object(pub(c), 201)


@bp.get("/recovery/cases/<string:caseId>")
@require_roles(*ALL_ROLES)
def get_case(caseId):
    c = CASES.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    return success_object(pub(c))


@bp.get("/recovery/cases")
@require_roles(*ALL_ROLES)
def list_cases():
    member_id = request_arg("member_id")
    status = request_arg("status")
    items = []
    for c in CASES.values():
        if member_id is not None and c["member_id"] != member_id:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(c)
    ordered, limit, offset = paginate(items)
    page = [pub(c) for c in ordered[offset : offset + limit]]
    return success_list(page, limit, offset, len(ordered))


def request_arg(name):
    return request.args.get(name)


@bp.post("/recovery/cases/<string:caseId>/notify-attorney")
@require_roles("RecoverySpecialist")
def notify_attorney(caseId):
    c = CASES.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    # §3.2: recorded only from IDENTIFIED; any other status is a generic error.
    if c["status"] != "IDENTIFIED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Attorney notification requires the case to be IDENTIFIED",
            409,
        )
    c["status"] = "ATTORNEY_NOTIFIED"
    c["attorney_notified_at"] = now_iso()
    touch(c)
    return success_object(pub(c))


@bp.post("/recovery/cases/<string:caseId>/expense-claims")
@require_roles("RecoverySpecialist")
def add_expense_claim(caseId):
    b = body()
    service_date = req_date(b, "service_date")
    paid_amount_cents = req_int(b, "paid_amount_cents", minimum=0, exclusive_min=True)
    claim_reference = req_str(b, "claim_reference")
    c = CASES.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    claim = new_entity()
    claim.update(
        {
            "case_id": caseId,
            "service_date": service_date,
            "paid_amount_cents": paid_amount_cents,
            "claim_reference": claim_reference,
            # §3.2: true exactly when service_date >= injury_date (calendar dates).
            "included_in_lien_basis": parse_date(service_date) >= parse_date(c["injury_date"]),
        }
    )
    EXPENSE_CLAIMS[claim["id"]] = claim
    # Derived balance recomputed on every contributing mutation (§2.9); the
    # addition increments the case's version (§3.2).
    recompute_case_total_paid_claims(c)
    touch(c)
    return success_object(pub(claim), 201)


@bp.get("/recovery/cases/<string:caseId>/expense-claims")
@require_roles(*ALL_ROLES)
def list_expense_claims(caseId):
    c = CASES.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    items = [cl for cl in EXPENSE_CLAIMS.values() if cl["case_id"] == caseId]
    ordered, limit, offset = paginate(items)
    page = [pub(cl) for cl in ordered[offset : offset + limit]]
    return success_list(page, limit, offset, len(ordered))


@bp.post("/recovery/cases/<string:caseId>/litigation")
@require_roles("RecoverySpecialist")
def record_litigation(caseId):
    b = body()
    event = req_enum(b, "litigation_event", LITIGATION_EVENTS)
    c = CASES.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    lit = c["litigation_status"]
    if event == "FILE_SUIT":
        # Initial filing and refile after dismissal are accepted only while the
        # case's resolution track is non-terminal (§3.2).
        if c["status"] in TERMINAL_CASE_STATUSES:
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "Litigation events are blocked on a terminal case",
                409,
            )
        if lit not in ("NO_SUIT", "SUIT_DISMISSED"):
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "FILE_SUIT requires litigation status NO_SUIT or SUIT_DISMISSED",
                409,
            )
        c["litigation_status"] = "SUIT_FILED"
    elif event == "RECORD_JUDGMENT":
        if lit != "SUIT_FILED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "RECORD_JUDGMENT requires litigation status SUIT_FILED",
                409,
            )
        c["litigation_status"] = "JUDGMENT"
    else:  # RECORD_DISMISSAL
        if lit != "SUIT_FILED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "RECORD_DISMISSAL requires litigation status SUIT_FILED",
                409,
            )
        c["litigation_status"] = "SUIT_DISMISSED"
    touch(c)
    return success_object(pub(c))


@bp.post("/recovery/cases/<string:caseId>/close")
@require_roles("RecoverySpecialist", "RecoverySupervisor")
def close_case(caseId):
    c = CASES.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    # §3.2: close with no recovery only from IDENTIFIED or ATTORNEY_NOTIFIED.
    if c["status"] not in ("IDENTIFIED", "ATTORNEY_NOTIFIED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Close requires the case to be IDENTIFIED or ATTORNEY_NOTIFIED",
            409,
        )
    c["status"] = "CLOSED_NO_RECOVERY"
    touch(c)
    return success_object(pub(c))


@bp.get("/recovery/cases/<string:caseId>/accounting-summary")
@require_roles("RecoveryAccountant", "RecoverySupervisor", "SystemAdmin")
def accounting_summary(caseId):
    c = CASES.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    # §3.5: POSTED postings only; totals are the SUM OF PER-POSTING ROUNDED
    # commissions, never round(sum(unrounded)) (§2.6).
    total_recovered = 0
    total_commission = 0
    posting_count = 0
    for p in POSTINGS.values():
        if p["status"] != "POSTED":
            continue
        s = SETTLEMENTS.get(p["settlement_id"])
        if s is None or s["case_id"] != caseId:
            continue
        total_recovered += p["gross_recovery_cents"]
        total_commission += p["commission_cents"]
        posting_count += 1
    return success_object(
        {
            "total_recovered_cents": total_recovered,
            "total_commission_cents": total_commission,
            "total_net_to_state_cents": total_recovered - total_commission,
            "posting_count": posting_count,
        }
    )
