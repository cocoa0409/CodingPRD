"""Payload factories — one per creatable entity, input fields only.

Codes and student numbers are suffixed with a process-wide counter so every
created row is unique even when a single test builds several worlds.
"""
import itertools

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def program_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "code": f"BS-{n:05d}",
        "name": f"Program {n}",
        "required_credits": 120,
    }
    defaults.update(overrides)
    return defaults


def term_payload(seq: int, start_date: str, end_date: str, **overrides) -> dict:
    defaults = {
        "code": f"T{seq}-{_next():05d}",
        "seq": seq,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


def student_payload(program_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "student_number": f"S-{n:05d}",
        "full_name": f"Student {n}",
        "program_id": program_id,
    }
    defaults.update(overrides)
    return defaults


def enrollment_payload(student_id: str, term_id: str, attempted_credits: int,
                       **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "term_id": term_id,
        "attempted_credits": attempted_credits,
    }
    defaults.update(overrides)
    return defaults


def post_grades_payload(earned_credits: int, quality_points: float, gpa_hours: int,
                        **overrides) -> dict:
    defaults = {
        "earned_credits": earned_credits,
        "quality_points": quality_points,
        "gpa_hours": gpa_hours,
    }
    defaults.update(overrides)
    return defaults


def amend_payload(earned_credits: int, quality_points: float, gpa_hours: int,
                  amendment_reason: str = "Grade correction", **overrides) -> dict:
    defaults = {
        "earned_credits": earned_credits,
        "quality_points": quality_points,
        "gpa_hours": gpa_hours,
        "amendment_reason": amendment_reason,
    }
    defaults.update(overrides)
    return defaults


def document_payload(doc_type: str = "NOTE", description: str = "Supporting note") -> dict:
    return {"doc_type": doc_type, "description": description}


def appeal_payload(sap_evaluation_id: str, expected_student_version: int,
                   **overrides) -> dict:
    defaults = {
        "sap_evaluation_id": sap_evaluation_id,
        "reason_category": "MEDICAL",
        "statement": "Mitigating circumstances statement",
        "documents": [document_payload()],
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


def decide_payload(decision: str, rationale: str = "Committee rationale",
                   **overrides) -> dict:
    defaults = {"decision": decision, "rationale": rationale}
    defaults.update(overrides)
    return defaults


def checkpoint_payload(term_id: str, required_earned_credits: int,
                       required_term_gpa: float = 2.0,
                       required_term_pace_pct: float = 67.0,
                       **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "required_term_gpa": required_term_gpa,
        "required_term_pace_pct": required_term_pace_pct,
        "required_earned_credits": required_earned_credits,
    }
    defaults.update(overrides)
    return defaults


def plan_payload(student_id: str, appeal_id: str, start_term_id: str,
                 total_required_credits: int, checkpoints: list,
                 **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "appeal_id": appeal_id,
        "start_term_id": start_term_id,
        "total_required_credits": total_required_credits,
        "checkpoints": checkpoints,
    }
    defaults.update(overrides)
    return defaults
