"""Die inventory endpoints and the new-die tooling charge (PRD 3.2)."""
from flask import Blueprint

from calc import NEW_DIE_CHARGE_CENTS
from db import DB, new_id, now_iso
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import get_die, sorted_created, touch
from util import as_int, as_str, body, pagination_args, reject_unknown, required

bp = Blueprint("dies", __name__)

_DIE_FIELDS = {"die_code", "shape_description", "cavities_across"}


def _create_die(new_die_charge_cents):
    data = body()
    reject_unknown(data, _DIE_FIELDS)
    die_code = as_str(required(data, "die_code"), "die_code")
    shape_description = as_str(
        required(data, "shape_description"), "shape_description"
    )
    cavities_across = as_int(required(data, "cavities_across"), "cavities_across")
    ts = now_iso()
    die = {
        "id": new_id(),
        "die_code": die_code,
        "shape_description": shape_description,
        "cavities_across": cavities_across,
        "status": "ACTIVE",
        "new_die_charge_cents": new_die_charge_cents,
        "charge_collected": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["dies"][die["id"]] = die
    return die


@bp.post("/label-jobs/dies")
def register_die():
    """Register an existing die already on the shelf (no tooling charge)."""
    auth(["Estimator"])
    return ok(_create_die(0), 201)


@bp.post("/label-jobs/dies/purchase")
def purchase_die():
    """Order a new die from the toolmaker; carries the one-time charge."""
    auth(["Estimator"])
    return ok(_create_die(NEW_DIE_CHARGE_CENTS), 201)


@bp.get("/label-jobs/dies")
def list_dies():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted_created(DB["dies"].values())
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.get("/label-jobs/dies/<die_id>")
def get_one_die(die_id):
    auth(ALL_ROLES)
    return ok(get_die(die_id))


@bp.post("/label-jobs/dies/<die_id>/retire")
def retire_die(die_id):
    auth(["Estimator"])
    die = get_die(die_id)
    data = body()
    reject_unknown(data, set())
    die["status"] = "RETIRED"
    touch(die)
    return ok(die)
