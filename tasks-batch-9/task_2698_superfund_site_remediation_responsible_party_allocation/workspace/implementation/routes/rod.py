"""The Record of Decision: community involvement and signature."""

from flask import Blueprint

import calc
import constants as K
import derive
import logical_clock
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from routes import common

bp = Blueprint("rod", __name__)


@bp.post("/sites/<site_id>/records-of-decision")
def create_rod(site_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    ri_id = shape.str_field(body, "remedial_investigation_id")
    summary = shape.str_field(body, "proposed_plan_summary")
    days = shape.int_field(body, "comment_period_days", lo=30, hi=90)
    site = common.get_site(site_id)
    ri = common.get_ri(ri_id)
    if ri["site_id"] != site["id"]:
        raise ApiError("ERR_REMEDIAL_INVESTIGATION_NOT_FOUND")
    common.deny_deleted(site)

    rod = common.new_record(
        {
            "site_id": site["id"],
            "remedial_investigation_id": ri["id"],
            "proposed_plan_summary": summary,
            "comment_period_days": days,
            "status": "DRAFT",
            "comment_period_start": None,
            "comment_period_end": None,
            "public_comments_count": 0,
            "responsiveness_summary": None,
            "selected_alternative_id": None,
            "signed_by_user_id": None,
            "signed_at": None,
        }
    )
    store.records_of_decision[rod["id"]] = rod
    return common.respond(rod, serialize.record_of_decision, 201)


@bp.post("/records-of-decision/<rod_id>/comment-period")
def open_comment_period(rod_id):
    require(K.ROLE_RPM)
    shape.get_body()
    rod = common.get_rod(rod_id)
    site = store.sites[rod["site_id"]]
    common.state(rod["status"] == "DRAFT")
    common.deny_deleted(site)
    ri = store.remedial_investigations[rod["remedial_investigation_id"]]
    if ri["status"] != "APPROVED":
        raise ApiError("ERR_RIFS_NOT_APPROVED")

    start = logical_clock.now()
    txn.watch(rod)
    rod["status"] = "PUBLIC_COMMENT"
    rod["comment_period_start"] = start
    # The window is the closed interval [start, start + comment_period_days].
    rod["comment_period_end"] = logical_clock.plus_days(start, rod["comment_period_days"])
    derive.recompute_site_derived(site)
    return common.respond(rod, serialize.record_of_decision)


@bp.post("/records-of-decision/<rod_id>/public-comments")
def file_comment(rod_id):
    require(K.ROLE_COMMUNITY, K.ROLE_PRP)
    body = shape.get_body()
    shape.str_field(body, "commenter_name")
    shape.str_field(body, "comment_text")
    rod = common.get_rod(rod_id)
    site = store.sites[rod["site_id"]]
    common.deny_deleted(site)
    # Priority 26.  Both a document in the wrong state and a filing past the
    # window report the same closure error; there is no separate state gate.
    if rod["status"] != "PUBLIC_COMMENT":
        raise ApiError("ERR_COMMENT_PERIOD_CLOSED")
    if logical_clock.now() > rod["comment_period_end"]:
        raise ApiError("ERR_COMMENT_PERIOD_CLOSED")

    txn.watch(rod)
    rod["public_comments_count"] += 1
    return common.respond(rod, serialize.record_of_decision)


@bp.post("/records-of-decision/<rod_id>/signature")
def sign_rod(rod_id):
    actor = require(K.ROLE_RPM)
    body = shape.get_body()
    summary = shape.str_field(body, "responsiveness_summary")
    alternative_id = shape.str_field(body, "alternative_id", required=False)
    rod = common.get_rod(rod_id)
    explicit = common.get_alternative(alternative_id) if alternative_id else None
    site = store.sites[rod["site_id"]]
    common.state(rod["status"] == "PUBLIC_COMMENT")
    common.deny_deleted(site)
    ri = store.remedial_investigations[rod["remedial_investigation_id"]]

    if actor.user_id == ri["approved_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if rod["public_comments_count"] < 1:
        raise ApiError("ERR_COMMUNITY_INVOLVEMENT_INCOMPLETE")
    if explicit is not None and ri["action_level_exceeded"]:
        if explicit["effectiveness_score"] < K.PROTECTIVE_EFFECTIVENESS_MIN:
            raise ApiError("ERR_REMEDY_NOT_PROTECTIVE")
    if explicit is not None and explicit["remedial_investigation_id"] != ri["id"]:
        raise ApiError("ERR_ALTERNATIVE_NOT_FOR_SITE")
    if logical_clock.now() <= rod["comment_period_end"]:
        raise ApiError("ERR_COMMENT_PERIOD_OPEN")

    winner = explicit
    if winner is None:
        winner = calc.remedy_selector(
            derive.ri_alternatives(ri["id"]), ri["action_level_exceeded"]
        )
        if winner is None:
            raise ApiError("ERR_NO_ELIGIBLE_REMEDY")

    # The authoritative link lives on the alternative; the document mirrors it.
    txn.watch(winner)
    winner["selected_by_rod_id"] = rod["id"]
    txn.watch(rod)
    rod["selected_alternative_id"] = winner["id"]
    rod["status"] = "SIGNED"
    rod["signed_by_user_id"] = actor.user_id
    rod["signed_at"] = logical_clock.now()
    rod["responsiveness_summary"] = summary

    amended = site["listing_status"] == "REMEDY_REEVALUATION"
    if site["listing_status"] in ("RI_FS_UNDERWAY", "REMEDY_REEVALUATION"):
        txn.watch(site)
        site["listing_status"] = "ROD_SIGNED"
    if amended:
        derive.withdraw_amendment_required(site)
    derive.recompute_site_derived(site)
    return common.respond(rod, serialize.record_of_decision)
