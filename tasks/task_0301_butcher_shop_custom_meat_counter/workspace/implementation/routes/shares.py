"""AnimalShare + ShareClaim: shares, claims, break-down, cancels (PRD §3.7)."""
from flask import request

import db
import errors
import response
import serializers
import validation as v
from middleware import authenticate, require_role
from routes._helpers import list_response
from services import common

SPECIES = {"BEEF", "PORK", "LAMB", "POULTRY"}
FRACTIONS = {"QUARTER", "HALF"}


def _units(fraction):
    return 1 if fraction == "QUARTER" else 2


def register(app):
    # ---- AnimalShare ----
    @app.route("/animal-shares", methods=["POST"])
    def create_share():
        _uid, role = authenticate()
        require_role(role, {"ShiftManager", "Butcher"})
        body = v.get_body()
        species = v.as_enum(v.require(body, "species"), "species", SPECIES)
        carcass = v.as_int(
            v.require(body, "carcass_weight_g"), "carcass_weight_g", minimum=1)
        deposit = v.as_int(
            v.require(body, "deposit_cents"), "deposit_cents", minimum=0)

        record = {
            "species": species,
            "carcass_weight_g": carcass,
            "deposit_cents": deposit,
            "claimed_fraction_x4": 0,
            "remaining_carcass_g": carcass,
            "share_status": "OPEN",
        }
        db.stamp_create(record)
        db.animal_shares[record["id"]] = record
        return response.object_response(serializers.animal_share(record), 201)

    @app.route("/animal-shares/<rid>", methods=["GET"])
    def get_share(rid):
        _uid, role = authenticate()
        require_role(role, {"ShiftManager", "Butcher", "Customer", "CounterClerk"})
        record = common.get_or_404(db.animal_shares, rid)
        return response.object_response(serializers.animal_share(record))

    @app.route("/animal-shares/<rid>/break-down", methods=["POST"])
    def break_down_share(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        share = common.get_or_404(db.animal_shares, rid)
        body = v.get_body()
        lots = v.require(body, "lots")
        if not isinstance(lots, list) or len(lots) == 0:
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "lots must be a non-empty array.")

        if share["share_status"] != "FULLY_CLAIMED":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Share is not FULLY_CLAIMED; cannot break down.")

        # Validate each spawned-lot spec and resolve its cut type (FK).
        parsed = []
        for i, spec in enumerate(lots):
            if not isinstance(spec, dict):
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "lots[%d] must be an object." % i)
            cut_type_id = v.as_str(v.require(spec, "cut_type_id"),
                                   "lots[%d].cut_type_id" % i)
            received = v.as_int(v.require(spec, "received_weight_g"),
                                "lots[%d].received_weight_g" % i, minimum=1)
            aging_target = v.as_int(v.opt(spec, "aging_target_days", 0),
                                    "lots[%d].aging_target_days" % i, minimum=0)
            common.fk_or_404(db.cut_types, cut_type_id)
            parsed.append((cut_type_id, received, aging_target))

        # Commit: spawn lots, then transition the share.
        for cut_type_id, received, aging_target in parsed:
            lot = {
                "cut_type_id": cut_type_id,
                "source_share_id": share["id"],
                "received_weight_g": received,
                "remaining_weight_g": received,
                "lot_status": "AVAILABLE",
                "locker_id": None,
                "aging_started_at": None,
                "aging_target_days": aging_target,
            }
            db.stamp_create(lot)
            db.inventory_lots[lot["id"]] = lot

        share["share_status"] = "BROKEN_DOWN"
        db.touch(share)
        return response.object_response(serializers.animal_share(share))

    @app.route("/animal-shares/<rid>/cancel", methods=["POST"])
    def cancel_share(rid):
        _uid, role = authenticate()
        require_role(role, {"ShiftManager"})
        share = common.get_or_404(db.animal_shares, rid)
        # Only an OPEN share with no active claims may be cancelled (PRD §3.7).
        if share["share_status"] != "OPEN":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Share is not OPEN; cannot cancel.")
        if share["claimed_fraction_x4"] != 0:
            errors.fail(errors.ERR_INVALID_STATE,
                        "Share has active claims; cannot cancel.")
        share["share_status"] = "CANCELLED"
        db.touch(share)
        return response.object_response(serializers.animal_share(share))

    # ---- ShareClaim ----
    @app.route("/share-claims", methods=["POST"])
    def create_claim():
        uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk"})
        body = v.get_body()
        animal_share_id = v.as_str(
            v.require(body, "animal_share_id"), "animal_share_id")
        customer_id = v.as_str(v.require(body, "customer_id"), "customer_id")
        fraction = v.as_enum(v.require(body, "fraction"), "fraction", FRACTIONS)

        share = common.fk_or_404(db.animal_shares, animal_share_id)
        customer = common.fk_or_404(db.customers, customer_id)

        # Share must be OPEN to accept a claim (state gate, PRD §2.10 #5).
        if share["share_status"] != "OPEN":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Share is not OPEN; cannot claim.")
        # Over-commit check (PRD §3.7) -> ERR_SHARE_OVERCOMMITTED.
        if share["claimed_fraction_x4"] + _units(fraction) > 4:
            errors.fail(errors.ERR_SHARE_OVERCOMMITTED,
                        "Claim would over-commit the carcass.")

        deposit_paid = share["deposit_cents"] * _units(fraction)
        claim = {
            "animal_share_id": animal_share_id,
            "customer_id": customer_id,
            "fraction": fraction,
            "deposit_paid_cents": deposit_paid,
            "claim_status": "ACTIVE",
        }
        db.stamp_create(claim)
        db.share_claims[claim["id"]] = claim

        # Reconcile share derived fields + bubble to FULLY_CLAIMED.
        common.reconcile_share(share)
        if share["claimed_fraction_x4"] == 4:
            share["share_status"] = "FULLY_CLAIMED"
        db.touch(share)
        return response.object_response(serializers.share_claim(claim), 201)

    @app.route("/share-claims/<rid>", methods=["GET"])
    def get_claim(rid):
        _uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk", "ShiftManager"})
        record = common.get_or_404(db.share_claims, rid)
        return response.object_response(serializers.share_claim(record))

    @app.route("/share-claims", methods=["GET"])
    def list_claims():
        _uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk", "ShiftManager"})
        records = list(db.share_claims.values())
        animal_share_id = request.args.get("animal_share_id")
        customer_id = request.args.get("customer_id")
        if animal_share_id is not None:
            records = [r for r in records
                       if r["animal_share_id"] == animal_share_id]
        if customer_id is not None:
            records = [r for r in records if r["customer_id"] == customer_id]
        return list_response(records, request.args, serializers.share_claim)

    @app.route("/share-claims/<rid>/cancel", methods=["POST"])
    def cancel_claim(rid):
        uid, role = authenticate()
        require_role(role, {"Customer"})
        claim = common.get_or_404(db.share_claims, rid)
        # Ownership check (PRD §2.10 #3) before state.
        if claim["customer_id"] != uid:
            errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                        "Customer does not own this claim.")

        if claim["claim_status"] != "ACTIVE":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Claim is not ACTIVE; cannot cancel.")
        share = db.animal_shares.get(claim["animal_share_id"])
        # Permitted only while parent share is OPEN or FULLY_CLAIMED.
        if share is None or share["share_status"] not in ("OPEN", "FULLY_CLAIMED"):
            errors.fail(errors.ERR_INVALID_STATE,
                        "Parent share is not OPEN/FULLY_CLAIMED.")

        was_fully = share["share_status"] == "FULLY_CLAIMED"
        claim["claim_status"] = "CANCELLED"
        db.touch(claim)
        # Refund deposit to store credit (PRD §3.7).
        common.credit_customer(claim["customer_id"], claim["deposit_paid_cents"])
        # Reconcile share + revert bubble FULLY_CLAIMED -> OPEN.
        common.reconcile_share(share)
        if was_fully and share["claimed_fraction_x4"] < 4:
            share["share_status"] = "OPEN"
        db.touch(share)
        return response.object_response(serializers.share_claim(claim))
