"""Consent directive endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import clock, commit, create, db, fmt_dt, parse_iso, snapshot, touch
from errors import ApiError
from middleware import HIE_ADMIN, PRIVACY_OFFICER, authenticate
from response import entity, entity_created, paginate, pagination
from services import repo
from services.clusters import recount
from services.counters import recompute_policy_directive_count
from validate import body, opt_dt, opt_enum_list, opt_id, req_enum, req_int, req_str
from routes.governance import SENSITIVE_CATEGORIES

bp = Blueprint("directives", __name__)

DIRECTIVE_TYPES = ("OPT_IN", "OPT_OUT", "SENSITIVE_CATEGORY_RESTRICTION")
DIRECTIVE_SCOPES = ("ALL_PARTICIPANTS", "SINGLE_PARTICIPANT")
TERMINAL_DIRECTIVE_STATES = ("SUPERSEDED", "REVOKED")


@bp.route("/hie/identity-clusters/<cluster_id>/consent-directives", methods=["POST"])
def record_directive(cluster_id):
    actor = authenticate((PRIVACY_OFFICER,))
    payload = body()
    directive_type = req_enum(payload, "directive_type", DIRECTIVE_TYPES)
    scope = req_enum(payload, "scope", DIRECTIVE_SCOPES)
    expected = req_int(payload, "expected_cluster_version")
    scoped_participant_id = opt_id(payload, "scoped_participant_id")
    categories = opt_enum_list(payload, "restricted_categories", SENSITIVE_CATEGORIES, [])
    from_raw, from_dt = opt_dt(payload, "effective_from")

    cluster = repo.must("clusters", cluster_id)
    if scoped_participant_id is not None:
        repo.must("participants", scoped_participant_id)

    if expected != int(cluster["version"]):
        raise ApiError("ERR_STALE_CLUSTER_VERSION")
    if cluster["status"] != "ACTIVE":
        raise ApiError("ERR_CLUSTER_MERGED_AWAY")

    policy = repo.active_policy_at(clock())
    if policy is None:
        raise ApiError("ERR_NO_ACTIVE_CONSENT_POLICY")

    if scope == "SINGLE_PARTICIPANT" and scoped_participant_id is None:
        raise ApiError("ERR_DIRECTIVE_SCOPE_PARTICIPANT_REQUIRED")
    if scope == "ALL_PARTICIPANTS" and scoped_participant_id is not None:
        raise ApiError("ERR_DIRECTIVE_SCOPE_PARTICIPANT_REQUIRED")
    if directive_type == "SENSITIVE_CATEGORY_RESTRICTION" and not categories:
        raise ApiError("ERR_DIRECTIVE_SCOPE_PARTICIPANT_REQUIRED")

    if from_raw is None:
        from_raw = fmt_dt(clock())
        from_dt = clock()

    directive = create(
        db.directives,
        "ConsentDirective",
        {
            "cluster_id": cluster["id"],
            "policy_id": policy["id"],
            "directive_type": directive_type,
            "scope": scope,
            "scoped_participant_id": scoped_participant_id,
            "restricted_categories": list(categories),
            "effective_from": from_raw,
            "status": "ACTIVE",
            "supersedes_directive_id": None,
            "recorded_by_user_id": actor.user_id,
            "revocation_reason": None,
        },
    )

    for incumbent in repo.where(
        "directives", cluster_id=cluster["id"], status="ACTIVE"
    ):
        if incumbent["id"] == directive["id"]:
            continue
        if incumbent["directive_type"] != directive_type:
            continue
        if incumbent["scope"] != scope:
            continue
        if incumbent["scoped_participant_id"] != scoped_participant_id:
            continue
        incumbent_from = parse_iso(incumbent["effective_from"])
        if incumbent_from is not None and from_dt < incumbent_from:
            continue
        snap = snapshot(incumbent)
        incumbent["status"] = "SUPERSEDED"
        commit(incumbent, snap)
        directive["supersedes_directive_id"] = incumbent["id"]

    recount(cluster)
    touch(cluster)
    policy_snap = snapshot(policy)
    recompute_policy_directive_count(policy)
    commit(policy, policy_snap)
    return entity_created(directive)


@bp.route("/hie/consent-directives/<directive_id>/revocation", methods=["POST"])
def revoke_directive(directive_id):
    authenticate((PRIVACY_OFFICER,))
    payload = body()
    reason = req_str(payload, "revocation_reason")

    directive = repo.must("directives", directive_id)
    if directive["status"] in TERMINAL_DIRECTIVE_STATES:
        raise ApiError("ERR_TERMINAL_STATE")
    if directive["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    directive["status"] = "REVOKED"
    directive["revocation_reason"] = reason
    touch(directive)

    cluster = repo.get("clusters", directive["cluster_id"])
    if cluster is not None:
        recount(cluster)
        touch(cluster)
    return entity(directive)


@bp.route("/hie/consent-directives/<directive_id>", methods=["GET"])
def read_directive(directive_id):
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    return entity(repo.must("directives", directive_id))


@bp.route("/hie/consent-directives", methods=["GET"])
def list_directives():
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    limit, offset = pagination()
    rows = repo.all_rows("directives")
    for key in (
        "cluster_id",
        "policy_id",
        "scoped_participant_id",
        "supersedes_directive_id",
        "status",
        "directive_type",
    ):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, limit, offset)
