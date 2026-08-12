"""Composite setup helpers.

Each helper drives the real API through PRD-declared endpoints and uses the
lenient get_success_data() validator so a broken precondition surfaces as a
clear "Setup failed" error. The test harness restarts the server (empty DB)
before every test, so every helper builds its world from scratch.

Identity threading: the Applicant role is entity-backed (PRD §2.1), so every
ownership-gated call is made with make_applicant_headers(applicant_id) using
the Applicant.id returned at registration. Lottery operators and certifying
officers use distinct opaque ids so the segregation rule of PRD §2.9 holds.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    COMPLIANCE_OFFICER_USER, LOTTERY_ADMIN_USER, MID_WINDOW, WINDOW_CLOSE,
)
from .factories import (
    create_ami_limit_payload, create_applicant_payload,
    create_application_payload, create_campaign_payload,
    create_compliance_report_payload, create_lottery_run_payload,
    create_occupancy_standard_payload, create_preference_claim_payload,
    create_property_payload, create_purge_run_payload, create_unit_payload,
    income_source,
)
from .test_users import (
    TEST_USERS, make_applicant_headers, make_application_clerk_headers,
    make_compliance_officer_headers, make_lottery_administrator_headers,
)

DEVELOPER = TEST_USERS["housing_developer_headers"]
MARKETING = TEST_USERS["marketing_coordinator_headers"]
CLERK = TEST_USERS["application_clerk_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
LOTTERY_ADMIN = TEST_USERS["lottery_administrator_headers"]
AUDITOR = TEST_USERS["funding_agency_auditor_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Low-level single-step helpers
# --------------------------------------------------------------------------
def set_clock(iso, api=api_client):
    return get_success_data(api.set_clock(iso, DEVELOPER))


def new_property(api=api_client, **over):
    return get_success_data(api.create_property(create_property_payload(**over),
                                                DEVELOPER))


def new_unit(api, property_id, **over):
    return get_success_data(
        api.create_unit(create_unit_payload(property_id, **over), DEVELOPER))


def new_occupancy_standard(api, property_id, **over):
    return get_success_data(api.create_occupancy_standard(
        create_occupancy_standard_payload(property_id, **over), DEVELOPER))


def new_ami_limit(api, property_id, **over):
    return get_success_data(api.create_ami_limit(
        create_ami_limit_payload(property_id, **over), DEVELOPER))


def get_property(api, property_id):
    return get_success_data(api.get_property(property_id, DEVELOPER))


def get_campaign(api, campaign_id):
    return get_success_data(api.get_campaign(campaign_id, DEVELOPER))


def campaign_version(api, campaign_id):
    return get_campaign(api, campaign_id)["version"]


def new_campaign(api, property_id, **over):
    """Create a DRAFT campaign."""
    return get_success_data(
        api.create_campaign(create_campaign_payload(property_id, **over),
                            DEVELOPER))


def campaign_action(api, campaign_id, action, headers, **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(
        api.transition_campaign(campaign_id, payload, headers))


def announce_campaign(api, campaign_id):
    return campaign_action(api, campaign_id, "ANNOUNCE", MARKETING)


def open_campaign(api, campaign_id):
    return campaign_action(api, campaign_id, "OPEN", DEVELOPER)


def close_campaign(api, campaign_id):
    return campaign_action(api, campaign_id, "CLOSE", DEVELOPER)


def close_campaign_at(api, campaign_id, when=WINDOW_CLOSE):
    """Advance the logical clock to the close instant and CLOSE the campaign."""
    set_clock(when, api)
    return close_campaign(api, campaign_id)


def new_open_campaign(api, property_id, open_clock=MID_WINDOW, **over):
    """Campaign -> ANNOUNCE -> (optional clock set) -> OPEN. Returns the OPEN
    campaign. open_clock=None leaves the logical clock untouched."""
    campaign = new_campaign(api, property_id, **over)
    announce_campaign(api, campaign["id"])
    if open_clock is not None:
        set_clock(open_clock, api)
    open_campaign(api, campaign["id"])
    return get_campaign(api, campaign["id"])


def new_applicant(api=api_client, **over):
    return get_success_data(
        api.create_applicant(create_applicant_payload(**over), ANONYMOUS))


def submit_application(api, campaign_id, applicant_id, **over):
    payload = create_application_payload(applicant_id, campaign_id, **over)
    return get_success_data(
        api.create_application(payload, make_applicant_headers(applicant_id)))


def review_action(api, application_id, action, headers, **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(
        api.review_application(application_id, payload, headers))


def verify_application(api, application_id, clerk_id="clerk-1"):
    """SUBMITTED -> UNDER_REVIEW -> VERIFIED (no PENDING claims assumed)."""
    clerk = make_application_clerk_headers(clerk_id)
    review_action(api, application_id, "BEGIN_REVIEW", clerk)
    return review_action(api, application_id, "COMPLETE_VERIFICATION", clerk)


def file_claim(api, application_id, applicant_id, category, evidence_ref):
    payload = create_preference_claim_payload(
        application_id, category=category, evidence_ref=evidence_ref)
    return get_success_data(
        api.create_preference_claim(payload,
                                    make_applicant_headers(applicant_id)))


def decide_claim(api, claim_id, action, clerk_id="clerk-1", **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(api.transition_preference_claim(
        claim_id, payload, make_application_clerk_headers(clerk_id)))


def new_verified_application(api, campaign_id, full_name="Test Applicant",
                             email=None, claims=(), **app_over):
    """Applicant + application + each claim in `claims` decided per its
    decision flag, then BEGIN_REVIEW + COMPLETE_VERIFICATION.

    claims: iterable of (category, evidence_ref, decision) where decision is
    "VERIFY" or "DENY"; DENY entries carry a fixed denial reason.
    Returns (applicant, application) with the application VERIFIED.
    """
    email = email or f"{full_name.replace(' ', '.').lower()}@example.com"
    applicant = new_applicant(api, full_name=full_name, email=email)
    application = submit_application(api, campaign_id, applicant["id"],
                                     **app_over)
    for category, evidence, decision in claims:
        claim = file_claim(api, application["id"], applicant["id"], category,
                           evidence)
        if decision == "VERIFY":
            decide_claim(api, claim["id"], "VERIFY")
        elif decision == "DENY":
            decide_claim(api, claim["id"], "DENY",
                         denial_reason="insufficient evidence")
    application = verify_application(api, application["id"])
    return applicant, application


def new_lottery_run(api, campaign_id, seed="SEED-1",
                    admin_user=LOTTERY_ADMIN_USER,
                    expected_campaign_version=None):
    """Create a DRAFT lottery run, reading the current campaign version for
    the optimistic-concurrency field when not given (PRD §2.6)."""
    if expected_campaign_version is None:
        expected_campaign_version = campaign_version(api, campaign_id)
    payload = create_lottery_run_payload(
        campaign_id, expected_campaign_version, seed=seed)
    return get_success_data(api.create_lottery_run(
        payload, make_lottery_administrator_headers(admin_user)))


def lottery_action(api, run_id, action, admin_user=LOTTERY_ADMIN_USER,
                   **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(api.transition_lottery_run(
        run_id, payload, make_lottery_administrator_headers(admin_user)))


def run_published_lottery(api, campaign_id, seed="SEED-1",
                          admin_user=LOTTERY_ADMIN_USER):
    """Create -> SEAL -> EXECUTE -> PUBLISH. Returns the PUBLISHED run."""
    run = new_lottery_run(api, campaign_id, seed=seed, admin_user=admin_user)
    lottery_action(api, run["id"], "SEAL", admin_user)
    lottery_action(api, run["id"], "EXECUTE", admin_user)
    lottery_action(api, run["id"], "PUBLISH", admin_user)
    return get_success_data(api.get_lottery_run(run["id"], LOTTERY_ADMIN))


def new_income_certification(api, application_id,
                             officer_id=COMPLIANCE_OFFICER_USER):
    return get_success_data(api.create_income_certification(
        {"application_id": application_id},
        make_compliance_officer_headers(officer_id)))


def advance_certification(api, cert_id, action, headers, **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(
        api.advance_income_certification(cert_id, payload, headers))


def certify_household_income(api, application_id, applicant_id, sources=None,
                             required_docs=("SALARY",),
                             officer_id=COMPLIANCE_OFFICER_USER):
    """Full documentation cycle: INITIATED -> DOCS_REQUESTED -> DOCS_RECEIVED
    -> CERTIFIED. Returns the CERTIFIED certification."""
    officer = make_compliance_officer_headers(officer_id)
    cert = new_income_certification(api, application_id, officer_id)
    advance_certification(api, cert["id"], "REQUEST_DOCS", officer,
                          required_docs=list(required_docs))
    advance_certification(api, cert["id"], "SUBMIT_DOCS",
                          make_applicant_headers(applicant_id),
                          income_sources=sources or [income_source()])
    return advance_certification(api, cert["id"], "CERTIFY", officer)


def generate_offers(api, campaign_id, admin_user=LOTTERY_ADMIN_USER):
    return get_success_data(api.generate_offers(
        {"campaign_id": campaign_id},
        make_lottery_administrator_headers(admin_user)))


def list_offers(api, campaign_id, status=None, headers=None, **params):
    query = {"campaign_id": campaign_id}
    if status:
        query["status"] = status
    query.update(params)
    return get_success_data(
        api.list_offers(headers or LOTTERY_ADMIN, params=query))


def list_entries(api, headers=None, **params):
    return get_success_data(
        api.list_waitlist_entries(headers or LOTTERY_ADMIN, params=params))


def get_entry_for_application(api, application_id):
    entries = list_entries(api, application_id=application_id)
    assert len(entries) == 1, f"expected one entry for {application_id}"
    return entries[0]


def get_pending_offer(api, campaign_id):
    offers = list_offers(api, campaign_id, status="PENDING")
    assert len(offers) == 1, f"expected one PENDING offer, got {len(offers)}"
    return offers[0]


def offer_owner_applicant_id(api, offer):
    """Resolve the owning Applicant.id behind an offer (entry -> application)."""
    entry = get_success_data(
        api.get_waitlist_entry(offer["entry_id"], LOTTERY_ADMIN))
    application = get_success_data(
        api.get_application(entry["application_id"], CLERK))
    return application["applicant_id"]


def decline_offer(api, offer):
    return get_success_data(api.respond_to_offer(
        offer["id"], {"action": "DECLINE"},
        make_applicant_headers(offer_owner_applicant_id(api, offer))))


def accept_offer(api, offer):
    return get_success_data(api.respond_to_offer(
        offer["id"], {"action": "ACCEPT"},
        make_applicant_headers(offer_owner_applicant_id(api, offer))))


def new_purge_run(api, campaign_id, notice_response_days=30,
                  expected_campaign_version=None):
    """Schedule a purge against a LEASING campaign, reading the current
    campaign version for the OCC field when not given (PRD §2.6)."""
    if expected_campaign_version is None:
        expected_campaign_version = campaign_version(api, campaign_id)
    payload = create_purge_run_payload(
        campaign_id, expected_campaign_version,
        notice_response_days=notice_response_days)
    return get_success_data(api.create_purge_run(payload, DEVELOPER))


def purge_action(api, purge_id, action):
    return get_success_data(
        api.advance_purge_run(purge_id, {"action": action}, DEVELOPER))


def new_report(api, campaign_id, officer_id=COMPLIANCE_OFFICER_USER, **over):
    payload = create_compliance_report_payload(campaign_id, **over)
    return get_success_data(api.create_compliance_report(
        payload, make_compliance_officer_headers(officer_id)))


def report_action(api, report_id, action, headers, **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(
        api.transition_compliance_report(report_id, payload, headers))


# --------------------------------------------------------------------------
# Composite pipelines
# --------------------------------------------------------------------------
def setup_property_with_units(api=api_client, num_units=1, occupancy=(1, 3),
                              ami_limits=None, unit_specs=None):
    """Property + ONE_BR occupancy standard + AMI limit rows + AVAILABLE units.

    ami_limits: iterable of (household_size, ami_tier, annual_limit_cents);
    defaults to the single (2, AMI_50, 4000000) row.
    unit_specs: iterable of create-unit overrides; defaults to num_units
    ONE_BR/AMI_50 units numbered 101, 102, ...
    Returns {"property": ..., "units": [...]}.
    """
    prop = new_property(api)
    if occupancy is not None:
        new_occupancy_standard(api, prop["id"], min_occupants=occupancy[0],
                               max_occupants=occupancy[1])
    for hh, tier, limit in (ami_limits
                            or [(2, "AMI_50", 4_000_000)]):
        new_ami_limit(api, prop["id"], household_size=hh, ami_tier=tier,
                      annual_limit_cents=limit)
    if unit_specs is None:
        unit_specs = [{"unit_number": f"10{i + 1}"} for i in range(num_units)]
    units = [new_unit(api, prop["id"], **spec) for spec in unit_specs]
    return {"property": prop, "units": units}


def setup_leasing_pipeline(api=api_client, applications=None, seed="SEED-1",
                           officer_id=COMPLIANCE_OFFICER_USER,
                           admin_user=LOTTERY_ADMIN_USER, certify=True,
                           close_at=WINDOW_CLOSE, **property_kwargs):
    """Full pipeline through a PUBLISHED lottery.

    property/units/config (setup_property_with_units)
    -> campaign ANNOUNCED, clock to mid-window, OPEN
    -> each application spec registered, claims decided, VERIFIED
    -> clock to close_at, CLOSE, lottery created/sealed/executed/published
    -> optionally each application taken through the full certification cycle

    applications: list of dicts with keys full_name/email and optional
    claims list and application overrides; defaults to a single household of
    2 with self-reported income 3000000 and no claims.

    Returns dict(property, units, campaign, run, applicants, applications,
    certs).
    """
    world = setup_property_with_units(api, **property_kwargs)
    campaign = new_open_campaign(api, world["property"]["id"])
    if applications is None:
        applications = [{"full_name": "Test Applicant"}]
    applicants, applications_out = [], []
    for spec in applications:
        spec = dict(spec)
        claims = spec.pop("claims", ())
        applicant, application = new_verified_application(
            api, campaign["id"], claims=claims, **spec)
        applicants.append(applicant)
        applications_out.append(application)
    close_campaign_at(api, campaign["id"], when=close_at)
    run = run_published_lottery(api, campaign["id"], seed=seed,
                                admin_user=admin_user)
    certs = []
    if certify:
        for applicant, application in zip(applicants, applications_out):
            certs.append(certify_household_income(
                api, application["id"], applicant["id"],
                officer_id=officer_id))
    return {
        "property": world["property"],
        "units": world["units"],
        "campaign": get_campaign(api, campaign["id"]),
        "run": run,
        "applicants": applicants,
        "applications": applications_out,
        "certs": certs,
    }


def setup_leasing_with_pending_offer(api=api_client, **kwargs):
    """Leasing pipeline + one generate batch. Adds "offers" (PENDING list)
    and "generation" (the batch response) to the world dict."""
    world = setup_leasing_pipeline(api, **kwargs)
    world["generation"] = generate_offers(api, world["campaign"]["id"])
    world["offers"] = list_offers(api, world["campaign"]["id"],
                                  status="PENDING")
    return world


def setup_purge_notices_sent(api=api_client, notice_days=30, seed="SEED-PURGE",
                             applications=None, **kwargs):
    """Leasing pipeline where every generated offer is declined (entries back
    to RANKED), then a purge run is scheduled and notices are sent.
    Returns the world dict with "purge" added."""
    world = setup_leasing_with_pending_offer(api, seed=seed,
                                             applications=applications,
                                             **kwargs)
    for offer in world["offers"]:
        decline_offer(api, offer)
    purge = new_purge_run(api, world["campaign"]["id"],
                          notice_response_days=notice_days)
    purge_action(api, purge["id"], "SEND_NOTICES")
    world["purge"] = get_success_data(api.get_purge_run(purge["id"], DEVELOPER))
    world["campaign"] = get_campaign(api, world["campaign"]["id"])
    return world
