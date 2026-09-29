"""Association registration and read (PRD 3.1, 2.6)."""

from flask import Blueprint

import response as R
import validation as V
from db import db, new_row
from middleware import READ_ALL, auth
from services import constants as C
from services import state as S

bp = Blueprint("associations", __name__)


@bp.post("/associations")
@auth("AssociationSecretary")
def create_association():
    body = V.get_body()
    name = V.req_str(body, "name")
    target = V.req_int(body, "reserve_target_cents", minimum=1)
    voting_basis = V.opt_enum(body, "default_voting_basis", C.VOTING_BASES, "PER_PARCEL")
    interest_basis = V.opt_enum(body, "delinquency_interest_basis", C.INTEREST_BASES, "STATUTORY")
    quorum_bps = V.opt_int(body, "quorum_bps", 5000, minimum=1, maximum=10000)

    row = new_row({
        "name": name,
        "reserve_target_cents": target,
        "default_voting_basis": voting_basis,
        "delinquency_interest_basis": interest_basis,
        "quorum_bps": quorum_bps,
        "reserve_balance_cents": 0,
        "reserve_funding_ratio": 0,
        "reserve_posture": "UNDERFUNDED",
    })
    db.associations[row["id"]] = row
    return R.ok(row, 201)


@bp.get("/associations/<association_id>")
@auth(*READ_ALL)
def read_association(association_id):
    return R.ok(S.require("association", association_id))
