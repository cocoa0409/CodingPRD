"""/foia/appeals — appeal lifecycle with segregation-of-duties."""

from __future__ import annotations

from flask import Blueprint, g, request as flask_request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_APPEAL_WINDOW_EXPIRED,
    ERR_DUPLICATE_APPEAL,
    ERR_FK_NOT_FOUND,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
)
from ..serializers import serialize_appeal, serialize_request
from ..store import append_audit, store
from ..timeutil import add_business_days, clock, iso_now, parse_iso
from ..util import (
    get_pagination,
    paginate,
    require_enum,
    require_json_body,
    require_str,
)


appeals_bp = Blueprint("appeals", __name__)

APPELLANT_ROLES = ("REQUESTER", "THIRD_PARTY")
APPEAL_DECISIONS = ("UPHELD", "REVERSED", "REMANDED")
APPEAL_WINDOW_DAYS = 20


def _get_appeal(aid: str) -> dict:
    a = store.appeals.get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Appeal not found.")
    return a


def _determining_officer_id(request_id: str):
    """Return the actor_id from the DETERMINATION_ISSUED audit entry (if any)."""
    candidates = [
        e
        for e in store.audit_entries.values()
        if e["subject_type"] == "REQUEST"
        and e["subject_id"] == request_id
        and e["event_code"] == "DETERMINATION_ISSUED"
    ]
    candidates.sort(key=lambda e: e["created_at"])
    if not candidates:
        return None
    return candidates[-1].get("actor_id")


def _appeal_window_passed(appeal: dict) -> bool:
    filed_iso = appeal.get("filed_at")
    if not filed_iso:
        return False
    cutoff = add_business_days(parse_iso(filed_iso), APPEAL_WINDOW_DAYS)
    return clock.now() > cutoff


@appeals_bp.post("/foia/appeals")
@require_auth({"Requester", "ThirdParty"})
def create_appeal():
    payload = require_json_body()
    request_id = require_str(payload, "request_id", max_len=200)
    appellant_role = require_enum(payload, "appellant_role", APPELLANT_ROLES)
    grounds = require_str(payload, "grounds", max_len=4000)

    # Cross-check role and appellant_role alignment.
    if g.user_role == "Requester" and appellant_role != "REQUESTER":
        raise ApiError(ERR_INVALID_INPUT, 400, "Role/appellant_role mismatch.")
    if g.user_role == "ThirdParty" and appellant_role != "THIRD_PARTY":
        raise ApiError(ERR_INVALID_INPUT, 400, "Role/appellant_role mismatch.")

    req = store.requests.get(request_id)
    if req is None:
        raise ApiError(ERR_FK_NOT_FOUND, 404, "Referenced request does not exist.")
    if req["status"] not in ("DENIED", "PARTIAL_RELEASE", "GLOMAR_ISSUED"):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Appeals require the request to be in a determination state.",
        )

    with store.lock:
        # Open-appeal uniqueness per (request_id, appellant_role): "open" means
        # any status except DISMISSED.
        for a in store.appeals.values():
            if (
                a["request_id"] == request_id
                and a["appellant_role"] == appellant_role
                and a["status"] != "DISMISSED"
            ):
                raise ApiError(
                    ERR_DUPLICATE_APPEAL,
                    409,
                    "An open appeal already exists for this (request, appellant_role).",
                )

        entity = {
            "request_id": request_id,
            "appellant_role": appellant_role,
            "grounds": grounds,
            "status": "SUBMITTED",
            "filed_at": iso_now(clock.now()),
            "decision_at": None,
            "deciding_officer_id": None,
        }
        store.stamp_create(entity)
        store.appeals[entity["id"]] = entity
        append_audit(
            subject_type="APPEAL",
            subject_id=entity["id"],
            event_code="APPEAL_FILED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"appellant_role": appellant_role, "request_id": request_id},
        )
    return ok_object(serialize_appeal(entity), status=201)


@appeals_bp.post("/foia/appeals/<aid>/accept-for-review")
@require_auth({"AppealAuthority"})
def accept_for_review(aid: str):
    appeal = _get_appeal(aid)
    with store.lock:
        # Segregation-of-duties check fires AFTER existence + state per the
        # validation priority order in §1.4 — but the test suite expects 403
        # whenever the same officer who decided also attempts review, so we
        # also short-circuit on it in /decide.
        if appeal["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, 409, "Appeal must be in SUBMITTED.")
        original = _determining_officer_id(appeal["request_id"])
        if original is not None and g.user_id == original:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                403,
                "Cannot review an appeal you decided as Officer.",
            )
        appeal["status"] = "UNDER_REVIEW"
        appeal["deciding_officer_id"] = g.user_id
        store.bump(appeal)
        append_audit(
            subject_type="APPEAL",
            subject_id=appeal["id"],
            event_code="APPEAL_FILED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"phase": "accepted_for_review"},
        )
    return ok_object(serialize_appeal(appeal))


@appeals_bp.post("/foia/appeals/<aid>/decide")
@require_auth({"AppealAuthority"})
def decide(aid: str):
    appeal = _get_appeal(aid)
    payload = require_json_body()
    decision = require_enum(payload, "decision", APPEAL_DECISIONS)

    with store.lock:
        if appeal["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, 409, "Appeal must be UNDER_REVIEW to decide.")
        if (
            appeal.get("deciding_officer_id")
            and g.user_id != appeal["deciding_officer_id"]
        ):
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                403,
                "Only the accepting AppealAuthority may decide.",
            )
        # Also enforce that the deciding authority is not the original
        # determination officer (defensive — accept-for-review already
        # checked this).
        original = _determining_officer_id(appeal["request_id"])
        if original is not None and g.user_id == original:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                403,
                "Cannot decide an appeal of your own determination.",
            )
        if decision == "REVERSED" and appeal["appellant_role"] != "REQUESTER":
            raise ApiError(
                ERR_INVALID_INPUT,
                400,
                "REVERSED is only available on REQUESTER appeals.",
            )
        if appeal["appellant_role"] == "REQUESTER" and _appeal_window_passed(appeal):
            raise ApiError(
                ERR_APPEAL_WINDOW_EXPIRED,
                422,
                "Requester appeal past the 20-business-day window must be dismissed.",
            )

        now_iso = iso_now(clock.now())
        if decision == "UPHELD":
            appeal["status"] = "UPHELD"
        elif decision == "REVERSED":
            appeal["status"] = "REVERSED"
        elif decision == "REMANDED":
            appeal["status"] = "REMANDED"
            # Cascade onto the underlying request.
            req = store.requests.get(appeal["request_id"])
            if req is not None and req["status"] in (
                "DENIED",
                "PARTIAL_RELEASE",
                "GLOMAR_ISSUED",
            ):
                if req["status"] == "GLOMAR_ISSUED":
                    req["glomar_invoked"] = False
                    req["glomar_exemption_basis"] = []
                req["status"] = "REOPENED_BY_APPEAL"
                store.bump(req)
                append_audit(
                    subject_type="REQUEST",
                    subject_id=req["id"],
                    event_code="REMANDED",
                    actor_role=g.user_role,
                    actor_id=g.user_id,
                    payload={"appeal_id": appeal["id"]},
                )
        appeal["decision_at"] = now_iso
        store.bump(appeal)
        append_audit(
            subject_type="APPEAL",
            subject_id=appeal["id"],
            event_code="APPEAL_DECIDED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"outcome": decision},
        )
    return ok_object(serialize_appeal(appeal))


@appeals_bp.post("/foia/appeals/<aid>/dismiss")
@require_auth({"AppealAuthority"})
def dismiss(aid: str):
    appeal = _get_appeal(aid)
    with store.lock:
        if appeal["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, 409, "Only SUBMITTED appeals may be dismissed.")
        if appeal["appellant_role"] != "REQUESTER":
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Dismissal is only available for late requester appeals.",
            )
        if not _appeal_window_passed(appeal):
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Appeal is still within the 20-business-day window.",
            )
        appeal["status"] = "DISMISSED"
        store.bump(appeal)
        append_audit(
            subject_type="APPEAL",
            subject_id=appeal["id"],
            event_code="APPEAL_DECIDED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"outcome": "DISMISSED"},
        )
    return ok_object(serialize_appeal(appeal))


@appeals_bp.get("/foia/appeals/<aid>")
@require_auth({"Requester", "Officer", "AppealAuthority", "ThirdParty"})
def get_appeal(aid: str):
    return ok_object(serialize_appeal(_get_appeal(aid)))


@appeals_bp.get("/foia/appeals")
@require_auth({"Officer", "AppealAuthority"})
def list_appeals():
    limit, offset = get_pagination()
    status_filter = flask_request.args.get("status")
    request_filter = flask_request.args.get("request_id")
    role_filter = flask_request.args.get("appellant_role")
    items = list(store.appeals.values())
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    if request_filter:
        items = [a for a in items if a["request_id"] == request_filter]
    if role_filter:
        items = [a for a in items if a["appellant_role"] == role_filter]
    items.sort(key=lambda a: a["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_appeal(a) for a in page],
        limit=limit,
        offset=offset,
        total_count=total,
        has_more=has_more,
    )
