"""Plan / provider / member configuration and the plan close lifecycle."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plan_payload,
    assert_plan,
    create_plan, create_member, create_provider, submit_claim, adjudicate_claim,
    terminate_plan, set_clock,
)

ADMIN = TEST_USERS["tpa_admin_headers"]
EXAMINER = TEST_USERS["claims_examiner_headers"]


def test_create_plan_returns_201_active_with_echoed_deductible(api):
    """PRD 3.1: "A newly created plan begins in `ACTIVE` status, with `terminated_at` unset."
    PRD 2.4: "`version`: an integer that starts at its initial value and increments by one on every mutation of the resource."

    Design: Corner/entities/plan_creation_returns_201_with_echoed_fields
    """
    resp = api.create_plan(create_plan_payload(individual_deductible_cents=100000), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_plan(data)
    assert data["status"] == "ACTIVE", f"new plan must be ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"new plan version must be 1, got {data['version']}"
    assert data["individual_deductible_cents"] == 100000


def test_create_plan_missing_deductible_returns_validation(api):
    """PRD 2.7: "A malformed body (missing required field, wrong type or enum value,
    or a negative amount where a non-negative one is required) yields `ERR_VALIDATION` (HTTP 400)".

    Design: Corner/entities/plan_create_missing_deductible_returns_validation
    """
    payload = {
        "sponsor_name": "Acme", "sponsor_tax_id": "11-1111111",
        "plan_year_start": "2026-01-01", "plan_year_end": "2026-12-31",
        "oop_max_cents": 500000, "plan_coinsurance_pct": 0.80, "run_out_days": 90,
    }  # individual_deductible_cents deliberately omitted
    resp = api.create_plan(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_in_network_provider_defaults_ppo_discount_to_zero(api):
    """PRD 3.2: "In-network providers may carry a `ppo_discount_pct`, the repricing
    discount from 0 to 1 applied to their billed charges; when omitted it defaults to 0."
    PRD 3.4: "For an in-network provider, each line's allowed amount is the line's
    `billed_cents` multiplied by one minus the provider's `ppo_discount_pct`, rounded
    half-up to whole cents, and the `allowed_amount_cents` is the sum of those per-line
    rounded results — the rounding is applied to each line before summing, not to the total."

    Design: Corner/entities/provider_default_ppo_discount_zero_applied
    """
    plan = create_plan()
    # Provider created WITHOUT ppo_discount_pct so the server default (0) applies.
    resp_p = api.create_provider(
        {"name": "InNet", "tax_id": "22-2222222", "npi": "1111111111", "in_network": True}, ADMIN)
    provider = validate_success(resp_p, expected_status=201)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], provider["id"], billed_lines=[{"billed_cents": 100000}])
    adjudicate_claim(claim["id"])
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["allowed_amount_cents"] == 100000, (
        f"in-network with default 0 discount reprices to 100000, got {data['allowed_amount_cents']}")


def test_list_members_filtered_by_plan_returns_created_member(api):
    """PRD 3.2: "Members may be listed and filtered by `plan_id`."

    Design: Corner/endpoints/list_members_by_plan_reverse_reachability
    """
    plan = create_plan()
    member = create_member(plan["id"])
    resp = api.list_members(ADMIN, params={"plan_id": plan["id"]})
    data, meta = validate_paginated(resp)
    ids = [m["id"] for m in data]
    assert member["id"] in ids, f"member {member['id']} not found in {ids}"


def test_close_plan_before_runout_elapsed_returns_invalid_state(api):
    """PRD 3.1: "A close attempted while the plan is not `TERMINATED`, or while the
    run-out window has not yet elapsed, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_plan_before_runout_elapsed_returns_invalid_state
    """
    plan = create_plan()
    terminate_plan(plan["id"], "2026-03-31")
    set_clock("2026-05-01T00:00:00Z")  # run-out ends 2026-06-29, still open
    resp = api.close_plan(plan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_close_plan_after_runout_elapsed_succeeds(api):
    """PRD 3.1: "Closing a plan moves it from `TERMINATED` to the terminal `CLOSED`
    state, and is only permitted once the run-out window has fully elapsed — that is,
    when the current logical-clock time is strictly later than `terminated_at` plus
    `run_out_days` days."

    Design: Corner/state_machines/plan_close_after_runout_elapsed_succeeds
    """
    plan = create_plan()
    terminate_plan(plan["id"], "2026-03-31")
    set_clock("2026-08-01T00:00:00Z")  # past run-out (2026-06-29)
    data = validate_success(api.close_plan(plan["id"], ADMIN))
    assert data["status"] == "CLOSED", f"plan must be CLOSED, got {data['status']}"
