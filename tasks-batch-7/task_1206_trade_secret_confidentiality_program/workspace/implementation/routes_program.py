"""Program-level routes: logical clock, program status, policy publish, sweep."""

from flask import Blueprint

import db as store
from db import (
    add_days,
    all_rows,
    created_asc,
    db,
    fmt_ts,
    new_record,
    now,
    now_raw,
    parse_dt,
    program,
    set_clock,
    stamp,
    touch,
)
from errors import err_invalid_request
from middleware import actor, body, require_field, require_roles
from response import ok_object
from services import (
    ACK_WINDOW_DAYS,
    anchor_return_obligations,
    recompute_counterparty_exposure,
    recompute_grant_count,
    recompute_nda_counts,
    recompute_training_current,
)

bp = Blueprint("program", __name__)

ENTITY_STATUS_SETS = {
    "SecretAsset": ("assets", ["DRAFT", "REGISTERED", "SUSPENDED", "RETIRED"]),
    "ReasonableMeasure": ("measures", ["PLANNED", "IMPLEMENTED", "VERIFIED", "LAPSED", "ABANDONED"]),
    "Counterparty": ("counterparties", ["ACTIVE", "SUSPENDED", "BARRED"]),
    "NdaAgreement": (
        "ndas",
        ["DRAFT", "SENT", "EXECUTED", "ACTIVE", "BREACH_ALLEGED", "SUPERSEDED", "TERMINATED", "EXPIRED"],
    ),
    "NdaObligation": ("obligations", ["PENDING", "FULFILLED", "WAIVED", "OVERDUE", "ESCALATED"]),
    "Employee": ("employees", ["PREBOARDING", "ACTIVE", "NOTICE", "DEPARTED"]),
    "Acknowledgment": ("acknowledgments", ["PENDING", "SIGNED", "SUPERSEDED", "EXPIRED"]),
    "ExitInterview": (
        "exit_interviews",
        ["SCHEDULED", "CONDUCTED", "NO_SHOW", "CERTIFIED", "ESCALATED", "CANCELLED"],
    ),
    "AccessGrant": (
        "grants",
        ["REQUESTED", "APPROVED", "DENIED", "PROVISIONED", "SUSPENDED", "REVOKED", "EXPIRED"],
    ),
    "DisclosureRequest": (
        "disclosures",
        ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "RETURNED", "WITHDRAWN", "EXECUTED"],
    ),
    "ForensicReview": (
        "forensic_reviews",
        ["OPENED", "IMAGING", "FINDINGS_DRAFTED", "COUNSEL_REVIEW", "CLOSED_NO_ACTION", "ESCALATED"],
    ),
    "DemandLetter": (
        "demand_letters",
        ["DRAFTED", "COUNSEL_APPROVED", "ISSUED", "ACKNOWLEDGED", "COMPLIED", "IGNORED", "LITIGATION", "WITHDRAWN"],
    ),
    "PreservationNotice": ("preservation_notices", ["DRAFT", "ISSUED", "ACTIVE", "RELEASED"]),
    "EvidenceItem": ("evidence_items", ["COLLECTED", "SEALED", "RELEASED"]),
    "TrainingAssignment": (
        "training_assignments",
        ["ASSIGNED", "COMPLETED", "OVERDUE", "ESCALATED", "EXCUSED"],
    ),
    "CleanDeskAudit": (
        "clean_desk_audits",
        ["SCHEDULED", "CONDUCTED", "REPORTED", "REMEDIATING", "CLOSED", "CANCELLED"],
    ),
}


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    user_id, role = actor()
    require_roles(role, "IPCounsel")
    data = body()
    raw = require_field(data, "to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise err_invalid_request("to_iso8601 must be an ISO 8601 timestamp")
    set_clock(dt, raw if isinstance(raw, str) else fmt_ts(dt))
    return ok_object({"now_iso8601": now_raw()})


@bp.get("/api/program/status")
def program_status():
    user_id, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "HRPartner", "SecurityOfficer")
    counts = {}
    for entity_name, (store_name, statuses) in ENTITY_STATUS_SETS.items():
        per_status = {s: 0 for s in statuses}
        for row in all_rows(store_name):
            if row["status"] in per_status:
                per_status[row["status"]] += 1
        counts[entity_name] = per_status
    return ok_object(
        {
            "current_policy_version": program["current_policy_version"],
            "now_iso8601": now_raw(),
            "counts": counts,
        }
    )


@bp.post("/api/program/policy/publish")
def policy_publish():
    user_id, role = actor()
    require_roles(role, "IPCounsel")
    data = body()
    new_version = require_field(data, "new_version")
    if not isinstance(new_version, str) or not new_version:
        raise err_invalid_request("new_version must be a non-empty string")
    if new_version == program["current_policy_version"]:
        raise err_invalid_request("new_version must differ from current_policy_version")
    # Supersede signed acknowledgments not on the new version (created_at ASC).
    superseded = 0
    for ack in created_asc(all_rows("acknowledgments")):
        if ack["status"] == "SIGNED" and ack["policy_version"] != new_version:
            ack["status"] = "SUPERSEDED"
            touch(ack)
            superseded += 1
    # Move the program to the new version, then re-issue fresh PENDING acks.
    program["current_policy_version"] = new_version
    reissued = 0
    due = add_days(now(), ACK_WINDOW_DAYS)
    for emp in created_asc(all_rows("employees")):
        if emp["status"] in ("PREBOARDING", "ACTIVE", "NOTICE"):
            new_record(
                "acknowledgments",
                {
                    "employee_id": emp["id"],
                    "policy_version": new_version,
                    "due_at": fmt_ts(due),
                    "_due_at_dt": due,
                    "signed_at": None,
                    "status": "PENDING",
                },
            )
            reissued += 1
    return ok_object(
        {
            "current_policy_version": new_version,
            "superseded_count": superseded,
            "reissued_count": reissued,
        }
    )


@bp.post("/api/program/sweep")
def sweep():
    """Ops-run checkpoint: fixed class order (PRD §2.5); all comparisons strict."""
    user_id, role = actor()
    require_roles(role, "IPCounsel", "SecurityOfficer")
    n = now()

    # 1. NDAs expire.
    ndas_expired = 0
    for nda in created_asc(all_rows("ndas")):
        if nda["status"] == "ACTIVE" and n > nda["_expiry_dt"]:
            nda["status"] = "EXPIRED"
            touch(nda)
            anchor_return_obligations(nda, nda["_expiry_dt"])
            cp = db["counterparties"].get(nda["counterparty_id"])
            if cp is not None:
                recompute_counterparty_exposure(cp)
            ndas_expired += 1

    # 2. Obligations go overdue.
    obligations_overdue = 0
    for ob in created_asc(all_rows("obligations")):
        if ob["status"] == "PENDING" and ob["_due_at_dt"] is not None and n > ob["_due_at_dt"]:
            ob["status"] = "OVERDUE"
            touch(ob)
            nda = db["ndas"].get(ob["nda_id"])
            if nda is not None:
                recompute_nda_counts(nda)
                cp = db["counterparties"].get(nda["counterparty_id"])
                if cp is not None:
                    recompute_counterparty_exposure(cp)
            obligations_overdue += 1

    # 3. Grants expire (APPROVED / PROVISIONED only).
    grants_expired = 0
    for g in created_asc(all_rows("grants")):
        if g["status"] in ("APPROVED", "PROVISIONED") and n > g["_expires_at_dt"]:
            g["status"] = "EXPIRED"
            touch(g)
            asset = db["assets"].get(g["asset_id"])
            if asset is not None:
                recompute_grant_count(asset)
            grants_expired += 1

    # 4. Training assignments go overdue.
    trainings_overdue = 0
    for t in created_asc(all_rows("training_assignments")):
        if t["status"] == "ASSIGNED" and n > t["_due_at_dt"]:
            t["status"] = "OVERDUE"
            touch(t)
            emp = db["employees"].get(t["employee_id"])
            if emp is not None:
                recompute_training_current(emp)
            trainings_overdue += 1

    # 5. Acknowledgments expire.
    acks_expired = 0
    for a in created_asc(all_rows("acknowledgments")):
        if a["status"] == "PENDING" and n > a["_due_at_dt"]:
            a["status"] = "EXPIRED"
            touch(a)
            acks_expired += 1

    # 6. Demand letters go ignored.
    letters_ignored = 0
    for letter in created_asc(all_rows("demand_letters")):
        if (
            letter["status"] in ("ISSUED", "ACKNOWLEDGED")
            and letter.get("_response_deadline_dt") is not None
            and n > letter["_response_deadline_dt"]
        ):
            letter["status"] = "IGNORED"
            touch(letter)
            letters_ignored += 1

    return ok_object(
        {
            "ndas_expired": ndas_expired,
            "obligations_overdue": obligations_overdue,
            "grants_expired": grants_expired,
            "trainings_overdue": trainings_overdue,
            "acks_expired": acks_expired,
            "letters_ignored": letters_ignored,
        }
    )
