"""ComplianceLetter endpoints (PRD 3.7). Letters are immutable artifacts."""
from flask import Blueprint

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import get_job, sorted_created, touch
from util import as_enum, as_str, body, pagination_args, reject_unknown, required

bp = Blueprint("letters", __name__)


@bp.post("/label-jobs/jobs/<job_id>/compliance-letters")
def issue_letter(job_id):
    auth(["QualityManager"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, {"letter_type", "body"})
    letter_type = as_enum(required(data, "letter_type"), "letter_type", {"FOOD_CONTACT"})
    letter_body = as_str(required(data, "body"), "body")
    if job["status"] not in ("PRINTED", "REWOUND"):
        raise ApiError(
            "ERR_JOB_NOT_READY_FOR_LETTER",
            409,
            "compliance letter issuance requires job in PRINTED or REWOUND",
        )
    # One FOOD_CONTACT letter per job.
    if any(
        l["job_id"] == job_id and l["letter_type"] == "FOOD_CONTACT"
        for l in DB["letters"].values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_LETTER",
            409,
            "a FOOD_CONTACT compliance letter already exists for this job",
        )
    # Issuance re-applies the component gate (PRD 3.7).
    substrate = DB["substrates"][job["substrate_id"]]
    ink_recipe = DB["ink_recipes"][job["ink_recipe_id"]]
    if not (
        substrate["food_contact_certified"] and ink_recipe["food_contact_compliant"]
    ):
        raise ApiError(
            "ERR_FOOD_CONTACT_COMPONENT",
            422,
            "substrate and ink recipe must both be food-contact qualified",
        )
    ts = now_iso()
    letter = {
        "id": new_id(),
        "job_id": job_id,
        "letter_type": letter_type,
        "issued_at": ts,
        "body": letter_body,
        "created_at": ts,
    }
    DB["letters"][letter["id"]] = letter
    # Letter issuance legitimately mutates the job (PRD 2.8).
    touch(job)
    return ok(letter, 201)


@bp.get("/label-jobs/jobs/<job_id>/compliance-letters")
def list_letters(job_id):
    auth(ALL_ROLES)
    get_job(job_id)
    limit, offset = pagination_args()
    items = sorted_created(l for l in DB["letters"].values() if l["job_id"] == job_id)
    return ok_list(items[offset : offset + limit], len(items), limit, offset)
