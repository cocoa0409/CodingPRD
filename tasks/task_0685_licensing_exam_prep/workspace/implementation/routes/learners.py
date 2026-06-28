"""Learner routes (PRD §3.2, §2.1)."""
from flask import Blueprint

from db import db, stamp_create
from response import success
from middleware import get_auth, require_role
from services import validate as V
from services.serialize import public
from services.lookups import get_learner
from errors import raise_err
import errors

bp = Blueprint("learners", __name__)


@bp.post("/learners")
def create_learner():
    _, role = get_auth()
    require_role(role, {"Learner"})
    data = V.body()
    email = V.as_str(V.require(data, "email"), "email")
    full_name = V.as_str(V.require(data, "full_name"), "full_name")
    # email unique among learners.
    for l in db.learners.values():
        if l["email"] == email:
            raise_err(errors.ERR_INVALID_REQUEST, "email must be unique")
    rec = {"email": email, "full_name": full_name}
    stamp_create(rec)
    db.learners[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/learners/<lid>")
def get_learner_route(lid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin"})
    rec = get_learner(lid)
    # Ownership: a Learner reading a learner-record must be that learner (PRD §2.1).
    if role == "Learner" and rec["id"] != user_id:
        raise_err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    return success(public(rec))
