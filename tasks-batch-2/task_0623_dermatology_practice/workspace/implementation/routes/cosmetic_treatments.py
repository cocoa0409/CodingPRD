"""CosmeticTreatment: wallet redemption with OCC (PRD 3.6, 2.7)."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
import services
from middleware import require

bp = Blueprint("cosmetic_treatments", __name__)


@bp.post("/cosmetic-treatments")
@require("Provider", "BillingSpecialist")
def create_treatment():
    data = helpers.body()
    encounter_id = helpers.require_str(data, "encounter_id")
    membership_id = helpers.require_str(data, "membership_id")
    service_name = helpers.require_str(data, "service_name")
    list_price_cents = helpers.require_int(data, "list_price_cents")
    expected_membership_version = helpers.require_int(data, "expected_membership_version")

    # Priority 4: body FK existence.
    enc = helpers.get_or_404(db.encounters, encounter_id, "encounter")
    membership = helpers.get_or_404(db.cosmetic_memberships, membership_id, "membership")

    # Priority 5: OCC version check runs before business balance checks (PRD 2.7).
    if expected_membership_version != membership["version"]:
        raise errors.stale_membership_version()

    # Priority 15: encounter must be COSMETIC and membership must be ACTIVE.
    if enc["visit_type"] != "COSMETIC" or membership["status"] != "ACTIVE":
        raise errors.membership_not_active()

    redeemed, out_of_pocket = services.compute_redemption(membership, list_price_cents)
    row = {
        "encounter_id": encounter_id,
        "membership_id": membership_id,
        "service_name": service_name,
        "list_price_cents": list_price_cents,
        "redeemed_cents": redeemed,
        "out_of_pocket_cents": out_of_pocket,
    }
    db.stamp_new(row)
    db.cosmetic_treatments[row["id"]] = row

    # Debit the wallet and bump membership version.
    membership["unit_balance_cents"] -= redeemed
    db.touch(membership)
    # Bubble-up: balance at exactly 0 auto-transitions ACTIVE -> EXHAUSTED,
    # which itself increments the membership version.
    if membership["unit_balance_cents"] == 0 and membership["status"] == "ACTIVE":
        membership["status"] = "EXHAUSTED"
        db.touch(membership)
    return response.created(row)


@bp.get("/cosmetic-treatments/<tid>")
@require("Provider", "BillingSpecialist", "PracticeAdmin")
def get_treatment(tid):
    row = helpers.get_or_404(db.cosmetic_treatments, tid, "treatment")
    return response.ok(row)


@bp.get("/cosmetic-treatments")
@require("Provider", "BillingSpecialist", "PracticeAdmin")
def list_treatments():
    rows = list(db.cosmetic_treatments.values())
    eid = request.args.get("encounter_id")
    if eid is not None:
        rows = [t for t in rows if t["encounter_id"] == eid]
    mid = request.args.get("membership_id")
    if mid is not None:
        rows = [t for t in rows if t["membership_id"] == mid]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)
