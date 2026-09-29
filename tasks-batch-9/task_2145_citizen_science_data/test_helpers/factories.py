"""Payload factories - one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS, THRESHOLDS

_seq = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_seq):04d}"


def create_protocol_payload(**overrides) -> dict:
    payload = {
        "code": TEST_DEFAULTS["PROTOCOL_CODE"],
        "title": TEST_DEFAULTS["PROTOCOL_TITLE"],
        "required_certification_level": "BASIC",
        "min_photo_count": TEST_DEFAULTS["MIN_PHOTO_COUNT"],
        "max_submission_lag_hours": TEST_DEFAULTS["MAX_SUBMISSION_LAG_HOURS"],
        "required_equipment_type": "NONE",
        "certification_valid_days": THRESHOLDS["DEFAULT_CERTIFICATION_VALID_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_volunteer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Vera Finch",
        "email": "vera@example.org",
        "home_region_code": "NE-01",
    }
    payload.update(overrides)
    return payload


def create_expert_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada Verifier",
        "specialty_taxon": "AVES",
        "verification_weight": TEST_DEFAULTS["VERIFIER_WEIGHT"],
    }
    payload.update(overrides)
    return payload


def create_certification_payload(volunteer_id, protocol_id, trainer_expert_id,
                                 level="ADVANCED", **overrides) -> dict:
    payload = {
        "volunteer_id": volunteer_id,
        "protocol_id": protocol_id,
        "trainer_expert_id": trainer_expert_id,
        "level": level,
    }
    payload.update(overrides)
    return payload


def complete_training_payload(exam_score=TEST_DEFAULTS["EXAM_SCORE"], **overrides) -> dict:
    payload = {"exam_score": exam_score}
    payload.update(overrides)
    return payload


def create_campaign_payload(protocol_id, **overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["CAMPAIGN_NAME"],
        "protocol_id": protocol_id,
        "season_start_date": TEST_DEFAULTS["SEASON_START"],
        "season_end_date": TEST_DEFAULTS["SEASON_END"],
        "target_observations_per_site": TEST_DEFAULTS["TARGET_PER_SITE"],
    }
    payload.update(overrides)
    return payload


def create_site_payload(**overrides) -> dict:
    payload = {
        "site_code": TEST_DEFAULTS["SITE_CODE"],
        "latitude": TEST_DEFAULTS["SITE_LAT"],
        "longitude": TEST_DEFAULTS["SITE_LON"],
        "habitat_type": "WETLAND",
        "priority_weight": TEST_DEFAULTS["SITE_PRIORITY_WEIGHT"],
    }
    payload.update(overrides)
    return payload


def create_observation_payload(campaign_id, site_id, volunteer_id, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "site_id": site_id,
        "volunteer_id": volunteer_id,
        "observed_at": "2026-08-05T06:00:00Z",
        "latitude": TEST_DEFAULTS["SITE_LAT"],
        "longitude": TEST_DEFAULTS["SITE_LON"],
        "species_code": TEST_DEFAULTS["SPECIES_CODE"],
        "count_value": 3,
    }
    payload.update(overrides)
    return payload


def create_photo_payload(file_hash="ph-1", captured_at="2026-08-05T06:05:00Z",
                         exif_latitude=TEST_DEFAULTS["SITE_LAT"],
                         exif_longitude=TEST_DEFAULTS["SITE_LON"], **overrides) -> dict:
    payload = {
        "file_hash": file_hash,
        "captured_at": captured_at,
        "exif_latitude": exif_latitude,
        "exif_longitude": exif_longitude,
    }
    payload.update(overrides)
    return payload


def cast_vote_payload(decision, confidence, expected_observation_version, **overrides) -> dict:
    payload = {
        "decision": decision,
        "confidence": confidence,
        "expected_observation_version": expected_observation_version,
    }
    payload.update(overrides)
    return payload


def create_equipment_payload(**overrides) -> dict:
    payload = {
        "asset_tag": "EQ-001",
        "equipment_type": "GPS_LOGGER",
        "calibration_valid_until": TEST_DEFAULTS["FAR_FUTURE_CALIBRATION"],
    }
    payload.update(overrides)
    return payload


def create_loan_payload(equipment_id, volunteer_id, expected_equipment_version,
                        start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-20T00:00:00Z", **overrides) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "volunteer_id": volunteer_id,
        "start_at": start_at,
        "due_at": due_at,
        "expected_equipment_version": expected_equipment_version,
    }
    payload.update(overrides)
    return payload


def return_loan_payload(condition_on_return="GOOD", **overrides) -> dict:
    payload = {"condition_on_return": condition_on_return}
    payload.update(overrides)
    return payload


def create_publication_payload(campaign_id, expected_campaign_version,
                               doi="10.5555/cs-2026-01", **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "doi": doi,
        "expected_campaign_version": expected_campaign_version,
    }
    payload.update(overrides)
    return payload


def create_partner_payload(**overrides) -> dict:
    payload = {
        "org_name": "Boreal Institute",
        "contact_email": "data@boreal.example",
        "trust_tier": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_access_grant_payload(publication_id, partner_id, scope="AGGREGATE",
                                expires_at="2027-01-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "publication_id": publication_id,
        "partner_id": partner_id,
        "scope": scope,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def reason_payload(reason="administrative action", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload
