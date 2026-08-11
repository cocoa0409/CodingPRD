"""The reading queue, the reporting chain, equipment QC and peer review
(PRD 3.6, 3.7)."""

from flask import Blueprint, g

from core import clock, db, gates
from core.auth import READ_ROLES, authenticate, authorize, require_owner
from core.constants import (
    ADDENDUM_WINDOW_DAYS,
    PEER_REVIEW_DISCORDANT_SCORE_MAX,
    PEER_REVIEW_SCORE_MAX,
    PEER_REVIEW_SCORE_MIN,
    QC_CHECK_RESULT_ENUM,
    READ_ATTEMPT_CAP,
    REPORT_KIND_ENUM,
    SPECIALIST_MAX_OPEN_READS,
)
from core.errors import ApiError
from core.validate import body, enum_value, opt_str, req_id, req_int, req_str
from routes.common import apply_filters, fk, listing, need, one
from services import cascades, derive, notify, tat

bp = Blueprint("reading", __name__)


# ==========================================================================
# ReadAssignment
# ==========================================================================

@bp.post("/read-assignments")
def create_read_assignment():
    authenticate()
    authorize("Scheduler")
    data = body()
    study = fk(data, "study_id", "studies", "ERR_STUDY_NOT_FOUND")
    specialist = fk(data, "specialist_id", "specialists", "ERR_SPECIALIST_NOT_FOUND")
    req_id(data, "study_id")
    req_id(data, "specialist_id")
    expected = req_int(data, "expected_study_version")
    # rung 7
    if expected != study["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # rungs 29-32 — the four matching axes, in their fixed order
    if specialist["status"] != "ACTIVE":
        raise ApiError("ERR_SPECIALIST_INACTIVE")
    if study["modality"] not in specialist["modality_privileges"]:
        raise ApiError("ERR_SPECIALIST_MODALITY_NOT_PRIVILEGED")
    if study["species"] not in specialist["species_privileges"]:
        raise ApiError("ERR_SPECIALIST_SPECIES_NOT_PRIVILEGED")
    if study["priority"] == "STAT" and not specialist["stat_eligible"]:
        raise ApiError("ERR_SPECIALIST_NOT_STAT_ELIGIBLE")
    # rung 33
    if study["read_attempt_count"] >= READ_ATTEMPT_CAP:
        raise ApiError("ERR_READ_ATTEMPT_CAP_EXCEEDED")
    # rung 34
    if derive.specialist_open_read_count(specialist) >= SPECIALIST_MAX_OPEN_READS:
        raise ApiError("ERR_SPECIALIST_READ_CAPACITY")
    # rung 35
    if study["workflow_status"] != "ACQUIRED" or study["qc_status"] != "ACCEPTED":
        raise ApiError("ERR_STUDY_NOT_READ_READY")

    study["read_attempt_count"] += 1
    study["workflow_status"] = "ASSIGNED"
    db.touch(study)

    rec = db.new_record()
    rec.update(
        {
            "study_id": study["id"],
            "specialist_id": specialist["id"],
            "attempt_number": study["read_attempt_count"],
            "status": "OFFERED",
            "offered_at": clock.now(),
            "responded_at": None,
            "decline_reason": None,
        }
    )
    db.insert("read_assignments", rec)
    return one("read_assignments", rec, 201)


@bp.get("/read-assignments/<assignment_id>")
def get_read_assignment(assignment_id):
    authenticate()
    authorize(*READ_ROLES)
    return one(
        "read_assignments",
        need("read_assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND"),
    )


@bp.get("/read-assignments")
def list_read_assignments():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("read_assignments")
    rows = apply_filters(
        rows, {"study_id": "study_id", "specialist_id": "specialist_id", "status": "status"}
    )
    return listing("read_assignments", rows)


@bp.post("/read-assignments/<assignment_id>/accept")
def accept_read(assignment_id):
    authenticate()
    authorize("Specialist")
    assignment = need("read_assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    require_owner(g.user_id == assignment["specialist_id"])
    if assignment["status"] != "OFFERED":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")
    assignment["status"] = "ACCEPTED"
    assignment["responded_at"] = clock.now()
    db.touch(assignment)
    study = db.get("studies", assignment["study_id"])
    if study is not None and study["workflow_status"] == "ASSIGNED":
        study["workflow_status"] = "READ_IN_PROGRESS"
        db.touch(study)
        tat.evaluate(study)
    return one("read_assignments", assignment)


@bp.post("/read-assignments/<assignment_id>/decline")
def decline_read(assignment_id):
    authenticate()
    authorize("Specialist")
    assignment = need("read_assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    require_owner(g.user_id == assignment["specialist_id"])
    data = body()
    reason = req_str(data, "decline_reason")
    if assignment["status"] != "OFFERED":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")
    assignment["status"] = "DECLINED"
    assignment["responded_at"] = clock.now()
    assignment["decline_reason"] = reason
    db.touch(assignment)
    study = db.get("studies", assignment["study_id"])
    # read_attempt_count is NOT given back — the attempt is consumed.
    if study is not None and study["workflow_status"] == "ASSIGNED":
        study["workflow_status"] = "ACQUIRED"
        db.touch(study)
        tat.evaluate(study)
    return one("read_assignments", assignment)


@bp.post("/read-assignments/<assignment_id>/hand-back")
def hand_back_read(assignment_id):
    authenticate()
    authorize("Specialist")
    assignment = need("read_assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    require_owner(g.user_id == assignment["specialist_id"])
    data = body()
    reason = req_str(data, "decline_reason")
    if assignment["status"] != "ACCEPTED":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")
    published = [
        r
        for r in db.where("reports", study_id=assignment["study_id"])
        if r["status"] == "PUBLISHED" and r["author_specialist_id"] == g.user_id
    ]
    if published:
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")
    assignment["status"] = "HANDED_BACK"
    assignment["responded_at"] = clock.now()
    assignment["decline_reason"] = reason
    db.touch(assignment)
    study = db.get("studies", assignment["study_id"])
    if study is not None and study["workflow_status"] == "READ_IN_PROGRESS":
        study["workflow_status"] = "ACQUIRED"
        db.touch(study)
        tat.evaluate(study)
    return one("read_assignments", assignment)


# ==========================================================================
# Report
# ==========================================================================

@bp.post("/reports")
def create_report():
    authenticate()
    authorize("Specialist")
    data = body()
    study = fk(data, "study_id", "studies", "ERR_STUDY_NOT_FOUND")
    req_id(data, "study_id")
    kind = req_str(data, "kind")
    findings = req_str(data, "findings")
    enum_value(kind, REPORT_KIND_ENUM, "kind")
    # rung 36 — authoring entitlement
    holds_accepted = any(
        a["status"] == "ACCEPTED" and a["specialist_id"] == g.user_id
        for a in db.where("read_assignments", study_id=study["id"])
    )
    authored_before = any(
        r["author_specialist_id"] == g.user_id
        and r["status"] in ("PUBLISHED", "SUPERSEDED", "RETRACTED")
        for r in db.where("reports", study_id=study["id"])
    )
    if not (holds_accepted or authored_before):
        raise ApiError("ERR_NOT_ASSIGNED_SPECIALIST")

    version_no = 1 + len(db.where("reports", study_id=study["id"]))
    rec = db.new_record()
    rec.update(
        {
            "study_id": study["id"],
            "author_specialist_id": g.user_id,
            "supersedes_report_id": None,
            "kind": kind,
            "report_version": version_no,
            "status": "DRAFT",
            "findings": findings,
            "published_at": None,
            "retracted_at": None,
            "retract_reason": None,
        }
    )
    db.insert("reports", rec)
    return one("reports", rec, 201)


@bp.get("/reports/<report_id>")
def get_report(report_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("reports", need("reports", report_id, "ERR_REPORT_NOT_FOUND"))


@bp.get("/reports")
def list_reports():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("reports")
    rows = apply_filters(
        rows,
        {
            "study_id": "study_id",
            "author_specialist_id": "author_specialist_id",
            "supersedes_report_id": "supersedes_report_id",
            "kind": "kind",
            "status": "status",
        },
    )
    return listing("reports", rows)


def _latest_final(study_id):
    finals = [
        r
        for r in db.sort_rows(db.where("reports", study_id=study_id))
        if r["kind"] == "FINAL" and r["status"] in ("PUBLISHED", "SUPERSEDED")
    ]
    if not finals:
        return None
    return finals[-1]


@bp.post("/reports/<report_id>/publish")
def publish_report(report_id):
    authenticate()
    authorize("Specialist")
    report = need("reports", report_id, "ERR_REPORT_NOT_FOUND")
    require_owner(g.user_id == report["author_specialist_id"])
    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    study = db.get("studies", report["study_id"])
    # rung 37 — the report sequence rule
    if report["kind"] == "PRELIMINARY":
        if study["workflow_status"] != "READ_IN_PROGRESS":
            raise ApiError("ERR_REPORT_SEQUENCE_INVALID")
    elif report["kind"] == "FINAL":
        if study["workflow_status"] not in ("READ_IN_PROGRESS", "PRELIM_REPORTED"):
            raise ApiError("ERR_REPORT_SEQUENCE_INVALID")
    else:  # ADDENDUM
        final = _latest_final(study["id"])
        if final is None:
            raise ApiError("ERR_REPORT_SEQUENCE_INVALID")
        # rung 38 — strictly before published_at + 14 days
        if clock.now() >= clock.plus_days(final["published_at"], ADDENDUM_WINDOW_DAYS):
            raise ApiError("ERR_ADDENDUM_WINDOW_CLOSED")

    predecessor = None
    for r in db.sort_rows(db.where("reports", study_id=study["id"])):
        if r["status"] == "PUBLISHED":
            predecessor = r
    report["status"] = "PUBLISHED"
    report["published_at"] = clock.now()
    report["supersedes_report_id"] = predecessor["id"] if predecessor else None
    db.touch(report)
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        db.touch(predecessor)

    if report["kind"] == "PRELIMINARY":
        study["workflow_status"] = "PRELIM_REPORTED"
        db.touch(study)
    elif report["kind"] == "FINAL":
        study["workflow_status"] = "FINALIZED"
        db.touch(study)
        for a in db.sort_rows(db.where("read_assignments", study_id=study["id"])):
            if a["status"] == "ACCEPTED":
                a["status"] = "COMPLETED"
                a["responded_at"] = clock.now()
                db.touch(a)
        tat.settle_on_final(study)

    notify.append(
        derive.clinic_id_of_study(study),
        study["id"],
        "REPORT_PUBLISHED",
        "Report %s published on study %s." % (report["id"], study["id"]),
    )
    tat.evaluate(study)
    return one("reports", report)


@bp.post("/reports/<report_id>/retract")
def retract_report(report_id):
    authenticate()
    authorize("Specialist", "PlatformAdmin")
    report = need("reports", report_id, "ERR_REPORT_NOT_FOUND")
    if g.role == "Specialist":
        require_owner(g.user_id == report["author_specialist_id"])
    data = body()
    reason = req_str(data, "retract_reason")
    if report["status"] != "PUBLISHED":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    study = db.get("studies", report["study_id"])
    was_final = report["kind"] == "FINAL"
    report["status"] = "RETRACTED"
    report["retracted_at"] = clock.now()
    report["retract_reason"] = reason
    db.touch(report)
    if was_final and study is not None and study["workflow_status"] == "FINALIZED":
        has_prelim = any(
            r["kind"] == "PRELIMINARY" and r["status"] in ("PUBLISHED", "SUPERSEDED")
            for r in db.where("reports", study_id=study["id"])
        )
        study["workflow_status"] = "PRELIM_REPORTED" if has_prelim else "READ_IN_PROGRESS"
        db.touch(study)
    return one("reports", report)


# ==========================================================================
# QcCheck (equipment quality control)
# ==========================================================================

@bp.post("/qc-checks")
def create_qc_check():
    authenticate()
    authorize("FieldTech")
    data = body()
    # rung 3 — the acting identity must be the technician named in the body.
    raw_tech = data.get("performed_by_technician_id")
    if isinstance(raw_tech, str) and raw_tech:
        require_owner(raw_tech == g.user_id)
    # rung 4
    equipment = fk(data, "equipment_id", "equipment", "ERR_EQUIPMENT_NOT_FOUND")
    technician = fk(
        data, "performed_by_technician_id", "technicians", "ERR_RECORD_NOT_FOUND"
    )
    # rung 5
    req_id(data, "equipment_id")
    req_id(data, "performed_by_technician_id")
    result = req_str(data, "result")
    note = opt_str(data, "note")
    # rung 6
    enum_value(result, QC_CHECK_RESULT_ENUM, "result")

    affected = []
    if result == "FAIL":
        affected = cascades.blast_radius(equipment)
        # rung 8 (G1) — a closed book beats a safety recall, absolutely.
        gates.g1_no_frozen_lines([s["id"] for s in affected])
    # rung 23 — status limb, then the certification limb against the EQUIPMENT's
    # modality (never a study's).
    if technician["status"] != "ACTIVE":
        raise ApiError("ERR_TECHNICIAN_INACTIVE")
    if equipment["modality"] not in technician["certified_modalities"]:
        raise ApiError("ERR_TECHNICIAN_NOT_CERTIFIED")

    now = clock.now()
    rec = db.new_record(with_version=False)
    rec.update(
        {
            "equipment_id": equipment["id"],
            "performed_by_technician_id": technician["id"],
            "result": result,
            "note": note,
            "performed_at": now,
            "affected_study_count": 0,
        }
    )
    db.insert("qc_checks", rec)

    if result == "PASS":
        equipment["last_passing_qc_at"] = now
        equipment["usage_count_since_qc"] = 0
        db.touch(equipment)
    else:
        rec["affected_study_count"] = cascades.quarantine_cascade(equipment, affected)
    return one("qc_checks", rec, 201)


@bp.get("/qc-checks/<qc_check_id>")
def get_qc_check(qc_check_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("qc_checks", need("qc_checks", qc_check_id, "ERR_RECORD_NOT_FOUND"))


@bp.get("/qc-checks")
def list_qc_checks():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("qc_checks")
    rows = apply_filters(
        rows,
        {
            "equipment_id": "equipment_id",
            "performed_by_technician_id": "performed_by_technician_id",
            "result": "result",
        },
    )
    return listing("qc_checks", rows)


# ==========================================================================
# PeerReview
# ==========================================================================

@bp.post("/peer-reviews")
def create_peer_review():
    authenticate()
    authorize("PlatformAdmin")
    data = body()
    report = fk(data, "report_id", "reports", "ERR_REPORT_NOT_FOUND")
    reviewer = fk(data, "reviewer_specialist_id", "specialists", "ERR_SPECIALIST_NOT_FOUND")
    req_id(data, "report_id")
    req_id(data, "reviewer_specialist_id")
    # rung 22
    if report["status"] not in ("PUBLISHED", "SUPERSEDED", "RETRACTED"):
        raise ApiError("ERR_PEER_REVIEW_INVALID_STATE")
    # rung 29
    if reviewer["status"] != "ACTIVE":
        raise ApiError("ERR_SPECIALIST_INACTIVE")
    # rung 39 — segregation of duties
    if reviewer["id"] == report["author_specialist_id"]:
        raise ApiError("ERR_PEER_REVIEW_SELF")

    rec = db.new_record()
    rec.update(
        {
            "report_id": report["id"],
            "reviewer_specialist_id": reviewer["id"],
            "status": "SAMPLED",
            "score": None,
            "outcome_note": None,
        }
    )
    db.insert("peer_reviews", rec)
    return one("peer_reviews", rec, 201)


@bp.get("/peer-reviews/<peer_review_id>")
def get_peer_review(peer_review_id):
    authenticate()
    authorize(*READ_ROLES)
    return one(
        "peer_reviews", need("peer_reviews", peer_review_id, "ERR_RECORD_NOT_FOUND")
    )


@bp.get("/peer-reviews")
def list_peer_reviews():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("peer_reviews")
    rows = apply_filters(
        rows,
        {
            "report_id": "report_id",
            "reviewer_specialist_id": "reviewer_specialist_id",
            "status": "status",
        },
    )
    return listing("peer_reviews", rows)


@bp.post("/peer-reviews/<peer_review_id>/submit")
def submit_peer_review(peer_review_id):
    authenticate()
    authorize("Specialist")
    review = need("peer_reviews", peer_review_id, "ERR_RECORD_NOT_FOUND")
    require_owner(g.user_id == review["reviewer_specialist_id"])
    data = body()
    score = req_int(
        data, "score", minimum=PEER_REVIEW_SCORE_MIN, maximum=PEER_REVIEW_SCORE_MAX
    )
    note = opt_str(data, "outcome_note")
    # rung 22 — the report is checked before the peer review.
    report = db.get("reports", review["report_id"])
    if report is None or report["status"] not in ("PUBLISHED", "SUPERSEDED", "RETRACTED"):
        raise ApiError("ERR_PEER_REVIEW_INVALID_STATE")
    if review["status"] != "SAMPLED":
        raise ApiError("ERR_PEER_REVIEW_INVALID_STATE")

    review["score"] = score
    review["outcome_note"] = note
    review["status"] = (
        "DISCORDANT" if score <= PEER_REVIEW_DISCORDANT_SCORE_MAX else "CONCUR"
    )
    db.touch(review)
    return one("peer_reviews", review)
