"""Inspection scheduling/completion and violation lifecycle.

Covers difficulty instances (violation reopen cycle, inspector half-open overlap,
existence-beats-temporal precedence) and corner instances (invalid window, cure of
already-cured, escalate before deadline, inspection reverse lookup).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_registrant, create_property, create_standard, create_inspection,
    complete_inspection, transition_violation, violations_for_inspection,
    setup_open_violation, set_clock, NON_EXISTENT_UUID,
)

OFFICER = TEST_USERS["code_officer_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


# --- Corner: invalid window ------------------------------------------------
def test_inspection_end_before_start_returns_invalid_window(api):
    """PRD §3.3: "The window must be well-formed with `scheduled_end` strictly
    after `scheduled_start`; otherwise the request is rejected with
    `ERR_INVALID_WINDOW`."

    Design: Corner/validations/inspection_end_before_start_returns_invalid_window
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    payload = {
        "property_id": prop["id"], "inspector_badge": "C2",
        "scheduled_start": "2026-03-02T11:00:00Z",
        "scheduled_end": "2026-03-02T09:00:00Z",
    }
    resp = api.create_inspection(payload, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# --- Corner: cure of already-cured violation -------------------------------
def test_cure_already_cured_violation_returns_invalid_state(api):
    """PRD §3.4: "Curing marks the standard corrected: it is allowed from either
    `OPEN` or `ESCALATED`, sets the violation's status to `CURED`". An attempt to
    cure a `CURED` violation is not an allowed source state.
    PRD §3.4: "An escalation attempted while the violation is not `OPEN` is
    rejected as an invalid state (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/cure_already_cured_violation_returns_invalid_state
    """
    ctx = setup_open_violation(api, cure_period_days=10)
    transition_violation(api, ctx["violation"]["id"], "CURE")
    resp = api.transition_violation(ctx["violation"]["id"], {"action": "CURE"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner: escalate before cure deadline ---------------------------------
def test_escalate_before_cure_deadline_returns_error(api):
    """PRD §3.4: "an escalation of an `OPEN` violation attempted before its
    `cure_deadline_at` is reached is rejected with `ERR_CURE_PERIOD_ACTIVE`".

    Design: Corner/validations/escalate_before_cure_deadline_returns_error
    """
    ctx = setup_open_violation(api, cure_period_days=10)
    # Clock is still at the default 2026-03-01; cure_deadline_at is 2026-03-11.
    resp = api.transition_violation(ctx["violation"]["id"], {"action": "ESCALATE"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE.value)


# --- Corner: inspection reverse lookup -------------------------------------
def test_inspections_reverse_lookup_by_property(api):
    """PRD §3.3: "Inspections may be fetched individually and listed with reverse
    lookup by `property_id`, by `inspector_badge`, and by `status`."

    Design: Corner/endpoints/inspections_reverse_lookup_by_property
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    inspection = create_inspection(api, prop["id"], inspector_badge="C7")
    data = validate_success(
        api.list_inspections(ADMIN, params={"property_id": prop["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == inspection["id"]


# --- Difficulty 8a: inspector half-open overlap ----------------------------
def _property_with_inspection(api, badge, start, end):
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    create_inspection(api, prop["id"], inspector_badge=badge,
                      scheduled_start=start, scheduled_end=end)
    return prop


def test_inspector_overlapping_window_rejected(api):
    """PRD §3.3: "if any other `SCHEDULED` inspection bearing the same
    `inspector_badge` has a window that overlaps the new one, the request is
    rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/inspector_halfopen_overlap
    """
    prop = _property_with_inspection(api, "B15", "2026-03-02T09:00:00Z",
                                     "2026-03-02T11:00:00Z")
    payload = {
        "property_id": prop["id"], "inspector_badge": "B15",
        "scheduled_start": "2026-03-02T10:00:00Z",
        "scheduled_end": "2026-03-02T12:00:00Z",
    }
    resp = api.create_inspection(payload, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED.value)


def test_inspector_adjacent_window_allowed(api):
    """PRD §3.3: "Overlap is measured on the half-open interval — the window runs
    from `scheduled_start` up to but not including `scheduled_end` — so two windows
    that merely touch, where one ends exactly when the other begins, are permitted."

    Design: Difficulty/resource_temporal_overlap/inspector_halfopen_overlap
    """
    prop = _property_with_inspection(api, "B15", "2026-03-02T09:00:00Z",
                                     "2026-03-02T11:00:00Z")
    payload = {
        "property_id": prop["id"], "inspector_badge": "B15",
        "scheduled_start": "2026-03-02T11:00:00Z",
        "scheduled_end": "2026-03-02T13:00:00Z",
    }
    data = validate_success(api.create_inspection(payload, OFFICER), expected_status=201)
    assert data["status"] == "SCHEDULED"


# --- Difficulty 5b: existence beats temporal -------------------------------
def test_missing_property_beats_double_booking(api):
    """PRD §2.10: "(4) existence of body foreign keys — ... the `property_id` on
    inspection, abatement-order, receivership-referral, and demolition-listing
    creation resolving to a real property (`ERR_PROPERTY_NOT_FOUND`) ... Only once
    all five of these pass does the system evaluate the domain-specific business
    rules".

    Design: Difficulty/priority_pair_validation_conflict/schedule_inspection_existence_beats_temporal
    """
    # An existing SCHEDULED inspection for badge B11 that WOULD overlap.
    _property_with_inspection(api, "B11", "2026-03-02T09:00:00Z",
                              "2026-03-02T11:00:00Z")
    payload = {
        "property_id": NON_EXISTENT_UUID, "inspector_badge": "B11",
        "scheduled_start": "2026-03-02T10:00:00Z",
        "scheduled_end": "2026-03-02T12:00:00Z",
    }
    resp = api.create_inspection(payload, OFFICER)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


def test_missing_property_fk_checked_before_business_rules(api):
    """PRD §2.10: "(4) existence of body foreign keys — ... the `property_id` on
    inspection ... creation resolving to a real property (`ERR_PROPERTY_NOT_FOUND`)
    ... Only once all five of these pass does the system evaluate the
    domain-specific business rules".

    Design: Difficulty/priority_pair_validation_conflict/schedule_inspection_existence_beats_temporal
    """
    # No conflicting inspection at all; the property FK still fails first.
    payload = {
        "property_id": NON_EXISTENT_UUID, "inspector_badge": "B11-fresh",
        "scheduled_start": "2026-03-02T09:00:00Z",
        "scheduled_end": "2026-03-02T11:00:00Z",
    }
    resp = api.create_inspection(payload, OFFICER)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


# --- Difficulty 3b: violation cured -> reopen cycle ------------------------
def _reopened_violation(api):
    """Cite a violation (cure 10), cure it, then re-cite the same code with a
    later failing inspection, reopening the CURED violation. Returns the refetched
    violation."""
    ctx = setup_open_violation(api, cure_period_days=10)
    transition_violation(api, ctx["violation"]["id"], "CURE")
    set_clock(api, "2026-03-15T00:00:00Z")
    insp2 = create_inspection(api, ctx["property"]["id"], inspector_badge="B7b",
                              scheduled_start="2026-03-15T09:00:00Z",
                              scheduled_end="2026-03-15T11:00:00Z")
    complete_inspection(api, insp2["id"], "FAIL", [ctx["standard"]["code"]])
    return validate_success(api.get_violation(ctx["violation"]["id"], OFFICER))


def test_cured_violation_reopens_to_open_on_recitation(api):
    """PRD §3.4: "When a later failing inspection re-cites a standard code for
    which the property already holds a `CURED` violation, the system does not
    create a duplicate; instead it reopens that existing violation. Reopening sets
    its status back to `OPEN`, clears `cured_at`, and re-stamps `cited_at` to the
    current clock".

    Design: Difficulty/non_linear_state_machine/violation_cured_reopen_cycle
    """
    violation = _reopened_violation(api)
    assert violation["status"] == "OPEN"


def test_reopened_violation_clears_cured_at(api):
    """PRD §3.4: "Reopening sets its status back to `OPEN`, clears `cured_at`, and
    re-stamps `cited_at` to the current clock, then recomputes `cure_deadline_at`
    from that fresh citation instant and the standard's cure period."

    Design: Difficulty/non_linear_state_machine/violation_cured_reopen_cycle
    """
    violation = _reopened_violation(api)
    assert violation["cured_at"] is None
