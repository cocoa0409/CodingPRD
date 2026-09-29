"""Monthly voucher submissions and special claims (PRD 3.9)."""
from flask import Blueprint

from core import (
    ROLE_CA, ROLE_HFO, ROLE_OWNER, clock_date, clock_date_str, create, fail,
    json_body, month_first_day, need_date, need_enum, need_int, need_month,
    need_str, opt_date, opt_int, opt_str, parse_month, respond_object, touch,
)
import calcs
from guards import (
    body_fk, endpoint, own_claim, own_contract, own_submission, require_state,
    resolve,
)

bp = Blueprint("money", __name__)


# --------------------------------------------------------------------------
# Voucher submissions
# --------------------------------------------------------------------------
@bp.post("/voucher-submissions")
@endpoint(ROLE_OWNER)
def create_submission():
    body = json_body()
    contract = body_fk(body, "contract_id", "contracts")
    if contract is not None:
        own_contract(contract)
    need_str(body, "contract_id")
    period_month = need_month(body, "period_month")
    expected = need_int(body, "expected_contract_version")
    if expected != contract["version"]:
        fail("ERR_STALE_CONTRACT_VERSION",
             "expected_contract_version does not match the contract's current version.")
    for existing in calcs.submissions_of_contract(contract["id"]):
        if existing["period_month"] == period_month and existing["state"] != "REVERSED":
            fail("ERR_DUPLICATE_VOUCHER_PERIOD",
                 "A live voucher already exists for this contract and billing month.")
    total, included = calcs.monthly_voucher_hap_request(contract, period_month)
    submission = create("submissions", {
        "contract_id": contract["id"],
        "period_month": period_month,
        "state": "DRAFT",
        "requested_hap_cents": total,
        "included_certification_count": included,
        "paid_amount_cents": None,
        "paid_on_date": None,
        "reversal_reason": None,
    })
    touch(contract)
    return respond_object(submission, 201)


@bp.get("/voucher-submissions/<submission_id>")
@endpoint(ROLE_OWNER, ROLE_CA, ROLE_HFO)
def read_submission(submission_id):
    return respond_object(resolve("submissions", submission_id), 200)


@bp.post("/voucher-submissions/<submission_id>/submit")
@endpoint(ROLE_OWNER)
def submit_submission(submission_id):
    submission = own_submission(resolve("submissions", submission_id))
    require_state(submission, "state", "DRAFT")
    contract = calcs.table("contracts").get(submission["contract_id"])
    total, included = calcs.monthly_voucher_hap_request(
        contract, submission["period_month"])
    year, month = parse_month(submission["period_month"])
    if month == 12:
        boundary = month_first_day(year + 1, 1)
    else:
        boundary = month_first_day(year, month + 1)
    if clock_date() < boundary:
        fail("ERR_PERIOD_NOT_ELAPSED",
             "The billed month has not fully closed yet.")
    if not (total > 0):
        fail("ERR_ZERO_VOUCHER_REQUEST",
             "A voucher requesting zero assistance cannot be submitted.")
    submission["requested_hap_cents"] = total
    submission["included_certification_count"] = included
    submission["state"] = "SUBMITTED"
    touch(submission)
    return respond_object(submission, 200)


@bp.post("/voucher-submissions/<submission_id>/pay")
@endpoint(ROLE_CA)
def pay_submission(submission_id):
    submission = resolve("submissions", submission_id)
    require_state(submission, "state", "SUBMITTED")
    contract = calcs.table("contracts").get(submission["contract_id"])
    amount = submission["requested_hap_cents"]
    if contract is None or amount > contract["hap_ledger_balance_cents"]:
        fail("ERR_HAP_BUDGET_EXCEEDED",
             "The disbursement exceeds the contract's remaining HAP authorization.")
    submission["state"] = "PAID"
    submission["paid_amount_cents"] = amount
    submission["paid_on_date"] = clock_date_str()
    touch(submission)
    contract["paid_hap_total_cents"] = contract["paid_hap_total_cents"] + amount
    calcs.recompute_contract_ledger(contract)
    touch(contract)
    return respond_object(submission, 200)


@bp.post("/voucher-submissions/<submission_id>/reverse")
@endpoint(ROLE_CA)
def reverse_submission(submission_id):
    submission = resolve("submissions", submission_id)
    body = json_body()
    reason = need_str(body, "reason")
    require_state(submission, "state", "PAID")
    contract = calcs.table("contracts").get(submission["contract_id"])
    for claim in calcs.claims_of_contract(submission["contract_id"]):
        if claim["claim_period_month"] == submission["period_month"] \
                and claim["state"] == "PAID":
            fail("ERR_CLAIM_PAID_BLOCKS_REVERSAL",
                 "A paid special claim covers this billing month.")
    amount = submission["paid_amount_cents"] or 0
    submission["state"] = "REVERSED"
    submission["reversal_reason"] = reason
    touch(submission)
    if contract is not None:
        contract["paid_hap_total_cents"] = contract["paid_hap_total_cents"] - amount
        calcs.recompute_contract_ledger(contract)
        touch(contract)
    return respond_object(submission, 200)


# --------------------------------------------------------------------------
# Special claims
# --------------------------------------------------------------------------
@bp.post("/special-claims")
@endpoint(ROLE_OWNER)
def create_claim():
    body = json_body()
    contract = body_fk(body, "contract_id", "contracts")
    if contract is not None:
        own_contract(contract)
    need_str(body, "contract_id")
    claim_type = need_enum(body, "claim_type", calcs.CLAIM_TYPES)
    unit_number = need_str(body, "unit_number")
    claim_period_month = need_month(body, "claim_period_month")
    vacancy_start = None
    vacancy_end = None
    estimated_days = None
    claimed_amount = None
    if claim_type == "VACANCY":
        vacancy_start = need_date(body, "vacancy_start_date")
        vacancy_end = opt_date(body, "vacancy_end_date")
        if vacancy_end is None:
            estimated_days = need_int(body, "estimated_vacancy_days", minimum=1)
        else:
            estimated_days = opt_int(body, "estimated_vacancy_days", minimum=1)
    else:
        claimed_amount = need_int(body, "claimed_amount_cents", minimum=0)
    deposit = opt_int(body, "security_deposit_balance_cents", default=0, minimum=0)
    draft = {
        "contract_id": contract["id"],
        "claim_type": claim_type,
        "unit_number": unit_number,
        "claim_period_month": claim_period_month,
        "vacancy_start_date": vacancy_start,
        "vacancy_end_date": vacancy_end,
        "estimated_vacancy_days": estimated_days,
        "claimed_amount_cents": claimed_amount,
        "security_deposit_balance_cents": deposit,
    }
    days, variant, amount = calcs.special_claim_amount(draft, contract)
    draft.update({
        "vacancy_days_claimed": days,
        "valuation_variant": variant,
        "computed_amount_cents": amount,
        "state": "DRAFT",
        "decision_reason": None,
        "paid_amount_cents": None,
    })
    return respond_object(create("claims", draft), 201)


@bp.get("/special-claims/<claim_id>")
@endpoint(ROLE_OWNER, ROLE_CA, ROLE_HFO)
def read_claim(claim_id):
    return respond_object(resolve("claims", claim_id), 200)


@bp.post("/special-claims/<claim_id>/submit")
@endpoint(ROLE_OWNER)
def submit_claim(claim_id):
    claim = own_claim(resolve("claims", claim_id))
    require_state(claim, "state", "DRAFT")
    contract = calcs.table("contracts").get(claim["contract_id"])
    days, variant, amount = calcs.special_claim_amount(claim, contract)
    other_days = calcs.aggregate_vacancy_days(
        claim["contract_id"], claim["unit_number"], claim["id"])
    if days + other_days > calcs.VACANCY_DAY_CAP:
        fail("ERR_VACANCY_DAYS_CAP_EXCEEDED",
             "The aggregate vacancy days for this unit would exceed %d."
             % calcs.VACANCY_DAY_CAP)
    if not (amount > 0):
        fail("ERR_ZERO_CLAIM_AMOUNT",
             "A claim with a non-positive computed amount cannot be submitted.")
    claim["vacancy_days_claimed"] = days
    claim["valuation_variant"] = variant
    claim["computed_amount_cents"] = amount
    claim["state"] = "SUBMITTED"
    touch(claim)
    return respond_object(claim, 200)


@bp.post("/special-claims/<claim_id>/decide")
@endpoint(ROLE_CA)
def decide_claim(claim_id):
    claim = resolve("claims", claim_id)
    body = json_body()
    decision = need_enum(body, "decision", ("APPROVE", "DENY"))
    reason = opt_str(body, "reason")
    require_state(claim, "state", "SUBMITTED")
    claim["state"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    claim["decision_reason"] = reason
    touch(claim)
    return respond_object(claim, 200)


@bp.post("/special-claims/<claim_id>/pay")
@endpoint(ROLE_CA)
def pay_claim(claim_id):
    claim = resolve("claims", claim_id)
    require_state(claim, "state", "APPROVED")
    contract = calcs.table("contracts").get(claim["contract_id"])
    covering = None
    for submission in calcs.submissions_of_contract(claim["contract_id"]):
        if submission["period_month"] != claim["claim_period_month"]:
            continue
        if submission["state"] == "PAID":
            covering = submission
    if covering is None:
        fail("ERR_COVERING_VOUCHER_NOT_PAID",
             "The voucher covering this claim period has not been paid.")
    amount = claim["computed_amount_cents"]
    if contract is None or amount > contract["hap_ledger_balance_cents"]:
        fail("ERR_HAP_BUDGET_EXCEEDED",
             "The disbursement exceeds the contract's remaining HAP authorization.")
    claim["state"] = "PAID"
    claim["paid_amount_cents"] = amount
    touch(claim)
    contract["paid_claims_total_cents"] = contract["paid_claims_total_cents"] + amount
    calcs.recompute_contract_ledger(contract)
    touch(contract)
    return respond_object(claim, 200)
