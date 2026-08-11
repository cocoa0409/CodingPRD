"""Configuration surface: catalog items, requirement lines, agency forms,
consulates, closure calendars, interview slots and the logical clock."""
from flask import Blueprint

import clock
import serializers
import store
import validation
from constants import (
    API_PREFIX,
    DOC_TYPES,
    GOVERNMENT_FEE_BASES,
    MINOR_AGE_THRESHOLD_YEARS,
    PASSPORT_VALIDITY_MONTHS_BEYOND_RETURN,
    SUPPORTING_DOC_VALIDITY_DAYS,
    VALIDITY_RULES,
    VISA_TYPES,
)
from errors import fail
from routes.common import CONFIG_READ_ROLES, created, endpoint, listing, ok
from services import cascade, lookup, slots
from validation import Body

bp = Blueprint("config", __name__)
P = API_PREFIX


# ---------------------------------------------------------------- catalog ---
@bp.route(P + "/catalog-items", methods=["POST"])
@endpoint("catalog_items.create", ["PlatformAdmin"])
def create_catalog_item(ctx):
    body = Body(ctx.body)
    nationality = body.string("nationality_code")
    destination = body.string("destination_country")
    visa_type = body.enum("visa_type", VISA_TYPES)
    gov_fee = body.integer("government_fee_cents", minimum=0)
    basis = body.enum("government_fee_basis", GOVERNMENT_FEE_BASES)
    base_fee = body.integer("base_service_fee_cents", minimum=0)
    form_code = body.string("form_code")
    override = body.integer("agency_turnaround_override_days", required=False, minimum=1)
    requires_appointment = body.boolean("requires_appointment", required=False, default=False)
    body.invalid(
        isinstance(nationality, str) and not _is_country_code(nationality),
        "nationality_code must be exactly 2 uppercase letters.",
    )
    body.invalid(
        isinstance(destination, str) and not _is_country_code(destination),
        "destination_country must be exactly 2 uppercase letters.",
    )
    body.check()

    row = store.insert("catalog_items", {
        "nationality_code": nationality,
        "destination_country": destination,
        "visa_type": visa_type,
        "government_fee_cents": gov_fee,
        "government_fee_basis": basis,
        "base_service_fee_cents": base_fee,
        "agency_turnaround_override_days": override,
        "form_code": form_code,
        "requires_appointment": bool(requires_appointment),
    })
    return created(serializers.catalog_item(row))


def _is_country_code(value):
    return len(value) == 2 and value.isalpha() and value.isupper()


@bp.route(P + "/catalog-items", methods=["GET"])
@endpoint("catalog_items.list", CONFIG_READ_ROLES)
def list_catalog_items(ctx):
    rows = store.all_rows("catalog_items")
    rows = validation.apply_filter(rows, "nationality_code")
    rows = validation.apply_filter(rows, "destination_country")
    rows = validation.apply_filter(rows, "visa_type")
    return listing(store.sort_default(rows), serializers.catalog_item)


@bp.route(P + "/catalog-items/<item_id>", methods=["GET"])
@endpoint("catalog_items.read", CONFIG_READ_ROLES)
def read_catalog_item(ctx, item_id):
    row = validation.need("catalog_items", item_id)
    return ok(serializers.catalog_item(row))


@bp.route(P + "/catalog-items/<item_id>/document-requirements", methods=["POST"])
@endpoint("document_requirements.create", ["PlatformAdmin"])
def create_document_requirement(ctx, item_id):
    item = validation.need("catalog_items", item_id)
    body = Body(ctx.body)
    doc_type = body.enum("doc_type", DOC_TYPES)
    is_required = body.boolean("is_required")
    validity_rule = body.enum("validity_rule", VALIDITY_RULES)
    validity_param = body.integer("validity_param", required=False, minimum=1)
    applies_max_age = body.integer("applies_max_age_years", required=False, minimum=1)
    body.check()

    if validity_param is None:
        if validity_rule == "VALID_BEYOND_RETURN_MONTHS":
            validity_param = PASSPORT_VALIDITY_MONTHS_BEYOND_RETURN
        elif validity_rule == "EXPIRES_AFTER_ISSUE_DAYS":
            validity_param = SUPPORTING_DOC_VALIDITY_DAYS
        else:
            validity_param = None
    elif validity_rule == "NONE":
        validity_param = None

    if applies_max_age is None and doc_type == "PARENTAL_CONSENT":
        applies_max_age = MINOR_AGE_THRESHOLD_YEARS

    row = store.insert("document_requirements", {
        "catalog_item_id": item["id"],
        "doc_type": doc_type,
        "is_required": is_required,
        "validity_rule": validity_rule,
        "validity_param": validity_param,
        "applies_max_age_years": applies_max_age,
    })
    return created(serializers.document_requirement(row))


@bp.route(P + "/catalog-items/<item_id>/document-requirements", methods=["GET"])
@endpoint("document_requirements.list", CONFIG_READ_ROLES)
def list_document_requirements(ctx, item_id):
    item = validation.need("catalog_items", item_id)
    return listing(lookup.requirements_of(item["id"]), serializers.document_requirement)


# ------------------------------------------------------------ agency forms ---
@bp.route(P + "/agency-forms", methods=["POST"])
@endpoint("agency_forms.create", ["PlatformAdmin"])
def create_agency_form(ctx):
    body = Body(ctx.body)
    form_code = body.string("form_code")
    revision = body.integer("revision", minimum=1)
    required_field_count = body.integer("required_field_count", minimum=1)
    body.check()
    row = store.insert("agency_forms", {
        "form_code": form_code,
        "revision": revision,
        "required_field_count": required_field_count,
        "status": "DRAFT",
        "published_at": None,
    })
    return created(serializers.agency_form(row))


@bp.route(P + "/agency-forms", methods=["GET"])
@endpoint("agency_forms.list", CONFIG_READ_ROLES)
def list_agency_forms(ctx):
    rows = store.all_rows("agency_forms")
    rows = validation.apply_filter(rows, "form_code")
    rows = validation.apply_filter(rows, "status")
    return listing(store.sort_default(rows), serializers.agency_form)


@bp.route(P + "/agency-forms/<form_id>", methods=["GET"])
@endpoint("agency_forms.read", CONFIG_READ_ROLES)
def read_agency_form(ctx, form_id):
    row = validation.need("agency_forms", form_id)
    return ok(serializers.agency_form(row))


@bp.route(P + "/agency-forms/<form_id>/publish", methods=["POST"])
@endpoint("agency_forms.publish", ["PlatformAdmin"])
def publish_agency_form(ctx, form_id):
    row = validation.need("agency_forms", form_id)
    validation.require_state(row["status"], ("DRAFT",))
    for other in store.all_rows("agency_forms"):
        if (other["form_code"] == row["form_code"]
                and other["status"] == "ACTIVE"
                and other["revision"] > row["revision"]):
            fail("ERR_INVALID_STATE",
                 "A strictly higher revision of this form_code is already ACTIVE.")
    row["status"] = "ACTIVE"
    row["published_at"] = clock.now()
    store.touch(row)
    cascade.publish_cascade(row)
    return ok(serializers.agency_form(row))


@bp.route(P + "/agency-forms/<form_id>/prepared-forms", methods=["GET"])
@endpoint("agency_forms.prepared_forms", CONFIG_READ_ROLES)
def list_forms_preparations(ctx, form_id):
    row = validation.need("agency_forms", form_id)
    rows = [f for f in store.all_rows("prepared_forms") if f["agency_form_id"] == row["id"]]
    rows = validation.apply_filter(rows, "prep_status")
    return listing(store.sort_default(rows), serializers.prepared_form)


# -------------------------------------------------------------- consulates ---
@bp.route(P + "/consulates", methods=["POST"])
@endpoint("consulates.create", ["PlatformAdmin"])
def create_consulate(ctx):
    body = Body(ctx.body)
    name = body.string("name")
    destination = body.string("destination_country")
    regions = body.string_array("jurisdiction_region_codes")
    body.invalid(
        isinstance(destination, str) and not _is_country_code(destination),
        "destination_country must be exactly 2 uppercase letters.",
    )
    body.check()
    row = store.insert("consulates", {
        "name": name,
        "destination_country": destination,
        "jurisdiction_region_codes": list(regions),
        "closure_dates": [],
    })
    return created(serializers.consulate(row))


@bp.route(P + "/consulates", methods=["GET"])
@endpoint("consulates.list", CONFIG_READ_ROLES)
def list_consulates(ctx):
    rows = store.all_rows("consulates")
    rows = validation.apply_filter(rows, "destination_country")
    return listing(store.sort_default(rows), serializers.consulate)


@bp.route(P + "/consulates/<consulate_id>", methods=["GET"])
@endpoint("consulates.read", CONFIG_READ_ROLES)
def read_consulate(ctx, consulate_id):
    row = validation.need("consulates", consulate_id)
    return ok(serializers.consulate(row))


@bp.route(P + "/consulates/<consulate_id>/closures", methods=["POST"])
@endpoint("consulates.closures", ["PlatformAdmin"])
def add_closure(ctx, consulate_id):
    consulate = validation.need("consulates", consulate_id)
    body = Body(ctx.body)
    closure_date = body.date("closure_date")
    body.check()
    rendered = clock.render_date(closure_date)
    if rendered not in consulate["closure_dates"]:
        consulate["closure_dates"].append(rendered)
        consulate["closure_dates"].sort()
        store.touch(consulate)
    for slot in lookup.slots_of_consulate(consulate):
        if clock.render_date(slot["starts_at"].date()) == rendered:
            slots.redrive(slot, consulate, bump=True)
    return ok(serializers.consulate(consulate))


@bp.route(P + "/consulates/<consulate_id>/slots", methods=["POST"])
@endpoint("slots.create", ["PlatformAdmin"])
def create_slot(ctx, consulate_id):
    consulate = validation.need("consulates", consulate_id)
    body = Body(ctx.body)
    starts_at = body.instant("starts_at")
    capacity = body.integer("capacity", minimum=1)
    body.check()
    row = store.insert("slots", {
        "consulate_id": consulate["id"],
        "starts_at": starts_at,
        "capacity": capacity,
        "booked_count": 0,
        "status": "OPEN",
    })
    slots.redrive(row, consulate)
    return created(serializers.slot(row))


@bp.route(P + "/consulates/<consulate_id>/slots", methods=["GET"])
@endpoint("slots.list", CONFIG_READ_ROLES)
def list_slots(ctx, consulate_id):
    consulate = validation.need("consulates", consulate_id)
    rows = lookup.slots_of_consulate(consulate)
    rows = validation.apply_filter(rows, "status")
    return listing(rows, serializers.slot)


@bp.route(P + "/slots/<slot_id>", methods=["GET"])
@endpoint("slots.read", CONFIG_READ_ROLES)
def read_slot(ctx, slot_id):
    row = validation.need("slots", slot_id)
    return ok(serializers.slot(row))


# ------------------------------------------------------------------- clock ---
@bp.route(P + "/_clock/set_current_utc", methods=["POST"])
@endpoint("clock.set", ["PlatformAdmin"])
def set_clock(ctx):
    body = Body(ctx.body)
    instant = body.instant("to_iso8601")
    body.check()
    current = clock.CLOCK.set(instant)
    return ok({"current_utc": clock.render_instant(current)})
