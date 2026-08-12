"""ServiceAccount endpoints: ingest, reads, election, close, write-off."""

from flask import Blueprint, request

from auth import require_roles
from envelope import ok_object, paginate
from errors import (ApiError, ERR_FISCAL_GATE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NO_DEFAULT_PRODUCT,
                    ERR_REFERENTIAL_STATE, ERR_UNIQUENESS_CONFLICT)
from serializers import ser_account
from services import (account_open_balance, adopted_default_product,
                      adopted_product_for_election, covering_adopted_schedule,
                      get_or_404)
from store import STORE
from util import (as_bool, as_enum, as_int, as_list, as_number, as_str,
                  get_body, quarter_of_date)

bp = Blueprint("accounts", __name__)

SERVICE_CLASSES = {"RESIDENTIAL", "SMALL_COMMERCIAL", "LARGE_COMMERCIAL",
                   "INDUSTRIAL", "AGRICULTURAL", "STREETLIGHT"}
ELECTIONS = {"DEFAULT", "OPT_UP_100", "OPT_DOWN_ECONOMY"}


@bp.post("/cca/service-accounts/ingest")
@require_roles("ProgramOperator")
def ingest_accounts():
    body = get_body(request)
    items = as_list(req_present_accounts(body), "accounts")

    # Priority 11 (uniqueness) before priority 16 (field validity):
    # validate the all-or-nothing duplicate rule first.
    seen = set()
    for item in items:
        if isinstance(item, dict):
            uan = item.get("utility_account_number")
            if isinstance(uan, str):
                if uan in seen:
                    raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                                   f"Duplicate utility_account_number '{uan}' in ingest batch")
                seen.add(uan)
    for uan in seen:
        for a in STORE.accounts.values():
            if a["utility_account_number"] == uan:
                raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                               f"utility_account_number '{uan}' already exists")

    # Field-level validation pass (atomic: nothing is created until all pass).
    prepared = []
    for item in items:
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Each account entry must be an object")
        uan = as_str(item.get("utility_account_number"), "utility_account_number")
        sclass = as_enum(item.get("service_class"), "service_class", SERVICE_CLASSES)
        kwh = as_int(item.get("annual_kwh_estimate"), "annual_kwh_estimate")
        if kwh < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "annual_kwh_estimate must be >= 0")
        peak = as_number(item.get("annual_peak_kw"), "annual_peak_kw")
        if float(peak) < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "annual_peak_kw must be >= 0")
        da = as_bool(item.get("da_eligible"), "da_eligible")
        prepared.append((uan, sclass, kwh, peak, da))

    ids = []
    for uan, sclass, kwh, peak, da in prepared:
        rec = STORE.new_record()
        rec.update({
            "utility_account_number": uan,
            "service_class": sclass,
            "annual_kwh_estimate": kwh,
            "annual_peak_kw": peak,
            "da_eligible": da,
            "enrollment_state": "PROSPECT",
            "product_election": "DEFAULT",
            "current_enrollment_notice_id": None,
            "vintage_year": None,
            "cumulative_billed_cents": 0,
            "cumulative_remitted_cents": 0,
            "uncollectible_flag": False,
            "_write_off_period": None,
        })
        STORE.accounts[rec["id"]] = rec
        ids.append(rec["id"])
    return ok_object({"ingested_count": len(ids), "account_ids": ids}, status=201)


def req_present_accounts(body):
    if "accounts" not in body or body["accounts"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field 'accounts'")
    return body["accounts"]


@bp.get("/cca/service-accounts")
@require_roles("ProgramOperator", "CustomerService", "BillingCoordinator",
               "FinanceController", "PortfolioManager")
def list_accounts():
    items = list(STORE.accounts.values())
    st = request.args.get("enrollment_state")
    if st is not None:
        items = [a for a in items if a["enrollment_state"] == st]
    pe = request.args.get("product_election")
    if pe is not None:
        items = [a for a in items if a["product_election"] == pe]
    sc = request.args.get("service_class")
    if sc is not None:
        items = [a for a in items if a["service_class"] == sc]
    nid = request.args.get("current_enrollment_notice_id")
    if nid is not None:
        items = [a for a in items if a["current_enrollment_notice_id"] == nid]
    uf = request.args.get("uncollectible_flag")
    if uf is not None:
        want = uf.lower() == "true"
        items = [a for a in items if a["uncollectible_flag"] == want]
    items.sort(key=lambda a: (a["_created_dt"], a["_seq"]))
    return paginate(items, ser_account)


@bp.get("/cca/service-accounts/<aid>")
@require_roles("ProgramOperator", "CustomerService", "BillingCoordinator", "FinanceController")
def get_account(aid):
    return ok_object(ser_account(get_or_404(STORE.accounts, aid, "ServiceAccount")))


@bp.post("/cca/service-accounts/<aid>/product-election")
@require_roles("CustomerService")
def product_election(aid):
    acct = get_or_404(STORE.accounts, aid, "ServiceAccount")
    if acct["enrollment_state"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Account in enrollment_state {acct['enrollment_state']} cannot change product election")
    body = get_body(request)
    if "product_election" not in body or body["product_election"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field 'product_election'")
    target = body["product_election"]
    if not isinstance(target, str) or target not in ELECTIONS:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "product_election must be one of ['DEFAULT', 'OPT_DOWN_ECONOMY', 'OPT_UP_100']")
    now = STORE.now()
    if target == "DEFAULT":
        prod = adopted_default_product()
        if prod is None or covering_adopted_schedule(prod["id"], now) is None:
            raise ApiError(ERR_NO_DEFAULT_PRODUCT, 422,
                           "No ADOPTED default product with a covering ADOPTED rate schedule exists")
    else:
        prod = None
        for p in STORE.products.values():
            if p["election_key"] == target:
                prod = p
                break
        if prod is None or prod["status"] != "ADOPTED":
            raise ApiError(ERR_REFERENTIAL_STATE, 422,
                           f"No ADOPTED product exists for election {target}")
        if covering_adopted_schedule(prod["id"], now) is None:
            raise ApiError(ERR_REFERENTIAL_STATE, 422,
                           f"No ADOPTED rate schedule covers the current date for election {target}")
    acct["product_election"] = target
    STORE.touch(acct)
    return ok_object(ser_account(acct))


@bp.post("/cca/service-accounts/<aid>/close")
@require_roles("CustomerService")
def close_account(aid):
    acct = get_or_404(STORE.accounts, aid, "ServiceAccount")
    if acct["enrollment_state"] not in ("ENROLLED", "OPTED_BACK_TO_BUNDLED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Account in enrollment_state {acct['enrollment_state']} cannot be closed")
    if account_open_balance(acct) != 0:
        raise ApiError(ERR_FISCAL_GATE, 422,
                       "Account close requires a zero open balance")
    acct["enrollment_state"] = "CLOSED"
    STORE.touch(acct)
    return ok_object(ser_account(acct))


@bp.post("/cca/service-accounts/<aid>/write-off")
@require_roles("FinanceController")
def write_off_account(aid):
    acct = get_or_404(STORE.accounts, aid, "ServiceAccount")
    if not acct["uncollectible_flag"]:
        acct["uncollectible_flag"] = True
        acct["_write_off_period"] = quarter_of_date(STORE.now())
        STORE.touch(acct)
    return ok_object(ser_account(acct))
