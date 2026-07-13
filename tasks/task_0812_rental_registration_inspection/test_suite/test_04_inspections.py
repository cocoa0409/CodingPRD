"""Inspection scoring (provisional vs final), scheduling guardrails (double-booking,
cooldown, reinspection precedence), begin guards, and complaint resolution.
"""
import pytest
from test_helpers import (
    ApiErrorId, TEST_USERS, get_success_data,
    validate_success, validate_error,
    make_inspector_headers, make_landlord_headers,
    setup_landlord_inspector_property, schedule_inspection, begin_inspection,
    record_item, run_periodic_to_passed, run_periodic_with_fail_items,
    create_landlord, create_inspector, create_property, create_complaint,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def _in_progress_with_one_minor_life_safety_fail(api):
    """REGISTERED property + PERIODIC inspection IN_PROGRESS holding exactly one
    LIFE_SAFETY / SMOKE_DETECTOR / FAIL / MINOR item."""
    ctx = setup_landlord_inspector_property(api, unit_count=3, year_built=1980)
    insp = schedule_inspection(api, ctx["property_id"], ctx["inspector_id"],
                               "2026-06-01T09:00:00Z", inspection_type="PERIODIC")
    begin_inspection(api, insp["id"], ctx["inspector_id"])
    record_item(api, insp["id"], ctx["inspector_id"], "LIFE_SAFETY", "SMOKE_DETECTOR", "FAIL",
                severity="MINOR")
    ctx["inspection"] = insp
    return ctx


# --- Difficulty: dual_variant_calc / inspection_score_provisional_vs_final

def test_provisional_score_ignores_missing_mandatory_category(api):
    """PRD §3.3: "The severity weights are 1 for MINOR, 3 for MAJOR, and 10 for CRITICAL. The
    category multipliers are 2.0 for LIFE_SAFETY, 1.0 for HABITABILITY, 1.5 for LEAD_PAINT, and
    1.5 for STRUCTURAL."
    PRD §3.3: "While the inspection is in progress the provisional score considers only the
    items recorded so far; it does not check whether every mandatory category has been covered,
    and it adds no synthetic penalty."

    Design: Difficulty/dual_variant_calc/inspection_score_provisional_vs_final
    """
    ctx = _in_progress_with_one_minor_life_safety_fail(api)
    data = validate_success(api.get_inspection(ctx["inspection"]["id"],
                                               make_inspector_headers(ctx["inspector_id"])))
    assert data["result_score"] == pytest.approx(2.0, abs=0.05), "MINOR(1) * LIFE_SAFETY(2.0) == 2.0"


def test_final_score_charges_synthetic_and_fails(api):
    """PRD §3.4: "for each mandatory category that has zero recorded items, a synthetic critical
    failure is charged, contributing the critical severity weight of 10 multiplied by that
    category's multiplier. The mandatory categories are LIFE_SAFETY and HABITABILITY, so a
    missing LIFE_SAFETY category adds 20.0 and a missing HABITABILITY category adds 10.0."
    PRD §3.4: "An inspection passes when three conditions all hold at completion: the final
    score is strictly less than the pass threshold of 5.0, no recorded item is a CRITICAL
    failure, and every mandatory category has at least one recorded item. If any of those three
    conditions fails, the inspection is FAILED."

    Design: Difficulty/dual_variant_calc/inspection_score_provisional_vs_final
    """
    ctx = _in_progress_with_one_minor_life_safety_fail(api)
    data = get_success_data(api.complete_inspection(ctx["inspection"]["id"],
                                                    make_inspector_headers(ctx["inspector_id"])))
    assert data["result_score"] == pytest.approx(12.0, abs=0.05), "2.0 base + 10.0 synthetic HABITABILITY"
    assert data["status"] == "FAILED"


# --- Difficulty: resource_temporal_overlap / inspector_double_booking_halfopen_overlap

def test_inspector_double_booked_overlapping_intervals_rejected(api):
    """PRD §3.2: "if the assigned inspector already has an inspection whose half-open interval —
    from its scheduled_date up to but not including scheduled_date plus its duration_minutes —
    overlaps the interval of the new inspection, scheduling is rejected with
    ERR_INSPECTOR_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/inspector_double_booking_halfopen_overlap
    """
    get_success_data(api.set_clock("2026-06-01T08:00:00Z", REGISTRAR))
    landlord = create_landlord(api)
    inspector = create_inspector(api)
    prop_a = create_property(api, landlord["id"], street_address="150 A")
    prop_b = create_property(api, landlord["id"], street_address="151 B")
    ih = make_inspector_headers(inspector["id"])
    validate_success(api.create_inspection(
        {"property_id": prop_a["id"], "inspector_id": inspector["id"], "inspection_type": "PERIODIC",
         "scheduled_date": "2026-06-01T09:00:00Z", "duration_minutes": 60}, ih), expected_status=201)
    # [09:30,10:30) overlaps [09:00,10:00)
    resp = api.create_inspection(
        {"property_id": prop_b["id"], "inspector_id": inspector["id"], "inspection_type": "PERIODIC",
         "scheduled_date": "2026-06-01T09:30:00Z", "duration_minutes": 60}, ih)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED.value)


def test_inspector_abutting_intervals_allowed(api):
    """PRD §3.2: "Intervals that merely abut (one ending exactly when the next begins) do not
    overlap and are allowed."

    Design: Difficulty/resource_temporal_overlap/inspector_double_booking_halfopen_overlap
    """
    get_success_data(api.set_clock("2026-06-01T08:00:00Z", REGISTRAR))
    landlord = create_landlord(api)
    inspector = create_inspector(api)
    prop_a = create_property(api, landlord["id"], street_address="150 A")
    prop_b = create_property(api, landlord["id"], street_address="151 B")
    ih = make_inspector_headers(inspector["id"])
    validate_success(api.create_inspection(
        {"property_id": prop_a["id"], "inspector_id": inspector["id"], "inspection_type": "PERIODIC",
         "scheduled_date": "2026-06-01T09:00:00Z", "duration_minutes": 60}, ih), expected_status=201)
    # [10:00,11:00) abuts [09:00,10:00) — allowed.
    resp = api.create_inspection(
        {"property_id": prop_b["id"], "inspector_id": inspector["id"], "inspection_type": "PERIODIC",
         "scheduled_date": "2026-06-01T10:00:00Z", "duration_minutes": 60}, ih)
    validate_success(resp, expected_status=201)


# --- Difficulty: resource_temporal_overlap / property_inspection_cooldown_buffer

def test_property_cooldown_within_24h_rejected(api):
    """PRD §3.2: "if the same property already has another non-terminal inspection whose
    scheduled_date falls within 24 hours of the new one — a closed window on both sides —
    scheduling is rejected with ERR_INSPECTION_COOLDOWN."

    Design: Difficulty/resource_temporal_overlap/property_inspection_cooldown_buffer
    """
    get_success_data(api.set_clock("2026-06-01T08:00:00Z", REGISTRAR))
    landlord = create_landlord(api)
    insp1 = create_inspector(api, badge_number="B16a", email="i16a@x.com")
    insp2 = create_inspector(api, badge_number="B16b", email="i16b@x.com")
    prop = create_property(api, landlord["id"], street_address="160 C")
    validate_success(api.create_inspection(
        {"property_id": prop["id"], "inspector_id": insp1["id"], "inspection_type": "PERIODIC",
         "scheduled_date": "2026-06-01T09:00:00Z", "duration_minutes": 60},
        make_inspector_headers(insp1["id"])), expected_status=201)
    # 10 hours later on the same property (different inspector, no overlap) → cooldown.
    resp = api.create_inspection(
        {"property_id": prop["id"], "inspector_id": insp2["id"], "inspection_type": "PERIODIC",
         "scheduled_date": "2026-06-01T19:00:00Z", "duration_minutes": 60},
        make_inspector_headers(insp2["id"]))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_COOLDOWN.value)


def test_property_cooldown_outside_24h_allowed(api):
    """PRD §3.2: "if the same property already has another non-terminal inspection whose
    scheduled_date falls within 24 hours of the new one — a closed window on both sides —
    scheduling is rejected with ERR_INSPECTION_COOLDOWN."

    Design: Difficulty/resource_temporal_overlap/property_inspection_cooldown_buffer
    """
    get_success_data(api.set_clock("2026-06-01T08:00:00Z", REGISTRAR))
    landlord = create_landlord(api)
    insp1 = create_inspector(api, badge_number="B16a", email="i16a@x.com")
    insp2 = create_inspector(api, badge_number="B16b", email="i16b@x.com")
    prop = create_property(api, landlord["id"], street_address="160 C")
    validate_success(api.create_inspection(
        {"property_id": prop["id"], "inspector_id": insp1["id"], "inspection_type": "PERIODIC",
         "scheduled_date": "2026-06-01T09:00:00Z", "duration_minutes": 60},
        make_inspector_headers(insp1["id"])), expected_status=201)
    # 25 hours later — outside the 24h buffer → allowed.
    resp = api.create_inspection(
        {"property_id": prop["id"], "inspector_id": insp2["id"], "inspection_type": "PERIODIC",
         "scheduled_date": "2026-06-02T10:00:00Z", "duration_minutes": 60},
        make_inspector_headers(insp2["id"]))
    validate_success(resp, expected_status=201)


# --- Difficulty: cross_entity_state_dependency / inspection_begin_blocked_by_suspended_property

def _suspended_property_with_scheduled_inspection(api):
    ctx = setup_landlord_inspector_property(api, unit_count=3, year_built=1980)
    run_periodic_with_fail_items(
        api, ctx,
        fail_items=[{"category": "LIFE_SAFETY", "code": "FIRE_EXIT", "severity": "CRITICAL"}],
        pass_items=[{"category": "HABITABILITY", "code": "HEAT"}],
        scheduled_date="2026-06-01T09:00:00Z",
    )
    get_success_data(api.set_clock("2026-06-05T09:00:00Z", REGISTRAR))
    ins2 = schedule_inspection(api, ctx["property_id"], ctx["inspector_id"],
                               "2026-06-05T09:00:00Z", inspection_type="PERIODIC")
    ctx["ins2"] = ins2
    return ctx


def test_begin_blocked_when_property_suspended(api):
    """PRD §3.3: "Two further conditions guard the start: the inspection must currently be
    SCHEDULED, and the property must be in registration_status REGISTERED — attempting to begin
    against a property that is not registered is rejected with ERR_PROPERTY_NOT_REGISTERED."

    Design: Difficulty/cross_entity_state_dependency/inspection_begin_blocked_by_suspended_property
    """
    ctx = _suspended_property_with_scheduled_inspection(api)
    resp = api.begin_inspection(ctx["ins2"]["id"], make_inspector_headers(ctx["inspector_id"]))
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_REGISTERED.value)


def test_begin_blocked_leaves_inspection_scheduled(api):
    """PRD §3.3: "Beginning the on-site visit advances the inspection from SCHEDULED to
    IN_PROGRESS, and it is permitted only when the acting inspector's X-User-ID matches the
    inspection's inspector_id."
    PRD §3.3: "the property must be in registration_status REGISTERED — attempting to begin
    against a property that is not registered is rejected with ERR_PROPERTY_NOT_REGISTERED."

    Design: Difficulty/cross_entity_state_dependency/inspection_begin_blocked_by_suspended_property
    """
    ctx = _suspended_property_with_scheduled_inspection(api)
    api.begin_inspection(ctx["ins2"]["id"], make_inspector_headers(ctx["inspector_id"]))
    data = validate_success(api.get_inspection(ctx["ins2"]["id"],
                                               make_inspector_headers(ctx["inspector_id"])))
    assert data["status"] == "SCHEDULED", "rejected begin leaves the inspection unchanged"


# --- Difficulty: priority_pair_validation_conflict / reinspection_state_beats_temporal

def test_reinspection_state_beats_temporal_combined(api):
    """PRD §3.2: "A REINSPECTION additionally references the failed inspection it re-checks via
    prior_inspection_id; that prior inspection must itself be in the FAILED state, and a prior
    inspection in any other state makes the transition invalid."
    PRD §2.10: "if a transition is attempted from a state that does not allow it, the request is
    rejected with ERR_INVALID_STATE. Any remaining business rules — habitability safety, fiscal,
    referential, temporal, and threshold checks named throughout §3 — are evaluated after the
    state check."

    Design: Difficulty/priority_pair_validation_conflict/reinspection_state_beats_temporal
    """
    ctx = setup_landlord_inspector_property(api, unit_count=3, year_built=1980)
    run_periodic_to_passed(api, ctx)  # prior inspection is PASSED, conducted at 2026-06-01T09:00
    prior_id = ctx["passed_inspection"]["id"]
    # scheduled_date 2026-06-01T12:00 is BOTH < conducted+48h (temporal) AND prior not FAILED (state).
    resp = api.create_inspection(
        {"property_id": ctx["property_id"], "inspector_id": ctx["inspector_id"],
         "inspection_type": "REINSPECTION", "prior_inspection_id": prior_id,
         "scheduled_date": "2026-06-01T12:00:00Z"}, make_inspector_headers(ctx["inspector_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reinspection_state_error_isolated_with_temporal_satisfied(api):
    """PRD §3.2: "that prior inspection must itself be in the FAILED state, and a prior
    inspection in any other state makes the transition invalid."
    PRD §2.10: "if a transition is attempted from a state that does not allow it, the request is
    rejected with ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/reinspection_state_beats_temporal
    """
    ctx = setup_landlord_inspector_property(api, unit_count=3, year_built=1980)
    run_periodic_to_passed(api, ctx)
    prior_id = ctx["passed_inspection"]["id"]
    # scheduled_date 2026-06-10 is well past conducted+48h, so temporal passes; only state fails.
    resp = api.create_inspection(
        {"property_id": ctx["property_id"], "inspector_id": ctx["inspector_id"],
         "inspection_type": "REINSPECTION", "prior_inspection_id": prior_id,
         "scheduled_date": "2026-06-10T09:00:00Z"}, make_inspector_headers(ctx["inspector_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner: state_machines / begin_already_in_progress_returns_invalid_state

def test_begin_already_in_progress_returns_invalid_state(api):
    """PRD §3.3: "Two further conditions guard the start: the inspection must currently be
    SCHEDULED, and the property must be in registration_status REGISTERED".
    PRD §2.10: "if a transition is attempted from a state that does not allow it, the request is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/begin_already_in_progress_returns_invalid_state
    """
    ctx = setup_landlord_inspector_property(api, unit_count=3, year_built=1980)
    insp = schedule_inspection(api, ctx["property_id"], ctx["inspector_id"],
                               "2026-06-01T09:00:00Z", inspection_type="PERIODIC")
    begin_inspection(api, insp["id"], ctx["inspector_id"])
    resp = api.begin_inspection(insp["id"], make_inspector_headers(ctx["inspector_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    data = validate_success(api.get_inspection(insp["id"], make_inspector_headers(ctx["inspector_id"])))
    assert data["status"] == "IN_PROGRESS", "unchanged"


# --- Corner: state_machines / complaint_resolved_on_passing_complaint_inspection

def test_complaint_resolved_on_passing_complaint_inspection(api):
    """PRD §3.2: "A COMPLAINT inspection additionally references the originating complaint_id,
    and scheduling it transitions the linked complaint from FILED to INSPECTION_SCHEDULED."
    PRD §3.4: "A COMPLAINT inspection that instead passes resolves its linked complaint,
    transitioning it from INSPECTION_SCHEDULED to RESOLVED."

    Design: Corner/state_machines/complaint_resolved_on_passing_complaint_inspection
    """
    ctx = setup_landlord_inspector_property(api, unit_count=3, year_built=1980)
    complaint = create_complaint(api, ctx["property_id"], category="HABITABILITY",
                                 severity_alleged="MAJOR")
    insp = schedule_inspection(api, ctx["property_id"], ctx["inspector_id"],
                               "2026-06-01T09:00:00Z", inspection_type="COMPLAINT",
                               complaint_id=complaint["id"])
    begin_inspection(api, insp["id"], ctx["inspector_id"])
    record_item(api, insp["id"], ctx["inspector_id"], "LIFE_SAFETY", "SMOKE_DETECTOR", "PASS")
    record_item(api, insp["id"], ctx["inspector_id"], "HABITABILITY", "HEAT", "PASS")
    get_success_data(api.complete_inspection(insp["id"], make_inspector_headers(ctx["inspector_id"])))
    complaints = get_success_data(api.list_property_complaints(ctx["property_id"], REGISTRAR))
    assert complaints[0]["status"] == "RESOLVED"
