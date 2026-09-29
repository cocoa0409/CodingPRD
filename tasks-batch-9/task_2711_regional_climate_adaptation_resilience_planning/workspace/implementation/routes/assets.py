"""PRD 3.4 -- the lifeline dependency graph and asset criticality ranking."""

from flask import Blueprint

import calc
import cascades
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_HAZARD_ANALYST, ROLE_REGIONAL_ADMINISTRATOR, guard
from core import dec
from errors import fail

bp = Blueprint("assets", __name__)

ASSET_CLASSES = ("WATER", "POWER", "TRANSPORT", "HEALTH", "COMMS")
AMENDABLE_STATUSES = ("UNRANKED", "RECOMPUTE_REQUIRED")


@bp.post("/resilience/assets")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def create_asset():
    body = validate.json_body()
    jurisdiction = lookup.need_ref("jurisdiction", body, "jurisdiction_id")
    if jurisdiction is None:
        validate.bad("jurisdiction_id", "is required.")
    upstream = lookup.need_ref("asset", body, "upstream_asset_id")

    asset_class = validate.enum_field(body, "asset_class", ASSET_CLASSES, required=True)
    name = validate.string_field(body, "name", required=True, min_len=1, max_len=120)
    replacement = validate.int_field(
        body, "replacement_value_cents", required=True, minimum=1
    )
    service_population = validate.int_field(
        body, "service_population", required=True, minimum=0
    )
    redundancy = validate.dec_field(
        body, "redundancy_factor", required=True, minimum=0, maximum=1
    )
    is_shared = validate.bool_field(body, "is_shared", default=False)

    record = {
        "jurisdiction_id": jurisdiction["id"],
        "upstream_asset_id": upstream["id"] if upstream is not None else None,
        "asset_class": asset_class,
        "name": name,
        "replacement_value_cents": replacement,
        "service_population": service_population,
        "redundancy_factor": redundancy,
        "is_shared": is_shared,
        "criticality_status": "UNRANKED",
        "consequence_score": None,
        "criticality_tier": None,
        "dependency_depth": None,
    }
    store.insert(store.assets, record)
    # the chain is walked on creation as well as on amendment and on ranking
    try:
        cascades.walk_asset_chain(record["id"], record["upstream_asset_id"])
    except Exception:
        del store.assets[record["id"]]
        raise
    return envelope.created(serialize.asset(record))


@bp.get("/resilience/assets")
@guard()
def list_assets():
    rows = envelope.match(
        store.ordered(store.assets),
        jurisdiction_id=envelope.str_filter("jurisdiction_id"),
        upstream_asset_id=envelope.str_filter("upstream_asset_id"),
        asset_class=envelope.str_filter("asset_class"),
        criticality_status=envelope.str_filter("criticality_status"),
        criticality_tier=envelope.str_filter("criticality_tier"),
        is_shared=envelope.bool_filter("is_shared"),
    )
    return envelope.listing(rows, serialize.asset)


@bp.get("/resilience/assets/<asset_id>")
@guard()
def get_asset(asset_id):
    row = lookup.need("asset", asset_id)
    return envelope.ok(serialize.asset(row))


@bp.patch("/resilience/assets/<asset_id>")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def amend_asset(asset_id):
    asset = lookup.need("asset", asset_id)
    body = validate.json_body()
    upstream = lookup.need_ref("asset", body, "upstream_asset_id")
    is_shared = validate.bool_field(body, "is_shared")
    if asset["criticality_status"] not in AMENDABLE_STATUSES:
        fail("ERR_ASSET_ALREADY_RANKED", "A RANKED asset may not be amended.")

    upstream_id = asset["upstream_asset_id"]
    if "upstream_asset_id" in body:
        upstream_id = upstream["id"] if upstream is not None else None
    cascades.walk_asset_chain(asset["id"], upstream_id)

    asset["upstream_asset_id"] = upstream_id
    if is_shared is not None:
        asset["is_shared"] = is_shared
    store.touch(asset)
    return envelope.ok(serialize.asset(asset))


@bp.post("/resilience/assets/<asset_id>/criticality-ranking")
@guard(ROLE_HAZARD_ANALYST)
def rank_asset(asset_id):
    asset = lookup.need("asset", asset_id)
    if asset["criticality_status"] not in AMENDABLE_STATUSES:
        fail("ERR_ASSET_ALREADY_RANKED", "This asset is already RANKED.")
    depth = cascades.walk_asset_chain(asset["id"], asset["upstream_asset_id"])
    assessed = lookup.assessments_of_asset(asset["id"], status="ASSESSED")
    if not assessed:
        fail(
            "ERR_NO_ASSESSED_VULNERABILITY",
            "The asset has no vulnerability assessment in ASSESSED status.",
        )

    peak = max(dec(row["vulnerability_score"]) for row in assessed)
    _exposed, score, tier = calc.consequence(
        asset["replacement_value_cents"],
        asset["redundancy_factor"],
        peak,
        depth,
        asset["is_shared"],
        asset["service_population"],
    )
    asset["dependency_depth"] = depth
    asset["consequence_score"] = score
    asset["criticality_tier"] = tier
    asset["criticality_status"] = "RANKED"
    store.touch(asset)
    return envelope.ok(serialize.asset(asset))
