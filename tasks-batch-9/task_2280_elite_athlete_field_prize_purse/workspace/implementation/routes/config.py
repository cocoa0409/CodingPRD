"""Edition configuration: purse lines and division standards (PRD 3.1)."""
from flask import Blueprint

from constants import DIVISIONS, GENDERS, PURSE_CATEGORIES
from db import db, new_record
from errors import err, invalid
from middleware import authenticate
from response import object_response
from services import gates, lookup, serializers
from validators import get_body, obool, oint, present, renum, rint, rstr

bp = Blueprint("config", __name__)

_NEEDS_DIVISION = ("DIVISION", "TIME_BONUS", "RECORD_BONUS")
_NEEDS_PLACE = ("OVERALL", "DIVISION", "MASTERS")


@bp.post("/purse-lines")
def create_purse_line():
    authenticate(("ElitesDirector",))
    body = get_body()
    edition_id = rstr(body, "race_edition_id")
    edition = lookup.get_edition(edition_id)

    category = renum(body, "category", PURSE_CATEGORIES)
    gender = renum(body, "gender", GENDERS)
    amount_cents = rint(body, "amount_cents", minimum=1)

    if category in _NEEDS_DIVISION:
        division = renum(body, "division", DIVISIONS)
    else:
        if present(body, "division"):
            raise invalid("division must be null for %s purse lines" % category)
        division = None

    if category in _NEEDS_PLACE:
        place = rint(body, "place", minimum=1, maximum=20)
    else:
        if present(body, "place"):
            raise invalid("place must be null for %s purse lines" % category)
        place = None

    if category == "TIME_BONUS":
        threshold_seconds = rint(body, "threshold_seconds", minimum=1)
    else:
        if present(body, "threshold_seconds"):
            raise invalid("threshold_seconds must be null for %s purse lines" % category)
        threshold_seconds = None

    gates.gate_edition(edition, ("PLANNING",))

    for line in lookup.edition_purse_lines(edition_id):
        if (
            line["category"] == category
            and line["division"] == division
            and line["gender"] == gender
            and line["place"] == place
            and line["threshold_seconds"] == threshold_seconds
        ):
            raise err("ERR_CONFIG_DUPLICATE", "A purse line with this key already exists")

    line = new_record(
        race_edition_id=edition_id,
        category=category,
        division=division,
        gender=gender,
        place=place,
        threshold_seconds=threshold_seconds,
        amount_cents=amount_cents,
    )
    db.purse_lines[line["id"]] = line
    return object_response(serializers.ser_purse_line(line), 201)


@bp.post("/division-standards")
def create_division_standard():
    authenticate(("ElitesDirector",))
    body = get_body()
    edition_id = rstr(body, "race_edition_id")
    edition = lookup.get_edition(edition_id)

    division = renum(body, "division", DIVISIONS)
    gender = renum(body, "gender", GENDERS)
    max_qualifying_seconds = rint(body, "max_qualifying_seconds", minimum=1)
    bib_range_start = rint(body, "bib_range_start", minimum=1, maximum=9999)
    bib_range_end = rint(body, "bib_range_end", minimum=1)
    if bib_range_end < bib_range_start:
        raise invalid("bib_range_end must not be smaller than bib_range_start")
    window_months = oint(body, "window_months", 24, 1, 60)
    requires_chip_timing = obool(body, "requires_chip_timing", True)

    gates.gate_edition(edition, ("PLANNING",))

    if lookup.find_standard(edition_id, division, gender) is not None:
        raise err(
            "ERR_CONFIG_DUPLICATE",
            "A division standard already exists for this division and gender",
        )

    standard = new_record(
        race_edition_id=edition_id,
        division=division,
        gender=gender,
        max_qualifying_seconds=max_qualifying_seconds,
        window_months=window_months,
        requires_chip_timing=requires_chip_timing,
        bib_range_start=bib_range_start,
        bib_range_end=bib_range_end,
    )
    db.division_standards[standard["id"]] = standard
    return object_response(serializers.ser_standard(standard), 201)
