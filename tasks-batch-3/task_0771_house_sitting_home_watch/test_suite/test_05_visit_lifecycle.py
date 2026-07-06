"""Visit lifecycle: the flag branch, ordered check-out guards, the key-custody
precondition on check-in, and vacation visit-schedule generation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, make_coordinator_headers, make_sitter_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/visit_flag_branch_divergent_checkout
# ---------------------------------------------------------------------------

def _flagged_visit(api):
    """IN_PROGRESS visit (one photo logged) flagged by a MINOR incident. Returns (ctx, incident)."""
    ctx = fx.setup_in_progress_visit(api, property_overrides={"checklist_config": ["MAIL"]},
                                     add_log=True)
    incident = fx.get_success_data(api.create_incident(
        f.create_incident_payload(ctx["visit"]["id"], category="OTHER", severity="MINOR"),
        make_sitter_headers(ctx["sitter"]["id"])))
    ctx["visit"] = fx.get_visit(api, ctx["visit"]["id"])
    return ctx, incident


def test_flagged_visit_checkout_blocked_by_open_incident(api):
    """PRD 3.7: "closing a flagged visit requires that every incident on the visit is RESOLVED, and
    an unresolved incident is rejected with ERR_UNRESOLVED_INCIDENT".

    Design: Difficulty/non_linear_state_machine/visit_flag_branch_divergent_checkout
    """
    ctx, _incident = _flagged_visit(api)
    assert ctx["visit"]["status"] == "FLAGGED"
    resp = api.check_out_visit(ctx["visit"]["id"], f.check_out_payload(["MAIL"]),
                               make_sitter_headers(ctx["sitter"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_INCIDENT.value, expected_status=409)


def test_flagged_visit_checks_out_once_incident_resolved(api):
    """PRD 3.7: "A flagged visit that satisfies all three checks closes to DONE exactly like an
    in-progress one — stamping check_out_at, computing the same provisional charge, and updating the
    invoice identically."

    Design: Difficulty/non_linear_state_machine/visit_flag_branch_divergent_checkout
    """
    ctx, incident = _flagged_visit(api)
    fx.get_success_data(api.resolve_incident(incident["id"], f.resolve_payload(0), COORD))
    resp = api.check_out_visit(ctx["visit"]["id"], f.check_out_payload(["MAIL"]),
                               make_sitter_headers(ctx["sitter"]["id"]))
    visit = validate_success(resp)
    assert visit["status"] == "DONE", visit


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/checkout_evidence_beats_checklist
# ---------------------------------------------------------------------------

def test_checkout_no_evidence_incomplete_checklist_reports_evidence(api):
    """PRD 3.6: "Two conditions are checked in this fixed order: first, at least one visit log entry
    must exist for the visit, and a checkout with no evidence is rejected with
    ERR_VISIT_EVIDENCE_MISSING; second, the completed_tasks set supplied at checkout must exactly
    equal the property's checklist_config set, and any mismatch is rejected with ERR_CHECKLIST_INCOMPLETE."

    Design: Difficulty/priority_pair_validation_conflict/checkout_evidence_beats_checklist
    """
    ctx = fx.setup_in_progress_visit(api,
                                     property_overrides={"checklist_config": ["MAIL", "PLANTS"]},
                                     add_log=False)
    resp = api.check_out_visit(ctx["visit"]["id"], f.check_out_payload(["MAIL"]),
                               make_sitter_headers(ctx["sitter"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VISIT_EVIDENCE_MISSING.value, expected_status=422)


def test_checkout_evidence_failure_leaves_visit_in_progress(api):
    """PRD 3.6: "a checkout with no evidence is rejected with ERR_VISIT_EVIDENCE_MISSING".

    Design: Difficulty/priority_pair_validation_conflict/checkout_evidence_beats_checklist
    """
    ctx = fx.setup_in_progress_visit(api,
                                     property_overrides={"checklist_config": ["MAIL", "PLANTS"]},
                                     add_log=False)
    api.check_out_visit(ctx["visit"]["id"], f.check_out_payload(["MAIL"]),
                        make_sitter_headers(ctx["sitter"]["id"]))
    assert fx.get_visit(api, ctx["visit"]["id"])["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/checkout_requires_at_least_one_log_entry_zero_vs_one
# ---------------------------------------------------------------------------

def test_checkout_with_zero_log_entries_rejected(api):
    """PRD 3.6: "at least one visit log entry must exist for the visit, and a checkout with no
    evidence is rejected with ERR_VISIT_EVIDENCE_MISSING".

    Design: Difficulty/boundary_precision_check/checkout_requires_at_least_one_log_entry_zero_vs_one
    """
    ctx = fx.setup_in_progress_visit(api, property_overrides={"checklist_config": ["MAIL"]},
                                     add_log=False)
    resp = api.check_out_visit(ctx["visit"]["id"], f.check_out_payload(["MAIL"]),
                               make_sitter_headers(ctx["sitter"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VISIT_EVIDENCE_MISSING.value, expected_status=422)


def test_checkout_succeeds_after_one_log_entry(api):
    """PRD 3.6: "at least one visit log entry must exist for the visit, and a checkout with no
    evidence is rejected with ERR_VISIT_EVIDENCE_MISSING".

    Design: Difficulty/boundary_precision_check/checkout_requires_at_least_one_log_entry_zero_vs_one
    """
    ctx = fx.setup_in_progress_visit(api, property_overrides={"checklist_config": ["MAIL"]},
                                     add_log=False)
    fx.add_photo_log(api, ctx["visit"]["id"], ctx["sitter"]["id"])
    resp = api.check_out_visit(ctx["visit"]["id"], f.check_out_payload(["MAIL"]),
                               make_sitter_headers(ctx["sitter"]["id"]))
    visit = validate_success(resp)
    assert visit["status"] == "DONE", visit


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/checkin_requires_key_checked_out
# ---------------------------------------------------------------------------

def test_check_in_without_checked_out_key_rejected(api):
    """PRD 3.6: "a key assignment for this booking and this sitter must currently be CHECKED_OUT,
    failing otherwise with ERR_KEY_NOT_CHECKED_OUT."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_key_checked_out
    """
    ctx = fx.setup_active_booking(api)
    fx.get_success_data(api.return_key(ctx["key"]["id"], COORD))
    fx.set_clock(api, "2026-06-01T09:00:00Z")
    resp = api.check_in_visit(ctx["visits"][0]["id"], f.check_in_payload(),
                              make_sitter_headers(ctx["sitter"]["id"]))
    validate_error(resp, ApiErrorId.ERR_KEY_NOT_CHECKED_OUT.value, expected_status=409)


def test_check_in_key_failure_leaves_visit_scheduled(api):
    """PRD 3.6: "a key assignment for this booking and this sitter must currently be CHECKED_OUT,
    failing otherwise with ERR_KEY_NOT_CHECKED_OUT."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_key_checked_out
    """
    ctx = fx.setup_active_booking(api)
    fx.get_success_data(api.return_key(ctx["key"]["id"], COORD))
    fx.set_clock(api, "2026-06-01T09:00:00Z")
    api.check_in_visit(ctx["visits"][0]["id"], f.check_in_payload(),
                       make_sitter_headers(ctx["sitter"]["id"]))
    assert fx.get_visit(api, ctx["visits"][0]["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner/calculations/vacation_visit_count_inclusive_three_days
# ---------------------------------------------------------------------------

def test_vacation_booking_generates_one_visit_per_inclusive_day(api):
    """PRD 3.4: "For a VACATION booking there is one visit for each calendar day from start_date to
    end_date inclusive, so the number of visits equals the whole-day difference between the two dates
    plus one."

    Design: Corner/calculations/vacation_visit_count_inclusive_three_days
    """
    ctx = fx.setup_pending_booking(api, booking_overrides={
        "booking_type": "VACATION",
        "start_date": "2026-06-01T00:00:00Z", "end_date": "2026-06-03T00:00:00Z"})
    fx.assign_booking(api, ctx["booking"]["id"], ctx["sitter"]["id"])
    resp = api.list_visits(COORD, params={"booking_id": ctx["booking"]["id"]})
    _data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3, meta
