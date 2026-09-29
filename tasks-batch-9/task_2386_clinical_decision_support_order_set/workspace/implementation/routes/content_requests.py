"""Content request intake, triage, resubmission and the two build endpoints
(PRD §3.1, §3.2, §3.3)."""
from flask import Blueprint, request

import const
import validate
from common import base_record, touch
from db import db
from errors import ApiError
from middleware import (authenticate, caller_id, check_freeze, get_alert, get_clinician,
                        get_content_request, get_order_set, get_release)
from response import created, ok, paginate
from services import calc
from services import domain

bp = Blueprint("content_requests", __name__)


def fk(data, field, getter):
    """Body foreign key existence check (PRD §2.7 step 5)."""
    value = data.get(field)
    if isinstance(value, str):
        return getter(value)
    return None


# ------------------------------------------------------------------ intake
@bp.post("/cds/content-requests")
def create_content_request():
    authenticate(("ClinicalSponsor", "CommitteeChair"))
    data = validate.body()

    sponsor = fk(data, "clinical_sponsor_id", get_clinician)

    title = validate.string(data, "title", required=True)
    request_type = validate.enum(data, "request_type", const.REQUEST_TYPES, required=True)
    clinical_domain = validate.enum(data, "clinical_domain", const.SPECIALTIES, required=True)
    urgency = validate.enum(data, "urgency", const.URGENCIES, required=True)
    evidence_grade = validate.enum(data, "evidence_grade", const.EVIDENCE_GRADES, required=True)
    sponsor_id = validate.string(data, "clinical_sponsor_id", required=True)
    citations = validate.citations(data, "evidence_citations")
    patient_safety_flag = validate.boolean(data, "patient_safety_flag", default=False)
    requested_go_live_at = validate.instant(data, "requested_go_live_at")

    if sponsor is None:
        sponsor = get_clinician(sponsor_id)
    if "ClinicalSponsor" not in (sponsor.get("authorized_roles") or []):
        raise ApiError("ERR_UNAUTHORIZED", "Named sponsor is not authorized as a ClinicalSponsor")
    if sponsor["employment_status"] != "ACTIVE":
        raise ApiError("ERR_CLINICIAN_NOT_ACTIVE", "Named sponsor is not ACTIVE")

    record = base_record()
    record.update({
        "title": title,
        "request_type": request_type,
        "clinical_sponsor_id": sponsor_id,
        "clinical_domain": clinical_domain,
        "urgency": urgency,
        "evidence_grade": evidence_grade,
        "evidence_citations": citations,
        "patient_safety_flag": patient_safety_flag,
        "requested_go_live_at": requested_go_live_at,
        "status": "INTAKE_SUBMITTED",
        "priority_score": calc.intake_provisional_score(evidence_grade, urgency, patient_safety_flag),
        "priority_score_basis": "INTAKE_PROVISIONAL",
        "peer_reviewed_citation_count": calc.peer_reviewed_count(citations),
        "triage_note": None,
        "return_count": 0,
    })
    db.content_requests[record["id"]] = record
    return created(record)


@bp.get("/cds/content-requests")
def list_content_requests():
    authenticate(const.ANY_ROLE)
    records = list(db.content_requests.values())

    sponsor_id = request.args.get("clinical_sponsor_id")
    status = request.args.get("status")
    urgency = request.args.get("urgency")
    request_type = request.args.get("request_type")
    clinical_domain = request.args.get("clinical_domain")
    safety = validate.query_bool("patient_safety_flag")

    if sponsor_id:
        records = [r for r in records if r["clinical_sponsor_id"] == sponsor_id]
    if status:
        records = [r for r in records if r["status"] == status]
    if urgency:
        records = [r for r in records if r["urgency"] == urgency]
    if request_type:
        records = [r for r in records if r["request_type"] == request_type]
    if clinical_domain:
        records = [r for r in records if r["clinical_domain"] == clinical_domain]
    if safety is not None:
        records = [r for r in records if r["patient_safety_flag"] is safety]

    # PRD §2.3: priority_score descending, created_at ascending as the tie-break.
    return paginate(records, sort_key=lambda r: (-r["priority_score"], r["created_at"], r.get("_seq", 0)))


@bp.get("/cds/content-requests/<cid>")
def read_content_request(cid):
    authenticate(const.ANY_ROLE)
    return ok(get_content_request(cid))


# ------------------------------------------------------------------ triage
@bp.post("/cds/content-requests/<cid>/triage")
def triage(cid):
    authenticate(("CommitteeChair",))
    record = get_content_request(cid)
    data = validate.body()
    decision = validate.enum(data, "decision", const.TRIAGE_DECISIONS, required=True)
    triage_note = validate.string(data, "triage_note")

    if record["status"] != "INTAKE_SUBMITTED":
        raise ApiError("ERR_CONTENT_REQUEST_NOT_TRIAGEABLE", "Request is not in INTAKE_SUBMITTED")

    if decision == "ACCEPT":
        if not calc.evidence_clears_acceptance_bar(
            record["evidence_citations"], record["patient_safety_flag"], record["urgency"]
        ):
            raise ApiError("ERR_EVIDENCE_INSUFFICIENT", "Evidence does not clear the acceptance bar")
        record["status"] = "TRIAGE_ACCEPTED"
        record["priority_score"] = calc.committee_calibrated_score(
            record["peer_reviewed_citation_count"], record["urgency"],
            record["patient_safety_flag"], record["created_at"], db.clock,
        )
        record["priority_score_basis"] = "COMMITTEE_CALIBRATED"
    elif decision == "RETURN":
        record["status"] = "RETURNED_TO_SPONSOR"
        record["return_count"] += 1
    else:
        record["status"] = "DECLINED"

    record["triage_note"] = triage_note
    touch(record)
    return ok(record)


@bp.post("/cds/content-requests/<cid>/resubmit")
def resubmit(cid):
    authenticate(("ClinicalSponsor",))
    record = get_content_request(cid)
    if record["clinical_sponsor_id"] != caller_id():
        raise ApiError("ERR_ROLE_IDENTITY_MISMATCH", "Only the named sponsor may resubmit")

    data = validate.body()
    citations = validate.citations(data, "evidence_citations")
    evidence_grade = validate.enum(
        data, "evidence_grade", const.EVIDENCE_GRADES, default=record["evidence_grade"]
    )
    urgency = validate.enum(data, "urgency", const.URGENCIES, default=record["urgency"])

    if record["status"] != "RETURNED_TO_SPONSOR":
        raise ApiError("ERR_CONTENT_REQUEST_NOT_RETURNED", "Request is not RETURNED_TO_SPONSOR")

    record["evidence_citations"] = citations
    record["evidence_grade"] = evidence_grade
    record["urgency"] = urgency
    record["peer_reviewed_citation_count"] = calc.peer_reviewed_count(citations)
    record["priority_score"] = calc.intake_provisional_score(
        evidence_grade, urgency, record["patient_safety_flag"]
    )
    record["priority_score_basis"] = "INTAKE_PROVISIONAL"
    record["status"] = "INTAKE_SUBMITTED"
    touch(record)
    return ok(record)


# ------------------------------------------------------------------ builds
def _check_build_gate(record):
    if record["status"] not in ("TRIAGE_ACCEPTED", "BUILD_IN_PROGRESS"):
        raise ApiError("ERR_CONTENT_REQUEST_NOT_ACCEPTED", "Request has not been accepted for build")


@bp.post("/cds/content-requests/<cid>/order-sets")
def create_order_set(cid):
    authenticate(("InformaticsBuilder",))
    record = get_content_request(cid)
    data = validate.body()

    # body foreign keys, in declared input order
    fk(data, "pinned_vendor_release_id", get_release)
    fk(data, "built_by_clinician_id", get_clinician)
    predecessor = fk(data, "supersedes_order_set_id", get_order_set)

    expected_version = validate.integer(data, "expected_content_request_version", required=True)
    name = validate.string(data, "name", required=True)
    specialty = validate.enum(data, "specialty", const.SPECIALTIES, required=True)
    release_id = validate.string(data, "pinned_vendor_release_id", required=True)
    builder_id = validate.string(data, "built_by_clinician_id", required=True)
    supersedes_id = validate.string(data, "supersedes_order_set_id")

    if expected_version != record["version"]:
        raise ApiError("ERR_STALE_CONTENT_REQUEST_VERSION", "Content request version is stale")

    _check_build_gate(record)
    check_freeze("order_set")

    if builder_id != caller_id():
        raise ApiError(
            "ERR_ROLE_IDENTITY_MISMATCH", "built_by_clinician_id must equal the calling builder"
        )

    order_set = base_record()
    order_set.update({
        "content_request_id": record["id"],
        "name": name,
        "specialty": specialty,
        "built_by_clinician_id": builder_id,
        "pinned_vendor_release_id": release_id,
        "supersedes_order_set_id": supersedes_id,
        "review_state": "DRAFT",
        "publication_state": "UNPUBLISHED",
        "risk_class": "HIGH" if record["patient_safety_flag"] else "STANDARD",
        "item_count": 0,
        "high_alert_item_count": 0,
        "peer_required_votes": None,
        "peer_cast_count": 0,
        "peer_approve_ratio": None,
        "specialty_required_votes": None,
        "specialty_cast_count": 0,
        "specialty_approve_ratio": None,
        "revision_round": 0,
        "votes_cast_count": 0,
        "votes_voided_count": 0,
        "pharmacy_signoff_at": None,
        "pharmacy_signoff_by_clinician_id": None,
        "go_live_at": None,
        "review_due_date": None,
        "expiration_at": None,
        "archive_eligible_at": None,
        "pinned_content_stale": False,
        "latest_adherence_pct": None,
        "archived_at": None,
    })
    db.order_sets[order_set["id"]] = order_set

    domain.advance_request_to_build(record)

    if predecessor is not None and predecessor["publication_state"] == "UNPUBLISHED":
        domain.supersede_unpublished_predecessor(predecessor)

    return created(order_set)


@bp.post("/cds/content-requests/<cid>/alerts")
def create_alert(cid):
    authenticate(("InformaticsBuilder",))
    record = get_content_request(cid)
    data = validate.body()

    fk(data, "designed_by_clinician_id", get_clinician)
    fk(data, "linked_order_set_id", get_order_set)

    name = validate.string(data, "name", required=True)
    criteria = validate.obj(data, "firing_criteria", required=True)
    if not isinstance(criteria.get("trigger_event"), str):
        raise ApiError("ERR_INVALID_REQUEST", "firing_criteria.trigger_event is required")
    if not isinstance(criteria.get("expression"), str):
        raise ApiError("ERR_INVALID_REQUEST", "firing_criteria.expression is required")
    designer_id = validate.string(data, "designed_by_clinician_id", required=True)
    severity_tier = validate.enum(data, "severity_tier", const.SEVERITY_TIERS, required=True)
    reason_codes = validate.array(data, "override_reason_codes", default=[])
    for code in reason_codes:
        if not isinstance(code, str):
            raise ApiError("ERR_INVALID_REQUEST", "override_reason_codes must be strings")
    reason_required = validate.boolean(data, "override_reason_required", default=True)
    justification = validate.string(data, "hard_stop_justification")
    linked_id = validate.string(data, "linked_order_set_id")

    _check_build_gate(record)
    check_freeze("alert")

    if severity_tier in ("TIER_1_HARD_STOP", "TIER_2_INTERRUPTIVE"):
        reason_required = True

    alert = base_record()
    alert.update({
        "content_request_id": record["id"],
        "name": name,
        "designed_by_clinician_id": designer_id,
        "linked_order_set_id": linked_id,
        "firing_criteria": criteria,
        "severity_tier": severity_tier,
        "override_reason_required": reason_required,
        "override_reason_codes": list(reason_codes),
        "hard_stop_justification": justification,
        "review_state": "DRAFT",
        "lifecycle_state": "UNPUBLISHED",
        "required_approval_votes": None,
        "approval_cast_count": 0,
        "lifetime_fire_count": 0,
        "windowed_fire_count": 0,
        "unwindowed_fire_count": 0,
        "lifetime_override_count": 0,
        "latest_burden_index": None,
        "latest_burden_classification": None,
        "suspension_count": 0,
        "suspension_reason": None,
        "restage_count": 0,
        "review_due_date": None,
        "expiration_at": None,
        "retired_at": None,
    })
    db.alerts[alert["id"]] = alert

    domain.advance_request_to_build(record)
    return created(alert)
