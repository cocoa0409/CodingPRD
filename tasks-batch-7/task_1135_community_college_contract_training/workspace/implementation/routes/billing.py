"""Invoice and OutcomeReport endpoints."""

from flask import Blueprint, request

import db
from db import stamp_new, store, touch
from errors import fail
from middleware import check_employer_scope, require_roles
from response import ok, ok_list, serialize
from services import lifecycle, lookups
from services.calculations import invoice_grant_offset, invoice_gross, placement_rate
from util import body_json, pagination_args, req_enum, req_int, req_number

bp = Blueprint("billing", __name__)

READ_ROLES = (
    "CollegeAdmin",
    "WorkforceCoordinator",
    "CredentialOfficer",
    "GrantOfficer",
    "EmployerContact",
    "BillingClerk",
    "Instructor",
)

INVOICE_VARIANTS = ("PROVISIONAL", "FINAL")


def _paginate(items):
    items = sorted(items, key=lambda r: r["created_at"])
    limit, offset = pagination_args()
    page = items[offset : offset + limit]
    return ok_list([serialize(r) for r in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.route("/ct/cohorts/<cid>/invoices", methods=["POST"])
def create_invoice(cid):
    require_roles("BillingClerk")
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    body = body_json()
    variant = req_enum(body, "variant", INVOICE_VARIANTS)
    if variant == "PROVISIONAL":
        allowed = cohort["delivery_status"] in ("LAUNCHED", "IN_PROGRESS")
    else:
        allowed = cohort["delivery_status"] in ("DELIVERED", "CREDENTIALED")
    if not allowed:
        fail(
            "ERR_INVOICE_VARIANT_NOT_ALLOWED",
            f"A {variant} invoice is not allowed for a cohort in {cohort['delivery_status']}",
        )
    for existing in lookups.invoices_of_cohort(cid):
        if existing["status"] in ("DRAFT", "ISSUED"):
            fail("ERR_INVALID_STATE", "An open invoice already exists for this cohort")
    lines, gross = invoice_gross(cohort, variant)
    offset = invoice_grant_offset(cohort, variant, gross)
    rec = stamp_new(
        {
            "id": db.new_id(),
            "cohort_id": cid,
            "agreement_id": cohort["agreement_id"],
            "variant": variant,
            "lines": lines,
            "gross_cents": gross,
            "grant_offset_cents": offset,
            "net_due_cents": gross - offset,
            "status": "DRAFT",
        }
    )
    store["invoices"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = require_roles(*READ_ROLES)
    invoice = lookups.get_or_404("invoices", iid, "Invoice")
    check_employer_scope(uid, role, lookups.employer_id_of_invoice(invoice))
    return ok(serialize(invoice))


@bp.route("/ct/invoices", methods=["GET"])
def list_invoices():
    uid, role = require_roles(*READ_ROLES)
    items = list(store["invoices"].values())
    if role == "EmployerContact":
        items = [i for i in items if lookups.employer_id_of_invoice(i) == uid]
    f_agreement = request.args.get("agreement_id")
    f_cohort = request.args.get("cohort_id")
    f_status = request.args.get("status")
    if f_agreement is not None:
        items = [i for i in items if i["agreement_id"] == f_agreement]
    if f_cohort is not None:
        items = [i for i in items if i["cohort_id"] == f_cohort]
    if f_status is not None:
        items = [i for i in items if i["status"] == f_status]
    return _paginate(items)


@bp.route("/ct/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    require_roles("BillingClerk")
    invoice = lookups.get_or_404("invoices", iid, "Invoice")
    if invoice["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", f"Cannot issue an invoice in {invoice['status']}")
    invoice["status"] = "ISSUED"
    touch(invoice)
    cohort = store["cohorts"].get(invoice["cohort_id"])
    if cohort is not None and cohort["billing_status"] == "UNBILLED":
        cohort["billing_status"] = "INVOICED"
        touch(cohort)
    agreement = store["agreements"].get(invoice["agreement_id"])
    if agreement is not None and agreement["billing_status"] == "UNBILLED":
        agreement["billing_status"] = "PARTIALLY_BILLED"
        touch(agreement)
    return ok(serialize(invoice))


@bp.route("/ct/invoices/<iid>/mark_paid", methods=["POST"])
def mark_invoice_paid(iid):
    require_roles("BillingClerk")
    invoice = lookups.get_or_404("invoices", iid, "Invoice")
    if invoice["status"] != "ISSUED":
        fail("ERR_INVOICE_NOT_PAYABLE", f"Cannot mark paid an invoice in {invoice['status']}")
    invoice["status"] = "PAID"
    touch(invoice)
    cohort = store["cohorts"].get(invoice["cohort_id"])
    if cohort is not None:
        cohort["billing_status"] = "PAID"
        touch(cohort)
    agreement = store["agreements"].get(invoice["agreement_id"])
    if agreement is not None:
        employer = store["employers"].get(agreement["employer_id"])
        if employer is not None:
            employer["lifetime_billed_cents"] += invoice["net_due_cents"]
            touch(employer)
        if agreement["billing_status"] != "SETTLED":
            before = agreement["billing_status"]
            lifecycle.maybe_settle_agreement_billing(agreement)
            if agreement["billing_status"] != before:
                touch(agreement)
    return ok(serialize(invoice))


@bp.route("/ct/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    require_roles("BillingClerk")
    invoice = lookups.get_or_404("invoices", iid, "Invoice")
    if invoice["status"] not in ("DRAFT", "ISSUED"):
        fail("ERR_INVALID_STATE", f"Cannot void an invoice in {invoice['status']}")
    was_issued = invoice["status"] == "ISSUED"
    invoice["status"] = "VOID"
    touch(invoice)
    if was_issued:
        cohort = store["cohorts"].get(invoice["cohort_id"])
        if cohort is not None and cohort["billing_status"] == "INVOICED":
            cohort["billing_status"] = "UNBILLED"
            touch(cohort)
    return ok(serialize(invoice))


# ---------------------------------------------------------------------------
# OutcomeReports
# ---------------------------------------------------------------------------

@bp.route("/ct/training-agreements/<aid>/outcome-reports", methods=["POST"])
def create_outcome_report(aid):
    require_roles("WorkforceCoordinator")
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    body = body_json()
    employed = req_int(body, "completers_employed_90d", min_value=0)
    satisfaction = req_number(body, "satisfaction_avg", min_value=0, allow_zero=True)
    if satisfaction > 5:
        fail("ERR_INVALID_REQUEST", "Field 'satisfaction_avg' must be between 0 and 5")
    follow_on = req_int(body, "follow_on_opportunity_cents", min_value=0)
    if agreement["contract_status"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_AGREEMENT_TERMINAL", f"Agreement is {agreement['contract_status']}")
    if agreement["contract_status"] != "IN_DELIVERY":
        fail(
            "ERR_INVALID_STATE",
            f"Cannot create an outcome report for an agreement in {agreement['contract_status']}",
        )
    rec = stamp_new(
        {
            "id": db.new_id(),
            "agreement_id": aid,
            "completers_employed_90d": employed,
            "satisfaction_avg": satisfaction,
            "follow_on_opportunity_cents": follow_on,
            "placement_pct": None,
            "status": "DRAFT",
        }
    )
    store["reports"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/outcome-reports/<rid>", methods=["GET"])
def get_outcome_report(rid):
    uid, role = require_roles(*READ_ROLES)
    report = lookups.get_or_404("reports", rid, "OutcomeReport")
    check_employer_scope(uid, role, lookups.employer_id_of_report(report))
    return ok(serialize(report))


@bp.route("/ct/outcome-reports/<rid>/submit", methods=["POST"])
def submit_outcome_report(rid):
    require_roles("WorkforceCoordinator")
    report = lookups.get_or_404("reports", rid, "OutcomeReport")
    if report["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", f"Cannot submit an outcome report in {report['status']}")
    agreement = store["agreements"][report["agreement_id"]]
    cohorts = lookups.cohorts_of_agreement(agreement["id"])
    if not all(c["delivery_status"] in ("CREDENTIALED", "CANCELLED") for c in cohorts):
        fail("ERR_OUTCOME_INCOMPLETE", "Not every cohort of the agreement is in a terminal state")
    report["placement_pct"] = placement_rate(agreement, report["completers_employed_90d"])
    report["status"] = "SUBMITTED"
    touch(report)
    return ok(serialize(report))


@bp.route("/ct/outcome-reports/<rid>/accept", methods=["POST"])
def accept_outcome_report(rid):
    require_roles("CollegeAdmin")
    report = lookups.get_or_404("reports", rid, "OutcomeReport")
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", f"Cannot accept an outcome report in {report['status']}")
    report["status"] = "ACCEPTED"
    touch(report)
    agreement = store["agreements"].get(report["agreement_id"])
    if agreement is not None:
        employer = store["employers"].get(agreement["employer_id"])
        if employer is not None:
            employer["follow_on_pipeline_cents"] += report["follow_on_opportunity_cents"]
            touch(employer)
        lifecycle.maybe_complete_agreement(agreement)
    return ok(serialize(report))
