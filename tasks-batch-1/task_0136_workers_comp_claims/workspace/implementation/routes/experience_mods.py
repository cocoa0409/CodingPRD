"""ExperienceModEntry endpoints (PRD §3.12). Computes EMR; re-rates policies."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_DUPLICATE_RESOURCE
from middleware import require_auth, get_json_body
from response import ok_object
from services.validation import require_str, require_int, require_number
from services import calculations as calc
from services import reserve as reserve_svc
from routes._common import get_employer, get_experience_mod, assert_employer_owns_employer

bp = Blueprint("experience_mods", __name__)


@bp.post("/experience-mods")
def create_experience_mod():
    require_auth(["PlatformAdmin"])()
    body = get_json_body()

    employer_id = require_str(body, "employer_id")
    emp = get_employer(employer_id)

    rating_year = require_int(body, "rating_year")
    weighting_factor = require_number(body, "weighting_factor", minimum=0, maximum=1)
    ballast_cents = require_int(body, "ballast_cents", minimum=0)
    expected_primary_cents = require_int(body, "expected_primary_cents", minimum=1)
    expected_excess_cents = require_int(body, "expected_excess_cents", minimum=0)

    # Uniqueness (priority 12): one entry per (employer_id, rating_year).
    for e in db.experience_mods.values():
        if e["employer_id"] == employer_id and e["rating_year"] == rating_year:
            raise APIError(ERR_DUPLICATE_RESOURCE, 409,
                           "An experience-mod entry already exists for this employer/year")

    # Actual losses: sum of Reserve.total_incurred over the employer's non-DENIED
    # claims (PRD §3.12). A claim contributes only if it has a reserve.
    losses = []
    for claim in db.claims.values():
        if _employer_of_claim(claim) != employer_id:
            continue
        if claim["status"] == "DENIED":
            continue
        reserve = reserve_svc.reserve_for_claim(claim["id"])
        if reserve is not None:
            losses.append(reserve["total_incurred_cents"])

    mod_dec = calc.experience_mod(
        losses, weighting_factor, ballast_cents,
        expected_primary_cents, expected_excess_cents,
    )
    mod_factor = float(mod_dec)

    entry = {
        "employer_id": employer_id,
        "rating_year": rating_year,
        "weighting_factor": weighting_factor,
        "ballast_cents": ballast_cents,
        "expected_primary_cents": expected_primary_cents,
        "expected_excess_cents": expected_excess_cents,
        "mod_factor": mod_factor,
    }
    db.stamp_common(entry)
    db.experience_mods[entry["id"]] = entry

    # Cascade: employer.current_emr = mod_factor; re-rate every policy.
    emp["current_emr"] = mod_factor
    db.bump(emp)
    for pol in db.policies.values():
        if pol["employer_id"] == employer_id:
            pol["modified_premium_cents"] = calc.modified_premium(
                pol["manual_premium_cents"], mod_factor)
            db.bump(pol)

    return ok_object(entry, 201)


@bp.get("/experience-mods/<rid>")
def get_experience_mod_route(rid):
    require_auth(["PlatformAdmin", "Employer"])()
    entry = get_experience_mod(rid)
    assert_employer_owns_employer(entry["employer_id"])
    return ok_object(entry, 200)


def _employer_of_claim(claim):
    pol = db.policies.get(claim["policy_id"])
    return pol.get("employer_id") if pol else None
