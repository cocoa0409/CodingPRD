"""Vendor content release review cycles, rule deltas and the activation cascades (PRD §3.6)."""
from flask import Blueprint, request

import const
import validate
from common import add_days, base_record, now, touch
from db import db
from errors import ApiError
from middleware import (authenticate, caller_role, check_freeze, check_read_freeze,
                        get_delta, get_release)
from response import created, ok, paginate
from services import calc, domain

bp = Blueprint("vendor", __name__)


# ------------------------------------------------------------------ releases
@bp.post("/cds/vendor-releases")
def create_release():
    authenticate(("PharmacyInformaticist", const.SYSTEM_ADMIN))
    data = validate.body()

    if isinstance(data.get("supersedes_release_id"), str):
        get_release(data["supersedes_release_id"])

    vendor_name = validate.string(data, "vendor_name", required=True)
    release_label = validate.string(data, "release_label", required=True)
    content_domain = validate.enum(data, "content_domain", const.CONTENT_DOMAINS, required=True)
    received_at = validate.instant(data, "received_at", default=None)
    effective_at = validate.instant(data, "effective_at")
    supersedes_id = validate.string(data, "supersedes_release_id")

    for existing in db.vendor_releases.values():
        if existing["vendor_name"] == vendor_name and existing["release_label"] == release_label:
            raise ApiError("ERR_INVALID_REQUEST", "release_label must be unique within the vendor")

    check_freeze("vendor")

    release = base_record()
    release.update({
        "vendor_name": vendor_name,
        "release_label": release_label,
        "content_domain": content_domain,
        "received_at": received_at if received_at is not None else now(),
        "effective_at": effective_at,
        "supersedes_release_id": supersedes_id,
        "review_cycle_state": "RECEIVED",
        "impact_score": None,
        "delta_count": 0,
        "contraindicated_delta_count": 0,
        "dispositioned_delta_count": 0,
        "restaged_order_set_count": 0,
        "activated_at": None,
    })
    db.vendor_releases[release["id"]] = release
    return created(release)


@bp.get("/cds/vendor-releases")
def list_releases():
    authenticate(const.ANY_ROLE)
    check_read_freeze("vendor")
    records = list(db.vendor_releases.values())
    for field in ("supersedes_release_id", "review_cycle_state", "vendor_name", "content_domain"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return paginate(records)


@bp.get("/cds/vendor-releases/<cid>")
def read_release(cid):
    authenticate(const.ANY_ROLE)
    release = get_release(cid)
    check_read_freeze("vendor")
    return ok(release)


# ------------------------------------------------------------------ deltas
@bp.post("/cds/vendor-releases/<cid>/deltas")
def create_delta(cid):
    authenticate(("PharmacyInformaticist", const.SYSTEM_ADMIN))
    release = get_release(cid)
    data = validate.body()

    rule_code = validate.string(data, "rule_code", required=True)
    change_type = validate.enum(data, "change_type", const.CHANGE_TYPES, required=True)
    description = validate.string(data, "description", required=True)
    drug_pair = validate.string(data, "drug_pair")
    prior_severity = validate.enum(data, "prior_severity", const.SEVERITIES)
    new_severity = validate.enum(data, "new_severity", const.SEVERITIES)

    for existing in domain.deltas_of_release(release["id"]):
        if existing["rule_code"] == rule_code:
            raise ApiError("ERR_INVALID_REQUEST", "rule_code must be unique within the release")

    if release["review_cycle_state"] != "RECEIVED":
        raise ApiError("ERR_VENDOR_RELEASE_NOT_RECEIVED", "Release is no longer in RECEIVED")

    check_freeze("vendor")

    delta = base_record()
    delta.update({
        "vendor_release_id": release["id"],
        "rule_code": rule_code,
        "change_type": change_type,
        "description": description,
        "drug_pair": drug_pair,
        "prior_severity": prior_severity,
        "new_severity": new_severity,
        "weight": calc.delta_weight(change_type, new_severity),
        "disposition": None,
        "suppression_justification": None,
        "dispositioned_at": None,
    })
    db.vendor_deltas[delta["id"]] = delta

    release["delta_count"] += 1
    if new_severity == "CONTRAINDICATED":
        release["contraindicated_delta_count"] += 1
    touch(release)

    return created(delta)


@bp.get("/cds/vendor-releases/<cid>/deltas")
def list_deltas(cid):
    authenticate(const.ANY_ROLE)
    release = get_release(cid)
    check_read_freeze("vendor")
    records = domain.deltas_of_release(release["id"])
    for field in ("change_type", "disposition", "new_severity"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return paginate(records)


@bp.post("/cds/vendor-rule-deltas/<cid>/disposition")
def disposition_delta(cid):
    authenticate(("PharmacyInformaticist", "CommitteeChair"))
    delta = get_delta(cid)
    data = validate.body()
    disposition = validate.enum(data, "disposition", const.DISPOSITIONS, required=True)
    justification = validate.string(data, "suppression_justification")

    release = db.vendor_releases.get(delta["vendor_release_id"])
    if release is None or release["review_cycle_state"] not in (
        "IMPACT_ANALYZED_FAST_TRACK", "IMPACT_ANALYZED_CLINICAL_REVIEW"
    ):
        raise ApiError("ERR_VENDOR_RELEASE_NOT_ANALYZED", "Release has not been impact analysed")

    check_freeze("vendor")

    if disposition == "SUPPRESS" and not (justification or "").strip():
        raise ApiError(
            "ERR_SUPPRESSION_JUSTIFICATION_REQUIRED",
            "A SUPPRESS disposition requires a suppression_justification",
        )

    first_disposition = delta["disposition"] is None
    delta["disposition"] = disposition
    delta["suppression_justification"] = justification
    delta["dispositioned_at"] = now()
    touch(delta)

    if first_disposition:
        release["dispositioned_delta_count"] += 1
        touch(release)

    return ok(delta)


# ------------------------------------------------------------------ impact analysis
@bp.post("/cds/vendor-releases/<cid>/run-impact-analysis")
def run_impact_analysis(cid):
    authenticate(("PharmacyInformaticist",))
    release = get_release(cid)
    data = validate.body()
    validate.string(data, "analysis_note")

    deltas = domain.deltas_of_release(release["id"])
    if release["review_cycle_state"] != "RECEIVED" or len(deltas) < 1:
        raise ApiError(
            "ERR_VENDOR_RELEASE_NOT_RECEIVED",
            "Impact analysis requires a RECEIVED release carrying at least one delta",
        )

    check_freeze("vendor")

    impact_score = sum(d["weight"] for d in deltas)
    release["impact_score"] = impact_score
    release["review_cycle_state"] = calc.impact_branch(impact_score)
    touch(release)
    return ok(release)


# ------------------------------------------------------------------ activation
def _mark_predecessor_superseded(release):
    predecessor_id = release.get("supersedes_release_id")
    if not predecessor_id:
        return None
    predecessor = db.vendor_releases.get(predecessor_id)
    if predecessor is None or predecessor["review_cycle_state"] == "SUPERSEDED":
        return predecessor
    predecessor["review_cycle_state"] = "SUPERSEDED"
    touch(predecessor)
    return predecessor


@bp.post("/cds/vendor-releases/<cid>/activate")
def activate_release(cid):
    authenticate(("PharmacyInformaticist", "CommitteeChair"))
    release = get_release(cid)
    data = validate.body()
    validate.string(data, "activation_note")

    state = release["review_cycle_state"]
    if state not in ("IMPACT_ANALYZED_FAST_TRACK", "IMPACT_ANALYZED_CLINICAL_REVIEW"):
        raise ApiError("ERR_VENDOR_RELEASE_NOT_ANALYZED", "Release has not been impact analysed")

    clinical = state == "IMPACT_ANALYZED_CLINICAL_REVIEW"
    if clinical and caller_role() != "CommitteeChair":
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Only a CommitteeChair may activate a clinical-review release",
        )

    check_freeze("vendor")

    deltas = domain.deltas_of_release(release["id"])
    if release["dispositioned_delta_count"] != release["delta_count"]:
        raise ApiError("ERR_DELTA_DISPOSITION_INCOMPLETE", "Every delta must be dispositioned first")

    if clinical:
        for delta in sorted(deltas, key=lambda d: d.get("_seq", 0)):
            if delta["disposition"] == "SUPPRESS" and not (delta["suppression_justification"] or "").strip():
                raise ApiError(
                    "ERR_SUPPRESSION_JUSTIFICATION_REQUIRED",
                    "Every SUPPRESS disposition needs a suppression_justification",
                )

    if release["effective_at"] is not None and now() < release["effective_at"]:
        raise ApiError(
            "ERR_VENDOR_RELEASE_NOT_ANALYZED", "The release's effective_at has not been reached"
        )

    release["review_cycle_state"] = "ACTIVATED"
    release["activated_at"] = now()
    predecessor = _mark_predecessor_superseded(release)
    touch(release)

    if clinical and predecessor is not None:
        restaged = 0
        affected = [
            o for o in db.order_sets.values()
            if o["pinned_vendor_release_id"] == predecessor["id"]
            and o["publication_state"] == "PUBLISHED"
        ]
        affected.sort(key=lambda o: o.get("_seq", 0))
        for order_set in affected:
            order_set["pinned_content_stale"] = True
            restaged += 1

            due = add_days(now(), const.STALE_CONTENT_REVIEW_DAYS)
            expiration = add_days(due, const.GRACE_PERIOD_DAYS)
            archive = add_days(expiration, const.ARCHIVE_AFTER_EXPIRY_DAYS)
            task = domain.governing_task("ORDER_SET", order_set["id"])
            if task is not None:
                task["review_due_date"] = due
                task["expiration_at"] = expiration
                task["archive_eligible_at"] = archive
                task["stale_content_triggered"] = True
                touch(task)
                domain.apply_schedule_to_order_set(order_set, due, expiration, archive)
            touch(order_set)
        release["restaged_order_set_count"] = restaged
        touch(release)

    return ok(release)
