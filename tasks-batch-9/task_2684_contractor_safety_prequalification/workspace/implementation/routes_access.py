"""The gate: badging workers onto sites, and the incident cascade."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import cascade
import derive
import response
import serialize
import store
import validators as V
from errors import fail
from store import S, insert, now, touch

bp = Blueprint("access", __name__)


@bp.route("/site-access-grants", methods=["POST"])
def create_grant():
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [
            ("worker_id", "string", True),
            ("site_id", "string", True),
            ("prequalification_id", "string", True),
            ("expires_at", "string", True),
        ]
    )
    expires_at = V.parse_instant("expires_at", body["expires_at"])
    clock = now()
    if expires_at <= clock:
        fail("ERR_INVALID_FIELD_VALUE", "expires_at must be strictly after the logical clock.")

    worker = V.get_worker(body["worker_id"])
    site = V.get_site(body["site_id"])
    preq = V.get_prequalification(body["prequalification_id"])
    auth.check_owner(role, user_id, contractor_id=preq["contractor_id"])

    # Coherence of the three references, before any posture check.
    if worker["contractor_id"] != preq["contractor_id"]:
        fail("ERR_INVALID_FIELD_VALUE", "The worker is not employed by the prequalified contractor.")
    if site["client_id"] != preq["client_id"]:
        fail("ERR_INVALID_FIELD_VALUE", "The site does not belong to the grading client.")

    contractor = S.contractors[preq["contractor_id"]]
    client = S.clients[preq["client_id"]]

    if contractor["status"] != "ACTIVE":
        fail("ERR_CONTRACTOR_NOT_ACTIVE", "The contractor is not ACTIVE.")
    if preq["status"] not in ("APPROVED", "CONDITIONAL"):
        fail("ERR_PREQUAL_NOT_ACTIVE", "The prequalification is not in active standing.")

    gate = derive.site_access_gate_status(site["id"])
    if gate == "LOCKED":
        fail("ERR_SITE_GATE_LOCKED", "The site gate is locked.")

    if not set(site["required_hazard_classes"]).issubset(set(contractor["hazard_profile"])):
        fail(
            "ERR_HAZARD_PROFILE_MISMATCH",
            "The contractor's hazard profile does not cover this site.",
        )

    demanded = calc.required_qualification_set(site["required_hazard_classes"])
    rows = derive.quals_of(worker["id"])
    for code in sorted(demanded):
        candidates = [r for r in rows if r["qualification_code"] == code]
        if not candidates:
            fail("ERR_WORKER_QUALIFICATION_EXPIRED", "Worker lacks credential %s." % code)
        latest = max(candidates, key=lambda r: r["expiration_date"])
        if not latest["expiration_date"] > clock:
            fail("ERR_WORKER_QUALIFICATION_EXPIRED", "Credential %s is not current." % code)

    pair_grants = [
        g
        for g in S.site_access_grants.values()
        if g["worker_id"] == worker["id"] and g["site_id"] == site["id"]
    ]
    for grant in pair_grants:
        if grant["status"] == "REVOKED" and grant["revoked_at"] is not None:
            if clock < grant["revoked_at"] + timedelta(hours=calc.ACCESS_COOLDOWN_HOURS):
                fail("ERR_ACCESS_COOLDOWN_ACTIVE", "The revocation cooldown has not elapsed.")
    for grant in pair_grants:
        if grant["status"] != "GRANTED":
            continue
        if calc.windows_overlap_closed(
            clock, expires_at, grant["granted_at"], grant["expires_at"]
        ):
            fail("ERR_ACCESS_WINDOW_OVERLAP", "The requested window collides with a live grant.")

    derive.coverage_gate(contractor, client)

    required_rank = calc.effective_min_rank(site["min_grade"], gate)
    grade = preq["grade"]
    if grade is None or calc.GRADE_RANK[grade] < required_rank:
        fail("ERR_GRADE_BELOW_SITE_MINIMUM", "The grade is below the site's effective minimum.")

    row = store.base_row()
    row.update(
        {
            "worker_id": worker["id"],
            "site_id": site["id"],
            "prequalification_id": preq["id"],
            "granted_at": clock,
            "expires_at": expires_at,
            "status": "GRANTED",
            "revocation_reason": None,
            "revoked_at": None,
            "qualification_snapshot": sorted(demanded),
        }
    )
    insert(S.site_access_grants, row)
    derive.recompute_site(site)
    return response.created(serialize.site_access_grant(row))


@bp.route("/site-access-grants/<grant_id>/revoke", methods=["POST"])
def revoke_grant(grant_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body([("revocation_reason", "string", False)])
    reason = "CLIENT_REVOKED"
    if body["revocation_reason"] is not None:
        reason = V.check_enum("revocation_reason", body["revocation_reason"], ("CLIENT_REVOKED",))

    row = V.get_leaf(S.site_access_grants, grant_id)
    site = S.sites[row["site_id"]]
    auth.check_owner(role, user_id, client_id=site["client_id"])

    if row["status"] != "GRANTED":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only a GRANTED badge may be revoked.")

    cascade.revoke_grant(row, reason)
    return response.ok(serialize.site_access_grant(row))


@bp.route("/incident-reports", methods=["POST"])
def create_incident_report():
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body(
        [
            ("contractor_id", "string", True),
            ("site_id", "string", True),
            ("occurred_at", "string", True),
            ("severity", "string", True),
            ("osha_reportable", "boolean", False),
            ("description", "string", True),
        ]
    )
    occurred_at = V.parse_instant("occurred_at", body["occurred_at"])
    severity = V.check_enum("severity", body["severity"], calc.SEVERITIES)
    description = V.check_str_len("description", body["description"], 1, 500)
    osha_reportable = bool(body["osha_reportable"]) if body["osha_reportable"] is not None else False
    clock = now()
    if occurred_at > clock:
        fail("ERR_INVALID_FIELD_VALUE", "occurred_at may not be in the future.")
    if occurred_at < clock - timedelta(days=calc.INCIDENT_LOOKBACK_DAYS):
        fail("ERR_INVALID_FIELD_VALUE", "occurred_at is older than the 365-day window.")

    contractor = V.get_contractor(body["contractor_id"])
    site = V.get_site(body["site_id"])
    auth.check_owner(role, user_id, client_id=site["client_id"])

    row = store.base_row()
    row.update(
        {
            "contractor_id": contractor["id"],
            "site_id": site["id"],
            "occurred_at": occurred_at,
            "severity": severity,
            "osha_reportable": osha_reportable,
            "description": description,
            "review_status": "OPEN",
            "findings_note": None,
            "closed_at": None,
            "triggered_suspension_count": 0,
        }
    )
    insert(S.incident_reports, row)

    flag_before = contractor["incident_review_flag"]
    derive.recompute_incident_counters(contractor)
    if severity in calc.SEVERE_SEVERITIES:
        derive.rematerialize_available_aggregate(contractor)
    touch(contractor)
    derive.recompute_site(site)

    if not flag_before and contractor["incident_review_flag"]:
        cascade.freeze_contractor(contractor, row)
    return response.created(serialize.incident_report(row))


@bp.route("/incident-reports/<report_id>/close-review", methods=["POST"])
def close_incident_review(report_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body([("findings_note", "string", True)])
    findings_note = V.check_str_len("findings_note", body["findings_note"], 1, 500)

    row = V.get_leaf(S.incident_reports, report_id)
    site = S.sites[row["site_id"]]
    auth.check_owner(role, user_id, client_id=site["client_id"])

    if row["review_status"] != "OPEN":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only an OPEN review may be closed.")

    row["findings_note"] = findings_note
    row["closed_at"] = now()
    row["review_status"] = "CLOSED"
    touch(row)

    contractor = S.contractors[row["contractor_id"]]
    flag_before = contractor["incident_review_flag"]
    derive.recompute_incident_counters(contractor)
    if row["severity"] in calc.SEVERE_SEVERITIES:
        derive.rematerialize_available_aggregate(contractor)
    touch(contractor)
    derive.recompute_site(site)

    if flag_before and not contractor["incident_review_flag"]:
        cascade.unfreeze_contractor(contractor)
    return response.ok(serialize.incident_report(row))
