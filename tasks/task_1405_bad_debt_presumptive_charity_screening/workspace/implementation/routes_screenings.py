"""PresumptiveCharityScreening endpoints: create (OCC-guarded), get,
list-by-account, evaluate (PRD 3.3)."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_SCREENABLE,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    invalid_state,
    not_found,
)
from middleware import (
    ROLE_COLLECTOR,
    ROLE_COUNSELOR,
    ROLE_OFFICER,
    authenticate,
)
from response import ok_list, ok_object
from services import (
    FPL_TABLE,
    SCREENABLE_STATUSES,
    ELIGIBLE_OUTCOMES,
    evaluate_eligibility,
    serialize_screening,
)
from util import (
    base_record,
    get_body,
    now_iso,
    paginate,
    req_enum,
    req_int,
    req_str,
    touch,
)

bp = Blueprint("screenings", __name__)

_READ_ROLES = [ROLE_COLLECTOR, ROLE_COUNSELOR, ROLE_OFFICER]


def get_screening_or_404(screening_id):
    scr = db.screenings.get(screening_id)
    if scr is None:
        raise not_found("screening not found")
    return scr


@bp.post("/self-pay/presumptive-charity-screenings")
def create_screening():
    authenticate([ROLE_COUNSELOR])
    b = get_body()
    account_id = req_str(b, "account_id")
    from routes_accounts import get_account_or_404
    account = get_account_or_404(account_id)

    screening_model = req_enum(b, "screening_model", ("FPL_TIERED", "SCORE_BASED"))
    household_size = None
    household_income_cents = None
    third_party_score = None
    if screening_model == "FPL_TIERED":
        household_size = req_int(b, "household_size")
        if household_size not in FPL_TABLE:
            raise ApiError(ERR_INVALID_REQUEST,
                           "household_size must be in 1..8", 400)
        household_income_cents = req_int(b, "household_income_cents")
        if household_income_cents < 0:
            raise ApiError(ERR_INVALID_REQUEST,
                           "household_income_cents must be >= 0", 400)
    else:
        third_party_score = req_int(b, "third_party_score")
        if not (0 <= third_party_score <= 1000):
            raise ApiError(ERR_INVALID_REQUEST,
                           "third_party_score must be in 0..1000", 400)

    # OCC (priority 5): expected_account_version is non-optional (PRD 2.7)
    expected_account_version = req_int(b, "expected_account_version")
    if expected_account_version != account["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_account_version does not match the account's current "
            "version",
            412,
        )

    # Supersede cascade: any prior PENDING or EVALUATED screening on the same
    # account becomes SUPERSEDED; the account's version is incremented by this
    # creation cascade (i.e. when the cascade actually mutates account state).
    cascaded = False
    for s in list(db.screenings.values()):
        if s["account_id"] != account_id or s["status"] not in ("PENDING", "EVALUATED"):
            continue
        was_eligible_evaluated = (
            s["status"] == "EVALUATED"
            and s["eligibility_outcome"] in ELIGIBLE_OUTCOMES
        )
        s["status"] = "SUPERSEDED"
        touch(s)
        cascaded = True
        if (was_eligible_evaluated
                and account["credit_reporting_status"] == "SUPPRESSED_BY_CHARITY"):
            # the new screening may disagree — credit status reverts
            account["credit_reporting_status"] = "REPORTABLE"
    if cascaded:
        touch(account)

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "screening_model": screening_model,
        "household_size": household_size,
        "household_income_cents": household_income_cents,
        "third_party_score": third_party_score,
        "fpl_percent": None,
        "eligibility_outcome": "PENDING",
        "charity_writeoff_percent": 0,
        "screened_at": None,
        "status": "PENDING",
    })
    db.screenings[rec["id"]] = rec
    return ok_object(serialize_screening(rec), 201)


@bp.get("/self-pay/presumptive-charity-screenings/<screening_id>")
def get_screening(screening_id):
    authenticate(_READ_ROLES)
    return ok_object(serialize_screening(get_screening_or_404(screening_id)))


@bp.get("/self-pay/accounts/<account_id>/presumptive-charity-screenings")
def list_screenings_for_account(account_id):
    authenticate(_READ_ROLES)
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = [s for s in db.screenings.values() if s["account_id"] == account_id]
    page, meta = paginate(items)
    return ok_list([serialize_screening(s) for s in page], meta)


@bp.post("/self-pay/presumptive-charity-screenings/<screening_id>/evaluate")
def evaluate_screening(screening_id):
    authenticate([ROLE_COUNSELOR])
    scr = get_screening_or_404(screening_id)
    if scr["status"] != "PENDING":
        raise invalid_state("only a PENDING screening can be evaluated")
    account = db.accounts.get(scr["account_id"])
    if account is None:
        raise not_found("account not found")
    if account["status"] not in SCREENABLE_STATUSES:
        raise ApiError(
            ERR_ACCOUNT_NOT_SCREENABLE,
            "screening evaluation requires account status OPEN, IN_EARLY_OUT "
            "or IN_COLLECTIONS",
            409,
        )
    outcome, writeoff_pct, fpl_percent = evaluate_eligibility(scr)
    scr["eligibility_outcome"] = outcome
    scr["charity_writeoff_percent"] = writeoff_pct
    scr["fpl_percent"] = fpl_percent
    scr["screened_at"] = now_iso()
    scr["status"] = "EVALUATED"
    touch(scr)
    # credit-reporting consequence (PRD 3.3)
    if (outcome in ELIGIBLE_OUTCOMES
            and account["credit_reporting_status"] in ("REPORTABLE", "REPORTED")):
        account["credit_reporting_status"] = "SUPPRESSED_BY_CHARITY"
        touch(account)
    return ok_object(serialize_screening(scr))
