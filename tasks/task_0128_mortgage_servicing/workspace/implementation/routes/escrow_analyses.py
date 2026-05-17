"""Escrow analysis routes."""
from __future__ import annotations

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    err_escrow_baseline,
    err_invalid_state,
    err_resource_not_found,
)
from middleware import require_auth
from response import list_success, success
from services.calculations import escrow_projection
from services.loan_engine import bump
from services.serializers import escrow_analysis_view
from utils import midnight_utc, new_uuid, parse_iso

from routes._helpers import (
    enforce_borrower_owns_loan,
    get_int,
    get_json,
    get_loan_or_404,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("escrow_analyses", __name__)


@bp.post("/loans/<lid>/escrow-analyses")
@require_auth(["Servicer"])
def create_escrow_analysis(lid):
    loan = get_loan_or_404(lid)
    if loan["posture"] == "PAID_OFF":
        raise err_invalid_state("Cannot create escrow analysis on a PAID_OFF loan.")
    body = get_json()
    ad_raw = body.get("analysis_date")
    if ad_raw is None:
        raise err_escrow_baseline("analysis_date required")
    try:
        analysis_date = parse_iso(ad_raw)
    except Exception:
        raise err_escrow_baseline("Invalid analysis_date")
    starting_balance = get_int(body, "starting_balance_cents")
    if starting_balance is None:
        raise err_escrow_baseline("starting_balance_cents required")

    # Validation priority 22: baseline checks.
    if midnight_utc(analysis_date) < midnight_utc(loan["origination_date"]):
        raise err_escrow_baseline("analysis_date is earlier than origination_date.")
    if starting_balance != loan["escrow_balance_cents"]:
        raise err_escrow_baseline("starting_balance_cents does not match current escrow balance.")

    disbursements = [d for d in store.disbursements.values() if d["loan_id"] == lid]
    projection = escrow_projection(loan, analysis_date, starting_balance, disbursements)

    now = store.now()
    eid = new_uuid()
    record = {
        "id": eid,
        "loan_id": lid,
        "analysis_date": analysis_date,
        "status": "PROVISIONAL",
        "starting_balance_cents": starting_balance,
        "projected_disbursements_cents": projection["projected_disbursements_cents"],
        "required_cushion_cents": projection["required_cushion_cents"],
        "shortage_cents": projection["shortage_cents"],
        "surplus_cents": projection["surplus_cents"],
        "new_monthly_escrow_cents": projection["new_monthly_escrow_cents"],
        "finalized_at": None,
        "created_at": now,
    }
    store.escrow_analyses[eid] = record
    return success(escrow_analysis_view(record), 201)


@bp.post("/loans/<lid>/escrow-analyses/<eid>/finalize")
@require_auth(["Servicer"])
def finalize_escrow_analysis(lid, eid):
    loan = get_loan_or_404(lid)
    record = store.escrow_analyses.get(eid)
    if record is None or record["loan_id"] != lid:
        raise err_resource_not_found("EscrowAnalysis not found under loan.")
    with store.lock:
        if record["status"] != "PROVISIONAL":
            # PRD §3.3: "Finalisation is only permitted when the source
            # analysis is still PROVISIONAL ... otherwise the request is
            # rejected with ERR_INVALID_STATE." (ERR_ESCROW_ANALYSIS_CONFLICT
            # is reserved for the race between two distinct PROVISIONAL
            # records on the same loan — PRD §2.5.)
            raise err_invalid_state("Source analysis is not PROVISIONAL.")
        # Reject if any FINALIZED on this loan has analysis_date >= this.
        for other in store.escrow_analyses.values():
            if other["loan_id"] != lid or other["id"] == eid:
                continue
            if other["status"] == "FINALIZED" and midnight_utc(other["analysis_date"]) >= midnight_utc(
                record["analysis_date"]
            ):
                raise err_invalid_state(
                    "A FINALIZED analysis with a later or equal analysis_date already exists."
                )
        # Recompute projection at commit time from the current disbursement set.
        disbursements = [d for d in store.disbursements.values() if d["loan_id"] == lid]
        projection = escrow_projection(
            loan,
            record["analysis_date"],
            record["starting_balance_cents"],
            disbursements,
        )
        record["projected_disbursements_cents"] = projection["projected_disbursements_cents"]
        record["required_cushion_cents"] = projection["required_cushion_cents"]
        record["shortage_cents"] = projection["shortage_cents"]
        record["surplus_cents"] = projection["surplus_cents"]
        record["new_monthly_escrow_cents"] = projection["new_monthly_escrow_cents"]

        now = store.now()
        record["status"] = "FINALIZED"
        record["finalized_at"] = now

        # Supersede prior FINALIZED and PROVISIONAL analyses on this loan.
        for other in store.escrow_analyses.values():
            if other["loan_id"] != lid or other["id"] == eid:
                continue
            if other["status"] in ("FINALIZED", "PROVISIONAL"):
                other["status"] = "SUPERSEDED"

        loan["monthly_escrow_payment_cents"] = projection["new_monthly_escrow_cents"]
        bump(loan, now)

        # Emit SURPLUS_REFUND disbursement if surplus > $50.
        if projection["surplus_cents"] > 5000:
            from datetime import timedelta

            rid = new_uuid()
            refund = {
                "id": rid,
                "loan_id": lid,
                "type": "SURPLUS_REFUND",
                "scheduled_date": now + timedelta(days=30),
                "amount_cents": projection["surplus_cents"],
                "status": "SCHEDULED",
                "paid_at": None,
                "failure_reason": None,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            store.disbursements[rid] = refund

    return success(escrow_analysis_view(record), 200)


@bp.get("/loans/<lid>/escrow-analyses")
@require_auth(["Servicer", "Borrower"])
def list_escrow_analyses(lid):
    loan = get_loan_or_404(lid)
    enforce_borrower_owns_loan(loan)
    limit, offset = parse_pagination()
    items = [e for e in store.escrow_analyses.values() if e["loan_id"] == lid]
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    items = sort_by_created_at(items)
    page = paginate(items, limit, offset)
    return list_success([escrow_analysis_view(e) for e in page], limit, offset, len(items), 200)
