"""Entity creation, defaults, computed fields, references, and listing
(PRD §2.3, §2.5, §3.1).

Corner queue: entities section + a few state_machines invalid-transition and
terminal-lockdown instances + the goal funding endpoints.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client as api, TEST_USERS, fixtures as fx, factories as f,
    ApiErrorId, FABRICATED_UUID,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# Corner: entities / create_household_returns_201_with_computed_aum_zero
# ===========================================================================
def test_create_household_returns_201_computed_zero(api):
    """PRD §2.8: "All three start at 0 on a freshly created household and are
    recomputed whenever an account's state changes, whenever an account is revalued,
    or whenever an account is added — the precise recomputation is given in §3."
    PRD §2.4: "an integer `version` that begins at its initial value and increments
    by one on every mutation of the resource."

    Design: Corner/entities/create_household_returns_201_with_computed_aum_zero
    """
    sched = fx.create_flat_fee_schedule()
    data = validate_success(api.create_household(
        f.household_payload(sched["id"], name="Carter Family"), ADVISOR),
        expected_status=201)
    assert data["billable_aum_cents"] == 0
    assert data["aggregated_aum_cents"] == 0
    assert data["breakpoint_tier_index"] == 0
    assert data["version"] == 1, f"version begins at 1, got {data['version']}"
    assert data["status"] == "ACTIVE"


# ===========================================================================
# Corner: entities / get_household_nonexistent_returns_not_found
# ===========================================================================
def test_get_household_nonexistent_not_found(api):
    """PRD §2.5: "The system validates path identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in
    the path that does not resolve to an existing resource."

    Design: Corner/entities/get_household_nonexistent_returns_not_found
    """
    resp = api.get_household(FABRICATED_UUID, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner: entities / create_client_missing_required_field_returns_invalid_request
# ===========================================================================
def test_create_client_missing_required_field_rejected(api):
    """PRD §3.1: "Creation requires the owning `household_id`, the client's
    `full_name`, a `date_of_birth` as an ISO `YYYY-MM-DD` date, and two
    onboarding-questionnaire scores: `risk_capacity_score`, the objective ability to
    bear loss, and `risk_tolerance_score`, the subjective willingness to bear loss."
    PRD §2.7: "Field-level input validation — enums within their declared sets,
    scores within range, non-negative cent amounts, well-formed ISO dates, and
    pagination bounds, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_client_missing_required_field_returns_invalid_request
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    payload = {"household_id": hh["id"], "full_name": "C",
               "date_of_birth": "1980-01-01", "risk_capacity_score": 60}
    resp = api.create_client(payload, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / client_score_out_of_range_returns_invalid_request
# ===========================================================================
def test_client_score_out_of_range_rejected(api):
    """PRD §3.1: "Both scores are integers from 0 through 100 inclusive; a score
    outside that range is an `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/client_score_out_of_range_returns_invalid_request
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    resp = api.create_client(
        f.client_payload(hh["id"], risk_capacity_score=150, risk_tolerance_score=60),
        ADVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / suitability_band_computed_from_min_scores
# ===========================================================================
def test_suitability_band_from_min_scores(api):
    """PRD §3.1: "As a side effect of KYC verification, the system computes the
    client's `suitability_band` from the smaller of `risk_capacity_score` and
    `risk_tolerance_score`: the conservative of the two scores selects the band. A
    low combined score yields `CONSERVATIVE`"

    min(80, 20) = 20 -> CONSERVATIVE.

    Design: Corner/entities/suitability_band_computed_from_min_scores
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_client(hh["id"], risk_capacity_score=80, risk_tolerance_score=20)
    data = validate_success(api.client_state(client["id"], "VERIFY_KYC", ADVISOR))
    assert data["suitability_band"] == "CONSERVATIVE", \
        f"min(80,20)=20 -> CONSERVATIVE, got {data['suitability_band']}"


# ===========================================================================
# Corner: entities / household_billing_method_defaults_to_arrears
# ===========================================================================
def test_household_billing_method_defaults_arrears(api):
    """PRD §2.8: "A household pins a `fee_schedule_id` and a `billing_method` of
    either `ARREARS` or `ADVANCE` (defaulting to `ARREARS`)"

    Design: Corner/entities/household_billing_method_defaults_to_arrears
    """
    sched = fx.create_flat_fee_schedule()
    payload = {"name": "HH", "lead_advisor_id": "adv-1", "fee_schedule_id": sched["id"]}
    data = validate_success(api.create_household(payload, ADVISOR), expected_status=201)
    assert data["billing_method"] == "ARREARS", \
        f"billing_method defaults to ARREARS, got {data['billing_method']}"


# ===========================================================================
# Corner: entities / create_household_bad_fee_schedule_reference
# ===========================================================================
def test_create_household_bad_fee_schedule_ref(api):
    """PRD §2.5: "When a creation request names another entity through a body field
    — `household_id`, `client_id`, `fee_schedule_id`, `target_portfolio_id`,
    `plan_id`, or `account_id` — and that referenced entity does not exist, the
    request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

    Design: Corner/entities/create_household_bad_fee_schedule_reference
    """
    resp = api.create_household(
        {"name": "HH", "lead_advisor_id": "adv-1", "fee_schedule_id": FABRICATED_UUID},
        ADVISOR)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Corner: entities / list_households_pagination_envelope
# ===========================================================================
def test_list_households_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_households_pagination_envelope
    """
    sched = fx.create_flat_fee_schedule()
    fx.create_household(sched["id"])
    data, meta = validate_paginated(api.list_households(ADVISOR, params={"limit": 10, "offset": 0}))
    assert isinstance(data, list)
    assert meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)


# ===========================================================================
# Corner: state_machines / client_activate_from_prospect_invalid_state
# ===========================================================================
def test_client_activate_from_prospect_invalid_state(api):
    """PRD §3.1: "Activating moves the client from `IPS_SIGNED` to `ACTIVE`; it
    requires the client be `IPS_SIGNED` and that at least one account exist for the
    client whose status is `PENDING` or `ACTIVE`."
    PRD §3.1: "A transition requested from a state where it is not defined is
    rejected with `ERR_INVALID_STATE` (409)."

    ACTIVATE on a PROSPECT (only defined from IPS_SIGNED) -> ERR_INVALID_STATE.

    Design: Corner/state_machines/client_activate_from_prospect_invalid_state
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_client(hh["id"])
    resp = api.client_state(client["id"], "ACTIVATE", ADVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / compliance_item_archive_from_open_invalid_state
# ===========================================================================
def test_compliance_archive_from_open_invalid_state(api):
    """PRD §3.9: "Archiving moves a `SATISFIED` item to the terminal `ARCHIVED`
    state; its side effect stamps `archive_hash` with a tamper-evident SHA-256 hash
    computed over the item's `subject_type`, `subject_id`, `obligation_type`, and
    `created_at` joined together."
    PRD §3.9: "Any of these transitions requested from a state where it is not
    defined is rejected with `ERR_INVALID_STATE` (409)."

    ARCHIVE on an OPEN item (only defined from SATISFIED) -> ERR_INVALID_STATE.

    Design: Corner/state_machines/compliance_item_archive_from_open_invalid_state
    """
    fx.set_clock("2026-03-01T00:00:00Z", headers=COMPLIANCE)
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    item = fx.create_compliance_item("HOUSEHOLD", hh["id"],
                                     obligation_type="FORM_ADV_DELIVERY",
                                     due_date="2026-12-31")
    resp = api.compliance_item_state(item["id"], "ARCHIVE", COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / client_disengage_then_disengage_again_terminal_lockdown
# ===========================================================================
def test_disengaged_client_rejects_further_action(api):
    """PRD §3.1: "From either `PROSPECT` or `KYC_VERIFIED`, a client may be
    disengaged to the terminal `DISENGAGED` state; disengagement carries no
    cascade."
    PRD §3.1: "A transition requested from a state where it is not defined is
    rejected with `ERR_INVALID_STATE` (409)."

    A second DISENGAGE on a terminal DISENGAGED client -> ERR_INVALID_STATE.

    Design: Corner/state_machines/client_disengage_then_disengage_again_terminal_lockdown
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_client(hh["id"])
    get_success_data(api.client_state(client["id"], "DISENGAGE", ADVISOR))
    resp = api.client_state(client["id"], "DISENGAGE", ADVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: endpoints / goal_fund_increases_current_amount
# ===========================================================================
def test_goal_fund_increases_current_amount_and_ratio(api):
    """PRD §3.6: "funding increases the goal's `current_amount_cents` and recomputes
    its `funded_ratio_bps` and `on_track`."

    DRAFT plan (ACTUAL): fund 300,000 onto current 200,000 -> 500,000 of target
    1,000,000 -> funded_ratio_bps 5000.

    Design: Corner/endpoints/goal_fund_increases_current_amount
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    plan = fx.create_draft_plan(hh["id"], assumed_annual_return_bps=0,
                                monthly_contribution_cents=0)
    goal = fx.create_goal(plan["id"], target_amount_cents=1000000,
                          target_date="2030-01-01", current_amount_cents=200000)
    data = validate_success(api.fund_goal(goal["id"], 300000, ADVISOR))
    assert data["current_amount_cents"] == 500000, \
        f"fund raises current to 500000, got {data['current_amount_cents']}"
    assert data["funded_ratio_bps"] == 5000, \
        f"500k of 1M -> 5000, got {data['funded_ratio_bps']}"


# ===========================================================================
# Corner: endpoints / goal_fund_nonpositive_rejected
# ===========================================================================
def test_goal_fund_nonpositive_rejected(api):
    """PRD §3.6: "Funds may later be added to a goal by an amount given as
    `amount_cents`, which must be greater than zero (a non-positive funding amount
    is also `ERR_GOAL_AMOUNT_INVALID`, 422)"

    Design: Corner/endpoints/goal_fund_nonpositive_rejected
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    plan = fx.create_draft_plan(hh["id"], assumed_annual_return_bps=0,
                                monthly_contribution_cents=0)
    goal = fx.create_goal(plan["id"], target_amount_cents=1000000,
                          target_date="2030-01-01", current_amount_cents=0)
    resp = api.fund_goal(goal["id"], 0, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_GOAL_AMOUNT_INVALID.value)
