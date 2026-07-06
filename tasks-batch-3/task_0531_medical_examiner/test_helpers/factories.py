"""Payload factories — one per entity, input fields only."""
from .constants import SERVED_COUNTY


def create_investigator_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Investigator", "badge_no": "BADGE-1"}
    defaults.update(overrides)
    return defaults


def create_pathologist_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Pathologist", "license_no": "LIC-1"}
    defaults.update(overrides)
    return defaults


def create_cooler_unit_payload(**overrides) -> dict:
    defaults = {"label": "COOLER-1", "slot_capacity": 2}
    defaults.update(overrides)
    return defaults


def create_case_payload(investigator_user_id, **overrides) -> dict:
    defaults = {
        "decedent_name": "Doe",
        "reported_death_at": "2026-05-01T00:00:00Z",
        "death_location_county": SERVED_COUNTY,
        "investigator_user_id": investigator_user_id,
    }
    defaults.update(overrides)
    return defaults


def triage_payload(case_type="NATURAL", **overrides) -> dict:
    defaults = {"case_type": case_type}
    defaults.update(overrides)
    return defaults


def create_body_payload(tag_no="TAG-1", **overrides) -> dict:
    defaults = {"tag_no": tag_no}
    defaults.update(overrides)
    return defaults


def store_body_payload(cooler_unit_id, expected_cooler_version, **overrides) -> dict:
    defaults = {
        "cooler_unit_id": cooler_unit_id,
        "expected_cooler_version": expected_cooler_version,
    }
    defaults.update(overrides)
    return defaults


def create_autopsy_exam_payload(pathologist_user_id, scheduled_for, duration_minutes, **overrides) -> dict:
    defaults = {
        "pathologist_user_id": pathologist_user_id,
        "scheduled_for": scheduled_for,
        "duration_minutes": duration_minutes,
    }
    defaults.update(overrides)
    return defaults


def complete_autopsy_exam_payload(primary_finding="finding", cause_of_death="cause", **overrides) -> dict:
    defaults = {"primary_finding": primary_finding, "cause_of_death": cause_of_death}
    defaults.update(overrides)
    return defaults


def create_specimen_payload(specimen_type="BLOOD", **overrides) -> dict:
    defaults = {"specimen_type": specimen_type}
    defaults.update(overrides)
    return defaults


def create_tox_screen_payload(panel="BASIC", **overrides) -> dict:
    defaults = {"panel": panel}
    defaults.update(overrides)
    return defaults


def result_tox_screen_payload(ethanol_mg_dl=0, **overrides) -> dict:
    defaults = {"ethanol_mg_dl": ethanol_mg_dl}
    defaults.update(overrides)
    return defaults


def amend_tox_screen_payload(ethanol_mg_dl=0, **overrides) -> dict:
    defaults = {"ethanol_mg_dl": ethanol_mg_dl}
    defaults.update(overrides)
    return defaults


def create_death_certificate_payload(cause_of_death="cause", manner_of_death="NATURAL", **overrides) -> dict:
    defaults = {"cause_of_death": cause_of_death, "manner_of_death": manner_of_death}
    defaults.update(overrides)
    return defaults


def sign_death_certificate_payload(expected_case_version, **overrides) -> dict:
    defaults = {"expected_case_version": expected_case_version}
    defaults.update(overrides)
    return defaults


def amend_death_certificate_payload(cause_of_death="cause", manner_of_death="NATURAL", **overrides) -> dict:
    defaults = {"cause_of_death": cause_of_death, "manner_of_death": manner_of_death}
    defaults.update(overrides)
    return defaults


def create_next_of_kin_payload(full_name="Kin", relationship="CHILD", **overrides) -> dict:
    defaults = {"full_name": full_name, "relationship": relationship}
    defaults.update(overrides)
    return defaults


def create_property_item_payload(description="item", valuation_cents=0, **overrides) -> dict:
    defaults = {"description": description, "valuation_cents": valuation_cents}
    defaults.update(overrides)
    return defaults


def create_property_release_payload(next_of_kin_id, **overrides) -> dict:
    defaults = {"next_of_kin_id": next_of_kin_id}
    defaults.update(overrides)
    return defaults


def create_indigent_disposition_payload(statutory_allowance_cents=0, itemized_cost_cents=0, **overrides) -> dict:
    defaults = {
        "statutory_allowance_cents": statutory_allowance_cents,
        "itemized_cost_cents": itemized_cost_cents,
    }
    defaults.update(overrides)
    return defaults
