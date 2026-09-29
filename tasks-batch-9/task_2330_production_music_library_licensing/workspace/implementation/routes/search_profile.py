"""The singleton CatalogSearchProfile (PRD §3.3)."""

from decimal import Decimal

from flask import Blueprint

from db import DB
from errors import fail
from middleware import body, opt_int, opt_number, req_int, require_role
from response import object_response
from routes.common import PREFIX
from services import calc
from services.cascade import bump_once
from services.derive import serialize_profile

bp = Blueprint("search_profile", __name__)


@bp.put(PREFIX + "/search-profile")
def put_profile():
    data = body()
    mood = req_int(data, "weight_mood", 0, 100)
    genre = req_int(data, "weight_genre", 0, 100)
    instrumentation = req_int(data, "weight_instrumentation", 0, 100)
    tempo = req_int(data, "weight_tempo", 0, 100)
    tolerance = opt_int(data, "tempo_tolerance_bpm", 1, 60, 20)
    factor = opt_number(data, "restricted_availability_factor", 0, 1, "0.60")
    require_role("CatalogAdmin")

    if mood + genre + instrumentation + tempo != 100:                    # 48
        fail("ERR_WEIGHTS_NOT_100", "the four facet weights must sum to 100.")

    row = DB.search_profile
    created = row is None
    if created:
        row = DB.new_row()
        DB.search_profile = row
    row.update(
        {
            "weight_mood": mood,
            "weight_genre": genre,
            "weight_instrumentation": instrumentation,
            "weight_tempo": tempo,
            "tempo_tolerance_bpm": tolerance,
            "_restricted_availability_factor": calc.dp2(factor),
        }
    )
    if not created:
        bump_once(row)
    return object_response(serialize_profile(row))


@bp.get(PREFIX + "/search-profile")
def get_profile():
    require_role("CatalogAdmin", "LicensingAgent")
    row = DB.search_profile
    if row is None:
        fail("ERR_SEARCH_PROFILE_NOT_FOUND", "the search profile has never been written.")
    return object_response(serialize_profile(row))
