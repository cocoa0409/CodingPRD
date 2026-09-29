"""Policy documents, versions and jurisdiction addenda."""
from flask import Blueprint

import auth
import clock
import db
import services
import validate
import web
from errors import fail

bp = Blueprint("authoring", __name__)

CATEGORIES = ["CODE_OF_CONDUCT", "LEAVE", "SAFETY", "COMPENSATION", "DATA_PRIVACY"]
READ_ANY = auth.ALL_ROLES
ADDENDUM_READ = ["HRComplianceAdmin", "PolicyAuthor", "LegalCounsel", "LocalizationSpecialist"]


@bp.post("/policy-documents")
def create_document():
    actor = auth.authorize(["PolicyAuthor"])
    data = validate.body()
    title = validate.req_str(data, "title", min_len=3, max_len=160)
    category = validate.req_enum(data, "category", CATEGORIES)
    max_days = validate.opt_int(data, "max_ack_deadline_days", 30, 1, 180)
    for row in db.all_rows("policy_documents"):
        if row["title"] == title:
            fail("ERR_DUPLICATE_RESOURCE", "title already registered")
    row = db.base_row()
    row.update({
        "title": title,
        "category": category,
        "owner_user_id": actor.user_id,
        "current_published_version_id": None,
        "latest_version_no": 0,
        "max_ack_deadline_days": max_days,
    })
    db.insert("policy_documents", row)
    return web.created("policy_documents", row)


@bp.get("/policy-documents")
def list_documents():
    auth.authorize(READ_ANY)
    rows = db.all_rows("policy_documents")
    rows = validate.query_filter(rows, "category")
    rows = validate.query_filter(rows, "current_published_version_id")
    return web.paged("policy_documents", rows)


@bp.get("/policy-documents/<policy_document_id>")
def read_document(policy_document_id):
    auth.authorize(READ_ANY)
    row = validate.path_row("policy_documents", policy_document_id)
    return web.one("policy_documents", row)


@bp.post("/policy-documents/<policy_document_id>/versions")
def create_version(policy_document_id):
    auth.authorize(["PolicyAuthor"])
    document = validate.path_row("policy_documents", policy_document_id)
    data = validate.body()
    raw_required = data.get("required_jurisdiction_ids")
    if isinstance(raw_required, list):
        for jid in raw_required:
            if isinstance(jid, str):
                validate.fk("jurisdictions", jid)
    body_text = validate.req_str(data, "body_text")
    section_count = validate.req_int(data, "section_count", 1, 40)
    required = validate.req_id_array(data, "required_jurisdiction_ids")
    expected = validate.req_int(data, "expected_policy_document_version")
    if expected != document["version"]:
        fail("ERR_STALE_POLICY_DOCUMENT_VERSION", "expected_policy_document_version is stale")
    row = db.base_row()
    row.update({
        "policy_document_id": document["id"],
        "version_no": document["latest_version_no"] + 1,
        "body_text": body_text,
        "section_count": section_count,
        "status": "DRAFT",
        "required_jurisdiction_ids": list(required),
        "effective_date": None,
        "window_end_date": None,
        "revision_round": 0,
        "approved_at": None,
        "pinned_addendum_ids": [],
    })
    db.insert("policy_versions", row)
    document["latest_version_no"] = document["latest_version_no"] + 1
    db.touch(document)
    return web.created("policy_versions", row)


@bp.get("/policy-versions")
def list_versions():
    auth.authorize(READ_ANY)
    rows = db.all_rows("policy_versions")
    rows = validate.query_filter(rows, "policy_document_id")
    rows = validate.query_filter(rows, "status")
    return web.paged("policy_versions", rows)


@bp.get("/policy-versions/<policy_version_id>")
def read_version(policy_version_id):
    auth.authorize(READ_ANY)
    row = validate.path_row("policy_versions", policy_version_id)
    return web.one("policy_versions", row)


@bp.post("/policy-versions/<policy_version_id>/addenda")
def create_addendum(policy_version_id):
    auth.authorize(["PolicyAuthor"])
    version = validate.path_row("policy_versions", policy_version_id)
    data = validate.body()
    if "jurisdiction_id" in data:
        validate.fk("jurisdictions", data.get("jurisdiction_id"))
    jurisdiction_id = validate.req_str(data, "jurisdiction_id")
    body_text = validate.req_str(data, "body_text")
    if version["status"] not in ("DRAFT", "IN_LEGAL_REVIEW"):
        fail("ERR_VERSION_INVALID_STATE", "version is %s" % version["status"])
    for row in services.rows_where("addenda", policy_version_id=version["id"],
                                   jurisdiction_id=jurisdiction_id):
        fail("ERR_DUPLICATE_RESOURCE", "addendum already exists for this jurisdiction")
    row = db.base_row()
    row.update({
        "policy_version_id": version["id"],
        "jurisdiction_id": jurisdiction_id,
        "body_text": body_text,
        "status": "DRAFT",
        "approved_by_reviewer_id": None,
    })
    db.insert("addenda", row)
    return web.created("addenda", row)


@bp.get("/addenda")
def list_addenda():
    auth.authorize(ADDENDUM_READ)
    rows = db.all_rows("addenda")
    rows = validate.query_filter(rows, "policy_version_id")
    rows = validate.query_filter(rows, "jurisdiction_id")
    rows = validate.query_filter(rows, "approved_by_reviewer_id")
    rows = validate.query_filter(rows, "status")
    return web.paged("addenda", rows)


@bp.get("/addenda/<addendum_id>")
def read_addendum(addendum_id):
    auth.authorize(ADDENDUM_READ)
    row = validate.path_row("addenda", addendum_id)
    return web.one("addenda", row)


@bp.post("/addenda/<addendum_id>/approve")
def approve_addendum(addendum_id):
    actor = auth.authorize(["LegalCounsel"])
    addendum = validate.path_row("addenda", addendum_id)
    if actor.entity["jurisdiction_id"] != addendum["jurisdiction_id"]:
        fail("ERR_REVIEWER_JURISDICTION_MISMATCH", "reviewer is not licensed in this jurisdiction")
    if addendum["status"] != "DRAFT":
        fail("ERR_ADDENDUM_INVALID_STATE", "addendum is %s" % addendum["status"])
    version = db.get("policy_versions", addendum["policy_version_id"])
    if version is None or version["status"] not in ("DRAFT", "IN_LEGAL_REVIEW"):
        fail("ERR_VERSION_INVALID_STATE", "owning version is not open for addendum approval")
    addendum["status"] = "APPROVED"
    addendum["approved_by_reviewer_id"] = actor.user_id
    db.touch(addendum)
    return web.one("addenda", addendum)


@bp.post("/policy-versions/<policy_version_id>/submit-for-review")
def submit_for_review(policy_version_id):
    auth.authorize(["PolicyAuthor"])
    version = validate.path_row("policy_versions", policy_version_id)
    if version["status"] != "DRAFT":
        fail("ERR_VERSION_INVALID_STATE", "version is %s" % version["status"])
    for jid in version["required_jurisdiction_ids"]:
        addenda = [a for a in services.rows_where("addenda", policy_version_id=version["id"],
                                                  jurisdiction_id=jid)
                   if a["status"] in ("DRAFT", "APPROVED")]
        if len(addenda) != 1:
            fail("ERR_ADDENDUM_NOT_APPROVED", "no draft or approved addendum for jurisdiction %s" % jid)
    for jid in version["required_jurisdiction_ids"]:
        reviews = [r for r in services.rows_where("legal_reviews", policy_version_id=version["id"],
                                                  jurisdiction_id=jid)
                   if r["status"] == "REQUESTED"]
        if len(reviews) != 1:
            fail("ERR_LEGAL_REVIEW_INCOMPLETE", "no requested review for jurisdiction %s" % jid)
    version["status"] = "IN_LEGAL_REVIEW"
    db.touch(version)
    return web.one("policy_versions", version)


@bp.post("/policy-versions/<policy_version_id>/approve")
def approve_version(policy_version_id):
    auth.authorize(["HRComplianceAdmin"])
    version = validate.path_row("policy_versions", policy_version_id)
    if version["status"] != "IN_LEGAL_REVIEW":
        fail("ERR_VERSION_INVALID_STATE", "version is %s" % version["status"])
    for jid in version["required_jurisdiction_ids"]:
        approved = [r for r in services.rows_where("legal_reviews", policy_version_id=version["id"],
                                                   jurisdiction_id=jid)
                    if r["status"] == "APPROVED"]
        if not approved:
            fail("ERR_LEGAL_REVIEW_INCOMPLETE", "no approved review for jurisdiction %s" % jid)
    for jid in version["required_jurisdiction_ids"]:
        approved = [a for a in services.rows_where("addenda", policy_version_id=version["id"],
                                                   jurisdiction_id=jid)
                    if a["status"] == "APPROVED"]
        if not approved:
            fail("ERR_ADDENDUM_NOT_APPROVED", "no approved addendum for jurisdiction %s" % jid)
    version["status"] = "APPROVED"
    version["approved_at"] = clock.now()
    version["pinned_addendum_ids"] = [
        a["id"] for a in services.rows_where("addenda", policy_version_id=version["id"])
        if a["status"] == "APPROVED"
    ]
    db.touch(version)
    return web.one("policy_versions", version)


@bp.post("/policy-versions/<policy_version_id>/reopen")
def reopen_version(policy_version_id):
    auth.authorize(["PolicyAuthor"])
    version = validate.path_row("policy_versions", policy_version_id)
    if version["status"] != "APPROVED":
        fail("ERR_VERSION_INVALID_STATE", "version is %s" % version["status"])
    for item in services.rows_where("release_items", policy_version_id=version["id"]):
        package = db.get("release_packages", item["release_package_id"])
        if package is not None and package["status"] in ("SCHEDULED", "RELEASED", "CLOSED"):
            fail("ERR_VERSION_INVALID_STATE", "version is committed to a live release package")
    version["status"] = "DRAFT"
    version["approved_at"] = None
    version["pinned_addendum_ids"] = []
    version["revision_round"] = version["revision_round"] + 1
    db.touch(version)
    for review in services.rows_where("legal_reviews", policy_version_id=version["id"]):
        if review["status"] != "APPROVED":
            continue
        review["status"] = "REQUESTED"
        review["round_no"] = review["round_no"] + 1
        review["decided_at"] = None
        db.touch(review)
        reviewer = db.get("legal_reviewers", review["reviewer_id"])
        if reviewer is not None:
            services.adjust_open_reviews(reviewer, 1)
    return web.one("policy_versions", version)


@bp.post("/policy-versions/<policy_version_id>/withdraw")
def withdraw_version(policy_version_id):
    auth.authorize(["HRComplianceAdmin"])
    version = validate.path_row("policy_versions", policy_version_id)
    status = version["status"]
    if status not in ("DRAFT", "PUBLISHED"):
        fail("ERR_VERSION_INVALID_STATE", "version is %s" % status)
    version["status"] = "WITHDRAWN"
    if status == "PUBLISHED":
        version["window_end_date"] = clock.now()
    db.touch(version)
    if status == "DRAFT":
        services.retire_addenda(version)
    else:
        document = services.document_of_version(version)
        if document is not None and document.get("current_published_version_id") == version["id"]:
            document["current_published_version_id"] = None
        services.void_open_assignments(version)
    return web.one("policy_versions", version)
