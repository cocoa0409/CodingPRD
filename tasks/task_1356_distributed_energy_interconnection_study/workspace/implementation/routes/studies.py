"""Study endpoints: scoping, retrieval, publish-results, finalize, cost shares."""
from flask import Blueprint

from db import DB, new_id, next_seq, pub, stamp_new, touch
from errors import ApiError
from middleware import READ_ROLES, auth
from response import ok, ok_list
from services import (INCLUDED_STATUSES, create_cost_share, cost_shares_of_study,
                      maybe_close_cluster, members_of, recompute_cost_shares,
                      study_of_cluster, withdraw_project)
from util import body, pagination_args, req_int

bp = Blueprint("studies", __name__)


def _get_study(study_id):
    study = DB["studies"].get(study_id)
    if study is None:
        raise ApiError("ERR_STUDY_NOT_FOUND", 404, "Study id does not exist")
    return study


@bp.route("/interconnection/cluster-groups/<cluster_id>/studies", methods=["POST"])
def scope_study(cluster_id):
    auth(["StudyEngineer"])
    cluster = DB["cluster_groups"].get(cluster_id)
    if cluster is None:
        raise ApiError("ERR_CLUSTER_GROUP_NOT_FOUND", 404, "ClusterGroup id does not exist")

    # State gate: the cluster must still be FORMING.
    if cluster["status"] != "FORMING":
        raise ApiError(
            "ERR_CLUSTER_NOT_ACCEPTING_PROJECTS", 409,
            "ClusterGroup not in FORMING when scoping a study",
        )
    # At most one Study ever exists per ClusterGroup.
    if study_of_cluster(cluster_id) is not None:
        raise ApiError(
            "ERR_STUDY_ALREADY_EXISTS", 409,
            "A Study already exists for this ClusterGroup",
        )
    members = members_of(cluster_id)
    # Scoping requires at least one READY member.
    if not any(m["status"] == "READY" for m in members):
        raise ApiError(
            "ERR_NO_READY_PROJECTS", 409,
            "Study scoping requires at least one member project in READY",
        )

    data = body()
    total_cost_cents = req_int(data, "total_cost_cents")
    if total_cost_cents <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "total_cost_cents must be greater than 0")

    study = {
        "id": new_id(),
        "_seq": next_seq(),
        "cluster_group_id": cluster_id,
        "total_cost_cents": total_cost_cents,
        "status": "IN_PROGRESS",
        "_basis": "PROVISIONAL",
    }
    stamp_new(study)
    DB["studies"][study["id"]] = study

    # The cluster advances FORMING -> STUDY_UNDERWAY.
    cluster["status"] = "STUDY_UNDERWAY"
    touch(cluster)

    # Readiness enforcement: READY members enter the study; SUBMITTED/QUEUED
    # members are automatically withdrawn (early 10% forfeiture band; the
    # scoping-time cascade suppresses any restudy side effect).
    for member in members:
        if member["status"] == "READY":
            member["status"] = "IN_STUDY"
            touch(member)
    for member in members:
        if member["status"] in ("SUBMITTED", "QUEUED"):
            withdraw_project(member, scoping=True)

    # PROVISIONAL cost shares for the included (IN_STUDY) members.
    for member in members_of(cluster_id):
        if member["status"] in INCLUDED_STATUSES:
            create_cost_share(study, member)
    recompute_cost_shares(study)
    return ok(pub(study), 201)


@bp.route("/interconnection/studies/<study_id>", methods=["GET"])
def get_study(study_id):
    auth(READ_ROLES)
    return ok(pub(_get_study(study_id)))


@bp.route("/interconnection/studies/<study_id>/publish-results", methods=["POST"])
def publish_results(study_id):
    auth(["StudyEngineer"])
    study = _get_study(study_id)

    # State: publication requires IN_PROGRESS.
    if study["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_STUDY_INVALID_STATE", 409,
            "publish-results requires the study to be IN_PROGRESS",
        )

    study["status"] = "RESULTS_PUBLISHED"
    study["_basis"] = "FINAL"
    touch(study)

    # Included members in IN_STUDY or RESTUDY_REQUIRED complete the study.
    for member in members_of(study["cluster_group_id"]):
        if member["status"] in ("IN_STUDY", "RESTUDY_REQUIRED"):
            member["status"] = "STUDY_COMPLETE"
            touch(member)

    # All cost shares recompute under the FINAL basis.
    recompute_cost_shares(study)
    return ok(pub(study), 200)


@bp.route("/interconnection/studies/<study_id>/finalize", methods=["POST"])
def finalize_study(study_id):
    auth(["StudyEngineer"])
    study = _get_study(study_id)

    # State: finalization requires RESULTS_PUBLISHED.
    if study["status"] != "RESULTS_PUBLISHED":
        raise ApiError(
            "ERR_STUDY_INVALID_STATE", 409,
            "finalize requires the study to be RESULTS_PUBLISHED",
        )

    study["status"] = "FINALIZED"
    touch(study)

    # The cluster advances STUDY_UNDERWAY -> STUDY_COMPLETE; cost shares are
    # now locked (later withdrawals neither reopen nor reallocate).
    cluster = DB["cluster_groups"][study["cluster_group_id"]]
    if cluster["status"] == "STUDY_UNDERWAY":
        cluster["status"] = "STUDY_COMPLETE"
        touch(cluster)
    maybe_close_cluster(cluster)
    return ok(pub(study), 200)


@bp.route("/interconnection/studies/<study_id>/cost-shares", methods=["GET"])
def list_study_cost_shares(study_id):
    auth(READ_ROLES)
    _get_study(study_id)
    limit, offset = pagination_args()
    items = cost_shares_of_study(study_id)
    page = items[offset:offset + limit]
    return ok_list([pub(c) for c in page], len(items), limit, offset)
