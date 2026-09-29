"""Sponsorship interval reads and relinquishment (PRD 3.1)."""
from flask import Blueprint

import serializers
from db import db, touch
from middleware import ALL_ROLES, endpoint
from response import ok, paginated
from routes.common import filters, gate, get_or_404, listing, matches
from services import audit

bp = Blueprint("sponsorships", __name__)


@bp.route("/sponsorship-transfers", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_transfers():
    active = filters("license_registration_id", "status")
    rows = listing(db.sponsorship_transfers, lambda r: matches(r, active))
    return paginated(rows, serializers.sponsorship_transfer)


@bp.route("/sponsorship-transfers/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_transfer(row_id):
    row = get_or_404(db.sponsorship_transfers, row_id)
    return ok(serializers.sponsorship_transfer(row))


@bp.route("/sponsorship-transfers/<row_id>/relinquish", methods=["POST"])
@endpoint("LicensingAnalyst")
def relinquish(row_id):
    row = get_or_404(db.sponsorship_transfers, row_id)
    gate("SponsorshipTransfer", row, ("ACTIVE",))
    row["status"] = "RELINQUISHED"
    # Half-open interval: the sponsorship stops covering exactly at this instant.
    row["relinquished_at"] = db.clock
    touch(row)
    lic = db.license_registrations.get(row["license_registration_id"])
    if lic is not None:
        lic["active_sponsoring_institution_code"] = None
        lic["active_sponsorship_effective_at"] = None
        touch(lic)
    audit.append("SponsorshipTransfer", row["id"], "SPONSORSHIP_CHANGED",
                 {"status": "RELINQUISHED",
                  "license_registration_id": row["license_registration_id"]})
    return ok(serializers.sponsorship_transfer(row))
