"""Or-equal submittals, specification deviations and the engineer's decision."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import clock
import constants as C
import db
import domain
import response
import serialize
import validate
from errors import fail
from util import D

bp = Blueprint("orequal", __name__)


# ---------------------------------------------------------------- submittals --

@bp.post("/or-equal-submittals")
def create_submittal():
    actor = auth.require("ApplicationEngineer")
    body = validate.body()
    project = validate.catalog_ref(body, "project_id", "projects")
    validate.string(body, "project_id")
    spec_section = validate.string(body, "spec_section", max_length=160)
    named_basis = validate.string(body, "named_basis_of_design", max_length=160)

    row = db.new_row("or_equal_submittals")
    row.update({
        "project_id": project["id"],
        "spec_section": spec_section,
        "named_basis_of_design": named_basis,
        "authored_by_user_id": actor,
        "status": "DRAFT",
        "revision_round": 0,
        "compliance_score": Decimal("100.00"),
        "open_fundamental_count": 0,
        "decided_by_user_id": None,
        "submitted_at": None,
    })
    db.insert("or_equal_submittals", row)
    return response.created(serialize.row(row))


@bp.get("/or-equal-submittals")
def list_submittals():
    auth.require(*auth.ROLES)
    project_id = validate.string_filter("project_id")
    status = validate.enum_filter("status", C.SUBMITTAL_STATUSES)
    rows = db.all_rows("or_equal_submittals")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/or-equal-submittals/<submittal_id>")
def get_submittal(submittal_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.submittal(submittal_id)))


# ---------------------------------------------------------------- deviations --

@bp.post("/or-equal-submittals/<submittal_id>/spec-deviations")
def create_deviation(submittal_id):
    auth.require("ApplicationEngineer")
    submittal = domain.submittal(submittal_id)
    body = validate.body()
    spec_paragraph = validate.string(body, "spec_paragraph", max_length=160)
    severity = validate.enum(body, "severity", C.DEVIATION_SEVERITIES)
    description = validate.string(body, "description", max_length=2000)
    expected_version = validate.integer(
        body, "expected_or_equal_submittal_version", minimum=0)

    domain.check_version(submittal, expected_version, "ERR_STALE_SUBMITTAL_VERSION")

    if submittal["status"] != "DRAFT":
        fail("ERR_SUBMITTAL_INVALID_STATE",
             "deviations may only be disclosed on a DRAFT submittal")

    row = db.new_row("spec_deviations")
    row.update({
        "or_equal_submittal_id": submittal["id"],
        "spec_paragraph": spec_paragraph,
        "severity": severity,
        "description": description,
        "disposition": "PENDING",
        "weighted_penalty_points": Decimal("0.00"),
        "dispositioned_by_user_id": None,
    })
    domain.reprice_deviation(row)
    db.insert("spec_deviations", row)

    domain.rescore_submittal(submittal)
    db.touch(submittal)
    return response.created(serialize.row(row))


@bp.get("/or-equal-submittals/<submittal_id>/spec-deviations")
def list_submittal_deviations(submittal_id):
    auth.require(*auth.ROLES)
    submittal = domain.submittal(submittal_id)
    disposition = validate.enum_filter("disposition", C.DEVIATION_DISPOSITIONS)
    rows = [r for r in db.all_rows("spec_deviations")
            if r["or_equal_submittal_id"] == submittal["id"]]
    if disposition:
        rows = [r for r in rows if r["disposition"] == disposition]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/spec-deviations")
def list_deviations():
    auth.require(*auth.ROLES)
    submittal_id = validate.string_filter("or_equal_submittal_id")
    disposition = validate.enum_filter("disposition", C.DEVIATION_DISPOSITIONS)
    severity = validate.enum_filter("severity", C.DEVIATION_SEVERITIES)
    rows = db.all_rows("spec_deviations")
    if submittal_id:
        rows = [r for r in rows if r["or_equal_submittal_id"] == submittal_id]
    if disposition:
        rows = [r for r in rows if r["disposition"] == disposition]
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/spec-deviations/<deviation_id>")
def get_deviation(deviation_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.deviation(deviation_id)))


@bp.post("/spec-deviations/<deviation_id>/disposition")
def disposition_deviation(deviation_id):
    actor = auth.require("EngineerOfRecord")
    deviation = domain.deviation(deviation_id)
    body = validate.body()
    disposition = validate.enum(body, "disposition", C.DISPOSITION_INPUTS)
    validate.string(body, "disposition_note", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if deviation["disposition"] != "PENDING":
        fail("ERR_DEVIATION_ALREADY_DISPOSITIONED",
             "the deviation has already been dispositioned")

    deviation["disposition"] = disposition
    deviation["dispositioned_by_user_id"] = actor
    domain.reprice_deviation(deviation)
    db.touch(deviation)

    submittal = db.get("or_equal_submittals", deviation["or_equal_submittal_id"])
    if submittal is not None:
        domain.rescore_submittal(submittal)
        db.touch(submittal)

    return response.ok(serialize.row(deviation))


# ------------------------------------------------------------------- transmit --

@bp.post("/or-equal-submittals/<submittal_id>/submit")
def submit_submittal(submittal_id):
    auth.require("ApplicationEngineer")
    submittal = domain.submittal(submittal_id)
    body = validate.body()
    validate.string(body, "transmittal_note", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if submittal["status"] != "DRAFT":
        fail("ERR_SUBMITTAL_INVALID_STATE", "only a DRAFT submittal may be transmitted")

    deviations = calc.submittal_deviations(submittal["id"])
    if not deviations:
        fail("ERR_COMPLIANCE_SCORE_TOO_LOW",
             "a submittal must disclose at least one deviation")
    if D(submittal["compliance_score"]) < C.MIN_COMPLIANCE_SCORE:
        fail("ERR_COMPLIANCE_SCORE_TOO_LOW",
             "compliance score is below the pinned floor of 70.00")

    project = db.get("projects", submittal["project_id"])
    if project is not None and clock.now() >= domain.dt_of(project["bid_due_at"]):
        fail("ERR_BID_WINDOW_CLOSED", "the bid window has closed")

    submittal["status"] = "SUBMITTED"
    submittal["submitted_at"] = clock.now_iso()
    db.touch(submittal)
    return response.ok(serialize.row(submittal))


# ----------------------------------------------------------- engineer decision --

@bp.post("/or-equal-submittals/<submittal_id>/engineer-decision")
def engineer_decision(submittal_id):
    actor = auth.require("EngineerOfRecord")
    submittal = domain.submittal(submittal_id)
    body = validate.body()
    decision = validate.enum(body, "decision", C.ENGINEER_DECISIONS)
    validate.string(body, "decision_note", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if submittal["status"] != "SUBMITTED":
        fail("ERR_SUBMITTAL_INVALID_STATE",
             "only a SUBMITTED submittal may be decided")

    project = db.get("projects", submittal["project_id"])
    deviations = calc.submittal_deviations(submittal["id"])

    if decision == "PRE_APPROVED":
        if int(submittal["open_fundamental_count"]) != 0:
            fail("ERR_FUNDAMENTAL_DEVIATION_OPEN",
                 "an open fundamental deviation blocks pre-approval")
        if D(submittal["compliance_score"]) < C.MIN_COMPLIANCE_SCORE:
            fail("ERR_COMPLIANCE_SCORE_TOO_LOW",
                 "compliance score is below the pinned floor of 70.00")
        submittal["status"] = "PRE_APPROVED"
        submittal["decided_by_user_id"] = actor
        for dev in deviations:
            if dev["disposition"] == "PENDING":
                dev["disposition"] = "ACCEPTED"
                dev["dispositioned_by_user_id"] = actor
                domain.reprice_deviation(dev)
                db.touch(dev)
        domain.rescore_submittal(submittal)
        db.touch(submittal)
        if project is not None and project["status"] in ("SCOPED", "BID_BLOCKED"):
            project["status"] = "BID_READY"
            db.touch(project)
        return response.ok(serialize.row(submittal))

    if decision == "REQUEST_REVISION":
        submittal["status"] = "DRAFT"
        submittal["revision_round"] = int(submittal["revision_round"]) + 1
        submittal["decided_by_user_id"] = actor
        for dev in deviations:
            if dev["disposition"] == "PENDING" and dev["severity"] == "FUNDAMENTAL":
                dev["disposition"] = "REJECTED"
                dev["dispositioned_by_user_id"] = actor
                domain.reprice_deviation(dev)
                db.touch(dev)
        domain.rescore_submittal(submittal)
        db.touch(submittal)
        return response.ok(serialize.row(submittal))

    submittal["status"] = "REJECTED"
    submittal["decided_by_user_id"] = actor
    for dev in deviations:
        if dev["disposition"] == "PENDING":
            dev["disposition"] = "WITHDRAWN"
            dev["dispositioned_by_user_id"] = actor
            domain.reprice_deviation(dev)
            db.touch(dev)
    domain.rescore_submittal(submittal)
    db.touch(submittal)

    if project is not None and project["status"] in ("SCOPED", "BID_READY"):
        others_preapproved = any(
            s["id"] != submittal["id"]
            and s["project_id"] == project["id"]
            and s["status"] == "PRE_APPROVED"
            for s in db.all_rows("or_equal_submittals"))
        if not others_preapproved:
            project["status"] = "BID_BLOCKED"
            db.touch(project)

    return response.ok(serialize.row(submittal))
