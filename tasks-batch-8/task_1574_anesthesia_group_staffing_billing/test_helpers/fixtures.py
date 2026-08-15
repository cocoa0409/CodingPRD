"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Fixtures use get_success_data() internally
so setup failures surface as clear "Setup failed" errors.

Identity threading: after creating a Provider, ownership-gated calls (accept,
decline, attestation submit) always use make_physician_headers(provider["id"])
or make_crna_headers(provider["id"]) — never the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    all_tefra_steps_true,
    create_call_assignment_payload,
    create_case_payload,
    create_fee_schedule_payload,
    create_physician_payload,
    create_provider_payload,
    create_roster_payload,
    create_site_payload,
    create_stipend_agreement_payload,
)
from .test_users import TEST_USERS, make_crna_headers, make_physician_headers

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation / state progression
# ---------------------------------------------------------------------------

def create_site(name=TEST_DEFAULTS["SITE_NAME"]):
    resp = api_client.create_site(create_site_payload(name=name), ADMIN)
    return get_success_data(resp)


def create_fee_schedule(code=TEST_DEFAULTS["PROCEDURE_CODE"], base_units=5,
                        contracted_max_cents=TEST_DEFAULTS["FEE_CONTRACTED_MAX_CENTS"]):
    resp = api_client.create_fee_schedule(
        create_fee_schedule_payload(procedure_code=code, base_units=base_units,
                                    contracted_max_cents=contracted_max_cents), ADMIN)
    return get_success_data(resp)


def create_physician(name="Dr. Avery", expiry=TEST_DEFAULTS["CREDENTIAL_EXPIRES_ON"],
                     dea=None):
    resp = api_client.create_provider(
        create_physician_payload(full_name=name, credential_expires_on=expiry,
                                 dea_expires_on=dea or expiry), ADMIN)
    return get_success_data(resp)


def create_crna(name="Crna One", expiry=TEST_DEFAULTS["CREDENTIAL_EXPIRES_ON"], dea=None):
    resp = api_client.create_provider(
        create_provider_payload(full_name=name, provider_type="CRNA",
                                credential_expires_on=expiry,
                                dea_expires_on=dea or expiry), ADMIN)
    return get_success_data(resp)


def create_provider(provider_type, name, expiry=TEST_DEFAULTS["CREDENTIAL_EXPIRES_ON"],
                    dea=None):
    resp = api_client.create_provider(
        create_provider_payload(full_name=name, provider_type=provider_type,
                                credential_expires_on=expiry,
                                dea_expires_on=dea or expiry), ADMIN)
    return get_success_data(resp)


def create_roster(site_id, service_date=TEST_DEFAULTS["SERVICE_DATE"],
                  required_primary_slots=1,
                  scheduled_day_end_minute=TEST_DEFAULTS["SCHEDULED_DAY_END_MINUTE"]):
    resp = api_client.create_roster(
        create_roster_payload(site_id=site_id, service_date=service_date,
                              required_primary_slots=required_primary_slots,
                              scheduled_day_end_minute=scheduled_day_end_minute), SCHED)
    return get_success_data(resp)


def create_published_roster(site_id, **kwargs):
    roster = create_roster(site_id, **kwargs)
    resp = api_client.publish_roster(roster["id"], SCHED)
    return get_success_data(resp)


def create_case(roster_id, procedure_code=TEST_DEFAULTS["PROCEDURE_CODE"],
                physical_status="P1", emergency_flag=None,
                scheduled_start_minute=540, scheduled_end_minute=600):
    payload = create_case_payload(
        roster_id=roster_id, procedure_code=procedure_code,
        physical_status=physical_status,
        scheduled_start_minute=scheduled_start_minute,
        scheduled_end_minute=scheduled_end_minute)
    if emergency_flag is not None:
        payload["emergency_flag"] = emergency_flag
    resp = api_client.create_case(payload, SCHED)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def propose_assignment(case_id, provider_id, role="CASE_PRIMARY"):
    """Propose an assignment, re-reading the case version for OCC. Returns the
    created PROPOSED assignment."""
    case = get_success_data(api_client.get_case(case_id, SCHED))
    resp = api_client.create_case_assignment(
        case_id, {"provider_id": provider_id, "assignment_role": role,
                  "expected_case_version": case["version"]}, SCHED)
    return get_success_data(resp)


def accept_assignment(assignment_id, provider_id, provider_type):
    """Accept as the owning provider (entity-backed identity threading)."""
    headers = (make_physician_headers(provider_id)
               if provider_type == "ANESTHESIOLOGIST" else make_crna_headers(provider_id))
    resp = api_client.accept_assignment(assignment_id, headers)
    return get_success_data(resp)


def propose_and_confirm(case_id, provider_id, provider_type, role="CASE_PRIMARY"):
    assignment = propose_assignment(case_id, provider_id, role)
    return accept_assignment(assignment["id"], provider_id, provider_type)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — site + fee + roster (+ providers)
# ---------------------------------------------------------------------------

def setup_site_fee_roster(procedure_code=TEST_DEFAULTS["PROCEDURE_CODE"], base_units=5,
                          contracted_max_cents=TEST_DEFAULTS["FEE_CONTRACTED_MAX_CENTS"],
                          service_date=TEST_DEFAULTS["SERVICE_DATE"],
                          required_primary_slots=1,
                          scheduled_day_end_minute=TEST_DEFAULTS["SCHEDULED_DAY_END_MINUTE"],
                          publish=True):
    """Site + fee schedule + roster (PUBLISHED unless publish=False).
    Returns (site, fee, roster)."""
    site = create_site()
    fee = create_fee_schedule(procedure_code, base_units, contracted_max_cents)
    if publish:
        roster = create_published_roster(
            site["id"], service_date=service_date,
            required_primary_slots=required_primary_slots,
            scheduled_day_end_minute=scheduled_day_end_minute)
    else:
        roster = create_roster(
            site["id"], service_date=service_date,
            required_primary_slots=required_primary_slots,
            scheduled_day_end_minute=scheduled_day_end_minute)
    return site, fee, roster


def setup_case_with_confirmed_primary(provider_type="ANESTHESIOLOGIST",
                                      procedure_code=TEST_DEFAULTS["PROCEDURE_CODE"],
                                      base_units=5,
                                      physical_status="P1", emergency_flag=None,
                                      scheduled_start_minute=540,
                                      scheduled_end_minute=600,
                                      service_date=TEST_DEFAULTS["SERVICE_DATE"],
                                      required_primary_slots=1,
                                      scheduled_day_end_minute=TEST_DEFAULTS[
                                          "SCHEDULED_DAY_END_MINUTE"],
                                      contracted_max_cents=TEST_DEFAULTS[
                                          "FEE_CONTRACTED_MAX_CENTS"]):
    """Site + fee + PUBLISHED roster + case + CONFIRMED CASE_PRIMARY.
    Returns dict with site, fee, roster, case, provider, primary assignment."""
    site, fee, roster = setup_site_fee_roster(
        procedure_code=procedure_code, base_units=base_units,
        contracted_max_cents=contracted_max_cents, service_date=service_date,
        required_primary_slots=required_primary_slots,
        scheduled_day_end_minute=scheduled_day_end_minute)
    provider = create_provider(provider_type,
                               "Dr. Avery" if provider_type == "ANESTHESIOLOGIST"
                               else "Crna One")
    case = create_case(roster["id"], procedure_code=procedure_code,
                       physical_status=physical_status, emergency_flag=emergency_flag,
                       scheduled_start_minute=scheduled_start_minute,
                       scheduled_end_minute=scheduled_end_minute)
    primary = propose_and_confirm(case["id"], provider["id"], provider_type)
    return {"site": site, "fee": fee, "roster": roster, "case": case,
            "provider": provider, "primary": primary}


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def run_case_clock(case_id, start_iso, end_iso=None):
    """Set clock to start_iso, start the case; optionally set clock to end_iso.
    Returns the started case."""
    set_clock(start_iso)
    started = get_success_data(api_client.start_case(case_id, SCHED))
    if end_iso is not None:
        set_clock(end_iso)
    return started


def complete_case_at(case_id, start_iso, end_iso):
    """Start at start_iso, complete at end_iso. Returns the completed case."""
    run_case_clock(case_id, start_iso, end_iso)
    return get_success_data(api_client.complete_case(case_id, SCHED))


def setup_completed_solo_case(provider_type="ANESTHESIOLOGIST",
                              procedure_code=TEST_DEFAULTS["PROCEDURE_CODE"],
                              base_units=5,
                              physical_status="P1", emergency_flag=None,
                              scheduled_start_minute=540,
                              scheduled_end_minute=600,
                              start_iso="2026-08-10T09:00:00Z",
                              end_iso="2026-08-10T10:00:00Z",
                              scheduled_day_end_minute=TEST_DEFAULTS[
                                  "SCHEDULED_DAY_END_MINUTE"],
                              contracted_max_cents=TEST_DEFAULTS[
                                  "FEE_CONTRACTED_MAX_CENTS"],
                              service_date=TEST_DEFAULTS["SERVICE_DATE"]):
    """Full chain through a COMPLETED case with one CONFIRMED primary (no
    directing). Returns ctx dict + 'completed' case + 'claims' list."""
    ctx = setup_case_with_confirmed_primary(
        provider_type=provider_type, procedure_code=procedure_code,
        base_units=base_units, physical_status=physical_status,
        emergency_flag=emergency_flag,
        scheduled_start_minute=scheduled_start_minute,
        scheduled_end_minute=scheduled_end_minute,
        scheduled_day_end_minute=scheduled_day_end_minute,
        contracted_max_cents=contracted_max_cents, service_date=service_date)
    completed = complete_case_at(ctx["case"]["id"], start_iso, end_iso)
    ctx["completed"] = completed
    claims = get_success_data(
        api_client.list_claims(SCHED, params={"case_id": ctx["case"]["id"]}))
    ctx["claims"] = claims if isinstance(claims, list) else claims.get("data", [])
    return ctx


def setup_locked_roster_with_ready_claim(**kwargs):
    """Completed solo case + roster LOCKED + claim marked READY.
    Returns ctx with 'claim' (the READY claim)."""
    ctx = setup_completed_solo_case(**kwargs)
    claim = ctx["claims"][0]
    get_success_data(api_client.lock_roster(ctx["roster"]["id"], SCHED))
    ready = get_success_data(api_client.mark_claim_ready(claim["id"], BILLING))
    ctx["claim"] = ready
    return ctx


def setup_directed_case(verify_attestation=True, base_units=5,
                        procedure_code=TEST_DEFAULTS["PROCEDURE_CODE"],
                        physical_status="P1",
                        scheduled_start_minute=540, scheduled_end_minute=660,
                        scheduled_day_end_minute=1200,
                        primary_type="CRNA",
                        roster=None, site=None):
    """Case with CONFIRMED CRNA primary + CONFIRMED directing physician;
    optionally a VERIFIED attestation. Returns ctx dict."""
    if site is None:
        site = create_site()
    create_fee_schedule(procedure_code, base_units)
    if roster is None:
        roster = create_published_roster(
            site["id"], required_primary_slots=1,
            scheduled_day_end_minute=scheduled_day_end_minute)
    director = create_physician("Dr. Direct")
    peer = create_physician("Dr. Peer")
    primary = create_provider(primary_type, "Crna One")
    case = create_case(roster["id"], procedure_code=procedure_code,
                       physical_status=physical_status,
                       scheduled_start_minute=scheduled_start_minute,
                       scheduled_end_minute=scheduled_end_minute)
    prim_asg = propose_and_confirm(case["id"], primary["id"], primary_type,
                                   "CASE_PRIMARY")
    dir_asg = propose_and_confirm(case["id"], director["id"], "ANESTHESIOLOGIST",
                                  "CASE_DIRECTING")
    attestation = None
    if verify_attestation:
        att = get_success_data(api_client.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        get_success_data(api_client.submit_attestation(
            att["id"], all_tefra_steps_true(), make_physician_headers(director["id"])))
        attestation = get_success_data(api_client.verify_attestation(
            att["id"], make_physician_headers(peer["id"])))
    return {"site": site, "roster": roster, "case": case, "director": director,
            "peer": peer, "primary": primary, "primary_assignment": prim_asg,
            "directing_assignment": dir_asg, "attestation": attestation}


def create_and_submit_attestation(case_id, physician_id, peer_id):
    """Create attestation (as Scheduler) and submit it as the physician.
    Returns the SUBMITTED attestation."""
    att = get_success_data(api_client.create_attestation(
        {"case_id": case_id, "physician_id": physician_id}, SCHED))
    return get_success_data(api_client.submit_attestation(
        att["id"], all_tefra_steps_true(), make_physician_headers(physician_id)))


# ---------------------------------------------------------------------------
# Tier 4: stipend scenarios
# ---------------------------------------------------------------------------

def create_stipend_agreement(site_id, effective_from=TEST_DEFAULTS["SERVICE_DATE"],
                             effective_to=TEST_DEFAULTS["SERVICE_DATE"],
                             call_stipend_cents=12000,
                             late_stay_rate_cents_per_minute=50,
                             standby_full_cents=30000,
                             standby_partial_cents=15000):
    resp = api_client.create_stipend_agreement(
        create_stipend_agreement_payload(
            site_id=site_id, effective_from=effective_from, effective_to=effective_to,
            call_stipend_cents=call_stipend_cents,
            late_stay_rate_cents_per_minute=late_stay_rate_cents_per_minute,
            standby_full_cents=standby_full_cents,
            standby_partial_cents=standby_partial_cents), ADMIN)
    return get_success_data(resp)


def setup_stipend_site(agreement_kwargs=None, roster_kwargs=None):
    """Site + stipend agreement + PUBLISHED roster. Returns (site, agreement,
    roster)."""
    site = create_site()
    agreement = create_stipend_agreement(site["id"], **(agreement_kwargs or {}))
    roster = create_published_roster(site["id"], **(roster_kwargs or {}))
    return site, agreement, roster


def list_stipend_entries(params, headers=None):
    data = get_success_data(
        api_client.list_stipend_entries(headers or SCHED, params=params))
    return data if isinstance(data, list) else data.get("data", [])


def list_claims(params, headers=None):
    data = get_success_data(api_client.list_claims(headers or SCHED, params=params))
    return data if isinstance(data, list) else data.get("data", [])


def list_audits(params, headers=None):
    data = get_success_data(api_client.list_audits(headers or AUDITOR, params=params))
    return data if isinstance(data, list) else data.get("data", [])


def list_findings(params, headers=None):
    data = get_success_data(api_client.list_findings(headers or AUDITOR, params=params))
    return data if isinstance(data, list) else data.get("data", [])


def list_assignments(params, headers=None):
    data = get_success_data(api_client.list_assignments(headers or SCHED, params=params))
    return data if isinstance(data, list) else data.get("data", [])


def list_cases(params, headers=None):
    data = get_success_data(api_client.list_cases(headers or SCHED, params=params))
    return data if isinstance(data, list) else data.get("data", [])


# ---------------------------------------------------------------------------
# Tier 5: credential-lapse audit fixtures
# ---------------------------------------------------------------------------

def setup_credential_lapse_audit(num_cases=1, provider_expiry="2026-08-15",
                                 shortened_expiry="2026-08-08",
                                 service_date=TEST_DEFAULTS["SERVICE_DATE"]):
    """Provider with expiry valid at assignment time, PROPOSED primary on
    num_cases cases, then credentials shortened -> CREDENTIAL_LAPSE findings on
    an auto-created OPEN audit. Returns ctx with provider, roster, cases,
    assignments, audit."""
    site, fee, roster = setup_site_fee_roster(
        service_date=service_date, required_primary_slots=max(1, num_cases),
        scheduled_day_end_minute=1200)
    provider = create_crna("Crna Three", expiry=provider_expiry)
    cases, assignments = [], []
    start = 600
    for _ in range(num_cases):
        case = create_case(roster["id"], scheduled_start_minute=start,
                           scheduled_end_minute=start + 60)
        asg = propose_assignment(case["id"], provider["id"], "CASE_PRIMARY")
        cases.append(case)
        assignments.append(asg)
        start += 100
    patched = get_success_data(api_client.update_provider_credentials(
        provider["id"],
        {"credential_expires_on": shortened_expiry, "dea_expires_on": shortened_expiry,
         "expected_provider_version": provider["version"]}, ADMIN))
    audits = list_audits({"roster_id": roster["id"]})
    return {"site": site, "fee": fee, "roster": roster, "provider": provider,
            "patched_provider": patched, "cases": cases, "assignments": assignments,
            "audit": audits[0] if audits else None}
