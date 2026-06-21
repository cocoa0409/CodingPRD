"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Helpers use the
lenient get_success_data() validator so setup failures surface as clear errors.

Identity threading: Taxpayer/Preparer are entity_backed:Taxpayer, so every
ownership-gated call uses make_taxpayer_headers(taxpayer_id) (the actual Taxpayer.id),
never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_taxpayer_headers, make_preparer_headers, make_irs_gateway_headers,
)
from . import factories as F


# ---------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------

def create_taxpayer(**overrides) -> dict:
    """Register a Taxpayer. overrides set prior_year_* etc."""
    payload = F.create_taxpayer_payload(**overrides)
    # Use a generic Taxpayer header for the create (registration is not ownership-gated).
    resp = api_client.create_taxpayer(payload, make_taxpayer_headers("bootstrap"))
    return get_success_data(resp)


def create_draft_return(taxpayer_id: str, **overrides) -> dict:
    """Open a DRAFT return owned by taxpayer_id."""
    payload = F.create_tax_return_payload(taxpayer_id, **overrides)
    resp = api_client.create_tax_return(payload, make_taxpayer_headers(taxpayer_id))
    return get_success_data(resp)


def add_income_document(return_id: str, taxpayer_id: str, **overrides) -> dict:
    payload = F.create_income_document_payload(**overrides)
    resp = api_client.create_income_document(
        return_id, payload, make_taxpayer_headers(taxpayer_id))
    return get_success_data(resp)


def add_schedule(return_id: str, taxpayer_id: str, schedule_type: str, **overrides) -> dict:
    payload = F.create_schedule_payload(schedule_type, **overrides)
    resp = api_client.create_schedule(
        return_id, payload, make_taxpayer_headers(taxpayer_id))
    return get_success_data(resp)


def add_dependent(return_id: str, taxpayer_id: str, **overrides) -> dict:
    payload = F.create_dependent_payload(**overrides)
    resp = api_client.create_dependent(
        return_id, payload, make_taxpayer_headers(taxpayer_id))
    return get_success_data(resp)


def add_credit_claim(return_id: str, taxpayer_id: str, credit_type: str, **overrides) -> dict:
    payload = F.create_credit_claim_payload(credit_type, **overrides)
    resp = api_client.create_credit_claim(
        return_id, payload, make_taxpayer_headers(taxpayer_id))
    return get_success_data(resp)


def add_estimated_payment(return_id: str, taxpayer_id: str, **overrides) -> dict:
    payload = F.create_estimated_tax_payment_payload(return_id, **overrides)
    resp = api_client.create_estimated_tax_payment(
        payload, make_taxpayer_headers(taxpayer_id))
    return get_success_data(resp)


def compute(return_id: str, taxpayer_id: str) -> dict:
    resp = api_client.compute_tax_return(return_id, make_taxpayer_headers(taxpayer_id))
    return get_success_data(resp)


def get_return(return_id: str, taxpayer_id: str) -> dict:
    resp = api_client.get_tax_return(return_id, make_taxpayer_headers(taxpayer_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------
# Tier 1 / 2: state progression + hierarchy
# ---------------------------------------------------------------------

def setup_taxpayer_and_return(taxpayer_overrides=None, return_overrides=None):
    """Taxpayer + DRAFT TaxReturn. Returns (taxpayer, tax_return)."""
    taxpayer = create_taxpayer(**(taxpayer_overrides or {}))
    tax_return = create_draft_return(taxpayer["id"], **(return_overrides or {}))
    return taxpayer, tax_return


def setup_draft_return_with_w2(box_amount_cents=8_000_000, federal_withholding_cents=0,
                               taxpayer_overrides=None, return_overrides=None):
    """Taxpayer + DRAFT return + one W-2. Returns (taxpayer, tax_return, doc)."""
    taxpayer, tax_return = setup_taxpayer_and_return(taxpayer_overrides, return_overrides)
    doc = add_income_document(
        tax_return["id"], taxpayer["id"],
        doc_type="W2", payer_name="Acme",
        box_amount_cents=box_amount_cents,
        federal_withholding_cents=federal_withholding_cents,
    )
    return taxpayer, tax_return, doc


def setup_computed_return(box_amount_cents=8_000_000, federal_withholding_cents=900_000,
                          taxpayer_overrides=None, return_overrides=None):
    """Taxpayer + return + one W-2 + compute to READY.
    Returns (taxpayer, computed_return)."""
    taxpayer, tax_return, _doc = setup_draft_return_with_w2(
        box_amount_cents, federal_withholding_cents,
        taxpayer_overrides, return_overrides)
    computed = compute(tax_return["id"], taxpayer["id"])
    return taxpayer, computed


# ---------------------------------------------------------------------
# Tier 3: full e-file lifecycle shortcuts
# ---------------------------------------------------------------------

def setup_transmitted_efile(box_amount_cents=8_000_000, federal_withholding_cents=900_000,
                            taxpayer_overrides=None, return_overrides=None):
    """Taxpayer + computed READY return + TRANSMITTED e-file.
    Returns (taxpayer, return_after_efile, efiling)."""
    taxpayer, computed = setup_computed_return(
        box_amount_cents, federal_withholding_cents,
        taxpayer_overrides, return_overrides)
    headers = make_taxpayer_headers(taxpayer["id"])
    resp = api_client.efile_tax_return(
        computed["id"], F.efile_payload(computed["version"]), headers)
    efiling = get_success_data(resp)
    ret_after = get_return(computed["id"], taxpayer["id"])
    return taxpayer, ret_after, efiling


def setup_acknowledged_efile(outcome="ACCEPTED", ack_code="A0000",
                             box_amount_cents=8_000_000, federal_withholding_cents=900_000,
                             taxpayer_overrides=None, return_overrides=None):
    """Full chain through gateway acknowledgement.
    Returns (taxpayer, return_after_ack, efiling_after_ack)."""
    taxpayer, _ret, efiling = setup_transmitted_efile(
        box_amount_cents, federal_withholding_cents,
        taxpayer_overrides, return_overrides)
    resp = api_client.acknowledge_efiling(
        efiling["id"], F.acknowledge_payload(outcome, ack_code),
        make_irs_gateway_headers())
    efiling_after = get_success_data(resp)
    ret_after = get_return(efiling_after["return_id"], taxpayer["id"])
    return taxpayer, ret_after, efiling_after


def setup_filed_return(box_amount_cents=8_000_000, federal_withholding_cents=900_000,
                       taxpayer_overrides=None, return_overrides=None):
    """Full chain to a FILED return (ACCEPTED e-file).
    Returns (taxpayer, filed_return, efiling)."""
    return setup_acknowledged_efile(
        outcome="ACCEPTED",
        box_amount_cents=box_amount_cents,
        federal_withholding_cents=federal_withholding_cents,
        taxpayer_overrides=taxpayer_overrides,
        return_overrides=return_overrides)


def setup_rejected_return(box_amount_cents=8_000_000, federal_withholding_cents=900_000,
                          taxpayer_overrides=None, return_overrides=None):
    """Full chain to a REJECTED return (REJECTED e-file).
    Returns (taxpayer, rejected_return, efiling)."""
    return setup_acknowledged_efile(
        outcome="REJECTED", ack_code="R0001",
        box_amount_cents=box_amount_cents,
        federal_withholding_cents=federal_withholding_cents,
        taxpayer_overrides=taxpayer_overrides,
        return_overrides=return_overrides)


# ---------------------------------------------------------------------
# Tier 4 / 5: amendment lifecycle
# ---------------------------------------------------------------------

def setup_draft_amendment(corrected_balance_due_cents=40_000,
                          correction_period_start="2025-01-01T00:00:00Z",
                          correction_period_end="2025-06-30T00:00:00Z",
                          box_amount_cents=8_000_000, federal_withholding_cents=900_000,
                          taxpayer_overrides=None):
    """FILED return + a DRAFT AmendedReturn against it.
    Returns (taxpayer, filed_return, efiling, amendment)."""
    taxpayer, filed, efiling = setup_filed_return(
        box_amount_cents=box_amount_cents,
        federal_withholding_cents=federal_withholding_cents,
        taxpayer_overrides=taxpayer_overrides)
    headers = make_taxpayer_headers(taxpayer["id"])
    resp = api_client.create_amended_return(
        F.create_amended_return_payload(
            filed["id"], taxpayer["id"], filed["version"],
            corrected_balance_due_cents=corrected_balance_due_cents,
            correction_period_start=correction_period_start,
            correction_period_end=correction_period_end,
        ),
        headers)
    amendment = get_success_data(resp)
    return taxpayer, filed, efiling, amendment


def setup_filed_amendment(corrected_balance_due_cents=40_000,
                          correction_period_start="2025-01-01T00:00:00Z",
                          correction_period_end="2025-06-30T00:00:00Z",
                          box_amount_cents=8_000_000, federal_withholding_cents=900_000):
    """Full chain through a FILED 1040X (original driven to AMENDED).
    Returns (taxpayer, original_return_after, efiling, filed_amendment)."""
    taxpayer, filed, efiling, amendment = setup_draft_amendment(
        corrected_balance_due_cents, correction_period_start, correction_period_end,
        box_amount_cents, federal_withholding_cents)
    headers = make_taxpayer_headers(taxpayer["id"])
    resp = api_client.file_amended_return(amendment["id"], headers)
    filed_amendment = get_success_data(resp)
    original_after = get_return(filed["id"], taxpayer["id"])
    return taxpayer, original_after, efiling, filed_amendment
