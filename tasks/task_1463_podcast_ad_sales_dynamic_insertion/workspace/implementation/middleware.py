"""Auth middleware: X-User-ID / X-User-Role header extraction, role checks,
and entity-backed ownership scoping (Advertiser / Agency / ShowProducer)."""

from flask import request

import db
from errors import err_unauthenticated, err_forbidden, err_agency_mismatch

VALID_ROLES = {"AdOps", "Advertiser", "Agency", "ShowProducer", "Finance", "Ingestion"}
ALL_ROLES = VALID_ROLES  # read surface shared across every declared role


def current_user():
    """Extract and validate the auth headers. Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise err_unauthenticated()
    if user_id is None or user_id.strip() == "":
        raise err_unauthenticated()
    return user_id, role


def require_roles(allowed_roles):
    """Auth (401) then endpoint role gate (403). Returns (user_id, role)."""
    user_id, role = current_user()
    if role not in allowed_roles:
        raise err_forbidden()
    return user_id, role


def check_campaign_scope(campaign, user_id, role):
    """Ownership/scope for operations resolving to a campaign.

    Advertiser: campaign.advertiser_id must equal X-User-ID (ERR_FORBIDDEN).
    Agency: the campaign's advertiser must be represented by X-User-ID
    (ERR_AGENCY_MISMATCH). Other roles: unscoped.
    """
    if role == "Advertiser":
        if campaign["advertiser_id"] != user_id:
            raise err_forbidden("Advertiser may act only on its own campaigns")
    elif role == "Agency":
        advertiser = db.advertisers.get(campaign["advertiser_id"])
        if advertiser is None or advertiser.get("agency_id") != user_id:
            raise err_agency_mismatch()
