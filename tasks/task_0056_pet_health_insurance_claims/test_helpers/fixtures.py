"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server with an empty DB before every test). Setup
calls use get_success_data() so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion failure.

Identity threading: PolicyHolder is entity_backed:Account, so every
ownership-gated PolicyHolder call passes make_policy_holder_headers(account_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_policy_holder_headers,
    make_underwriter_headers,
    make_claims_adjuster_headers,
)
from .factories import (
    create_account_payload,
    create_policy_payload,
    create_condition_payload,
    create_claim_payload,
    create_line_payload,
    create_invoice_payload,
)


def _uw():
    return make_underwriter_headers()


def _adj():
    return make_claims_adjuster_headers()


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Set the server clock (Underwriter-only capability)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, _uw()))


# --------------------------------------------------------------------------
# Tier 1/2: account + policy + activation
# --------------------------------------------------------------------------
def create_account(**overrides) -> dict:
    return get_success_data(api_client.create_account(create_account_payload(**overrides), _uw()))


def create_policy(account_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_policy(account_id, create_policy_payload(**overrides), _uw())
    )


def activate_policy(account_id, policy_id, **payload) -> dict:
    return get_success_data(
        api_client.activate_policy(account_id, policy_id, dict(payload), _uw())
    )


def create_account_with_active_policy(account_overrides=None, policy_overrides=None):
    """Account + one ACTIVE policy (PolicyYear 0 created). Returns (account, policy)."""
    account = create_account(**(account_overrides or {}))
    policy = create_policy(account["id"], **(policy_overrides or {}))
    activate_policy(account["id"], policy["id"])
    return account, policy


def get_year_zero(account_id, policy_id) -> dict:
    """Return the first PolicyYear (year_index 0) of a policy."""
    data, _ = _list_years(account_id, policy_id)
    assert data, "Setup failed: no PolicyYear found for policy"
    return data[0]


def _list_years(account_id, policy_id):
    resp = api_client.list_policy_years(account_id, policy_id, _uw())
    body = resp.json()
    return body["data"], body.get("meta", {})


def get_year_zero_version(account_id, policy_id) -> int:
    return get_year_zero(account_id, policy_id)["version"]


def create_condition(account_id, policy_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_condition(account_id, policy_id, create_condition_payload(**overrides), _uw())
    )


# --------------------------------------------------------------------------
# Tier 3: claim assembly through arbitrary lifecycle stages
# --------------------------------------------------------------------------
def open_claim(account_id, policy_id, **overrides) -> dict:
    """Open a DRAFT claim as the owning PolicyHolder."""
    return get_success_data(
        api_client.create_claim(
            account_id, policy_id, create_claim_payload(**overrides),
            make_policy_holder_headers(account_id),
        )
    )


def add_line(account_id, claim_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_line(claim_id, create_line_payload(**overrides), make_policy_holder_headers(account_id))
    )


def upload_invoice(account_id, claim_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_invoice(claim_id, create_invoice_payload(**overrides), make_policy_holder_headers(account_id))
    )


def run_ocr(claim_id, invoice_id, ocr_total_cents) -> dict:
    return get_success_data(
        api_client.run_ocr(claim_id, invoice_id, {"ocr_total_cents": ocr_total_cents}, _adj())
    )


def accept_invoice(claim_id, invoice_id) -> dict:
    return get_success_data(api_client.accept_invoice(claim_id, invoice_id, _adj()))


def submit_claim(account_id, claim_id) -> dict:
    return get_success_data(api_client.submit_claim(claim_id, make_policy_holder_headers(account_id)))


def begin_review(claim_id) -> dict:
    return get_success_data(api_client.begin_review(claim_id, _adj()))


def build_claim_in_review(account_id, policy_id, condition_id=None,
                          claim_overrides=None, billed_amount_cents=40000,
                          ocr_total_cents=None):
    """Open a claim, add one line, upload+OCR(match)+accept an invoice, submit,
    begin-review. Returns the IN_REVIEW claim dict.

    condition_id is threaded into the claim payload when supplied (non-WELLNESS).
    ocr_total_cents defaults to billed_amount_cents (zero mismatch -> OCR_DONE).
    """
    overrides = dict(claim_overrides or {})
    if condition_id is not None:
        overrides["condition_id"] = condition_id
    claim = open_claim(account_id, policy_id, **overrides)
    add_line(account_id, claim["id"], billed_amount_cents=billed_amount_cents)
    invoice = upload_invoice(account_id, claim["id"])
    run_ocr(claim["id"], invoice["id"], billed_amount_cents if ocr_total_cents is None else ocr_total_cents)
    accept_invoice(claim["id"], invoice["id"])
    submit_claim(account_id, claim["id"])
    return begin_review(claim["id"])


def adjudicate_approve(account_id, policy_id, claim_id, expected_version=None) -> dict:
    """Adjudicate APPROVE supplying the current PolicyYear version."""
    if expected_version is None:
        expected_version = get_year_zero_version(account_id, policy_id)
    return get_success_data(
        api_client.adjudicate(
            claim_id, {"decision": "APPROVE", "expected_policy_year_version": expected_version}, _adj()
        )
    )


def approve_claim_in_review(account_id, policy_id, condition_id=None,
                            claim_overrides=None, billed_amount_cents=40000):
    """Full chain: build an IN_REVIEW claim and APPROVE it. Returns approved claim dict."""
    claim = build_claim_in_review(
        account_id, policy_id, condition_id=condition_id,
        claim_overrides=claim_overrides, billed_amount_cents=billed_amount_cents,
    )
    return adjudicate_approve(account_id, policy_id, claim["id"])
