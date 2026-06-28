"""Quote pricing, compliance gates, and TTL expiry."""
from datetime import timedelta

import db
import errors
from errors import ApiError
from models import touch
from services import calculations

# Material category <-> service type one-to-one mapping
COMPAT = {
    "TINT": "TINT_FILM",
    "PPF": "PPF_FILM",
    "WRAP": "WRAP_VINYL",
    "CERAMIC": "CERAMIC_COATING",
}


def material_compatible(service_type, material_category):
    return COMPAT.get(service_type) == material_category


def included_lines(quote_id):
    lines = [l for l in db.quote_lines.values()
             if l["quote_id"] == quote_id and l["status"] == "INCLUDED"]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    return lines


def observe_ttl_expiry(quote):
    """Lazy TTL: a PRICED quote past created_at + QUOTE_TTL_DAYS becomes EXPIRED
    on the next read/price. Mutates and returns the quote.
    """
    if quote["status"] != "PRICED":
        return quote
    created = db.parse_iso(quote["created_at"])
    deadline = created + timedelta(days=calculations.QUOTE_TTL_DAYS)
    if db.now() >= deadline:
        quote["status"] = "EXPIRED"
        touch(quote)
    return quote


def _state_regulation_for_shop(shop):
    state_code = shop.get("state_code")
    for reg in db.state_tint_regulations.values():
        if reg.get("state_code") == state_code:
            return reg
    return None


def _approved_exemption(vehicle_profile_id):
    """Return an APPROVED MedicalExemption covering the vehicle, or None."""
    for ex in db.medical_exemptions.values():
        if ex["vehicle_profile_id"] == vehicle_profile_id and ex["status"] == "APPROVED":
            return ex
    return None


def run_compliance_gates(quote):
    """Run the three pricing gates in fixed order before money is computed
    (PRD §3.4). Also re-verify material compatibility (priority 40).

    Gate order:
      1. exemption applicability (ERR_EXEMPTION_NOT_ALLOWED, 422)
      2. front-side VLT floor (ERR_TINT_BELOW_LEGAL_VLT, 422)
      3. windshield strip limit (ERR_WINDSHIELD_STRIP_EXCEEDS_LIMIT, 422)
    """
    lines = included_lines(quote["id"])
    shop = db.shop_locations.get(quote["shop_location_id"])
    regulation = _state_regulation_for_shop(shop) if shop else None

    vehicle_profile_id = quote["vehicle_profile_id"]
    exemption = _approved_exemption(vehicle_profile_id)
    medical_allowed = bool(regulation.get("medical_exemption_allowed")) if regulation else False

    # Compute the effective front-side floor.
    statutory_floor = regulation.get("front_side_min_vlt_pct") if regulation else None

    # Gate 1: exemption applicability — if a FRONT_SIDE line is below the statutory
    # floor AND an APPROVED exemption covers the vehicle BUT the state's
    # medical_exemption_allowed is false -> ERR_EXEMPTION_NOT_ALLOWED.
    if regulation is not None and statutory_floor is not None and exemption is not None and not medical_allowed:
        for line in lines:
            if line["window_position"] == "FRONT_SIDE" and line["requested_vlt_pct"] < statutory_floor:
                raise ApiError(errors.ERR_EXEMPTION_NOT_ALLOWED, 422,
                               "Medical exemption cannot be used in this state.")

    # Effective floor: lowered to exemption.exempt_min_vlt_pct only when the state
    # allows medical exemptions and an APPROVED exemption covers the vehicle.
    effective_floor = statutory_floor
    if statutory_floor is not None and medical_allowed and exemption is not None:
        effective_floor = exemption["exempt_min_vlt_pct"]

    # Gate 2: front-side VLT floor.
    if effective_floor is not None:
        for line in lines:
            if line["window_position"] == "FRONT_SIDE" and line["requested_vlt_pct"] < effective_floor:
                raise ApiError(errors.ERR_TINT_BELOW_LEGAL_VLT, 422,
                               "FRONT_SIDE requested_vlt_pct is below the effective legal floor.")

    # Gate 3: windshield strip limit (no exemption overrides this).
    if regulation is not None:
        max_strip = regulation.get("windshield_strip_max_inches")
        if max_strip is not None:
            for line in lines:
                if line["window_position"] == "WINDSHIELD" and line["strip_depth_inches"] > max_strip:
                    raise ApiError(errors.ERR_WINDSHIELD_STRIP_EXCEEDS_LIMIT, 422,
                                   "WINDSHIELD strip_depth_inches exceeds the allowed depth.")

    # Material compatibility re-verified at pricing time (priority 40).
    for line in lines:
        pkg = db.service_packages.get(line["service_package_id"])
        mat = db.film_materials.get(line["film_material_id"])
        if not material_compatible(pkg["service_type"], mat["category"]):
            raise ApiError(errors.ERR_MATERIAL_INCOMPATIBLE, 422,
                           "Material category incompatible with package service_type.")


def price_quote(quote):
    """Recompute line totals and quote-level money fields. Caller has already
    validated state, version, included-lines, and compliance.
    """
    lines = included_lines(quote["id"])
    vehicle = db.vehicle_profiles.get(quote["vehicle_profile_id"])
    size_surcharge = vehicle["size_surcharge_cents"]

    line_totals = []
    for line in lines:
        pkg = db.service_packages.get(line["service_package_id"])
        mat = db.film_materials.get(line["film_material_id"])
        total = calculations.line_item_price(
            base_rate_cents=pkg["base_rate_cents"],
            coverage=line["coverage"],
            price_multiplier_bps=mat["price_multiplier_bps"],
            size_surcharge_cents=size_surcharge,
        )
        line["line_total_cents"] = total
        touch(line)
        line_totals.append(total)

    fleet_discount_bps = 0
    if quote.get("fleet_account_id"):
        fleet = db.fleet_accounts.get(quote["fleet_account_id"])
        if fleet:
            fleet_discount_bps = fleet["discount_bps"]

    totals = calculations.quote_total(line_totals, fleet_discount_bps, quote["rushed"])
    quote.update(totals)


def zero_money_fields(quote):
    quote["subtotal_cents"] = 0
    quote["discount_cents"] = 0
    quote["net_cents"] = 0
    quote["rush_fee_cents"] = 0
    quote["total_due_cents"] = 0
    quote["deposit_required_cents"] = 0
