"""Identity-document verification fork (PRD §3.5)."""

from flask import Blueprint, request

import constants as K
import envelope
import rows
import serializers
import states
from clock import CLOCK
from context import Ctx
from errors import ApiError
from store import DB

bp = Blueprint("documents", __name__)


def _account_of(document):
    member = DB.members.get(document["member_id"])
    return DB.accounts.get(member["account_id"]) if member else None


@bp.post("/identity-documents/<document_id>/verify")
def verify_document(document_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT, K.ROLE_PLATFORM_ADMIN])
    document = ctx.path("document", document_id)
    ctx.write_gates(_account_of(document))
    states.gate("document_status", document["status"], ("PENDING",))
    # Declared transition precondition with no dedicated code: the current
    # instant must be STRICTLY before expires_at.
    if not (CLOCK.now < document["expires_at_dt"]):
        raise ApiError(
            "ERR_INVALID_STATE", "The document has reached its expiry and cannot be verified."
        )
    document["status"] = "VERIFIED"
    document["verified_at"] = CLOCK.now
    rows.touch(document)
    return envelope.ok(serializers.document(document))


@bp.post("/identity-documents/<document_id>/reject")
def reject_document(document_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    document = ctx.path("document", document_id)
    ctx.load_body()
    fields = ctx.validate(
        [{"name": "rejection_reason_code", "type": "string", "required": True}]
    )
    ctx.write_gates(_account_of(document))
    states.gate("document_status", document["status"], ("PENDING",))
    document["status"] = "REJECTED"
    document["rejection_reason_code"] = fields["rejection_reason_code"]
    rows.touch(document)
    return envelope.ok(serializers.document(document))
