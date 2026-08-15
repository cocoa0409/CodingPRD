"""Waiver request endpoints (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import stamp_new, bump, now_iso, parse_ts
from errors import (
    ApiError, invalid, forbidden, not_found,
    ERR_NOT_RESPONSIBLE_ATTORNEY, ERR_SOD_SELF_APPROVAL,
    ERR_WAIVER_INVALID_STATE, ERR_WAIVER_ACTIVE_EXISTS,
    ERR_CHECK_SUPERSEDED, ERR_HIT_NOT_CONFIRMED,
)
from middleware import caller, admit, admit_action, body
from response import ok_object, paginate, sort_by_created
from services.cascades import waiver_approved, waiver_revoked
from services.validate import resolve

bp = Blueprint("waivers", __name__)

WAIVER_READERS = ("ResponsibleAttorney", "ConflictsPartner", "FirmAdmin")
ACTIVE_WAIVER_STATUSES = ("DRAFT", "SENT", "CONSENTED", "APPROVED")
WAIVER_EXPIRY_DAYS = 30


def _waiver_matter(waiver):
    return db.store.matters.get(waiver["matter_id"])


@bp.post("/intake/matters/<mid>/waiver-requests")
def create_waiver(mid):
    user_id, role = caller()
    admit(role, ("ResponsibleAttorney",))
    matter = resolve(db.store.matters, mid)
    data = body()

    # Tier 3: hit FK resolution.
    conflict_hit_id = data.get("conflict_hit_id")
    hit = resolve(db.store.conflict_hits, conflict_hit_id) \
        if conflict_hit_id is not None else None

    # Tier 5 ownership: caller must be the matter's responsible attorney.
    if user_id != matter["responsible_attorney_id"]:
        raise ApiError(ERR_NOT_RESPONSIBLE_ATTORNEY, 403,
                       "Only the matter's responsible attorney may draft a "
                       "waiver")

    # Tier 9 referential: producing check must not be SUPERSEDED; the hit
    # must be CONFIRMED.
    if hit is not None:
        check = db.store.conflict_checks.get(hit["check_id"])
        if check is not None and check["status"] == "SUPERSEDED":
            raise ApiError(ERR_CHECK_SUPERSEDED, 409,
                           "The hit's conflict check has been superseded")
        if hit["review_status"] != "CONFIRMED":
            raise ApiError(ERR_HIT_NOT_CONFIRMED, 422,
                           "Waiver requires a CONFIRMED hit")

    # Tier 10: at most one ACTIVE waiver per hit.
    if hit is not None:
        for w in db.store.waiver_requests.values():
            if (w["conflict_hit_id"] == hit["id"]
                    and w["status"] in ACTIVE_WAIVER_STATUSES):
                raise ApiError(ERR_WAIVER_ACTIVE_EXISTS, 409,
                               "An active waiver already exists for this hit")

    # Tier 12: request shape.
    if hit is None:
        raise invalid("conflict_hit_id is required")
    proposed_terms = data.get("proposed_terms")
    if not isinstance(proposed_terms, str) or proposed_terms == "":
        raise invalid("proposed_terms is required")

    waiver = stamp_new({
        "matter_id": matter["id"],
        "conflict_hit_id": hit["id"],
        "requested_by_attorney_id": user_id,
        "proposed_terms": proposed_terms,
        "status": "DRAFT",
        "sent_at": None,
        "expires_at": None,
        "consent_document_ref": None,
        "decline_reason": "",
        "approved_by_attorney_id": None,
    })
    db.store.waiver_requests[waiver["id"]] = waiver
    return ok_object(waiver, 201)


@bp.get("/intake/matters/<mid>/waiver-requests")
def list_matter_waivers(mid):
    _, role = caller()
    admit(role, WAIVER_READERS)
    resolve(db.store.matters, mid)
    rows = [w for w in db.store.waiver_requests.values()
            if w["matter_id"] == mid]
    return paginate(sort_by_created(rows), request.args)


@bp.post("/intake/waiver-requests/<wid>/transition")
def waiver_transition(wid):
    user_id, role = caller()
    admit(role, ("ResponsibleAttorney", "ConflictsPartner", "Client"))
    data = body()
    action = data.get("action")

    # Tier 2 per-action role rules.
    if action in ("SEND", "REDRAFT"):
        admit_action(role, ("ResponsibleAttorney",))
    elif action in ("RECORD_CONSENT", "DECLINE"):
        admit_action(role, ("Client",))
    elif action == "APPROVE":
        admit_action(role, ("ConflictsPartner",))
    elif action == "REVOKE":
        admit_action(role, ("Client", "ConflictsPartner"))

    # Tier 3: path resolution.
    waiver = resolve(db.store.waiver_requests, wid)
    matter = _waiver_matter(waiver)
    hit = db.store.conflict_hits.get(waiver["conflict_hit_id"])

    if action == "SEND":
        # Tier 5 ownership: only the requester sends.
        if user_id != waiver["requested_by_attorney_id"]:
            raise ApiError(ERR_NOT_RESPONSIBLE_ATTORNEY, 403,
                           "Only the waiver requester may send it")
        # Tier 6 state.
        if waiver["status"] != "DRAFT":
            raise ApiError(ERR_WAIVER_INVALID_STATE, 409,
                           "SEND requires a DRAFT waiver")
        # Tier 9 referential: the hit must still be CONFIRMED.
        if hit is None or hit["review_status"] != "CONFIRMED":
            raise ApiError(ERR_HIT_NOT_CONFIRMED, 422,
                           "SEND requires the referenced hit to be CONFIRMED")
        waiver["status"] = "SENT"
        waiver["sent_at"] = now_iso()
        waiver["expires_at"] = db.format_ts(
            parse_ts(waiver["sent_at"]) + timedelta(days=WAIVER_EXPIRY_DAYS))
        bump(waiver)
        return ok_object(waiver)

    if action == "RECORD_CONSENT":
        # Tier 5 ownership: caller must be the matter's client party.
        if matter is None or user_id != matter["client_party_id"]:
            raise forbidden("Only the matter's client may record consent")
        # Tier 6 state (an EXPIRED-swept waiver fails here).
        if waiver["status"] != "SENT":
            raise ApiError(ERR_WAIVER_INVALID_STATE, 409,
                           "RECORD_CONSENT requires a SENT waiver")
        # Tier 12 shape: consent_document_ref is required.
        ref = data.get("consent_document_ref")
        if not isinstance(ref, str) or ref == "":
            raise invalid("consent_document_ref is required")
        waiver["status"] = "CONSENTED"
        waiver["consent_document_ref"] = ref
        bump(waiver)
        return ok_object(waiver)

    if action == "DECLINE":
        if matter is None or user_id != matter["client_party_id"]:
            raise forbidden("Only the matter's client may decline a waiver")
        if waiver["status"] != "SENT":
            raise ApiError(ERR_WAIVER_INVALID_STATE, 409,
                           "DECLINE requires a SENT waiver")
        reason = data.get("decline_reason")
        if reason is not None and not isinstance(reason, str):
            raise invalid("decline_reason must be a string")
        waiver["status"] = "DECLINED"
        waiver["decline_reason"] = reason if reason is not None else ""
        bump(waiver)
        return ok_object(waiver)

    if action == "APPROVE":
        # Tier 6 state.
        if waiver["status"] != "CONSENTED":
            raise ApiError(ERR_WAIVER_INVALID_STATE, 409,
                           "APPROVE requires a CONSENTED waiver")
        # Tier 7 segregation of duties: approver != requester.
        if user_id == waiver["requested_by_attorney_id"]:
            raise ApiError(ERR_SOD_SELF_APPROVAL, 403,
                           "The waiver requester cannot approve it")
        waiver["status"] = "APPROVED"
        waiver["approved_by_attorney_id"] = user_id
        bump(waiver)
        waiver_approved(waiver)
        return ok_object(waiver)

    if action == "REVOKE":
        # Tier 5 ownership: a Client caller must own the matter.
        if role == "Client" and (matter is None
                                 or user_id != matter["client_party_id"]):
            raise forbidden("Only the matter's client may revoke its waiver")
        # Tier 6 state.
        if waiver["status"] not in ("CONSENTED", "APPROVED"):
            raise ApiError(ERR_WAIVER_INVALID_STATE, 409,
                           "REVOKE requires a CONSENTED or APPROVED waiver")
        prior_status = waiver["status"]
        waiver["status"] = "REVOKED"
        bump(waiver)
        waiver_revoked(waiver, prior_status)
        return ok_object(waiver)

    if action == "REDRAFT":
        # Tier 5 ownership: only the original requester redrafts.
        if user_id != waiver["requested_by_attorney_id"]:
            raise ApiError(ERR_NOT_RESPONSIBLE_ATTORNEY, 403,
                           "Only the waiver requester may redraft it")
        # Tier 6 state.
        if waiver["status"] not in ("DECLINED", "REVOKED", "EXPIRED"):
            raise ApiError(ERR_WAIVER_INVALID_STATE, 409,
                           "REDRAFT requires a DECLINED, REVOKED, or EXPIRED "
                           "waiver")
        # Shape check before any mutation (atomicity).
        terms = data.get("proposed_terms")
        if terms is not None and not isinstance(terms, str):
            raise invalid("proposed_terms must be a string")
        waiver["status"] = "DRAFT"
        waiver["sent_at"] = None
        waiver["expires_at"] = None
        waiver["consent_document_ref"] = None
        waiver["decline_reason"] = ""
        waiver["approved_by_attorney_id"] = None
        if terms is not None:
            waiver["proposed_terms"] = terms
        bump(waiver)
        return ok_object(waiver)

    raise invalid("action must be SEND, RECORD_CONSENT, DECLINE, APPROVE, "
                  "REVOKE, or REDRAFT")
