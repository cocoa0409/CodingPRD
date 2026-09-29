"""PRD 3.2 -- downscaled hazard projections, publication and republication."""

from flask import Blueprint

import cascades
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_HAZARD_ANALYST, guard
from core import clock
from errors import fail

bp = Blueprint("hazards", __name__)

HAZARD_TYPES = ("HEAT", "FLOOD", "DROUGHT", "STORM")
SCENARIOS = ("RCP45", "RCP85")
HORIZON_YEARS = (2040, 2060, 2080)


def _projection_fields(body):
    exposure = validate.dec_field(body, "exposure_index", required=True, minimum=0, maximum=1)
    probability = validate.dec_field(
        body, "annual_event_probability", required=True, minimum="0.0001", maximum="1.0000"
    )
    loss = validate.int_field(body, "projected_annual_loss_cents", required=True, minimum=0)
    return exposure, probability, loss


@bp.post("/resilience/hazard-profiles")
@guard(ROLE_HAZARD_ANALYST)
def create_hazard_profile():
    body = validate.json_body()
    jurisdiction = lookup.need_ref("jurisdiction", body, "jurisdiction_id")
    if jurisdiction is None:
        validate.bad("jurisdiction_id", "is required.")
    hazard_type = validate.enum_field(body, "hazard_type", HAZARD_TYPES, required=True)
    scenario = validate.enum_field(body, "scenario", SCENARIOS, required=True)
    horizon_year = validate.int_field(
        body, "horizon_year", required=True, allowed=HORIZON_YEARS
    )
    exposure, probability, loss = _projection_fields(body)

    record = store.insert(store.hazard_profiles, {
        "jurisdiction_id": jurisdiction["id"],
        "hazard_type": hazard_type,
        "scenario": scenario,
        "horizon_year": horizon_year,
        "exposure_index": exposure,
        "annual_event_probability": probability,
        "projected_annual_loss_cents": loss,
        "status": "DRAFT",
        "published_version": 0,
        "published_at": None,
    })
    return envelope.created(serialize.hazard_profile(record))


@bp.get("/resilience/hazard-profiles")
@guard()
def list_hazard_profiles():
    rows = envelope.match(
        store.ordered(store.hazard_profiles),
        jurisdiction_id=envelope.str_filter("jurisdiction_id"),
        hazard_type=envelope.str_filter("hazard_type"),
        scenario=envelope.str_filter("scenario"),
        status=envelope.str_filter("status"),
    )
    return envelope.listing(rows, serialize.hazard_profile)


@bp.get("/resilience/hazard-profiles/<hazard_profile_id>")
@guard()
def get_hazard_profile(hazard_profile_id):
    row = lookup.need("hazard_profile", hazard_profile_id)
    return envelope.ok(serialize.hazard_profile(row))


@bp.post("/resilience/hazard-profiles/<hazard_profile_id>/publish")
@guard(ROLE_HAZARD_ANALYST)
def publish_hazard_profile(hazard_profile_id):
    profile = lookup.need("hazard_profile", hazard_profile_id)
    if profile["status"] != "DRAFT":
        fail(
            "ERR_HAZARD_PROFILE_ALREADY_PUBLISHED",
            "Only a DRAFT projection may be published.",
        )

    for other in store.ordered(store.hazard_profiles):
        if other["id"] == profile["id"] or other["status"] != "PUBLISHED":
            continue
        same = (
            other["jurisdiction_id"] == profile["jurisdiction_id"]
            and other["hazard_type"] == profile["hazard_type"]
            and other["scenario"] == profile["scenario"]
            and other["horizon_year"] == profile["horizon_year"]
        )
        if same:
            other["status"] = "SUPERSEDED"
            store.touch(other)

    profile["status"] = "PUBLISHED"
    profile["published_version"] = 1
    profile["published_at"] = clock.now()
    store.touch(profile)
    return envelope.ok(serialize.hazard_profile(profile))


@bp.post("/resilience/hazard-profiles/<hazard_profile_id>/revisions")
@guard(ROLE_HAZARD_ANALYST)
def revise_hazard_profile(hazard_profile_id):
    profile = lookup.need("hazard_profile", hazard_profile_id)
    body = validate.json_body()
    exposure, probability, loss = _projection_fields(body)
    if profile["status"] != "PUBLISHED":
        fail(
            "ERR_HAZARD_PROFILE_NOT_PUBLISHED",
            "Only a PUBLISHED projection may be revised.",
        )

    # Hop 1: the three projection fields are overwritten and the counter advances.
    profile["exposure_index"] = exposure
    profile["annual_event_probability"] = probability
    profile["projected_annual_loss_cents"] = loss
    profile["published_version"] += 1
    profile["published_at"] = clock.now()
    store.touch(profile)

    cascades.republication_cascade(profile)
    return envelope.ok(serialize.hazard_profile(profile))
