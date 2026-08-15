"""EducationAssignment complete endpoint (PRD 3.9). Listing lives on the merchant sub-resource."""

from flask import Blueprint, g

from clock import CLOCK
from db import db
from errors import ApiError
from records import touch
from response import ok_object
from routes.common import authenticate, get_or_404, hide_if_cross_merchant
from serializers import serialize_education_assignment

bp = Blueprint("education", __name__)


@bp.post("/acquirer/education-assignments/<aid>/complete")
def complete_assignment(aid):
    authenticate(("MerchantUser",))
    asg = get_or_404(db.education_assignments, aid, "EducationAssignment")
    hide_if_cross_merchant(asg["merchant_id"])
    # Priority 5: assignment must still be ASSIGNED.
    if asg["status"] != "ASSIGNED":
        raise ApiError(409, "ERR_ASSIGNMENT_NOT_OPEN", "The education assignment is not ASSIGNED")
    # Priority 6: suspension gate.
    merchant = db.merchants[asg["merchant_id"]]
    if merchant["status"] != "ACTIVE":
        raise ApiError(409, "ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED")
    asg["status"] = "COMPLETED"
    asg["completed_at"] = CLOCK.now()
    touch(asg)
    return ok_object(serialize_education_assignment(asg))
