"""Logical clock, jurisdictions, taxability rules, properties and channels (PRD 3.1)."""

from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import resolve
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("config", __name__)

JURISDICTION_CODE_PATTERN = r"^[A-Z0-9-]+$"
CHANNEL_TYPES = ("OWNED_WEB", "OWNED_APP", "OTA", "GDS", "METASEARCH", "VOICE")
TAXABILITY_VALUES = ("TAXABLE", "EXEMPT", "TAXABLE_IF_MANDATORY")
PROPERTY_STATUSES = ("ACTIVE", "SUSPENDED")
POSTURES = ("COMPLIANT", "AT_RISK", "NON_COMPLIANT")


# ------------------------------------------------------------- logical clock

@bp.get("/_clock")
def read_clock():
    """Deliberately unauthenticated (PRD 2.1)."""
    return envelope.ok({"current_utc": clock.now_iso()})


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require([auth.PLATFORM_ADMIN])
    payload = shape.body()
    instant = shape.timestamp(payload, "to_iso8601", required=True)
    clock.set_now(instant)
    return envelope.ok({"current_utc": clock.now_iso()})


# ------------------------------------------------------------- jurisdictions

@bp.post("/jurisdictions")
def create_jurisdiction():
    auth.require([auth.PLATFORM_ADMIN])
    payload = shape.body()
    code = shape.string(payload, "code", min_len=3, max_len=32,
                        pattern=JURISDICTION_CODE_PATTERN)
    name = shape.string(payload, "name", min_len=1, max_len=120)
    rate = shape.integer(payload, "occupancy_tax_rate_bps", minimum=0, maximum=5000)
    first_quote_total_required = shape.boolean(payload, "first_quote_total_required")
    itemization_required_on_folio = shape.boolean(payload, "itemization_required_on_folio")
    mandatory_fee_ban = shape.boolean(payload, "mandatory_fee_ban", required=False,
                                      default=False)
    opt_out_mandate = shape.boolean(payload, "opt_out_mandate", required=False,
                                    default=False)

    for existing in store.jurisdictions.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_JURISDICTION_CODE",
                           "Jurisdiction code %s already exists." % code)

    row = {
        "code": code,
        "name": name,
        "occupancy_tax_rate_bps": rate,
        "first_quote_total_required": first_quote_total_required,
        "itemization_required_on_folio": itemization_required_on_folio,
        "mandatory_fee_ban": mandatory_fee_ban,
        "opt_out_mandate": opt_out_mandate,
    }
    store.stamp_new(row)
    store.jurisdictions[row["id"]] = row
    return envelope.created(serialize.jurisdiction(row))


@bp.get("/jurisdictions/<identifier>")
def read_jurisdiction(identifier):
    auth.require(auth.OPERATORS)
    return envelope.ok(serialize.jurisdiction(resolve.jurisdiction(identifier)))


@bp.get("/jurisdictions")
def list_jurisdictions():
    auth.require(auth.OPERATORS)
    rows = envelope.apply_filters(
        store.sort_default(store.jurisdictions.values()),
        [("code", envelope.str_filter("code")),
         ("mandatory_fee_ban", envelope.bool_filter("mandatory_fee_ban"))],
    )
    return envelope.page(rows, serialize.jurisdiction)


# ---------------------------------------------------------- taxability rules

@bp.post("/taxability-rules")
def create_taxability_rule():
    auth.require([auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER])
    payload = shape.body()
    jurisdiction_id = shape.identifier(payload, "jurisdiction_id")
    fee_code = shape.string(payload, "fee_code", min_len=1, max_len=32)
    taxability = shape.enum(payload, "taxability", TAXABILITY_VALUES)
    tax_rate_bps = shape.integer(payload, "tax_rate_bps", required=False,
                                 minimum=0, maximum=5000)

    resolve.jurisdiction(jurisdiction_id)

    if store.taxability_rule(jurisdiction_id, fee_code) is not None:
        raise ApiError("ERR_DUPLICATE_TAXABILITY_RULE",
                       "A rule for %s already exists in that jurisdiction." % fee_code)

    row = {
        "jurisdiction_id": jurisdiction_id,
        "fee_code": fee_code,
        "taxability": taxability,
        "tax_rate_bps": tax_rate_bps,
    }
    store.stamp_new(row)
    store.taxability_rules[row["id"]] = row
    return envelope.created(serialize.taxability_rule(row))


@bp.get("/taxability-rules/<identifier>")
def read_taxability_rule(identifier):
    auth.require(auth.OPERATORS)
    return envelope.ok(serialize.taxability_rule(resolve.taxability_rule(identifier)))


@bp.get("/taxability-rules")
def list_taxability_rules():
    auth.require(auth.OPERATORS)
    rows = envelope.apply_filters(
        store.sort_default(store.taxability_rules.values()),
        [("jurisdiction_id", envelope.str_filter("jurisdiction_id")),
         ("fee_code", envelope.str_filter("fee_code")),
         ("taxability", envelope.str_filter("taxability"))],
    )
    return envelope.page(rows, serialize.taxability_rule)


# ----------------------------------------------------------------- properties

@bp.post("/properties")
def create_property():
    auth.require([auth.PLATFORM_ADMIN])
    payload = shape.body()
    jurisdiction_id = shape.identifier(payload, "jurisdiction_id")
    name = shape.string(payload, "name", min_len=1, max_len=120)
    brand_code = shape.string(payload, "brand_code", min_len=1, max_len=16)
    base_room_rate_cents = shape.integer(payload, "base_room_rate_cents", minimum=0)
    status = shape.enum(payload, "status", PROPERTY_STATUSES, required=False,
                        default="ACTIVE")

    resolve.jurisdiction(jurisdiction_id)

    row = {
        "jurisdiction_id": jurisdiction_id,
        "name": name,
        "brand_code": brand_code,
        "base_room_rate_cents": base_room_rate_cents,
        "status": status,
        "min_channel_disclosure_score": None,
        "disclosure_posture": "COMPLIANT",
        "open_disclosure_obligation_count": 0,
        "published_fee_program_count": 0,
        "aggregate_disclosure_gap_cents": 0,
    }
    store.stamp_new(row)
    store.properties[row["id"]] = row
    return envelope.created(serialize.property_row(row))


@bp.get("/properties/<identifier>")
def read_property(identifier):
    auth.require(auth.OPERATORS)
    return envelope.ok(serialize.property_row(resolve.property_(identifier)))


@bp.get("/properties")
def list_properties():
    auth.require(auth.OPERATORS)
    rows = envelope.apply_filters(
        store.sort_default(store.properties.values()),
        [("jurisdiction_id", envelope.str_filter("jurisdiction_id")),
         ("status", envelope.str_filter("status")),
         ("disclosure_posture", envelope.str_filter("disclosure_posture"))],
    )
    return envelope.page(rows, serialize.property_row)


@bp.get("/properties/<identifier>/disclosure-summary")
def property_disclosure_summary(identifier):
    auth.require([auth.PLATFORM_ADMIN, auth.REVENUE_MANAGER, auth.COMPLIANCE_OFFICER,
                  auth.REGULATORY_LIAISON])
    prop = resolve.property_(identifier)

    profiles = store.profiles_of_property(prop["id"])
    deployed = sum(1 for p in profiles if p["status"] == "DEPLOYED")
    flagged = sum(1 for p in profiles if p["status"] == "FLAGGED")
    minimum = derive.min_channel_disclosure_score(prop)
    burden = 0
    for program in store.programs_of_property(prop["id"]):
        if program["status"] == "PUBLISHED":
            burden += program["total_mandatory_fee_cents_per_night"]

    return envelope.ok({
        "property_id": prop["id"],
        "disclosure_posture": calc.posture_for(minimum),
        "min_channel_disclosure_score": minimum,
        "open_disclosure_obligation_count": derive.open_disclosure_obligation_count(prop),
        "deployed_profile_count": deployed,
        "flagged_profile_count": flagged,
        "published_fee_program_count": derive.published_fee_program_count(prop),
        "total_mandatory_fee_cents_per_night": burden,
        "aggregate_disclosure_gap_cents": derive.aggregate_disclosure_gap_cents(prop),
    })


# ------------------------------------------------------------------- channels

@bp.post("/channels")
def create_channel():
    auth.require([auth.PLATFORM_ADMIN])
    payload = shape.body()
    name = shape.string(payload, "name", min_len=1, max_len=120)
    channel_type = shape.enum(payload, "channel_type", CHANNEL_TYPES)
    supports_total_price_display = shape.boolean(payload, "supports_total_price_display")
    supports_itemization = shape.boolean(payload, "supports_itemization")

    row = {
        "name": name,
        "channel_type": channel_type,
        "supports_total_price_display": supports_total_price_display,
        "supports_itemization": supports_itemization,
    }
    store.stamp_new(row)
    store.channels[row["id"]] = row
    return envelope.created(serialize.channel(row))


@bp.get("/channels/<identifier>")
def read_channel(identifier):
    auth.require(auth.OPERATORS)
    return envelope.ok(serialize.channel(resolve.channel(identifier)))


@bp.get("/channels")
def list_channels():
    auth.require(auth.OPERATORS)
    rows = envelope.apply_filters(
        store.sort_default(store.channels.values()),
        [("channel_type", envelope.str_filter("channel_type")),
         ("supports_total_price_display",
          envelope.bool_filter("supports_total_price_display")),
         ("supports_itemization", envelope.bool_filter("supports_itemization"))],
    )
    return envelope.page(rows, serialize.channel)
