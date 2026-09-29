"""The insight repository: themes, findings and evidence links (PRD 3.7)."""
from decimal import Decimal as D

from flask import Blueprint, g

import serializers
from auth import ALL_ROLES, require_roles
from calc import (
    MIN_DISTINCT_PARTICIPANTS,
    MIN_PUBLISH_STRENGTH,
    THEME_MAX_DEPTH,
    link_contribution,
    recompute_finding,
    refresh_theme_weights,
    set_field,
)
from clock import clock
from envelope import created, no_content, ok, paged_listing
from errors import ApiError
from store import by_created, db
from validators import (
    artifact_or_404,
    body,
    filter_bool,
    filter_enum,
    filter_str,
    finding_or_404,
    link_or_404,
    ref,
    req_enum,
    req_str,
    study_or_404,
    theme_or_404,
)

bp = Blueprint("repository", __name__)

THEME_STATUSES = ("EMERGING", "ESTABLISHED")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
FINDING_STATUSES = ("DRAFT", "EVIDENCE_LOCKED", "PUBLISHED", "RETRACTED")
WEIGHT_CLASSES = ("DIRECT_QUOTE", "OBSERVED_BEHAVIOR", "SELF_REPORT")


@bp.post("/themes")
@require_roles("Researcher", "ResearchLead")
def create_theme():
    data = body()
    parent = theme_or_404(ref(data, "parent_theme_id"))
    label = req_str(data, "label")
    depth = 1 if parent is None else parent["depth"] + 1
    if depth > THEME_MAX_DEPTH:
        raise ApiError("ERR_THEME_DEPTH_EXCEEDED", "The theme tree is capped at three levels.")
    if any(t["label"] == label for t in db.themes.values()):
        raise ApiError("ERR_DUPLICATE_LABEL", "That theme label already exists.")
    row = db.new("themes", {
        "label": label,
        "parent_theme_id": parent["id"] if parent is not None else None,
        "depth": depth,
        "own_evidence_weight": D("0.00"),
        "evidence_weight": D("0.00"),
        "reuse_count": 0,
        "status": "EMERGING",
    })
    return created(serializers.theme(row))


@bp.get("/themes/<theme_id>")
@require_roles(*ALL_ROLES)
def read_theme(theme_id):
    return ok(serializers.theme(theme_or_404(theme_id)))


@bp.get("/themes")
@require_roles(*ALL_ROLES)
def list_themes():
    parent = theme_or_404(_filter_id("parent_theme_id"))
    status = filter_enum("status", THEME_STATUSES)
    label_contains = filter_str("label_contains")
    rows = list(db.themes.values())
    if parent is not None:
        rows = [t for t in rows if t["parent_theme_id"] == parent["id"]]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if label_contains is not None:
        rows = [t for t in rows if label_contains in t["label"]]
    rows = sorted(rows, key=lambda t: (-D(t["evidence_weight"]), t["created_at"], t["_seq"]))
    return paged_listing(rows, serializers.theme)


@bp.post("/findings")
@require_roles("Researcher", "ResearchLead")
def create_finding():
    data = body()
    study = study_or_404(ref(data, "study_id"))
    theme = theme_or_404(ref(data, "theme_id"))
    req_str(data, "study_id")
    req_str(data, "theme_id")
    statement = req_str(data, "statement", max_len=500)
    severity = req_enum(data, "severity", SEVERITIES)
    row = db.new("findings", {
        "study_id": study["id"],
        "theme_id": theme["id"],
        "authored_by_user_id": g.user_id,
        "statement": statement,
        "severity": severity,
        "evidence_strength": D("0.00"),
        "strength_variant": "PROVISIONAL",
        "admissible_link_count": 0,
        "distinct_participant_count": 0,
        "status": "DRAFT",
        "retraction_reason": None,
        "published_at": None,
    })
    return created(serializers.finding(row))


@bp.post("/findings/<finding_id>/evidence-links")
@require_roles("Researcher", "ResearchLead")
def create_link(finding_id):
    data = body()
    artifact = artifact_or_404(ref(data, "artifact_id"))
    finding = finding_or_404(finding_id)
    req_str(data, "artifact_id")
    excerpt_ref = req_str(data, "excerpt_ref")
    weight_class = req_enum(data, "weight_class", WEIGHT_CLASSES)
    if finding["status"] in ("PUBLISHED", "RETRACTED"):
        raise ApiError("ERR_INVALID_STATE", "Evidence links cannot be written on a %s finding." % finding["status"])
    if artifact["lifecycle_state"] != "RETAINED":
        raise ApiError("ERR_ARTIFACT_PURGED", "The cited artifact has been purged.")
    recruitment = db.recruitments.get(artifact["recruitment_id"])
    if recruitment is None or recruitment["study_id"] != finding["study_id"]:
        raise ApiError("ERR_EVIDENCE_STUDY_MISMATCH", "The artifact belongs to another study.")
    study = db.studies.get(finding["study_id"])
    if finding["status"] == "EVIDENCE_LOCKED":
        set_field(finding, "status", "DRAFT")
        set_field(finding, "strength_variant", "PROVISIONAL")
    row = db.new("links", {
        "finding_id": finding["id"],
        "artifact_id": artifact["id"],
        "excerpt_ref": excerpt_ref,
        "weight_class": weight_class,
        "contribution": link_contribution(weight_class, study["method"]),
        "is_admissible": True,
        "inadmissible_reason": None,
    })
    recompute_finding(finding)
    return created(serializers.link(row))


@bp.delete("/evidence-links/<link_id>")
@require_roles("Researcher", "ResearchLead")
def delete_link(link_id):
    link = link_or_404(link_id)
    finding = db.findings.get(link["finding_id"])
    if finding is None or finding["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Links can only be removed from a DRAFT finding.")
    db.delete("links", link)
    recompute_finding(finding)
    return no_content()


@bp.post("/findings/<finding_id>/lock")
@require_roles("Researcher", "ResearchLead")
def lock_finding(finding_id):
    finding = finding_or_404(finding_id)
    study = db.studies.get(finding["study_id"])
    if finding["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT finding can be locked.")
    if study is None or study["execution_status"] not in ("ANALYSIS", "REPORTED", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE", "The study has not reached analysis.")
    if finding["admissible_link_count"] < 1:
        raise ApiError("ERR_NO_ADMISSIBLE_EVIDENCE", "The finding carries no admissible evidence.")
    if finding["distinct_participant_count"] < MIN_DISTINCT_PARTICIPANTS:
        raise ApiError("ERR_INSUFFICIENT_CORROBORATION", "At least three distinct participants are required.")
    set_field(finding, "status", "EVIDENCE_LOCKED")
    set_field(finding, "strength_variant", "CORROBORATED")
    recompute_finding(finding)
    return ok(serializers.finding(finding))


@bp.post("/findings/<finding_id>/publish")
@require_roles("ResearchLead", "ResearchOpsAdmin")
def publish_finding(finding_id):
    existing = db.findings.get(finding_id)
    if existing is not None and existing["authored_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "A finding cannot be published by its author.")
    finding = finding_or_404(finding_id)
    if finding["status"] != "EVIDENCE_LOCKED":
        raise ApiError("ERR_INVALID_STATE", "Only an EVIDENCE_LOCKED finding can be published.")
    if D(finding["evidence_strength"]) < MIN_PUBLISH_STRENGTH:
        raise ApiError("ERR_EVIDENCE_TOO_WEAK", "The finding's evidence strength is below 0.45.")
    set_field(finding, "status", "PUBLISHED")
    set_field(finding, "published_at", clock.now())
    refresh_theme_weights(db.themes.get(finding["theme_id"]))
    return ok(serializers.finding(finding))


@bp.get("/findings/<finding_id>")
@require_roles(*ALL_ROLES)
def read_finding(finding_id):
    return ok(serializers.finding(finding_or_404(finding_id)))


@bp.get("/findings")
@require_roles(*ALL_ROLES)
def list_findings():
    study = study_or_404(_filter_id("study_id"))
    theme_id = _filter_id("theme_id")
    status = filter_enum("status", FINDING_STATUSES)
    rows = list(db.findings.values())
    if study is not None:
        rows = [f for f in rows if f["study_id"] == study["id"]]
    if theme_id is not None:
        rows = [f for f in rows if f["theme_id"] == theme_id]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    rows = sorted(rows, key=lambda f: (-D(f["evidence_strength"]), f["created_at"], f["_seq"]))
    return paged_listing(rows, serializers.finding)


@bp.get("/findings/<finding_id>/evidence-links")
@require_roles(*ALL_ROLES)
def list_finding_links(finding_id):
    finding = finding_or_404(finding_id)
    is_admissible = filter_bool("is_admissible")
    rows = [l for l in db.links.values() if l["finding_id"] == finding["id"]]
    if is_admissible is not None:
        rows = [l for l in rows if l["is_admissible"] == is_admissible]
    return paged_listing(by_created(rows), serializers.link)


def _filter_id(name):
    from flask import request as flask_request
    raw = flask_request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
