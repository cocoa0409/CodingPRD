"""Listings, syndication and the marketing disclosure standard (PRD 3.8)."""
from flask import Blueprint

import enums
import helpers as h
import serializers as ser
from db import cfg, db, new_id
from errors import ApiError

bp = Blueprint("marketing", __name__)

READ_ROLES = (
    "ProgramAdministrator",
    "ProgramAuditor",
    "DealerPrincipal",
    "CustomerAdvocate",
)
LIVE_STATUSES = ("ACTIVE", "UNDER_AUDIT")


def listing_or_404(listing_id):
    row = db.listings.get(listing_id)
    if row is None:
        raise ApiError("ERR_LISTING_NOT_FOUND", "No listing with that id.")
    return row


def _check_disclosures(config, tokens):
    missing = [
        token
        for token in (config["listing_required_disclosure_fields"] or [])
        if token not in tokens
    ]
    if missing:
        raise ApiError(
            "ERR_MARKETING_STANDARD_VIOLATION",
            "The advertisement omits the required disclosure %s." % missing[0],
        )


@bp.route("/listings", methods=["POST"])
def create_listing():
    _uid, _role, dealer = h.authorize(("DealerPrincipal",))
    config = cfg()
    body = h.body_dict()
    certification_id = h.f_string(body, "certification_id")
    channel = h.f_enum(body, "channel", enums.CHANNELS)
    price_cents = h.f_int(body, "price_cents", minimum=1)
    tokens = h.f_list(body, "disclosure_fields", non_empty=False)
    for token in tokens:
        if not isinstance(token, str) or token.strip() == "":
            h.bad_request("disclosure_fields must hold non-empty strings.")

    certification = db.certifications.get(certification_id)
    if certification is None:
        raise ApiError(
            "ERR_REFERENCED_ENTITY_NOT_FOUND", "certification_id does not resolve."
        )
    if certification["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "That certification belongs to another dealership.",
        )
    if certification["status"] not in LIVE_STATUSES:
        raise ApiError(
            "ERR_CERTIFICATION_NOT_ACTIVE",
            "Only a live certification may be advertised.",
        )

    _check_disclosures(config, tokens)

    for other in db.listings.values():
        if (
            other["certification_id"] == certification_id
            and other["channel"] == channel
            and other["status"] != "WITHDRAWN"
        ):
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                "That certification already holds a live listing on this channel.",
            )

    row = h.new_common(
        {
            "id": new_id(),
            "certification_id": certification_id,
            "channel": channel,
            "price_cents": price_cents,
            "disclosure_fields": list(tokens),
            "status": "DRAFT",
            "syndicated_at": None,
            "syndicated_snapshot_version": None,
            "withdrawn_at": None,
            "withdrawal_reason": None,
            "removal_due_at": None,
        }
    )
    db.listings[row["id"]] = row
    return h.object_response(ser.listing(row), 201)


@bp.route("/certifications/<certification_id>/listings", methods=["GET"])
def list_listings(certification_id):
    user_id, role, _principal = h.authorize(READ_ROLES)
    channel = h.q_enum("channel", enums.CHANNELS)
    status = h.q_enum("status", enums.LISTING_STATUSES)
    limit, offset = h.pagination()
    if certification_id not in db.certifications:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND", "No certification with that id.")
    h.require_dealer_scope(
        user_id, role, db.certifications[certification_id]["dealer_id"]
    )
    rows = [l for l in db.listings.values() if l["certification_id"] == certification_id]
    if channel:
        rows = [r for r in rows if r["channel"] == channel]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return h.paged(rows, limit, offset, ser.listing)


@bp.route("/listings/<listing_id>/syndicate", methods=["POST"])
def syndicate(listing_id):
    _uid, _role, dealer = h.authorize(("DealerPrincipal",))
    config = cfg()
    body = h.body_dict()
    expected_version = h.f_int(body, "expected_certification_version")

    listing = listing_or_404(listing_id)
    certification = db.certifications.get(listing["certification_id"])

    if certification is None or certification["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION", "That listing belongs to another dealership."
        )

    if listing["status"] == "WITHDRAWN":
        raise ApiError(
            "ERR_LISTING_WITHDRAWN", "A withdrawn listing can never be republished."
        )
    if certification["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CERTIFICATION_NOT_ACTIVE",
            "Only an ACTIVE certification may be syndicated.",
        )

    if expected_version != certification["version"]:
        raise ApiError(
            "ERR_STALE_CERTIFICATION_VERSION",
            "The certification has moved on since it was read; re-read it and retry.",
        )

    if dealer["privilege_status"] == "SUSPENDED":
        raise ApiError(
            "ERR_DEALER_PRIVILEGE_SUSPENDED",
            "A suspended dealer may not publish on any channel.",
        )

    _check_disclosures(config, listing["disclosure_fields"])
    if (
        listing["channel"] == "THIRD_PARTY_AGGREGATOR"
        and dealer["privilege_status"] != "ACTIVE"
    ):
        raise ApiError(
            "ERR_MARKETING_STANDARD_VIOLATION",
            "The aggregator channel demands a dealer whose privilege is exactly ACTIVE.",
        )

    certification["listing_syndicated_at"] = db.clock
    h.touch(certification)

    listing["status"] = "SYNDICATED"
    listing["syndicated_at"] = db.clock
    listing["syndicated_snapshot_version"] = certification["version"]
    h.touch(listing)
    return h.object_response(ser.listing(listing))
