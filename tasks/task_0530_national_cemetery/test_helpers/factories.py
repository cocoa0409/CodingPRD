"""Payload factories — one per entity, input fields only."""


def create_cemetery_payload(**overrides) -> dict:
    defaults = {
        "name": "Test National Cemetery",
        "country_code": "US",
        "honors_squad_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(cemetery_id, **overrides) -> dict:
    defaults = {
        "cemetery_id": cemetery_id,
        "code": "A",
        "kind": "IN_GROUND",
    }
    defaults.update(overrides)
    return defaults


def create_gravesite_payload(section_id, **overrides) -> dict:
    defaults = {
        "section_id": section_id,
        "grid_ref": "R1C1",
        "gravesite_class": "STANDARD",
        "depth_capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_niche_payload(section_id, **overrides) -> dict:
    defaults = {
        "section_id": section_id,
        "niche_ref": "T1N1",
        "urn_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_burial_case_payload(cemetery_id, **overrides) -> dict:
    """VETERAN AT_NEED case with a passing service history by default."""
    defaults = {
        "cemetery_id": cemetery_id,
        "case_type": "AT_NEED",
        "applicant_role": "VETERAN",
        "requested_class": "STANDARD",
        "character_of_discharge": "HONORABLE",
        "service_days": 3650,
        "died_on_active_duty": False,
    }
    defaults.update(overrides)
    return defaults


def create_pmc_payload(burial_case_id, **overrides) -> dict:
    defaults = {"burial_case_id": burial_case_id}
    defaults.update(overrides)
    return defaults


def create_interment_schedule_payload(burial_case_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "burial_case_id": burial_case_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_marker_order_payload(burial_case_id, **overrides) -> dict:
    defaults = {
        "burial_case_id": burial_case_id,
        "marker_type": "FLAT_GRANITE",
        "inscription_lines": ["A VETERAN"],
    }
    defaults.update(overrides)
    return defaults


def create_military_honors_payload(interment_schedule_id, **overrides) -> dict:
    defaults = {
        "interment_schedule_id": interment_schedule_id,
        "detail_size": "TWO_PERSON",
    }
    defaults.update(overrides)
    return defaults
