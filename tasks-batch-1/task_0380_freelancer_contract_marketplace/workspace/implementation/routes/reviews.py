"""Review endpoints (PRD 3.8)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_auth, require_role
from response import success
from services import common, derive

bp = Blueprint("reviews", __name__)


@bp.post("/reviews")
def create_review():
    user_id, role = require_auth()
    require_role(role, ["Client", "Freelancer"])
    body = common.get_body()
    contract_id = common.require_str(body, "contract_id")
    author_role = common.require_enum(body, "author_role", {"CLIENT", "FREELANCER"})
    rating = common.require_int(body, "rating", minimum=1, maximum=5)
    comment = common.require_str(body, "comment")
    c = common.get_contract(contract_id)
    # ownership: acting party must own its side of the contract
    if role == "Client":
        common.check_client_owns(role, user_id, c["client_id"])
    else:
        common.check_freelancer_owns(role, user_id, c["freelancer_id"])
    if c["status"] != "COMPLETED":
        raise err("ERR_REVIEW_CONTRACT_NOT_COMPLETED", "Contract is not COMPLETED")
    rec = db.new_common()
    rec.update({
        "contract_id": contract_id,
        "author_role": author_role,
        "freelancer_id": c["freelancer_id"],
        "rating": rating,
        "comment": comment,
    })
    db.reviews[rec["id"]] = rec
    # only client-authored ratings feed reputation
    if author_role == "CLIENT":
        derive.recompute_freelancer_reputation(db.freelancers[c["freelancer_id"]])
    return success(derive.review_view(rec), status=201)


@bp.get("/reviews/<rid>")
def get_review(rid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    r = db.reviews.get(rid)
    if r is None:
        # The catalogue has no review-specific 404; Reviews are addressed via the
        # contract being reviewed, so a missing review surfaces as not found.
        from errors import ApiError
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "Review not found")
    return success(derive.review_view(r))
