from flask import Blueprint

import constants as C
import serializers
import validation as V
from envelope import object_response
from lookups import path_row
from store import db

bp = Blueprint("applicants", __name__)


def _demographics_complete(row):
    for field in ("full_name", "date_of_birth", "sex", "place_of_birth"):
        value = row.get(field)
        if value is None:
            return False
        if isinstance(value, str) and value == "":
            return False
    return True


@bp.post("/livescan/applicants")
def create_applicant():
    data = V.body()
    full_name = V.req_string(data, "full_name")
    date_of_birth = V.req_date(data, "date_of_birth")
    sex = V.req_string(data, "sex")
    id_document_type = V.req_string(data, "id_document_type")
    id_document_expires_on = V.req_date(data, "id_document_expires_on")
    place_of_birth = V.opt_string(data, "place_of_birth")

    V.enum_value("sex", sex, C.SEXES)
    V.enum_value("id_document_type", id_document_type, C.ID_DOCUMENT_TYPES)

    fields = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "sex": sex,
        "place_of_birth": place_of_birth,
        "id_document_type": id_document_type,
        "id_document_expires_on": id_document_expires_on,
        "demographics_complete": False,
    }
    fields["demographics_complete"] = _demographics_complete(fields)
    row = db.create("applicants", fields)
    return object_response(serializers.applicant(row), 201)


@bp.get("/livescan/applicants/<id>")
def read_applicant(id):
    return object_response(serializers.applicant(path_row("applicants", id)))


@bp.patch("/livescan/applicants/<id>")
def correct_applicant(id):
    row = path_row("applicants", id)
    data = V.body()
    place_of_birth = V.opt_string(data, "place_of_birth", default=None)
    id_document_type = V.opt_string(data, "id_document_type", default=None)
    id_document_expires_on = V.opt_date(data, "id_document_expires_on", default=None)
    if id_document_type is not None:
        V.enum_value("id_document_type", id_document_type, C.ID_DOCUMENT_TYPES)

    changed = False
    if "place_of_birth" in data and data["place_of_birth"] is not None:
        if row["place_of_birth"] != place_of_birth:
            changed = True
        row["place_of_birth"] = place_of_birth
    if id_document_type is not None:
        if row["id_document_type"] != id_document_type:
            changed = True
        row["id_document_type"] = id_document_type
    if id_document_expires_on is not None:
        if row["id_document_expires_on"] != id_document_expires_on:
            changed = True
        row["id_document_expires_on"] = id_document_expires_on

    complete = _demographics_complete(row)
    if row["demographics_complete"] != complete:
        changed = True
    row["demographics_complete"] = complete
    if changed:
        db.touch(row)
    return object_response(serializers.applicant(row))
