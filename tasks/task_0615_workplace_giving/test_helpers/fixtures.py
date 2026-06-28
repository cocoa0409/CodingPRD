"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly-restarted, empty server, so each fixture builds its full
precondition chain from scratch using only PRD-declared endpoints. Fixtures use the lenient
get_success_data() validator so a setup failure surfaces clearly.

Identity threading: the Employee role is entity_backed, so ownership-gated Employee calls use
make_employee_headers(emp_id). GivingAdmin / ProgramManager are opaque.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_program_payload,
    create_employee_payload,
    create_charity_payload,
    create_campaign_payload,
    create_donation_payload,
    create_payroll_schedule_payload,
    create_volunteer_log_payload,
    create_disbursement_batch_payload,
    stage_grant_payload,
)
from .test_users import TEST_USERS, make_employee_headers
from .constants import YEAR_WINDOW_START, YEAR_WINDOW_END

PM = TEST_USERS["program_manager_headers"]
GA = TEST_USERS["giving_admin_headers"]


# ─── Clock control ──────────────────────────────────────────────────────────
def set_clock(to_iso8601):
    """Set the server logical clock (GivingAdmin is authorized)."""
    return get_success_data(api_client.set_clock(to_iso8601, GA))


# ─── Tier 1: single-entity state progression ────────────────────────────────
def create_program(**overrides):
    """Create a DRAFT program. Returns the program dict."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides), PM))


def create_active_program(**overrides):
    """Create a program and activate it (DRAFT -> ACTIVE). Returns the activated program."""
    prog = create_program(**overrides)
    return get_success_data(api_client.activate_program(prog["id"], PM))


def create_approved_charity(program_id, **overrides):
    """Submit a charity and vet it through SUBMITTED -> UNDER_REVIEW -> APPROVED."""
    charity = get_success_data(
        api_client.create_charity(create_charity_payload(program_id, **overrides), GA)
    )
    api_client.start_review_charity(charity["id"], GA)
    return get_success_data(api_client.approve_charity(charity["id"], GA))


def create_employee(program_id, **overrides):
    """Enroll an ACTIVE employee. Returns the employee dict."""
    return get_success_data(
        api_client.create_employee(create_employee_payload(program_id, **overrides), GA)
    )


def create_live_campaign(program_id, charity_id, **overrides):
    """Create a campaign and launch it (DRAFT -> LIVE). Charity must be APPROVED first."""
    camp = get_success_data(
        api_client.create_campaign(create_campaign_payload(program_id, charity_id, **overrides), PM)
    )
    return get_success_data(api_client.launch_campaign(camp["id"], PM))


# ─── Tier 2: base giving scenario (program + charity + employee + campaign) ──
def setup_giving_scenario(program_overrides=None, charity_overrides=None,
                          employee_overrides=None, campaign_overrides=None):
    """Active program + approved charity + active employee + live campaign.

    Returns dict: {program, charity, employee, campaign}.
    """
    program = create_active_program(**(program_overrides or {}))
    charity = create_approved_charity(program["id"], **(charity_overrides or {}))
    employee = create_employee(program["id"], **(employee_overrides or {}))
    campaign = create_live_campaign(program["id"], charity["id"], **(campaign_overrides or {}))
    return {
        "program": program,
        "charity": charity,
        "employee": employee,
        "campaign": campaign,
    }


# ─── Tier 3: donation lifecycle shortcuts ───────────────────────────────────
def create_pledged_donation(scenario, **donation_overrides):
    """Pledge one donation in a giving scenario. Returns the donation dict."""
    payload = create_donation_payload(
        scenario["program"]["id"],
        scenario["employee"]["id"],
        scenario["campaign"]["id"],
        **donation_overrides,
    )
    return get_success_data(api_client.create_donation(payload, GA))


def create_authorized_donation(scenario, **donation_overrides):
    """Pledge + authorize one donation (PLEDGED -> AUTHORIZED). Returns the donation dict."""
    don = create_pledged_donation(scenario, **donation_overrides)
    return get_success_data(api_client.authorize_donation(don["id"], GA))


def create_settled_donation(scenario, **donation_overrides):
    """Pledge + authorize + settle one donation (-> SETTLED). Returns the donation dict."""
    don = create_pledged_donation(scenario, **donation_overrides)
    api_client.authorize_donation(don["id"], GA)
    return get_success_data(api_client.settle_donation(don["id"], GA))


def get_matching_gift_for_donation(donation_id):
    """Return the MatchingGift dict linked to a donation, or None."""
    data, _meta = _list(api_client.list_matching_gifts(GA, params={"donation_id": donation_id}))
    return data[0] if data else None


def _list(response):
    """Helper for list endpoints: return (data_list, meta)."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 3b: volunteer log lifecycle ───────────────────────────────────────
def create_logged_volunteer_log(scenario, **log_overrides):
    """Create a LOGGED volunteer log against the scenario's approved charity."""
    payload = create_volunteer_log_payload(
        scenario["program"]["id"],
        scenario["employee"]["id"],
        scenario["charity"]["id"],
        **log_overrides,
    )
    return get_success_data(api_client.create_volunteer_log(payload, GA))


def create_approved_volunteer_log(scenario, **log_overrides):
    """Create + approve a volunteer log (LOGGED -> APPROVED, computes the DfD grant)."""
    log = create_logged_volunteer_log(scenario, **log_overrides)
    return get_success_data(api_client.approve_volunteer_log(log["id"], GA))


# ─── Tier 4: disbursement batch / grant staging ─────────────────────────────
def create_open_batch(program_id, charity_id, **overrides):
    """Open a disbursement batch (status OPEN, version 1). Returns the batch dict."""
    return get_success_data(
        api_client.create_disbursement_batch(
            create_disbursement_batch_payload(program_id, charity_id, **overrides), GA
        )
    )


def stage_grant(batch_id, source_type, source_id, expected_batch_version):
    """Stage one grant into a batch (OCC-guarded). Returns the staged grant dict."""
    return get_success_data(
        api_client.stage_grant(
            batch_id,
            stage_grant_payload(source_type, source_id, expected_batch_version),
            GA,
        )
    )


def setup_batch_with_donation_grants(scenario, base_amounts, period_start=None, period_end=None):
    """Settle one donation per base amount, then stage each as a DONATION grant into one OPEN batch.

    Returns dict: {batch, grants (list), donations (list)}. The batch is left OPEN (not locked).
    Grants are staged in base_amounts order; the OCC version is threaded from each stage response.
    """
    donations = []
    for amt in base_amounts:
        donations.append(create_settled_donation(scenario, base_amount_cents=amt))

    batch_kwargs = {}
    if period_start is not None:
        batch_kwargs["period_start"] = period_start
    if period_end is not None:
        batch_kwargs["period_end"] = period_end
    batch = create_open_batch(scenario["program"]["id"], scenario["charity"]["id"], **batch_kwargs)

    version = batch["version"]
    grants = []
    for don in donations:
        grant_resp = api_client.stage_grant(
            batch["id"], stage_grant_payload("DONATION", don["id"], version), GA
        )
        grant_data = get_success_data(grant_resp)
        grants.append(grant_data)
        # Re-read the batch to get its live (advanced) version for the next OCC stage; the
        # grant's own version field is not the batch version.
        batch = get_success_data(api_client.get_disbursement_batch(batch["id"], GA))
        version = batch["version"]
    return {"batch": batch, "grants": grants, "donations": donations}


def lock_batch(batch_id):
    """Lock an OPEN batch with >= 1 staged grant (OPEN -> LOCKED). Returns the batch dict."""
    return get_success_data(api_client.lock_disbursement_batch(batch_id, GA))


# ─── Tier 5: full disbursement-settled lifecycle ────────────────────────────
def setup_locked_match_batch(scenario, base_amount_cents=40000, period_start=None, period_end=None):
    """Build a LOCKED batch holding one MATCH-source grant.

    Settles a request_match donation so its MatchingGift is FINALIZED, opens a batch, stages the
    MATCH grant, and locks it. Returns dict:
    {batch, grant, matching_gift, donation}. The batch is LOCKED, ready to settle.
    """
    donation = create_settled_donation(scenario, base_amount_cents=base_amount_cents, request_match=True)
    mg = get_matching_gift_for_donation(donation["id"])
    batch_kwargs = {}
    if period_start is not None:
        batch_kwargs["period_start"] = period_start
    if period_end is not None:
        batch_kwargs["period_end"] = period_end
    batch = create_open_batch(scenario["program"]["id"], scenario["charity"]["id"], **batch_kwargs)
    grant = stage_grant(batch["id"], "MATCH", mg["id"], batch["version"])
    locked = lock_batch(batch["id"])
    return {"batch": locked, "grant": grant, "matching_gift": mg, "donation": donation}


# ─── Tier 6: payroll schedule helpers ───────────────────────────────────────
def create_active_schedule(scenario, **overrides):
    """Create an ACTIVE payroll schedule for the scenario employee/campaign."""
    payload = create_payroll_schedule_payload(
        scenario["program"]["id"],
        scenario["employee"]["id"],
        scenario["campaign"]["id"],
        **overrides,
    )
    return get_success_data(api_client.create_payroll_schedule(payload, GA))


def run_cycle(schedule_id):
    """Run one cycle on an ACTIVE schedule (self-loop). Returns the new Donation dict."""
    return get_success_data(api_client.run_cycle_payroll_schedule(schedule_id, GA))
