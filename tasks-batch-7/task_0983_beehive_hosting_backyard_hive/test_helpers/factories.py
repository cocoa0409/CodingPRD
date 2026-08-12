"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS, THRESHOLDS

_counter = itertools.count(1)


def _unique_email() -> str:
    return f"host-{next(_counter)}@example.com"


def create_host_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Host", "email": _unique_email()}
    defaults.update(overrides)
    return defaults


def sign_waiver_payload(**overrides) -> dict:
    defaults = {"waiver_version": TEST_DEFAULTS["WAIVER_VERSION"]}
    defaults.update(overrides)
    return defaults


def create_site_payload(host_id: str, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "address": "1 Test Lane",
        "base_capacity_hives": THRESHOLDS["DEFAULT_BASE_CAPACITY_HIVES"],
        "water_source": True,
        "setback_feet": 10,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(host_id: str, site_id: str, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "site_id": site_id,
        "term_start_date": TEST_DEFAULTS["TERM_START"],
        "term_end_date": TEST_DEFAULTS["TERM_END"],
        "host_share_base_bps": TEST_DEFAULTS["HOST_SHARE_BASE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def propose_amendment_payload(proposed_bps: int, expected_version: int) -> dict:
    return {
        "proposed_host_share_base_bps": proposed_bps,
        "expected_agreement_version": expected_version,
    }


def create_hive_payload(site_id: str, agreement_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id, "agreement_id": agreement_id}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(hive_id: str, **overrides) -> dict:
    defaults = {
        "hive_id": hive_id,
        "inspected_at": "2026-05-10T00:00:00Z",
        "mites_counted": 0,
        "bees_sampled": 300,
        "disease_flag": False,
        "brood_score": 9,
        "queen_seen": True,
        "stores_kg": 12.0,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_payload(hive_id: str, **overrides) -> dict:
    defaults = {
        "hive_id": hive_id,
        "product": "APIVAR",
        "start_date": "2026-05-02T00:00:00Z",
        "end_date": "2026-05-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_harvest_payload(hive_id: str, **overrides) -> dict:
    defaults = {
        "hive_id": hive_id,
        "collected_on": "2026-06-15T00:00:00Z",
        "gross_kg": 5.000,
        "moisture_pct": 18.0,
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["SEASON_NAME"],
        "frost_date": TEST_DEFAULTS["SEASON_FROST"],
    }
    defaults.update(overrides)
    return defaults


def rollover_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["NEXT_SEASON_NAME"],
        "frost_date": TEST_DEFAULTS["NEXT_SEASON_FROST"],
    }
    defaults.update(overrides)
    return defaults


def create_swarm_event_payload(site_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id}
    defaults.update(overrides)
    return defaults


def create_removal_job_payload(hive_id: str, **overrides) -> dict:
    defaults = {"hive_id": hive_id, "reason": "RELOCATION"}
    defaults.update(overrides)
    return defaults


def decide_removal_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def schedule_removal_payload(scheduled_start: str, crew_id: str) -> dict:
    return {"scheduled_start": scheduled_start, "crew_id": crew_id}


def create_subscription_payload(host_id: str, plan: str, **overrides) -> dict:
    defaults = {"host_id": host_id, "plan": plan}
    defaults.update(overrides)
    return defaults


def change_plan_payload(plan: str, expected_version: int) -> dict:
    return {"plan": plan, "expected_subscription_version": expected_version}


def create_enrollment_payload(host_id: str, course_code: str) -> dict:
    return {"host_id": host_id, "course_code": course_code}


def create_incident_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "severity": "MINOR",
        "occurred_at": "2026-05-03T00:00:00Z",
        "description": "sting reported near the fence",
    }
    defaults.update(overrides)
    return defaults


def resolve_incident_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome, "liability_cents": 0}
    defaults.update(overrides)
    return defaults
