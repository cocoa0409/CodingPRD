"""Composition endpoints, including the facet search (PRD §3.2, §3.3)."""

from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import fail
from middleware import (
    ALL_STAFF,
    body,
    opt_enum,
    opt_enum_array,
    opt_int,
    opt_string,
    req_enum,
    req_enum_array,
    req_int,
    req_string,
    require_role,
)
from response import object_response, page_response, pagination
from routes.common import (
    GENRES,
    INSTRUMENTS,
    MOODS,
    PREFIX,
    require_state,
)
from services import calc
from services.cascade import bump_once
from services.derive import (
    active_license_count,
    lookup,
    rows,
    serialize_composition,
)

bp = Blueprint("compositions", __name__)

ALL_ROLES = ALL_STAFF + ("Composer", "Licensee")


@bp.post(PREFIX + "/compositions")
def create_composition():
    data = body()
    composer_id = req_string(data, "composer_id")
    agreement_id = req_string(data, "agreement_id")
    title = req_string(data, "title", allow_empty=False)
    duration = req_int(data, "duration_sec", 1, 3600)
    tempo = req_int(data, "tempo_bpm", 40, 240)
    genre = req_enum(data, "genre", GENRES)
    moods = req_enum_array(data, "mood_tags", MOODS, 0, 5)
    instruments = req_enum_array(data, "instrumentation", INSTRUMENTS, 0, 6)

    composer = lookup("composers", composer_id)                 # 3 body FK order
    agreement = lookup("agreements", agreement_id)
    require_role("CatalogAdmin")

    row = DB.new_row()
    row.update(
        {
            "composer_id": composer["id"],
            "agreement_id": agreement["id"],
            "title": title,
            "duration_sec": duration,
            "tempo_bpm": tempo,
            "genre": genre,
            "mood_tags": moods,
            "instrumentation": instruments,
            "catalog_status": "INGESTED",
            "availability_status": "AVAILABLE",
        }
    )
    DB.compositions[row["id"]] = row
    return object_response(serialize_composition(row), 201)


@bp.get(PREFIX + "/compositions/search")
def search_compositions():
    limit, offset = pagination(request.args)
    require_role("CatalogAdmin", "LicensingAgent", "Licensee")
    profile = DB.search_profile
    if profile is None:
        fail("ERR_SEARCH_PROFILE_NOT_FOUND", "the search profile has never been written.")

    moods = _facet_list(request.args, "mood_tags")
    instruments = _facet_list(request.args, "instrumentation")
    genre = request.args.get("genre") or None
    tempo_raw = request.args.get("tempo_bpm")
    tempo = None
    if tempo_raw not in (None, ""):
        try:
            tempo = int(str(tempo_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "tempo_bpm must be an integer.")

    eligible = [
        c for c in rows("compositions")
        if c["catalog_status"] == "CATALOGED"
        and c["availability_status"] in ("AVAILABLE", "RESTRICTED")
    ]
    scored = []
    for comp in eligible:
        scored.append((comp, _relevance(comp, profile, moods, genre, instruments, tempo)))
    scored.sort(key=lambda pair: (-pair[1], pair[0]["created_at"], pair[0]["id"]))
    ordered = [pair for pair in scored]
    total = len(ordered)
    page = ordered[offset:offset + limit]
    from response import array_response

    data = [serialize_composition(comp, score) for comp, score in page]
    return array_response(data, limit, offset, total)


def _facet_list(args, name):
    values = []
    for raw in args.getlist(name):
        for part in str(raw).split(","):
            part = part.strip()
            if part:
                values.append(part)
    return values or None


def _relevance(comp, profile, moods, genre, instruments, tempo):
    numerator = Decimal("0")
    denominator = Decimal("0")
    if moods:
        weight = Decimal(profile["weight_mood"])
        hit = len(set(moods) & set(comp["mood_tags"]))
        numerator += weight * (Decimal(hit) / Decimal(len(moods)))
        denominator += weight
    if genre:
        weight = Decimal(profile["weight_genre"])
        numerator += weight * (Decimal(1) if comp["genre"] == genre else Decimal(0))
        denominator += weight
    if instruments:
        weight = Decimal(profile["weight_instrumentation"])
        hit = len(set(instruments) & set(comp["instrumentation"]))
        numerator += weight * (Decimal(hit) / Decimal(len(instruments)))
        denominator += weight
    if tempo is not None:
        weight = Decimal(profile["weight_tempo"])
        distance = Decimal(abs(comp["tempo_bpm"] - tempo))
        proximity = Decimal(1) - distance / Decimal(profile["tempo_tolerance_bpm"])
        if proximity < 0:
            proximity = Decimal(0)
        numerator += weight * proximity
        denominator += weight
    if denominator == 0:
        return Decimal("0.00")
    weighted = Decimal(100) * numerator / denominator
    factor = Decimal("1.00")
    if comp["availability_status"] == "RESTRICTED":
        factor = profile["_restricted_availability_factor"]
    recency = Decimal("1.00")
    age_days = (DB.now - comp["_created_dt"]).days
    if age_days <= calc.RECENCY_BOOST_DAYS:
        recency = calc.RECENCY_BOOST
    return calc.dp2(weighted * factor * recency)


@bp.get(PREFIX + "/compositions/<composition_id>")
def get_composition(composition_id):
    row = lookup("compositions", composition_id)
    require_role(*ALL_ROLES)
    return object_response(serialize_composition(row))


@bp.get(PREFIX + "/compositions")
def list_compositions():
    limit, offset = pagination(request.args)
    require_role(*ALL_STAFF)
    result = rows("compositions")
    for name in ("composer_id", "agreement_id", "catalog_status", "availability_status"):
        wanted = request.args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_composition)


@bp.patch(PREFIX + "/compositions/<composition_id>")
def patch_composition(composition_id):
    data = body()
    title = opt_string(data, "title", allow_empty=False)
    tempo = opt_int(data, "tempo_bpm", 40, 240)
    genre = opt_enum(data, "genre", GENRES)
    moods = opt_enum_array(data, "mood_tags", MOODS, 0, 5)
    instruments = opt_enum_array(data, "instrumentation", INSTRUMENTS, 0, 6)
    row = lookup("compositions", composition_id)
    require_role("CatalogAdmin")

    if title is not None:
        row["title"] = title
    if tempo is not None:
        row["tempo_bpm"] = tempo
    if genre is not None:
        row["genre"] = genre
    if moods is not None:
        row["mood_tags"] = moods
    if instruments is not None:
        row["instrumentation"] = instruments
    bump_once(row)
    return object_response(serialize_composition(row))


@bp.post(PREFIX + "/compositions/<composition_id>/catalog")
def catalog_composition(composition_id):
    row = lookup("compositions", composition_id)
    require_role("CatalogAdmin")
    require_state(row, "catalog_status", ("INGESTED",), "composition")
    agreement = DB.agreements.get(row["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":                 # 13
        fail("ERR_AGREEMENT_NOT_ACTIVE", "the governing agreement is not ACTIVE.")
    if not row["mood_tags"] or not row["instrumentation"]:                   # 36
        fail("ERR_METADATA_INCOMPLETE", "mood_tags and instrumentation are both required.")
    row["catalog_status"] = "CATALOGED"
    bump_once(row)
    return object_response(serialize_composition(row))


@bp.post(PREFIX + "/compositions/<composition_id>/retire")
def retire_composition(composition_id):
    data = body()
    reason = req_string(data, "reason", allow_empty=False)
    row = lookup("compositions", composition_id)
    require_role("CatalogAdmin")
    require_state(row, "catalog_status", ("INGESTED", "CATALOGED"), "composition")
    if active_license_count(row["id"]) > 0:                                  # 37
        fail("ERR_COMPOSITION_HAS_ACTIVE_LICENSES", "the work still has live licences.")
    row["catalog_status"] = "RETIRED"
    row["availability_status"] = "WITHDRAWN"
    row["retire_reason"] = reason
    bump_once(row)
    return object_response(serialize_composition(row))
