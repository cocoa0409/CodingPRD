"""Access credential redeem/revoke and feedback submission."""

from flask import Blueprint

import clock
import db
import errors
import middleware as mw
import response
from services import calc, core

bp = Blueprint("credentials_feedback", __name__)


def _get_credential_or_404(credential_id):
    cred = db.access_credentials.get(credential_id)
    if cred is None:
        raise errors.err(errors.ERR_ACCESS_CREDENTIAL_NOT_FOUND,
                         "Access credential not found.", 404)
    return cred


def _request_of(cred):
    return db.showing_requests.get(cred["showing_request_id"])


@bp.post("/showing-desk/access-credentials/<credential_id>/redeem")
def redeem_credential(credential_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["BuyerAgent"])
    cred = _get_credential_or_404(credential_id)
    req = _request_of(cred)
    if req is None:
        raise errors.err(errors.ERR_SHOWING_REQUEST_NOT_FOUND,
                         "Showing request not found.", 404)
    # Ownership: buyer agent owns the request
    if caller.user_id != req["buyer_agent_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the buyer agent of this request.", 403)
    if cred["status"] != "ISSUED":
        raise errors.err(errors.ERR_CREDENTIAL_NOT_REDEEMABLE,
                         "Credential is not in ISSUED status.", 409)
    if req["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_SHOWING_NOT_CONFIRMED,
                         "Parent showing request is not CONFIRMED.", 409)
    now = clock.now()
    if now < cred["active_from"]:
        raise errors.err(errors.ERR_CREDENTIAL_NOT_YET_ACTIVE,
                         "Credential is not yet active.", 422)
    if now >= cred["expires_at"]:
        raise errors.err(errors.ERR_CREDENTIAL_EXPIRED,
                         "Credential has expired.", 422)
    cred["status"] = "USED"
    cred["redeemed_at"] = now
    core.touch(cred)
    core.add_activity(req["listing_id"], req["id"], "CREDENTIAL_REDEEMED",
                      "BuyerAgent", "Access credential redeemed.")
    return response.success_object(core.credential_view(cred))


@bp.post("/showing-desk/access-credentials/<credential_id>/revoke")
def revoke_credential(credential_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["ListingAgent"])
    cred = _get_credential_or_404(credential_id)
    req = _request_of(cred)
    if req is None:
        raise errors.err(errors.ERR_SHOWING_REQUEST_NOT_FOUND,
                         "Showing request not found.", 404)
    listing = db.listings.get(req["listing_id"])
    if listing is None or caller.user_id != listing["listing_agent_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the listing agent of this listing.", 403)
    if cred["status"] != "ISSUED":
        raise errors.err(errors.ERR_CREDENTIAL_NOT_REDEEMABLE,
                         "Credential is not in ISSUED status.", 409)
    cred["status"] = "REVOKED"
    core.touch(cred)
    core.add_activity(req["listing_id"], req["id"], "CREDENTIAL_REVOKED",
                      "ListingAgent", "Access credential revoked by listing agent.")
    return response.success_object(core.credential_view(cred))


@bp.post("/showing-desk/feedback-requests/<feedback_id>/submit")
def submit_feedback(feedback_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    spec = {f"q{i}": ("integer", True) for i in range(1, 6)}
    spec["comment"] = ("string", False)
    fields = mw.validate_fields(body, spec)
    # ERR_RATING_OUT_OF_RANGE lives inside the request-shape stage (PRD §2.7.2)
    for i in range(1, 6):
        v = fields[f"q{i}"]
        if v < 1 or v > 5:
            raise errors.err(errors.ERR_RATING_OUT_OF_RANGE,
                             f"q{i} must be an integer between 1 and 5.", 400)
    mw.require_roles(caller, ["BuyerAgent"])
    fb = db.feedback_requests.get(feedback_id)
    if fb is None:
        raise errors.err(errors.ERR_FEEDBACK_REQUEST_NOT_FOUND,
                         "Feedback request not found.", 404)
    req = db.showing_requests.get(fb["showing_request_id"])
    if req is None:
        raise errors.err(errors.ERR_SHOWING_REQUEST_NOT_FOUND,
                         "Showing request not found.", 404)
    if caller.user_id != req["buyer_agent_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the buyer agent of this request.", 403)
    if fb["status"] == "SUBMITTED":
        raise errors.err(errors.ERR_FEEDBACK_ALREADY_SUBMITTED,
                         "Feedback has already been submitted.", 409)
    if fb["status"] != "SENT":
        raise errors.err(errors.ERR_FEEDBACK_NOT_AVAILABLE,
                         "Feedback request is not in SENT status.", 409)
    fb["q1"], fb["q2"], fb["q3"], fb["q4"], fb["q5"] = (
        fields["q1"], fields["q2"], fields["q3"], fields["q4"], fields["q5"])
    fb["comment"] = fields.get("comment")
    fb["overall_score"] = calc.per_feedback_score(
        fields["q1"], fields["q2"], fields["q3"], fields["q4"], fields["q5"])
    fb["status"] = "SUBMITTED"
    fb["submitted_at"] = clock.now()
    core.touch(fb)
    listing = db.listings.get(req["listing_id"])
    if listing is not None:
        calc.recompute_listing_avg_feedback(listing)
    core.add_activity(req["listing_id"], req["id"], "FEEDBACK_SUBMITTED",
                      "BuyerAgent", "Feedback submitted.")
    return response.success_object(core.feedback_view(fb))
