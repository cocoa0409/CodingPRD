"""State registration lifecycle: review cycle, expiry sweep, invalid transitions
(PRD §2.5, §2.10, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_state_registration,
    get_formula,
    get_registration,
    setup_registration,
    validate_error,
    validate_success,
)


def test_registration_approve_from_submitted_fails(api, state_regulator_headers):
    """PRD §3.7: "The approval decision — `UNDER_REVIEW` to `APPROVED` — carries
    the OCC field `expected_formula_version` per §2.7"
    PRD §2.10: "Fourth, transition validity: the requested action must correspond
    to a transition that exists from the resource's current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/registration_approve_from_submitted_fails
    """
    ctx = setup_registration(target_state="SUBMITTED", state_code="MN")
    version = get_formula(ctx["formula"]["id"])["version"]
    resp = api.approve_registration(
        ctx["registration"]["id"], {"expected_formula_version": version}, state_regulator_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_registration(ctx["registration"]["id"])["status"] == "SUBMITTED"


def test_registration_full_review_cycle_and_clock_expiry(
    api, platform_admin_headers, state_regulator_headers
):
    """PRD §3.7: "Submission stamps `submitted_at`, computes the `fee_cents` from
    the fee schedule, and lands the registration in `SUBMITTED`."
    PRD §3.7: "The annual registration fee is assessed in integer cents from a
    per-state base — 7500 cents for CA, 6000 cents for TX, 8000 cents for NY, and
    a default of 5000 cents for any other state — scaled by the declared tonnage
    tier."
    PRD §2.5: "advancing it past a registration's annual, state-specific expiry
    date drives that registration from `APPROVED` to `EXPIRED` as an automatic
    system transition"

    Design: Corner/state_machines/registration_full_review_cycle_and_clock_expiry
    """
    ctx = setup_registration(target_state="SUBMITTED", state_code="CA", tonnage_tier=3.0)
    registration = ctx["registration"]
    assert_state_registration(registration)
    assert registration["status"] == "SUBMITTED"
    assert registration["fee_cents"] == 7500
    assert registration["submitted_at"], "submission must stamp submitted_at"

    accepted = validate_success(
        api.accept_registration_for_review(registration["id"], state_regulator_headers)
    )
    assert accepted["status"] == "UNDER_REVIEW"

    version = get_formula(ctx["formula"]["id"])["version"]
    approved = validate_success(
        api.approve_registration(
            registration["id"], {"expected_formula_version": version}, state_regulator_headers
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_at"], "approval must stamp decided_at"

    validate_success(
        api.set_clock({"to_iso8601": "2027-09-01T00:00:00Z"}, platform_admin_headers)
    )
    expired = get_registration(registration["id"])
    assert expired["status"] == "EXPIRED"
