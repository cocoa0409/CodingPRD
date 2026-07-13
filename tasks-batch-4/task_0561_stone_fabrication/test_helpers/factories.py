"""Payload factories — one per entity, input fields only."""


def create_project_payload(**overrides) -> dict:
    defaults = {
        "customer_name": "Test Customer",
        "address": "1 Rock Rd",
        "material_grade": "PREMIUM",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    defaults = {
        "expected_project_version": 1,
        "est_sqft": 40,
        "material_grade": "PREMIUM",
        "edge_profile": "OGEE",
        "edge_linear_ft": 25,
        "sink_count": 2,
        "faucet_count": 0,
        "cooktop_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_template_payload(**overrides) -> dict:
    defaults = {
        "measured_sqft": 40,
        "edge_profile": "OGEE",
        "edge_linear_ft": 25,
    }
    defaults.update(overrides)
    return defaults


def create_cutout_payload(**overrides) -> dict:
    defaults = {"cutout_type": "SINK"}
    defaults.update(overrides)
    return defaults


def create_slab_payload(**overrides) -> dict:
    defaults = {
        "slab_label": "SL1",
        "material_grade": "PREMIUM",
        "nominal_sqft": 50,
    }
    defaults.update(overrides)
    return defaults


def create_bay_payload(**overrides) -> dict:
    defaults = {"name": "BAY1"}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {"name": "CREW1"}
    defaults.update(overrides)
    return defaults


def create_fabrication_order_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "template_id": None,
        "slab_id": None,
        "bay_id": None,
        "scheduled_start": "2026-06-10T08:00:00Z",
        "scheduled_end": "2026-06-10T12:00:00Z",
        "pieces": [{"label": "A", "sqft": 25}, {"label": "B", "sqft": 15}],
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "fabrication_order_id": None,
        "crew_id": None,
        "install_date": "2026-06-15",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 170000, "kind": "DEPOSIT"}
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    defaults = {
        "expected_project_version": 1,
        "description": "scope change",
        "delta_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {"claim_type": "CRACK", "description": "hairline crack near sink"}
    defaults.update(overrides)
    return defaults
