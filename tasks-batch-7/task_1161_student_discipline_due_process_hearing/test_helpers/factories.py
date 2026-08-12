"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "STUDENT_FULL_NAME": "Stu Test",
    "STUDENT_DOB": "2010-05-01T00:00:00Z",
    "STUDENT_GRADE": 9,
    "STUDENT_GROUP": "WHITE",
    "STUDENT_GUARDIAN": "g1",
    "OFFENSE_CODE": "DISR-01",
    "OFFENSE_TITLE": "Disruption",
    "OFFENSE_CATEGORY": "DISRUPTION",
    "OFFENSE_SEVERITY": 2,
    "CASE_DESCRIPTION": "incident report",
    "INCIDENT_DATE": "2026-05-04T08:00:00Z",
    "SANCTION_DAYS": 2,
    "SANCTION_TYPE": "OUT_OF_SCHOOL",
    "DELIVERY_METHOD": "EMAIL",
    "APPEAL_GROUNDS": "appeal grounds",
    "HEARING_OFFICER": "ho_1",
    "EVIDENCE_TYPE": "DOCUMENT",
    "EVIDENCE_DESCRIPTION": "incident report",
    "SITE_NAME": "Site A",
    "SITE_CAPACITY": 5,
}


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STUDENT_FULL_NAME"],
        "date_of_birth": DEFAULTS["STUDENT_DOB"],
        "grade_level": DEFAULTS["STUDENT_GRADE"],
        "demographic_group": DEFAULTS["STUDENT_GROUP"],
        "guardian_id": DEFAULTS["STUDENT_GUARDIAN"],
    }
    defaults.update(overrides)
    return defaults


def create_offense_code_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["OFFENSE_CODE"],
        "title": DEFAULTS["OFFENSE_TITLE"],
        "category": DEFAULTS["OFFENSE_CATEGORY"],
        "severity_level": DEFAULTS["OFFENSE_SEVERITY"],
        "expellable": False,
    }
    defaults.update(overrides)
    return defaults


def create_sanction_band_payload(occurrence_index=1, min_days=1, max_days=3, **overrides) -> dict:
    defaults = {
        "occurrence_index": occurrence_index,
        "min_days": min_days,
        "max_days": max_days,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(student_id, incident_date=None, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "incident_date": incident_date or DEFAULTS["INCIDENT_DATE"],
        "description": DEFAULTS["CASE_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_classify_payload(offense_code_id, expected_case_version, **overrides) -> dict:
    defaults = {
        "offense_code_id": offense_code_id,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_sanction_payload(sanction_days, expected_case_version, **overrides) -> dict:
    defaults = {
        "sanction_days": sanction_days,
        "sanction_type": DEFAULTS["SANCTION_TYPE"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(delivery_method=None, **overrides) -> dict:
    defaults = {"delivery_method": delivery_method or DEFAULTS["DELIVERY_METHOD"]}
    defaults.update(overrides)
    return defaults


def create_conference_payload(scheduled_at, **overrides) -> dict:
    defaults = {"scheduled_at": scheduled_at}
    defaults.update(overrides)
    return defaults


def create_conference_outcome_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_appeal_payload(grounds=None, **overrides) -> dict:
    defaults = {"grounds": grounds or DEFAULTS["APPEAL_GROUNDS"]}
    defaults.update(overrides)
    return defaults


def create_appeal_decision_payload(outcome, rationale=None, **overrides) -> dict:
    defaults = {"outcome": outcome}
    if rationale is not None:
        defaults["rationale"] = rationale
    defaults.update(overrides)
    return defaults


def create_hearing_payload(case_id, hearing_officer_id=None, scheduled_start=None,
                           scheduled_end=None, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "hearing_officer_id": hearing_officer_id or DEFAULTS["HEARING_OFFICER"],
        "scheduled_start": scheduled_start or "2026-05-08T10:00:00Z",
        "scheduled_end": scheduled_end or "2026-05-08T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(item_type=None, description=None, **overrides) -> dict:
    defaults = {
        "item_type": item_type or DEFAULTS["EVIDENCE_TYPE"],
        "description": description or DEFAULTS["EVIDENCE_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_ruling_payload(ruling, **overrides) -> dict:
    defaults = {"ruling": ruling}
    defaults.update(overrides)
    return defaults


def create_hearing_decision_payload(outcome, rationale=None, **overrides) -> dict:
    defaults = {"outcome": outcome}
    if rationale is not None:
        defaults["rationale"] = rationale
    defaults.update(overrides)
    return defaults


def create_mdr_schedule_payload(meeting_at, **overrides) -> dict:
    defaults = {"meeting_at": meeting_at}
    defaults.update(overrides)
    return defaults


def create_mdr_complete_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_alt_ed_site_payload(name=None, capacity=None, **overrides) -> dict:
    defaults = {
        "name": name or DEFAULTS["SITE_NAME"],
        "capacity": capacity if capacity is not None else DEFAULTS["SITE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(case_id, site_id, start_date="2026-05-11T00:00:00Z",
                             planned_end_date="2026-05-29T00:00:00Z", **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "site_id": site_id,
        "start_date": start_date,
        "planned_end_date": planned_end_date,
    }
    defaults.update(overrides)
    return defaults


def create_placement_outcome_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_re_entry_plan_payload(conditions=None, conference_date="2026-05-26T00:00:00Z",
                                 **overrides) -> dict:
    defaults = {
        "conditions": conditions if conditions is not None else ["attend orientation"],
        "conference_date": conference_date,
    }
    defaults.update(overrides)
    return defaults


def create_re_entry_outcome_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_expungement_request_payload(student_id, **overrides) -> dict:
    defaults = {"student_id": student_id}
    defaults.update(overrides)
    return defaults


def create_expungement_decision_payload(outcome, rationale=None, **overrides) -> dict:
    defaults = {"outcome": outcome}
    if rationale is not None:
        defaults["rationale"] = rationale
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
