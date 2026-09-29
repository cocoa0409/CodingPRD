"""Species registration and reads."""

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc

bp = Blueprint("species", __name__)

TAXON_GROUPS = ("ELASMOBRANCH", "TELEOST", "INVERTEBRATE", "MARINE_MAMMAL", "REPTILE", "BIRD")
PROTECTION_STATUSES = ("UNLISTED", "CITES_APPENDIX_II", "CITES_APPENDIX_I", "ESA_LISTED")
RATINGS = ("GREEN", "YELLOW", "RED")

SPECIES_COMPUTED = ("wild_take_quota_reserved", "permit_required")


@bp.route("/aquarium/species", methods=["POST"])
def create_species():
    M.authenticate({M.CURATOR})
    body = M.json_body()
    V.reject_computed(body, SPECIES_COMPUTED)
    scientific_name = V.as_str(body, "scientific_name", required=True)
    common_name = V.as_str(body, "common_name", required=True)
    taxon_group = V.as_enum(body, "taxon_group", TAXON_GROUPS, required=True)
    protection_status = V.as_enum(body, "protection_status", PROTECTION_STATUSES, required=True)
    rating = V.as_enum(body, "sustainability_rating", RATINGS, required=True)
    bioload = V.as_dec(body, "bioload_units_per_specimen", required=True, exclusive_minimum=0)
    base_days = V.as_int(body, "base_quarantine_days", required=True, minimum=1, maximum=180)
    quota = V.as_int(body, "wild_take_quota_annual", default=0, minimum=0)

    for row in db.db.species.values():
        if row["scientific_name"] == scientific_name:
            raise ApiError("ERR_DUPLICATE_CODE")

    row = db.new_row()
    row.update({
        "scientific_name": scientific_name,
        "common_name": common_name,
        "taxon_group": taxon_group,
        "protection_status": protection_status,
        "sustainability_rating": rating,
        "bioload_units_per_specimen": bioload,
        "base_quarantine_days": base_days,
        "wild_take_quota_annual": quota,
        "wild_take_quota_reserved": 0,
        "permit_required": False,
    })
    row["permit_required"] = calc.species_permit_required(row)
    db.insert("species", row)
    return response.object_response(S.species(row), 201)


@bp.route("/aquarium/species", methods=["GET"])
def list_species():
    M.authenticate(M.NON_LIAISON)
    taxon_group = M.enum_param("taxon_group", TAXON_GROUPS)
    protection_status = M.enum_param("protection_status", PROTECTION_STATUSES)
    rating = M.enum_param("sustainability_rating", RATINGS)
    limit, offset = M.pagination()

    def keep(row):
        if taxon_group is not None and row["taxon_group"] != taxon_group:
            return False
        if protection_status is not None and row["protection_status"] != protection_status:
            return False
        if rating is not None and row["sustainability_rating"] != rating:
            return False
        return True

    rows = db.ordered("species", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.species(r) for r in page], limit, offset, total)


@bp.route("/aquarium/species/<row_id>", methods=["GET"])
def get_species(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("species", row_id)
    return response.object_response(S.species(row))
