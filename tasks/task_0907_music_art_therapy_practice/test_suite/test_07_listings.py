"""Filtered list endpoints (reverse-reachability by foreign key).

Queue B (corner): endpoints.
"""
from test_helpers import validate_paginated, TEST_USERS
from test_helpers import fixtures as fx


def test_list_referrals_by_client_id(api):
    """PRD §2.3: "List endpoints also accept the filter query parameters named in
    their endpoint definitions (for example `client_id`, `session_id`, `status`),
    which narrow the result set by exact match before pagination is applied."

    Design: Corner/endpoints/list_referrals_by_client_id
    """
    client = fx.new_self_pay_client(api)
    ref = fx.new_referral(api, client["id"])
    resp = api.list_referrals(TEST_USERS["intake_headers"], params={"client_id": client["id"]})
    data, _ = validate_paginated(resp)
    match = [r for r in data if r["id"] == ref["id"]]
    assert match and match[0]["client_id"] == client["id"]


def test_list_sessions_by_therapist_id(api):
    """PRD §2.3: "List endpoints also accept the filter query parameters named in
    their endpoint definitions (for example `client_id`, `session_id`, `status`),
    which narrow the result set by exact match before pagination is applied."

    Design: Corner/endpoints/list_sessions_by_therapist_id
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"])
    resp = api.list_sessions(TEST_USERS["intake_headers"], params={"therapist_id": ctx["ther_id"]})
    data, _ = validate_paginated(resp)
    match = [s for s in data if s["id"] == session["id"]]
    assert match and match[0]["therapist_id"] == ctx["ther_id"]


def test_list_goals_by_plan_id(api):
    """PRD §2.3: "List endpoints also accept the filter query parameters named in
    their endpoint definitions (for example `client_id`, `session_id`, `status`),
    which narrow the result set by exact match before pagination is applied."
    PRD §3.3: "Goals may be listed under their plan."

    Design: Corner/endpoints/list_goals_by_plan_id
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    resp = api.list_goals(ctx["plan_id"], TEST_USERS["clinical_headers"])
    data, _ = validate_paginated(resp)
    match = [g for g in data if g["id"] == ctx["goal_id"]]
    assert match and match[0]["plan_id"] == ctx["plan_id"]


def test_list_enrollments_by_client_id(api):
    """PRD §2.3: "List endpoints also accept the filter query parameters named in
    their endpoint definitions (for example `client_id`, `session_id`, `status`),
    which narrow the result set by exact match before pagination is applied."

    Design: Corner/endpoints/list_enrollments_by_client_id
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"])
    enrollment = fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    resp = api.list_enrollments(TEST_USERS["intake_headers"], params={"client_id": ctx["client_id"]})
    data, _ = validate_paginated(resp)
    match = [e for e in data if e["id"] == enrollment["id"]]
    assert match and match[0]["client_id"] == ctx["client_id"]


def test_list_progress_notes_by_enrollment(api):
    """PRD §2.3: "List endpoints also accept the filter query parameters named in
    their endpoint definitions (for example `client_id`, `session_id`, `status`),
    which narrow the result set by exact match before pagination is applied."
    PRD §3.7: "Notes may be listed under their enrollment or created there".

    Design: Corner/endpoints/list_progress_notes_by_enrollment
    """
    ctx = fx.setup_completed_session(api, payer="SELF_PAY")
    note = fx.get_success_data(api.create_progress_note(
        ctx["enrollment_id"], {"narrative": "n", "rubric_score": 55, "outcome_rating": "MAINTAINED"},
        ctx["ther_headers"]))
    resp = api.list_progress_notes(ctx["enrollment_id"], ctx["ther_headers"])
    data, _ = validate_paginated(resp)
    match = [n for n in data if n["id"] == note["id"]]
    assert match and match[0]["enrollment_id"] == ctx["enrollment_id"]


def test_list_superbills_by_session_id(api):
    """PRD §2.3: "List endpoints also accept the filter query parameters named in
    their endpoint definitions (for example `client_id`, `session_id`, `status`),
    which narrow the result set by exact match before pagination is applied."
    PRD §3.8: "Superbills can be fetched individually and listed with filters on
    `client_id`, `session_id`, and `status`."

    Design: Corner/endpoints/list_superbills_by_session_id
    """
    ctx = fx.setup_billed_session(api, visits_authorized=3)
    resp = api.list_superbills(TEST_USERS["billing_headers"], params={"session_id": ctx["session_id"]})
    data, _ = validate_paginated(resp)
    match = [s for s in data if s["id"] == ctx["superbill_id"]]
    assert match and match[0]["session_id"] == ctx["session_id"]
    assert match[0]["client_id"] == ctx["client_id"]
