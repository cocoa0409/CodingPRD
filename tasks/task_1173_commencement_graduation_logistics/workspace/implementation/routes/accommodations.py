"""Accommodation request workflow routes (approve/deny/fulfill)."""
import db
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_ACCESSIBLE_CAPACITY_EXCEEDED,
)
from middleware import get_caller, require_role, require_graduate_ownership
from response import success
from services.common import get_accommodation_or_404, get_ceremony_or_404
from services.pools import effective_venue
from services.serialize import accommodation_out


def register(bp):
    @bp.route("/accommodation-requests/<rid>", methods=["GET"])
    def get_accommodation(rid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        r = get_accommodation_or_404(rid)
        require_graduate_ownership(user_id, role, r["graduate_id"])
        return success(accommodation_out(r))

    @bp.route("/accommodation-requests/<rid>/approve", methods=["POST"])
    def approve_accommodation(rid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        r = get_accommodation_or_404(rid)
        ceremony = get_ceremony_or_404(r["ceremony_id"])
        if r["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Request is not SUBMITTED")
        if r["request_type"] == "WHEELCHAIR_SEAT":
            venue = effective_venue(ceremony)
            approved = sum(
                1 for x in db.accommodation_requests.values()
                if x["ceremony_id"] == r["ceremony_id"]
                and x["request_type"] == "WHEELCHAIR_SEAT"
                and x["status"] in {"APPROVED", "FULFILLED"}
            )
            if venue is None or approved >= venue["accessible_capacity"]:
                raise_err(ERR_ACCESSIBLE_CAPACITY_EXCEEDED, "Accessible pool exhausted")
        r["status"] = "APPROVED"
        r["approved_by_user_id"] = user_id
        r["version"] += 1
        db.touch(r)
        return success(accommodation_out(r))

    @bp.route("/accommodation-requests/<rid>/deny", methods=["POST"])
    def deny_accommodation(rid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        r = get_accommodation_or_404(rid)
        if r["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Request is not SUBMITTED")
        r["status"] = "DENIED"
        r["version"] += 1
        db.touch(r)
        return success(accommodation_out(r))

    @bp.route("/accommodation-requests/<rid>/fulfill", methods=["POST"])
    def fulfill_accommodation(rid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        r = get_accommodation_or_404(rid)
        # SoD (priority 6) before state (priority 8)
        if r["approved_by_user_id"] is not None and user_id == r["approved_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES, "Fulfiller must differ from approver")
        if r["status"] != "APPROVED":
            raise_err(ERR_INVALID_STATE, "Request is not APPROVED")
        r["status"] = "FULFILLED"
        r["fulfilled_by_user_id"] = user_id
        r["version"] += 1
        db.touch(r)
        return success(accommodation_out(r))
