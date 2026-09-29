"""Applicant demographics and the collection-method rules (PRD 3.3)."""

from flask import Blueprint

import constants as C
import serializers as S
import store
from auth import authenticate
from errors import fail
from response import object_response
from validate import Field, check, json_body, lookup

bp = Blueprint("demographics", __name__)

CREATE_FIELDS = [
    Field("application_id", "string", required=True),
    Field("applicant_role", "string", required=True, enum=C.APPLICANT_ROLES),
    Field("collection_method", "string", required=True, enum=C.COLLECTION_METHODS),
    Field("ethnicity_codes", "array", required=True, member_enum=C.ETHNICITY_CODES),
    Field("race_codes", "array", required=True, member_enum=C.RACE_CODES),
    Field("sex_code", "string", required=True, enum=C.SEX_CODES),
    Field("is_natural_person", "boolean"),
    Field("age_years", "integer"),
    Field("observation_basis", "string", enum=C.OBSERVATION_BASES),
]

PATCH_FIELDS = [
    Field("collection_method", "string", enum=C.COLLECTION_METHODS),
    Field("ethnicity_codes", "array", member_enum=C.ETHNICITY_CODES),
    Field("race_codes", "array", member_enum=C.RACE_CODES),
    Field("sex_code", "string", enum=C.SEX_CODES),
    Field("age_years", "integer"),
    Field("observation_basis", "string", enum=C.OBSERVATION_BASES),
    Field("is_natural_person", "boolean"),
]


def collection_rules(channel, row):
    """The four collection rules of PRD 3.3, evaluated in the stated order."""
    method = row["collection_method"]
    ethnicity = row["ethnicity_codes"] or []
    race = row["race_codes"] or []
    sex = row["sex_code"]
    natural = row["is_natural_person"]

    # 1. Visual observation requires an in-person application.
    if method == "VISUAL_OBSERVATION_OR_SURNAME" and channel != "FACE_TO_FACE":
        fail("ERR_VISUAL_OBSERVATION_NOT_PERMITTED")

    # 2. Observation may only produce aggregate categories.
    if method == "VISUAL_OBSERVATION_OR_SURNAME":
        for code in ethnicity:
            if code not in C.OBSERVABLE_ETHNICITY:
                fail("ERR_DISAGGREGATED_CODE_NOT_PERMITTED")
        for code in race:
            if code not in C.OBSERVABLE_RACE:
                fail("ERR_DISAGGREGATED_CODE_NOT_PERMITTED")
        if sex not in C.OBSERVABLE_SEX:
            fail("ERR_DISAGGREGATED_CODE_NOT_PERMITTED")

    # 3. In-person applications may not simply decline.
    if channel == "FACE_TO_FACE" and natural is True and method == "NOT_PROVIDED_BY_APPLICANT":
        fail("ERR_OBSERVATION_REQUIRED_FOR_IN_PERSON")

    # 4. Non-natural persons carry nothing.
    if natural is False:
        if method != "NOT_APPLICABLE":
            fail("ERR_NON_NATURAL_PERSON_MISMATCH")
        for code in ethnicity:
            if code != "NOT_APPLICABLE":
                fail("ERR_NON_NATURAL_PERSON_MISMATCH")
        for code in race:
            if code != "NOT_APPLICABLE":
                fail("ERR_NON_NATURAL_PERSON_MISMATCH")
        if sex != "NOT_APPLICABLE":
            fail("ERR_NON_NATURAL_PERSON_MISMATCH")


def array_limits(row):
    """Ladder step 15 -- both limits surface as ERR_TOO_MANY_RACE_CODES."""
    if len(row["race_codes"] or []) > C.MAX_RACE_CODES:
        fail("ERR_TOO_MANY_RACE_CODES")
    if len(row["ethnicity_codes"] or []) > C.MAX_ETHNICITY_CODES:
        fail("ERR_TOO_MANY_RACE_CODES")


@bp.route("/hmda/demographic-entries", methods=["POST"])
def create_demographic_entry():
    authenticate(["LoanOfficer"])
    body = check(json_body(), CREATE_FIELDS)
    app = lookup(store.applications, body["application_id"], "ERR_APPLICATION_NOT_FOUND")

    candidate = {
        "collection_method": body["collection_method"],
        "ethnicity_codes": body["ethnicity_codes"],
        "race_codes": body["race_codes"],
        "sex_code": body["sex_code"],
        "is_natural_person": (True if body.get("is_natural_person") is None
                              else body["is_natural_person"]),
    }
    collection_rules(app["application_channel"], candidate)

    for existing in store.demographic_entries.values():
        if (existing["application_id"] == app["id"]
                and existing["applicant_role"] == body["applicant_role"]):
            fail("ERR_DUPLICATE_DEMOGRAPHIC_ROLE")
    array_limits(candidate)

    row = store.new_row()
    row.update({
        "application_id": app["id"],
        "applicant_role": body["applicant_role"],
        "is_natural_person": candidate["is_natural_person"],
        "collection_method": candidate["collection_method"],
        "ethnicity_codes": list(candidate["ethnicity_codes"]),
        "race_codes": list(candidate["race_codes"]),
        "sex_code": candidate["sex_code"],
        "age_years": body.get("age_years"),
        "observation_basis": (body.get("observation_basis")
                              if body.get("observation_basis") is not None else "NOT_OBSERVED"),
        "status": "RECORDED",
    })
    store.demographic_entries[row["id"]] = row
    return object_response(S.demographic_entry(row), 201)


@bp.route("/hmda/demographic-entries/<entry_id>", methods=["PATCH"])
def patch_demographic_entry(entry_id):
    authenticate(["LoanOfficer"])
    row = lookup(store.demographic_entries, entry_id, "ERR_DEMOGRAPHIC_ENTRY_NOT_FOUND")
    body = check(json_body(), PATCH_FIELDS)
    app = store.applications[row["application_id"]]
    if app["stage"] == "ARCHIVED":
        fail("ERR_APPLICATION_ARCHIVED")

    merged = {
        "collection_method": row["collection_method"],
        "ethnicity_codes": list(row["ethnicity_codes"]),
        "race_codes": list(row["race_codes"]),
        "sex_code": row["sex_code"],
        "is_natural_person": row["is_natural_person"],
    }
    for name in ("collection_method", "ethnicity_codes", "race_codes", "sex_code",
                 "is_natural_person"):
        if name in body and body[name] is not None:
            merged[name] = body[name]

    collection_rules(app["application_channel"], merged)
    array_limits(merged)

    row["collection_method"] = merged["collection_method"]
    row["ethnicity_codes"] = list(merged["ethnicity_codes"])
    row["race_codes"] = list(merged["race_codes"])
    row["sex_code"] = merged["sex_code"]
    row["is_natural_person"] = merged["is_natural_person"]
    if "age_years" in body:
        row["age_years"] = body["age_years"]
    if "observation_basis" in body and body["observation_basis"] is not None:
        row["observation_basis"] = body["observation_basis"]
    row["status"] = "AMENDED"
    store.bump(row)
    return object_response(S.demographic_entry(row))
