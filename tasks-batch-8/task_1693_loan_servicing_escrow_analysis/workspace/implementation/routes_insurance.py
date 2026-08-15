"""Insurance policies: lapse, force-placement, refunds."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import any_role, check_borrower_owner, require_roles
from domain import (
    account_of_loan,
    check_advance_cap,
    new_advance,
    post_ledger,
    recovery_waterfall,
    replay,
)
from errors import (
    ApiError,
    ERR_ACTIVE_COVERAGE,
    ERR_ALREADY_TERMINAL,
    ERR_COVERAGE_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOAN_NOT_ACTIVE,
    ERR_NOTICE_WINDOW,
    ERR_REMINDER_EARLY,
    not_found,
)
from routes_core import get_loan_or_404
from serializers import policy_out
from store import store
from util import (
    bump,
    days_30360,
    fmt_date,
    new_record,
    now_dt,
    now_ts,
    ok,
    ok_list,
    parse_date,
    rhu,
    today,
)
from validate import body, opt_enum, opt_int, positive_amount, req_date, req_enum, req_str

bp = Blueprint("insurance", __name__)

POLICY_TYPES = ("HAZARD", "FLOOD")
DAY_COUNT = ("ACT_365", "CONTRACT_30_360")
TERMINAL = ("REFUNDED", "CANCELLED", "EXPIRED_CLOSED")


def get_policy_or_404(pid):
    p = store.policies.get(pid)
    if p is None:
        raise not_found("InsurancePolicy not found")
    return p


def _half_open_overlap(s1, e1, s2, e2):
    """[s1,e1) intersects [s2,e2)? Pure adjacency is NOT overlap."""
    return s1 < e2 and s2 < e1


def _overlap_exists(loan_id, policy_type, start_s, end_s, exclude_id=None):
    s1 = parse_date(start_s)
    e1 = parse_date(end_s)
    for other in store.policies.values():
        if other["loan_id"] != loan_id or other["policy_type"] != policy_type:
            continue
        if other["status"] != "ACTIVE" or other["id"] == exclude_id:
            continue
        if _half_open_overlap(s1, e1, parse_date(other["coverage_start_date"]),
                              parse_date(other["coverage_end_date"])):
            return True
    return False


@bp.post("/servicing/loans/<lid>/insurance-policies")
def create_policy(lid):
    uid, role = require_roles("InsuranceSpecialist", "Borrower")
    if role == "Borrower":
        check_borrower_owner(uid, lid)
    loan = get_loan_or_404(lid)
    data = body()
    ptype = req_enum(data, "policy_type", POLICY_TYPES)
    carrier = req_str(data, "carrier_name")
    number = req_str(data, "policy_number")
    start = req_date(data, "coverage_start_date")
    end = req_date(data, "coverage_end_date")
    premium = opt_int(data, "annual_premium_cents")
    if not isinstance(data.get("annual_premium_cents"), int) or isinstance(
            data.get("annual_premium_cents"), bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "annual_premium_cents is required and must be an integer")
    if parse_date(end) <= parse_date(start):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "coverage_end_date must be after coverage_start_date")
    if loan["status"] != "ACTIVE":
        raise ApiError(ERR_LOAN_NOT_ACTIVE, 409, "Loan is not ACTIVE")
    if _overlap_exists(lid, ptype, start, end):
        raise ApiError(ERR_COVERAGE_OVERLAP, 409,
                       "Coverage overlaps another ACTIVE same-type policy")
    positive_amount(premium, "annual_premium_cents")
    pol = new_record({
        "loan_id": lid,
        "policy_type": ptype,
        "carrier_name": carrier,
        "policy_number": number,
        "coverage_start_date": start,
        "coverage_end_date": end,
        "annual_premium_cents": premium,
        "status": "ACTIVE",
        "notice_1_sent_at": None,
        "notice_2_sent_at": None,
        "force_placed_at": None,
        "fp_premium_cents": None,
        "fp_coverage_end": None,
        "day_count_convention": "ACT_365",
        "fp_refund_cents": None,
        "refund_processed_at": None,
        "refund_timeliness": None,
    })
    store.policies[pol["id"]] = pol
    return ok(policy_out(pol), 201)


@bp.get("/servicing/loans/<lid>/insurance-policies")
def list_policies(lid):
    any_role()
    get_loan_or_404(lid)
    rows = [p for p in sorted(store.policies.values(), key=lambda r: r["_seq"])
            if p["loan_id"] == lid]
    ptype = request.args.get("policy_type")
    if ptype is not None:
        rows = [r for r in rows if r["policy_type"] == ptype]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([policy_out(r) for r in rows])


@bp.get("/servicing/insurance-policies/<pid>")
def get_policy(pid):
    any_role()
    return ok(policy_out(get_policy_or_404(pid)))


def _transition_guard(pol):
    if pol["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Policy is terminal")


@bp.post("/servicing/insurance-policies/<pid>/report-lapse")
def report_lapse(pid):
    require_roles("InsuranceSpecialist")
    pol = get_policy_or_404(pid)
    _transition_guard(pol)
    if pol["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Policy is not ACTIVE")
    pol["status"] = "LAPSED"
    bump(pol)
    return ok(policy_out(pol))


@bp.post("/servicing/insurance-policies/<pid>/send-first-notice")
def send_first_notice(pid):
    require_roles("InsuranceSpecialist")
    pol = get_policy_or_404(pid)
    _transition_guard(pol)
    if pol["status"] != "LAPSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Policy is not LAPSED")
    pol["status"] = "NOTICE_1_SENT"
    pol["notice_1_sent_at"] = now_ts()
    bump(pol)
    return ok(policy_out(pol))


@bp.post("/servicing/insurance-policies/<pid>/send-reminder-notice")
def send_reminder_notice(pid):
    require_roles("InsuranceSpecialist")
    pol = get_policy_or_404(pid)
    _transition_guard(pol)
    if pol["status"] != "NOTICE_1_SENT":
        raise ApiError(ERR_INVALID_STATE, 409, "Policy is not NOTICE_1_SENT")
    n1 = parse_date(pol["notice_1_sent_at"][:10])
    if today() < n1 + timedelta(days=30):
        raise ApiError(ERR_REMINDER_EARLY, 409,
                       "Reminder requires current date >= notice_1 date + 30 days")
    pol["status"] = "NOTICE_2_SENT"
    pol["notice_2_sent_at"] = now_ts()
    bump(pol)
    return ok(policy_out(pol))


@bp.post("/servicing/insurance-policies/<pid>/charge-force-placement")
def charge_force_placement(pid):
    require_roles("InsuranceSpecialist")
    pol = get_policy_or_404(pid)
    data = body()
    premium = data.get("fp_premium_cents")
    if not isinstance(premium, int) or isinstance(premium, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "fp_premium_cents is required and must be an integer")
    conv = opt_enum(data, "day_count_convention", DAY_COUNT, "ACT_365")
    _transition_guard(pol)
    if pol["status"] != "NOTICE_2_SENT":
        raise ApiError(ERR_INVALID_STATE, 409, "Policy is not NOTICE_2_SENT")
    loan = store.loans.get(pol["loan_id"])
    if loan is None or loan["status"] != "ACTIVE":
        raise ApiError(ERR_LOAN_NOT_ACTIVE, 409, "Loan is not ACTIVE")
    now_date = today()
    n1 = parse_date(pol["notice_1_sent_at"][:10])
    n2 = parse_date(pol["notice_2_sent_at"][:10])
    if now_date < n1 + timedelta(days=45) or now_date < n2 + timedelta(days=15):
        raise ApiError(ERR_NOTICE_WINDOW, 409, "Force-placement notice windows not met")
    # Barred while any other ACTIVE same-type policy exists on the loan
    for other in store.policies.values():
        if (other["id"] != pol["id"] and other["loan_id"] == pol["loan_id"]
                and other["policy_type"] == pol["policy_type"]
                and other["status"] == "ACTIVE"):
            raise ApiError(ERR_ACTIVE_COVERAGE, 409,
                           "Another ACTIVE same-type policy exists on the loan")
    positive_amount(premium, "fp_premium_cents")
    account = account_of_loan(pol["loan_id"])
    shortfall = 0
    if account is not None:
        shortfall = premium - max(account["balance_cents"], 0)
        if shortfall > 0:
            check_advance_cap(account["id"], shortfall)
    if account is not None:
        post_ledger(account, "FORCE_PLACEMENT_CHARGE", -premium, fmt_date(now_date),
                    "InsurancePolicy", pol["id"])
        if shortfall > 0:
            adv = new_advance(account, "FORCE_PLACEMENT_PREMIUM", shortfall, None)
            post_ledger(account, "ADVANCE_ISSUED", shortfall, fmt_date(now_date),
                        "EscrowAdvance", adv["id"])
        replay(account)
    pol["status"] = "FORCE_PLACED"
    pol["fp_premium_cents"] = premium
    pol["day_count_convention"] = conv
    pol["force_placed_at"] = now_ts()
    pol["fp_coverage_end"] = fmt_date(now_date + timedelta(days=365))
    bump(pol)
    if account is not None:
        bump(account)
    return ok(policy_out(pol))


@bp.post("/servicing/insurance-policies/<pid>/reinstate")
def reinstate_policy(pid):
    uid, role = require_roles("InsuranceSpecialist", "Borrower")
    pol = get_policy_or_404(pid)
    if role == "Borrower":
        check_borrower_owner(uid, pol["loan_id"])
    data = body()
    new_start = req_date(data, "new_coverage_start_date")
    new_end = req_date(data, "new_coverage_end_date")
    new_premium = opt_int(data, "new_annual_premium_cents")
    _transition_guard(pol)
    if pol["status"] not in ("LAPSED", "NOTICE_1_SENT", "NOTICE_2_SENT"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Policy cannot be reinstated from its current state")
    loan = store.loans.get(pol["loan_id"])
    if loan is None or loan["status"] != "ACTIVE":
        raise ApiError(ERR_LOAN_NOT_ACTIVE, 409, "Loan is not ACTIVE")
    if parse_date(new_end) <= today():
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "new_coverage_end_date must be after the current date")
    if _overlap_exists(pol["loan_id"], pol["policy_type"], new_start, new_end,
                       exclude_id=pol["id"]):
        raise ApiError(ERR_COVERAGE_OVERLAP, 409,
                       "New coverage overlaps another ACTIVE same-type policy")
    pol["coverage_start_date"] = new_start
    pol["coverage_end_date"] = new_end
    if new_premium is not None:
        pol["annual_premium_cents"] = new_premium
    pol["notice_1_sent_at"] = None
    pol["notice_2_sent_at"] = None
    pol["status"] = "ACTIVE"
    bump(pol)
    return ok(policy_out(pol))


@bp.post("/servicing/insurance-policies/<pid>/refund-force-placement")
def refund_force_placement(pid):
    require_roles("InsuranceSpecialist")
    pol = get_policy_or_404(pid)
    _transition_guard(pol)
    if pol["status"] != "FORCE_PLACED":
        raise ApiError(ERR_INVALID_STATE, 409, "Policy is not FORCE_PLACED")
    now_date = today()
    # Evidence policy: another ACTIVE same-type policy covering the current date;
    # selector: earliest coverage_start_date, tie-break created_at ASC.
    candidates = [
        p for p in store.policies.values()
        if p["id"] != pol["id"] and p["loan_id"] == pol["loan_id"]
        and p["policy_type"] == pol["policy_type"] and p["status"] == "ACTIVE"
        and parse_date(p["coverage_start_date"]) <= now_date
        < parse_date(p["coverage_end_date"])
    ]
    if not candidates:
        raise ApiError(ERR_INVALID_STATE, 409, "No evidence coverage policy exists")
    candidates.sort(key=lambda p: (p["coverage_start_date"], p["_seq"]))
    evidence = candidates[0]
    evidence_date = parse_date(evidence["created_at"][:10])
    fp_date = parse_date(pol["force_placed_at"][:10])
    premium = pol["fp_premium_cents"]
    if pol["day_count_convention"] == "CONTRACT_30_360":
        used = days_30360(fp_date, evidence_date)
        refund = rhu(Decimal(premium) * Decimal(360 - used) / Decimal(360))
    else:
        used = (evidence_date - fp_date).days
        refund = rhu(Decimal(premium) * Decimal(365 - used) / Decimal(365))
    pol["fp_refund_cents"] = refund
    pol["refund_processed_at"] = now_ts()
    pol["refund_timeliness"] = (
        "ON_TIME" if now_date <= evidence_date + timedelta(days=15) else "LATE")
    account = account_of_loan(pol["loan_id"])
    if account is not None:
        post_ledger(account, "FORCE_PLACEMENT_REFUND", refund, fmt_date(now_date),
                    "InsurancePolicy", pol["id"])
        recovery_waterfall(account, refund, fmt_date(now_date))
        replay(account)
    pol["status"] = "REFUNDED"
    bump(pol)
    if account is not None:
        bump(account)
    return ok(policy_out(pol))


@bp.post("/servicing/insurance-policies/<pid>/cancel")
def cancel_policy(pid):
    require_roles("InsuranceSpecialist")
    pol = get_policy_or_404(pid)
    _transition_guard(pol)
    if pol["status"] not in ("ACTIVE", "LAPSED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only ACTIVE or LAPSED policies can be cancelled")
    pol["status"] = "CANCELLED"
    bump(pol)
    return ok(policy_out(pol))
