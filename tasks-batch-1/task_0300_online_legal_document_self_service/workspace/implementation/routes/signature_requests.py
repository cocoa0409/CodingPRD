"""SignatureRequest routes: create envelope, send/void transitions, and sign
(compound completion bubbles project to SIGNED + schedules UpdateReminder)."""

from datetime import timedelta

from flask import Blueprint, request

import constants
import errors
import validators
from common import (
    base_entity,
    get_or_404,
    list_collection,
    parse_datetime,
    serialize,
    touch,
)
from db import now_iso, store
from middleware import get_json_body, parse_pagination, roles
from response import array_response, object_response

bp = Blueprint("signature_requests", __name__)


@bp.route("/legal/signature-requests", methods=["POST"])
@roles("Customer")
def create_signature_request():
    body = get_json_body()
    revision_id = validators.require_string(body, "document_revision_id")
    signer_emails = validators.require_string_array(body, "signer_emails", non_empty=True)
    notary_required = validators.optional_bool(body, "notary_required", default=False)

    # Existence (404).
    revision = store.document_revisions.get(revision_id)
    if revision is None:
        raise errors.not_found("document_revision_id does not exist")

    ent = base_entity()
    ent.update({
        "document_revision_id": revision_id,
        "signer_emails": list(signer_emails),
        "notary_required": notary_required,
        "signed_emails": [],
        "signed_count": 0,
        "status": "DRAFT",
    })
    store.signature_requests[ent["id"]] = ent
    return object_response(serialize(ent), 201)


@bp.route("/legal/signature-requests/<sid>", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_signature_request(sid):
    ent = get_or_404(store.signature_requests, sid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/signature-requests", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def list_signature_requests():
    limit, offset = parse_pagination()
    revision_id = request.args.get("document_revision_id")

    def predicate(e):
        if revision_id is not None and e["document_revision_id"] != revision_id:
            return False
        return True

    page, total = list_collection(store.signature_requests, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)


@bp.route("/legal/signature-requests/<sid>/transition", methods=["POST"])
@roles("Customer")
def transition_signature_request(sid):
    sr = get_or_404(store.signature_requests, sid)
    body = get_json_body()
    to_status = validators.require_enum(body, "to_status", {"SENT", "VOIDED"})

    current = sr["status"]

    if to_status == "SENT":
        if current != "DRAFT":
            raise errors.invalid_state("SENT requires DRAFT")
        revision = store.document_revisions.get(sr["document_revision_id"])
        # Revision must still be FINAL.
        if revision is None or revision["status"] != "FINAL":
            raise errors.ApiError(errors.ERR_REVISION_SUPERSEDED, 409,
                                  "Referenced revision is superseded")
        # Owning project must be FINALIZED.
        project = store.document_projects.get(revision["document_project_id"]) if revision else None
        if project is None or project["status"] != "FINALIZED":
            raise errors.ApiError(errors.ERR_PROJECT_NOT_FINALIZED, 409,
                                  "Owning project is not FINALIZED")
        sr["status"] = "SENT"
        touch(sr)

    elif to_status == "VOIDED":
        if current not in ("DRAFT", "SENT", "PARTIALLY_SIGNED"):
            raise errors.invalid_state("VOIDED requires DRAFT, SENT, or PARTIALLY_SIGNED")
        sr["status"] = "VOIDED"
        touch(sr)

    return object_response(serialize(sr), 200)


@bp.route("/legal/signature-requests/<sid>/sign", methods=["POST"])
@roles("Customer")
def sign(sid):
    sr = get_or_404(store.signature_requests, sid)
    body = get_json_body()
    signer_email = validators.require_string(body, "signer_email")

    # State: only SENT or PARTIALLY_SIGNED accept signatures.
    if sr["status"] not in ("SENT", "PARTIALLY_SIGNED"):
        raise errors.invalid_state("Sign requires status SENT or PARTIALLY_SIGNED")

    # Signer must be invited (409) before the already-signed check (PRD §3.7).
    if signer_email not in sr["signer_emails"]:
        raise errors.ApiError(errors.ERR_SIGNER_NOT_INVITED, 409,
                              "Signer email is not invited")
    if signer_email in sr["signed_emails"]:
        raise errors.ApiError(errors.ERR_ALREADY_SIGNED, 409,
                              "Signer has already signed this envelope")

    sr["signed_emails"].append(signer_email)
    sr["signed_count"] = len(sr["signed_emails"])

    if sr["signed_count"] >= len(sr["signer_emails"]):
        # Final outstanding signer -> COMPLETED (compound bubble-up).
        sr["status"] = "COMPLETED"
        touch(sr)
        _bubble_complete(sr)
    else:
        sr["status"] = "PARTIALLY_SIGNED"
        touch(sr)

    return object_response(serialize(sr), 200)


def _bubble_complete(sr):
    """Hop B: owning DocumentProject FINALIZED -> SIGNED; schedule UpdateReminder
    (hop C) with due_at = now + REMINDER_INTERVAL_DAYS."""
    revision = store.document_revisions.get(sr["document_revision_id"])
    if revision is None:
        return
    project = store.document_projects.get(revision["document_project_id"])
    if project is None or project["status"] != "FINALIZED":
        return

    project["status"] = "SIGNED"
    touch(project)

    # due_at = signing time + interval. Signing "time" is the current logical
    # clock if set, otherwise wall clock (created_at semantics).
    base_dt = _current_clock_dt()
    due = base_dt + timedelta(days=constants.REMINDER_INTERVAL_DAYS)
    due_iso = due.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due.microsecond // 1000:03d}Z"

    reminder = base_entity()
    reminder.update({
        "document_project_id": project["id"],
        "due_at": due_iso,
        "status": "SCHEDULED",
    })
    store.update_reminders[reminder["id"]] = reminder


def _current_clock_dt():
    if store.clock_now is not None:
        return parse_datetime(store.clock_now, "clock")
    # Fall back to wall clock.
    return parse_datetime(now_iso(), "now")
