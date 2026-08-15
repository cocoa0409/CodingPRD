"""Routes: flat alias GETs (fetch by id without ancestors) and FK reverse
lookup list endpoints."""
from flask import Blueprint, jsonify, request

from core import (
    db, auth, envelope_obj, paginate, get_or_404, observe_offering,
    observe_account,
)
from serializers import (
    ser_department, ser_offering, ser_fee_item, ser_purchase_item,
    ser_enrollment, ser_assessment, ser_purchase, ser_program,
    ser_application, ser_payment, ser_plan, ser_refund, ser_run,
    ser_installment, ser_allocation, ser_ledger,
)

bp = Blueprint("alias", __name__)
ANY = ("Bookkeeper", "FamilyMember", "Superintendent")


def ok(payload, code=200):
    resp = jsonify(payload)
    resp.status_code = code
    return resp


# ---------------------------------------------------------------------------
# Flat alias GETs
# ---------------------------------------------------------------------------

@bp.get("/departments/<id>")
def alias_department(id):
    auth(ANY)
    return ok(envelope_obj(ser_department(
        get_or_404("departments", id, "department"))))


@bp.get("/offerings/<id>")
def alias_offering(id):
    auth(ANY)
    off = get_or_404("offerings", id, "offering")
    observe_offering(off)
    return ok(envelope_obj(ser_offering(off)))


@bp.get("/fee-catalog-items/<id>")
def alias_fee_item(id):
    auth(ANY)
    return ok(envelope_obj(ser_fee_item(
        get_or_404("fee_items", id, "fee catalog item"))))


@bp.get("/optional-purchase-items/<id>")
def alias_purchase_item(id):
    auth(ANY)
    return ok(envelope_obj(ser_purchase_item(
        get_or_404("purchase_items", id, "optional purchase item"))))


@bp.get("/enrollments/<id>")
def alias_enrollment(id):
    auth(ANY)
    return ok(envelope_obj(ser_enrollment(
        get_or_404("enrollments", id, "enrollment"))))


@bp.get("/fee-assessments/<id>")
def alias_assessment(id):
    auth(ANY)
    return ok(envelope_obj(ser_assessment(
        get_or_404("assessments", id, "fee assessment"))))


@bp.get("/purchases/<id>")
def alias_purchase(id):
    auth(ANY)
    return ok(envelope_obj(ser_purchase(
        get_or_404("purchases", id, "purchase"))))


@bp.get("/waiver-programs/<id>")
def alias_program(id):
    auth(ANY)
    return ok(envelope_obj(ser_program(
        get_or_404("programs", id, "waiver program"))))


@bp.get("/waiver-applications/<id>")
def alias_application(id):
    auth(ANY)
    return ok(envelope_obj(ser_application(
        get_or_404("applications", id, "waiver application"))))


@bp.get("/payments/<id>")
def alias_payment(id):
    auth(ANY)
    return ok(envelope_obj(ser_payment(get_or_404("payments", id, "payment"))))


@bp.get("/payment-plans/<id>")
def alias_plan(id):
    auth(ANY)
    plan = get_or_404("plans", id, "payment plan")
    account = db.accounts.get(plan["student_account_id"])
    if account is not None:
        observe_account(account)
    return ok(envelope_obj(ser_plan(plan)))


@bp.get("/refunds/<id>")
def alias_refund(id):
    auth(ANY)
    return ok(envelope_obj(ser_refund(get_or_404("refunds", id, "refund"))))


@bp.get("/reconciliation-runs/<id>")
def alias_run(id):
    auth(ANY)
    return ok(envelope_obj(ser_run(
        get_or_404("runs", id, "reconciliation run"))))


# ---------------------------------------------------------------------------
# FK reverse lookups
# ---------------------------------------------------------------------------

@bp.get("/departments/<id>/offerings")
def dept_offerings(id):
    auth(ANY)
    get_or_404("departments", id, "department")
    rows = [o for o in db.offerings.values() if o["department_id"] == id]
    for o in rows:
        observe_offering(o)
    return ok(paginate(rows, ser_offering))


@bp.get("/fee-catalog-items/<id>/offerings")
def fee_item_offerings(id):
    auth(ANY)
    get_or_404("fee_items", id, "fee catalog item")
    rows = [o for o in db.offerings.values() if o["fee_item_id"] == id]
    for o in rows:
        observe_offering(o)
    return ok(paginate(rows, ser_offering))


@bp.get("/departments/<id>/fee-catalog-items")
def dept_fee_items(id):
    auth(ANY)
    get_or_404("departments", id, "department")
    rows = [i for i in db.fee_items.values() if i["department_id"] == id]
    return ok(paginate(rows, ser_fee_item))


@bp.get("/departments/<id>/optional-purchase-items")
def dept_purchase_items(id):
    auth(ANY)
    get_or_404("departments", id, "department")
    rows = [i for i in db.purchase_items.values() if i["department_id"] == id]
    return ok(paginate(rows, ser_purchase_item))


@bp.get("/offerings/<id>/enrollments")
def offering_enrollments(id):
    auth(ANY)
    get_or_404("offerings", id, "offering")
    rows = [e for e in db.enrollments.values() if e["offering_id"] == id]
    if "status" in request.args:
        rows = [e for e in rows if e["status"] == request.args["status"]]
    return ok(paginate(rows, ser_enrollment))


@bp.get("/enrollments/<id>/fee-assessments")
def enrollment_assessments(id):
    auth(ANY)
    get_or_404("enrollments", id, "enrollment")
    rows = [a for a in db.assessments.values() if a.get("enrollment_id") == id]
    return ok(paginate(rows, ser_assessment))


@bp.get("/fee-catalog-items/<id>/fee-assessments")
def fee_item_assessments(id):
    auth(ANY)
    get_or_404("fee_items", id, "fee catalog item")
    rows = [a for a in db.assessments.values() if a["fee_item_id"] == id]
    return ok(paginate(rows, ser_assessment))


@bp.get("/departments/<id>/fee-assessments")
def dept_assessments(id):
    auth(ANY)
    get_or_404("departments", id, "department")
    rows = [a for a in db.assessments.values() if a["department_id"] == id]
    if "status" in request.args:
        rows = [a for a in rows if a["status"] == request.args["status"]]
    return ok(paginate(rows, ser_assessment))


@bp.get("/payment-plans/<id>/fee-assessments")
def plan_assessments(id):
    auth(ANY)
    get_or_404("plans", id, "payment plan")
    rows = [a for a in db.assessments.values()
            if a.get("payment_plan_id") == id]
    return ok(paginate(rows, ser_assessment))


@bp.get("/optional-purchase-items/<id>/purchases")
def item_purchases(id):
    auth(ANY)
    get_or_404("purchase_items", id, "optional purchase item")
    rows = [p for p in db.purchases.values() if p["item_id"] == id]
    if "status" in request.args:
        rows = [p for p in rows if p["status"] == request.args["status"]]
    return ok(paginate(rows, ser_purchase))


@bp.get("/waiver-programs/<id>/waiver-applications")
def program_applications(id):
    auth(ANY)
    get_or_404("programs", id, "waiver program")
    rows = [a for a in db.applications.values()
            if a["waiver_program_id"] == id]
    if "status" in request.args:
        rows = [a for a in rows if a["status"] == request.args["status"]]
    return ok(paginate(rows, ser_application))


@bp.get("/payments/<id>/allocations")
def payment_allocations(id):
    auth(ANY)
    get_or_404("payments", id, "payment")
    rows = [a for a in db.allocations.values() if a["payment_id"] == id]
    return ok(paginate(rows, ser_allocation))


@bp.get("/fee-assessments/<id>/payment-allocations")
def assessment_allocations(id):
    auth(ANY)
    get_or_404("assessments", id, "fee assessment")
    rows = [a for a in db.allocations.values() if a["fee_assessment_id"] == id]
    return ok(paginate(rows, ser_allocation))


@bp.get("/payment-plans/<id>/installments")
def plan_installments(id):
    auth(ANY)
    plan = get_or_404("plans", id, "payment plan")
    account = db.accounts.get(plan["student_account_id"])
    if account is not None:
        observe_account(account)
    rows = [i for i in db.installments.values() if i["payment_plan_id"] == id]
    if "status" in request.args:
        rows = [i for i in rows if i["status"] == request.args["status"]]
    return ok(paginate(rows, ser_installment))


@bp.get("/fee-assessments/<id>/refunds")
def assessment_refunds(id):
    auth(ANY)
    get_or_404("assessments", id, "fee assessment")
    rows = [r for r in db.refunds.values() if r.get("fee_assessment_id") == id]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    return ok(paginate(rows, ser_refund))


@bp.get("/purchases/<id>/refunds")
def purchase_refunds(id):
    auth(ANY)
    get_or_404("purchases", id, "purchase")
    rows = [r for r in db.refunds.values() if r.get("purchase_id") == id]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    return ok(paginate(rows, ser_refund))


@bp.get("/departments/<id>/ledger-entries")
def dept_ledger(id):
    auth(ANY)
    get_or_404("departments", id, "department")
    rows = [e for e in db.ledger.values() if e["department_id"] == id]
    if "entry_type" in request.args:
        rows = [e for e in rows if e["entry_type"] == request.args["entry_type"]]
    return ok(paginate(rows, ser_ledger))


@bp.get("/payments/<id>/ledger-entries")
def payment_ledger(id):
    auth(ANY)
    get_or_404("payments", id, "payment")
    rows = [e for e in db.ledger.values() if e["source_payment_id"] == id]
    return ok(paginate(rows, ser_ledger))


@bp.get("/reconciliation-runs/<id>/ledger-entries")
def run_ledger(id):
    auth(ANY)
    get_or_404("runs", id, "reconciliation run")
    rows = [e for e in db.ledger.values()
            if e["reconciliation_run_id"] == id]
    return ok(paginate(rows, ser_ledger))


@bp.get("/school-years/<id>/reconciliation-runs")
def year_runs(id):
    auth(ANY)
    get_or_404("years", id, "school year")
    rows = [r for r in db.runs.values() if r["school_year_id"] == id]
    return ok(paginate(rows, ser_run))
