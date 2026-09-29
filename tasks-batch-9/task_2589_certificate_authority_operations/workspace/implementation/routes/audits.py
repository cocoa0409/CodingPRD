"""Root program audits, findings, opinions and correspondence (PRD 3.9)."""

import datetime

from flask import Blueprint

from db import db, make_record, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services import calc
from services.lookup import get_audit
from validation import FINDING_SEVERITIES, ROOT_PROGRAMS, enum_value, req_str, req_ts

bp = Blueprint("audits", __name__)

RESPONSE_WINDOW = datetime.timedelta(days=14)
OPEN_AUDIT_STATES = ("SCHEDULED", "FIELDWORK")


def _new_communication(incident_id, audit_id, root_program, kind, body, sent_by, within_deadline):
    record = make_record({
        "incident_id": incident_id,
        "audit_id": audit_id,
        "root_program": root_program,
        "kind": kind,
        "body": body,
        "sent_at": db.now(),
        "within_deadline": within_deadline,
        "sent_by_user_id": sent_by,
    }, versioned=False)
    db.communications[record["id"]] = record
    return record


@bp.route("/ca/root-program-audits", methods=["POST"])
def create_audit():
    authenticate(("COMPLIANCE_AUDITOR",))
    body = json_body()
    root_program = req_str(body, "root_program")
    period_start = req_ts(body, "period_start")
    period_end = req_ts(body, "period_end")
    enum_value(root_program, ROOT_PROGRAMS, "root_program")

    if period_end <= period_start or (period_end - period_start) > datetime.timedelta(days=366):
        fail(
            "ERR_INVALID_AUDIT_PERIOD",
            "period_end must be strictly after period_start and span at most 366 days.",
        )
    for existing in db.audits.values():
        if existing["root_program"] == root_program and existing["state"] in OPEN_AUDIT_STATES:
            fail("ERR_AUDIT_ALREADY_OPEN", "An audit for that root program is already in flight.")

    record = make_record({
        "root_program": root_program,
        "period_start": period_start,
        "period_end": period_end,
        "state": "SCHEDULED",
        "finding_count": 0,
        "critical_finding_count": 0,
        "opinion_at": None,
        "opined_by_user_id": None,
        "assessed_subscriber_count": 0,
        "retired_profile_count": 0,
    })
    db.audits[record["id"]] = record
    return created(public(record))


@bp.route("/ca/root-program-audits", methods=["GET"])
def list_audits():
    read_only(ALL_ROLES)
    records = apply_filters(db.audits.values(), {"root_program": "str", "state": "str"})
    return paginated(sort_records(records))


@bp.route("/ca/root-program-audits/<audit_id>", methods=["GET"])
def get_one_audit(audit_id):
    read_only(ALL_ROLES)
    return ok(public(get_audit(audit_id)))


@bp.route("/ca/root-program-audits/<audit_id>/findings", methods=["POST"])
def record_finding(audit_id):
    authenticate(("COMPLIANCE_AUDITOR",))
    body = json_body()
    severity = req_str(body, "severity")
    req_str(body, "summary")
    enum_value(severity, FINDING_SEVERITIES, "severity")

    audit = get_audit(audit_id)
    if audit["state"] not in OPEN_AUDIT_STATES:
        fail("ERR_AUDIT_NOT_OPEN_FOR_FINDINGS", "The audit already carries an opinion.")

    audit["finding_count"] += 1
    if severity == "CRITICAL":
        audit["critical_finding_count"] += 1
    audit["state"] = "FIELDWORK"
    touch(audit)
    return ok(public(audit))


@bp.route("/ca/root-program-audits/<audit_id>/opine", methods=["POST"])
def opine_audit(audit_id):
    user_id, _role = authenticate(("COMPLIANCE_AUDITOR",))
    audit = get_audit(audit_id)

    if audit["state"] not in OPEN_AUDIT_STATES:
        fail("ERR_AUDIT_NOT_IN_FIELDWORK", "The audit has already been opined.")
    if audit["finding_count"] < 1:
        fail("ERR_AUDIT_NO_FINDINGS", "An audit with no findings cannot carry an opinion.")

    now = db.now()
    qualified = audit["critical_finding_count"] >= 1 or audit["finding_count"] >= 3
    audit["state"] = "QUALIFIED" if qualified else "UNQUALIFIED"
    audit["opinion_at"] = now
    audit["opined_by_user_id"] = user_id

    assessed = 0
    for subscriber in sort_records(list(db.subscribers.values())):
        incidents = calc.incidents_of_subscriber_in_period(
            subscriber["id"], audit["period_start"], audit["period_end"]
        )
        if not incidents:
            continue
        subscriber["risk_score_audit_final"] = calc.risk_score_audit_final(
            subscriber["id"], audit["period_start"], audit["period_end"], now
        )
        touch(subscriber)
        assessed += 1
    audit["assessed_subscriber_count"] = assessed

    retired = 0
    if qualified:
        targets = [
            p for p in db.profiles.values()
            if p["status"] == "ACTIVE" and p["validation_type"] == "EV"
        ]
        for profile in sort_records(targets):
            profile["status"] = "RETIRED"
            profile["retired_at"] = now
            touch(profile)
            retired += 1
    audit["retired_profile_count"] = retired
    touch(audit)

    _new_communication(
        None,
        audit["id"],
        audit["root_program"],
        "AUDIT_QUALIFIED_NOTICE" if qualified else "AUDIT_CLEAN_NOTICE",
        None,
        "system",
        True,
    )
    return ok(public(audit))


@bp.route("/ca/root-program-audits/<audit_id>/communications", methods=["POST"])
def create_audit_communication(audit_id):
    user_id, _role = authenticate(("COMPLIANCE_AUDITOR",))
    body = json_body()
    root_program = req_str(body, "root_program")
    narrative = req_str(body, "body")
    enum_value(root_program, ROOT_PROGRAMS, "root_program")

    audit = get_audit(audit_id)
    if audit["state"] not in ("QUALIFIED", "UNQUALIFIED"):
        fail("ERR_AUDIT_NOT_OPINED", "Correspondence is only sent after an opinion exists.")

    within = db.now() <= audit["opinion_at"] + RESPONSE_WINDOW
    record = _new_communication(
        None, audit["id"], root_program, "ROOT_PROGRAM_RESPONSE", narrative, user_id, within
    )
    return created(public(record))


@bp.route("/ca/root-program-audits/<audit_id>/communications", methods=["GET"])
def list_audit_communications(audit_id):
    read_only(ALL_ROLES)
    audit = get_audit(audit_id)
    records = [c for c in db.communications.values() if c["audit_id"] == audit["id"]]
    records = apply_filters(records, {"kind": "str"})
    records = sorted(records, key=lambda c: (c["sent_at"], c["_seq"]))
    return paginated(records)
