"""/foia/third-party-notices — Reverse-FOIA notice lifecycle."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_FK_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOTICE_ALREADY_CLOSED,
    ERR_THIRD_PARTY_DEADLINE_PASSED,
)
from ..serializers import serialize_third_party_notice
from ..store import append_audit, store
from ..timeutil import add_business_days, clock, iso_now, parse_iso
from ..util import require_json_body, require_str


third_party_notices_bp = Blueprint("third_party_notices", __name__)

THIRD_PARTY_DAYS = 10


def _get_notice(nid: str) -> dict:
    notice = store.third_party_notices.get(nid)
    if notice is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Third-party notice not found.")
    return notice


@third_party_notices_bp.post("/foia/third-party-notices")
@require_auth({"Officer"})
def create_notice():
    payload = require_json_body()
    request_id = require_str(payload, "request_id", max_len=200)
    record_id = require_str(payload, "record_id", max_len=200)

    req = store.requests.get(request_id)
    if req is None:
        raise ApiError(ERR_FK_NOT_FOUND, 404, "Referenced request does not exist.")
    rec = store.responsive_records.get(record_id)
    if rec is None:
        raise ApiError(ERR_FK_NOT_FOUND, 404, "Referenced record does not exist.")
    if rec["request_id"] != request_id:
        raise ApiError(ERR_INVALID_INPUT, 400, "Record does not belong to this request.")
    if not rec.get("contains_third_party_info"):
        raise ApiError(
            ERR_INVALID_INPUT,
            400,
            "Cannot notify a third party on a record that has no third-party info.",
        )
    if not rec.get("third_party_id"):
        raise ApiError(
            ERR_INVALID_INPUT,
            400,
            "Record is missing third_party_id.",
        )

    now = clock.now()
    deadline_iso = iso_now(add_business_days(now, THIRD_PARTY_DAYS))
    entity = {
        "request_id": request_id,
        "record_id": record_id,
        "third_party_id": rec["third_party_id"],
        "status": "PENDING_RESPONSE",
        "response_deadline": deadline_iso,
        "objection_grounds": None,
    }
    with store.lock:
        store.stamp_create(entity)
        store.third_party_notices[entity["id"]] = entity
        append_audit(
            subject_type="THIRD_PARTY_NOTICE",
            subject_id=entity["id"],
            event_code="THIRD_PARTY_NOTIFIED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={
                "request_id": request_id,
                "record_id": record_id,
                "third_party_id": entity["third_party_id"],
                "response_deadline": deadline_iso,
            },
        )
    return ok_object(serialize_third_party_notice(entity), status=201)


def _deadline_passed(notice: dict) -> bool:
    deadline = notice.get("response_deadline")
    if not deadline:
        return False
    return clock.now() >= parse_iso(deadline)


@third_party_notices_bp.post("/foia/third-party-notices/<nid>/consent")
@require_auth({"ThirdParty"})
def consent(nid: str):
    notice = _get_notice(nid)
    with store.lock:
        if g.user_id != notice["third_party_id"]:
            raise ApiError(ERR_FORBIDDEN, 403, "Caller is not the noticed third party.")
        if notice["status"] != "PENDING_RESPONSE":
            raise ApiError(ERR_NOTICE_ALREADY_CLOSED, 409, "Notice already closed.")
        if _deadline_passed(notice):
            raise ApiError(
                ERR_THIRD_PARTY_DEADLINE_PASSED,
                422,
                "Third-party deadline has passed.",
            )
        notice["status"] = "CONSENTED"
        store.bump(notice)
        append_audit(
            subject_type="THIRD_PARTY_NOTICE",
            subject_id=notice["id"],
            event_code="THIRD_PARTY_RESPONDED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"outcome": "CONSENT"},
        )
    return ok_object(serialize_third_party_notice(notice))


@third_party_notices_bp.post("/foia/third-party-notices/<nid>/object")
@require_auth({"ThirdParty"})
def object_notice(nid: str):
    notice = _get_notice(nid)
    payload = require_json_body()
    grounds = require_str(payload, "objection_grounds", max_len=4000)
    with store.lock:
        if g.user_id != notice["third_party_id"]:
            raise ApiError(ERR_FORBIDDEN, 403, "Caller is not the noticed third party.")
        if notice["status"] != "PENDING_RESPONSE":
            raise ApiError(ERR_NOTICE_ALREADY_CLOSED, 409, "Notice already closed.")
        if _deadline_passed(notice):
            raise ApiError(
                ERR_THIRD_PARTY_DEADLINE_PASSED,
                422,
                "Third-party deadline has passed.",
            )
        notice["status"] = "OBJECTED"
        notice["objection_grounds"] = grounds
        store.bump(notice)
        append_audit(
            subject_type="THIRD_PARTY_NOTICE",
            subject_id=notice["id"],
            event_code="THIRD_PARTY_RESPONDED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"outcome": "OBJECT", "objection_grounds": grounds},
        )
    return ok_object(serialize_third_party_notice(notice))


@third_party_notices_bp.post("/foia/third-party-notices/<nid>/override")
@require_auth({"AppealAuthority"})
def override(nid: str):
    notice = _get_notice(nid)
    with store.lock:
        if notice["status"] not in ("PENDING_RESPONSE", "OBJECTED"):
            raise ApiError(ERR_INVALID_STATE, 409, "Notice cannot be overridden.")
        # Need a reverse-FOIA appeal on this notice's record that resolves
        # against the third party.  We scan appeals on the parent request.
        record_id = notice["record_id"]
        related_appeals = [
            a
            for a in store.appeals.values()
            if a["request_id"] == notice["request_id"]
            and a["appellant_role"] == "THIRD_PARTY"
        ]
        # From PENDING_RESPONSE: DISMISSED or UPHELD against third party.
        # From OBJECTED:        UPHELD against third party only.
        if notice["status"] == "PENDING_RESPONSE":
            ok = any(a["status"] in ("DISMISSED", "UPHELD") for a in related_appeals)
        else:  # OBJECTED
            ok = any(a["status"] == "UPHELD" for a in related_appeals)
        if not ok:
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Override requires a resolved Reverse-FOIA appeal against the third party.",
            )

        notice["status"] = "OVERRIDDEN"
        store.bump(notice)
        append_audit(
            subject_type="THIRD_PARTY_NOTICE",
            subject_id=notice["id"],
            event_code="THIRD_PARTY_RESPONDED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"outcome": "OVERRIDDEN"},
        )
    return ok_object(serialize_third_party_notice(notice))


@third_party_notices_bp.get("/foia/third-party-notices/<nid>")
@require_auth({"Officer", "AppealAuthority", "ThirdParty"})
def get_notice(nid: str):
    notice = _get_notice(nid)
    return ok_object(serialize_third_party_notice(notice))
