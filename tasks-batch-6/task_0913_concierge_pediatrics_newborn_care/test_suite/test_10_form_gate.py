"""School, camp and sports paperwork: the issuance gate and the turnaround promise."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_form_request,
    assert_instant_equals,
    complete_well_visit,
    create_form_request_payload,
    get_child,
    get_form_request,
    set_clock,
    setup_active_membership,
    validate_error,
    validate_paginated,
    validate_success,
    well_visit_for,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _newborn_household(household_name, child_first_name):
    """A May-born child on an ACTIVE membership, with zero immunization doses."""
    return setup_active_membership(
        clock="2026-06-01T00:00:00Z",
        household_name=household_name,
        child_first_name=child_first_name,
        date_of_birth="2026-05-20",
        advance_clock_to="2026-06-15T00:00:00Z",
    )


# ==========================================================================
# The empty-dose-set boundary
# ==========================================================================


def test_a_newborn_with_no_doses_is_vacuously_complete_and_the_gate_passes(api):
    """PRD §3.5: "This produces an important empty-set boundary: for a newborn every
    requirement is 0, so a child with no recorded doses at all is vacuously complete."
    PRD §3.5: "A child born 2026-05-20 read on 2026-06-15 is 26 days old, needs nothing of
    either series, and reads complete; read four days later on 2026-06-19 the same child
    is 30 days old, the first `HEPB` position has become required, and the same child now
    reads incomplete."
    PRD §3.9: "Creation evaluates that gate immediately. If every rung passes the request
    rests in `PENDING`."

    Design: Difficulty/boundary_precision_check/newborn_with_empty_dose_set_is_vacuously_complete_until_day_thirty
    """
    scenario = _newborn_household("Persson", "Vera")
    membership, child, doc = scenario["membership"], scenario["child"], scenario["physician"]

    rows, meta = validate_paginated(
        api.list_immunization_doses(ADMIN, params={"child_id": child["id"]})
    )
    assert meta["total_count"] == 0 and rows == []

    complete_well_visit(well_visit_for(membership["id"], "M1")["id"], doc["id"], "2026-06-15")

    read = get_child(child["id"])
    assert read["age_days"] == 26
    assert read["immunization_complete_for_age"] is True

    resp = api.create_form_request(
        create_form_request_payload(
            membership["id"], form_type="CAMP", needed_by_date="2026-07-31"
        ),
        COORDINATOR,
    )
    form = validate_success(resp, 201)
    assert_form_request(form)
    assert form["status"] == "PENDING"
    assert form["blocked_reason"] is None
    assert_instant_equals(form["due_at"], "2026-06-18T00:00:00.000Z", "FormRequest.due_at")


def test_on_day_thirty_the_same_empty_dose_set_blocks_the_gate(api):
    """PRD §3.5: "For each of the two vaccine series, the required dose count is the number
    of positions in that series whose minimum age plus a thirty-day lag is less than or
    equal to the child's `age_days` today — the comparison is inclusive, so a position
    becomes required on the exact day the child's age reaches that sum."
    PRD §3.9: "Rung two: the child's `immunization_complete_for_age` must be true under
    the counting rules of §3.5; otherwise the reason is `IMMUNIZATION_INCOMPLETE`."
    PRD §3.9: "If any rung fails, the request is written straight to `BLOCKED` with the
    first failing rung's reason recorded in `blocked_reason` — and the call still returns
    201 with the blocked row."

    Design: Difficulty/boundary_precision_check/newborn_with_empty_dose_set_is_vacuously_complete_until_day_thirty
    """
    scenario = _newborn_household("Persson", "Vera")
    membership, child, doc = scenario["membership"], scenario["child"], scenario["physician"]

    complete_well_visit(well_visit_for(membership["id"], "M1")["id"], doc["id"], "2026-06-15")

    set_clock("2026-06-19T00:00:00Z")

    read = get_child(child["id"])
    assert read["age_days"] == 30
    assert read["immunization_complete_for_age"] is False

    resp = api.create_form_request(
        create_form_request_payload(
            membership["id"], form_type="SCHOOL", needed_by_date="2026-07-31"
        ),
        COORDINATOR,
    )
    blocked = validate_success(resp, 201)
    assert resp.status_code == 201, "a failing gate is information, not an error"
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "IMMUNIZATION_INCOMPLETE"


# ==========================================================================
# The well-visit recency rung and the recovery loop
# ==========================================================================


def test_a_household_with_no_recent_well_visit_gets_a_blocked_request(api):
    """PRD §3.9: "Rung three: the membership must have at least one well visit in status
    `COMPLETED` whose `completed_date` falls within the last 365 days — precisely, on or
    after today minus 365 days and on or before today, **both bounds inclusive**, so a
    visit completed exactly 365 days ago still satisfies the rung while one completed 366
    days ago does not; otherwise the reason is `WELL_VISIT_STALE`."
    PRD §3.9: "The service stamps `requested_at` with the current instant and computes
    `due_at` once, as `requested_at` plus the plan's `form_sla_hours` — five days on
    `ESSENTIAL`, three on `PLUS`, one on `PREMIER` — and never recomputes it afterwards,
    so a mid-flight plan change does not move a promise already made."

    Design: Difficulty/cross_entity_state_dependency/form_issuance_gated_on_recent_completed_well_visit
    """
    scenario = _newborn_household("Tanaka", "Hana")

    resp = api.create_form_request(
        create_form_request_payload(
            scenario["membership"]["id"], form_type="SPORTS", needed_by_date="2026-08-01"
        ),
        COORDINATOR,
    )
    form = validate_success(resp, 201)

    assert resp.status_code == 201
    assert form["status"] == "BLOCKED"
    assert form["blocked_reason"] == "WELL_VISIT_STALE"
    assert_instant_equals(form["due_at"], "2026-06-18T00:00:00.000Z", "FormRequest.due_at")


def test_completing_a_well_visit_lets_recheck_and_issue_release_the_form(api):
    """PRD §3.9: "If every rung now passes, the request moves `BLOCKED → PENDING` and its
    `blocked_reason` is cleared to null, putting it back in the issuance queue."
    PRD §3.9: "If the request is in `PENDING` and the gate now passes on every rung, it
    moves `PENDING → ISSUED`, `issued_at` is stamped with the current instant, and
    `sla_met` is set to true when the `issued_at` is at or before the `due_at` and false
    when it is later — the comparison is inclusive at equality, so issuing at the exact
    due instant still counts as met."

    Design: Difficulty/cross_entity_state_dependency/form_issuance_gated_on_recent_completed_well_visit
    """
    scenario = _newborn_household("Tanaka", "Hana")
    membership, doc = scenario["membership"], scenario["physician"]

    form = validate_success(
        api.create_form_request(
            create_form_request_payload(
                membership["id"], form_type="SPORTS", needed_by_date="2026-08-01"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert form["status"] == "BLOCKED"

    m1 = well_visit_for(membership["id"], "M1")
    completed = complete_well_visit(m1["id"], doc["id"], "2026-06-15")
    assert completed["punctuality"] == "ON_SCHEDULE"
    assert completed["status"] == "COMPLETED"

    rechecked = validate_success(api.recheck_form_request(form["id"], COORDINATOR))
    assert rechecked["status"] == "PENDING"
    assert rechecked["blocked_reason"] is None

    issued = validate_success(
        api.issue_form_request(form["id"], scenario["physician_headers"])
    )
    assert issued["status"] == "ISSUED"
    assert_instant_equals(issued["issued_at"], "2026-06-15T00:00:00.000Z", "FormRequest.issued_at")
    assert issued["sla_met"] is True


def test_issuing_a_blocked_request_is_refused_outright(api):
    """PRD §3.9: "If the request is already in `BLOCKED`, issuance is refused outright with
    `ERR_FORM_GATE_NOT_MET` — a blocked request must first be recovered through a
    recheck."

    Design: Corner/errors/corner_issuing_a_blocked_form_returns_form_gate_not_met
    """
    scenario = _newborn_household("Ximenes", "Tomas")

    form = validate_success(
        api.create_form_request(
            create_form_request_payload(
                scenario["membership"]["id"], form_type="CAMP", needed_by_date="2026-08-01"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert form["status"] == "BLOCKED"
    assert form["blocked_reason"] == "WELL_VISIT_STALE"

    resp = api.issue_form_request(form["id"], scenario["physician_headers"])
    validate_error(resp, ApiErrorId.ERR_FORM_GATE_NOT_MET)
    assert resp.status_code == 409

    unchanged = get_form_request(form["id"])
    assert unchanged["status"] == "BLOCKED"
    assert unchanged["issued_at"] is None
    assert unchanged["sla_met"] is None
