"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PROGRAM": "MEDICARE",
    "RESOLUTION_HOURS": 720,
    "EXTENSION_HOURS": 0,
    "EFFECTUATION_HOURS": 72,
}

# The full seven-element content set whose weights sum to exactly 1.00 (PRD §3.5).
ALL_DECISION_ELEMENTS = [
    "citation_of_criteria",
    "appeal_rights",
    "decision_rationale",
    "expedited_availability",
    "ire_notice",
    "contact_information",
    "language_assistance",
]

# The full set minus appeal_rights (weight 0.25) — yields completeness 0.75.
DECISION_ELEMENTS_MINUS_APPEAL_RIGHTS = [
    "citation_of_criteria",
    "decision_rationale",
    "expedited_availability",
    "ire_notice",
    "contact_information",
    "language_assistance",
]

# The full set minus language_assistance (weight 0.05) — incomplete.
DECISION_ELEMENTS_MINUS_LANGUAGE = [
    "citation_of_criteria",
    "appeal_rights",
    "decision_rationale",
    "expedited_availability",
    "ire_notice",
    "contact_information",
]


def create_member_payload(**overrides) -> dict:
    defaults = {
        "member_ref": "MBR-0001",
        "full_name": "Test Member",
        "program": DEFAULTS["PROGRAM"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "npi": "1234567890",
        "legal_name": "Test Provider",
        "contract_status": "CONTRACTED",
        "w9_on_file": True,
    }
    defaults.update(overrides)
    return defaults


def create_deadline_policy_payload(**overrides) -> dict:
    defaults = {
        "program": DEFAULTS["PROGRAM"],
        "case_kind": "GRIEVANCE",
        "priority_track": "STANDARD",
        "resolution_hours": DEFAULTS["RESOLUTION_HOURS"],
        "extension_hours": DEFAULTS["EXTENSION_HOURS"],
        "effectuation_hours": DEFAULTS["EFFECTUATION_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "case_kind": "GRIEVANCE",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_notification_payload(**overrides) -> dict:
    defaults = {
        "recipient_kind": "MEMBER",
        "notification_kind": "DECISION",
        "supplied_elements": list(ALL_DECISION_ELEMENTS),
    }
    defaults.update(overrides)
    return defaults


def create_clinical_factors_payload(**overrides) -> dict:
    defaults = {
        "severity": 5,
        "acuity": 5,
        "guideline_match": 5,
        "comorbidity": 5,
        "functional_impairment": 5,
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {"decision_outcome": "UNFAVORABLE"}
    defaults.update(overrides)
    return defaults


def create_reopening_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "request_reason": "NEW_EVIDENCE",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}
