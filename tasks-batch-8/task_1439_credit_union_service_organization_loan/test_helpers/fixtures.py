"""
Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

All helpers use get_success_data() (lenient validator) so setup failures produce
clear "Setup failed" errors instead of confusing assertion failures.

Identity threading: every ownership-gated call uses the per-instance header
builders from test_users (make_cuso_officer_headers(cuso_id),
make_originator_headers(originator_id), make_buyer_headers(buyer_id),
make_treasury_headers(credit_union_id)) — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_credit_union_payload, create_cuso_payload, create_investment_payload,
    create_agreement_payload, create_offering_payload, create_commitment_payload,
    create_exception_payload, create_remittance_payload,
    create_surveillance_report_payload, create_exam_payload, create_finding_payload,
    create_loss_event_payload, create_repurchase_case_payload,
)
from .test_users import (
    TEST_USERS, make_treasury_headers, make_cuso_officer_headers,
    make_originator_headers, make_buyer_headers, make_regulator_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


# ─── Tier 0: primitive creators ─────────────────────────────────────────────

def register_credit_union(charter_number="CU-1", legal_name="Test Credit Union",
                          cu_type="BUYER", total_assets_cents=DEFAULTS["CU_TOTAL_ASSETS"],
                          net_worth_cents=DEFAULTS["CU_NET_WORTH"], **overrides):
    """Register a credit union (NetworkAdmin). Returns the created CreditUnion."""
    payload = create_credit_union_payload(
        charter_number=charter_number, legal_name=legal_name, cu_type=cu_type,
        total_assets_cents=total_assets_cents, net_worth_cents=net_worth_cents,
        **overrides)
    res = api_client.create_credit_union(payload, ADMIN)
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_credit_union -> {res.text}"
    return data


def register_cuso(legal_name="CUSO One", service_line="LENDING", **overrides):
    """Register a CUSO (NetworkAdmin). Returns the created CUSO."""
    payload = create_cuso_payload(legal_name=legal_name, service_line=service_line, **overrides)
    res = api_client.create_cuso(payload, ADMIN)
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_cuso -> {res.text}"
    return data


def set_clock(to_iso8601: str):
    """Advance the logical clock (NetworkAdmin). Returns the response data."""
    res = api_client.set_clock(to_iso8601, ADMIN)
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: set_clock({to_iso8601}) -> {res.text}"
    return data


def run_sweep():
    """Run the ops-run sweep (NetworkAdmin). Returns the sweep summary."""
    res = api_client.run_sweep(ADMIN)
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: run_sweep -> {res.text}"
    return data


# ─── Tier 1: state progression — agreements, offerings, certificates ────────

def create_draft_agreement(cuso_id, originator_id, **terms):
    """Create a servicing agreement (CUSOOfficer owning cuso_id). Returns DRAFT agreement."""
    payload = create_agreement_payload(cuso_id, originator_id, **terms)
    res = api_client.create_servicing_agreement(payload, make_cuso_officer_headers(cuso_id))
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_servicing_agreement -> {res.text}"
    return data


def activate_agreement(agreement_id, cuso_id):
    """Activate a DRAFT agreement (its CUSOOfficer). Returns ACTIVE agreement."""
    res = api_client.activate_servicing_agreement(agreement_id, make_cuso_officer_headers(cuso_id))
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: activate_agreement -> {res.text}"
    return data


def create_active_agreement(cuso_id, originator_id, **terms):
    """Create + activate a servicing agreement. Returns ACTIVE agreement."""
    agreement = create_draft_agreement(cuso_id, originator_id, **terms)
    return activate_agreement(agreement["id"], cuso_id)


def create_draft_offering(agreement_id, originator_id, **overrides):
    """Create an offering under an agreement (its OriginatorUser). Returns DRAFT offering."""
    payload = create_offering_payload(agreement_id, **overrides)
    res = api_client.create_offering(payload, make_originator_headers(originator_id))
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_offering -> {res.text}"
    return data


def open_offering(offering_id, originator_id):
    """Open a DRAFT offering (its OriginatorUser). Returns OPEN offering."""
    res = api_client.open_offering(offering_id, make_originator_headers(originator_id))
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: open_offering -> {res.text}"
    return data


def create_open_offering(agreement_id, originator_id, **overrides):
    """Create + open an offering. Returns OPEN offering."""
    offering = create_draft_offering(agreement_id, originator_id, **overrides)
    return open_offering(offering["id"], originator_id)


def commit(offering_id, buyer_id, committed_amount_cents=DEFAULTS["COMMIT_AMOUNT"], **overrides):
    """Buyer commits to an offering. Returns the PENDING_DILIGENCE certificate."""
    payload = create_commitment_payload(
        offering_id, committed_amount_cents=committed_amount_cents, **overrides)
    res = api_client.create_commitment(payload, make_buyer_headers(buyer_id))
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_commitment -> {res.text}"
    return data


def approve_diligence(certificate_id, buyer_id):
    """Buyer approves diligence. Returns the COMMITTED certificate."""
    res = api_client.approve_diligence(certificate_id, make_buyer_headers(buyer_id))
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: approve_diligence -> {res.text}"
    return data


def fund_certificate(certificate_id, buyer_id):
    """Buyer funds a COMMITTED certificate. Returns the ACTIVE certificate."""
    res = api_client.fund_commitment(certificate_id, make_buyer_headers(buyer_id))
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: fund_commitment -> {res.text}"
    return data


def create_funded_certificate(offering_id, buyer_id,
                              committed_amount_cents=DEFAULTS["COMMIT_AMOUNT"]):
    """Commit -> approve-diligence -> fund. Returns the ACTIVE certificate."""
    cert = commit(offering_id, buyer_id, committed_amount_cents)
    approve_diligence(cert["id"], buyer_id)
    return fund_certificate(cert["id"], buyer_id)


# ─── Tier 2: entity hierarchy — full pool context ───────────────────────────

def setup_pool(num_buyers=1, agreement_overrides=None, offering_overrides=None,
               buyer_overrides=None, originator_overrides=None, originator_type="ORIGINATOR"):
    """
    Standard network: one originator CU, `num_buyers` buyer CUs, one CUSO,
    one ACTIVE agreement, one OPEN offering.

    Returns dict with keys: originator, buyers (list), cuso, agreement, offering.
    """
    originator_kw = dict(cu_type=originator_type,
                         total_assets_cents=DEFAULTS["ORIG_TOTAL_ASSETS"],
                         net_worth_cents=DEFAULTS["ORIG_NET_WORTH"])
    originator_kw.update(originator_overrides or {})
    originator = register_credit_union(charter_number="CU-ORIG",
                                       legal_name="Originator CU", **originator_kw)

    buyers = []
    for i in range(num_buyers):
        buyer_kw = dict(cu_type="BUYER")
        buyer_kw.update(buyer_overrides or {})
        suffix = "" if num_buyers == 1 else f"-{i + 1}"
        buyers.append(register_credit_union(charter_number=f"CU-BUY{suffix}",
                                            legal_name=f"Buyer CU {i + 1}", **buyer_kw))

    cuso = register_cuso()
    agreement = create_active_agreement(cuso["id"], originator["id"],
                                        **(agreement_overrides or {}))
    offering = create_open_offering(agreement["id"], originator["id"],
                                    **(offering_overrides or {}))
    return {"originator": originator, "buyers": buyers, "cuso": cuso,
            "agreement": agreement, "offering": offering}


def setup_pool_with_funded_cert(committed_amount_cents=DEFAULTS["COMMIT_AMOUNT"], **pool_kwargs):
    """
    Standard pool plus one funded (ACTIVE) certificate from the first buyer.
    Returns dict(pool context) + key "certificate".
    """
    ctx = setup_pool(**pool_kwargs)
    cert = create_funded_certificate(ctx["offering"]["id"], ctx["buyers"][0]["id"],
                                     committed_amount_cents)
    ctx["certificate"] = cert
    return ctx


# ─── Tier 3: lifecycle shortcuts — remittances, exceptions, findings ────────

def schedule_remittance(certificate_id, originator_id,
                        period_start=DEFAULTS["PERIOD_START"],
                        period_end=DEFAULTS["PERIOD_END"],
                        collections_cents=100_000, **overrides):
    """Schedule a period remittance (OriginatorUser). Returns the SCHEDULED remittance."""
    payload = create_remittance_payload(
        certificate_id, period_start=period_start, period_end=period_end,
        collections_cents=collections_cents, **overrides)
    res = api_client.create_remittance(payload, make_originator_headers(originator_id))
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_remittance -> {res.text}"
    return data


def flag_exception(certificate_id, buyer_id, exception_type="MISSING_NOTE",
                   description="Documentation gap"):
    """Buyer flags a documentation exception. Returns the OPEN exception."""
    payload = create_exception_payload(certificate_id, exception_type=exception_type,
                                       description=description)
    res = api_client.create_exception(payload, make_buyer_headers(buyer_id))
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_exception -> {res.text}"
    return data


def open_exam(cuso_id, start_date="2026-08-01T00:00:00Z",
              end_date="2026-08-15T00:00:00Z", regulator_id="reg-1"):
    """Regulator opens an exam on a CUSO. Returns the IN_PROGRESS exam."""
    payload = create_exam_payload(cuso_id, start_date=start_date, end_date=end_date)
    res = api_client.create_exam(payload, make_regulator_headers(regulator_id))
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_exam -> {res.text}"
    return data


def record_finding(exam_id, severity="CRITICAL", description="Finding",
                   remediation_due_date=DEFAULTS["REMEDIATION_DUE"], regulator_id="reg-1"):
    """Regulator records a finding on an exam. Returns the OPEN finding."""
    payload = create_finding_payload(exam_id, severity=severity, description=description,
                                     remediation_due_date=remediation_due_date)
    res = api_client.create_finding(payload, make_regulator_headers(regulator_id))
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_finding -> {res.text}"
    return data


def setup_exam_with_finding(severity="CRITICAL", regulator_id="reg-1"):
    """CUSO + IN_PROGRESS exam + one recorded finding. Returns dict of all three."""
    cuso = register_cuso()
    exam = open_exam(cuso["id"], regulator_id=regulator_id)
    finding = record_finding(exam["id"], severity=severity, regulator_id=regulator_id)
    return {"cuso": cuso, "exam": exam, "finding": finding}


def finalize_exam(exam_id, regulator_id="reg-2"):
    """Regulator finalizes an exam. Returns the FINALIZED exam."""
    res = api_client.finalize_exam(exam_id, make_regulator_headers(regulator_id))
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: finalize_exam -> {res.text}"
    return data


def suspend_cuso_with_open_critical(cuso_id, regulator_id="reg-1"):
    """
    Drive a CUSO to SUSPENDED: open an exam, record a CRITICAL finding, finalize.
    Returns dict(cuso GET after finalize, exam, finding).
    """
    exam = open_exam(cuso_id, regulator_id=regulator_id)
    finding = record_finding(exam["id"], severity="CRITICAL", regulator_id=regulator_id)
    finalize_exam(exam["id"], regulator_id=regulator_id)
    cuso = get_success_data(api_client.get_cuso(cuso_id, ADMIN))
    return {"cuso": cuso, "exam": exam, "finding": finding}


# ─── Tier 4: investments ────────────────────────────────────────────────────

def setup_investor(total_assets_cents=50_000_000_000, net_worth_cents=5_000_000_000):
    """Investor CU (DUAL) + target CUSO. Returns dict(investor, cuso)."""
    investor = register_credit_union(charter_number="CU-INV", legal_name="Investor CU",
                                     cu_type="DUAL", total_assets_cents=total_assets_cents,
                                     net_worth_cents=net_worth_cents)
    cuso = register_cuso()
    return {"investor": investor, "cuso": cuso}


def submit_investment(investor_id, cuso_id, amount_cents, approval_basis=None):
    """TreasuryUser submits an investment. Returns the PENDING_REVIEW investment."""
    overrides = {"amount_cents": amount_cents}
    if approval_basis is not None:
        overrides["approval_basis"] = approval_basis
    payload = create_investment_payload(investor_id, cuso_id, **overrides)
    res = api_client.create_cuso_investment(payload, make_treasury_headers(investor_id))
    data = get_success_data(res)
    assert res.status_code == 201, f"Setup failed: create_cuso_investment -> {res.text}"
    return data


def approve_investment(investment_id, regulator_id="reg-1"):
    """Regulator approves an investment. Returns the APPROVED investment."""
    res = api_client.approve_cuso_investment(investment_id, make_regulator_headers(regulator_id))
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: approve_cuso_investment -> {res.text}"
    return data


# ─── Tier 4b: specialized pool states ───────────────────────────────────────

def setup_day_count_pair():
    """
    Two ACTIVE agreements (THIRTY_360 and ACT_360, fee 25bps, due day 15) under
    one CUSO/originator, each with an OPEN offering (pool 100,000,000, min 0.01,
    yield 600bps, window 2026-08-01..2026-09-01) and one funded 10,000,000
    certificate from the same buyer. Returns dict with ids and entities.
    """
    originator = register_credit_union(charter_number="CU-ORIG", legal_name="Originator CU",
                                       cu_type="ORIGINATOR",
                                       total_assets_cents=DEFAULTS["ORIG_TOTAL_ASSETS"],
                                       net_worth_cents=DEFAULTS["ORIG_NET_WORTH"])
    buyer = register_credit_union(charter_number="CU-BUY", legal_name="Buyer CU")
    cuso = register_cuso()

    ag_t = create_active_agreement(cuso["id"], originator["id"],
                                   day_count_convention="THIRTY_360")
    ag_a = create_active_agreement(cuso["id"], originator["id"],
                                   day_count_convention="ACT_360")
    window = {"open_at": "2026-08-01T00:00:00Z", "close_at": "2026-09-01T00:00:00Z"}
    off_t = create_open_offering(ag_t["id"], originator["id"], pool_name="Pool T", **window)
    off_a = create_open_offering(ag_a["id"], originator["id"], pool_name="Pool A", **window)
    cert_t = create_funded_certificate(off_t["id"], buyer["id"], 10_000_000)
    cert_a = create_funded_certificate(off_a["id"], buyer["id"], 10_000_000)
    return {"originator": originator, "buyer": buyer, "cuso": cuso,
            "agreement_thirty": ag_t, "agreement_act": ag_a,
            "offering_thirty": off_t, "offering_act": off_a,
            "cert_thirty": cert_t, "cert_act": cert_a}


def setup_wac_pool():
    """
    One ACTIVE agreement (THIRTY_360, fee 25bps, due day 15) with two OPEN
    offerings (600bps and 700bps, pool 1,000,000,000 each, min 0.01):
    cert A 20,000,000 in the 600bps pool (funded, then one on-time remittance
    of collections 5,052,083 for 2026-08-01..2026-08-31 paid down) and
    cert B 10,000,000 in the 700bps pool (funded). Returns dict with the
    agreement's current version for OCC-guarded report creation.
    """
    ctx = setup_pool(num_buyers=1)
    originator, buyer, cuso, agreement = (ctx["originator"], ctx["buyers"][0],
                                          ctx["cuso"], ctx["agreement"])
    window = {"open_at": "2026-08-01T00:00:00Z", "close_at": "2026-09-01T00:00:00Z"}
    off1 = create_open_offering(agreement["id"], originator["id"], pool_name="Pool 600",
                                pool_principal_cents=1_000_000_000, yield_rate_bps=600,
                                **window)
    off2 = create_open_offering(agreement["id"], originator["id"], pool_name="Pool 700",
                                pool_principal_cents=1_000_000_000, yield_rate_bps=700,
                                **window)
    cert_a = create_funded_certificate(off1["id"], buyer["id"], 20_000_000)
    cert_b = create_funded_certificate(off2["id"], buyer["id"], 10_000_000)
    rem = schedule_remittance(cert_a["id"], originator["id"], collections_cents=5_052_083)
    res = api_client.pay_remittance(rem["id"], make_originator_headers(originator["id"]))
    assert res.status_code == 200, f"Setup failed: pay_remittance -> {res.text}"
    version = get_success_data(api_client.get_servicing_agreement(
        agreement["id"], make_cuso_officer_headers(cuso["id"])))["version"]
    return {"originator": originator, "buyer": buyer, "cuso": cuso, "agreement": agreement,
            "offering_600": off1, "offering_700": off2,
            "cert_a": cert_a, "cert_b": cert_b, "remittance_a": rem,
            "agreement_version": version}


def setup_loss_rounding_pool():
    """
    Three buyers each fund exactly 300 cents into one OPEN offering
    (pool 90,000, min_share_pct 0.001, yield 600bps, loss_basis OUTSTANDING).

    The logical clock is advanced between the three commitments so the
    certificates carry distinct, ascending created_at timestamps — the
    residual-cent tie-break (PRD §3.7: created_at ascending) then resolves
    deterministically to the earliest-created certificate.
    """
    originator = register_credit_union(charter_number="CU-ORIG", legal_name="Originator CU",
                                       cu_type="ORIGINATOR",
                                       total_assets_cents=DEFAULTS["ORIG_TOTAL_ASSETS"],
                                       net_worth_cents=DEFAULTS["ORIG_NET_WORTH"])
    buyers = [register_credit_union(charter_number=f"CU-B{i}", legal_name=f"Buyer {i}")
              for i in (1, 2, 3)]
    cuso = register_cuso()
    agreement = create_active_agreement(cuso["id"], originator["id"])
    offering = create_open_offering(agreement["id"], originator["id"],
                                    pool_name="Pool Tiny", pool_principal_cents=90_000,
                                    min_share_pct=0.001,
                                    open_at="2026-08-01T00:00:00Z",
                                    close_at="2026-09-01T00:00:00Z")
    certs = []
    for i, buyer in enumerate(buyers):
        set_clock(f"2026-08-0{i + 1}T00:00:00Z")
        certs.append(create_funded_certificate(offering["id"], buyer["id"], 300))
    return {"originator": originator, "buyers": buyers, "cuso": cuso,
            "agreement": agreement, "offering": offering, "certificates": certs}


def setup_delinquent_agreement(threshold=1, grace_period_days=5, collections_cents=100_000):
    """
    ACTIVE agreement (given threshold/grace, due day 15) + OPEN offering +
    one funded 10,000,000 certificate + one SCHEDULED remittance for
    2026-08-01..2026-08-31; clock advanced to 2026-09-21 and the sweep run,
    flipping the remittance to LATE_UNPAID, the agreement to DELINQUENT, and
    the offering to SUSPENDED. Returns the full context dict.
    """
    ctx = setup_pool_with_funded_cert(
        agreement_overrides={"grace_period_days": grace_period_days,
                             "late_remittance_threshold": threshold})
    rem = schedule_remittance(ctx["certificate"]["id"], ctx["originator"]["id"],
                              collections_cents=collections_cents)
    set_clock("2026-09-21T00:00:00Z")
    run_sweep()
    ctx["remittance"] = rem
    return ctx
