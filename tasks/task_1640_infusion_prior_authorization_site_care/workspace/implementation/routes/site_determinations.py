"""Site-of-care steering determinations (PRD 3.3)."""
from flask import Blueprint

from db import db, next_seq
from middleware import authorized
from response import success_object
from routes.helpers import get_request, patient_for_request, policy_for_request, check_request_not_terminal, list_response
from serializers import serialize
from services.calculations import compute_steering
from util import new_id, CLOCK
from validate import get_body, req_int

bp = Blueprint("site_determinations", __name__)


@bp.post("/infusion/authorization-requests/<rid>/site-of-care-determinations")
def create_site_determination(rid):
    authorized(["MedicalDirector"])
    body = get_body()
    home_allowed = req_int(body, "home_allowed_cents")
    hospital_allowed = req_int(body, "hospital_allowed_cents")
    home_billed = req_int(body, "home_billed_cents")
    hospital_billed = req_int(body, "hospital_billed_cents")

    req = get_request(rid)
    check_request_not_terminal(req)
    patient = patient_for_request(req)
    policy = policy_for_request(req)

    variant, steer_score, recommended, steered = compute_steering(
        policy, patient, req, home_allowed, hospital_allowed, home_billed, hospital_billed)

    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "authorization_request_id": req["id"],
        "home_allowed_cents": home_allowed,
        "hospital_allowed_cents": hospital_allowed,
        "home_billed_cents": home_billed,
        "hospital_billed_cents": hospital_billed,
        "score_variant": variant,
        "steer_score": steer_score,
        "recommended_site_type": recommended,
        "steered": steered,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["site_of_care_determinations"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/authorization-requests/<rid>/site-of-care-determinations")
def list_site_determinations(rid):
    authorized(["MedicalDirector", "AuthCoordinator", "Scheduler"])
    get_request(rid)
    items = [d for d in db["site_of_care_determinations"].values()
             if d["authorization_request_id"] == rid]
    return list_response(items)
