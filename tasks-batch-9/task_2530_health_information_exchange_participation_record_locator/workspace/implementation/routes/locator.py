"""Record locator queries and the access audit trail (PRD 3.7)."""
from flask import Blueprint, request

from db import clock, create, db, parse_iso, serialize
from errors import ApiError
from middleware import (
    CLINICIAN,
    HIE_ADMIN,
    PARTICIPANT_ADMIN,
    PRIVACY_OFFICER,
    PUBLIC_HEALTH_OFFICER,
    PURPOSE_DOMAIN,
    authenticate,
    require_purpose,
    require_scope,
)
from response import entity, entity_created, paginate, pagination
from services import consent, repo, sanctions
from validate import (
    body,
    opt_digits,
    opt_enum,
    opt_id,
    opt_str,
    req_date,
    req_enum,
    req_str,
)
from routes.records import SEXES

bp = Blueprint("locator", __name__)

AUDIT_ACTIONS = ("DISCLOSED", "WITHHELD", "BREAK_GLASS_DISCLOSED")
OPERATIONAL_FEED_STATUSES = ("MONITORED", "DEGRADED")


def _has_operational_ccda_feed(participant_id):
    for feed in repo.participant_feeds(participant_id):
        if feed["feed_type"] == "CCDA" and feed["status"] in OPERATIONAL_FEED_STATUSES:
            return True
    return False


@bp.route("/hie/record-locator-queries", methods=["POST"])
def submit_query():
    actor = authenticate((CLINICIAN, PARTICIPANT_ADMIN, PUBLIC_HEALTH_OFFICER))
    payload = body()
    raw_participant = payload.get("querying_participant_id")
    if isinstance(raw_participant, str):
        require_scope(actor, raw_participant)
    require_purpose(actor, payload.get("purpose_of_use"))

    querying_participant_id = req_str(payload, "querying_participant_id")
    purpose_of_use = req_enum(payload, "purpose_of_use", PURPOSE_DOMAIN)
    family_name = req_str(payload, "family_name")
    given_name = req_str(payload, "given_name")
    birth_date = req_date(payload, "birth_date")
    sex = opt_enum(payload, "sex", SEXES)
    ssn_last4 = opt_digits(payload, "ssn_last4", 4)
    postal_code = opt_str(payload, "postal_code")
    phone_digits = opt_digits(payload, "phone_digits", 10)
    break_glass_id = opt_id(payload, "break_glass_id")

    participant = repo.must("participants", querying_participant_id)
    session = None
    if break_glass_id is not None:
        session = repo.must("break_glass", break_glass_id)

    if participant["onboarding_status"] != "CERTIFIED":
        raise ApiError("ERR_PARTICIPANT_NOT_CERTIFIED")
    if not _has_operational_ccda_feed(participant["id"]):
        raise ApiError("ERR_QUERY_FEED_NOT_OPERATIONAL")

    policy = repo.active_policy_at(clock())
    if policy is None:
        raise ApiError("ERR_NO_ACTIVE_CONSENT_POLICY")

    if session is not None:
        sanctions.expire_if_due(session)
        expires = parse_iso(session["expires_at"])
        if session["session_status"] != "OPEN":
            raise ApiError("ERR_BREAK_GLASS_SESSION_NOT_OPEN")
        if expires is None or clock() > expires:
            raise ApiError("ERR_BREAK_GLASS_SESSION_NOT_OPEN")
        if session["invoking_clinician_user_id"] != actor.user_id:
            raise ApiError("ERR_BREAK_GLASS_SESSION_NOT_OPEN")

    config = repo.active_threshold_config()
    if config is None:
        raise ApiError("ERR_NO_ACTIVE_THRESHOLD_CONFIG")

    demographics = {
        "family_name": family_name,
        "given_name": given_name,
        "birth_date": birth_date,
        "ssn_last4": ssn_last4,
        "postal_code": postal_code,
        "phone_digits": phone_digits,
    }
    outcome, plan, _cluster = consent.evaluate(
        participant, config, policy, demographics, purpose_of_use, session
    )

    fields = {
        "querying_participant_id": querying_participant_id,
        "clinician_user_id": actor.user_id,
        "purpose_of_use": purpose_of_use,
        "family_name": family_name,
        "given_name": given_name,
        "birth_date": birth_date,
        "sex": sex,
        "ssn_last4": ssn_last4,
        "postal_code": postal_code,
        "phone_digits": phone_digits,
        "break_glass_id": break_glass_id,
    }
    fields.update(outcome)
    query = create(db.queries, "RecordLocatorQuery", fields, versioned=False)

    for item in plan:
        create(
            db.audit_entries,
            "AccessAuditEntry",
            {
                "query_id": query["id"],
                "record_id": item["record_id"],
                "disclosing_participant_id": item["disclosing_participant_id"],
                "action": item["action"],
                "suppression_reason": item["suppression_reason"],
                "sensitive_category_hit": item["sensitive_category_hit"],
                "reviewed": False,
            },
            versioned=False,
        )
    return entity_created(query)


@bp.route("/hie/record-locator-queries/<query_id>", methods=["GET"])
def read_query(query_id):
    authenticate((PRIVACY_OFFICER, HIE_ADMIN, PARTICIPANT_ADMIN))
    return entity(repo.must("queries", query_id))


@bp.route("/hie/record-locator-queries", methods=["GET"])
def list_queries():
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    limit, offset = pagination()
    rows = repo.all_rows("queries")
    for key in (
        "querying_participant_id",
        "cluster_id",
        "break_glass_id",
        "governing_policy_id",
        "governing_directive_id",
        "consent_decision",
    ):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, limit, offset)


@bp.route("/hie/access-audit-entries/<entry_id>", methods=["GET"])
def read_audit_entry(entry_id):
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    return entity(repo.must("audit_entries", entry_id))


@bp.route("/hie/access-audit-entries", methods=["GET"])
def list_audit_entries():
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    limit, offset = pagination()
    rows = repo.all_rows("audit_entries")
    for key in ("query_id", "record_id", "disclosing_participant_id", "action"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, limit, offset)
