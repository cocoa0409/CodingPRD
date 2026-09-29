"""PRD 3.1 -- member jurisdictions and the social vulnerability overlay."""

import re

from flask import Blueprint

import calc
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_REGIONAL_ADMINISTRATOR, guard
from errors import fail

bp = Blueprint("jurisdictions", __name__)

STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED")
TIERS = ("LOW", "MODERATE", "HIGH", "SEVERE")
CODE_PATTERN = re.compile(r"^[A-Z0-9-]+$")


@bp.post("/resilience/jurisdictions")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def create_jurisdiction():
    body = validate.json_body()
    name = validate.string_field(body, "name", required=True, min_len=1, max_len=120)
    code = validate.string_field(
        body, "jurisdiction_code", required=True, min_len=3, max_len=32
    )
    if not CODE_PATTERN.match(code):
        validate.bad(
            "jurisdiction_code", "may contain only uppercase letters, digits and hyphens."
        )
    population = validate.int_field(body, "population", required=True, minimum=1)
    svi_score = validate.dec_field(body, "svi_score", required=True, minimum=0, maximum=1)
    weight = validate.int_field(
        body, "endorsement_weight", default=1, minimum=1, maximum=10
    )
    status = validate.enum_field(body, "status", STATUSES, default="ACTIVE")

    for row in store.jurisdictions.values():
        if row["jurisdiction_code"] == code:
            fail(
                "ERR_DUPLICATE_JURISDICTION_CODE",
                "jurisdiction_code %s is already held by another member." % code,
            )

    tier = calc.svi_tier(svi_score)
    record = store.insert(store.jurisdictions, {
        "name": name,
        "jurisdiction_code": code,
        "population": population,
        "svi_score": svi_score,
        "svi_tier": tier,
        "disadvantaged_flag": calc.disadvantaged(tier),
        "endorsement_weight": weight,
        "status": status,
    })
    return envelope.created(serialize.jurisdiction(record))


@bp.get("/resilience/jurisdictions")
@guard()
def list_jurisdictions():
    rows = envelope.match(
        store.ordered(store.jurisdictions),
        status=envelope.str_filter("status"),
        svi_tier=envelope.str_filter("svi_tier"),
        disadvantaged_flag=envelope.bool_filter("disadvantaged_flag"),
    )
    return envelope.listing(rows, serialize.jurisdiction)


@bp.get("/resilience/jurisdictions/<jurisdiction_id>")
@guard()
def get_jurisdiction(jurisdiction_id):
    row = lookup.need("jurisdiction", jurisdiction_id)
    return envelope.ok(serialize.jurisdiction(row))


@bp.patch("/resilience/jurisdictions/<jurisdiction_id>")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def amend_jurisdiction(jurisdiction_id):
    row = lookup.need("jurisdiction", jurisdiction_id)
    body = validate.json_body()
    status = validate.enum_field(body, "status", STATUSES)
    weight = validate.int_field(body, "endorsement_weight", minimum=1, maximum=10)
    svi_score = validate.dec_field(body, "svi_score", minimum=0, maximum=1)

    if status is not None:
        row["status"] = status
    if weight is not None:
        row["endorsement_weight"] = weight
    if svi_score is not None:
        row["svi_score"] = svi_score
        tier = calc.svi_tier(svi_score)
        row["svi_tier"] = tier
        row["disadvantaged_flag"] = calc.disadvantaged(tier)
    store.touch(row)
    return envelope.ok(serialize.jurisdiction(row))
