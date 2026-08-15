"""Policy application endpoints (PRD 3.5): submission with the JIT trigger and
provisional commission, decide, issue, rescind."""

from flask import Blueprint

from core import calc, cascade, constants as K
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import (
    authorize, producer_scope, req_enum, req_int, req_str, resolve,
)
from core.routes_shared import create_commission_entry
from core.serialize import application as serialize_application
from core.store import db, new_row, bump
from routes.appointments import check_appointment_uniqueness

bp = Blueprint("applications", __name__)

_READ_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin", "Producer")
_LIST_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin")


@bp.route("/api/applications", methods=["POST"])
def create_application():
    ctx = authorize("Producer", "LicensingCoordinator")
    producer_id = ctx.body.get("producer_id")
    if not isinstance(producer_id, str) or producer_id == "":
        fail("ERR_INVALID_REQUEST", "Field 'producer_id' is required and must be a string id.")
    state_code = req_str(ctx.body, "state_code")
    loa = req_enum(ctx.body, "line_of_authority", K.LOAS)
    applicant_name = req_str(ctx.body, "applicant_name")
    premium_cents = req_int(ctx.body, "premium_cents")
    producer = resolve("producers", producer_id)
    producer_scope(ctx, producer["id"])
    # Business-safety before structural before fiscal (PRD 2.9 rungs 8 < 15, 18 < 21).
    if producer["status"] != "ACTIVE":
        fail("ERR_PRODUCER_SUSPENDED", "The writing producer is not ACTIVE.")

    snapshot = calc.eligibility_posture(producer, state_code, loa)["eligibility_status"]

    jit_appointment = None
    if snapshot == "APPOINTMENT_GAP":
        # Both appointment creation guards bind system JIT creation as well.
        check_appointment_uniqueness("producer_id", producer["id"], state_code, db.now)

    if premium_cents < K.MIN_PREMIUM_CENTS:
        fail("ERR_PREMIUM_BELOW_MINIMUM", "premium_cents must be at least 500.")

    submitted_at = db.now
    if snapshot == "APPOINTMENT_GAP":
        jit_appointment = new_row("appointments", {
            "producer_id": producer["id"],
            "agency_id": None,
            "state_code": state_code,
            "lines_of_authority": [loa],
            "origin": "JIT",
            "status": "JIT_PENDING",
            "effective_date": submitted_at,
            "termination_date": None,
            "termination_reason": None,
            "termination_initiated_at": None,
            "jit_filing_deadline": calc.jit_filing_deadline(submitted_at),
        })

    row = new_row("applications", {
        "producer_id": producer["id"],
        "state_code": state_code,
        "line_of_authority": loa,
        "applicant_name": applicant_name,
        "premium_cents": premium_cents,
        "status": "SUBMITTED",
        "submitted_at": submitted_at,
        "decided_at": None,
        "issued_at": None,
        "eligibility_snapshot": snapshot,
        "jit_appointment_id": jit_appointment["id"] if jit_appointment is not None else None,
    })
    create_commission_entry(row, producer)
    return object_response(serialize_application(row), 201)


@bp.route("/api/applications/<applicationId>", methods=["GET"])
def get_application(applicationId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("applications", applicationId)
    producer_scope(ctx, row["producer_id"])
    return object_response(serialize_application(row), 200)


@bp.route("/api/applications", methods=["GET"])
def list_applications():
    authorize(*_LIST_ROLES)
    rows = db.ordered("applications")
    rows = filter_exact(rows, "producer_id")
    rows = filter_exact(rows, "status")
    rows = filter_exact(rows, "jit_appointment_id")
    return paginate(rows, serialize_application)


@bp.route("/api/applications/<applicationId>/decide", methods=["POST"])
def decide_application(applicationId):
    ctx = authorize("LicensingCoordinator")
    app = resolve("applications", applicationId)
    decision = req_enum(ctx.body, "decision", ("APPROVE", "DECLINE"))
    if app["status"] != "SUBMITTED":
        fail(
            "ERR_INVALID_STATE",
            "Application in status {} cannot be decided.".format(app["status"]),
        )
    if decision == "DECLINE":
        cascade.decline_application(app)
        return object_response(serialize_application(app), 200)
    # APPROVE: the license gate (rung 9).
    lic = calc.active_license_covering(
        "producer_id", app["producer_id"], app["state_code"], [app["line_of_authority"]]
    )
    if lic is None:
        fail(
            "ERR_LICENSE_NOT_ACTIVE",
            "Producer holds no ACTIVE license in this state covering the line.",
        )
    app["status"] = "APPROVED"
    app["decided_at"] = db.now
    bump(app)
    return object_response(serialize_application(app), 200)


@bp.route("/api/applications/<applicationId>/issue", methods=["POST"])
def issue_application(applicationId):
    authorize("LicensingCoordinator")
    app = resolve("applications", applicationId)
    if app["status"] != "APPROVED":
        fail(
            "ERR_INVALID_STATE",
            "Application in status {} cannot be issued.".format(app["status"]),
        )
    producer = db.producers.get(app["producer_id"])
    if producer is None or producer["status"] != "ACTIVE":
        fail("ERR_PRODUCER_SUSPENDED", "The writing producer is not ACTIVE.")
    appt, _ = calc.covering_appointment(producer, app["state_code"], app["line_of_authority"])
    if appt is None:
        fail(
            "ERR_APPOINTMENT_NOT_ACTIVE",
            "No ACTIVE appointment (own or affiliated agency) covers this line in this state.",
        )
    # FINAL pricing reads the YTD total BEFORE this application's own premium
    # enters the input set - a single application never tiers itself up.
    ytd_before = calc.producer_ytd_live(producer["id"])
    entry = calc.entry_for_application(app["id"])
    final_amount = calc.commission_amount_cents(app, producer, ytd_before)
    app["status"] = "ISSUED"
    app["issued_at"] = db.now
    app["eligibility_snapshot"] = calc.eligibility_posture(
        producer, app["state_code"], app["line_of_authority"]
    )["eligibility_status"]
    bump(app)
    calc.recompute_producer_ytd(producer)
    if entry is not None:
        entry["amount_cents"] = final_amount
        entry["amount_variant"] = "FINAL"
        bump(entry)
        if entry["status"] == "HELD":
            calc.recompute_producer_held(producer["id"])
    return object_response(serialize_application(app), 200)


@bp.route("/api/applications/<applicationId>/rescind", methods=["POST"])
def rescind_application(applicationId):
    authorize("LicensingCoordinator")
    app = resolve("applications", applicationId)
    if app["status"] != "ISSUED":
        fail(
            "ERR_INVALID_STATE",
            "Application in status {} cannot be rescinded.".format(app["status"]),
        )
    app["status"] = "RESCINDED"
    bump(app)
    producer = db.producers.get(app["producer_id"])
    if producer is not None:
        calc.recompute_producer_ytd(producer)
    entry = calc.entry_for_application(app["id"])
    if cascade.forfeit_entry(entry, include_paid=True):
        calc.recompute_producer_held(app["producer_id"])
    return object_response(serialize_application(app), 200)
