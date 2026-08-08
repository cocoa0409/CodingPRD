"""Contamination casework and health advisories.

Covers the cyclic case machine, the case-close cleanup cascade, the
advisory-count conservation invariant, the closed-interval advisory overlap
guard, segregation of duties, and manual advisory issuance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_health_officer_headers,
    factories as f, fixtures as fx,
)

OFFICER = TEST_USERS["health_officer_headers"]


# --------------------------------------------------------------------------
# non_linear_state_machine / contamination_case_cyclic_reopen
# --------------------------------------------------------------------------
def test_resolved_case_reopens_to_investigating(api):
    """PRD §3.7: "from RESOLVED the officer may reopen the case back to
    INVESTIGATING, again by supplying to_status, forming a cycle that lets a case
    that resurfaces be worked again."

    Design: Difficulty/non_linear_state_machine/contamination_case_cyclic_reopen
    """
    ctx = fx.create_well_only(api)
    case = fx.open_manual_case(api, ctx.well_id, "officer-1")
    fx.advance_case_to_resolved(api, case["id"], "officer-1")
    resp = api.transition_case(case["id"], {"to_status": "INVESTIGATING"},
                               make_health_officer_headers("officer-1"))
    data = validate_success(resp, 200)
    assert data["status"] == "INVESTIGATING"


def test_reopened_case_can_advance_again(api):
    """PRD §3.7: "From OPEN it moves to INVESTIGATING, from INVESTIGATING to
    MITIGATION, and from MITIGATION to RESOLVED; each of these steps is requested
    by naming the desired next status in a to_status field, and each requires the
    case to currently be in the immediately preceding status".

    Design: Difficulty/non_linear_state_machine/contamination_case_cyclic_reopen
    """
    ctx = fx.create_well_only(api)
    case = fx.open_manual_case(api, ctx.well_id, "officer-1")
    fx.advance_case_to_resolved(api, case["id"], "officer-1")
    officer = make_health_officer_headers("officer-1")
    get_success_data(api.transition_case(case["id"], {"to_status": "INVESTIGATING"}, officer))
    resp = api.transition_case(case["id"], {"to_status": "MITIGATION"}, officer)
    data = validate_success(resp, 200)
    assert data["status"] == "MITIGATION"


# --------------------------------------------------------------------------
# transitive_cascade / case_close_cascade_lifts_advisory_and_recomputes_potability
# --------------------------------------------------------------------------
def test_case_close_lifts_advisory_and_zeroes_count(api):
    """PRD §3.7: "every `ACTIVE` advisory whose `source_case_id` is this case is
    lifted (moved from `ACTIVE` to `LIFTED`) and the well's
    `active_advisory_count` is decremented accordingly".

    Design: Difficulty/transitive_cascade/case_close_cascade_lifts_advisory_and_recomputes_potability
    """
    ctx = fx.setup_well_with_cascade_case(api)
    fx.advance_case_to_resolved(api, ctx.case["id"], "officer-closer")
    get_success_data(api.close_case(ctx.case["id"], {"resolution_notes": "remediated"},
                                    make_health_officer_headers("officer-closer")))
    advisory = get_success_data(api.get_advisory(ctx.advisory["id"], OFFICER))
    assert advisory["status"] == "LIFTED"
    well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    assert well["active_advisory_count"] == 0


def test_case_close_recomputes_potability_from_latest_result(api):
    """PRD §3.7: "then the well's potability_status is recomputed from the
    confirmed level of the latest remaining resulted sample, using the same
    SAFE→POTABLE, ADVISORY→ADVISORY, UNSAFE→UNSAFE mapping."

    Design: Difficulty/transitive_cascade/case_close_cascade_lifts_advisory_and_recomputes_potability
    """
    ctx = fx.setup_well_with_cascade_case(api)
    fx.advance_case_to_resolved(api, ctx.case["id"], "officer-closer")
    closed = get_success_data(api.close_case(
        ctx.case["id"], {"resolution_notes": "remediated"},
        make_health_officer_headers("officer-closer")))
    assert closed["status"] == "CLOSED"
    well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    # Latest remaining resulted sample is the bacteria-PRESENT (confirmed UNSAFE)
    # one, so the recompute maps UNSAFE->UNSAFE.
    assert well["potability_status"] == "UNSAFE"


# --------------------------------------------------------------------------
# compensating_invariant / case_open_close_conserves_active_advisory_count
# --------------------------------------------------------------------------
def test_case_open_then_close_returns_count_to_zero(api):
    """PRD §2.7: "A Well carries active_advisory_count, defaulting to 0, defined
    as the number of advisories for that well whose status is ACTIVE."
    PRD §3.7: "every ACTIVE advisory whose source_case_id is this case is lifted
    (moved from ACTIVE to LIFTED) and the well's active_advisory_count is
    decremented accordingly".

    Design: Difficulty/compensating_invariant/case_open_close_conserves_active_advisory_count
    """
    ctx = fx.setup_well_with_cascade_case(api)
    assert ctx.well["active_advisory_count"] == 1
    fx.advance_case_to_resolved(api, ctx.case["id"], "officer-closer")
    get_success_data(api.close_case(ctx.case["id"], {"resolution_notes": "cleared"},
                                    make_health_officer_headers("officer-closer")))
    well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    assert well["active_advisory_count"] == 0


def test_advisory_count_reflects_active_only_across_open_and_close(api):
    """PRD §2.7: "It is recomputed whenever an advisory is issued (manually or by
    cascade) and whenever an advisory is lifted."

    Design: Difficulty/compensating_invariant/case_open_close_conserves_active_advisory_count
    """
    ctx = fx.setup_well_with_cascade_case(api)
    opened_well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    assert opened_well["active_advisory_count"] == 1
    fx.advance_case_to_resolved(api, ctx.case["id"], "officer-closer")
    get_success_data(api.close_case(ctx.case["id"], {"resolution_notes": "cleared"},
                                    make_health_officer_headers("officer-closer")))
    closed_well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    assert closed_well["active_advisory_count"] == 0


# --------------------------------------------------------------------------
# resource_temporal_overlap / advisory_closed_interval_same_type_overlap
# --------------------------------------------------------------------------
def test_same_type_advisory_touching_endpoint_conflicts(api):
    """PRD §3.6: "if any existing ACTIVE advisory of the same advisory_type on
    the well has a closed interval [effective_from, effective_to] that overlaps
    the proposed interval — where two closed intervals overlap when each starts
    no later than the other ends — the request is rejected with
    ERR_ADVISORY_WINDOW_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/advisory_closed_interval_same_type_overlap
    """
    ctx = fx.create_well_only(api)
    get_success_data(api.create_advisory(f.advisory_payload(
        ctx.well_id, advisory_type="NITRATE",
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z"), OFFICER))
    resp = api.create_advisory(f.advisory_payload(
        ctx.well_id, advisory_type="NITRATE",
        effective_from="2026-06-30T00:00:00Z", effective_to="2026-07-15T00:00:00Z"), OFFICER)
    validate_error(resp, ApiErrorId.ERR_ADVISORY_WINDOW_OVERLAP)


def test_different_type_advisory_same_window_allowed(api):
    """PRD §3.6: "Advisories of different types, or lifted advisories, never
    conflict."

    Design: Difficulty/resource_temporal_overlap/advisory_closed_interval_same_type_overlap
    """
    ctx = fx.create_well_only(api)
    get_success_data(api.create_advisory(f.advisory_payload(
        ctx.well_id, advisory_type="NITRATE",
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z"), OFFICER))
    resp = api.create_advisory(f.advisory_payload(
        ctx.well_id, advisory_type="LEAD",
        effective_from="2026-06-30T00:00:00Z", effective_to="2026-07-15T00:00:00Z"), OFFICER)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Corner: segregation of duties + manual advisory count
# --------------------------------------------------------------------------
def test_self_close_by_opening_officer_forbidden(api):
    """PRD §3.7: "A case may be closed only from RESOLVED status, and only by an
    officer different from the one who opened it: the closing officer's X-User-ID
    must not equal the case's opened_by_officer_id, or the close is rejected with
    ERR_SELF_CLOSE_FORBIDDEN (HTTP 403)."

    Design: Corner/state_machines/contamination_self_close_returns_forbidden
    """
    ctx = fx.create_well_only(api)
    case = fx.open_manual_case(api, ctx.well_id, "officer-A", severity="MODERATE")
    fx.advance_case_to_resolved(api, case["id"], "officer-A")
    resp = api.close_case(case["id"], {"resolution_notes": "self close"},
                          make_health_officer_headers("officer-A"))
    validate_error(resp, ApiErrorId.ERR_SELF_CLOSE_FORBIDDEN)


def test_manual_advisory_increments_active_count(api):
    """PRD §3.6: "A manual advisory is created `ACTIVE` with `source_case_id`
    null, and it increments the well's `active_advisory_count`."

    Design: Corner/cross_cutting/manual_advisory_issue_increments_active_count
    """
    ctx = fx.create_well_only(api)
    resp = api.create_advisory(f.advisory_payload(
        ctx.well_id, advisory_type="LEAD",
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z"), OFFICER)
    advisory = validate_success(resp, 201)
    assert advisory["status"] == "ACTIVE"
    well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    assert well["active_advisory_count"] == 1
