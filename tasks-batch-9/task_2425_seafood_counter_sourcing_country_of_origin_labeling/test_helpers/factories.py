"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "STORE_NUMBER": "4120",
    "DEPARTMENT_NAME": "Seafood Service Counter",
    "CASE_SLOT_COUNT": 6,
    "SUPPLIER_NAME": "Gulf Bay Dealers",
    "PERMIT_NUMBER": "PERMIT-8801",
    "PROGRAM_NAME": "Blue Ocean Council",
    "CERTIFICATE_NUMBER": "BOC-77120",
    "CLAIM_TEXT": "Certified sustainable wild-capture fishery",
    "HEADLINE": "Fresh Atlantic Cod at the Counter",
    "VESSEL_NAME": "Estrella del Golfo",
    "CHAIN_OF_CUSTODY_REF": "COC-55210",
    "TAKEN_BY_USER_ID": "assoc-7",
}


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def counter_payload(**overrides) -> dict:
    payload = {
        "store_number": DEFAULTS["STORE_NUMBER"],
        "department_name": DEFAULTS["DEPARTMENT_NAME"],
        "case_slot_count": DEFAULTS["CASE_SLOT_COUNT"],
    }
    payload.update(overrides)
    return payload


def supplier_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SUPPLIER_NAME"],
        "permit_number": DEFAULTS["PERMIT_NUMBER"],
    }
    payload.update(overrides)
    return payload


def species_payload(**overrides) -> dict:
    payload = {
        "market_name": "Atlantic Cod",
        "scientific_name": "Gadus morhua",
        "acceptable_market_names": ["Atlantic Cod", "Cod"],
        "simp_covered": False,
        "high_risk_substitution": False,
        "sustainability_program_eligible": True,
    }
    payload.update(overrides)
    return payload


def atlantic_cod_payload(**overrides) -> dict:
    return species_payload(**overrides)


def tilapia_payload(**overrides) -> dict:
    return species_payload(
        market_name="Tilapia",
        scientific_name="Oreochromis niloticus",
        acceptable_market_names=["Tilapia"],
        simp_covered=False,
        high_risk_substitution=False,
        sustainability_program_eligible=False,
        **overrides,
    )


def red_snapper_payload(**overrides) -> dict:
    return species_payload(
        market_name="Red Snapper",
        scientific_name="Lutjanus campechanus",
        acceptable_market_names=["Red Snapper"],
        simp_covered=True,
        high_risk_substitution=True,
        sustainability_program_eligible=False,
        **overrides,
    )


def pacific_cod_payload(**overrides) -> dict:
    return species_payload(
        market_name="Pacific Cod",
        scientific_name="Gadus macrocephalus",
        acceptable_market_names=["Pacific Cod", "True Cod"],
        simp_covered=False,
        high_risk_substitution=False,
        sustainability_program_eligible=True,
        **overrides,
    )


def sockeye_salmon_payload(**overrides) -> dict:
    return species_payload(
        market_name="Sockeye Salmon",
        scientific_name="Oncorhynchus nerka",
        acceptable_market_names=["Sockeye Salmon", "Red Salmon"],
        simp_covered=False,
        high_risk_substitution=False,
        sustainability_program_eligible=True,
        **overrides,
    )


def gulf_grouper_payload(**overrides) -> dict:
    return species_payload(
        market_name="Gulf Grouper",
        scientific_name="Mycteroperca jordani",
        acceptable_market_names=["Gulf Grouper", "Grouper"],
        simp_covered=False,
        high_risk_substitution=True,
        sustainability_program_eligible=False,
        **overrides,
    )


# --------------------------------------------------------------------------
# Lot receipt
# --------------------------------------------------------------------------
def lot_payload(counter_id: str, supplier_id: str, species_id: str, **overrides) -> dict:
    payload = {
        "counter_id": counter_id,
        "supplier_id": supplier_id,
        "species_id": species_id,
        "lot_code": "COD-0801-A",
        "harvest_method": "WILD_LONGLINE",
        "production_method": "WILD",
        "origin_country_code": "US",
        "previously_frozen": False,
        "fresh_claim": True,
        "received_weight_kg": 20.000,
        "unit_cost_cents_per_kg": 1700,
        "retail_price_cents_per_kg": 2450,
        "cooked_retail_price_cents_per_kg": 2600,
    }
    payload.update(overrides)
    return payload


def tilapia_lot_payload(counter_id: str, supplier_id: str, species_id: str, **overrides) -> dict:
    variant = {
        "lot_code": "TIL-0801-B",
        "harvest_method": "AQUACULTURE_POND",
        "production_method": "FARMED",
        "origin_country_code": "EC",
        "previously_frozen": False,
        "fresh_claim": False,
        "received_weight_kg": 10.000,
        "unit_cost_cents_per_kg": 1700,
        "retail_price_cents_per_kg": 2300,
        "cooked_retail_price_cents_per_kg": 2500,
    }
    variant.update(overrides)
    return lot_payload(counter_id, supplier_id, species_id, **variant)


def snapper_lot_payload(counter_id: str, supplier_id: str, species_id: str, **overrides) -> dict:
    variant = {
        "lot_code": "SNP-0801-D",
        "harvest_method": "WILD_TRAP",
        "production_method": "WILD",
        "origin_country_code": "MX",
        "previously_frozen": False,
        "fresh_claim": False,
        "received_weight_kg": 15.000,
        "unit_cost_cents_per_kg": 2600,
        "retail_price_cents_per_kg": 3400,
        "cooked_retail_price_cents_per_kg": 3800,
    }
    variant.update(overrides)
    return lot_payload(counter_id, supplier_id, species_id, **variant)


# --------------------------------------------------------------------------
# Downstream records
# --------------------------------------------------------------------------
def case_label_payload(lot_id: str, expected_lot_version: int, **overrides) -> dict:
    payload = {"lot_id": lot_id, "expected_lot_version": expected_lot_version}
    payload.update(overrides)
    return payload


def ad_item_payload(counter_id: str, lot_id: str, **overrides) -> dict:
    payload = {
        "counter_id": counter_id,
        "lot_id": lot_id,
        "headline": DEFAULTS["HEADLINE"],
        "ad_start_at": "2026-08-01T09:00:00Z",
        "ad_end_at": "2026-08-08T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def ice_bed_reading_payload(counter_id: str, case_slot: int, reading_at: str,
                            temperature_c: float, **overrides) -> dict:
    payload = {
        "counter_id": counter_id,
        "case_slot": case_slot,
        "reading_at": reading_at,
        "temperature_c": temperature_c,
        "taken_by_user_id": DEFAULTS["TAKEN_BY_USER_ID"],
    }
    payload.update(overrides)
    return payload


def simp_document_payload(lot_id: str, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "harvesting_vessel_name": DEFAULTS["VESSEL_NAME"],
        "harvest_date": "2026-07-20T00:00:00Z",
        "landing_date": "2026-07-22T00:00:00Z",
        "chain_of_custody_ref": DEFAULTS["CHAIN_OF_CUSTODY_REF"],
    }
    payload.update(overrides)
    return payload


def certification_payload(counter_id: str, supplier_id: str, species_id: str, **overrides) -> dict:
    payload = {
        "counter_id": counter_id,
        "supplier_id": supplier_id,
        "species_id": species_id,
        "program_name": DEFAULTS["PROGRAM_NAME"],
        "certificate_number": DEFAULTS["CERTIFICATE_NUMBER"],
        "valid_from": "2026-07-01T00:00:00Z",
        "valid_until": "2026-12-01T00:00:00Z",
        "claim_text": DEFAULTS["CLAIM_TEXT"],
    }
    payload.update(overrides)
    return payload


def shrink_event_payload(lot_id: str, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "reason": "UNSOLD_FRESH",
        "shrink_weight_kg": 8.375,
        "conversion_requested_kg": 6.000,
    }
    payload.update(overrides)
    return payload


def verification_sample_payload(lot_id: str, **overrides) -> dict:
    payload = {"lot_id": lot_id, "sampled_weight_g": 150}
    payload.update(overrides)
    return payload
