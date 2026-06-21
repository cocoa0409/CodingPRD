"""Composite setup helpers for the Genetic & Molecular Testing Lab API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the per-test server starts against an empty database). Setup calls
use get_success_data() so a setup break surfaces as a clear "Setup failed".

The order lifecycle is long (catalog -> order -> requisition -> consent ->
specimen/accession -> sequencing -> variants/classify -> classification/complete
-> report -> sign-out), so these helpers encapsulate the multi-step preambles
and accept **overrides for the values individual tests must control.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_headers
from . import factories as F

DEFAULT_CLOCK = "2026-06-19T00:00:00.000Z"

DIRECTOR = TEST_USERS["director_headers"]          # X-User-ID director-1
INTAKE = TEST_USERS["intake_headers"]
ACCESSIONING = TEST_USERS["accessioning_headers"]
MOLECULAR = TEST_USERS["molecular_headers"]        # X-User-ID tech-1
BILLING = TEST_USERS["billing_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Set the deterministic lab clock. Returns the LabClock data."""
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


# --------------------------------------------------------------------------- #
# Tier 1/2: catalog + order construction
# --------------------------------------------------------------------------- #
def create_gene(symbol, is_acmg_reportable=False):
    return get_success_data(
        api_client.create_gene(
            F.create_gene_payload(symbol=symbol, is_acmg_reportable=is_acmg_reportable),
            DIRECTOR))


def create_published_panel(list_price_cents=40000, requires_consent=False,
                           gene_symbols=("GENE",), acmg_flags=None, name="Panel"):
    """Create genes, a panel, add the genes as INCLUDED memberships, publish.
    Returns (panel, [gene, ...]).
    """
    if acmg_flags is None:
        acmg_flags = [False] * len(gene_symbols)
    genes = []
    for sym, acmg in zip(gene_symbols, acmg_flags):
        genes.append(create_gene(sym, acmg))
    panel = get_success_data(api_client.create_panel(
        F.create_panel_payload(name=name, list_price_cents=list_price_cents,
                               requires_consent=requires_consent),
        DIRECTOR))
    for g in genes:
        get_success_data(api_client.add_panel_gene(
            panel["id"], F.add_panel_gene_payload(g["id"]), DIRECTOR))
    panel = get_success_data(api_client.publish_panel(panel["id"], DIRECTOR))
    return panel, genes


def create_provider():
    return get_success_data(api_client.create_provider(
        F.create_provider_payload(), INTAKE))


def place_order(panel_id, provider_id, patient_dob="1990-01-01", patient_mrn="MRN-T"):
    return get_success_data(api_client.create_test_order(
        F.create_test_order_payload(panel_id, provider_id,
                                    patient_mrn=patient_mrn, patient_dob=patient_dob),
        INTAKE))


def setup_ordered(list_price_cents=40000, requires_consent=False,
                  gene_symbols=("GENE",), acmg_flags=None,
                  patient_dob="1990-01-01", name="Panel"):
    """Catalog + provider + a freshly placed ORDERED order.
    Returns dict with panel, genes, provider, order.
    """
    set_clock()
    panel, genes = create_published_panel(
        list_price_cents=list_price_cents, requires_consent=requires_consent,
        gene_symbols=gene_symbols, acmg_flags=acmg_flags, name=name)
    provider = create_provider()
    order = place_order(panel["id"], provider["id"], patient_dob=patient_dob)
    return {"panel": panel, "genes": genes, "provider": provider, "order": order}


# --------------------------------------------------------------------------- #
# Tier 1/3: requisition + billing fork
# --------------------------------------------------------------------------- #
def add_requisition(order_id, insurance_payer="SELF_PAY"):
    return get_success_data(api_client.create_requisition(
        order_id, F.create_requisition_payload(insurance_payer=insurance_payer),
        INTAKE))


def submit_requisition(order_id):
    return get_success_data(api_client.submit_requisition(order_id, INTAKE))


def setup_requisitioned(insurance_payer="SELF_PAY", **order_kwargs):
    """Order -> requisition created -> submitted (REQUISITIONED, billing forked).
    Returns dict adding requisition.
    """
    ctx = setup_ordered(**order_kwargs)
    req = add_requisition(ctx["order"]["id"], insurance_payer=insurance_payer)
    submit_requisition(ctx["order"]["id"])
    ctx["requisition"] = req
    return ctx


def auth_approve(order_id, allowed_amount_cents):
    return get_success_data(api_client.auth_decision(
        order_id, F.auth_decision_payload("APPROVED", allowed_amount_cents), BILLING))


def auth_deny(order_id):
    return get_success_data(api_client.auth_decision(
        order_id, F.auth_decision_payload("DENIED"), BILLING))


# --------------------------------------------------------------------------- #
# Tier 1: consent
# --------------------------------------------------------------------------- #
def add_signed_consent(order_id, incidental_findings_opt_in=True):
    consent = get_success_data(api_client.create_consent(
        order_id, F.create_consent_payload(
            incidental_findings_opt_in=incidental_findings_opt_in), INTAKE))
    get_success_data(api_client.sign_consent(order_id, consent["id"], INTAKE))
    return consent


# --------------------------------------------------------------------------- #
# Tier 1/3: specimen + accession + sequencing
# --------------------------------------------------------------------------- #
def add_specimen(order_id, specimen_type="BLOOD", quantity_ng=80,
                 collected_at="2026-06-18T00:00:00.000Z"):
    return get_success_data(api_client.create_specimen(
        order_id, F.create_specimen_payload(
            specimen_type=specimen_type, quantity_ng=quantity_ng,
            collected_at=collected_at), ACCESSIONING))


def accession(order_id, specimen_id):
    return get_success_data(api_client.accession_specimen(order_id, specimen_id, ACCESSIONING))


def setup_sequencing(insurance_payer="SELF_PAY", requires_consent=False,
                     opt_in=True, specimen_type="BLOOD", quantity_ng=80,
                     **order_kwargs):
    """Drive an order all the way to SEQUENCING.
    If requires_consent, a signed consent is added before accessioning.
    Returns dict adding specimen.
    """
    ctx = setup_requisitioned(insurance_payer=insurance_payer,
                              requires_consent=requires_consent, **order_kwargs)
    if requires_consent:
        ctx["consent"] = add_signed_consent(ctx["order"]["id"], opt_in)
    spec = add_specimen(ctx["order"]["id"], specimen_type=specimen_type,
                        quantity_ng=quantity_ng)
    accession(ctx["order"]["id"], spec["id"])
    get_success_data(api_client.start_sequencing(ctx["order"]["id"], ACCESSIONING))
    ctx["specimen"] = spec
    return ctx


# --------------------------------------------------------------------------- #
# Tier 3: variants + classification
# --------------------------------------------------------------------------- #
def add_variant(order_id, gene_id, hgvs="c.100A>T", headers=None):
    return get_success_data(api_client.create_variant(
        order_id, F.create_variant_payload(gene_id, hgvs=hgvs),
        headers or MOLECULAR))


def classify(order_id, variant_id, classification, user_id="tech-1"):
    return get_success_data(api_client.classify_variant(
        order_id, variant_id, F.classify_payload(classification),
        make_headers(user_id, "MolecularTechnologist")))


def complete_classification(order_id):
    return get_success_data(api_client.complete_classification(order_id, MOLECULAR))


def create_report(order_id, headers=None):
    return get_success_data(api_client.create_report(order_id, headers or MOLECULAR))


def setup_classified(classification="BENIGN", insurance_payer="SELF_PAY",
                     gene_hgvs="c.100A>T", classifier_user_id="tech-1",
                     **seq_kwargs):
    """SEQUENCING order -> one variant on the panel gene classified -> CLASSIFIED.
    Returns dict adding variant.
    """
    ctx = setup_sequencing(insurance_payer=insurance_payer, **seq_kwargs)
    gene_id = ctx["genes"][0]["id"]
    var = add_variant(ctx["order"]["id"], gene_id, hgvs=gene_hgvs)
    classify(ctx["order"]["id"], var["id"], classification, user_id=classifier_user_id)
    complete_classification(ctx["order"]["id"])
    ctx["variant"] = var
    return ctx


def setup_draft_report(classification="BENIGN", insurance_payer="SELF_PAY",
                       classifier_user_id="tech-1", **seq_kwargs):
    """CLASSIFIED order with a DRAFT report created. Returns dict adding report."""
    ctx = setup_classified(classification=classification,
                           insurance_payer=insurance_payer,
                           classifier_user_id=classifier_user_id, **seq_kwargs)
    ctx["report"] = create_report(ctx["order"]["id"])
    return ctx


def sign_out(order_id, report_id, director_user_id="director-1"):
    return get_success_data(api_client.sign_out_report(
        order_id, report_id, make_headers(director_user_id, "LabDirector")))


def setup_signed_out(classification="BENIGN", insurance_payer="SELF_PAY",
                     classifier_user_id="tech-1", director_user_id="director-1",
                     **seq_kwargs):
    """Full lifecycle through SIGNED_OUT for a clean (BENIGN, SELF_PAY) order.
    Signer differs from classifier by default (director-1 vs tech-1).
    Returns dict adding report (now SIGNED_OUT).
    """
    ctx = setup_draft_report(classification=classification,
                             insurance_payer=insurance_payer,
                             classifier_user_id=classifier_user_id, **seq_kwargs)
    sign_out(ctx["order"]["id"], ctx["report"]["id"], director_user_id=director_user_id)
    return ctx


def get_order(order_id, headers=None):
    return get_success_data(api_client.get_test_order(order_id, headers or DIRECTOR))


# --------------------------------------------------------------------------- #
# Tier 5: counselor + referral
# --------------------------------------------------------------------------- #
def create_counselor(counselor_name="GC One"):
    return get_success_data(api_client.create_counselor(
        F.create_counselor_payload(counselor_name=counselor_name), DIRECTOR))


def request_referral(order_id, counselor_id, reason="PATIENT_REQUEST"):
    return get_success_data(api_client.create_referral(
        order_id, F.create_referral_payload(counselor_id, reason=reason), COUNSELOR))


def schedule_referral(order_id, referral_id, slot_start, slot_end):
    return get_success_data(api_client.schedule_referral(
        order_id, referral_id, F.schedule_referral_payload(slot_start, slot_end),
        COUNSELOR))


# --------------------------------------------------------------------------- #
# Tier 5: sequencer + run
# --------------------------------------------------------------------------- #
def create_sequencer(instrument_name="NovaSeq", turnaround_buffer_minutes=None):
    payload = F.create_sequencer_payload(instrument_name=instrument_name)
    if turnaround_buffer_minutes is not None:
        payload["turnaround_buffer_minutes"] = turnaround_buffer_minutes
    return get_success_data(api_client.create_sequencer(payload, DIRECTOR))


def schedule_run(sequencer_id, order_id, window_start, window_end):
    return get_success_data(api_client.schedule_run(
        sequencer_id, F.schedule_run_payload(order_id, window_start, window_end),
        ACCESSIONING))
