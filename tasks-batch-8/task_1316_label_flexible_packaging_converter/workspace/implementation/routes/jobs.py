"""LabelJob endpoints: quoting, release, press execution, shipment (PRD 3.4-3.8)."""
from flask import Blueprint, request

from calc import (
    MIN_ORDER_QTY,
    job_invoice_calc,
    job_material_calc,
    job_quote_calc,
)
from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import cancel_job, get_customer, get_job, sorted_created, touch
from util import (
    as_bool,
    as_int,
    as_str,
    body,
    pagination_args,
    reject_unknown,
    required,
)

bp = Blueprint("jobs", __name__)

_CREATE_FIELDS = {
    "artwork_version_id",
    "substrate_id",
    "ink_recipe_id",
    "die_id",
    "press_id",
    "quantity_ordered",
    "repeat_length_mm",
    "requires_food_contact_letter",
    "rewind_max_rolls",
    "max_splices_per_roll",
}

_FILTERS = (
    "customer_id",
    "artwork_version_id",
    "substrate_id",
    "ink_recipe_id",
    "die_id",
    "press_id",
    "status",
)


def _fk(collection, key, label):
    """Body FK reference existence: a dangling reference does not resolve."""
    entity = DB[collection].get(key)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return entity


@bp.post("/label-jobs/customers/<customer_id>/jobs")
def create_job(customer_id):
    auth(["Estimator"])
    get_customer(customer_id)
    data = body()
    reject_unknown(data, _CREATE_FIELDS)
    artwork_version_id = as_str(
        required(data, "artwork_version_id"), "artwork_version_id"
    )
    substrate_id = as_str(required(data, "substrate_id"), "substrate_id")
    ink_recipe_id = as_str(required(data, "ink_recipe_id"), "ink_recipe_id")
    die_id = as_str(required(data, "die_id"), "die_id")
    press_id = as_str(required(data, "press_id"), "press_id")
    quantity_ordered = as_int(required(data, "quantity_ordered"), "quantity_ordered")
    repeat_length_mm = as_int(
        required(data, "repeat_length_mm"), "repeat_length_mm"
    )
    requires_food_contact_letter = (
        as_bool(data["requires_food_contact_letter"], "requires_food_contact_letter")
        if "requires_food_contact_letter" in data
        else False
    )
    rewind_max_rolls = as_int(required(data, "rewind_max_rolls"), "rewind_max_rolls")
    max_splices_per_roll = as_int(
        required(data, "max_splices_per_roll"), "max_splices_per_roll"
    )
    # Referenced resources must exist.
    artwork = _fk("artworks", artwork_version_id, "Artwork revision")
    substrate = _fk("substrates", substrate_id, "Substrate")
    ink_recipe = _fk("ink_recipes", ink_recipe_id, "Ink recipe")
    die = _fk("dies", die_id, "Die")
    press = _fk("presses", press_id, "Press")
    # Creation guards: station capacity, then die status (PRD 2.5 order).
    if artwork["color_count"] > press["station_count"]:
        raise ApiError(
            "ERR_COLOR_COUNT_EXCEEDS_PRESS",
            409,
            "artwork color_count exceeds press station_count",
        )
    if die["status"] == "RETIRED":
        raise ApiError(
            "ERR_DIE_RETIRED", 422, "job creation references a RETIRED die"
        )
    quoted = job_quote_calc(
        quantity_ordered, repeat_length_mm, press, substrate, ink_recipe, artwork
    )
    ts = now_iso()
    job = {
        "id": new_id(),
        "customer_id": customer_id,
        "artwork_version_id": artwork_version_id,
        "substrate_id": substrate_id,
        "ink_recipe_id": ink_recipe_id,
        "die_id": die_id,
        "press_id": press_id,
        "quantity_ordered": quantity_ordered,
        "repeat_length_mm": repeat_length_mm,
        "requires_food_contact_letter": requires_food_contact_letter,
        "rewind_max_rolls": rewind_max_rolls,
        "max_splices_per_roll": max_splices_per_roll,
        "material_ft": None,
        "quoted_price_cents": quoted,
        "invoiced_price_cents": None,
        "die_charge_applied_cents": 0,
        "status": "QUOTED",
        "good_quantity_produced": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["jobs"][job["id"]] = job
    return ok(job, 201)


@bp.get("/label-jobs/customers/<customer_id>/jobs")
def list_customer_jobs(customer_id):
    auth(ALL_ROLES)
    get_customer(customer_id)
    limit, offset = pagination_args()
    items = sorted_created(
        j for j in DB["jobs"].values() if j["customer_id"] == customer_id
    )
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.get("/label-jobs/jobs")
def list_jobs():
    """Cross-customer job listing with optional FK/status filters (PRD 3.4)."""
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted_created(DB["jobs"].values())
    for field in _FILTERS:
        value = request.args.get(field)
        if value is not None:
            items = [j for j in items if j[field] == value]
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.get("/label-jobs/jobs/<job_id>")
def get_one_job(job_id):
    auth(ALL_ROLES)
    return ok(get_job(job_id))


@bp.post("/label-jobs/jobs/<job_id>/approve")
def approve_job(job_id):
    auth(["Estimator"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, set())
    if job["status"] != "QUOTED":
        raise ApiError("ERR_JOB_NOT_QUOTED", 409, "approve requires job in QUOTED")
    job["status"] = "APPROVED"
    touch(job)
    return ok(job)


@bp.post("/label-jobs/jobs/<job_id>/release")
def release_job(job_id):
    auth(["Estimator"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, {"expected_artwork_version"})
    expected_artwork_version = as_int(
        required(data, "expected_artwork_version"), "expected_artwork_version"
    )
    # State admissibility.
    if job["status"] != "APPROVED":
        raise ApiError(
            "ERR_JOB_NOT_APPROVED", 409, "release requires job in APPROVED"
        )
    # Business rules in PRD 2.5 order: food-contact component safety first.
    substrate = DB["substrates"][job["substrate_id"]]
    ink_recipe = DB["ink_recipes"][job["ink_recipe_id"]]
    if job["requires_food_contact_letter"] and not (
        substrate["food_contact_certified"] and ink_recipe["food_contact_compliant"]
    ):
        raise ApiError(
            "ERR_FOOD_CONTACT_COMPONENT",
            422,
            "food-contact job requires certified substrate and compliant ink recipe",
        )
    # Referential freshness: the referenced revision must be APPROVED.
    artwork = DB["artworks"][job["artwork_version_id"]]
    if artwork["status"] != "APPROVED":
        raise ApiError(
            "ERR_ARTWORK_NOT_APPROVED",
            422,
            "release requires the referenced artwork revision to be APPROVED",
        )
    # Fiscal gates: minimum order, then credit hold.
    if job["quantity_ordered"] < MIN_ORDER_QTY:
        raise ApiError(
            "ERR_BELOW_MINIMUM_ORDER",
            422,
            "quantity_ordered must be at least 1000",
        )
    customer = DB["customers"][job["customer_id"]]
    if customer["credit_hold"]:
        raise ApiError(
            "ERR_CUSTOMER_CREDIT_HOLD", 422, "customer is on credit hold"
        )
    # Optimistic concurrency is checked last (PRD 2.5 / 2.8).
    if expected_artwork_version != artwork["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_artwork_version does not match the revision's current version",
        )
    # First-use die billing: the charge follows the die, billed exactly once.
    die = DB["dies"][job["die_id"]]
    if die["new_die_charge_cents"] > 0 and not die["charge_collected"]:
        job["die_charge_applied_cents"] = die["new_die_charge_cents"]
        die["charge_collected"] = True
        touch(die)
    # Freeze material footage at release.
    press = DB["presses"][job["press_id"]]
    job["material_ft"] = job_material_calc(
        job["quantity_ordered"], job["repeat_length_mm"], press
    )
    job["status"] = "RELEASED"
    touch(job)
    return ok(job)


@bp.post("/label-jobs/jobs/<job_id>/start-press")
def start_press(job_id):
    auth(["PressOperator"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, set())
    if job["status"] != "RELEASED":
        raise ApiError(
            "ERR_JOB_NOT_RELEASED", 409, "start-press requires job in RELEASED"
        )
    # One job at a time per press.
    for other in DB["jobs"].values():
        if (
            other["id"] != job["id"]
            and other["press_id"] == job["press_id"]
            and other["status"] == "ON_PRESS"
        ):
            raise ApiError(
                "ERR_PRESS_OCCUPIED",
                409,
                "another job is ON_PRESS on the referenced press",
            )
    job["status"] = "ON_PRESS"
    touch(job)
    return ok(job)


@bp.post("/label-jobs/jobs/<job_id>/complete-press")
def complete_press(job_id):
    auth(["PressOperator"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, {"good_quantity_produced"})
    if "good_quantity_produced" in data and data["good_quantity_produced"] is not None:
        as_int(data["good_quantity_produced"], "good_quantity_produced")
    if job["status"] != "ON_PRESS":
        raise ApiError(
            "ERR_JOB_NOT_ON_PRESS", 409, "complete-press requires job in ON_PRESS"
        )
    good = data.get("good_quantity_produced")
    if not isinstance(good, int) or isinstance(good, bool) or good <= 0:
        raise ApiError(
            "ERR_INVALID_GOOD_QTY",
            422,
            "good_quantity_produced must be supplied and greater than zero",
        )
    measurements = [m for m in DB["measurements"].values() if m["job_id"] == job_id]
    # Color history is revision-by-append (PRD 3.6): a superseded FAIL row
    # stays FAIL but does not block completion — the latest row recorded for
    # each station is that station's record on file. Rows are stored in
    # creation order, so the last row seen per station is the latest.
    latest_by_station = {}
    for m in measurements:
        latest_by_station[m["station_no"]] = m
    if not measurements or any(
        m["verdict"] != "PASS" for m in latest_by_station.values()
    ):
        raise ApiError(
            "ERR_COLOR_NOT_APPROVED",
            422,
            "complete-press requires every color measurement to be PASS "
            "and at least one measurement to exist",
        )
    job["good_quantity_produced"] = good
    job["status"] = "PRINTED"
    touch(job)
    return ok(job)


@bp.post("/label-jobs/jobs/<job_id>/ship")
def ship_job(job_id):
    auth(["QualityManager"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, {"expected_job_version"})
    expected_job_version = as_int(
        required(data, "expected_job_version"), "expected_job_version"
    )
    if job["status"] != "REWOUND":
        raise ApiError("ERR_JOB_NOT_REWOUND", 409, "ship requires job in REWOUND")
    if job["requires_food_contact_letter"] and not any(
        l["job_id"] == job_id and l["letter_type"] == "FOOD_CONTACT"
        for l in DB["letters"].values()
    ):
        raise ApiError(
            "ERR_COMPLIANCE_LETTER_MISSING",
            422,
            "food-contact job cannot ship without a FOOD_CONTACT letter",
        )
    # Optimistic concurrency is checked last (PRD 2.5 / 2.8).
    if expected_job_version != job["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_job_version does not match the job's current version",
        )
    substrate = DB["substrates"][job["substrate_id"]]
    ink_recipe = DB["ink_recipes"][job["ink_recipe_id"]]
    artwork = DB["artworks"][job["artwork_version_id"]]
    job["invoiced_price_cents"] = job_invoice_calc(job, substrate, ink_recipe, artwork)
    job["status"] = "SHIPPED"
    touch(job)
    return ok(job)


@bp.post("/label-jobs/jobs/<job_id>/cancel")
def cancel_job_endpoint(job_id):
    auth(["Estimator"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, set())
    if job["status"] not in ("QUOTED", "APPROVED", "RELEASED"):
        raise ApiError(
            "ERR_JOB_NOT_CANCELLABLE",
            409,
            "cancel requires job in QUOTED, APPROVED, or RELEASED",
        )
    cancel_job(job)
    return ok(job)
