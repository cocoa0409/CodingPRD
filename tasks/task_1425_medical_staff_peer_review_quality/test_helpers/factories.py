"""Payload factories — one per writable resource, input fields only (PRD §3)."""

from .constants import DEFAULT_REFERRED_AT

DEFAULTS = {
    "PROVIDER_NAME": "Dr. Test Provider",
    "SPECIALTY": "SURGERY",
    "MEMBER_ROLE": "MEMBER",
    "REFERRAL_SOURCE": "OTHER",
    "REFERRED_AT": DEFAULT_REFERRED_AT,
    "DESCRIPTION": "Referral narrative for peer review.",
    "CONFLICT_TYPE": "PRIOR_TREATING",
    "NOTE_BODY": "Privileged committee note body.",
    "RESPONSE_TEXT": "Provider response to the committee rating.",
    "EXTERNAL_REASON": "Case requires an external review body.",
    "FOCUS_BASIS": "Pattern of concerns requiring focused review.",
    "GROUP_NAME": "focus-panel-1",
    "RESOLUTION_NOTE": "Focused review completed.",
}


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "specialty": DEFAULTS["SPECIALTY"],
    }
    defaults.update(overrides)
    return defaults


def create_committee_member_payload(**overrides) -> dict:
    defaults = {
        "provider_id": "",
        "member_role": DEFAULTS["MEMBER_ROLE"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "subject_provider_id": "",
        "referral_source": DEFAULTS["REFERRAL_SOURCE"],
        "referred_at": DEFAULTS["REFERRED_AT"],
        "description": DEFAULTS["DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def screen_case_payload(decision="SCREEN_IN", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {
        "reviewer_id": "",
        "expected_case_version": 1,
    }
    defaults.update(overrides)
    return defaults


def submit_assignment_payload(care_appropriateness_score, expected_case_version,
                              ofi_score=None, **overrides) -> dict:
    payload = {
        "care_appropriateness_score": care_appropriateness_score,
        "expected_case_version": expected_case_version,
    }
    if ofi_score is not None:
        payload["ofi_score"] = ofi_score
    payload.update(overrides)
    return payload


def revise_assignment_payload(care_appropriateness_score, ofi_score=None, **overrides) -> dict:
    payload = {"care_appropriateness_score": care_appropriateness_score}
    if ofi_score is not None:
        payload["ofi_score"] = ofi_score
    payload.update(overrides)
    return payload


def create_note_payload(**overrides) -> dict:
    defaults = {"body": DEFAULTS["NOTE_BODY"]}
    defaults.update(overrides)
    return defaults


def create_conflict_declaration_payload(**overrides) -> dict:
    defaults = {
        "provider_id": "",
        "conflict_type": DEFAULTS["CONFLICT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_response_payload(**overrides) -> dict:
    defaults = {"response_text": DEFAULTS["RESPONSE_TEXT"]}
    defaults.update(overrides)
    return defaults


def refer_external_payload(**overrides) -> dict:
    defaults = {"reason": DEFAULTS["EXTERNAL_REASON"]}
    defaults.update(overrides)
    return defaults


def create_focused_review_payload(**overrides) -> dict:
    defaults = {
        "provider_id": "",
        "basis": DEFAULTS["FOCUS_BASIS"],
    }
    defaults.update(overrides)
    return defaults


def close_focused_review_payload(**overrides) -> dict:
    defaults = {"resolution_note": DEFAULTS["RESOLUTION_NOTE"]}
    defaults.update(overrides)
    return defaults


def create_focus_group_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["GROUP_NAME"]}
    defaults.update(overrides)
    return defaults


def add_focus_group_member_payload(**overrides) -> dict:
    defaults = {"member_id": ""}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
