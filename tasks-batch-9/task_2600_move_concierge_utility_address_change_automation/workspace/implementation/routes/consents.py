"""Consent records: capture with supersede under optimistic concurrency, plus
revocation and its suspension cascade."""

from flask import Blueprint

import db
import response
import validators as v
from middleware import (
    COMPLIANCE_OFFICER,
    MOVE_OPS_AGENT,
    RESIDENT,
    authenticate,
)
from services import cascades, enums, gates
from services.lookup import (
    consent_or_404,
    consents_of_resident,
    ref_move,
    resident_or_404,
)
from errors import ApiError

bp = Blueprint("consents", __name__)


@bp.post("/residents/<resident_id>/consent-records")
def create_consent(resident_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, RESIDENT)
    resident = resident_or_404(resident_id)
    body = v.body()

    # rung 4: the optional move reference resolves before rung 5 and rung 6.
    move = ref_move(v.id_field(body, "move_id", required=False))

    # rung 5: a Resident may only record consent for itself.
    caller.own_if(RESIDENT, resident["id"])

    # rung 6: shape.
    scope = v.enum_field(body, "scope", enums.CONSENT_SCOPES)
    source_channel = v.enum_field(body, "source_channel", enums.SOURCE_CHANNELS)
    text_version = v.str_field(body, "consent_text_version", min_len=1, max_len=16)
    expected = v.int_field(body, "expected_resident_version")
    expires_text, expires_at = v.ts_field(body, "expires_at", required=False, default=None)
    if expires_at is not None and expires_at <= db.now():
        v.bad("Field 'expires_at' must be strictly after the current time.")
    if move is not None and move["resident_id"] != resident["id"]:
        v.bad("Field 'move_id' must name a move of this resident.")

    # rung 14: optimistic concurrency on the resident row.
    gates.check_resident_version(resident, expected)

    # A newer grant supersedes the resident's prior grant for the same scope.
    for prior in consents_of_resident(resident["id"]):
        if prior["scope"] == scope and prior["state"] == "GRANTED":
            prior["state"] = "SUPERSEDED"
            db.touch(prior)

    rec = db.base_record()
    rec.update(
        {
            "resident_id": resident["id"],
            "move_id": move["id"] if move is not None else None,
            "scope": scope,
            "source_channel": source_channel,
            "consent_text_version": text_version,
            "state": "GRANTED",
            "granted_at": db.now_iso(),
            "expires_at": expires_text,
            "revoked_at": None,
            "revocation_reason": None,
        }
    )
    db.db.consents[rec["id"]] = rec

    db.touch(resident)
    cascades.apply_consent_restoration(resident, scope)
    return response.created(db.public(rec))


@bp.get("/consent-records/<consent_id>")
def read_consent(consent_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, RESIDENT)
    rec = consent_or_404(consent_id)
    caller.own_if(RESIDENT, rec["resident_id"])
    return response.ok(db.public(rec))


@bp.get("/consent-records")
def list_consents():
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    rows = response.match_filters(
        db.db.consents.values(),
        {
            "resident_id": "resident_id",
            "move_id": "move_id",
            "scope": "scope",
            "state": "state",
            "source_channel": "source_channel",
        },
    )
    return response.paginated(rows)


@bp.post("/consent-records/<consent_id>/revocation")
def revoke_consent(consent_id):
    caller = authenticate(COMPLIANCE_OFFICER, RESIDENT)
    rec = consent_or_404(consent_id)
    caller.own_if(RESIDENT, rec["resident_id"])
    body = v.body()
    reason = v.str_field(
        body, "revocation_reason", required=False, min_len=1, max_len=500, default=None
    )

    # rung 11: only a GRANTED consent may be revoked.
    if rec["state"] != "GRANTED":
        raise ApiError(
            "ERR_CONSENT_ALREADY_TERMINAL",
            "This consent record is no longer in state GRANTED.",
        )

    rec["state"] = "REVOKED"
    rec["revoked_at"] = db.now_iso()
    rec["revocation_reason"] = reason
    db.touch(rec)

    resident = resident_or_404(rec["resident_id"])
    cascades.apply_consent_termination(rec, resident)
    return response.ok(db.public(rec))
