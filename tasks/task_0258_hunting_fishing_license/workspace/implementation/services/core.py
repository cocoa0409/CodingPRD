"""Business-logic constants, calculations, and shared lookups.

Calculations follow PRD §3.5 (license_fee), §3.8 (draw_priority_score),
§3.9 (season_bag_budget), §3.10 (replacement_admin_fee) and SCAFFOLD §1.3.
All money is integer cents; round-half-up applied once (PRD §2.8).
"""
from decimal import Decimal, ROUND_HALF_UP

from db import store, parse_dt
from errors import err, ERR_NOT_FOUND, ERR_RESIDENCY_RESTRICTED

# ---- constants (SCAFFOLD §1.3) ----
NONRESIDENT_MULTIPLIER = Decimal("2.5")
AGENT_SURCHARGE_CENTS = 300
MAX_PREFERENCE_POINTS = 12
RESIDENCY_MIN_MONTHS = 12
REPLACEMENT_BASE_CENTS = 1500
TAG_REPLACEMENT_SURCHARGE_CENTS = 1000
NONRESIDENT_REPLACEMENT_SURCHARGE_CENTS = 500


# ---- existence helpers (raise ERR_NOT_FOUND) ----
def get_applicant_or_404(applicant_id):
    r = store.applicants.get(applicant_id)
    if r is None:
        raise err(ERR_NOT_FOUND, "Applicant not found")
    return r


def get_residency_verification_or_404(rid):
    r = store.residency_verifications.get(rid)
    if r is None:
        raise err(ERR_NOT_FOUND, "ResidencyVerification not found")
    return r


def get_education_certificate_or_404(eid):
    r = store.education_certificates.get(eid)
    if r is None:
        raise err(ERR_NOT_FOUND, "EducationCertificate not found")
    return r


def get_license_product_or_404(pid):
    r = store.license_products.get(pid)
    if r is None:
        raise err(ERR_NOT_FOUND, "LicenseProduct not found")
    return r


def get_species_season_or_404(sid):
    r = store.species_seasons.get(sid)
    if r is None:
        raise err(ERR_NOT_FOUND, "SpeciesSeason not found")
    return r


def get_draw_pool_or_404(pid):
    r = store.draw_pools.get(pid)
    if r is None:
        raise err(ERR_NOT_FOUND, "DrawPool not found")
    return r


def get_draw_application_or_404(aid):
    r = store.draw_applications.get(aid)
    if r is None:
        raise err(ERR_NOT_FOUND, "DrawApplication not found")
    return r


def get_license_or_404(lid):
    r = store.licenses.get(lid)
    if r is None:
        raise err(ERR_NOT_FOUND, "License not found")
    return r


def get_harvest_report_or_404(hid):
    r = store.harvest_reports.get(hid)
    if r is None:
        raise err(ERR_NOT_FOUND, "HarvestReport not found")
    return r


def get_replacement_or_404(rid):
    r = store.replacements.get(rid)
    if r is None:
        raise err(ERR_NOT_FOUND, "Replacement not found")
    return r


# ---- calculation: license_fee (PRD §3.5) ----
def check_residency_restriction(product, applicant):
    """Enforce residency restriction (raises ERR_RESIDENCY_RESTRICTED)."""
    restriction = product["residency_restriction"]
    rs = applicant["residency_status"]
    if restriction == "RESIDENT_ONLY" and rs != "RESIDENT":
        raise err(ERR_RESIDENCY_RESTRICTED, "Product is RESIDENT_ONLY")
    if restriction == "NONRESIDENT_ONLY" and rs != "NONRESIDENT":
        raise err(ERR_RESIDENCY_RESTRICTED, "Product is NONRESIDENT_ONLY")


def compute_license_fee(product, applicant, issued_via):
    """Residency multiplier first (round once), then OTC agent surcharge.

    Assumes the residency restriction has already been validated.
    """
    base = product["base_fee_cents"]
    if applicant["residency_status"] == "NONRESIDENT":
        priced = int(
            (Decimal(base) * NONRESIDENT_MULTIPLIER).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    else:
        priced = base
    if issued_via == "OVER_THE_COUNTER":
        priced = priced + AGENT_SURCHARGE_CENTS
    return priced


# ---- calculation: draw_priority_score (PRD §3.8) ----
def compute_priority_score(points_at_entry, bonus_at_entry, scoring_model):
    pp = points_at_entry
    b = bonus_at_entry
    if scoring_model == "SQUARED":
        return pp * pp + b
    return pp + b  # LINEAR


# ---- calculation: season_bag_budget_remaining (PRD §3.9) ----
def applicant_licenses_for_season(applicant_id, season_id):
    """All License ids held by the applicant whose product is bound to season."""
    result = []
    for lic in store.licenses.values():
        if lic["applicant_id"] != applicant_id:
            continue
        product = store.license_products.get(lic["license_product_id"])
        if product is None:
            continue
        if product["species_season_id"] == season_id:
            result.append(lic["id"])
    return result


def counted_quantity_for_season(applicant_id, season_id):
    """Sum quantity of SUBMITTED+ACCEPTED reports under the applicant's
    licenses for this season (REJECTED excluded)."""
    license_ids = set(applicant_licenses_for_season(applicant_id, season_id))
    counted = 0
    for hr in store.harvest_reports.values():
        if hr["license_id"] in license_ids and hr["status"] in ("SUBMITTED", "ACCEPTED"):
            counted += hr["quantity"]
    return counted


# ---- calculation: replacement_admin_fee (PRD §3.10) ----
def compute_replacement_admin_fee(original_license, reason):
    if reason == "STOLEN":
        return 0
    kind = store.license_products[original_license["license_product_id"]]["product_kind"]
    applicant = store.applicants[original_license["applicant_id"]]
    base = REPLACEMENT_BASE_CENTS
    if kind == "TAG":
        base = base + TAG_REPLACEMENT_SURCHARGE_CENTS
    if applicant["residency_status"] == "NONRESIDENT":
        base = base + NONRESIDENT_REPLACEMENT_SURCHARGE_CENTS
    return base


# ---- age helper (PRD §3.7 minimum-age) ----
def age_in_years(birth_date_str, on_dt):
    """Whole-years age of an applicant on the given instant.

    birth_date is a YYYY-MM-DD calendar date; on_dt is a tz-aware datetime.
    """
    bd = parse_dt(birth_date_str + "T00:00:00Z")
    years = on_dt.year - bd.year
    # Subtract one if the birthday hasn't occurred yet this year.
    if (on_dt.month, on_dt.day) < (bd.month, bd.day):
        years -= 1
    return years
