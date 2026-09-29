"""Patient record contribution, clusters and match links (PRD 3.3 - 3.5)."""
from flask import Blueprint, request

from db import create, db, touch
from errors import ApiError
from middleware import (
    CLINICIAN,
    HIE_ADMIN,
    PARTICIPANT_ADMIN,
    PRIVACY_OFFICER,
    authenticate,
    require_action_role,
    require_scope,
)
from response import entity, entity_created, paginate, pagination
from services import repo
from services.clusters import merge_for_link, recount, recount_and_bump, unmerge_for_link
from services.matching import agreement_output, score_pair
from services.precision import dec, out
from validate import (
    body,
    opt_digits,
    opt_enum_list,
    opt_str,
    req_date,
    req_enum,
    req_int,
    req_str,
)
from routes.governance import SENSITIVE_CATEGORIES
from routes.participants import CONTRIBUTION_STATUSES

bp = Blueprint("records", __name__)

SEXES = ("M", "F", "O", "U")
COMPLETENESS_FIELDS = (
    "given_name",
    "family_name",
    "birth_date",
    "ssn_last4",
    "postal_code",
    "phone_digits",
)
MATCH_STATES = ("CLUSTERED", "QUARANTINED", "WITHDRAWN_FROM_INDEX")
LINK_STATES = (
    "PROPOSED",
    "AUTO_LINKED",
    "PENDING_REVIEW",
    "LINKED",
    "REJECTED",
    "UNLINKED",
)
STEWARD_DECISIONS = ("CONFIRM", "REJECT", "REOPEN")
STEWARD_DECISION_ROLES = {
    "CONFIRM": (PRIVACY_OFFICER, HIE_ADMIN),
    "REJECT": (PRIVACY_OFFICER, HIE_ADMIN),
    "REOPEN": (PRIVACY_OFFICER,),
}


def completeness_score(record):
    return sum(1 for field in COMPLETENESS_FIELDS if record.get(field) is not None)


def _new_cluster_for(record):
    cluster = create(
        db.clusters,
        "IdentityCluster",
        {
            "primary_record_id": None,
            "member_record_count": 0,
            "participant_count": 0,
            "pending_review_link_count": 0,
            "status": "ACTIVE",
            "merged_into_cluster_id": None,
            "active_directive_count": 0,
        },
    )
    record["cluster_id"] = cluster["id"]
    recount(cluster)
    return cluster


@bp.route("/hie/participants/<pid>/patient-records", methods=["POST"])
def contribute_record(pid):
    actor = authenticate((PARTICIPANT_ADMIN, HIE_ADMIN))
    require_scope(actor, pid)
    payload = body()
    source_mrn = req_str(payload, "source_mrn")
    given_name = req_str(payload, "given_name")
    family_name = req_str(payload, "family_name")
    birth_date = req_date(payload, "birth_date")
    sex = req_enum(payload, "sex", SEXES)
    ssn_last4 = opt_digits(payload, "ssn_last4", 4)
    postal_code = opt_str(payload, "postal_code")
    phone_digits = opt_digits(payload, "phone_digits", 10)
    categories = opt_enum_list(payload, "sensitive_categories", SENSITIVE_CATEGORIES, [])

    participant = repo.must("participants", pid)

    for existing in repo.where("patient_records", participant_id=pid):
        if existing["source_mrn"] == source_mrn:
            raise ApiError("ERR_DUPLICATE_SOURCE_MRN")

    config = repo.active_threshold_config()
    if config is None:
        raise ApiError("ERR_NO_ACTIVE_THRESHOLD_CONFIG")

    if participant["onboarding_status"] not in CONTRIBUTION_STATUSES:
        raise ApiError("ERR_PARTICIPANT_NOT_ONBOARDED_FOR_DATA")

    fields = {
        "participant_id": pid,
        "source_mrn": source_mrn,
        "given_name": given_name,
        "family_name": family_name,
        "birth_date": birth_date,
        "sex": sex,
        "ssn_last4": ssn_last4,
        "postal_code": postal_code,
        "phone_digits": phone_digits,
        "sensitive_categories": list(categories),
        "cluster_id": None,
        "prior_cluster_id": None,
        "match_state": "CLUSTERED",
        "completeness_score": 0,
    }
    fields["completeness_score"] = sum(
        1 for field in COMPLETENESS_FIELDS if fields.get(field) is not None
    )
    record = create(db.patient_records, "PatientRecord", fields)
    _new_cluster_for(record)

    candidates = [
        r
        for r in repo.all_rows("patient_records")
        if r["id"] != record["id"]
        and r["participant_id"] != pid
        and r["match_state"] == "CLUSTERED"
    ]
    eligible_candidates = []
    for candidate in candidates:
        cluster = repo.get("clusters", candidate["cluster_id"])
        if cluster is not None and cluster["status"] == "ACTIVE":
            eligible_candidates.append(candidate)

    auto_threshold = dec(config["auto_link_threshold"])
    review_lower = dec(config["review_lower_bound"])

    for candidate in eligible_candidates:
        score, variant, agreements = score_pair(config, candidate, record)
        if score >= auto_threshold:
            status = "AUTO_LINKED"
        elif score >= review_lower:
            status = "PENDING_REVIEW"
        else:
            status = "REJECTED"
        link = create(
            db.match_links,
            "MatchLink",
            {
                "left_record_id": candidate["id"],
                "right_record_id": record["id"],
                "threshold_config_id": config["id"],
                "cluster_id": None,
                "merged_away_cluster_id": None,
                "match_score": out(score),
                "score_variant": variant,
                "field_agreement_map": agreement_output(agreements),
                "status": status,
                "reviewed_by_user_id": None,
                "review_note": None,
                "unlink_reason": None,
            },
        )
        config["scored_link_count"] = int(config["scored_link_count"] or 0) + 1
        touch(config)

        left_cluster = repo.get("clusters", candidate["cluster_id"])
        right_cluster = repo.get("clusters", record["cluster_id"])
        if status == "AUTO_LINKED":
            merge_for_link(link, left_cluster, right_cluster)
        elif status == "PENDING_REVIEW":
            recount_and_bump(left_cluster)
            if right_cluster["id"] != left_cluster["id"]:
                recount_and_bump(right_cluster)

    return entity_created(record)


@bp.route("/hie/match-links/<link_id>/steward-decision", methods=["POST"])
def steward_decision(link_id):
    actor = authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    payload = body()
    require_action_role(actor, payload.get("decision"), STEWARD_DECISION_ROLES)
    decision = req_enum(payload, "decision", STEWARD_DECISIONS)
    expected = req_int(payload, "expected_cluster_version")
    note = opt_str(payload, "review_note")

    link = repo.must("match_links", link_id)
    left_record = repo.get("patient_records", link["left_record_id"])
    right_record = repo.get("patient_records", link["right_record_id"])
    left_cluster = (
        repo.get("clusters", left_record["cluster_id"]) if left_record else None
    )
    right_cluster = (
        repo.get("clusters", right_record["cluster_id"]) if right_record else None
    )

    if left_cluster is not None and expected != int(left_cluster["version"]):
        raise ApiError("ERR_STALE_CLUSTER_VERSION")

    if link["status"] == "REJECTED":
        raise ApiError("ERR_TERMINAL_STATE")
    if decision in ("CONFIRM", "REJECT") and link["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if decision == "REOPEN":
        if link["status"] != "UNLINKED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if (
            left_cluster is None
            or right_cluster is None
            or left_cluster["status"] != "ACTIVE"
            or right_cluster["status"] != "ACTIVE"
        ):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if decision == "CONFIRM":
        if (
            left_cluster is None
            or right_cluster is None
            or left_cluster["status"] != "ACTIVE"
            or right_cluster["status"] != "ACTIVE"
        ):
            raise ApiError("ERR_CLUSTER_MERGED_AWAY")

    if decision in ("CONFIRM", "REJECT"):
        config = repo.get("threshold_configs", link["threshold_config_id"])
        if (
            config is not None
            and config["activated_by_user_id"] is not None
            and actor.user_id == config["activated_by_user_id"]
        ):
            raise ApiError("ERR_SOD_STEWARD_IS_TUNER")

    if decision == "CONFIRM":
        link["status"] = "LINKED"
        link["reviewed_by_user_id"] = actor.user_id
        link["review_note"] = note
        touch(link)
        merge_for_link(link, left_cluster, right_cluster)
    elif decision == "REJECT":
        link["status"] = "REJECTED"
        link["reviewed_by_user_id"] = actor.user_id
        link["review_note"] = note
        touch(link)
        recount_and_bump(left_cluster)
        if right_cluster is not None and right_cluster["id"] != left_cluster["id"]:
            recount_and_bump(right_cluster)
    else:
        link["status"] = "PENDING_REVIEW"
        link["reviewed_by_user_id"] = actor.user_id
        link["review_note"] = note
        touch(link)
        recount_and_bump(left_cluster)
        if right_cluster["id"] != left_cluster["id"]:
            recount_and_bump(right_cluster)
    return entity(link)


@bp.route("/hie/match-links/<link_id>/unlink", methods=["POST"])
def unlink(link_id):
    actor = authenticate((PRIVACY_OFFICER,))
    payload = body()
    expected = req_int(payload, "expected_cluster_version")
    reason = req_str(payload, "unlink_reason")

    link = repo.must("match_links", link_id)
    pinned_cluster = repo.get("clusters", link["cluster_id"])
    if pinned_cluster is not None and expected != int(pinned_cluster["version"]):
        raise ApiError("ERR_STALE_CLUSTER_VERSION")

    if link["status"] == "REJECTED":
        raise ApiError("ERR_TERMINAL_STATE")
    if link["status"] not in ("AUTO_LINKED", "LINKED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    link["status"] = "UNLINKED"
    link["unlink_reason"] = reason
    touch(link)
    unmerge_for_link(link)
    return entity(link)


@bp.route("/hie/patient-records/<record_id>", methods=["GET"])
def read_record(record_id):
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN, PRIVACY_OFFICER))
    return entity(repo.must("patient_records", record_id))


@bp.route("/hie/patient-records", methods=["GET"])
def list_records():
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN, PRIVACY_OFFICER))
    limit, offset = pagination()
    rows = repo.all_rows("patient_records")
    for key in ("participant_id", "cluster_id", "prior_cluster_id", "match_state", "source_mrn"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, limit, offset)


@bp.route("/hie/identity-clusters/<cluster_id>", methods=["GET"])
def read_cluster(cluster_id):
    authenticate((HIE_ADMIN, PRIVACY_OFFICER, CLINICIAN))
    return entity(repo.must("clusters", cluster_id))


@bp.route("/hie/identity-clusters", methods=["GET"])
def list_clusters():
    authenticate((HIE_ADMIN, PRIVACY_OFFICER))
    limit, offset = pagination()
    rows = repo.all_rows("clusters")
    for key in ("primary_record_id", "merged_into_cluster_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, limit, offset)


@bp.route("/hie/match-links/<link_id>", methods=["GET"])
def read_link(link_id):
    authenticate((HIE_ADMIN, PRIVACY_OFFICER))
    return entity(repo.must("match_links", link_id))


@bp.route("/hie/match-links", methods=["GET"])
def list_links():
    authenticate((HIE_ADMIN, PRIVACY_OFFICER))
    limit, offset = pagination()
    rows = repo.all_rows("match_links")
    for key in (
        "left_record_id",
        "right_record_id",
        "threshold_config_id",
        "cluster_id",
        "merged_away_cluster_id",
        "status",
    ):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, limit, offset)
