"""Flat single-resource GETs and filtered-list GETs (FK reverse-reachability
helpers, SCAFFOLD Table 5 tail)."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, check_investor_owns
from response import success_object, success_list
from services.core import (
    serialize, paginate, filter_by,
    get_share_class, get_nav_period, get_series, get_kyc_case, get_attestation,
    get_subscription, get_side_letter, get_mfn_clause, get_capital_account,
    get_series_lot, get_redemption, get_statement,
)

bp = Blueprint("flat", __name__)

ALL = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager", "Investor")
STAFF4 = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager")
NAV_READERS = STAFF4
FA_CO = ("FundAdmin", "ComplianceOfficer")
FA_CO_PM = ("FundAdmin", "ComplianceOfficer", "PortfolioManager")


# ---------------------------------------------------------------------------
# Flat single-resource GETs
# ---------------------------------------------------------------------------


@bp.get("/share-classes/<rid>")
def flat_share_class(rid):
    require_roles(*ALL)
    return success_object(serialize(get_share_class(rid)))


@bp.get("/nav-periods/<rid>")
def flat_nav_period(rid):
    require_roles(*NAV_READERS)
    return success_object(serialize(get_nav_period(rid)))


@bp.get("/series/<rid>")
def flat_series(rid):
    require_roles(*NAV_READERS)
    return success_object(serialize(get_series(rid)))


@bp.get("/kyc-cases/<rid>")
def flat_kyc_case(rid):
    caller = require_roles("FundAdmin", "ComplianceOfficer", "Investor")
    rec = get_kyc_case(rid)
    check_investor_owns(caller, rec["investor_id"])
    return success_object(serialize(rec))


@bp.get("/accreditations/<rid>")
def flat_accreditation(rid):
    caller = require_roles("FundAdmin", "ComplianceOfficer", "Investor")
    rec = get_attestation(rid)
    check_investor_owns(caller, rec["investor_id"])
    return success_object(serialize(rec))


@bp.get("/subscriptions/<rid>")
def flat_subscription(rid):
    caller = require_roles(*ALL)
    rec = get_subscription(rid)
    check_investor_owns(caller, rec["investor_id"])
    return success_object(serialize(rec))


@bp.get("/side-letters/<rid>")
def flat_side_letter(rid):
    caller = require_roles(*FA_CO_PM, "Investor")
    rec = get_side_letter(rid)
    check_investor_owns(caller, rec["investor_id"])
    return success_object(serialize(rec))


@bp.get("/mfn-clauses/<rid>")
def flat_mfn_clause(rid):
    require_roles(*FA_CO_PM, "Investor")
    return success_object(serialize(get_mfn_clause(rid)))


@bp.get("/capital-accounts/<rid>")
def flat_capital_account(rid):
    caller = require_roles(*ALL)
    rec = get_capital_account(rid)
    check_investor_owns(caller, rec["investor_id"])
    return success_object(serialize(rec))


@bp.get("/series-lots/<rid>")
def flat_series_lot(rid):
    caller = require_roles(*ALL)
    rec = get_series_lot(rid)
    account = get_capital_account(rec["capital_account_id"])
    check_investor_owns(caller, account["investor_id"])
    return success_object(serialize(rec))


@bp.get("/redemptions/<rid>")
def flat_redemption(rid):
    caller = require_roles(*ALL)
    rec = get_redemption(rid)
    check_investor_owns(caller, rec["investor_id"])
    return success_object(serialize(rec))


@bp.get("/statements/<rid>")
def flat_statement(rid):
    caller = require_roles(*ALL)
    rec = get_statement(rid)
    account = get_capital_account(rec["capital_account_id"])
    check_investor_owns(caller, account["investor_id"])
    return success_object(serialize(rec))


# ---------------------------------------------------------------------------
# Flat filtered-list GETs
# ---------------------------------------------------------------------------


@bp.get("/share-classes")
def list_share_classes_flat():
    require_roles(*ALL)
    items = filter_by(db["share_classes"].values(),
                      fund_id=request.args.get("fund_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/nav-periods")
def list_nav_periods_flat():
    require_roles(*NAV_READERS)
    items = filter_by(db["nav_periods"].values(),
                      fund_id=request.args.get("fund_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/series")
def list_series_flat():
    require_roles(*NAV_READERS)
    items = filter_by(db["series"].values(),
                      share_class_id=request.args.get("share_class_id"),
                      nav_period_id=request.args.get("nav_period_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/kyc-cases")
def list_kyc_cases_flat():
    require_roles(*FA_CO)
    items = filter_by(db["kyc_cases"].values(),
                      investor_id=request.args.get("investor_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/accreditations")
def list_accreditations_flat():
    caller = require_roles("FundAdmin", "ComplianceOfficer", "Investor")
    investor_id = request.args.get("investor_id")
    if caller.is_investor:
        check_investor_owns(caller, investor_id or caller.user_id)
        investor_id = caller.user_id
    items = filter_by(db["accreditations"].values(), investor_id=investor_id)
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/subscriptions")
def list_subscriptions_flat():
    require_roles(*STAFF4)
    items = filter_by(db["subscriptions"].values(),
                      investor_id=request.args.get("investor_id"),
                      share_class_id=request.args.get("share_class_id"),
                      effective_series_id=request.args.get("effective_series_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/side-letters")
def list_side_letters_flat():
    require_roles(*FA_CO_PM)
    items = filter_by(db["side_letters"].values(),
                      investor_id=request.args.get("investor_id"),
                      share_class_id=request.args.get("share_class_id"),
                      subscription_id=request.args.get("subscription_id"),
                      supersedes_side_letter_id=request.args.get("supersedes_side_letter_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/mfn-clauses")
def list_mfn_clauses_flat():
    require_roles(*FA_CO_PM, "Investor")
    items = filter_by(db["mfn_clauses"].values(),
                      fund_id=request.args.get("fund_id"),
                      status=request.args.get("status"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/capital-accounts")
def list_capital_accounts_flat():
    require_roles(*STAFF4)
    items = filter_by(db["capital_accounts"].values(),
                      investor_id=request.args.get("investor_id"),
                      share_class_id=request.args.get("share_class_id"),
                      subscription_id=request.args.get("subscription_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/series-lots")
def list_series_lots_flat():
    require_roles(*STAFF4)
    items = filter_by(db["series_lots"].values(),
                      capital_account_id=request.args.get("capital_account_id"),
                      series_id=request.args.get("series_id"),
                      nav_period_id=request.args.get("nav_period_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/redemptions")
def list_redemptions_flat():
    require_roles(*STAFF4)
    items = filter_by(db["redemptions"].values(),
                      capital_account_id=request.args.get("capital_account_id"),
                      investor_id=request.args.get("investor_id"),
                      requested_effective_period_id=request.args.get("requested_effective_period_id"),
                      effective_period_id=request.args.get("effective_period_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/statements")
def list_statements_flat():
    caller = require_roles(*ALL)
    items = list(db["statements"].values())
    if caller.is_investor:
        own_accounts = {a["id"] for a in db["capital_accounts"].values()
                        if a["investor_id"] == caller.user_id}
        items = [s for s in items if s["capital_account_id"] in own_accounts]
    items = filter_by(items,
                      capital_account_id=request.args.get("capital_account_id"),
                      nav_period_id=request.args.get("nav_period_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)
