"""Tutoring referrals and FK reverse-reachability listing (corner: endpoints)."""
from test_helpers import (
    validate_success, validate_paginated, get_success_data, TEST_USERS,
    create_district, create_student, create_liaison, make_student_eligible,
)

SC = TEST_USERS["state_coordinator_headers"]
LIAISON = TEST_USERS["liaison_headers"]


def test_tutoring_referral_create_and_close(api):
    """PRD §3.8: "A `Liaison` or `StateCoordinator` opens one for a `student_id` in a
    `subject` (`MATH`, `READING`, or `OTHER`); it starts `OPEN`. From `OPEN` it may
    be closed to the terminal `CLOSED` or canceled to the terminal `CANCELED`".

    Design: Corner/endpoints/tutoring_referral_create_and_close
    """
    d = create_district()
    s = create_student(d["id"])
    ref = validate_success(api.create_referral({"student_id": s["id"], "subject": "MATH"}, LIAISON), 201)
    assert ref["status"] == "OPEN"
    closed = validate_success(api.close_referral(ref["id"], LIAISON))
    assert closed["status"] == "CLOSED"


def test_list_students_by_liaison_reverse_reachability(api):
    """PRD §3.1: "writes the student's `liaison_id` and recomputes the liaison's `current_caseload`."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object."

    Design: Corner/endpoints/fk_reverse_list_students_by_liaison
    """
    d = create_district()
    lia = create_liaison(d["id"], max_caseload=25)
    s = create_student(d["id"])
    make_student_eligible(s["id"], s["version"])
    get_success_data(api.assign_liaison(s["id"], {"liaison_id": lia["id"]}, SC))

    data, meta = validate_paginated(api.list_students(SC, params={"liaison_id": lia["id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == s["id"]
