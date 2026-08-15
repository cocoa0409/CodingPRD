"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import (
    GRANT_VALID_FROM,
    GRANT_VALID_UNTIL,
    INTENDED_ADMIN_DATE,
    MAX_SCORE_POINTS,
    SESSION_SCHEDULED_AT,
    TARGET_SAMPLE_SIZE,
    WINDOW_END,
    WINDOW_START,
)

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_code": _uniq("PROG"),
        "subject": "MATH",
        "grade_level": 8,
        "admin_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_standard_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "standard_code": _uniq("CS"),
        "strand": "S",
        "description": "Standard description text",
        "depth_of_knowledge": 2,
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(program_id, primary_standard_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "item_code": _uniq("IT"),
        "primary_standard_id": primary_standard_id,
        "item_type": "MC",
        "stimulus_html": "<p>Stem</p>",
        "options_json": {"choices": ["A", "B"], "correct_keys": ["A"]},
        "max_score_points": MAX_SCORE_POINTS,
    }
    defaults.update(overrides)
    return defaults


def create_committee_payload(program_id, committee_kind="CONTENT", **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "committee_kind": committee_kind,
        "name": _uniq("Committee"),
        "quorum_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(committee_id, agenda_item_ids, **overrides) -> dict:
    defaults = {
        "committee_id": committee_id,
        "scheduled_at": SESSION_SCHEDULED_AT,
        "agenda_item_ids": list(agenda_item_ids),
    }
    defaults.update(overrides)
    return defaults


def create_verdict_payload(item_id, verdict="ACCEPT", **overrides) -> dict:
    defaults = {"item_id": item_id, "verdict": verdict}
    defaults.update(overrides)
    return defaults


def create_window_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "window_label": _uniq("FT"),
        "start_utc": WINDOW_START,
        "end_utc": WINDOW_END,
        "target_sample_size": TARGET_SAMPLE_SIZE,
    }
    defaults.update(overrides)
    return defaults


def create_response_payload(item_id, student_anon_id, raw_score, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "student_anon_id": student_anon_id,
        "response_timestamp": "2026-08-06T12:00:00Z",
        "attempt_duration_seconds": 60,
        "raw_score": raw_score,
    }
    defaults.update(overrides)
    return defaults


def create_blueprint_payload(program_id, item_count=1, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "blueprint_code": _uniq("BP"),
        "sections": [{"strand": "S", "item_count": item_count,
                      "dok_min": 1, "dok_max": 100}],
    }
    defaults.update(overrides)
    return defaults


def create_form_payload(blueprint_id, **overrides) -> dict:
    defaults = {
        "blueprint_id": blueprint_id,
        "form_code": _uniq("F"),
        "intended_admin_date": INTENDED_ADMIN_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(item_id, section_index=0, position_in_section=1,
                        is_anchor=False) -> dict:
    return {
        "item_id": item_id,
        "section_index": section_index,
        "position_in_section": position_in_section,
        "is_anchor": is_anchor,
    }


def create_equating_link_payload(program_id, source_form_id, target_form_id,
                                 anchor_item_ids) -> dict:
    return {
        "program_id": program_id,
        "source_form_id": source_form_id,
        "target_form_id": target_form_id,
        "anchor_item_ids": list(anchor_item_ids),
    }


def create_variant_payload(item_id, variant_kind="TRANSLATION", **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "variant_kind": variant_kind,
        "stimulus_html": "<p>Variant stem</p>",
        "options_json": {"choices": ["A", "B"], "correct_keys": ["A"]},
    }
    if variant_kind == "TRANSLATION":
        defaults["language_code"] = "es"
    else:
        defaults["accommodation_code"] = "LARGE_PRINT"
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(program_id, grantee_user_id, grant_scope,
                                **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "grantee_user_id": grantee_user_id,
        "grant_scope": grant_scope,
        "valid_from": GRANT_VALID_FROM,
        "valid_until": GRANT_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


DOSSIER_BODY = (
    "This technical manual documents the design, development, and psychometric "
    "evidence supporting the administration of the form. It describes the item "
    "development workflow, the review and field-test procedures, the statistical "
    "analysis methods, and the equating design used to place scores on a common "
    "reporting scale for the administration year."
)


def create_dossier_payload(program_id, form_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "form_id": form_id,
        "dossier_kind": "TECHNICAL_MANUAL",
        "content_md": DOSSIER_BODY,
    }
    defaults.update(overrides)
    return defaults
