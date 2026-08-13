"""POST /markets — register a market under a program."""

from flask import Blueprint

from db import STORE, stamp_new
from middleware import ensure_valid_json, req_str
from response import success_object
from routes.common import Pipeline, ref_exists
from services.domain import serialize_market

bp = Blueprint("markets", __name__)


@bp.route("/markets", methods=["POST"])
def create_market():
    pipe = Pipeline(["ProgramAdmin"], is_write=True)
    body = pipe.body
    # Priority 6: body-referenced ids exist (runs before shape, priority 8)
    ref_exists("programs", body.get("program_id"))
    ensure_valid_json(body)
    program_id = req_str(body, "program_id")
    name = req_str(body, "name")
    city = req_str(body, "city")
    market = stamp_new({"program_id": program_id, "name": name, "city": city})
    STORE["markets"][market["id"]] = market
    env, status = success_object(serialize_market(market), 201)
    pipe.commit(status, env.get_json())
    return env, status
