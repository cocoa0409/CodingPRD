from flask import Blueprint, request

import db
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_object, success_rows
from services.core import all_entities, touch
from services.derived import (
    CRITICAL_DAYS,
    WARNING_DAYS,
    append_evaluation,
    derive_privilege,
    invalidate_items_for,
    recompute_posture,
)
from util import iso_z, parse_date_loose

bp = Blueprint("ops", __name__)

CLOCK_SCHEMA = {
    "to_iso8601": ("datetime", True, None),
}


@bp.route("/credentialing/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = auth_context()
    require_role(role, {"SystemOperator"})
    body = validate_body(get_body(allow_empty=False), CLOCK_SCHEMA)
    db.set_logical_now(body["to_iso8601"])
    return success_object({"current_utc": iso_z(db.logical_now())})


@bp.route("/credentialing/monitoring/expiry-report", methods=["GET"])
def expiry_report():
    auth_context()
    limit, offset = pagination_params()
    nurse_filter = request.args.get("nurse_id")
    today = db.current_date()
    rows = []
    for lic in all_entities("licenses"):
        if lic["status"] not in ("VERIFIED", "ACTIVE", "ENCUMBERED", "EXPIRED"):
            continue
        if nurse_filter is not None and lic["nurse_id"] != nurse_filter:
            continue
        rows.append(("LICENSE", lic["id"], lic["nurse_id"], lic["expires_on"], lic["created_at"], lic["_seq"]))
    for cert in all_entities("certifications"):
        if cert["status"] not in ("ACTIVE", "EXPIRED"):
            continue
        if nurse_filter is not None and cert["nurse_id"] != nurse_filter:
            continue
        rows.append(("CERTIFICATION", cert["id"], cert["nurse_id"], cert["expires_on"], cert["created_at"], cert["_seq"]))
    for completion in all_entities("completions"):
        if completion["status"] not in ("CURRENT", "LAPSED"):
            continue
        if nurse_filter is not None and completion["nurse_id"] != nurse_filter:
            continue
        rows.append(("COMPLETION", completion["id"], completion["nurse_id"], completion["expires_on"], completion["created_at"], completion["_seq"]))

    def bucket(days):
        if days < 0:
            return "EXPIRED"
        if days <= CRITICAL_DAYS:
            return "CRITICAL"
        if days <= WARNING_DAYS:
            return "WARNING"
        return "OK"

    enriched = []
    for kind, cred_id, nurse_id, expires_on, created_at, seq in rows:
        days_to_expiry = (parse_date_loose(expires_on) - today).days
        enriched.append({
            "credential_kind": kind,
            "credential_id": cred_id,
            "nurse_id": nurse_id,
            "expires_on": expires_on,
            "days_to_expiry": days_to_expiry,
            "bucket": bucket(days_to_expiry),
            "created_at": created_at,
            "_seq": seq,
        })
    # Sort: days_to_expiry ASC, tie-break created_at ASC (insertion sequence on ties).
    enriched.sort(key=lambda r: (r["days_to_expiry"], r["created_at"], r["_seq"]))
    for row in enriched:
        row.pop("_seq", None)
    total = len(enriched)
    page = enriched[offset:offset + limit]
    return success_rows(page, limit, offset, total)


@bp.route("/credentialing/_ops/expiry-sweep", methods=["POST"])
def expiry_sweep():
    user_id, role = auth_context()
    require_role(role, {"SystemOperator"})
    today = db.current_date()
    licenses_expired = 0
    certifications_expired = 0
    completions_lapsed = 0
    shifts_auto_cancelled = 0
    packets_voided = 0
    privilege_evaluations_appended = 0
    affected_nurse_ids = []

    def mark_affected(nurse_id):
        if nurse_id not in affected_nurse_ids:
            affected_nurse_ids.append(nurse_id)

    # 1. Licenses ACTIVE/ENCUMBERED past expiry -> EXPIRED (+ item invalidation).
    for lic in all_entities("licenses"):
        if lic["status"] in ("ACTIVE", "ENCUMBERED") and parse_date_loose(lic["expires_on"]) < today:
            lic["status"] = "EXPIRED"
            touch(lic)
            licenses_expired += 1
            mark_affected(lic["nurse_id"])
            packets_voided += invalidate_items_for(lic["id"])
    # 2. Certifications ACTIVE past expiry -> EXPIRED (+ invalidation cascade).
    for cert in all_entities("certifications"):
        if cert["status"] == "ACTIVE" and parse_date_loose(cert["expires_on"]) < today:
            cert["status"] = "EXPIRED"
            touch(cert)
            certifications_expired += 1
            mark_affected(cert["nurse_id"])
            packets_voided += invalidate_items_for(cert["id"])
    # 3. Completions CURRENT past expiry -> LAPSED (+ invalidation cascade).
    for completion in all_entities("completions"):
        if completion["status"] == "CURRENT" and parse_date_loose(completion["expires_on"]) < today:
            completion["status"] = "LAPSED"
            touch(completion)
            completions_lapsed += 1
            mark_affected(completion["nurse_id"])
            packets_voided += invalidate_items_for(completion["id"])

    pre_posture = {
        nid: db.STORES["nurses"][nid]["credential_posture"]
        for nid in affected_nurse_ids if nid in db.STORES["nurses"]
    }

    # 4. Posture recompute for every affected nurse (+ posture cascade).
    affected_nurse_ids.sort(key=lambda nid: db.STORES["nurses"][nid]["_seq"] if nid in db.STORES["nurses"] else 0)
    flipped_away_from_clear = set()
    for nid in affected_nurse_ids:
        nurse = db.STORES["nurses"].get(nid)
        if nurse is None:
            continue
        changed, cancelled, voided = recompute_posture(nurse)
        if changed and nurse["credential_posture"] != "CLEAR":
            flipped_away_from_clear.add(nid)
        shifts_auto_cancelled += cancelled
        packets_voided += voided

    # 5. Privilege re-derivation (SWEEP rows when changed); embedded derivations
    #    recompute posture in all cases — except that a single trigger cannot
    #    oscillate (§3.5): a nurse whose step-4 flip fired the cascade keeps her
    #    suspended posture; only a later recompute after remediation may clear her.
    for nid in affected_nurse_ids:
        nurse = db.STORES["nurses"].get(nid)
        if nurse is None:
            continue
        changed, status, scope, home_id = derive_privilege(nurse, reason=None)
        if changed:
            append_evaluation(nurse, "SWEEP", status, scope, home_id)
            privilege_evaluations_appended += 1
            touch(nurse)
        if nid in flipped_away_from_clear:
            continue
        _, cancelled, voided = recompute_posture(nurse)
        shifts_auto_cancelled += cancelled
        packets_voided += voided

    postures_changed = sum(
        1 for nid, before in pre_posture.items()
        if nid in db.STORES["nurses"] and db.STORES["nurses"][nid]["credential_posture"] != before
    )

    return success_object({
        "licenses_expired": licenses_expired,
        "certifications_expired": certifications_expired,
        "completions_lapsed": completions_lapsed,
        "postures_changed": postures_changed,
        "shifts_auto_cancelled": shifts_auto_cancelled,
        "packets_voided": packets_voided,
        "privilege_evaluations_appended": privilege_evaluations_appended,
    })
