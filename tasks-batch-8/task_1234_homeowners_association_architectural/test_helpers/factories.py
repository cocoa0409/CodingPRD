"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_association_payload(**overrides) -> dict:
    defaults = {
        "name": "Test HOA",
        "statutory_response_days": TEST_DEFAULTS["STATUTORY_RESPONSE_DAYS"],
        "counting_mode": TEST_DEFAULTS["COUNTING_MODE"],
        "fine_mode": TEST_DEFAULTS["FINE_MODE"],
        "base_fine_cents": TEST_DEFAULTS["BASE_FINE_CENTS"],
        "daily_fine_cents": TEST_DEFAULTS["DAILY_FINE_CENTS"],
        "lien_threshold_cents": TEST_DEFAULTS["LIEN_THRESHOLD_CENTS"],
        "committee_size": TEST_DEFAULTS["COMMITTEE_SIZE"],
        "quorum_min": TEST_DEFAULTS["QUORUM_MIN"],
        "supermajority_required": True,
        "max_window_days": TEST_DEFAULTS["MAX_WINDOW_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ann A",
        "email": "ann.a@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(primary_owner_id: str, **overrides) -> dict:
    defaults = {
        "lot_number": "L-1",
        "address": "1 Main St",
        "primary_owner_id": primary_owner_id,
    }
    defaults.update(overrides)
    return defaults


def create_blackout_payload(start_date: str, end_date: str, **overrides) -> dict:
    defaults = {
        "start_date": start_date,
        "end_date": end_date,
        "reason": "holiday moratorium",
    }
    defaults.update(overrides)
    return defaults


def create_variance_payload(application_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "guideline_section": "SEC-4.2",
        "deviation_description": "granted deviation",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "project_type": "FENCE",
        "guideline_section": "SEC-4.2",
        "description": "fence",
        "requested_window_start": TEST_DEFAULTS["WINDOW_START"],
        "requested_window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_attachment_payload(kind: str = "DRAWING", **overrides) -> dict:
    defaults = {
        "kind": kind,
        "label": "site plan" if kind == "DRAWING" else "material sample",
        "uri": f"s3://arc/{kind.lower()}-1",
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(ballot: str = "APPROVE") -> dict:
    return {"ballot": ballot}


def create_decision_payload(conditions=None, denial_reason=None) -> dict:
    payload = {}
    if conditions is not None:
        payload["conditions"] = conditions
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


def create_conditions_payload(conditions, expected_application_version: int) -> dict:
    return {
        "conditions": conditions,
        "expected_application_version": expected_application_version,
    }


def create_appeal_payload(grounds: str = "appeal grounds") -> dict:
    return {"grounds": grounds}


def create_appeal_decision_payload(outcome: str, board_note=None) -> dict:
    payload = {"outcome": outcome}
    if board_note is not None:
        payload["board_note"] = board_note
    return payload


def create_contractor_change_payload(contractor_name: str, contractor_license: str,
                                     expected_permit_version: int) -> dict:
    return {
        "contractor_name": contractor_name,
        "contractor_license": contractor_license,
        "expected_permit_version": expected_permit_version,
    }


def create_extension_payload(new_window_end: str) -> dict:
    return {"new_window_end": new_window_end}


def create_inspection_record_payload(result: str, result_notes=None) -> dict:
    payload = {"result": result}
    if result_notes is not None:
        payload["result_notes"] = result_notes
    return payload


def create_violation_payload(kind: str = "UNAPPROVED_WORK", **overrides) -> dict:
    defaults = {
        "kind": kind,
        "description": "unapproved work",
    }
    defaults.update(overrides)
    return defaults


def create_settle_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def create_waive_payload(amount_cents: int, reason: str = "goodwill") -> dict:
    return {"amount_cents": amount_cents, "reason": reason}


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
