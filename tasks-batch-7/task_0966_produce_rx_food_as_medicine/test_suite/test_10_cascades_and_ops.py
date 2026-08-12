"""Cross-entity status cascades, cycle-close settlement, and the operations
run (PRD §2.9, §3.4, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_clinic_staff_headers,
    setup_enrollment, setup_active_program,
    setup_issued_voucher, setup_settled_redemption,
    create_clinic, create_patient_with_consent, create_referral,
    start_review, close_cycle, set_clock, get_pool, get_enrollment,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Depth instance: depth-3 funder-suspend cascade
# ---------------------------------------------------------------------------

def _suspend_single_funder(ctx):
    return validate_success(api_client.suspend_funder(ctx["funder"]["id"], ADMIN), 200)


def test_funder_suspend_suspends_pool_and_freezes_program(api):
    """PRD §2.9: "Suspending a funder moves each of that funder's FUNDED pools
    to SUSPENDED; each pool suspension, when it leaves its program with no
    remaining FUNDED pool, freezes the program to FROZEN; and the freeze in
    turn suspends every one of that program's enrollments currently in ACTIVE
    status."

    Design: Difficulty/transitive_cascade/funder_suspend_cascades_pool_program_enrollment
    """
    ctx = setup_enrollment()
    _suspend_single_funder(ctx)

    pool = get_pool(ctx["pool"]["id"])
    assert pool["status"] == "SUSPENDED"
    program = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert program["status"] == "FROZEN"


def test_funder_suspend_cascade_suspends_active_enrollment(api):
    """PRD §2.9: "Suspending a funder moves each of that funder's FUNDED pools
    to SUSPENDED; each pool suspension, when it leaves its program with no
    remaining FUNDED pool, freezes the program to FROZEN; and the freeze in
    turn suspends every one of that program's enrollments currently in ACTIVE
    status."

    Design: Difficulty/transitive_cascade/funder_suspend_cascades_pool_program_enrollment
    """
    ctx = setup_enrollment()
    _suspend_single_funder(ctx)

    enrollment = get_enrollment(ctx["enrollment_id"])
    assert enrollment["status"] == "SUSPENDED"

    program = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert program["status"] == "FROZEN"


# ---------------------------------------------------------------------------
# Depth instance: cycle close expires vouchers and releases reserves
# ---------------------------------------------------------------------------

def test_cycle_close_expires_issued_voucher(api):
    """PRD §3.4: "Closing a cycle — permitted only from OPEN, else
    `ERR_CYCLE_NOT_OPEN` — settles it: each voucher of the cycle still in
    ISSUED status is expired in `created_at` ascending order, moving to
    EXPIRED, and each expiry releases that voucher's `remaining_cents` from
    the pool's `reserved_cents` back into `available_cents`."

    Design: Difficulty/transitive_cascade/cycle_close_expires_voucher_and_releases_reserve
    """
    ctx = setup_settled_redemption()
    close_cycle(ctx["cycle"]["id"])

    voucher = validate_success(api.get_voucher(ctx["voucher_id"], ADMIN), 200)
    assert voucher["status"] == "EXPIRED"


def test_cycle_close_releases_reserve_to_available(api):
    """PRD §3.4: "each voucher of the cycle still in ISSUED status is expired
    in `created_at` ascending order, moving to EXPIRED, and each expiry
    releases that voucher's `remaining_cents` from the pool's `reserved_cents`
    back into `available_cents`."

    Design: Difficulty/transitive_cascade/cycle_close_expires_voucher_and_releases_reserve
    """
    # After the default redemption: reserved 9500, disbursed 3000,
    # available 487500; expiry of the voucher (remaining 9500) releases it.
    ctx = setup_settled_redemption()
    close_cycle(ctx["cycle"]["id"])

    pool = get_pool(ctx["pool"]["id"])
    assert pool["reserved_cents"] == 0
    assert pool["disbursed_cents"] == 3000
    assert pool["available_cents"] == 497000


# ---------------------------------------------------------------------------
# Operations run: referral expiry threshold
# ---------------------------------------------------------------------------

def test_run_ops_expires_stale_referral_and_increments_index(api):
    """PRD §3.9: "It increments the program's `ops_run_index` by one, expires
    referrals, and lapses disengaged enrollments. Referral expiry looks at
    every referral of the program in SUBMITTED or UNDER_REVIEW: one whose age
    — the current logical clock minus its `created_at` — is strictly greater
    than fourteen days moves to EXPIRED, while a referral exactly fourteen
    days old is not yet expired."

    Design: Corner/cross_cutting_complexity_layers/c_run_ops_increments_index_and_expires_stale_referral
    """
    ctx = setup_active_program()
    clinic = create_clinic()
    patient_a = create_patient_with_consent(clinic["id"], full_name="Pat A")
    # R1 created at the default logical clock 2026-05-01, left UNDER_REVIEW.
    referral1 = create_referral(clinic["id"], patient_a["id"],
                                ctx["program"]["id"])
    start_review(referral1["id"])

    set_clock("2026-05-20T00:00:00Z")
    patient_b = create_patient_with_consent(clinic["id"], full_name="Pat B",
                                            household_size=3)
    # R2 created at 2026-05-20 (age 0 at the ops run), left SUBMITTED.
    referral2 = create_referral(clinic["id"], patient_b["id"],
                                ctx["program"]["id"])

    result = validate_success(api.run_ops(ctx["program"]["id"], ADMIN), 200)
    assert result["ops_run_index"] == 1
    assert result["expired_referral_count"] == 1
    assert result["lapsed_enrollment_count"] == 0

    r1 = validate_success(api.get_referral(referral1["id"], ADMIN), 200)
    assert r1["status"] == "EXPIRED"  # age 19 days > 14
    r2 = validate_success(api.get_referral(referral2["id"], ADMIN), 200)
    assert r2["status"] == "SUBMITTED"  # age 0 days
