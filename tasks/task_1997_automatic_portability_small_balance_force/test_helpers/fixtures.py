"""Composite setup helpers for multi-step test prerequisites.

All fixtures build preconditions from scratch against a freshly restarted
server, using only PRD-declared endpoints. Setup calls use get_success_data()
so failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_participant_headers,
    make_provider_ops_headers,
    make_fiduciary_reviewer_headers,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base entity creation + simple state progression
# ---------------------------------------------------------------------------

def create_active_recordkeeper(code="RK-A", legal_name="Recordkeeper A"):
    """Create a recordkeeper and activate it. Returns the recordkeeper dict."""
    rk = get_success_data(api_client.create_recordkeeper(
        {"recordkeeper_code": code, "legal_name": legal_name}, OPS,
    ))
    return get_success_data(api_client.activate_recordkeeper(rk["id"], OPS))


def create_plan(recordkeeper_id, **overrides):
    """Create a plan with defaults plus overrides. Returns the plan dict."""
    payload = {
        "plan_name": "Plan X",
        "sponsor_ein": "11-1111111",
        "recordkeeper_id": recordkeeper_id,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_plan(payload, SPONSOR))


def create_participant(**overrides):
    """Create a participant. Returns the participant dict."""
    payload = {
        "ssn_hash": "hash-a",
        "full_name": "Ann A",
        "date_of_birth": "1980-01-01",
        "mailing_address_line1": "1 Main St",
        "mailing_city": "Springfield",
        "mailing_state": "IL",
        "mailing_zip": "62701",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_participant(payload, SPONSOR))


def create_open_batch(plan_id):
    """Open a distribution batch for a plan. Returns the batch dict."""
    return get_success_data(api_client.create_distribution_batch(
        {"plan_id": plan_id}, SPONSOR,
    ))


def create_case(batch_id, plan_id, participant_id,
                separation_date_balance_cents=50000,
                processing_date_balance_cents=50000,
                **overrides):
    """Attach a case to an OPEN batch. Returns the case dict."""
    payload = {
        "distribution_batch_id": batch_id,
        "plan_id": plan_id,
        "participant_id": participant_id,
        "separation_date": "2026-07-15T00:00:00Z",
        "separation_date_balance_cents": separation_date_balance_cents,
        "processing_date_balance_cents": processing_date_balance_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_distribution_case(payload, SPONSOR))


# ---------------------------------------------------------------------------
# Tier 2: batch with case(s), lock
# ---------------------------------------------------------------------------

def setup_locked_batch_one_case(balance=50000, participant_overrides=None,
                                plan_overrides=None):
    """Recordkeeper ACTIVE -> plan -> participant -> batch -> case -> lock.

    Returns dict with keys: rk, plan, participant, batch, case.
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"], **(plan_overrides or {}))
    participant = create_participant(**(participant_overrides or {}))
    batch = create_open_batch(plan["id"])
    case = create_case(batch["id"], plan["id"], participant["id"],
                       separation_date_balance_cents=balance,
                       processing_date_balance_cents=balance)
    get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
    batch = get_success_data(api_client.get_distribution_batch(batch["id"], OPS))
    return {"rk": rk, "plan": plan, "participant": participant,
            "batch": batch, "case": case}


# ---------------------------------------------------------------------------
# Tier 3: notice + election lifecycle shortcuts
# ---------------------------------------------------------------------------

def send_force_out_notice_and_deliver(case_id):
    """Create FORCE_OUT_ELECTION notice and record DELIVERED. Returns notice."""
    notice = get_success_data(api_client.create_notice(
        case_id, {"notice_type": "FORCE_OUT_ELECTION"}, OPS,
    ))
    get_success_data(api_client.record_notice_delivery(
        notice["id"], {"outcome": "DELIVERED"}, OPS,
    ))
    return get_success_data(api_client.get_notice(notice["id"], OPS))


def submit_election(case_id, participant_id, election_type, **overrides):
    """Participant submits an election at the case's current version.

    Re-reads the case to get the fresh version. Returns the election dict.
    """
    case = get_success_data(api_client.get_distribution_case(case_id, OPS))
    payload = {
        "election_type": election_type,
        "expected_case_version": case["version"],
    }
    payload.update(overrides)
    return get_success_data(api_client.create_election(
        case_id, payload, make_participant_headers(participant_id),
    ))


def setup_notified_case(balance=50000, **kwargs):
    """Locked batch with one case whose FORCE_OUT_ELECTION notice is DELIVERED.

    Returns dict: rk, plan, participant, batch, case, notice.
    Case is NOTIFIED with response_deadline = 2026-08-31T00:00:00.000Z.
    """
    ctx = setup_locked_batch_one_case(balance=balance, **kwargs)
    notice = send_force_out_notice_and_deliver(ctx["case"]["id"])
    case = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    ctx["notice"] = notice
    ctx["case"] = case
    return ctx


def setup_elected_case(balance=50000, election_type="SAFE_HARBOR_IRA", **kwargs):
    """Notified case plus a SUBMITTED election from the owning participant.

    Returns dict: rk, plan, participant, batch, case, notice, election.
    Case is ELECTED.
    """
    ctx = setup_notified_case(balance=balance, **kwargs)
    election = submit_election(
        ctx["case"]["id"], ctx["participant"]["id"], election_type,
    )
    case = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    ctx["election"] = election
    ctx["case"] = case
    return ctx


def setup_executed_batch_elected_ira(balance=300000):
    """Elected SAFE_HARBOR_IRA case; batch EXECUTED by ops_exec_1.

    Returns dict: rk, plan, participant, batch, case, notice, election.
    """
    ctx = setup_elected_case(balance=balance, election_type="SAFE_HARBOR_IRA")
    get_success_data(api_client.execute_distribution_batch(
        ctx["batch"]["id"], make_provider_ops_headers("ops_exec_1"),
    ))
    ctx["batch"] = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    return ctx


def setup_executed_batch_elected_cash(balance=100000, plan_overrides=None):
    """Elected LUMP_SUM_CASH case; batch EXECUTED by ops_exec_1.

    Returns dict: rk, plan, participant, batch, case, notice, election.
    """
    ctx = setup_elected_case(
        balance=balance, election_type="LUMP_SUM_CASH",
        plan_overrides=plan_overrides,
    )
    get_success_data(api_client.execute_distribution_batch(
        ctx["batch"]["id"], make_provider_ops_headers("ops_exec_1"),
    ))
    ctx["batch"] = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    return ctx


def setup_established_ira(balance=300000, fee_day_count_convention=None):
    """Full pipeline through IRA establishment.

    Returns dict: rk, plan, participant, batch, case, notice, election, ira.
    """
    ctx = setup_executed_batch_elected_ira(balance=balance)
    payload = {"distribution_case_id": ctx["case"]["id"]}
    if fee_day_count_convention is not None:
        payload["fee_day_count_convention"] = fee_day_count_convention
    ira = get_success_data(api_client.create_safe_harbor_ira(payload, OPS))
    ctx["ira"] = ira
    ctx["case"] = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    return ctx


def setup_ira_with_fee_disclosure(balance=300000, fee_day_count_convention=None):
    """Established IRA plus DELIVERED FEE_DISCLOSURE notice."""
    ctx = setup_established_ira(
        balance=balance, fee_day_count_convention=fee_day_count_convention,
    )
    notice = get_success_data(api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "FEE_DISCLOSURE"}, OPS,
    ))
    get_success_data(api_client.record_notice_delivery(
        notice["id"], {"outcome": "DELIVERED"}, OPS,
    ))
    ctx["fee_notice"] = get_success_data(api_client.get_notice(notice["id"], OPS))
    return ctx


def setup_auto_expired_case(balance=100000):
    """Auto-path case: NOTIFIED, window expired via sweep at 2026-08-31T00:00:01Z,
    batch EXECUTED. force_out_path determined by balance vs default thresholds.

    Returns dict: rk, plan, participant, batch, case, notice.
    """
    ctx = setup_notified_case(balance=balance)
    get_success_data(api_client.set_clock("2026-08-31T00:00:01Z", OPS))
    get_success_data(api_client.run_sweep(OPS))
    get_success_data(api_client.execute_distribution_batch(
        ctx["batch"]["id"], make_provider_ops_headers("ops_exec_1"),
    ))
    ctx["batch"] = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    ctx["case"] = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: match / transfer setup
# ---------------------------------------------------------------------------

def setup_second_active_recordkeeper_and_plan(code="RK-B", legal_name="Recordkeeper B",
                                              plan_name="Plan Y", ein="33-3333333",
                                              **plan_overrides):
    """Create a second ACTIVE recordkeeper and a plan on it."""
    rk_b = create_active_recordkeeper(code=code, legal_name=legal_name)
    plan_payload = {"plan_name": plan_name, "sponsor_ein": ein}
    plan_payload.update(plan_overrides)
    plan_y = create_plan(rk_b["id"], **plan_payload)
    return rk_b, plan_y


def setup_matched_ira(balance=300000, name_similarity=0.90, dob_match=True,
                      ssn_exact=True, advance_clock=None):
    """Established IRA plus an auto-confirmed match to plan Y at RK-B.

    Returns dict: all of setup_established_ira plus rk_b, plan_y, match.
    IRA is MATCHED.
    """
    ctx = setup_established_ira(balance=balance)
    rk_b, plan_y = setup_second_active_recordkeeper_and_plan()
    match = get_success_data(api_client.create_match_search(
        ctx["ira"]["id"],
        {
            "new_plan_id": plan_y["id"],
            "new_recordkeeper_id": rk_b["id"],
            "employment_start_date": "2026-08-10",
            "ssn_exact": ssn_exact,
            "name_similarity": name_similarity,
            "dob_match": dob_match,
        },
        OPS,
    ))
    if advance_clock is not None:
        get_success_data(api_client.set_clock(advance_clock, OPS))
    ctx["rk_b"] = rk_b
    ctx["plan_y"] = plan_y
    ctx["match"] = match
    ctx["ira"] = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
    return ctx


def setup_transfer_ready_ira(balance=300000, clock="2026-09-01T00:00:00Z"):
    """MATCHED IRA with AUTO_PORTABILITY_PRENOTICE delivered and its window elapsed.

    Prenotice is delivered at the default clock 2026-08-01 (deadline 2026-08-31);
    clock is then advanced to `clock` (default 2026-09-01, past the deadline).
    Returns dict including ira (fresh read) with current version.
    """
    ctx = setup_matched_ira(balance=balance)
    prenotice = get_success_data(api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "AUTO_PORTABILITY_PRENOTICE"}, OPS,
    ))
    get_success_data(api_client.record_notice_delivery(
        prenotice["id"], {"outcome": "DELIVERED"}, OPS,
    ))
    get_success_data(api_client.set_clock(clock, OPS))
    ctx["prenotice"] = get_success_data(api_client.get_notice(prenotice["id"], OPS))
    ctx["ira"] = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
    return ctx


def initiate_transfer(ira_id):
    """Initiate a transfer against the IRA's unique CONFIRMED match.

    Re-reads the IRA to get the current version. Returns the transfer dict.
    """
    ira = get_success_data(api_client.get_safe_harbor_ira(ira_id, OPS))
    return get_success_data(api_client.create_transfer(
        ira_id, {"expected_ira_version": ira["version"]}, OPS,
    ))


# ---------------------------------------------------------------------------
# Tier 5: reconciliation / review terminal states
# ---------------------------------------------------------------------------

def setup_reconciled_batch():
    """Batch with one elected-IRA case fully settled and reconciled.

    Returns dict: rk, plan, participant, batch, case, notice, election, ira.
    Batch is RECONCILED, executed_by_user_id == "ops_exec_1".
    """
    ctx = setup_executed_batch_elected_ira(balance=300000)
    ira = get_success_data(api_client.create_safe_harbor_ira(
        {"distribution_case_id": ctx["case"]["id"]}, OPS,
    ))
    get_success_data(api_client.reconcile_distribution_batch(ctx["batch"]["id"], OPS))
    ctx["ira"] = ira
    ctx["batch"] = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    return ctx


def setup_reviewed_batch(reviewer_id="fid_rev_1"):
    """Batch fully through REVIEWED via an attested fiduciary review."""
    ctx = setup_reconciled_batch()
    review = get_success_data(api_client.create_fiduciary_review(
        {
            "distribution_batch_id": ctx["batch"]["id"],
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-09-01T00:00:00Z",
        },
        make_fiduciary_reviewer_headers(reviewer_id),
    ))
    get_success_data(api_client.attest_review(
        review["id"], make_fiduciary_reviewer_headers(reviewer_id),
    ))
    ctx["review"] = get_success_data(
        api_client.get_fiduciary_review(review["id"], OPS))
    ctx["batch"] = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    return ctx
