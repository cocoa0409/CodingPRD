"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database (the harness restarts the server
before each test), so every precondition is built here from PRD-declared
endpoints only. Setup calls use get_success_data() so failures surface as
clear "Setup step failed" errors rather than confusing assertion failures.

Segregation-of-duties convention (PRD §2.9): certificates are uploaded by
u_co1 and reviewed/approved by u_co2; audit campaigns are opened by u_aud1.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_campaign_payload,
    create_certificate_payload,
    create_certificate_version_payload,
    create_customer_payload,
    create_exemption_reason_payload,
    create_jurisdiction_rule_payload,
    create_order_line_payload,
    create_order_payload,
    create_outreach_campaign_payload,
    create_remediation_action_payload,
    create_tenant_payload,
)
from .test_users import TEST_USERS, USER_IDS

ADMIN = TEST_USERS["tenant_admin_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
AUD1 = TEST_USERS["auditor_headers"]
AUD2 = TEST_USERS["auditor_2_headers"]
CLERK = TEST_USERS["order_clerk_headers"]
FULFILL = TEST_USERS["fulfillment_clerk_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ─── Tier 0: single-resource creation ────────────────────────────────────────

def create_tenant(**overrides):
    """Create a Tenant. Returns the tenant (clock day 0, posture CLEAR)."""
    return get_success_data(api_client.create_tenant(create_tenant_payload(**overrides), ADMIN))


def add_jurisdiction_rule(tid, **overrides):
    return get_success_data(api_client.create_jurisdiction_rule(
        tid, create_jurisdiction_rule_payload(**overrides), ADMIN))


def add_exemption_reason(tid, **overrides):
    return get_success_data(api_client.create_exemption_reason(
        tid, create_exemption_reason_payload(**overrides), ADMIN))


def setup_tenant_config(rule_specs=None, reason_overrides=None, tenant_overrides=None):
    """Tenant + one jurisdiction rule per rule_specs entry + one exemption reason.

    rule_specs: list of kwargs dicts for add_jurisdiction_rule; default one CA rule
    that accepts RESALE and never expires (validity_window_days=0).
    Returns the tenant dict.
    """
    tenant = create_tenant(**(tenant_overrides or {}))
    for spec in (rule_specs if rule_specs is not None else [{"state_code": "CA"}]):
        add_jurisdiction_rule(tenant["id"], **spec)
    add_exemption_reason(tid=tenant["id"], **(reason_overrides or {}))
    return tenant


def create_customer(tid, **overrides):
    """Create a Customer (onboarding NOT completed). Returns the customer."""
    return get_success_data(api_client.create_customer(
        tid, create_customer_payload(**overrides), CO1))


def create_onboarded_customer(tid, **overrides):
    """Create a Customer and complete onboarding (PRD §3.2). Returns the customer."""
    cust = create_customer(tid, **overrides)
    return get_success_data(api_client.complete_onboarding(tid, cust["id"], CO1))


# ─── Version readers (OCC endpoints need the parent's current version) ───────

def get_customer_version(tid, customer_id) -> int:
    return get_success_data(api_client.get_customer(tid, customer_id, CO1))["version"]


def get_campaign_version(tid, campaign_id) -> int:
    return get_success_data(api_client.get_audit_campaign(tid, campaign_id, AUD1))["version"]


def advance_days(tid, days):
    """Advance the tenant logical clock (PRD §2.4). Returns the updated tenant."""
    return get_success_data(api_client.advance_day(tid, {"days": days}, ADMIN))


# ─── Tier 1: certificate lifecycle ───────────────────────────────────────────

def create_certificate_draft(tid, customer_id, uploader_headers=None, **overrides):
    """Create an ExemptionCertificate in DRAFT (no version uploaded)."""
    uploader = uploader_headers or CO1
    return get_success_data(api_client.create_certificate(
        tid, customer_id, create_certificate_payload(**overrides), uploader))


def upload_version(tid, cert_id, uploader_headers=None, **overrides):
    uploader = uploader_headers or CO1
    return get_success_data(api_client.upload_certificate_version(
        tid, cert_id, create_certificate_version_payload(**overrides), uploader))


def drive_certificate_to_under_review(tid, customer_id, uploader_headers=None,
                                      reviewer_headers=None, cert_overrides=None,
                                      version_overrides=None):
    """Create cert -> upload version -> submit -> begin_review.

    Uploader and reviewer are distinct users (PRD §2.9 reviewer-vs-uploader rule).
    Returns the certificate now in UNDER_REVIEW.
    """
    uploader = uploader_headers or CO1
    reviewer = reviewer_headers or CO2
    cert = create_certificate_draft(tid, customer_id, uploader_headers=uploader,
                                    **(cert_overrides or {}))
    upload_version(tid, cert["id"], uploader_headers=uploader, **(version_overrides or {}))
    get_success_data(api_client.submit_certificate(tid, cert["id"], uploader))
    return get_success_data(api_client.begin_review_certificate(tid, cert["id"], reviewer))


def create_approved_certificate(tid, customer_id, uploader_headers=None, reviewer_headers=None,
                                cert_overrides=None, version_overrides=None):
    """Full review flow through APPROVED. Reads the customer's current version
    immediately before approving (PRD §2.8 optimistic concurrency on Customer).
    Returns the APPROVED certificate."""
    reviewer = reviewer_headers or CO2
    cert = drive_certificate_to_under_review(
        tid, customer_id,
        uploader_headers=uploader_headers, reviewer_headers=reviewer,
        cert_overrides=cert_overrides, version_overrides=version_overrides)
    cust_version = get_customer_version(tid, customer_id)
    return get_success_data(api_client.approve_certificate(
        tid, cert["id"], {"expected_customer_version": cust_version}, reviewer))


def setup_customer_with_approved_cert(state="CA", validity_window_days=0,
                                      anchor_rule="EFFECTIVE_DATE",
                                      signed_date="2026-01-01", effective_date="2026-01-01"):
    """Tenant + jurisdiction rule + reason + onboarded customer + one APPROVED cert.
    Returns (tenant, customer, cert)."""
    tenant = setup_tenant_config(rule_specs=[{
        "state_code": state,
        "validity_window_days": validity_window_days,
        "anchor_rule": anchor_rule,
    }])
    cust = create_onboarded_customer(tid=tenant["id"], primary_ship_to_state=state)
    cert = create_approved_certificate(
        tenant["id"], cust["id"],
        cert_overrides={"ship_to_state": state, "signed_date": signed_date,
                        "effective_date": effective_date},
        version_overrides={"signed_date": signed_date, "effective_date": effective_date})
    return tenant, cust, cert


# ─── Tier 2: orders ──────────────────────────────────────────────────────────

def create_order_with_lines(tid, customer_id, lines, **order_overrides):
    """Create a DRAFT order and add lines. `lines` is a list of
    (sku, quantity, unit_price_cents, is_exempt_claimed) tuples.
    Returns the order re-read after line additions."""
    order = get_success_data(api_client.create_order(
        tid, customer_id, create_order_payload(**order_overrides), CLERK))
    for sku, qty, price, exempt in lines:
        get_success_data(api_client.add_order_line(
            tid, order["id"],
            create_order_line_payload(sku=sku, quantity=qty,
                                      unit_price_cents=price, is_exempt_claimed=exempt),
            CLERK))
    return get_success_data(api_client.get_order(tid, order["id"], CLERK))


def submit_order(tid, order_id):
    return get_success_data(api_client.submit_order(tid, order_id, CLERK))


def create_held_order(tid, customer_id, lines=(("ABC-1", 1, 5000, True),), **order_overrides):
    """Order submitted with no matching approved certificate -> HELD_FOR_CERT."""
    order = create_order_with_lines(tid, customer_id, lines, **order_overrides)
    return submit_order(tid, order["id"])


def setup_blocked_exposure_scenario(big_line_cents):
    """Engineer customer.blocked_exposure_cents == big_line_cents while a second
    order sits in READY_TO_SHIP (PRD §3.5 shipping-gate tests).

    Layout: a big CA order submitted with no CA certificate lands HELD_FOR_CERT
    (uncovered == big_line_cents); an approved TX certificate then lets a 1-cent
    TX order land READY_TO_SHIP (its EX-prefixed SKU is fully covered under either
    coverage mode per PRD §3.5). The CA order's state does not match the TX
    certificate, so it stays HELD and blocked exposure stays at big_line_cents.
    """
    tenant = setup_tenant_config(rule_specs=[{"state_code": "CA"}, {"state_code": "TX"}])
    cust = create_onboarded_customer(tid=tenant["id"], primary_ship_to_state="CA")
    big = create_held_order(tenant["id"], cust["id"],
                            lines=(("BIG-1", 1, big_line_cents, True),),
                            order_ref="O-big", ship_to_state="CA")
    cert_tx = create_approved_certificate(tenant["id"], cust["id"],
                                          cert_overrides={"ship_to_state": "TX"})
    small = create_order_with_lines(tenant["id"], cust["id"],
                                    (("EX-SMALL", 1, 1, True),),
                                    order_ref="O-small", ship_to_state="TX")
    small = submit_order(tenant["id"], small["id"])
    return {"tenant": tenant, "customer": cust, "big_order": big,
            "small_order": small, "cert_tx": cert_tx}


# ─── Tier 3: audit campaigns, samples, remediation ───────────────────────────

def create_campaign(tid, opener_headers=None, **overrides):
    opener = opener_headers or AUD1
    return get_success_data(api_client.create_audit_campaign(
        tid, create_audit_campaign_payload(**overrides), opener))


def open_campaign_with_samples(tid, opener_headers=None, **campaign_overrides):
    """Create + open + draw samples. Returns (campaign, samples_list).

    Population control: callers arrange exactly the intended APPROVED-cert
    population before calling (PRD §3.8 population definition)."""
    opener = opener_headers or AUD1
    camp = create_campaign(tid, opener_headers=opener, **campaign_overrides)
    get_success_data(api_client.open_audit_campaign(tid, camp["id"], opener))
    get_success_data(api_client.sample_audit_campaign(tid, camp["id"], opener))
    samples = get_success_data(api_client.list_audit_samples(tid, camp["id"], opener))
    return camp, samples


def request_and_receive_docs(tid, sample_id):
    """PENDING -> DOC_REQUESTED -> DOC_RECEIVED. Returns the updated sample."""
    get_success_data(api_client.request_docs(tid, sample_id, AUD1))
    return get_success_data(api_client.receive_docs(tid, sample_id, CO1))


def fail_sample(tid, sample_id, failure_reason="documentation inadequate"):
    return get_success_data(api_client.fail_sample(
        tid, sample_id, {"failure_reason": failure_reason}, AUD1))


def create_manual_remediation(tid, sample_id, action_type="WAIVE_SAMPLE",
                              assigned_to_user_id=None, assessment_amount_cents=None):
    """Auditor-created remediation action (PRD §3.9). The assignee is an explicit
    input, which keeps the assignee-only begin rule exercisable."""
    overrides = {"action_type": action_type,
                 "assigned_to_user_id": assigned_to_user_id or USER_IDS["COMPLIANCE_OFFICER"]}
    if assessment_amount_cents is not None:
        overrides["assessment_amount_cents"] = assessment_amount_cents
    return get_success_data(api_client.create_remediation_action(
        tid, sample_id, create_remediation_action_payload(**overrides), AUD1))


def begin_remediation(tid, action_id, user_headers=None):
    return get_success_data(api_client.begin_remediation_action(
        tid, action_id, user_headers or CO1))


def resolve_remediation(tid, campaign_id, action_id, user_headers=None):
    """Begin is assumed done; reads the campaign's current version immediately
    before resolving (PRD §2.8 optimistic concurrency on AuditCampaign)."""
    headers = user_headers or CO1
    camp_v = get_campaign_version(tid, campaign_id)
    return get_success_data(api_client.resolve_remediation_action(
        tid, action_id, {"expected_campaign_version": camp_v}, headers))


def setup_campaign_with_failed_sample(state="CA", failure_reason="missing signature"):
    """Customer with one APPROVED cert; campaign sampled it; the single sample is
    driven DOC_RECEIVED -> FAILED, so the campaign auto-transitions to REMEDIATION
    (PRD §3.8) and a COLLECT_NEW_CERT remediation is auto-created.

    Returns dict(tenant, customer, cert, campaign, sample, actions).
    """
    tenant, cust, cert = setup_customer_with_approved_cert(state=state)
    camp, samples = open_campaign_with_samples(tid=tenant["id"],
                                               population_state_filter=[state],
                                               floor_sample_size=1)
    sample = samples[0]
    request_and_receive_docs(tenant["id"], sample["id"])
    failed = fail_sample(tenant["id"], sample["id"], failure_reason)
    actions = get_success_data(api_client.list_remediation_actions(tenant["id"], sample["id"], AUD1))
    return {"tenant": tenant, "customer": cust, "cert": cert, "campaign": camp,
            "sample": failed, "actions": actions}


def setup_passed_campaign(state="CA"):
    """One customer + approved cert; campaign floor=1; sample PASSED so the
    campaign reaches REMEDIATION with zero FAILED samples.
    Returns dict(tenant, customer, cert, campaign, sample)."""
    tenant, cust, cert = setup_customer_with_approved_cert(state=state)
    camp, samples = open_campaign_with_samples(tid=tenant["id"],
                                               population_state_filter=[state],
                                               floor_sample_size=1)
    sample = samples[0]
    request_and_receive_docs(tenant["id"], sample["id"])
    get_success_data(api_client.pass_sample(tenant["id"], sample["id"], AUD1))
    return {"tenant": tenant, "customer": cust, "cert": cert,
            "campaign": camp, "sample": sample}


def get_defense_packet_id(tid, campaign_id):
    """The packet is one-to-one with its campaign; retrieval returns an array of
    zero or one element (PRD §3.9)."""
    data = get_success_data(api_client.get_defense_packet(tid, campaign_id, AUD1))
    assert len(data) == 1, f"Setup expected exactly one defense packet, got {len(data)}"
    return data[0]["id"]


def setup_campaign_in_defense_assembly(state="CA"):
    """All-PASSED campaign moved REMEDIATION -> DEFENSE_ASSEMBLY; its defense
    packet exists in DRAFT. Returns dict(tenant, customer, cert, campaign, sample, packet_id)."""
    bundle = setup_passed_campaign(state=state)
    tid = bundle["tenant"]["id"]
    get_success_data(api_client.begin_defense_assembly(tid, bundle["campaign"]["id"], AUD1))
    bundle["packet_id"] = get_defense_packet_id(tid, bundle["campaign"]["id"])
    return bundle


def setup_delivered_packet_campaign(state="CA"):
    """Full pipeline through packet DELIVERED (PRD §3.9).
    Returns dict(tenant, customer, cert, campaign, sample, packet_id)."""
    bundle = setup_campaign_in_defense_assembly(state=state)
    tid = bundle["tenant"]["id"]
    get_success_data(api_client.assemble_defense_packet(tid, bundle["packet_id"], AUD1))
    get_success_data(api_client.deliver_defense_packet(tid, bundle["packet_id"], AUD1))
    return bundle


# ─── Tier 4: population / threshold targeting ────────────────────────────────

def setup_population_tenant(customer_count, state="CA"):
    """Tenant with `customer_count` customers, each holding one APPROVED
    never-expiring certificate for `state` — an audit population of exactly
    `customer_count` (PRD §3.8). Each certificate's SKUs/dates are identical."""
    tenant = setup_tenant_config(rule_specs=[{"state_code": state, "validity_window_days": 0}])
    for i in range(customer_count):
        cust = create_onboarded_customer(
            tid=tenant["id"], external_ref=f"C{i + 1:02d}",
            legal_name=f"Cust {i + 1:02d}", primary_ship_to_state=state)
        create_approved_certificate(tenant["id"], cust["id"],
                                    cert_overrides={"ship_to_state": state},
                                    version_overrides={"file_uri": f"s3://c{i + 1:02d}.pdf"})
    return tenant


def setup_outreach_scenario(validity_window_days=365, effective_date="2026-08-01"):
    """Tenant + customer with one APPROVED CA certificate expiring
    `validity_window_days` after `effective_date`. Returns (tenant, customer, cert)."""
    return setup_customer_with_approved_cert(
        state="CA", validity_window_days=validity_window_days,
        signed_date=effective_date, effective_date=effective_date)


def create_scheduled_outreach_campaign(tid, **overrides):
    """Create + schedule an outreach campaign (DRAFT -> SCHEDULED)."""
    camp = get_success_data(api_client.create_outreach_campaign(
        tid, create_outreach_campaign_payload(**overrides), CO1))
    return get_success_data(api_client.schedule_outreach_campaign(tid, camp["id"], CO1))


# ─── Tier 5: defense packet with mixed outcomes ──────────────────────────────

def setup_mixed_outcome_campaign():
    """Four customers each with one APPROVED CA cert; campaign FIXED_FLOOR floor=4
    draws four samples. Samples are then driven: [0] PASSED, [1] PASSED,
    [2] WAIVED, [3] FAILED; the FAILED sample receives a WAIVE_SAMPLE remediation
    that is begun and RESOLVED by u_co1, so defense assembly becomes permitted
    (PRD §3.9). Campaign ends in DEFENSE_ASSEMBLY with the packet in DRAFT.

    Returns dict(tenant, customers, certs, campaign, samples, packet_id).
    """
    tenant = setup_tenant_config(rule_specs=[{"state_code": "CA", "validity_window_days": 0}])
    customers, certs = [], []
    for i in range(4):
        cust = create_onboarded_customer(
            tid=tenant["id"], external_ref=f"C{i + 1}", legal_name=f"Cust {i + 1}")
        cert = create_approved_certificate(
            tenant["id"], cust["id"],
            version_overrides={"file_uri": f"s3://c{i + 1}.pdf"})
        customers.append(cust)
        certs.append(cert)

    camp, samples = open_campaign_with_samples(tid=tenant["id"],
                                               population_state_filter=["CA"],
                                               floor_sample_size=4)
    assert len(samples) == 4, f"Setup expected 4 samples, got {len(samples)}"
    tid = tenant["id"]

    # [0] -> PASSED, [1] -> PASSED
    for s in samples[0:2]:
        request_and_receive_docs(tid, s["id"])
        get_success_data(api_client.pass_sample(tid, s["id"], AUD1))
    # [2] -> WAIVED (waive is allowed from DOC_REQUESTED, PRD §3.8)
    get_success_data(api_client.request_docs(tid, samples[2]["id"], AUD1))
    get_success_data(api_client.waive_sample(tid, samples[2]["id"], AUD1))
    # [3] -> FAILED, then remediated via a manual WAIVE_SAMPLE action
    request_and_receive_docs(tid, samples[3]["id"])
    fail_sample(tid, samples[3]["id"], "missing signature")
    action = create_manual_remediation(tid, samples[3]["id"], action_type="WAIVE_SAMPLE")
    begin_remediation(tid, action["id"], CO1)
    resolve_remediation(tid, camp["id"], action["id"], CO1)

    get_success_data(api_client.begin_defense_assembly(tid, camp["id"], AUD1))
    packet_id = get_defense_packet_id(tid, camp["id"])
    return {"tenant": tenant, "customers": customers, "certs": certs,
            "campaign": camp, "samples": samples, "packet_id": packet_id}
