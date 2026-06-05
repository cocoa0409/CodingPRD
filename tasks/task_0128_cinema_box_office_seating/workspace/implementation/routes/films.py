"""Film endpoints (PRD §3.1) including the end-run transition."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import authenticate, authorize, CINEMA_MANAGER, BOX_OFFICE_AGENT, DISTRIBUTOR
import response
from services import common as C
from routes._helpers import get_or_404, require_distributor_owns_film

bp = Blueprint("films", __name__)


def _validate_split_schedule(schedule):
    """split_schedule must be a list of {week_index, distributor_pct},
    contain a week_index 0 entry, and every distributor_pct in [0,1]."""
    if not isinstance(schedule, list) or len(schedule) == 0:
        raise E.invalid_request("split_schedule must be a non-empty array")
    has_week0 = False
    for term in schedule:
        if not isinstance(term, dict):
            raise E.invalid_request("split_schedule entries must be objects")
        wi = term.get("week_index")
        pct = term.get("distributor_pct")
        if not C.is_int(wi) or wi < 0:
            raise E.invalid_request("week_index must be an integer >= 0")
        if not C.is_number(pct):
            raise E.invalid_request("distributor_pct must be a number")
        if wi == 0:
            has_week0 = True
    # ERR_INVALID_SPLIT_SCHEDULE (priority 17) for the domain content check.
    if not has_week0:
        raise E.APIError(E.ERR_INVALID_SPLIT_SCHEDULE, 422, "split_schedule missing a week_index 0 entry")
    for term in schedule:
        pct = term["distributor_pct"]
        if pct < 0 or pct > 1:
            raise E.APIError(E.ERR_INVALID_SPLIT_SCHEDULE, 422, "distributor_pct must be in [0,1]")


@bp.route("/films", methods=["POST"])
def create_film():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    body = C.get_body()
    C.require_fields(body, ["title", "runtime_minutes", "distributor_id", "release_date", "split_schedule"])
    title = C.require_str(body, "title")
    runtime = C.require_int(body, "runtime_minutes")
    if runtime < 1:
        raise E.invalid_request("runtime_minutes must be >= 1")
    distributor_id = C.require_str(body, "distributor_id")
    release_raw = C.require_str(body, "release_date")
    release_dt = C.parse_iso(release_raw)
    schedule = body["split_schedule"]

    # Existence (priority 4) before the split-schedule business check (priority 17).
    get_or_404(db.distributors, distributor_id, "Distributor")

    _validate_split_schedule(schedule)

    film = C.new_common_fields()
    film.update({
        "title": title,
        "runtime_minutes": runtime,
        "distributor_id": distributor_id,
        "release_date": release_raw,
        "split_schedule": schedule,
        "status": "BOOKING",
    })
    film["_release_dt"] = release_dt
    db.films[film["id"]] = film
    return response.ok_object(C.serialize(film), 201)


@bp.route("/films/<film_id>", methods=["GET"])
def get_film(film_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT, DISTRIBUTOR})
    film = get_or_404(db.films, film_id, "Film")
    require_distributor_owns_film(film)
    return response.ok_object(C.serialize(film), 200)


@bp.route("/films", methods=["GET"])
def list_films():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, DISTRIBUTOR})
    limit, offset = C.parse_pagination()
    distributor_id = request.args.get("distributor_id")
    status = request.args.get("status")
    items = list(db.films.values())
    # Distributor scope: only own films.
    from middleware import current_role, current_user_id
    if current_role() == DISTRIBUTOR:
        items = [f for f in items if f["distributor_id"] == current_user_id()]
    if distributor_id is not None:
        items = [f for f in items if f["distributor_id"] == distributor_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/films/<film_id>/end-run", methods=["POST"])
def end_run(film_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    film = get_or_404(db.films, film_id, "Film")
    if film["status"] != "RUNNING":
        raise E.invalid_state("Film must be RUNNING to end its run")
    # No showtime of this film may remain SCHEDULED or ON_SALE.
    for st in db.showtimes.values():
        if st["film_id"] == film_id and st["status"] in ("SCHEDULED", "ON_SALE"):
            raise E.invalid_state("Film has SCHEDULED or ON_SALE showtimes")
    film["status"] = "ENDED"
    C.touch(film)
    return response.ok_object(C.serialize(film), 200)
