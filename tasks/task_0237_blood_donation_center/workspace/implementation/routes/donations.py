"""Donations: reads and the test-result (release/discard) cascade."""
from flask import Blueprint, request

import db
import errors
import lookup
from common import get_json_body, paginate, require_enum
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_donation, serialize_test_result

bp = Blueprint("donations", __name__)

PANEL_OUTCOMES = {"NEGATIVE", "POSITIVE", "INDETERMINATE"}


@bp.route("/blood-bank/donations", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager")
def list_donations():
    donor_id = request.args.get("donor_id")
    appointment_id = request.args.get("appointment_id")
    center_id = request.args.get("center_id")
    status = request.args.get("status")
    donation_type = request.args.get("donation_type")
    with db.lock:
        rows = list(db.donations.values())
        if donor_id is not None:
            rows = [d for d in rows if d["donor_id"] == donor_id]
        if appointment_id is not None:
            rows = [d for d in rows if d["appointment_id"] == appointment_id]
        if center_id is not None:
            rows = [d for d in rows if d["center_id"] == center_id]
        if status is not None:
            rows = [d for d in rows if d["status"] == status]
        if donation_type is not None:
            rows = [d for d in rows if d["donation_type"] == donation_type]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_donation(d) for d in page], limit, offset, total)


@bp.route("/blood-bank/donations/<donation_id>", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager")
def get_donation(donation_id):
    with db.lock:
        donation = lookup.donation(donation_id)
        return success(serialize_donation(donation))


@bp.route("/blood-bank/donations/<donation_id>/test-results", methods=["POST"])
@require_roles("LabTechnician")
def record_test_result(donation_id):
    body = get_json_body()
    with db.lock:
        donation = lookup.donation(donation_id)
        panel_outcome = require_enum(body, "panel_outcome", PANEL_OUTCOMES)

        # state: donation must be COLLECTED
        if donation["status"] != "COLLECTED":
            raise ApiError(errors.ERR_DONATION_NOT_COLLECTED, 409,
                           "Donation must be COLLECTED to record a test result.")

        # on NEGATIVE path, a SEVERE adverse reaction blocks release
        if panel_outcome == "NEGATIVE":
            has_severe = any(
                r["donation_id"] == donation_id and r["severity"] == "SEVERE"
                for r in db.adverse_reactions.values()
            )
            if has_severe:
                raise ApiError(errors.ERR_SEVERE_REACTION_BLOCKS_RELEASE, 409,
                               "A SEVERE adverse reaction blocks release.")

        center = db.centers.get(donation["center_id"])

        # create the TestResult row
        test_result = {
            "donation_id": donation_id,
            "donor_id": donation["donor_id"],
            "panel_outcome": panel_outcome,
            "resulted_at": center["current_utc"],
        }
        db.stamp_new(test_result)
        db.test_results[test_result["id"]] = test_result
        donation["test_result_id"] = test_result["id"]

        if panel_outcome == "NEGATIVE":
            donation["status"] = "RELEASABLE"
            db.touch(donation)
            _release_units(donation, center)
        else:
            donation["status"] = "DISCARDED"
            db.touch(donation)
            _discard_units(donation)
            if panel_outcome == "POSITIVE":
                donor = db.donors.get(donation["donor_id"])
                domain.create_deferral(
                    donor, center, "INFECTIOUS_RISK", "PERMANENT",
                    "Auto-deferral from POSITIVE infectious-disease panel",
                )

        return success(serialize_test_result(test_result), status=201)


def _release_units(donation, center):
    for unit in db.blood_units.values():
        if unit["donation_id"] == donation["id"] and unit["status"] == "QUARANTINED":
            unit["status"] = "AVAILABLE"
            unit["released_at"] = center["current_utc"]
            if unit["component"] == "PLATELET":
                unit["expires_at"] = domain.release_anchored_expiry(unit["released_at"])
            db.touch(unit)
            domain.adjust_bucket(unit["center_id"], unit["blood_type"],
                                 unit["component"], available_delta=1)


def _discard_units(donation):
    for unit in db.blood_units.values():
        if unit["donation_id"] == donation["id"] and unit["status"] == "QUARANTINED":
            unit["status"] = "DISCARDED"
            db.touch(unit)
