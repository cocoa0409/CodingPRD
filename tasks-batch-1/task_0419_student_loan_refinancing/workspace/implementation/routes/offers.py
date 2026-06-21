"""Offer routes: fetch, list, and lock.

PRD §3.4 (locking an offer). Lock is OCC-guarded on the parent Application
version, applies autopay + member-tier discount, supersedes siblings, and
advances the application to UNDER_REVIEW.
"""
from flask import Blueprint, request

import calc
import db
import serialize
import clock
from auth import authorize
from errors import err
from response import object_response, array_response
from store_helpers import get_or_404, sorted_by_created, paginate, append_audit
from validate import get_json_body, require_int, optional_bool, parse_pagination

bp = Blueprint("offers", __name__)


def _cosigner_for_application(application_id):
    for c in db.cosigners.values():
        if c["application_id"] == application_id:
            return c
    return None


@bp.route("/offers/<rid>", methods=["GET"])
def get_offer(rid):
    authorize(("GET", "/offers/{id}"))
    record = get_or_404(db.offers, rid)
    return object_response(serialize.offer(record), 200)


@bp.route("/offers", methods=["GET"])
def list_offers():
    authorize(("GET", "/offers"))
    limit, offset = parse_pagination()
    f_app = request.args.get("application_id")
    f_status = request.args.get("status")
    records = list(db.offers.values())
    if f_app is not None:
        records = [r for r in records if r["application_id"] == f_app]
    if f_status is not None:
        records = [r for r in records if r["status"] == f_status]
    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.offer(r) for r in page], limit, offset, total)


@bp.route("/offers/<rid>/lock", methods=["POST"])
def lock_offer(rid):
    user_id, role = authorize(("POST", "/offers/{id}/lock"))
    body = get_json_body()
    # expected_application_version is required (PRD §2.8).
    expected_version = require_int(body, "expected_application_version")
    autopay_elected = optional_bool(body, "autopay_elected", default=False)

    with db.lock():
        offer = get_or_404(db.offers, rid)
        app = get_or_404(db.applications, offer["application_id"])

        # Validation order (PRD §2.6, §3.4):
        # state (application PREQUALIFIED) -> OCC -> offer state/expiry -> cosigner.
        if app["status"] != "PREQUALIFIED":
            raise err("ERR_INVALID_STATE", "lock only when application is PREQUALIFIED")

        # OCC: expected_application_version must match Application.version.
        if expected_version != app["version"]:
            raise err("ERR_STALE_APPLICATION_VERSION", "stale application version")

        # Target offer must be PRESENTED (state) ...
        if offer["status"] != "PRESENTED":
            raise err("ERR_INVALID_STATE", "offer not PRESENTED")

        # Segregation of order in §3.4: offer expiry then cosigner-consented.
        # Per §3.4 the cosigner-consent guard is listed after expiry; honor that.
        if not (offer["expires_at_dt"] > clock.now()):
            raise err("ERR_OFFER_EXPIRED", "offer expired")

        cosigner = _cosigner_for_application(app["id"])
        if cosigner is not None and cosigner["consent_status"] != "CONSENTED":
            raise err("ERR_COSIGNER_NOT_CONSENTED", "attached cosigner has not consented")

        borrower = db.borrowers[app["borrower_id"]]

        # Compute locked APR: autopay first, then member-tier, then floor clamp.
        offer["autopay_elected"] = autopay_elected
        offer["locked_apr_bps"] = calc.locked_apr_bps(
            offer["estimated_apr_bps"], autopay_elected, borrower["member_tier"]
        )
        offer["status"] = "LOCKED"
        db.touch(offer)

        # Sibling PRESENTED offers on this application -> SUPERSEDED.
        for sib in db.offers.values():
            if sib["application_id"] == app["id"] and sib["id"] != offer["id"] and sib["status"] == "PRESENTED":
                sib["status"] = "SUPERSEDED"
                db.touch(sib)

        # Application -> UNDER_REVIEW; version incremented by 1 (the OCC bump).
        app["status"] = "UNDER_REVIEW"
        db.touch(app)
        append_audit("APPLICATION", app["id"], "OFFER_LOCKED", role, user_id)
    return object_response(serialize.offer(offer), 200)
