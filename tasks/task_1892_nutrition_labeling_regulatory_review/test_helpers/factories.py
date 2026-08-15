"""Payload factories — one per entity, input fields only.

Defaults encode a complete nine-part nutrient profile (the "Wafers" profile)
and a standard 110g baked-good package; override per test as needed.
"""

DEFAULTS = {
    "CLIENT_NAME": "Acme Foods",
    "HOME_MARKET": "US_FDA",
    "PRODUCT_NAME": "Cookie",
    "PRODUCT_CATEGORY": "BAKED_GOOD",
    "NET_WEIGHT_G": 110,
    "SURFACE_AREA_SQ_IN": 30.0,
    "PDP_AREA_SQ_IN": 6.0,
    "HOUSEHOLD_UNIT_NAME": "piece",
    "HOUSEHOLD_UNIT_WEIGHT_G": 27.5,
    "RECIPE_NAME": "v1",
    "LAB_REPORT_REF": "LR-100",
    "DECLARED_FORMAT": "TABULAR",
    "DECLARED_TYPE_SIZE_IN": 0.0625,
    "FACILITY_CODE": "F1",
}

# Complete database nutrient profile (per 100 g) used unless overridden.
WAFER_PROFILE = {
    "kcal_per_100g": 400,
    "fat_g_per_100g": 8.0,
    "satfat_g_per_100g": 2.0,
    "chol_mg_per_100g": 0,
    "sodium_mg_per_100g": 200,
    "carb_g_per_100g": 70,
    "fiber_g_per_100g": 2.0,
    "sugar_g_per_100g": 20.0,
    "protein_g_per_100g": 5.0,
}

# Lab assay vector used by default for lab-analysis payloads.
LAB_ASSAY_LR100 = {
    "kcal_per_100g": 350.0,
    "fat_g_per_100g": 1.4,
    "satfat_g_per_100g": 0.2,
    "chol_mg_per_100g": 0,
    "sodium_mg_per_100g": 3.5,
    "carb_g_per_100g": 80.0,
    "fiber_g_per_100g": 2.2,
    "sugar_g_per_100g": 24.0,
    "protein_g_per_100g": 7.4,
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLIENT_NAME"],
        "home_market_code": DEFAULTS["HOME_MARKET"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(include_household=True, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "product_category": DEFAULTS["PRODUCT_CATEGORY"],
        "net_weight_g": DEFAULTS["NET_WEIGHT_G"],
        "total_surface_area_sq_in": DEFAULTS["SURFACE_AREA_SQ_IN"],
        "pdp_area_sq_in": DEFAULTS["PDP_AREA_SQ_IN"],
    }
    if include_household:
        defaults["household_unit_name"] = DEFAULTS["HOUSEHOLD_UNIT_NAME"]
        defaults["household_unit_weight_g"] = DEFAULTS["HOUSEHOLD_UNIT_WEIGHT_G"]
    defaults.update(overrides)
    return defaults


def create_ingredient_payload(include_allergen_tags=False, **overrides) -> dict:
    """Full-profile ingredient. allergen_tags is omitted unless requested so
    the documented empty-list default stays observable."""
    defaults = {"name": "Wafers"}
    defaults.update(WAFER_PROFILE)
    if include_allergen_tags:
        defaults["allergen_tags"] = []
    defaults.update(overrides)
    return defaults


def create_recipe_payload(lines, yield_factor=None, **overrides) -> dict:
    """lines is required. yield_factor is omitted unless given so the
    documented 1.0 default stays observable."""
    defaults = {"name": DEFAULTS["RECIPE_NAME"], "lines": lines}
    if yield_factor is not None:
        defaults["yield_factor"] = yield_factor
    defaults.update(overrides)
    return defaults


def create_lab_analysis_payload(**overrides) -> dict:
    defaults = {"lab_report_ref": DEFAULTS["LAB_REPORT_REF"]}
    defaults.update(LAB_ASSAY_LR100)
    defaults.update(overrides)
    return defaults


def review_lab_payload(outcome="VALIDATED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_nutrient_panel_payload(method="DATABASE", **overrides) -> dict:
    defaults = {"method": method}
    defaults.update(overrides)
    return defaults


def create_racc_assignment_payload(market_code="US_FDA", **overrides) -> dict:
    defaults = {"market_code": market_code}
    defaults.update(overrides)
    return defaults


def create_label_version_payload(racc_assignment_id, expected_product_version,
                                 ingredient_statement_text, contains_text,
                                 **overrides) -> dict:
    defaults = {
        "market_code": "US_FDA",
        "nutrient_basis": "DATABASE",
        "racc_assignment_id": racc_assignment_id,
        "declared_format": DEFAULTS["DECLARED_FORMAT"],
        "declared_type_size_in": DEFAULTS["DECLARED_TYPE_SIZE_IN"],
        "ingredient_statement_text": ingredient_statement_text,
        "contains_text": contains_text,
        "expected_product_version": expected_product_version,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(claim_type="LOW_FAT", **overrides) -> dict:
    defaults = {"claim_type": claim_type}
    defaults.update(overrides)
    return defaults


def create_market_variant_payload(effective_start, market_code="CA_CFIA",
                                  effective_end=None,
                                  translated_contains_text=None,
                                  **overrides) -> dict:
    defaults = {
        "market_code": market_code,
        "effective_start": effective_start,
    }
    if effective_end is not None:
        defaults["effective_end"] = effective_end
    if translated_contains_text is not None:
        defaults["translated_contains_text"] = translated_contains_text
    defaults.update(overrides)
    return defaults


def create_artwork_audit_payload(product_id, label_version_id, scheduled_start,
                                 scheduled_end, scoring_method=None, **overrides) -> dict:
    """scoring_method is omitted unless given so the documented WEIGHTED
    default stays observable."""
    defaults = {
        "product_id": product_id,
        "label_version_id": label_version_id,
        "facility_code": DEFAULTS["FACILITY_CODE"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if scoring_method is not None:
        defaults["scoring_method"] = scoring_method
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(severity="MAJOR", field_ref="NUTRITION_VALUES",
                                 on_pack_text="on-pack text",
                                 approved_text="approved text", **overrides) -> dict:
    defaults = {
        "severity": severity,
        "field_ref": field_ref,
        "on_pack_text": on_pack_text,
        "approved_text": approved_text,
    }
    defaults.update(overrides)
    return defaults
