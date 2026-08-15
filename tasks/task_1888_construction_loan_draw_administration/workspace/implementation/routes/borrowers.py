from flask import Blueprint, g

import db
from auth import ALL_ROLES, require_role
from db import pub
from respond import success
from services import get_or_404
from util import get_body, req_enum, req_str

bp = Blueprint("borrowers", __name__)

ENTITY_TYPES = ["INDIVIDUAL", "LLC", "CORPORATION", "PARTNERSHIP"]


@bp.post("/borrowers")
def create_borrower():
    require_role(g.role, {"LenderAdmin"})
    body = get_body()
    rec = db.base_record()
    rec.update(
        {
            "legal_name": req_str(body, "legal_name"),
            "contact_email": req_str(body, "contact_email"),
            "entity_type": req_enum(body, "entity_type", ENTITY_TYPES),
        }
    )
    db.borrowers[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/borrowers/<rid>")
def get_borrower(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(get_or_404(db.borrowers, rid, "Borrower")))
