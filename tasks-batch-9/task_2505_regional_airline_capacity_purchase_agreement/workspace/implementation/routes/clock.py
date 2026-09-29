"""The logical clock (PRD 2.5): the only way the service's notion of now moves."""

from flask import Blueprint

import validate
from auth import ROLE_CPA_ADMINISTRATOR, require
from core import clock, parse_date
from db import store, touch, values
from response import empty_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def set_current_utc():
    data = validate.body()
    _, instant = validate.datetime_field(data, "to_iso8601")

    clock.set(instant)

    # One sweep: ACTIVE agreements whose term ended strictly before the new date.
    new_date = instant.date()
    for agreement in values(store.agreements):
        if agreement["status"] != "ACTIVE":
            continue
        term_end = parse_date(agreement["term_end_date"])
        if term_end is not None and term_end < new_date:
            agreement["status"] = "EXPIRED"
            touch(agreement)

    return empty_response(200)
