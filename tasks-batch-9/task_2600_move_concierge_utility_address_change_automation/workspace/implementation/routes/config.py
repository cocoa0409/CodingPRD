"""Configuration surface: feed sources, residents, service addresses, utility
providers, service territories and referral partners."""

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    FEED_INTEGRATOR,
    MOVE_OPS_AGENT,
    PARTNER_AGENT,
    PROVIDER_AGENT,
    RESIDENT,
    authenticate,
)
from services import cascades, enums, mapping
from services.lookup import (
    feed_source_or_404,
    address_or_404,
    partner_or_404,
    provider_or_404,
    ref_provider,
    resident_or_404,
    territory_or_404,
)

bp = Blueprint("config", __name__)


# ------------------------------------------------------------- feed sources
@bp.post("/feed-sources")
def create_feed_source():
    authenticate()
    body = v.body()
    name = v.str_field(body, "name", min_len=1, max_len=120)
    source_type = v.enum_field(body, "source_type", enums.SOURCE_TYPES)
    share = v.decimal_field(
        body, "referral_revenue_share_pct", minimum="0.0000", maximum="0.5000"
    )
    dedupe = v.int_field(body, "dedupe_window_days", required=False, minimum=1, maximum=120, default=30)
    tier = v.enum_field(body, "trust_tier", enums.TRUST_TIERS, required=False, default="TIER_B")

    rec = db.base_record()
    rec.update(
        {
            "name": name,
            "source_type": source_type,
            "dedupe_window_days": dedupe,
            "trust_tier": tier,
            "referral_revenue_share_pct": share,
            "accrued_share_cents": 0,
            "feed_status": "ACTIVE",
        }
    )
    db.db.feed_sources[rec["id"]] = rec
    return response.created(db.public(rec))


@bp.get("/feed-sources/<feed_id>")
def read_feed_source(feed_id):
    caller = authenticate(FEED_INTEGRATOR, MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    rec = feed_source_or_404(feed_id)
    caller.own_if(FEED_INTEGRATOR, rec["id"])
    return response.ok(db.public(rec))


@bp.patch("/feed-sources/<feed_id>/status")
def set_feed_status(feed_id):
    authenticate()
    rec = feed_source_or_404(feed_id)
    body = v.body()
    rec["feed_status"] = v.enum_field(body, "feed_status", enums.FEED_STATUSES)
    db.touch(rec)
    return response.ok(db.public(rec))


# ---------------------------------------------------------------- residents
@bp.post("/residents")
def create_resident():
    authenticate(FEED_INTEGRATOR, MOVE_OPS_AGENT)
    body = v.body()
    full_name = v.str_field(body, "full_name", min_len=1, max_len=120)
    email = v.str_field(body, "email", min_len=3, max_len=200)
    if email.count("@") != 1:
        v.bad("Field 'email' must contain exactly one '@'.")
    phone_last4 = v.str_field(body, "phone_last4", min_len=4, max_len=4)
    if not phone_last4.isdigit():
        v.bad("Field 'phone_last4' must be exactly four digits.")
    dob_text, _dob = v.date_field(body, "date_of_birth")
    ssn_last4 = v.str_field(body, "ssn_last4", min_len=4, max_len=4)
    if not ssn_last4.isdigit():
        v.bad("Field 'ssn_last4' must be exactly four digits.")
    opt_out = v.bool_field(body, "marketing_opt_out", required=False, default=False)

    rec = db.base_record()
    rec.update(
        {
            "full_name": full_name,
            "email": email,
            "phone_last4": phone_last4,
            "date_of_birth": dob_text,
            "ssn_last4": ssn_last4,
            "marketing_opt_out": opt_out,
            "opted_out_at": None,
        }
    )
    db.db.residents[rec["id"]] = rec
    return response.created(db.public(rec))


@bp.get("/residents/<resident_id>")
def read_resident(resident_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, RESIDENT)
    rec = resident_or_404(resident_id)
    caller.own_if(RESIDENT, rec["id"])
    return response.ok(db.public(rec))


@bp.patch("/residents/<resident_id>/marketing-preferences")
def set_marketing_preferences(resident_id):
    caller = authenticate(COMPLIANCE_OFFICER, RESIDENT)
    rec = resident_or_404(resident_id)
    caller.own_if(RESIDENT, rec["id"])
    body = v.body()
    wanted = v.bool_field(body, "marketing_opt_out")

    rec["marketing_opt_out"] = wanted
    if wanted:
        rec["opted_out_at"] = db.now_iso()
        db.touch(rec)
        cascades.void_open_placements_of_resident(rec)
    else:
        rec["opted_out_at"] = None
        db.touch(rec)
    return response.ok(db.public(rec))


# --------------------------------------------------------- service addresses
@bp.post("/service-addresses")
def create_service_address():
    authenticate(FEED_INTEGRATOR, MOVE_OPS_AGENT)
    body = v.body()
    line1 = v.str_field(body, "line1", min_len=1, max_len=160)
    city = v.str_field(body, "city", min_len=1, max_len=120)
    state_code = v.str_field(body, "state_code", min_len=2, max_len=2)
    if not (state_code.isalpha() and state_code.isupper()):
        v.bad("Field 'state_code' must be two uppercase letters.")
    postal_code = v.str_field(body, "postal_code", min_len=5, max_len=5)
    if not postal_code.isdigit():
        v.bad("Field 'postal_code' must be exactly five digits.")
    unit = v.str_field(body, "unit", required=False, min_len=1, max_len=40, default=None)

    rec = db.base_record()
    rec.update(
        {
            "line1": line1,
            "unit": unit,
            "city": city,
            "state_code": state_code,
            "postal_code": postal_code,
            "address_hash": "%s|%s|%s" % (line1.lower(), (unit or "").lower(), postal_code),
            "usps_deliverable": not postal_code.startswith("000"),
        }
    )
    db.db.service_addresses[rec["id"]] = rec
    return response.created(db.public(rec))


@bp.get("/service-addresses/<address_id>")
def read_service_address(address_id):
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    return response.ok(db.public(address_or_404(address_id)))


# --------------------------------------------------------- utility providers
@bp.post("/utility-providers")
def create_utility_provider():
    authenticate()
    body = v.body()
    name = v.str_field(body, "name", min_len=1, max_len=120)
    utility_type = v.enum_field(body, "utility_type", enums.UTILITY_TYPES)
    fields = v.list_field(
        body,
        "required_account_fields",
        min_len=1,
        max_len=6,
        allowed=enums.ACCOUNT_FIELD_NAMES,
    )
    deposit_policy = v.enum_field(body, "deposit_policy", enums.DEPOSIT_POLICIES)
    credit_check_required = v.bool_field(body, "credit_check_required")
    lead_days = v.int_field(
        body, "scheduling_lead_days", minimum=0, maximum=enums.MAX_SCHEDULING_LEAD_DAYS
    )
    flat_deposit = v.int_field(body, "flat_deposit_cents", required=False, minimum=0, default=0)
    same_day_stop = v.bool_field(body, "same_day_stop_allowed", required=False, default=False)

    # rung 46: a FLAT policy may not exceed the deposit ceiling.
    if deposit_policy == "FLAT" and flat_deposit > enums.DEPOSIT_CAP_CENTS:
        raise ApiError(
            "ERR_DEPOSIT_CAP_EXCEEDED",
            "flat_deposit_cents may not exceed %d." % enums.DEPOSIT_CAP_CENTS,
        )

    rec = db.base_record()
    rec.update(
        {
            "name": name,
            "utility_type": utility_type,
            "required_account_fields": list(fields),
            "deposit_policy": deposit_policy,
            "flat_deposit_cents": flat_deposit,
            "credit_check_required": credit_check_required,
            "scheduling_lead_days": lead_days,
            "same_day_stop_allowed": same_day_stop,
            "provider_status": "ACTIVE",
        }
    )
    db.db.utility_providers[rec["id"]] = rec
    return response.created(db.public(rec))


@bp.get("/utility-providers/<provider_id>")
def read_utility_provider(provider_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, PROVIDER_AGENT)
    rec = provider_or_404(provider_id)
    caller.own_if(PROVIDER_AGENT, rec["id"])
    return response.ok(db.public(rec))


@bp.patch("/utility-providers/<provider_id>/status")
def set_provider_status(provider_id):
    authenticate()
    rec = provider_or_404(provider_id)
    body = v.body()
    rec["provider_status"] = v.enum_field(body, "provider_status", enums.PROVIDER_STATUSES)
    db.touch(rec)
    return response.ok(db.public(rec))


# ------------------------------------------------------ service territories
@bp.post("/provider-service-territories")
def create_territory():
    caller = authenticate(PROVIDER_AGENT)
    body = v.body()
    provider = ref_provider(v.id_field(body, "provider_id", required=False))
    caller.own_if(PROVIDER_AGENT, provider["id"] if provider else caller.user_id)
    if provider is None:
        v.bad("Field 'provider_id' is required.")

    postal_code = v.str_field(body, "postal_code", min_len=5, max_len=5)
    if not postal_code.isdigit():
        v.bad("Field 'postal_code' must be exactly five digits.")
    state_code = v.str_field(body, "state_code", min_len=2, max_len=2)
    if not (state_code.isalpha() and state_code.isupper()):
        v.bad("Field 'state_code' must be two uppercase letters.")
    from_text, from_date = v.date_field(body, "effective_from")
    priority_rank = v.int_field(body, "priority_rank", minimum=1, maximum=999)
    to_text, to_date = v.date_field(body, "effective_to", required=False, default=None)
    if to_date is not None and to_date < from_date:
        v.bad("Field 'effective_to' must not precede 'effective_from'.")
    is_default = v.bool_field(body, "is_default_carrier", required=False, default=False)

    # rung 33: default-carrier rows must be separated by a clear day.
    if is_default:
        mapping.check_territory_overlap(provider, postal_code, from_date)

    rec = db.base_record()
    rec.update(
        {
            "provider_id": provider["id"],
            "postal_code": postal_code,
            "state_code": state_code,
            "effective_from": from_text,
            "effective_to": to_text,
            "is_default_carrier": is_default,
            "priority_rank": priority_rank,
        }
    )
    db.db.territories[rec["id"]] = rec
    return response.created(db.public(rec))


@bp.get("/provider-service-territories/<territory_id>")
def read_territory(territory_id):
    caller = authenticate(MOVE_OPS_AGENT, PROVIDER_AGENT)
    rec = territory_or_404(territory_id)
    caller.own_if(PROVIDER_AGENT, rec["provider_id"])
    return response.ok(db.public(rec))


@bp.get("/provider-service-territories")
def list_territories():
    authenticate(MOVE_OPS_AGENT, PROVIDER_AGENT)
    rows = response.match_filters(
        db.db.territories.values(),
        {
            "provider_id": "provider_id",
            "postal_code": "postal_code",
            "state_code": "state_code",
            "is_default_carrier": "is_default_carrier",
        },
    )
    return response.paginated(rows)


# -------------------------------------------------------- referral partners
@bp.post("/referral-partners")
def create_partner():
    authenticate()
    body = v.body()
    name = v.str_field(body, "name", min_len=1, max_len=120)
    vertical = v.enum_field(body, "vertical", enums.VERTICALS)
    payout_model = v.enum_field(body, "payout_model", enums.PAYOUT_MODELS)
    window_days = v.int_field(body, "attribution_window_days", minimum=1, maximum=90)
    basis = v.enum_field(body, "attribution_basis", enums.ATTRIBUTION_BASES)
    cap = v.int_field(body, "monthly_placement_cap", minimum=1, maximum=1000)
    rev_share = v.decimal_field(
        body, "rev_share_pct", required=False, minimum="0.0000", maximum="0.9000", default=None
    )
    bounty = v.int_field(body, "bounty_cents", required=False, minimum=0, default=None)

    if payout_model == "FLAT_BOUNTY" and bounty is None:
        v.bad("Field 'bounty_cents' is required for a FLAT_BOUNTY payout model.")
    if payout_model == "REV_SHARE_PCT" and rev_share is None:
        v.bad("Field 'rev_share_pct' is required for a REV_SHARE_PCT payout model.")

    rec = db.base_record()
    rec.update(
        {
            "name": name,
            "vertical": vertical,
            "payout_model": payout_model,
            "bounty_cents": bounty if bounty is not None else 0,
            "rev_share_pct": rev_share if rev_share is not None else db.round_money("0", 4),
            "attribution_window_days": window_days,
            "attribution_basis": basis,
            "monthly_placement_cap": cap,
            "partner_status": "ACTIVE",
        }
    )
    db.db.partners[rec["id"]] = rec
    return response.created(db.public(rec))


@bp.get("/referral-partners/<partner_id>")
def read_partner(partner_id):
    caller = authenticate(MOVE_OPS_AGENT, PARTNER_AGENT)
    rec = partner_or_404(partner_id)
    caller.own_if(PARTNER_AGENT, rec["id"])
    return response.ok(db.public(rec))


@bp.patch("/referral-partners/<partner_id>/status")
def set_partner_status(partner_id):
    authenticate()
    rec = partner_or_404(partner_id)
    body = v.body()
    rec["partner_status"] = v.enum_field(body, "partner_status", enums.PARTNER_STATUSES)
    db.touch(rec)
    return response.ok(db.public(rec))
