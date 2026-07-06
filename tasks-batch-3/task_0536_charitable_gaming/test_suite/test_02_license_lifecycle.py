"""License lifecycle: submit/approve/suspend/reinstate, invalid transitions, prize limit."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_orgofficer_headers,
    create_organization, create_draft_license, create_active_license,
    create_submitted_license,
)

REGULATOR = TEST_USERS["regulator_headers"]


# ─── Difficulty: License ACTIVE -> SUSPENDED -> ACTIVE cycle ──────────
def test_suspend_active_license(api):
    """PRD §3.2: "A `Regulator` may suspend an `ACTIVE` license, advancing it from `ACTIVE`
    to `SUSPENDED` (permitted only from `ACTIVE`, else `ERR_INVALID_STATE`)."

    Design: Difficulty/non_linear_state_machine/license_active_suspended_active_cycle
    """
    org, lic = create_active_license()
    suspended = validate_success(api.suspend_license(lic["id"], REGULATOR), 200)
    assert suspended["status"] == "SUSPENDED"


def test_reinstate_returns_license_to_active(api):
    """PRD §3.2: "A `Regulator` may reinstate a suspended license, advancing it from
    `SUSPENDED` back to `ACTIVE`; this requires the license to be `SUSPENDED` (else
    `ERR_INVALID_STATE`) and requires `total_violation_points_active` to be below the
    suspension threshold of 10 points (else `ERR_OUTSTANDING_VIOLATIONS`)."

    Design: Difficulty/non_linear_state_machine/license_active_suspended_active_cycle
    """
    org, lic = create_active_license()
    validate_success(api.suspend_license(lic["id"], REGULATOR), 200)
    reinstated = validate_success(api.reinstate_license(lic["id"], REGULATOR), 200)
    assert reinstated["status"] == "ACTIVE"


# ─── Corner: invalid license transitions ─────────────────────────────
def test_approve_draft_license_invalid_state(api):
    """PRD §3.2: "Approval requires the license to be in `SUBMITTED` (else
    `ERR_INVALID_STATE`) and requires the owning organization's `eligibility_status` to be
    `ELIGIBLE` at the moment of approval (else `ERR_ORG_NOT_ELIGIBLE`)."

    Design: Corner/state_machines/approve_draft_license_returns_invalid_state
    """
    org = create_organization()
    lic = create_draft_license(org["id"])
    res = api.approve_license(lic["id"], REGULATOR)
    validate_error(res, "ERR_INVALID_STATE")
    fetched = validate_success(api.get_license(lic["id"], make_orgofficer_headers(org["id"])), 200)
    assert fetched["status"] == "DRAFT"


def test_submit_twice_invalid_state(api):
    """PRD §3.2: "Submitting a license for review advances it from `DRAFT` to `SUBMITTED`;
    this is permitted only while the license is in `DRAFT`, otherwise the request is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/submit_twice_returns_invalid_state
    """
    org, lic = create_submitted_license()
    res = api.submit_license(lic["id"], make_orgofficer_headers(org["id"]))
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: annual prize limit fixed by license_type ────────────────
def test_annual_prize_limit_raffle(api):
    """PRD §3.2: "At creation its `annual_prize_limit_cents` is fixed from the license type
    — 1,000,000 cents for `BINGO`, 2,000,000 cents for `RAFFLE`, and 3,000,000 cents for
    `COMBINED` — and its prize ledgers `prize_committed_cents` and `prize_settled_cents`
    both start at zero."
    PRD §3.5: "The `prize_allowance_remaining_cents` is `annual_prize_limit_cents` minus
    `prize_committed_cents` minus `prize_settled_cents`."

    Design: Corner/calculations/annual_prize_limit_by_type_raffle
    """
    org, lic = create_active_license(license_type="RAFFLE")
    assert lic["annual_prize_limit_cents"] == 2_000_000
    assert lic["prize_allowance_remaining_cents"] == 2_000_000
