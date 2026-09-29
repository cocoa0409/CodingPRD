"""ReconciliationRun endpoints (PRD 3.8)."""

from flask import Blueprint

from auth import ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_PROGRAM_ADMIN, authenticate
from calc import VARIANCE_TOLERANCE_CENTS, rebate_and_settlement
from domain import (close_term_if_ready, get_agreement, get_run, get_term,
                    reconciliation_totals, run_json)
from errors import fail
from response import apply_filters, object_response, paginate
from store import base_record, db, in_order, now, touch
from validate import f_enum, f_int, f_str, get_body

bp = Blueprint("reconciliation", __name__)

METHODS = ("ENROLLMENT_SNAPSHOT", "ACCESS_DAYS_WEIGHTED")


def _latest(runs):
    if not runs:
        return None
    return sorted(runs, key=lambda r: (r["created_at"], r["_seq"]))[-1]


def _current_run(agreement_id, term_id, statuses):
    return _latest([r for r in db.runs.values()
                    if r["agreement_id"] == agreement_id
                    and r["term_id"] == term_id
                    and r["status"] in statuses])


@bp.post("/reconciliation-runs")
def create_run():
    actor = authenticate(ROLE_PROGRAM_ADMIN)
    body = get_body(("agreement_id", "term_id", "method", "publisher_reported_count",
                     "publisher_reported_amount_cents", "expected_agreement_version",
                     "supersedes_run_id"))
    agreement_id = f_str(body, "agreement_id")
    term_id = f_str(body, "term_id")
    method = f_enum(body, "method", METHODS)
    reported_count = f_int(body, "publisher_reported_count", minimum=0)
    reported_amount = f_int(body, "publisher_reported_amount_cents", minimum=0)
    expected_version = f_int(body, "expected_agreement_version")
    supersedes_run_id = f_str(body, "supersedes_run_id", required=False, default=None)

    # Declaration order: term_id, then agreement_id, then supersedes_run_id.
    term = get_term(term_id)
    agreement = get_agreement(agreement_id)
    prior = get_run(supersedes_run_id) if supersedes_run_id is not None else None

    if expected_version != agreement["version"]:
        fail("ERR_STALE_AGREEMENT_VERSION")

    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE")
    if agreement["reconciliation_status"] not in ("NOT_STARTED", "STALE", "COMPUTED"):
        fail("ERR_INVALID_STATE")

    current = _current_run(agreement["id"], term["id"], ("COMPUTED",))
    if agreement["reconciliation_status"] == "COMPUTED" and current is not None:
        # A recompute must name the pairing's current computed run.
        if prior is None or prior["id"] != current["id"]:
            fail("ERR_INVALID_STATE")
    if prior is not None:
        if (prior["agreement_id"] != agreement["id"]
                or prior["term_id"] != term["id"]
                or prior["status"] != "COMPUTED"
                or current is None or prior["id"] != current["id"]):
            fail("ERR_INVALID_STATE")

    billable_count, opted_out_count, gross = reconciliation_totals(agreement, term, method)
    rebate, settlement = rebate_and_settlement(
        gross, agreement["rebate_threshold_cents"], agreement["rebate_pct"])

    run = base_record()
    run.update({
        "agreement_id": agreement["id"],
        "term_id": term["id"],
        "supersedes_run_id": prior["id"] if prior is not None else None,
        "method": method,
        "status": "COMPUTED",
        "billable_count": billable_count,
        "opted_out_count": opted_out_count,
        "gross_invoice_cents": gross,
        "rebate_cents": rebate,
        "settlement_amount_cents": settlement,
        "publisher_reported_count": reported_count,
        "publisher_reported_amount_cents": reported_amount,
        "count_variance": reported_count - billable_count,
        "variance_cents": reported_amount - settlement,
        "dispute_note": None,
        "computed_by_user_id": actor.user_id,
        "settled_by_user_id": None,
        "settled_at": None,
    })
    db.runs[run["id"]] = run

    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    agreement["reconciliation_status"] = "COMPUTED"
    touch(agreement)
    return object_response(run_json(run), 201)


@bp.get("/reconciliation-runs/<run_id>")
def read_run(run_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE)
    return object_response(run_json(get_run(run_id)))


@bp.get("/reconciliation-runs")
def list_runs():
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE)
    items = apply_filters(in_order(db.runs.values()), [
        ("agreement_id", "agreement_id"),
        ("term_id", "term_id"),
        ("supersedes_run_id", "supersedes_run_id"),
        ("status", "status"),
        ("method", "method"),
    ])
    return paginate(items, run_json)


@bp.post("/reconciliation-runs/<run_id>/dispute")
def dispute_run(run_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    body = get_body(("dispute_note",))
    note = f_str(body, "dispute_note")
    run = get_run(run_id)
    agreement = get_agreement(run["agreement_id"])

    if run["status"] != "COMPUTED":
        fail("ERR_INVALID_STATE")
    current = _current_run(run["agreement_id"], run["term_id"], ("COMPUTED",))
    if current is None or current["id"] != run["id"]:
        fail("ERR_INVALID_STATE")
    if agreement["reconciliation_status"] != "COMPUTED":
        fail("ERR_INVALID_STATE")
    if abs(run["variance_cents"]) <= VARIANCE_TOLERANCE_CENTS:
        fail("ERR_VARIANCE_WITHIN_TOLERANCE")

    run["status"] = "DISPUTED"
    run["dispute_note"] = note
    touch(run)
    agreement["reconciliation_status"] = "DISPUTED"
    touch(agreement)
    return object_response(run_json(run))


@bp.post("/reconciliation-runs/<run_id>/settle")
def settle_run(run_id):
    actor = authenticate(ROLE_PROGRAM_ADMIN)
    get_body(())
    run = get_run(run_id)
    agreement = get_agreement(run["agreement_id"])
    term = get_term(run["term_id"])

    if run["status"] == "COMPUTED":
        if agreement["reconciliation_status"] != "COMPUTED":
            fail("ERR_INVALID_STATE")
        if abs(run["variance_cents"]) > VARIANCE_TOLERANCE_CENTS:
            fail("ERR_VARIANCE_TOLERANCE_EXCEEDED")
        if term["status"] != "BILLING_LOCKED":
            fail("ERR_TERM_NOT_LOCKED")
        settled_amount = run["settlement_amount_cents"]
    elif run["status"] == "DISPUTED":
        if agreement["reconciliation_status"] != "DISPUTED":
            fail("ERR_INVALID_STATE")
        if term["status"] != "BILLING_LOCKED":
            fail("ERR_TERM_NOT_LOCKED")
        settled_amount = run["publisher_reported_amount_cents"]
    else:
        fail("ERR_INVALID_STATE")

    run["status"] = "SETTLED"
    run["settled_at"] = now()
    run["settled_by_user_id"] = actor.user_id
    touch(run)

    # Hop one.
    agreement["reconciliation_status"] = "SETTLED"
    agreement["settled_amount_cents"] = settled_amount
    touch(agreement)
    # Hops two and three.
    close_term_if_ready(term)
    return object_response(run_json(run))
