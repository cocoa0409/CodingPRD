"""License endpoints (PRD §3.2)."""
from flask import Blueprint, request

import serialize
from db import store, new_common
from errors import err, ERR_INVALID_DATE_RANGE, ERR_LICENSE_OVERLAP
from middleware import auth, get_json_body, lookup, paginate
from response import object_response, array_response
from util import require_str, require_enum, parse_dt, validate_state_code

bp = Blueprint("licenses", __name__)

ALL_ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}
LOB = {"AUTO", "HOME", "GL", "WC", "UMBRELLA"}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection. Boundary touch is NOT overlap."""
    return a_start < b_end and b_start < a_end


@bp.post("/licenses")
def create_license():
    auth({"AgencyAdmin"})
    body = get_json_body()
    producer_id = require_str(body, "producer_id")
    with store.lock:
        lookup(store.producers, producer_id)  # existence (404)
        state_code = validate_state_code(body.get("state_code"))
        lob = require_enum(body, "line_of_business", LOB)
        eff = parse_dt(require_str(body, "effective_date"), "effective_date")
        exp = parse_dt(require_str(body, "expiration_date"), "expiration_date")

        # business: effective strictly before expiration
        if not (eff < exp):
            raise err(ERR_INVALID_DATE_RANGE, "effective_date must be before expiration_date")

        # business: no overlapping license for same producer/state/lob
        for lic in store.licenses.values():
            if (
                lic["producer_id"] == producer_id
                and lic["state_code"] == state_code
                and lic["line_of_business"] == lob
            ):
                lstart = parse_dt(lic["effective_date"], "effective_date")
                lend = parse_dt(lic["expiration_date"], "expiration_date")
                if _intervals_overlap(eff, exp, lstart, lend):
                    raise err(ERR_LICENSE_OVERLAP, "license interval overlaps existing license")

        rec = new_common()
        rec.update(
            producer_id=producer_id,
            state_code=state_code,
            line_of_business=lob,
            effective_date=body["effective_date"],
            expiration_date=body["expiration_date"],
        )
        store.licenses[rec["id"]] = rec
        return object_response(serialize.license(rec), 201)


@bp.get("/licenses/<lid>")
def get_license(lid):
    auth(ALL_ROLES)
    rec = lookup(store.licenses, lid)
    return object_response(serialize.license(rec))


@bp.get("/licenses")
def list_licenses():
    auth(ALL_ROLES)
    producer_id = request.args.get("producer_id")
    state_code = request.args.get("state_code")
    lob = request.args.get("line_of_business")
    recs = [
        l
        for l in store.licenses.values()
        if (producer_id is None or l["producer_id"] == producer_id)
        and (state_code is None or l["state_code"] == state_code)
        and (lob is None or l["line_of_business"] == lob)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.license(l) for l in page], limit, offset, total)
