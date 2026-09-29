"""Queue A — rule_id: priority_pair_validation_conflict.

Requests that violate two ladder positions at once. The lower-numbered position
must win, and the masked error must never surface.
"""
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_compliance_officer_headers,
    make_deployment_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")
CE_CLOSER = make_claims_examiner_headers("ce_2")
CO = make_compliance_officer_headers("co_1")


# ---------------------------------------------------------------------------
# Instance 1 — pair_a_close_claim_state_19_beats_moratorium_safety_21
# ---------------------------------------------------------------------------
def _triaged_claim_under_moratorium(api):
    """CAT-2026-501 DECLARED with an EFFECTIVE CANCELLATION_MORATORIUM bulletin
    covering the current instant, plus one claim TRIAGED at STANDARD."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-501",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-07-26T00:00:00.000Z",
                "exposure_count": 1000,
                "avg_insured_value": 250000,
                "expected_severity_index": 0.0400,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    bulletin = validate_success(
        api.create_bulletin(
            {
                "event_id": event["id"],
                "bulletin_number": "FL-2026-M7",
                "jurisdiction_state": "FL",
                "bulletin_type": "CANCELLATION_MORATORIUM",
                "effective_from": "2026-07-25T00:00:00.000Z",
                "effective_to": "2026-09-01T00:00:00.000Z",
            },
            CO,
        ),
        201,
    )
    validate_success(api.activate_bulletin(bulletin["id"], CO))
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-5101",
                "loss_state": "FL",
                "loss_date_utc": "2026-07-27T00:00:00.000Z",
                "reported_loss_amount": 120000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 400000,
                        "deductible_amount": 5000,
                        "estimated_damage_amount": 150000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    return event, bulletin, triaged


def test_closing_a_triaged_claim_under_moratorium_reports_the_state_failure(api):
    """PRD §2.11: "Closing a claim that is still `TRIAGED` while a cancellation
    moratorium is in force returns `ERR_CLAIM_NOT_INSPECTED`, not
    `ERR_MORATORIUM_ACTIVE`, because the state check at position 19 precedes the safety
    check at position 21."
    PRD §2.11: "The response always carries the error belonging to the
    **lowest-numbered** rule in the ladder below; evaluation stops at the first failure,
    so a later, more interesting violation is masked by an earlier one."

    Design: Difficulty/priority_pair_validation_conflict/pair_a_close_claim_state_19_beats_moratorium_safety_21
    """
    event, _, claim = _triaged_claim_under_moratorium(api)
    live = validate_success(api.get_event(event["id"], CM))
    assert live["moratorium_active"] is True
    assert live["posture"] == "RESTRICTED"
    assert_money_equals(claim["severity_score"], 35.30, "severity_score")

    error = validate_error(
        api.close_claim(claim["id"], CE_CLOSER), ApiErrorId.ERR_CLAIM_NOT_INSPECTED, 409
    )

    assert error["error_id"] != ApiErrorId.ERR_MORATORIUM_ACTIVE.value


def test_the_masked_moratorium_check_leaves_the_claim_untouched(api):
    """PRD §3.6: "**Closure** moves the claim `INSPECTED → CLOSED`, and five conditions
    guard it. The claim must be `INSPECTED` (`ERR_CLAIM_NOT_INSPECTED`). The parent
    event's `moratorium_active` must be false (`ERR_MORATORIUM_ACTIVE`)."
    PRD §3.6: "Closure records the acting `X-User-ID` in `closing_examiner_user_id` and
    recomputes the event's `open_claim_count` and posture."
    PRD §2.11: "Position 19 is the state check: the target must currently be in a state
    from which the requested transition is declared, and the error returned is the
    specific one named by that transition's preconditions rather than a generic one;
    `ERR_INVALID_STATE` (HTTP 409) is the fallback used only when a state-transition
    endpoint is invoked from a from-state that no declared transition covers and no more
    specific error applies."

    Design: Difficulty/priority_pair_validation_conflict/pair_a_close_claim_state_19_beats_moratorium_safety_21
    """
    event, _, claim = _triaged_claim_under_moratorium(api)

    validate_error(api.close_claim(claim["id"], CE_CLOSER), ApiErrorId.ERR_CLAIM_NOT_INSPECTED)

    refreshed = validate_success(api.get_claim(claim["id"], CE))
    assert refreshed["handling_status"] == "TRIAGED"
    assert refreshed["closing_examiner_user_id"] is None
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert refreshed_event["moratorium_active"] is True
    assert refreshed_event["posture"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# Instance 2 — pair_b_confirm_deployment_temporal_23_beats_fiscal_38
# ---------------------------------------------------------------------------
def _adjacent_window_against_exhausted_block(api):
    """CAT-2026-502 DECLARED; adjuster A has a DEMOBILIZED window
    2026-09-01 -> 2026-09-05 and is AVAILABLE again; adjuster B holds the block's
    single room for 2026-09-20 -> 2026-09-25 so the block is EXHAUSTED; A's second
    REQUESTED deployment asks for 2026-09-05 -> 2026-09-09 plus that one room."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-502",
                "peril_type": "HAIL",
                "jurisdiction_state": "TX",
                "event_start_utc": "2026-07-26T00:00:00.000Z",
                "exposure_count": 600,
                "avg_insured_value": 160000,
                "expected_severity_index": 0.0900,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))

    def _make_adjuster(name):
        return validate_success(
            api.create_adjuster(
                {
                    "full_name": name,
                    "employment_type": "STAFF",
                    "home_state": "TX",
                    "licensed_states": ["TX"],
                    "license_expiry_utc": "2027-09-30T00:00:00.000Z",
                    "max_open_claims": 8,
                    "daily_rate": 500,
                    "per_diem_rate": 50,
                    "desk_certified": False,
                    "aerial_certified": False,
                },
                DC,
            ),
            201,
        )

    adj_a = _make_adjuster("Adjuster A")
    adj_b = _make_adjuster("Adjuster B")
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Single Room Inn",
                "city": "Amarillo",
                "rooms_total": 1,
                "nightly_rate": 150,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-30T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], DC))

    first = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-05T00:00:00.000Z",
                "adjuster_id": adj_a["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )
    validate_success(api.confirm_deployment(first["id"], DC))
    validate_success(api.set_clock("2026-08-02T00:00:00.000Z", DC))
    validate_success(api.demobilize_deployment(first["id"], DC))
    validate_success(api.set_clock("2026-08-03T00:00:00.000Z", DC))

    holder = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-20T00:00:00.000Z",
                "window_end_utc": "2026-09-25T00:00:00.000Z",
                "adjuster_id": adj_b["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )
    validate_success(api.confirm_deployment(holder["id"], DC))
    second = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-05T00:00:00.000Z",
                "window_end_utc": "2026-09-09T00:00:00.000Z",
                "adjuster_id": adj_a["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )
    return event, adj_a, block, second


def test_rest_buffer_conflict_masks_the_housing_capacity_failure(api):
    """PRD §2.11: "Confirming a deployment that both breaches the 12-hour rest buffer
    and asks for more rooms than the block has available returns
    `ERR_DEPLOYMENT_WINDOW_CONFLICT`, not `ERR_HOUSING_CAPACITY_EXCEEDED`, because the
    temporal rule at position 23 precedes the fiscal rule at position 38."
    PRD §3.5: "Concretely, a conflict exists when the new window's start is earlier than
    the other window's end extended forward by twelve hours *and* the other window's
    start is earlier than the new window's end extended forward by twelve hours."
    PRD §3.5: "Exact adjacency is therefore **rejected**: a full twelve-hour gap must
    separate the windows, and the rejection is `ERR_DEPLOYMENT_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/pair_b_confirm_deployment_temporal_23_beats_fiscal_38
    """
    _, adj_a, block, second = _adjacent_window_against_exhausted_block(api)
    staged_block = validate_success(api.get_housing_block(block["id"], DC))
    assert staged_block["rooms_available"] == 0
    assert staged_block["status"] == "EXHAUSTED"

    error = validate_error(
        api.confirm_deployment(second["id"], DC),
        ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT,
        409,
    )

    assert error["error_id"] != ApiErrorId.ERR_HOUSING_CAPACITY_EXCEEDED.value
    assert validate_success(api.get_adjuster(adj_a["id"], DC))["deployment_status"] == "AVAILABLE"


def test_the_rejected_confirmation_leaves_deployment_and_rooms_exactly_as_they_were(api):
    """PRD §3.5: "The created deployment is `REQUESTED`, its `selection_reason` records
    `EXPLICIT_ADJUSTER` when the caller pinned an adjuster and `SELECTOR_RANKED` when the
    server chose, and both `provisional_cost` and `final_settled_cost` read 0.00 because
    a requested deployment has not been priced and has drawn no rooms."
    PRD §2.10: "For every housing block, `rooms_total` equals `rooms_available` plus
    `rooms_occupied`, and `rooms_occupied` equals the sum of `rooms_reserved` over the
    deployments drawing on that block whose status is `CONFIRMED` or `ON_SITE`."

    Design: Difficulty/priority_pair_validation_conflict/pair_b_confirm_deployment_temporal_23_beats_fiscal_38
    """
    _, _, block, second = _adjacent_window_against_exhausted_block(api)

    validate_error(
        api.confirm_deployment(second["id"], DC), ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT
    )

    refreshed = validate_success(api.get_deployment(second["id"], DC))
    assert refreshed["status"] == "REQUESTED"
    assert_money_equals(refreshed["provisional_cost"], 0.00, "provisional_cost")
    refreshed_block = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed_block["rooms_occupied"] == 1
    assert refreshed_block["rooms_available"] == 0
    assert refreshed_block["status"] == "EXHAUSTED"


# ---------------------------------------------------------------------------
# Instance 3 — pair_c_schedule_assignment_referential_29_beats_constraint_32
# ---------------------------------------------------------------------------
def _aerial_claim_and_capped_adjuster(api):
    """CAT-2026-503 DECLARED @ 0.5000; one DESK-certified adjuster with
    max_open_claims 1 already holding a SCHEDULED assignment on FAST_TRACK claim P;
    claim Q is INACCESSIBLE + CAT_SEVERE, so its mode resolves to AERIAL."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-503",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-07-28T00:00:00.000Z",
                "exposure_count": 1100,
                "avg_insured_value": 300000,
                "expected_severity_index": 0.5000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Cap One",
                "employment_type": "STAFF",
                "home_state": "FL",
                "licensed_states": ["FL"],
                "license_expiry_utc": "2027-08-31T00:00:00.000Z",
                "max_open_claims": 1,
                "daily_rate": 650,
                "per_diem_rate": 0,
                "desk_certified": True,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )
    claim_p = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-5301",
                "loss_state": "FL",
                "loss_date_utc": "2026-07-28T00:00:00.000Z",
                "reported_loss_amount": 5000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 50000,
                        "deductible_amount": 250,
                        "estimated_damage_amount": 6000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    claim_p = validate_success(api.triage_claim(claim_p["id"], CE))
    assignment_p = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim_p["id"],
                "mode": "DESK",
                "window_start_utc": "2026-08-05T00:00:00.000Z",
                "window_end_utc": "2026-08-06T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    claim_q = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-5302",
                "loss_state": "FL",
                "loss_date_utc": "2026-07-28T00:00:00.000Z",
                "reported_loss_amount": 200000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 200000,
                        "deductible_amount": 5000,
                        "estimated_damage_amount": 250000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "INACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    claim_q = validate_success(api.triage_claim(claim_q["id"], CE))
    return event, adjuster, claim_p, assignment_p, claim_q


def test_inspection_mode_mismatch_masks_the_adjuster_capacity_failure(api):
    """PRD §2.11: "Scheduling a field-mode inspection against a claim whose resolved
    mode is aerial, using an adjuster who is already at their assignment ceiling, returns
    `ERR_INSPECTION_MODE_MISMATCH`, not `ERR_ADJUSTER_AT_CAPACITY`, because the
    referential rule at position 29 precedes the constraint at position 32."
    PRD §3.7: "The submitted `mode` must equal the claim's `inspection_mode` **as
    currently computed**, not as it stood at triage — a claim whose access has since
    degraded needs the mode the resolver returns now, and a mismatch is
    `ERR_INSPECTION_MODE_MISMATCH` (HTTP 422)."
    PRD §3.6: "If the claim's `access_status` is `INACCESSIBLE` and its `triage_tier` is
    `COMPLEX` or `CAT_SEVERE`, the mode is `AERIAL` — a severe loss nobody can drive to
    gets flown."

    Design: Difficulty/priority_pair_validation_conflict/pair_c_schedule_assignment_referential_29_beats_constraint_32
    """
    _, adjuster, _, _, claim_q = _aerial_claim_and_capped_adjuster(api)
    assert claim_q["inspection_mode"] == "AERIAL"
    assert_money_equals(claim_q["severity_score"], 100.00, "severity_score")
    assert validate_success(api.get_adjuster(adjuster["id"], DC))["open_assignment_count"] == 1

    error = validate_error(
        api.create_inspection_assignment(
            {
                "claim_id": claim_q["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-08-10T00:00:00.000Z",
                "window_end_utc": "2026-08-11T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        ApiErrorId.ERR_INSPECTION_MODE_MISMATCH,
        422,
    )

    assert error["error_id"] != ApiErrorId.ERR_ADJUSTER_AT_CAPACITY.value


def test_the_rejected_scheduling_creates_nothing_and_leaves_both_claims_alone(api):
    """PRD §3.6: "Otherwise, if the tier is `FAST_TRACK` and the `reported_loss_amount`
    is 10000.00 or less, the mode is `DESK` — the boundary is inclusive, so a reported
    loss of exactly 10000.00 resolves to `DESK` while 10000.01 resolves to `FIELD`."
    PRD §3.7: "The adjuster's `open_assignment_count` must be strictly below their
    `max_open_claims`, evaluated before this new assignment is counted, otherwise
    `ERR_ADJUSTER_AT_CAPACITY` (HTTP 409)."
    PRD §3.7: "Assignment lists may be filtered by `claim_id`, `adjuster_id`,
    `deployment_id`, `status` and `mode`."

    Design: Difficulty/priority_pair_validation_conflict/pair_c_schedule_assignment_referential_29_beats_constraint_32
    """
    _, adjuster, claim_p, assignment_p, claim_q = _aerial_claim_and_capped_adjuster(api)

    validate_error(
        api.create_inspection_assignment(
            {
                "claim_id": claim_q["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-08-10T00:00:00.000Z",
                "window_end_utc": "2026-08-11T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        ApiErrorId.ERR_INSPECTION_MODE_MISMATCH,
    )

    assert validate_success(api.get_claim(claim_p["id"], CE))["inspection_mode"] == "DESK"
    assert_money_equals(claim_p["severity_score"], 21.50, "severity_score")
    assert validate_success(api.get_claim(claim_q["id"], CE))["handling_status"] == "TRIAGED"
    rows = validate_success(
        api.list_inspection_assignments(DC, params={"adjuster_id": adjuster["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == assignment_p["id"]
