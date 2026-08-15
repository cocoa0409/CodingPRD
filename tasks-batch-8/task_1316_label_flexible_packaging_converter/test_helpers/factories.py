"""Payload factories — one per entity, input fields only (PRD §3/§4)."""


def create_customer_payload(**overrides) -> dict:
    defaults = {"account_name": "Test Customer"}
    defaults.update(overrides)
    return defaults


def create_artwork_version_payload(**overrides) -> dict:
    defaults = {
        "artwork_code": "AW-1",
        "revision_no": 1,
        "color_count": 2,
        "plate_set_cost_cents": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_substrate_payload(**overrides) -> dict:
    defaults = {
        "substrate_code": "BOPP-30",
        "width_mm": 1000,
        "cost_per_msq_cents": 40,
    }
    defaults.update(overrides)
    return defaults


def create_ink_recipe_payload(**overrides) -> dict:
    defaults = {
        "recipe_code": "INK-1",
        "cost_per_lb_cents": 300,
    }
    defaults.update(overrides)
    return defaults


def create_die_payload(**overrides) -> dict:
    defaults = {
        "die_code": "D-1",
        "shape_description": "rect 76x50",
        "cavities_across": 4,
    }
    defaults.update(overrides)
    return defaults


def create_press_payload(**overrides) -> dict:
    defaults = {
        "press_code": "P-1",
        "station_count": 4,
        "setup_waste_ft": 300,
        "run_waste_pct_numerator": 5,
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(artwork_version_id: str, substrate_id: str,
                       ink_recipe_id: str, die_id: str, press_id: str,
                       **overrides) -> dict:
    defaults = {
        "artwork_version_id": artwork_version_id,
        "substrate_id": substrate_id,
        "ink_recipe_id": ink_recipe_id,
        "die_id": die_id,
        "press_id": press_id,
        "quantity_ordered": 1000,
        "repeat_length_mm": 76,
        "rewind_max_rolls": 2,
        "max_splices_per_roll": 1,
    }
    defaults.update(overrides)
    return defaults


def create_color_measurement_payload(**overrides) -> dict:
    defaults = {"station_no": 1, "delta_e": 1.0}
    defaults.update(overrides)
    return defaults


def create_rewind_roll_payload(**overrides) -> dict:
    defaults = {"roll_seq": 1, "label_count": 1000, "splice_count": 0}
    defaults.update(overrides)
    return defaults


def create_compliance_letter_payload(**overrides) -> dict:
    defaults = {
        "letter_type": "FOOD_CONTACT",
        "body": "We certify the substrate and ink recipe conform to "
                "food-contact requirements.",
    }
    defaults.update(overrides)
    return defaults
