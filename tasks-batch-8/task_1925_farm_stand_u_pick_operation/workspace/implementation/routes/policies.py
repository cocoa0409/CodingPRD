"""PricingPolicy endpoints (PRD §3.1, §2.6)."""

from flask import Blueprint, request

import db
import domain
from errors import raise_err, ERR_NOT_FOUND, ERR_STALE_VERSION
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_int,
    req_str,
    require,
)

bp = Blueprint("policies", __name__)

FM = ("FarmManager",)
READERS = ("FarmManager", "GateStaff", "FieldStaff")


@bp.post("/farm/pricing-policies")
def create_policy():
    require(FM)
    body = get_body()
    check_no_undeclared(
        body,
        {
            "season_id",
            "expected_season_version",
            "admission_per_person_cents",
            "container_fee_cents",
            "weekend_surge_bps",
            "bundle_discount_bps",
            "bundle_cap_cents",
        },
    )
    season_id = req_str(body, "season_id")
    expected = req_int(body, "expected_season_version")
    admission = req_int(body, "admission_per_person_cents", min_value=0)
    container_fee = req_int(body, "container_fee_cents", min_value=0)
    surge = req_int(body, "weekend_surge_bps", min_value=10000)
    bundle_bps = req_int(body, "bundle_discount_bps", min_value=0)
    bundle_cap = req_int(body, "bundle_cap_cents", min_value=0)
    season = db.seasons.get(season_id)
    if season is None:
        raise_err(ERR_NOT_FOUND, "season_id does not resolve")
    # OCC (PRD §2.6): expected_season_version must equal the season's version.
    if expected != season["version"]:
        raise_err(ERR_STALE_VERSION, "expected_season_version is stale")
    prior = next(
        (
            p
            for p in db.pricing_policies.values()
            if p["season_id"] == season_id and p["status"] == "ACTIVE"
        ),
        None,
    )
    policy = domain.new_entity()
    policy.update(
        {
            "season_id": season_id,
            "admission_per_person_cents": admission,
            "container_fee_cents": container_fee,
            "weekend_surge_bps": surge,
            "bundle_discount_bps": bundle_bps,
            "bundle_cap_cents": bundle_cap,
            "policy_version": (prior["policy_version"] + 1) if prior else 1,
            "status": "ACTIVE",
        }
    )
    db.pricing_policies[policy["id"]] = policy
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        domain.touch(prior)
    # Supersession is a mutation of the season: Season.version increments by 1.
    domain.touch(season)
    return ok_object(domain.serialize_policy(policy), 201)


@bp.get("/farm/pricing-policies/<pid>")
def get_policy(pid):
    require(READERS)
    policy = db.pricing_policies.get(pid)
    if policy is None:
        raise_err(ERR_NOT_FOUND, "PricingPolicy not found")
    return ok_object(domain.serialize_policy(policy))


@bp.get("/farm/pricing-policies")
def list_policies():
    require(READERS)
    items = list(db.pricing_policies.values())
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [p for p in items if p["season_id"] == season_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, domain.serialize_policy)
