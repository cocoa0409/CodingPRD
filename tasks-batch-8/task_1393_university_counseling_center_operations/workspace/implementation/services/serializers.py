"""Serializers: strip internal fields (underscore-prefixed) before output.

Also handles the Registrar academic view of Student per PRD §2.6: when a
Registrar reads a student, counseling-derived fields (risk band, episode
status, session counts, strike counts) MUST NOT appear.
"""

from __future__ import annotations


def serialize(entity: dict) -> dict:
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items: list) -> list:
    return [serialize(it) for it in items]


# Fields hidden from the Registrar academic view (counseling-derived).
_REGISTRAR_HIDDEN = {
    "no_show_strike_count",
    "strike_reset_anchor",
    "booking_posture",
}


def serialize_student_for_role(student: dict, role: str) -> dict:
    base = serialize(student)
    if role == "Registrar":
        return {k: v for k, v in base.items() if k not in _REGISTRAR_HIDDEN}
    return base


def serialize_students_for_role(students: list, role: str) -> list:
    return [serialize_student_for_role(s, role) for s in students]
