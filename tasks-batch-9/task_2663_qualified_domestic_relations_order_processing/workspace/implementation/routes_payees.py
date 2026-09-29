"""Alternate payee accounts, distributions, voids and the 1099-R ledger (PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import enums
import errors
import services
import validation as v
from auth import endpoint
from envelope import object_response, paginate
from store import db, order_by, public, public_list

bp = Blueprint("payees", __name__)


def find_ap_account(account_id):
    account = db.ap_accounts.get(account_id)
    if account is None:
        errors.fail(errors.ERR_AP_ACCOUNT_NOT_FOUND,
                    "No alternate payee account with that id.")
    return account


def find_distribution(distribution_id):
    row = db.distributions.get(distribution_id)
    if row is None:
        errors.fail(errors.ERR_DISTRIBUTION_NOT_FOUND, "No distribution with that id.")
    return row


def find_tax_report(report_id):
    row = db.tax_reports.get(report_id)
    if row is None:
        errors.fail(errors.ERR_TAX_REPORT_NOT_FOUND, "No tax report with that id.")
    return row


def funding_plan_account(ap_account):
    case = db.qdro_cases[ap_account["qdro_case_id"]]
    return services.operative_plan_account(case)


@bp.route("/alternate-payee-accounts/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "AlternatePayee", "Attorney")
def read_ap_account(caller, id):
    account = find_ap_account(id)
    auth.own_ap_account(caller, account)
    auth.attorney_standing(caller)
    return object_response(public(account))


@bp.route("/alternate-payee-accounts/<id>/distributions", methods=["POST"])
@endpoint("PlanAdministrator", "AlternatePayee")
def issue_distribution(caller, id):
    data = v.body()
    expected_version = v.req_int(data, "expected_ap_account_version", 0, None)
    election = v.req_enum(data, "election", enums.ELECTIONS)
    gross = v.req_int(data, "gross_amount_cents", 1, None)
    institution = v.opt_string(data, "rollover_institution", 1, 120)
    account = find_ap_account(id)
    auth.own_ap_account(caller, account)
    if account["status"] != "ESTABLISHED":
        errors.fail(errors.ERR_AP_ACCOUNT_CLOSED, "The alternate payee account is CLOSED.")
    if expected_version != account["version"]:
        errors.fail(errors.ERR_STALE_AP_ACCOUNT_VERSION,
                    "expected_ap_account_version does not match the account's current version.")
    if election == "DIRECT_ROLLOVER" and institution is None:
        errors.fail(errors.ERR_ROLLOVER_INSTITUTION_REQUIRED,
                    "A DIRECT_ROLLOVER election requires a rollover_institution.")
    shared = account["payment_mode"] == "SHARED_PAYMENT"
    if shared and gross != account["per_period_amount_cents"]:
        errors.fail(errors.ERR_SHARED_PAYMENT_AMOUNT_MISMATCH,
                    "gross_amount_cents must equal the account's per_period_amount_cents.")
    plan_account = funding_plan_account(account) if shared else None
    if shared:
        pool = plan_account["available_balance_cents"]
        basis_pool = plan_account["after_tax_basis_cents"]
        balance_pool = plan_account["assignable_base_cents"]
    else:
        pool = account["balance_cents"]
        basis_pool = account["after_tax_basis_cents"]
        balance_pool = account["balance_cents"]
    if gross > pool:
        errors.fail(errors.ERR_INSUFFICIENT_DISTRIBUTABLE_BALANCE,
                    "The requested gross exceeds the funding pool.")

    case = db.qdro_cases[account["qdro_case_id"]]
    settlement = calc.settle_distribution(election, gross, basis_pool, balance_pool,
                                          case["alternate_payee_dob"], db.today())
    fields = {
        "alternate_payee_account_id": account["id"],
        "election": election,
        "gross_amount_cents": gross,
        "rollover_institution": institution,
        "issued_at": db.now_iso(),
        "voided_at": None,
        "status": "ISSUED",
    }
    fields.update(settlement)
    allocations = []
    if shared:
        sources = services.assignable_sources_of(plan_account["id"])
        base = sum(s["balance_cents"] for s in sources)
        allocations = calc.per_source_allocation(gross, sources, base)
    fields["_source_allocations"] = allocations
    distribution = db.new_row("Distribution", fields)
    db.distributions[distribution["id"]] = distribution
    if shared:
        for index, source in enumerate(sources):
            source["balance_cents"] -= allocations[index]
            db.touch(source)
        services.recompute_plan_account(plan_account, force=True)
    services.recompute_ap_account(account)
    services.append_tax_report(distribution)
    if not shared and account["balance_cents"] == 0:
        account["status"] = "CLOSED"
    db.touch(account)
    return object_response(public(distribution), 201)


@bp.route("/alternate-payee-accounts/<id>/distributions", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "AlternatePayee", "Attorney")
def list_distributions(caller, id):
    status = v.query_enum("status", enums.DISTRIBUTION_STATUSES)
    tax_year = v.query_int("tax_year")
    account = find_ap_account(id)
    auth.own_ap_account(caller, account)
    auth.attorney_standing(caller)
    rows = services.distributions_of(account["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tax_year is not None:
        rows = [r for r in rows if r["tax_year"] == tax_year]
    return paginate(public_list(rows))


@bp.route("/distributions/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "AlternatePayee", "Attorney")
def read_distribution(caller, id):
    distribution = find_distribution(id)
    account = db.ap_accounts.get(distribution["alternate_payee_account_id"])
    if account is not None:
        auth.own_ap_account(caller, account)
    auth.attorney_standing(caller)
    return object_response(public(distribution))


@bp.route("/distributions/<id>/void", methods=["POST"])
@endpoint("PlanAdministrator")
def void_distribution(caller, id):
    distribution = find_distribution(id)
    account = db.ap_accounts[distribution["alternate_payee_account_id"]]
    if distribution["status"] != "ISSUED":
        errors.fail(errors.ERR_DISTRIBUTION_ALREADY_VOIDED,
                    "The distribution has already been voided.")
    if account["status"] != "ESTABLISHED":
        errors.fail(errors.ERR_AP_ACCOUNT_CLOSED, "The alternate payee account is CLOSED.")
    if db.today().year != distribution["tax_year"]:
        errors.fail(errors.ERR_VOID_ACROSS_TAX_YEARS,
                    "A distribution may only be voided inside its own tax year.")
    # L1.
    distribution["status"] = "VOIDED"
    distribution["voided_at"] = db.now_iso()
    db.touch(distribution)
    # L2 - the funding side is restored.
    if account["payment_mode"] == "SHARED_PAYMENT":
        plan_account = funding_plan_account(account)
        sources = services.assignable_sources_of(plan_account["id"])
        allocations = distribution.get("_source_allocations") or []
        for index, source in enumerate(sources):
            if index < len(allocations):
                source["balance_cents"] += allocations[index]
                db.touch(source)
        services.recompute_plan_account(plan_account, force=True)
    # L3 - totals recomputed from the ISSUED set alone.
    services.recompute_ap_account(account)
    original = services.original_tax_report(distribution["id"])
    services.append_tax_report(distribution, sign=-1,
                              correction_of=original["id"] if original else None)
    # L4.
    db.touch(account)
    return object_response(public(distribution))


@bp.route("/tax-reports/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "AlternatePayee")
def read_tax_report(caller, id):
    report = find_tax_report(id)
    if caller.is_payee and caller.user_id != report["alternate_payee_account_id"]:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                    "The presented X-User-ID does not own the resource reached.")
    return object_response(public(report))


@bp.route("/tax-reports", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "AlternatePayee")
def list_tax_reports(caller):
    distribution_id = v.query_string("distribution_id")
    account_id = v.query_string("alternate_payee_account_id")
    correction_of = v.query_string("correction_of_tax_report_id")
    tax_year = v.query_int("tax_year")
    rows = order_by(list(db.tax_reports.values()), "written_at")
    if distribution_id is not None:
        rows = [r for r in rows if r["distribution_id"] == distribution_id]
    if account_id is not None:
        rows = [r for r in rows if r["alternate_payee_account_id"] == account_id]
    if correction_of is not None:
        rows = [r for r in rows if r["correction_of_tax_report_id"] == correction_of]
    if tax_year is not None:
        rows = [r for r in rows if r["tax_year"] == tax_year]
    if caller.is_payee:
        rows = [r for r in rows if r["alternate_payee_account_id"] == caller.user_id]
    return paginate(public_list(rows))
