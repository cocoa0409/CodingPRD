"""Rights scripts and self-help resources: governance chain + cascades."""

from flask import Blueprint, request

from db import store, now
from errors import (
    raise_err, invalid_request, not_found, forbidden, invalid_state,
    ERR_SCRIPT_REVIEWER_CONFLICT, ERR_SCRIPT_VERSION_CHAIN_BROKEN,
    ERR_DUPLICATE_PUBLISHED_SCRIPT, ERR_SCRIPT_NOT_PUBLISHED,
)
from middleware import require_roles
from response import ok_object, ok_list
from serializers import script_out, resource_out
from services import (
    make_record, bump, outdate_script_cascade, retire_script_cascade,
    outdate_resource_cascade, ISSUE_CATEGORIES,
)
from util import (
    get_payload, check_unknown, require, as_str, as_int, as_enum, parse_dt,
    page_of, query_enum,
)

bp = Blueprint("scripts", __name__)

SCRIPT_STATUSES = ("DRAFT", "IN_REVIEW", "PUBLISHED", "SUPERSEDED", "RETIRED")
RESOURCE_STATUSES = ("CURRENT", "OUTDATED", "RETIRED")
SCRIPT_READ_ROLES = ("Counselor", "HotlineSupervisor", "AgencyAdmin", "DataProtectionOfficer", "Analyst")


def _actor_is_reviewer(role, uid):
    if role != "Counselor":
        return False
    counselor = store.counselors.get(uid)
    return counselor is not None and counselor["is_script_reviewer"]


# ---------------------------------------------------------------------------
# RightsScript
# ---------------------------------------------------------------------------

@bp.route("/hotline/scripts", methods=["POST"])
def create_script():
    _, uid = require_roles("Counselor")
    data = get_payload()
    check_unknown(data, {"jurisdiction_id", "issue_category", "version_no", "body", "supersedes_script_id"})
    jurisdiction_id = as_str(require(data, "jurisdiction_id"), "jurisdiction_id")
    issue_category = as_enum(require(data, "issue_category"), "issue_category", ISSUE_CATEGORIES)
    version_no = as_int(require(data, "version_no"), "version_no")
    body = as_str(require(data, "body"), "body")
    supersedes_script_id = data.get("supersedes_script_id")
    if supersedes_script_id is not None:
        as_str(supersedes_script_id, "supersedes_script_id")
    if jurisdiction_id not in store.jurisdictions:
        invalid_request("jurisdiction_id does not reference an existing jurisdiction")
    if supersedes_script_id is not None and supersedes_script_id not in store.scripts:
        invalid_request("supersedes_script_id does not reference an existing script")
    rec = make_record({
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
        "version_no": version_no,
        "body": body,
        "effective_from": None,
        "effective_until": None,
        "supersedes_script_id": supersedes_script_id,
        "author_counselor_id": uid,
        "reviewer_counselor_id": None,
        "status": "DRAFT",
    })
    store.scripts[rec["id"]] = rec
    return ok_object(script_out(rec), status=201)


@bp.route("/hotline/scripts/<sid>", methods=["GET"])
def get_script(sid):
    require_roles(*SCRIPT_READ_ROLES)
    rec = store.scripts.get(sid)
    if rec is None:
        not_found("script not found")
    return ok_object(script_out(rec))


@bp.route("/hotline/scripts", methods=["GET"])
def list_scripts():
    require_roles(*SCRIPT_READ_ROLES)
    jurisdiction_id = request.args.get("jurisdiction_id")
    issue_category = query_enum("issue_category", ISSUE_CATEGORIES)
    status = query_enum("status", SCRIPT_STATUSES)
    supersedes = request.args.get("supersedes_script_id")
    author = request.args.get("author_counselor_id")
    reviewer = request.args.get("reviewer_counselor_id")
    recs = list(store.scripts.values())
    if jurisdiction_id is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jurisdiction_id]
    if issue_category is not None:
        recs = [r for r in recs if r["issue_category"] == issue_category]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if supersedes is not None:
        recs = [r for r in recs if r["supersedes_script_id"] == supersedes]
    if author is not None:
        recs = [r for r in recs if r["author_counselor_id"] == author]
    if reviewer is not None:
        recs = [r for r in recs if r["reviewer_counselor_id"] == reviewer]
    page, total, limit, offset = page_of(recs)
    return ok_list([script_out(r) for r in page], total, limit, offset)


@bp.route("/hotline/scripts/<sid>/state", methods=["POST"])
def transition_script(sid):
    role, uid = require_roles("Counselor", "HotlineSupervisor")
    rec = store.scripts.get(sid)
    if rec is None:
        not_found("script not found")
    data = get_payload()
    check_unknown(data, {"to_status", "effective_from"})
    to_status = as_enum(require(data, "to_status"), "to_status", SCRIPT_STATUSES)
    effective_from = None
    if "effective_from" in data and data["effective_from"] is not None:
        effective_from = parse_dt(data["effective_from"], "effective_from")

    current = rec["status"]

    if current == "DRAFT" and to_status == "IN_REVIEW":
        # only the author submits a draft for review
        if role != "Counselor" or uid != rec["author_counselor_id"]:
            forbidden("only the author may submit a draft for review")
        rec["status"] = "IN_REVIEW"
        bump(rec)
        return ok_object(script_out(rec))

    if current == "IN_REVIEW" and to_status == "DRAFT":
        # a reviewer returns the script for rework
        if not _actor_is_reviewer(role, uid):
            forbidden("only a script reviewer may return a script for rework")
        rec["status"] = "DRAFT"
        bump(rec)
        return ok_object(script_out(rec))

    if current == "IN_REVIEW" and to_status == "PUBLISHED":
        if not _actor_is_reviewer(role, uid):
            forbidden("publisher must be a counselor with is_script_reviewer=true")
        if uid == rec["author_counselor_id"]:
            raise_err(ERR_SCRIPT_REVIEWER_CONFLICT,
                      "segregation of duties: publisher must differ from author")
        if effective_from is None:
            invalid_request("effective_from is required for publication")
        if effective_from > now():
            invalid_request("effective_from must not lie after the current logical time")
        sup = store.scripts.get(rec["supersedes_script_id"]) if rec["supersedes_script_id"] else None
        if sup is not None and sup["effective_from"] is not None and effective_from <= sup["effective_from"]:
            invalid_request("effective_from must be strictly after the superseded script's effective_from")
        if sup is not None:
            if (
                sup["status"] != "PUBLISHED"
                or sup["jurisdiction_id"] != rec["jurisdiction_id"]
                or sup["issue_category"] != rec["issue_category"]
                or rec["version_no"] != sup["version_no"] + 1
            ):
                raise_err(ERR_SCRIPT_VERSION_CHAIN_BROKEN,
                          "supersedes target must be PUBLISHED, same pair, version_no + 1")
        else:
            duplicate = any(
                s["status"] == "PUBLISHED"
                and s["jurisdiction_id"] == rec["jurisdiction_id"]
                and s["issue_category"] == rec["issue_category"]
                for s in store.scripts.values()
            )
            if rec["version_no"] != 1 or duplicate:
                raise_err(ERR_DUPLICATE_PUBLISHED_SCRIPT,
                          "a PUBLISHED script already exists for this pair (or version_no != 1)")
        rec["reviewer_counselor_id"] = uid
        rec["effective_from"] = effective_from
        rec["status"] = "PUBLISHED"
        bump(rec)
        if sup is not None:
            outdate_script_cascade(sup, effective_from)
        return ok_object(script_out(rec))

    if current == "PUBLISHED" and to_status == "RETIRED":
        if role != "HotlineSupervisor":
            forbidden("only a HotlineSupervisor may retire a published script")
        rec["status"] = "RETIRED"
        bump(rec)
        retire_script_cascade(rec)
        return ok_object(script_out(rec))

    if current == "DRAFT" and to_status == "RETIRED":
        # author withdraws a draft
        if role != "Counselor" or uid != rec["author_counselor_id"]:
            forbidden("only the author may withdraw a draft")
        rec["status"] = "RETIRED"
        bump(rec)
        return ok_object(script_out(rec))

    invalid_state("script transition %s -> %s is not allowed" % (current, to_status))


# ---------------------------------------------------------------------------
# SelfHelpResource
# ---------------------------------------------------------------------------

RESOURCE_READ_ROLES = ("Counselor", "HotlineSupervisor", "AgencyAdmin", "Analyst")


@bp.route("/hotline/self-help-resources", methods=["POST"])
def create_resource():
    require_roles("Counselor", "HotlineSupervisor")
    data = get_payload()
    check_unknown(data, {"jurisdiction_id", "issue_category", "title", "body", "language_code", "linked_script_id"})
    jurisdiction_id = as_str(require(data, "jurisdiction_id"), "jurisdiction_id")
    issue_category = as_enum(require(data, "issue_category"), "issue_category", ISSUE_CATEGORIES)
    title = as_str(require(data, "title"), "title")
    body = as_str(require(data, "body"), "body")
    language_code = as_str(require(data, "language_code"), "language_code")
    linked_script_id = as_str(require(data, "linked_script_id"), "linked_script_id")
    if jurisdiction_id not in store.jurisdictions:
        invalid_request("jurisdiction_id does not reference an existing jurisdiction")
    script = store.scripts.get(linked_script_id)
    if script is None:
        invalid_request("linked_script_id does not reference an existing script")
    if (
        script["status"] != "PUBLISHED"
        or script["jurisdiction_id"] != jurisdiction_id
        or script["issue_category"] != issue_category
    ):
        raise_err(ERR_SCRIPT_NOT_PUBLISHED,
                  "linked script must be PUBLISHED for the resource's pair")
    rec = make_record({
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
        "title": title,
        "body": body,
        "language_code": language_code,
        "linked_script_id": linked_script_id,
        "status": "CURRENT",
    })
    store.resources[rec["id"]] = rec
    return ok_object(resource_out(rec), status=201)


@bp.route("/hotline/self-help-resources/<rid>", methods=["GET"])
def get_resource(rid):
    require_roles(*RESOURCE_READ_ROLES)
    rec = store.resources.get(rid)
    if rec is None:
        not_found("self-help resource not found")
    return ok_object(resource_out(rec))


@bp.route("/hotline/self-help-resources", methods=["GET"])
def list_resources():
    require_roles(*RESOURCE_READ_ROLES)
    jurisdiction_id = request.args.get("jurisdiction_id")
    linked_script_id = request.args.get("linked_script_id")
    status = query_enum("status", RESOURCE_STATUSES)
    recs = list(store.resources.values())
    if jurisdiction_id is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jurisdiction_id]
    if linked_script_id is not None:
        recs = [r for r in recs if r["linked_script_id"] == linked_script_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total, limit, offset = page_of(recs)
    return ok_list([resource_out(r) for r in page], total, limit, offset)


@bp.route("/hotline/self-help-resources/<rid>/state", methods=["POST"])
def transition_resource(rid):
    role, uid = require_roles("Counselor", "HotlineSupervisor")
    rec = store.resources.get(rid)
    if rec is None:
        not_found("self-help resource not found")
    data = get_payload()
    check_unknown(data, {"to_status", "linked_script_id"})
    to_status = as_enum(require(data, "to_status"), "to_status", RESOURCE_STATUSES)
    current = rec["status"]

    if current == "OUTDATED" and to_status == "CURRENT":
        linked_script_id = data.get("linked_script_id")
        if linked_script_id is None:
            invalid_request("linked_script_id is required to refresh a resource")
        as_str(linked_script_id, "linked_script_id")
        script = store.scripts.get(linked_script_id)
        if script is None:
            invalid_request("linked_script_id does not reference an existing script")
        if (
            script["status"] != "PUBLISHED"
            or script["jurisdiction_id"] != rec["jurisdiction_id"]
            or script["issue_category"] != rec["issue_category"]
        ):
            raise_err(ERR_SCRIPT_NOT_PUBLISHED,
                      "linked script must be a PUBLISHED script for the resource's pair")
        rec["linked_script_id"] = linked_script_id
        rec["status"] = "CURRENT"
        bump(rec)
        return ok_object(resource_out(rec))

    if current in ("CURRENT", "OUTDATED") and to_status == "RETIRED":
        if role != "HotlineSupervisor":
            forbidden("only a HotlineSupervisor may retire a resource")
        rec["status"] = "RETIRED"
        bump(rec)
        outdate_resource_cascade(rec, "OPERATOR")
        return ok_object(resource_out(rec))

    invalid_state("resource transition %s -> %s is not allowed" % (current, to_status))
