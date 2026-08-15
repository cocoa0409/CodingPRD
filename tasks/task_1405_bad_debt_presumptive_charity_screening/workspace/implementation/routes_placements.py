"""EarlyOutPlacement and CollectionAgencyPlacement endpoints (PRD 3.4, 3.5)."""

from datetime import date, timedelta

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_ACTIVE_PLACEMENT_EXISTS,
    ERR_CHARITY_BLOCKS,
    ERR_INVALID_REQUEST,
    ERR_NOT_AGENCY_BUCKET,
    ERR_NOT_EARLY_OUT_BUCKET,
    ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT,
    ERR_RECALL_DEADLINE_PASSED,
    ERR_RECALL_WINDOW_STILL_OPEN,
    invalid_state,
    not_found,
)
from middleware import (
    ROLE_AGENCY,
    ROLE_COLLECTOR,
    ROLE_OFFICER,
    authenticate,
)
from response import ok_list, ok_object
from services import (
    AGENCY_RECALL_WINDOW_DAYS,
    EARLY_OUT_RECALL_DAYS,
    REQUIRED_STATEMENTS_BEFORE_AGENCY,
    active_agency_placement,
    active_early_out,
    agency_recall_fee_cents,
    eligible_evaluated_screening,
    open_dispute,
    serialize_agency_placement,
    serialize_early_out,
    statements_sent_count,
)
from util import (
    base_record,
    get_body,
    now_iso,
    paginate,
    req_int,
    req_str,
    today,
    touch,
)

bp = Blueprint("placements", __name__)

_EO_READ_ROLES = [ROLE_COLLECTOR, ROLE_OFFICER]
_AG_READ_ROLES = [ROLE_COLLECTOR, ROLE_OFFICER, ROLE_AGENCY]


def get_early_out_or_404(placement_id):
    p = db.early_out_placements.get(placement_id)
    if p is None:
        raise not_found("early-out placement not found")
    return p


def get_agency_placement_or_404(placement_id):
    p = db.agency_placements.get(placement_id)
    if p is None:
        raise not_found("collection agency placement not found")
    return p


def _req_fee_bps(b):
    fee = req_int(b, "contingency_fee_bps")
    if fee < 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "contingency_fee_bps must be >= 0", 400)
    return fee


# ---------------------------------------------------------------------------
# Early-out placements
# ---------------------------------------------------------------------------

@bp.post("/self-pay/early-out-placements")
def create_early_out_placement():
    authenticate([ROLE_COLLECTOR])
    b = get_body()
    account_id = req_str(b, "account_id")
    from routes_accounts import get_account_or_404
    account = get_account_or_404(account_id)
    vendor_name = req_str(b, "vendor_name")
    fee_bps = _req_fee_bps(b)

    # state precondition (priority 6)
    if account["status"] != "OPEN":
        raise invalid_state("early-out placement requires account status OPEN")
    # charity-eligibility guard (priority 10)
    if eligible_evaluated_screening(account_id) is not None:
        raise ApiError(
            ERR_CHARITY_BLOCKS,
            "an evaluated charity-eligible screening blocks early-out placement",
            409,
        )
    # aging-band prerequisite (priority 11)
    if account["aging_bucket"] not in ("BUCKET_30", "BUCKET_60"):
        raise ApiError(
            ERR_NOT_EARLY_OUT_BUCKET,
            "early-out placement requires aging bucket BUCKET_30 or BUCKET_60",
            409,
        )
    if active_early_out(account_id) is not None:
        raise ApiError(ERR_ACTIVE_PLACEMENT_EXISTS,
                       "an ACTIVE early-out placement already exists", 409)

    gl = date.fromisoformat(account["guarantor_liability_date"])
    rec = base_record()
    rec.update({
        "account_id": account_id,
        "vendor_name": vendor_name,
        "placement_balance_cents": account["current_balance_cents"],
        "contingency_fee_bps": fee_bps,
        "placed_at": now_iso(),
        "recall_deadline": (gl + timedelta(days=EARLY_OUT_RECALL_DAYS)).isoformat(),
        "status": "ACTIVE",
    })
    db.early_out_placements[rec["id"]] = rec
    account["status"] = "IN_EARLY_OUT"
    touch(account)
    return ok_object(serialize_early_out(rec), 201)


@bp.get("/self-pay/early-out-placements/<placement_id>")
def get_early_out(placement_id):
    authenticate(_EO_READ_ROLES)
    return ok_object(serialize_early_out(get_early_out_or_404(placement_id)))


@bp.get("/self-pay/accounts/<account_id>/early-out-placements")
def list_early_out_for_account(account_id):
    authenticate(_EO_READ_ROLES)
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = [p for p in db.early_out_placements.values()
             if p["account_id"] == account_id]
    page, meta = paginate(items)
    return ok_list([serialize_early_out(p) for p in page], meta)


@bp.post("/self-pay/early-out-placements/<placement_id>/recall")
def recall_early_out(placement_id):
    authenticate([ROLE_COLLECTOR])
    p = get_early_out_or_404(placement_id)
    if p["status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE early-out placement can be recalled")
    if today() > date.fromisoformat(p["recall_deadline"]):
        raise ApiError(ERR_RECALL_DEADLINE_PASSED,
                       "early-out recall attempted after recall_deadline", 409)
    p["status"] = "RECALLED"
    touch(p)
    account = db.accounts.get(p["account_id"])
    if account is not None and account["status"] == "IN_EARLY_OUT":
        account["status"] = "OPEN"
        touch(account)
    return ok_object(serialize_early_out(p))


# ---------------------------------------------------------------------------
# Collection agency placements
# ---------------------------------------------------------------------------

@bp.post("/self-pay/collection-agency-placements")
def create_agency_placement():
    authenticate([ROLE_COLLECTOR])
    b = get_body()
    account_id = req_str(b, "account_id")
    from routes_accounts import get_account_or_404
    account = get_account_or_404(account_id)
    agency_name = req_str(b, "agency_name")
    fee_bps = _req_fee_bps(b)

    # state precondition (priority 6): escalation path from IN_EARLY_OUT or
    # direct path from OPEN
    if account["status"] not in ("OPEN", "IN_EARLY_OUT"):
        raise invalid_state(
            "agency placement requires account status OPEN or IN_EARLY_OUT")
    escalation = account["status"] == "IN_EARLY_OUT"
    eop = active_early_out(account_id) if escalation else None
    if escalation and eop is None:
        raise invalid_state("account is IN_EARLY_OUT but has no ACTIVE "
                            "early-out placement")
    if active_agency_placement(account_id) is not None:
        raise ApiError(ERR_ACTIVE_PLACEMENT_EXISTS,
                       "an ACTIVE collection agency placement already exists", 409)
    # open-dispute guard (priority 9)
    if open_dispute(account_id) is not None:
        raise ApiError(ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT,
                       "an OPEN patient dispute blocks agency placement", 409)
    # charity-eligibility guard (priority 10)
    if eligible_evaluated_screening(account_id) is not None:
        raise ApiError(
            ERR_CHARITY_BLOCKS,
            "an evaluated charity-eligible screening blocks agency placement",
            409,
        )
    if escalation:
        # escalation requires the early-out recall deadline to have passed
        if today() <= date.fromisoformat(eop["recall_deadline"]):
            raise ApiError(
                ERR_RECALL_WINDOW_STILL_OPEN,
                "escalation requires the logical clock date to be after the "
                "early-out recall_deadline",
                409,
            )
    else:
        # direct path: deepest aging band + statement-cycle minimum
        if account["aging_bucket"] != "BUCKET_120_PLUS":
            raise ApiError(
                ERR_NOT_AGENCY_BUCKET,
                "direct agency placement requires aging bucket BUCKET_120_PLUS",
                409,
            )
        if statements_sent_count(account_id) < REQUIRED_STATEMENTS_BEFORE_AGENCY:
            raise ApiError(
                "ERR_INSUFFICIENT_STATEMENT_CYCLE",
                "statements_sent_count has not reached the agency referral "
                "minimum",
                409,
            )

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "agency_name": agency_name,
        "placement_balance_cents": account["current_balance_cents"],
        "contingency_fee_bps": fee_bps,
        "placed_at": now_iso(),
        "recall_window_closes_at": (
            today() + timedelta(days=AGENCY_RECALL_WINDOW_DAYS)).isoformat(),
        "credit_reported_at": None,
        "status": "ACTIVE",
    })
    db.agency_placements[rec["id"]] = rec
    if escalation:
        eop["status"] = "ESCALATED_TO_AGENCY"
        touch(eop)
    account["status"] = "IN_COLLECTIONS"
    account["credit_reporting_status"] = "REPORTABLE"
    touch(account)
    return ok_object(serialize_agency_placement(rec), 201)


@bp.get("/self-pay/collection-agency-placements/<placement_id>")
def get_agency_placement(placement_id):
    authenticate(_AG_READ_ROLES)
    return ok_object(serialize_agency_placement(
        get_agency_placement_or_404(placement_id)))


@bp.get("/self-pay/accounts/<account_id>/collection-agency-placements")
def list_agency_placements_for_account(account_id):
    authenticate(_AG_READ_ROLES)
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = [p for p in db.agency_placements.values()
             if p["account_id"] == account_id]
    page, meta = paginate(items)
    return ok_list([serialize_agency_placement(p) for p in page], meta)


@bp.post("/self-pay/collection-agency-placements/<placement_id>/recall")
def recall_agency_placement(placement_id):
    authenticate([ROLE_COLLECTOR])
    p = get_agency_placement_or_404(placement_id)
    if p["status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE agency placement can be recalled")
    if today() <= date.fromisoformat(p["recall_window_closes_at"]):
        p["status"] = "RECALLED_NO_FEE"
    else:
        # recall fee is computed for audit only: no balance, recovery, or
        # write-off mutation; its observable footprint is the terminal status
        p["status"] = "RECALLED_WITH_FEE"
        p["_recall_fee_cents"] = agency_recall_fee_cents(p)
    touch(p)
    account = db.accounts.get(p["account_id"])
    if account is not None and account["status"] == "IN_COLLECTIONS":
        account["status"] = "OPEN"
        # credit_reporting_status is left as-is: bureau deletion is a manual
        # step outside this API
        touch(account)
    return ok_object(serialize_agency_placement(p))


@bp.post("/self-pay/collection-agency-placements/<placement_id>/mark-credit-reported")
def mark_credit_reported(placement_id):
    authenticate([ROLE_AGENCY])
    p = get_agency_placement_or_404(placement_id)
    if p["status"] != "ACTIVE":
        raise invalid_state(
            "only an ACTIVE agency placement can be marked credit-reported")
    p["credit_reported_at"] = now_iso()
    touch(p)
    account = db.accounts.get(p["account_id"])
    if account is not None and account["credit_reporting_status"] not in (
            "FROZEN_BY_DISPUTE", "SUPPRESSED_BY_CHARITY", "REPORTED"):
        account["credit_reporting_status"] = "REPORTED"
        touch(account)
    return ok_object(serialize_agency_placement(p))
