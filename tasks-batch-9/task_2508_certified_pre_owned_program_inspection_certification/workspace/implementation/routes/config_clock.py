"""Programme configuration (PRD 2.6) and the logical clock (PRD 2.5)."""
from flask import Blueprint

import enums
import helpers as h
import serializers as ser
from db import CONFIG_FIELDS, cfg, db

bp = Blueprint("config", __name__)

_INT_FIELDS = {
    "max_age_days": 1,
    "max_odometer_miles": 1,
    "base_fee_cents": 0,
    "age_surcharge_free_years": 0,
    "age_surcharge_cents_per_year": 0,
    "mileage_surcharge_free_miles": 0,
    "mileage_surcharge_cents_per_10k": 0,
    "recon_reimbursement_cap_cents": 0,
    "factory_basic_months": 0,
    "factory_basic_miles": 0,
    "warranty_extension_months": 0,
    "warranty_extension_miles": 0,
    "warranty_total_cap_months": 0,
    "warranty_total_cap_miles": 0,
    "claim_per_claim_cap_cents": 0,
    "claim_window_days": 0,
    "claim_variant_volume_floor": 0,
    "audit_sample_min_per_run": 0,
    "audit_fail_suspension_count": 0,
    "doc_retention_years": 0,
    "listing_removal_sla_hours": 0,
    "inspection_slot_minutes": 0,
    "technician_buffer_minutes": 0,
}

_FRACTION_FIELDS = (
    "surcharge_cap_pct",
    "recon_reimbursement_share",
    "claim_ratio_probation_threshold",
    "claim_ratio_suspension_threshold",
    "probation_claim_share",
    "audit_sample_pct",
)


@bp.route("/program-config", methods=["GET"])
def read_config():
    h.authorize(enums.ALL_ROLES)
    return h.object_response(ser.program_config(cfg()))


@bp.route("/program-config", methods=["PUT"])
def retune_config():
    h.authorize(("ProgramAdministrator",))
    body = h.body_dict()
    # Unknown keys are ignored rather than rejected: the PRD declares every
    # tunable optional and says nothing about additional properties.
    updates = {}
    for field, minimum in _INT_FIELDS.items():
        if field in body:
            updates[field] = h.f_int(body, field, required=True, minimum=minimum)
    for field in _FRACTION_FIELDS:
        if field in body:
            updates[field] = h.f_number(body, field, required=True, minimum=0)
    if "ineligible_title_brands" in body:
        updates["ineligible_title_brands"] = h.f_enum_list(
            body, "ineligible_title_brands", enums.BRANDABLE, non_empty=False
        )
    if "ineligible_prior_uses" in body:
        updates["ineligible_prior_uses"] = h.f_enum_list(
            body, "ineligible_prior_uses", enums.PRIOR_USES, non_empty=False
        )
    if "required_doc_types" in body:
        updates["required_doc_types"] = h.f_enum_list(
            body, "required_doc_types", enums.DOC_TYPES, non_empty=False
        )
    if "listing_required_disclosure_fields" in body:
        tokens = h.f_list(
            body, "listing_required_disclosure_fields", non_empty=False
        )
        for token in tokens:
            if not isinstance(token, str) or token.strip() == "":
                h.bad_request(
                    "listing_required_disclosure_fields must hold non-empty strings."
                )
        updates["listing_required_disclosure_fields"] = list(tokens)
    if "volume_discount_tiers" in body:
        tiers = h.f_list(body, "volume_discount_tiers", non_empty=False)
        parsed = []
        for tier in tiers:
            if not isinstance(tier, dict):
                h.bad_request("Each volume discount tier must be an object.")
            min_count = h.f_int(tier, "min_count", required=True, minimum=0)
            pct = h.f_number(tier, "pct", required=True, minimum=0)
            parsed.append({"min_count": min_count, "pct": pct})
        seen = set()
        for tier in parsed:
            if tier["min_count"] in seen:
                h.bad_request("volume_discount_tiers min_count values must be unique.")
            seen.add(tier["min_count"])
        updates["volume_discount_tiers"] = parsed

    config = cfg()
    config.update(updates)
    h.touch(config)
    return h.object_response(ser.program_config(config))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    h.authorize(("ProgramAdministrator",))
    body = h.body_dict()
    raw = h.f_string(body, "current_utc")
    db.clock = h.parse_instant(raw, "Field 'current_utc'")
    return h.object_response({"current_utc": raw})
