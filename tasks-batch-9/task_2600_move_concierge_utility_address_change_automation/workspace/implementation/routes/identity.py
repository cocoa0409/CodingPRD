"""Identity verification reads and the external KBA result callback."""

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    EXTERNAL_SERVICE_GATEWAY,
    MOVE_OPS_AGENT,
    authenticate,
)
from services import derive, enums
from services.lookup import move_or_404, verification_or_404

bp = Blueprint("identity", __name__)


@bp.get("/identity-verifications/<verification_id>")
def read_verification(verification_id):
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    return response.ok(db.public(verification_or_404(verification_id)))


@bp.get("/identity-verifications")
def list_verifications():
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    rows = response.match_filters(
        db.db.verifications.values(),
        {
            "move_id": "move_id",
            "resident_id": "resident_id",
            "status": "status",
            "method": "method",
        },
    )
    return response.paginated(rows)


@bp.post("/identity-verifications/<verification_id>/kba-result")
def kba_result(verification_id):
    authenticate(EXTERNAL_SERVICE_GATEWAY)
    rec = verification_or_404(verification_id)
    body = v.body()
    outcome = v.enum_field(body, "outcome", ("PASSED", "FAILED"))
    score = v.int_field(body, "score", minimum=300, maximum=850)

    # rung 12: only a PENDING attempt can receive a bureau result.
    if rec["status"] != "PENDING":
        raise ApiError(
            "ERR_VERIFICATION_ALREADY_DECIDED",
            "This identity verification has already been decided.",
        )

    move = move_or_404(rec["move_id"])
    snap = derive.snapshot(move)

    # calculations.identity_kba_evaluation, threshold form.
    expires_at = db.parse_ts(rec["expires_at"])
    lapsed = expires_at is not None and db.now() > expires_at
    passed = outcome == "PASSED" and score >= enums.KBA_PASS_SCORE and not lapsed

    rec["kba_score"] = score
    rec["decided_at"] = db.now_iso()
    rec["status"] = "EXPIRED" if lapsed else ("PASSED" if passed else "FAILED")
    db.touch(rec)

    if passed:
        move["verified_at"] = db.now_iso()
        move["lifecycle_status"] = "VERIFIED"
    elif move["lifecycle_status"] in ("IDENTITY_PENDING", "INTAKE"):
        move["lifecycle_status"] = "IDENTITY_FAILED"

    derive.recompute(move)
    derive.commit(move, snap)
    return response.ok(db.public(rec))
