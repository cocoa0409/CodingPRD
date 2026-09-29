"""Product listings, ingredients, lifecycle decisions and distribution records."""

from flask import Blueprint, request

import access
import domain
import envelope
import schema
import store
from access import Checks, Ctx
from errors import ApiError

bp = Blueprint("listings", __name__)


def _listing_facility(listing):
    return domain.facility_of_listing(listing)


# ------------------------------------------------------------------ listings
@bp.post("/cosmetics/listings")
def create_listing():
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    rp_id = schema.raw_string(body, "responsible_person_id")
    facility_id = schema.raw_string(body, "facility_id")

    def resolve_rp():
        if rp_id is not None:
            ctx.rp = access.need_responsible_person(rp_id)

    def resolve_facility():
        if facility_id is not None:
            facility = store.get("facilities", facility_id)
            if facility is None:
                # PRD §3.3: an unresolvable facility_id surfaces as ERR_LISTING_NOT_FOUND.
                raise ApiError("ERR_LISTING_NOT_FOUND")
            ctx.facility = facility

    checks.add(access.R_RESPONSIBLE_PERSON, resolve_rp)
    checks.add(access.R_LISTING, resolve_facility)
    checks.add(access.R_OWNER,
               lambda: access.check_owner(auth, responsible_person_id=rp_id))

    def validate():
        payload = body if body is not None else {}
        schema.string_field(payload, "facility_id", max_len=100)
        schema.string_field(payload, "responsible_person_id", max_len=100)
        ctx.product_name = schema.string_field(payload, "product_name", max_len=200)
        ctx.category_code = schema.string_field(payload, "category_code", max_len=16)
        ctx.product_form = schema.enum_field(payload, "product_form", domain.PRODUCT_FORMS)
        ctx.professional = schema.bool_field(payload, "professional_use_only", default=False)
        ctx.statement = schema.bool_field(payload, "professional_use_statement_present", default=False)
        ctx.contact_type = schema.enum_field(payload, "label_contact_type", domain.LABEL_CONTACT_TYPES)
        ctx.contact_value = schema.string_field(payload, "label_contact_value", max_len=300)
        ctx.lot_units = schema.int_field(payload, "lot_authorized_units", required=False,
                                        minimum=0, default=0)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_CATEGORY, lambda: access.state_error(
        ctx.category_code in domain.CATEGORY_CODES, "ERR_UNKNOWN_CATEGORY_CODE"))
    checks.add(access.R_NOT_REGISTERED, lambda: access.state_error(
        ctx.facility["registration_status"] in domain.ADMISSIBLE_REGISTERED,
        "ERR_FACILITY_NOT_REGISTERED"))
    checks.run()

    listing = store.insert("listings", {
        "facility_id": ctx.facility["id"],
        "responsible_person_id": ctx.rp["id"],
        "product_name": ctx.product_name,
        "category_code": ctx.category_code,
        "product_form": ctx.product_form,
        "professional_use_only": ctx.professional,
        "professional_use_statement_present": ctx.statement,
        "label_contact_type": ctx.contact_type,
        "label_contact_value": ctx.contact_value,
        "lot_authorized_units": ctx.lot_units,
        "listing_number": None,
        "listing_status": "DRAFT",
        "safety_status": "UNSUBSTANTIATED",
        "suspension_reason": None,
    })
    return envelope.created(domain.listing_json(listing))


@bp.get("/cosmetics/listings/<lid>")
def get_listing(lid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))
    checks.run()
    return envelope.ok(domain.listing_json(ctx.listing))


@bp.get("/cosmetics/listings")
def list_listings():
    access.authorize(domain.ROLES)
    records = store.all_of("listings")
    for name in ("facility_id", "responsible_person_id", "listing_status", "safety_status"):
        value = request.args.get(name)
        if value:
            records = [r for r in records if r[name] == value]
    return envelope.paginate(store.by_created(records), domain.listing_json)


# --------------------------------------------------------------- ingredients
@bp.post("/cosmetics/listings/<lid>/ingredients")
def add_ingredient(lid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))

    def validate():
        payload = body if body is not None else {}
        ctx.inci = schema.string_field(payload, "inci_name", max_len=120)
        ctx.cas = schema.string_field(payload, "cas_number", required=False, max_len=32, default=None)
        ctx.function_code = schema.enum_field(payload, "function_code", domain.FUNCTION_CODES)
        ctx.concentration = schema.decimal_field(payload, "concentration_pct", minimum=0,
                                                 maximum=100, exclusive_min=True, places=4)
        ctx.allergen = schema.bool_field(payload, "is_fragrance_allergen", default=False)
        ctx.disclosed = schema.bool_field(payload, "label_disclosed", default=False)
        ctx.data_gap = schema.bool_field(payload, "is_data_gap_flag", default=False)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_LISTING, lambda: access.state_error(
        ctx.listing["listing_status"] != "DELISTED", "ERR_INVALID_LISTING_STATE"))

    def duplicate():
        wanted = ctx.inci.strip().lower()
        for existing in domain.ingredients_of_listing(lid):
            if existing["inci_name"].strip().lower() == wanted:
                raise ApiError("ERR_DUPLICATE_INGREDIENT")

    checks.add(access.R_DUPLICATE_INGREDIENT, duplicate)
    checks.run()

    ingredient = store.insert("ingredients", {
        "listing_id": lid,
        "inci_name": ctx.inci,
        "cas_number": ctx.cas,
        "function_code": ctx.function_code,
        "concentration_pct": ctx.concentration,
        "is_fragrance_allergen": ctx.allergen,
        "label_disclosed": ctx.disclosed,
        "is_data_gap_flag": ctx.data_gap,
    })
    domain.refresh_data_gap(ctx.listing)
    return envelope.created(domain.ingredient_json(ingredient))


@bp.get("/cosmetics/listings/<lid>/ingredients")
def list_ingredients(lid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))
    checks.run()
    records = domain.ingredients_of_listing(lid)
    flag = request.args.get("is_fragrance_allergen")
    if flag is not None and flag != "":
        wanted = flag.strip().lower() in ("true", "1", "yes")
        records = [r for r in records if bool(r["is_fragrance_allergen"]) == wanted]
    return envelope.paginate(store.by_created(records), domain.ingredient_json)


# ---------------------------------------------------------------- lifecycle
@bp.post("/cosmetics/listings/<lid>/submit")
def submit_listing(lid):
    auth = access.authorize("ResponsiblePersonAgent")
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))
    checks.add(access.R_NOT_REGISTERED, lambda: access.state_error(
        _listing_facility(ctx.listing)["registration_status"] in domain.ADMISSIBLE_REGISTERED,
        "ERR_FACILITY_NOT_REGISTERED"))
    checks.add(access.R_FROZEN, lambda: access.state_error(
        _listing_facility(ctx.listing)["compliance_posture"] != "FROZEN",
        "ERR_FACILITY_POSTURE_FROZEN"))
    checks.add(access.R_STATE_LISTING, lambda: access.state_error(
        ctx.listing["listing_status"] in ("DRAFT", "RETURNED"), "ERR_INVALID_LISTING_STATE"))
    checks.add(access.R_NOT_ADEQUATE, lambda: access.state_error(
        ctx.listing["safety_status"] == "SUBSTANTIATED", "ERR_SUBSTANTIATION_NOT_ADEQUATE"))
    checks.add(access.R_ALLERGEN, lambda: access.state_error(
        domain.allergen_disclosure_complete(ctx.listing), "ERR_ALLERGEN_DISCLOSURE_INCOMPLETE"))

    def professional_use():
        listing = ctx.listing
        if not listing["professional_use_only"]:
            return
        ok = (
            listing["professional_use_statement_present"] is True
            and listing["category_code"] in domain.PROFESSIONAL_USE_PERMITTED_CATEGORIES
        )
        access.state_error(ok, "ERR_PROFESSIONAL_USE_LABEL_REQUIRED")

    checks.add(access.R_PROFESSIONAL_USE, professional_use)

    def label_contact():
        listing = ctx.listing
        if listing["professional_use_only"]:
            allowed = domain.LABEL_CONTACT_TYPES
        else:
            allowed = domain.CONSUMER_LABEL_CONTACT_TYPES
        ok = (
            listing["label_contact_type"] in allowed
            and bool(listing["label_contact_value"])
            and bool(str(listing["label_contact_value"]).strip())
        )
        access.state_error(ok, "ERR_LABEL_CONTACT_REQUIRED")

    checks.add(access.R_LABEL_CONTACT, label_contact)

    def cap():
        rp = store.get("responsible_persons", ctx.listing["responsible_person_id"])
        access.state_error(
            rp is not None and domain.active_designation_count(rp) < rp["designation_cap"],
            "ERR_DESIGNATION_CAP_EXCEEDED")

    checks.add(access.R_DESIGNATION_CAP, cap)
    checks.run()

    listing = ctx.listing
    facility = _listing_facility(listing)
    listing["listing_status"] = "SUBMITTED"
    store.touch(listing)
    store.touch(store.get("responsible_persons", listing["responsible_person_id"]))
    domain.ledger_append(facility["id"], "STATE_TRANSITION", "ProductListing", listing["id"],
                         "Listing submitted for review.")
    return envelope.ok(domain.listing_json(listing))


@bp.post("/cosmetics/listings/<lid>/listing-decision")
def listing_decision(lid):
    access.authorize("RegulatoryReviewer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))

    def validate():
        payload = body if body is not None else {}
        ctx.decision = schema.enum_field(payload, "decision", ("LIST", "RETURN"))
        ctx.note = schema.string_field(payload, "decision_note", required=False, max_len=1000, default=None)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_FROZEN, lambda: access.state_error(
        _listing_facility(ctx.listing)["compliance_posture"] != "FROZEN",
        "ERR_FACILITY_POSTURE_FROZEN"))
    checks.add(access.R_STATE_LISTING, lambda: access.state_error(
        ctx.listing["listing_status"] == "SUBMITTED", "ERR_INVALID_LISTING_STATE"))
    checks.run()

    listing = ctx.listing
    facility = _listing_facility(listing)
    if ctx.decision == "LIST":
        listing["listing_status"] = "LISTED"
        if listing["listing_number"] is None:
            issued = len([l for l in store.all_of("listings") if l["listing_number"]])
            listing["listing_number"] = "CPL-%06d" % (issued + 1)
        store.touch(listing)
        domain.ledger_append(facility["id"], "STATE_TRANSITION", "ProductListing", listing["id"],
                             "Listing accepted onto the public list.")
    else:
        listing["listing_status"] = "RETURNED"
        store.touch(listing)
        store.touch(store.get("responsible_persons", listing["responsible_person_id"]))
        domain.ledger_append(facility["id"], "STATE_TRANSITION", "ProductListing", listing["id"],
                             "Listing returned to the responsible person.")
    return envelope.ok(domain.listing_json(listing))


@bp.post("/cosmetics/listings/<lid>/transfer-responsible-person")
def transfer_responsible_person(lid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    incoming_id = schema.raw_string(body, "responsible_person_id")

    def resolve_incoming():
        if incoming_id is not None:
            ctx.incoming = access.need_responsible_person(incoming_id)

    checks.add(access.R_RESPONSIBLE_PERSON, resolve_incoming)
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))

    def validate():
        payload = body if body is not None else {}
        schema.string_field(payload, "responsible_person_id", max_len=100)
        ctx.expected = schema.int_field(payload, "expected_listing_version", minimum=0)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STALE_LISTING, lambda: access.state_error(
        ctx.expected == ctx.listing["version"], "ERR_STALE_LISTING_VERSION"))
    checks.add(access.R_STATE_LISTING, lambda: access.state_error(
        ctx.listing["listing_status"] != "DELISTED", "ERR_INVALID_LISTING_STATE"))
    checks.add(access.R_SAME_PERSON, lambda: access.state_error(
        ctx.listing["responsible_person_id"] != ctx.incoming["id"],
        "ERR_TRANSFER_TARGET_SAME_PERSON"))
    checks.add(access.R_DESIGNATION_CAP, lambda: access.state_error(
        domain.active_designation_count(ctx.incoming) < ctx.incoming["designation_cap"],
        "ERR_DESIGNATION_CAP_EXCEEDED"))
    checks.run()

    listing = ctx.listing
    outgoing = store.get("responsible_persons", listing["responsible_person_id"])
    moves_slot = listing["listing_status"] in ("SUBMITTED", "LISTED")
    listing["responsible_person_id"] = ctx.incoming["id"]
    store.touch(listing)
    if moves_slot:
        store.touch(outgoing)
        store.touch(ctx.incoming)
    return envelope.ok(domain.listing_json(listing))


@bp.post("/cosmetics/listings/<lid>/delist")
def delist_listing(lid):
    auth = access.authorize("ResponsiblePersonAgent", "EnforcementOfficer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))

    def validate():
        payload = body if body is not None else {}
        ctx.reason = schema.string_field(payload, "reason", required=False, max_len=1000, default=None)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_LISTING, lambda: access.state_error(
        ctx.listing["listing_status"] in ("LISTED", "SUSPENDED", "RETURNED"),
        "ERR_INVALID_LISTING_STATE"))
    checks.add(access.R_OPEN_RECALL, lambda: access.state_error(
        domain.open_recall_count(ctx.listing) == 0, "ERR_OPEN_RECALL_BLOCKS_DELIST"))
    checks.run()

    listing = ctx.listing
    facility = _listing_facility(listing)
    prior_status = listing["listing_status"]
    listing["listing_status"] = "DELISTED"
    listing["suspension_reason"] = None
    store.touch(listing)
    if prior_status in ("SUBMITTED", "LISTED"):
        store.touch(store.get("responsible_persons", listing["responsible_person_id"]))
    domain.ledger_append(facility["id"], "STATE_TRANSITION", "ProductListing", listing["id"],
                         "Listing delisted.")
    return envelope.ok(domain.listing_json(listing))


# ------------------------------------------------------- distribution records
@bp.post("/cosmetics/listings/<lid>/distribution-records")
def create_distribution_record(lid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))

    def validate():
        payload = body if body is not None else {}
        ctx.lot_code = schema.string_field(payload, "lot_code", max_len=40)
        ctx.consignee = schema.string_field(payload, "consignee_name", max_len=200)
        ctx.consignee_class = schema.enum_field(payload, "consignee_class", domain.CONSIGNEE_CLASSES)
        ctx.ship = schema.day_field(payload, "ship_date")
        ctx.delivery = schema.day_field(payload, "delivery_date")
        ctx.units = schema.int_field(payload, "units_shipped", minimum=1)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_WINDOW_BOUNDS, lambda: access.state_error(
        ctx.ship <= ctx.delivery, "ERR_INVALID_WINDOW_BOUNDS"))
    checks.add(access.R_NOT_REGISTERED, lambda: access.state_error(
        _listing_facility(ctx.listing)["registration_status"] in domain.ADMISSIBLE_REGISTERED,
        "ERR_FACILITY_NOT_REGISTERED"))
    checks.add(access.R_FROZEN, lambda: access.state_error(
        _listing_facility(ctx.listing)["compliance_posture"] != "FROZEN",
        "ERR_FACILITY_POSTURE_FROZEN"))

    def lot_window():
        for other in domain.records_of_listing(lid):
            if other["lot_code"] != ctx.lot_code:
                continue
            disjoint = ctx.delivery < other["ship_date"] or other["delivery_date"] < ctx.ship
            if not disjoint:
                raise ApiError("ERR_LOT_WINDOW_CONFLICT")

    checks.add(access.R_LOT_WINDOW, lot_window)

    def lot_capacity():
        recorded = sum(r["units_shipped"] for r in domain.records_of_listing(lid)
                       if r["lot_code"] == ctx.lot_code)
        access.state_error(recorded + ctx.units <= ctx.listing["lot_authorized_units"],
                          "ERR_LOT_CAPACITY_EXCEEDED")

    checks.add(access.R_LOT_CAPACITY, lot_capacity)
    checks.run()

    record = store.insert("distribution_records", {
        "listing_id": lid,
        "withdrawal_id": None,
        "lot_code": ctx.lot_code,
        "consignee_name": ctx.consignee,
        "consignee_class": ctx.consignee_class,
        "ship_date": ctx.ship,
        "delivery_date": ctx.delivery,
        "units_shipped": ctx.units,
        "units_reported_returned": 0,
        "units_reported_destroyed": 0,
        "units_in_transit_returns": 0,
        "units_verified_returned": 0,
        "units_verified_destroyed": 0,
    })
    return envelope.created(domain.distribution_record_json(record))


@bp.get("/cosmetics/distribution-records")
def list_distribution_records():
    access.authorize(domain.ROLES)
    records = store.all_of("distribution_records")
    for name in ("listing_id", "withdrawal_id", "lot_code"):
        value = request.args.get(name)
        if value:
            records = [r for r in records if r[name] == value]
    return envelope.paginate(store.by_created(records), domain.distribution_record_json)


@bp.get("/cosmetics/distribution-records/<rid>")
def get_distribution_record(rid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_RECORD, lambda: ctx.set("record", access.need_record(rid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(
        auth, store.get("listings", ctx.record["listing_id"])))
    checks.run()
    return envelope.ok(domain.distribution_record_json(ctx.record))
