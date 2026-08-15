"""Content strikes, the two-round appeal process, and segregated resolution (§3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import domain
from core import (ApiError, auth, body, err_invalid_state, err_not_found,
                  err_ownership, ok_obj, paginate, pagination, req_enum,
                  req_str, require_role)

bp = Blueprint("strikes", __name__)

POLICY_CODES = ("COPYRIGHT", "HATE_SPEECH", "NUDITY", "HARASSMENT", "SPAM")
SEVERITIES = ("MINOR", "MAJOR", "SEVERE")
READ_ROLES = ("PlatformAdmin", "Creator", "TrustAgent", "AppealsOfficer")
STRIKE_WINDOW_DAYS = 90
APPEAL_WINDOW_DAYS = 14
APPEAL_ROUND_CAP = 2


@bp.post("/api/channels/<channel_id>/strikes")
def issue_strike(channel_id):
    uid, role = auth()
    b = body()
    policy_code = req_enum(b, "policy_code", POLICY_CODES)
    severity = req_enum(b, "severity", SEVERITIES)
    evidence_ref = req_str(b, "evidence_ref")
    require_role(role, ("TrustAgent",))
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    old_posture = domain.monetization_posture(ch)
    ts = db.now()
    s = db.new_entity(
        channel_id=channel_id,
        policy_code=policy_code,
        severity=severity,
        evidence_ref=evidence_ref,
        strike_status="ISSUED",
        issued_at=ts,
        expires_at=ts + timedelta(days=STRIKE_WINDOW_DAYS),
        appeal_deadline=ts + timedelta(days=APPEAL_WINDOW_DAYS),
        appeal_round=0,
        issued_by_user_id=uid,  # recorded for segregation of duties
        resolved_by_user_id=None,
        upheld_at=None,
    )
    db.store.strikes[s["id"]] = s
    # Posture recomputed on every strike transition, incl. the hold cascade
    # when the active weight crosses 3.
    domain.posture_cascade(ch, old_posture, cause="POSTURE")
    return ok_obj(domain.strike_json(s), status=201)


@bp.get("/api/channels/<channel_id>/strikes")
def list_strikes(channel_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, READ_ROLES)
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    strikes = domain.channel_strikes(channel_id)
    status = request.args.get("strike_status")
    if status is not None:
        strikes = [s for s in strikes if s["strike_status"] == status]
    return paginate(strikes, limit, offset, domain.strike_json)


@bp.post("/api/strikes/<strike_id>/appeal")
def appeal_strike(strike_id):
    uid, role = auth()
    b = body()
    statement = req_str(b, "statement")
    require_role(role, ("Creator",))
    s = db.store.strikes.get(strike_id)
    if s is None:
        raise err_not_found("Strike not found")
    if uid != s["channel_id"]:
        raise err_ownership()
    # State admissibility (6): round 1 from ISSUED, round 2 from UPHELD.
    if s["strike_status"] not in ("ISSUED", "UPHELD"):
        raise err_invalid_state("Only an ISSUED or UPHELD strike can be appealed")
    # Window (10) outranks rounds (11): an appeal violating both reports the window.
    if db.now() > s["appeal_deadline"]:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", 409,
                       "The strike's appeal_deadline has passed")
    if s["appeal_round"] >= APPEAL_ROUND_CAP:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED", 409,
                       "appeal_round has reached the cap of 2")
    s["strike_status"] = "UNDER_APPEAL"
    s["appeal_round"] += 1
    db.touch(s)
    ch = domain.get_channel(s["channel_id"])
    # Weight still counts while UNDER_APPEAL; recompute rarely changes posture.
    domain.posture_cascade(ch, domain.monetization_posture(ch), cause="POSTURE")
    return ok_obj(domain.strike_json(s))


@bp.post("/api/strikes/<strike_id>/resolve-appeal")
def resolve_appeal(strike_id):
    uid, role = auth()
    b = body()
    outcome = req_enum(b, "outcome", ("UPHELD", "REVERSED"))
    resolution_note = req_str(b, "resolution_note")
    require_role(role, ("AppealsOfficer",))
    s = db.store.strikes.get(strike_id)
    if s is None:
        raise err_not_found("Strike not found")
    if s["strike_status"] != "UNDER_APPEAL":
        raise err_invalid_state("Only an UNDER_APPEAL strike can be resolved")
    # Segregation of duties (8): the resolver must not be the issuer.
    if uid == s["issued_by_user_id"]:
        raise ApiError("ERR_SELF_REVIEW_FORBIDDEN", 403,
                       "The resolving AppealsOfficer must differ from the issuing TrustAgent")
    ch = domain.get_channel(s["channel_id"])
    old_posture = domain.monetization_posture(ch)
    s["resolved_by_user_id"] = uid
    if outcome == "UPHELD":
        s["strike_status"] = "UPHELD"
        s["upheld_at"] = db.now()
        # Round-2 appeal window opens at upheld_at + 14 days.
        s["appeal_deadline"] = db.now() + timedelta(days=APPEAL_WINDOW_DAYS)
        db.touch(s)
        domain.posture_cascade(ch, old_posture, cause="POSTURE")
    else:  # REVERSED: weight removed; a return to STANDARD releases POSTURE holds.
        s["strike_status"] = "REVERSED"
        db.touch(s)
        domain.posture_cascade(ch, old_posture, cause="POSTURE")
        if domain.monetization_posture(ch) == "STANDARD":
            domain.release_held_payouts(ch["id"], "POSTURE")
    return ok_obj(domain.strike_json(s))
