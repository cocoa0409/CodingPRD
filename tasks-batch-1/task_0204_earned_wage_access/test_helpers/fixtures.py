"""Composite setup helpers for the Earned Wage Access API.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of each test. Setup calls use the
lenient get_success_data() so a broken precondition surfaces as a clear "Setup failed".

Segregation of duties (PRD §2.8): the advance approver/disburser uses the operator id
'officer-approver'; the repayment-batch poster uses the distinct id 'officer-poster';
the statement signer / write-off actor uses the distinct ComplianceOfficer id
'compliance-signer'. These three identities are kept separate so SoD checks pass on the
happy path.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_employer_payload,
    create_advance_policy_payload,
    create_fee_schedule_payload,
    create_pay_period_payload,
    create_worker_payload,
    create_time_entry_payload,
    create_advance_payload,
    create_repayment_batch_payload,
    create_reconciliation_statement_payload,
)
from .test_users import (
    TEST_USERS,
    make_payroll_officer_headers,
    make_compliance_officer_headers,
)
from .constants import CLOCK_BASE


ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["payroll_officer_headers"]          # approver/disburser (officer-approver)
POSTER = TEST_USERS["payroll_poster_headers"]            # batch poster (officer-poster)
SIGNER = TEST_USERS["compliance_officer_headers"]        # signer/write-off (compliance-signer)


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Pin the deterministic server clock (PRD §3.12)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 / 2: Base provisioning
# ---------------------------------------------------------------------------
def create_employer(clock=CLOCK_BASE, **overrides):
    """Set the clock to `clock` (if given) then create an employer. Returns the employer dict."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.create_employer(create_employer_payload(**overrides), ADMIN))


def create_standard_policy(employer_id, **overrides):
    return get_success_data(
        api_client.create_advance_policy(create_advance_policy_payload(employer_id, **overrides), ADMIN)
    )


def create_fee_schedule(employer_id, **overrides):
    return get_success_data(
        api_client.create_fee_schedule(create_fee_schedule_payload(employer_id, **overrides), ADMIN)
    )


def create_pay_period(employer_id, **overrides):
    return get_success_data(
        api_client.create_pay_period(create_pay_period_payload(employer_id, **overrides), OFFICER)
    )


def create_worker(employer_id, **overrides):
    return get_success_data(
        api_client.create_worker(create_worker_payload(employer_id, **overrides), OFFICER)
    )


def post_time_entry(pay_period_id, worker_id, shift_start_at, shift_end_at, hours_worked, **overrides):
    return get_success_data(
        api_client.create_time_entry(
            create_time_entry_payload(pay_period_id, worker_id, shift_start_at,
                                      shift_end_at, hours_worked, **overrides),
            OFFICER,
        )
    )


def setup_employer_with_policy_and_fees(clock=CLOCK_BASE, employer_overrides=None,
                                        policy_overrides=None, fee_overrides=None):
    """Active employer + STANDARD advance policy + fee schedule. Returns (employer, policy, fee)."""
    employer = create_employer(clock=clock, **(employer_overrides or {}))
    policy = create_standard_policy(employer["id"], **(policy_overrides or {}))
    fee = create_fee_schedule(employer["id"], **(fee_overrides or {}))
    return employer, policy, fee


def setup_base_scenario(clock=CLOCK_BASE, employer_overrides=None, policy_overrides=None,
                        fee_overrides=None, period_overrides=None, worker_overrides=None):
    """Full base: employer + policy + fee schedule + OPEN pay period + worker.
    Returns (employer, policy, fee, period, worker)."""
    employer, policy, fee = setup_employer_with_policy_and_fees(
        clock=clock, employer_overrides=employer_overrides,
        policy_overrides=policy_overrides, fee_overrides=fee_overrides,
    )
    period = create_pay_period(employer["id"], **(period_overrides or {}))
    worker = create_worker(employer["id"], **(worker_overrides or {}))
    return employer, policy, fee, period, worker


# ---------------------------------------------------------------------------
# Tier 4: Earnings accumulation
# ---------------------------------------------------------------------------
def post_shifts_for_gross_80000(period_id, worker_id):
    """Three POSTED shifts (16h + 16h + 8h = 40h @ 2000c = gross 80000 => accessible 40000).
    Shifts respect the 30-minute rest buffer between closed intervals."""
    post_time_entry(period_id, worker_id, "2026-06-02T08:00:00Z", "2026-06-03T00:00:00Z", 16.0)
    post_time_entry(period_id, worker_id, "2026-06-03T08:00:00Z", "2026-06-04T00:00:00Z", 16.0)
    post_time_entry(period_id, worker_id, "2026-06-04T08:00:00Z", "2026-06-04T16:00:00Z", 8.0)


def post_shift_6h_gross_12000(period_id, worker_id):
    """One POSTED 6h shift @ 2000c = gross 12000 => accessible 6000."""
    post_time_entry(period_id, worker_id, "2026-06-02T08:00:00Z", "2026-06-02T14:00:00Z", 6.0)


def post_shift_10h_gross_20000(period_id, worker_id):
    """One POSTED 10h shift @ 2000c = gross 20000 => accessible 10000."""
    post_time_entry(period_id, worker_id, "2026-06-02T08:00:00Z", "2026-06-02T18:00:00Z", 10.0)


def get_worker_version(worker_id):
    """Read the worker and return its current version (for the OCC guard on advance create)."""
    return get_success_data(api_client.get_worker(worker_id, OFFICER))["version"]


# ---------------------------------------------------------------------------
# Tier 3: Advance lifecycle shortcuts
# ---------------------------------------------------------------------------
def request_advance(worker_id, period_id, requested_principal_cents, expected_worker_version=None,
                    headers=None, **overrides):
    """Create (REQUESTED) an advance. If expected_worker_version is None, reads the live version."""
    if expected_worker_version is None:
        expected_worker_version = get_worker_version(worker_id)
    payload = create_advance_payload(worker_id, period_id, requested_principal_cents,
                                     expected_worker_version, **overrides)
    return get_success_data(api_client.create_advance(payload, headers or OFFICER))


def request_and_approve_advance(worker_id, period_id, requested_principal_cents, **overrides):
    """Create + approve an advance (REQUESTED -> APPROVED). Returns the approved advance."""
    adv = request_advance(worker_id, period_id, requested_principal_cents, **overrides)
    return get_success_data(api_client.approve_advance(adv["id"], OFFICER))


def request_approve_disburse_advance(worker_id, period_id, requested_principal_cents, **overrides):
    """Create + approve + disburse (REQUESTED -> APPROVED -> DISBURSED). Returns disbursed advance."""
    adv = request_and_approve_advance(worker_id, period_id, requested_principal_cents, **overrides)
    return get_success_data(api_client.disburse_advance(adv["id"], OFFICER))


# ---------------------------------------------------------------------------
# Batch / payday helpers
# ---------------------------------------------------------------------------
def open_batch(period_id):
    return get_success_data(api_client.create_repayment_batch(create_repayment_batch_payload(period_id), OFFICER))


def post_batch(batch_id, headers=None):
    """Post a batch with a fresh OCC version. Default poster is the distinct 'officer-poster'
    identity (SoD vs the 'officer-approver' approver)."""
    version = get_success_data(api_client.get_repayment_batch(batch_id, OFFICER))["version"]
    return get_success_data(
        api_client.post_repayment_batch(batch_id, {"expected_repaymentbatch_version": version},
                                        headers or POSTER)
    )


def lock_period(period_id):
    return get_success_data(api_client.lock_pay_period(period_id, OFFICER))


def run_payday(period_id):
    return get_success_data(api_client.run_payday(period_id, OFFICER))


def lock_and_post_batch(period_id):
    """Lock the period, open a DRAFT batch, and post it. Returns the posted batch."""
    lock_period(period_id)
    batch = open_batch(period_id)
    return post_batch(batch["id"])


# ---------------------------------------------------------------------------
# Tier 5: Terminal-state / cascade composites
# ---------------------------------------------------------------------------
def setup_disbursed_instant_advance_6000(employer_overrides=None):
    """Base scenario + 6h shift (gross 12000) + one INSTANT advance principal 6000
    (fee 199 + round(6000*0.02)=120 => 319; recoup_target 6319) approved and disbursed.
    Returns (employer, period, worker, advance)."""
    employer, _policy, _fee, period, worker = setup_base_scenario(employer_overrides=employer_overrides)
    post_shift_6h_gross_12000(period["id"], worker["id"])
    adv = request_approve_disburse_advance(worker["id"], period["id"], 6000,
                                           disbursement_speed="INSTANT")
    return employer, period, worker, adv


def setup_defaulted_advance_319():
    """Drive one INSTANT advance (rt 6319) to DEFAULTED with 319 outstanding via payday.

    Worker gross 12000 => per-worker recoup cap floor(12000*0.5)=6000. The batch recoups
    6000 (fee 319 first, then 5681 principal), leaving 319 outstanding; run-payday then
    defaults the advance. Returns (employer, period, worker, advance) with advance DEFAULTED.
    """
    employer, period, worker, adv = setup_disbursed_instant_advance_6000()
    lock_and_post_batch(period["id"])
    run_payday(period["id"])
    return employer, period, worker, adv


def setup_defaulted_with_draft_statement_319():
    """As setup_defaulted_advance_319, plus a DRAFT reconciliation statement created post-payday
    (drift 319, outcome DISCREPANCY; employer posture FROZEN).
    Returns (employer, period, worker, advance, statement)."""
    employer, period, worker, adv = setup_defaulted_advance_319()
    stmt = get_success_data(
        api_client.create_reconciliation_statement(
            create_reconciliation_statement_payload(period["id"]), SIGNER)
    )
    return employer, period, worker, adv, stmt


def setup_settled_full_recoup_advance_12000():
    """Base scenario + 40h shifts (gross 80000, cap 40000) + STANDARD advance principal 12000
    (rt 12000) disbursed, then a posted batch that fully recoups it (12000 <= cap 40000) so the
    advance reaches SETTLED and the funding pool is credited back.
    Returns (employer, period, worker, advance, batch)."""
    employer, _policy, _fee, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    adv = request_approve_disburse_advance(worker["id"], period["id"], 12000,
                                           disbursement_speed="STANDARD")
    lock_period(period["id"])
    batch = open_batch(period["id"])
    posted = post_batch(batch["id"])
    return employer, period, worker, adv, posted


def setup_worker_on_hold_via_writeoff():
    """Produce a worker that is ON_HOLD because an advance was WRITTEN_OFF, while the employer
    posture is NOT frozen (its only DISCREPANCY period was cleared by write-off + a SIGNED clean
    statement). A second pay period (pp2) is opened with fresh earnings and a fresh REQUESTED
    advance against the worker.

    Returns (employer, pp1, pp2, worker, adv1_written_off, adv2_requested).
    """
    employer, _policy, _fee, pp1, worker = setup_base_scenario()
    post_shift_6h_gross_12000(pp1["id"], worker["id"])
    adv1 = request_approve_disburse_advance(worker["id"], pp1["id"], 6000,
                                            disbursement_speed="INSTANT")
    lock_and_post_batch(pp1["id"])
    run_payday(pp1["id"])
    # adv1 is now DEFAULTED with 319 outstanding; write it off (sustains the hold).
    get_success_data(api_client.write_off_advance(adv1["id"], SIGNER))
    # Write-off subtracts 319 from expected => statement CLEAN; sign it to lift FROZEN.
    stmt1 = get_success_data(
        api_client.create_reconciliation_statement(
            create_reconciliation_statement_payload(pp1["id"]), SIGNER))
    get_success_data(api_client.sign_reconciliation_statement(stmt1["id"], SIGNER))
    # Second period (abutting) with fresh earnings and a fresh REQUESTED advance.
    set_clock("2026-06-03T00:00:00Z")
    pp2 = create_pay_period(employer["id"], start_at="2026-06-08T00:00:00Z",
                            end_at="2026-06-15T00:00:00Z")
    post_time_entry(pp2["id"], worker["id"], "2026-06-09T08:00:00Z",
                    "2026-06-09T14:00:00Z", 6.0)
    adv2 = request_advance(worker["id"], pp2["id"], 2000, disbursement_speed="STANDARD")
    return employer, pp1, pp2, worker, adv1, adv2
