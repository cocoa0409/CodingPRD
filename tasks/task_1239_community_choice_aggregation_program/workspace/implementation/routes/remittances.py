"""RemittanceFile endpoints: register, reconcile (OCC waterfall), dispute, settle."""

from flask import Blueprint, g, request

from auth import require_roles
from envelope import ok_object, paginate
from errors import (ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_REFERENTIAL_STATE,
                    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_EXTRACT_VERSION)
from serializers import ser_remittance
from services import (find_matching_extract, get_or_404, waterfall_apply,
                      waterfall_reverse)
from store import STORE
from util import as_int, check_month, dec, get_body, quarter_of_month, round_half_up_int

bp = Blueprint("remittances", __name__)

BC_FC_UL = ("BillingCoordinator", "FinanceController", "UtilityLiaison")


def _present(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
    return body[field]


@bp.post("/cca/remittance-files")
@require_roles("BillingCoordinator")
def create_remittance():
    body = get_body(request)
    period = check_month(_present(body, "remittance_period"), "remittance_period")
    gross = as_int(_present(body, "gross_remittance_cents"), "gross_remittance_cents")
    if gross < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "gross_remittance_cents must be >= 0")
    fee = as_int(_present(body, "utility_fee_bps"), "utility_fee_bps")
    if not (0 <= fee <= 300):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "utility_fee_bps must lie between 0 and 300 inclusive")
    fee_cents = round_half_up_int(dec(gross) * dec(fee) / dec(10000))
    rec = STORE.new_record()
    rec.update({
        "remittance_period": period,
        "gross_remittance_cents": gross,
        "utility_fee_bps": fee,
        "net_remittance_cents": gross - fee_cents,
        "applied_cents": 0,
        "status": "RECEIVED",
        "_reconciled_by": None,
        "_applications": [],
    })
    STORE.remittances[rec["id"]] = rec
    return ok_object(ser_remittance(rec), status=201)


@bp.get("/cca/remittance-files")
@require_roles(*BC_FC_UL)
def list_remittances():
    items = list(STORE.remittances.values())
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    rp = request.args.get("remittance_period")
    if rp is not None:
        items = [r for r in items if r["remittance_period"] == rp]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    return paginate(items, ser_remittance)


@bp.get("/cca/remittance-files/<rid>")
@require_roles(*BC_FC_UL)
def get_remittance(rid):
    return ok_object(ser_remittance(get_or_404(STORE.remittances, rid, "RemittanceFile")))


@bp.post("/cca/remittance-files/<rid>/reconcile")
@require_roles("BillingCoordinator")
def reconcile_remittance(rid):
    rf = get_or_404(STORE.remittances, rid, "RemittanceFile")
    if rf["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "RemittanceFile is SETTLED (terminal)")
    if rf["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"RemittanceFile in status {rf['status']} cannot be reconciled")
    extract = find_matching_extract(rf["remittance_period"])
    if extract is None:
        raise ApiError(ERR_REFERENTIAL_STATE, 422,
                       "No ACCEPTED or SETTLED billing extract matches the remittance period")
    body = get_body(request)
    expected = _present(body, "expected_extract_version")
    expected = as_int(expected, "expected_extract_version")
    if expected != extract["version"]:
        raise ApiError(ERR_STALE_EXTRACT_VERSION, 412,
                       "expected_extract_version does not match the matching extract's version")
    waterfall_apply(rf, extract)
    rf["status"] = "RECONCILED"
    rf["_reconciled_by"] = g.user_id
    STORE.touch(rf)
    # Reconciliation mutates the matching extract's version by 1.
    STORE.touch(extract)
    return ok_object(ser_remittance(rf))


@bp.post("/cca/remittance-files/<rid>/dispute")
@require_roles("UtilityLiaison")
def dispute_remittance(rid):
    rf = get_or_404(STORE.remittances, rid, "RemittanceFile")
    if rf["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "RemittanceFile is SETTLED (terminal)")
    if rf["status"] != "RECONCILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"RemittanceFile in status {rf['status']} cannot be disputed")
    waterfall_reverse(rf)
    rf["status"] = "DISPUTED"
    STORE.touch(rf)
    return ok_object(ser_remittance(rf))


@bp.post("/cca/remittance-files/<rid>/reopen")
@require_roles("BillingCoordinator")
def reopen_remittance(rid):
    rf = get_or_404(STORE.remittances, rid, "RemittanceFile")
    if rf["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "RemittanceFile is SETTLED (terminal)")
    if rf["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"RemittanceFile in status {rf['status']} cannot be reopened")
    rf["status"] = "RECEIVED"
    STORE.touch(rf)
    return ok_object(ser_remittance(rf))


@bp.post("/cca/remittance-files/<rid>/settle")
@require_roles("FinanceController")
def settle_remittance(rid):
    rf = get_or_404(STORE.remittances, rid, "RemittanceFile")
    if rf["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "RemittanceFile is SETTLED (terminal)")
    if rf["status"] != "RECONCILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"RemittanceFile in status {rf['status']} cannot be settled")
    if g.user_id == rf["_reconciled_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The settling FinanceController must differ from the reconciler")
    if rf["applied_cents"] != rf["net_remittance_cents"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "applied_cents must equal net_remittance_cents at settlement")
    rf["status"] = "SETTLED"
    STORE.touch(rf)
    # Cascade hop 1: matching ACCEPTED extract -> SETTLED.
    extract = None
    for e in sorted(STORE.extracts.values(), key=lambda x: (x["_created_dt"], x["_seq"])):
        if e["billing_month"] == rf["remittance_period"] and e["status"] == "ACCEPTED":
            extract = e
            break
    if extract is not None:
        extract["status"] = "SETTLED"
        STORE.touch(extract)
        # Cascade hop 2: attribute billed revenue to the containing bad-debt pool.
        period = quarter_of_month(extract["billing_month"])
        for pool in STORE.pools.values():
            if pool["pool_period"] == period and pool["status"] == "ACCRUING":
                pool["billed_generation_cents"] += extract["total_billed_cents"]
                STORE.touch(pool)
                break
    return ok_object(ser_remittance(rf))
