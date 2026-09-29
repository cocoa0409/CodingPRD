"""Patient medical records (PRD §3.1)."""

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import matches, str_arg
from response import envelope, paged, pagination_params
from services import COMORBIDITY_TIERS, by_seq, require, stamp_new
from util import Body, serialize

bp = Blueprint("patients", __name__)


@bp.post("/patients")
def create_patient():
    authenticate(("NurseCaseManager",))
    body = Body(request.get_json(silent=True))

    facility_id = body.id_field("facility_id")
    mrn = body.str_field("mrn", min_len=1)
    full_name = body.str_field("full_name", min_len=1)
    birth_date = body.date_field("birth_date")
    impairment_group_code = body.str_field("impairment_group_code", pattern=r"^\d{4}$")
    etiologic_diagnosis_code = body.str_field("etiologic_diagnosis_code", min_len=1)
    comorbidity_tier = body.enum_field("comorbidity_tier", COMORBIDITY_TIERS)

    # ladder rank 10 — body identifier existence
    require(store.facilities, facility_id)

    # ladder rank 40 — mrn uniqueness per facility
    for existing in store.patients.values():
        if existing["facility_id"] == facility_id and existing["mrn"] == mrn:
            raise ApiError("ERR_MRN_DUPLICATE")

    patient = stamp_new({
        "facility_id": facility_id,
        "mrn": mrn,
        "full_name": full_name,
        "birth_date": birth_date.isoformat(),
        "impairment_group_code": impairment_group_code,
        "etiologic_diagnosis_code": etiologic_diagnosis_code,
        "comorbidity_tier": comorbidity_tier,
    })
    store.patients[patient["id"]] = patient
    return envelope(serialize(patient), 201)


@bp.get("/patients/<patient_id>")
def get_patient(patient_id):
    authenticate(ALL_ROLES)
    patient = require(store.patients, patient_id)
    return envelope(serialize(patient), 200)


@bp.get("/patients")
def list_patients():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {"facility_id": str_arg("facility_id"), "mrn": str_arg("mrn")}
    items = [p for p in by_seq(list(store.patients.values())) if matches(p, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(p) for p in page], 200, pagination)
