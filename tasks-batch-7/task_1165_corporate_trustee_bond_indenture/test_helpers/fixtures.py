"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so no state
carries over). Setup calls use the lenient get_success_data validator so
failures surface as clear "Setup failed" errors.

Identity threading: issuer-scoped calls use make_issuer_headers with the
indenture's issuer_ref; noteholder-scoped calls use make_noteholder_headers
with the actual NoteholderAccount.id (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_indenture_payload, create_tranche_payload,
    create_noteholder_account_payload, create_position_payload,
    create_covenant_obligation_payload, create_covenant_certificate_payload,
    create_interest_run_payload, create_redemption_run_payload,
    create_default_case_payload, create_direction_payload,
    create_endorsement_payload, create_consent_solicitation_payload,
    create_ballot_payload, create_collateral_item_payload,
    create_release_request_payload, create_substitution_request_payload,
    create_fee_invoice_payload, create_trustee_appointment_payload,
)
from .test_users import (
    TEST_USERS, make_issuer_headers, make_noteholder_headers,
    make_trust_officer_headers, make_trust_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["trust_officer_headers"]
MANAGER = TEST_USERS["trust_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + simple creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    """Advance the logical clock (PRD §2.5); triggers the system sweep."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_indenture(**overrides):
    """Create a DRAFT indenture (PRD §3.1)."""
    resp = api_client.create_indenture(create_indenture_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_tranche(indenture_id, **overrides):
    resp = api_client.create_tranche(create_tranche_payload(indenture_id, **overrides), ADMIN)
    return get_success_data(resp)


def register_account(holder_ref="H-A", legal_name="Holder A", contact_email="a@x.com"):
    resp = api_client.create_noteholder_account(
        create_noteholder_account_payload(
            holder_ref=holder_ref, legal_name=legal_name, contact_email=contact_email),
        ADMIN)
    return get_success_data(resp)


def register_position(tranche_id, account_id, original_principal_cents):
    resp = api_client.create_position(
        create_position_payload(tranche_id, account_id, original_principal_cents), ADMIN)
    return get_success_data(resp)


def get_indenture(indenture_id):
    return get_success_data(api_client.get_indenture(indenture_id, ADMIN))


def get_tranche(tranche_id):
    return get_success_data(api_client.get_tranche(tranche_id, ADMIN))


def get_position(position_id):
    return get_success_data(api_client.get_position(position_id, ADMIN))


def get_account(account_id):
    return get_success_data(api_client.get_noteholder_account(account_id, ADMIN))


def get_payment_run(run_id):
    return get_success_data(api_client.get_payment_run(run_id, OFFICER))


def get_default_case(case_id):
    return get_success_data(api_client.get_default_case(case_id, OFFICER))


def get_direction(direction_id):
    return get_success_data(api_client.get_direction(direction_id, OFFICER))


def get_solicitation(solicitation_id):
    return get_success_data(api_client.get_consent_solicitation(solicitation_id, OFFICER))


def get_obligation(obligation_id):
    return get_success_data(api_client.get_covenant_obligation(obligation_id, OFFICER))


def get_release_request(request_id):
    return get_success_data(api_client.get_collateral_release_request(request_id, OFFICER))


def get_collateral_item(item_id):
    return get_success_data(api_client.get_collateral_item(item_id, OFFICER))


def get_fee_invoice(invoice_id):
    return get_success_data(api_client.get_fee_invoice(invoice_id, OFFICER))


def list_run_records(run_id):
    """All DistributionRecords of a run (list sorted by created_at asc, PRD §2.3)."""
    data = get_success_data(api_client.list_distribution_records(
        OFFICER, params={"payment_run_id": run_id, "limit": 100}))
    return data


def run_records_by_position(run_id, positions):
    """Map position_id -> DistributionRecord for the given positions."""
    records = list_run_records(run_id)
    by_position = {}
    for rec in records:
        by_position[rec["position_id"]] = rec
    return {p["id"]: by_position.get(p["id"]) for p in positions}


# ---------------------------------------------------------------------------
# Tier 1: State progression
# ---------------------------------------------------------------------------

def create_active_indenture_with_tranche(indenture_overrides=None, tranche_overrides=None,
                                         reset_clock=True):
    """DRAFT indenture + tranche + activate (PRD §3.1).

    Returns (indenture, tranche) with the indenture re-read after activation
    so its status/version reflect ACTIVE."""
    if reset_clock:
        set_clock(CLOCK_START)
    ind = create_indenture(**(indenture_overrides or {}))
    tranche = create_tranche(ind["id"], **(tranche_overrides or {}))
    resp = api_client.activate_indenture(ind["id"], ADMIN)
    get_success_data(resp)
    return get_indenture(ind["id"]), tranche


# ---------------------------------------------------------------------------
# Tier 2: Entity hierarchy
# ---------------------------------------------------------------------------

def setup_indenture_with_positions(amounts=(400000000, 350000000, 250000000),
                                   holder_prefixes=("H-A", "H-B", "H-C"),
                                   indenture_overrides=None, tranche_overrides=None,
                                   reset_clock=True):
    """Active indenture + tranche + one account and position per amount.

    The tranche's original principal defaults to the sum of the position
    amounts so the aggregate cap (PRD §3.2) is exactly met.
    Returns dict(indenture, tranche, accounts, positions).
    """
    ind_over = dict(indenture_overrides or {})
    tr_over = dict(tranche_overrides or {})
    tr_over.setdefault("original_principal_cents", sum(amounts))
    indenture, tranche = create_active_indenture_with_tranche(ind_over, tr_over, reset_clock)
    accounts, positions = [], []
    for i, amount in enumerate(amounts):
        prefix = holder_prefixes[i] if i < len(holder_prefixes) else f"H-{i}"
        account = register_account(prefix, f"Holder {prefix}", f"{prefix.lower()}@x.com")
        position = register_position(tranche["id"], account["id"], amount)
        accounts.append(account)
        positions.append(position)
    return {
        "indenture": indenture, "tranche": tranche,
        "accounts": accounts, "positions": positions,
    }


# ---------------------------------------------------------------------------
# Tier 3: Payment-run lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_interest_run(tranche_id, start=TEST_DEFAULTS["INTEREST_PERIOD_START"],
                        end=TEST_DEFAULTS["INTEREST_PERIOD_END"],
                        pay_date=TEST_DEFAULTS["INTEREST_PAYMENT_DATE"]):
    resp = api_client.create_payment_run(
        create_interest_run_payload(tranche_id, period_start_date=start,
                                    period_end_date=end, scheduled_payment_date=pay_date),
        OFFICER)
    return get_success_data(resp)


def create_redemption_run(tranche_id, target_amount_cents,
                          payment_type="SINKING_FUND_REDEMPTION",
                          scheduled_payment_date="2026-06-15"):
    resp = api_client.create_payment_run(
        create_redemption_run_payload(
            tranche_id, target_amount_cents, payment_type=payment_type,
            scheduled_payment_date=scheduled_payment_date),
        OFFICER)
    return get_success_data(resp)


def fund_run(run_id, amount_cents, issuer_ref="issuer-1"):
    """Issuer deposit (PRD §3.4). Ownership: issuer_ref must equal X-User-ID."""
    resp = api_client.fund_payment_run(
        run_id, {"amount_cents": amount_cents}, make_issuer_headers(issuer_ref))
    return get_success_data(resp)


def execute_run(run_id):
    resp = api_client.execute_payment_run(run_id, OFFICER)
    return get_success_data(resp)


def reverse_run(run_id, manager_id="manager-1"):
    resp = api_client.reverse_payment_run(run_id, make_trust_manager_headers(manager_id))
    return get_success_data(resp)


def create_funded_interest_run(tranche_id, gross_amount_cents, issuer_ref="issuer-1", **kwargs):
    """INTEREST run funded to exactly its gross (equality is FUNDED, PRD §3.4)."""
    run = create_interest_run(tranche_id, **kwargs)
    run = fund_run(run["id"], gross_amount_cents, issuer_ref)
    return run


def create_executed_interest_run(tranche_id, gross_amount_cents, issuer_ref="issuer-1", **kwargs):
    """INTEREST run funded and executed; returns (run, records)."""
    run = create_funded_interest_run(tranche_id, gross_amount_cents, issuer_ref, **kwargs)
    run = execute_run(run["id"])
    return run, list_run_records(run["id"])


# ---------------------------------------------------------------------------
# Tier 3b: Default cases and directions
# ---------------------------------------------------------------------------

def declare_default(indenture_id, default_type="PAYMENT",
                    cure_deadline=TEST_DEFAULTS["CURE_DEADLINE"],
                    officer_id="officer-1", source_ref=None):
    payload = create_default_case_payload(
        indenture_id, default_type=default_type, cure_deadline=cure_deadline)
    if source_ref is not None:
        payload["source_ref"] = source_ref
    resp = api_client.create_default_case(payload, make_trust_officer_headers(officer_id))
    return get_success_data(resp)


def confirm_default(case_id, manager_id="manager-1"):
    resp = api_client.confirm_default_case(case_id, make_trust_manager_headers(manager_id))
    return get_success_data(resp)


def cure_default(case_id, manager_id="manager-1"):
    resp = api_client.cure_default_case(case_id, make_trust_manager_headers(manager_id))
    return get_success_data(resp)


def setup_confirmed_default(indenture_id, **kwargs):
    """ALLEGED case declared by officer-1 and confirmed by manager-1 (SoD-clean)."""
    case = declare_default(indenture_id, **kwargs)
    return confirm_default(case["id"])


def create_direction(case_id, instruction_type="ACCELERATE",
                     expires_at=TEST_DEFAULTS["DIRECTION_EXPIRY"]):
    """Open a direction with a fresh OCC version read of the case (PRD §2.7)."""
    case = get_default_case(case_id)
    resp = api_client.create_direction(
        create_direction_payload(
            case_id, expected_default_case_version=case["version"],
            instruction_type=instruction_type, expires_at=expires_at),
        OFFICER)
    return get_success_data(resp)


def endorse_direction(direction_id, account_id):
    """Noteholder endorses its own account (ownership: X-User-ID == account id)."""
    resp = api_client.endorse_direction(
        direction_id, create_endorsement_payload(account_id),
        make_noteholder_headers(account_id))
    return get_success_data(resp)


def withdraw_endorsement(endorsement_id, account_id):
    resp = api_client.withdraw_endorsement(endorsement_id, make_noteholder_headers(account_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3c: Covenant calendar
# ---------------------------------------------------------------------------

def create_obligation(indenture_id, covenant_type="FINANCIAL_REPORT",
                      frequency="QUARTERLY", period_anchor_date="2026-06-30", **overrides):
    payload = create_covenant_obligation_payload(
        indenture_id, covenant_type=covenant_type, frequency=frequency,
        period_anchor_date=period_anchor_date, **overrides)
    resp = api_client.create_covenant_obligation(payload, OFFICER)
    return get_success_data(resp)


def submit_certificate(obligation_id, issuer_ref="issuer-1", **overrides):
    payload = create_covenant_certificate_payload(obligation_id, **overrides)
    resp = api_client.create_covenant_certificate(payload, make_issuer_headers(issuer_ref))
    return get_success_data(resp)


def review_certificate(certificate_id, decision, officer_id="officer-1", rejection_reason=None):
    payload = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    resp = api_client.review_covenant_certificate(
        certificate_id, payload, make_trust_officer_headers(officer_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3d: Consent solicitations
# ---------------------------------------------------------------------------

def create_solicitation(indenture_id, issuer_ref="issuer-1", **overrides):
    payload = create_consent_solicitation_payload(indenture_id, **overrides)
    # None means "omit the optional field" (e.g. amendment_payload on a
    # WAIVE_COVENANT solicitation, target_obligation_id on AMEND_TERMS).
    payload = {k: v for k, v in payload.items() if v is not None}
    resp = api_client.create_consent_solicitation(payload, make_issuer_headers(issuer_ref))
    return get_success_data(resp)


def open_solicitation(solicitation_id):
    resp = api_client.open_consent_solicitation(solicitation_id, OFFICER)
    return get_success_data(resp)


def create_open_solicitation(indenture_id, issuer_ref="issuer-1", **overrides):
    solicitation = create_solicitation(indenture_id, issuer_ref=issuer_ref, **overrides)
    return open_solicitation(solicitation["id"])


def cast_ballot(solicitation_id, account_id, vote="CONSENT"):
    resp = api_client.cast_ballot(
        solicitation_id, create_ballot_payload(account_id, vote),
        make_noteholder_headers(account_id))
    return get_success_data(resp)


def close_solicitation(solicitation_id):
    resp = api_client.close_consent_solicitation(solicitation_id, OFFICER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3e: Collateral
# ---------------------------------------------------------------------------

def register_collateral(indenture_id, description, collateral_type,
                        appraised_value_cents, valuation_date="2026-04-01"):
    resp = api_client.create_collateral_item(
        create_collateral_item_payload(
            indenture_id, description=description, collateral_type=collateral_type,
            appraised_value_cents=appraised_value_cents, valuation_date=valuation_date),
        OFFICER)
    return get_success_data(resp)


def create_release_request(item, request_type="RELEASE", issuer_ref="issuer-1", **overrides):
    """Create a release/substitution request with a fresh OCC version read."""
    if request_type == "SUBSTITUTION":
        payload = create_substitution_request_payload(
            item["id"], expected_collateral_item_version=item["version"], **overrides)
    else:
        payload = create_release_request_payload(
            item["id"], expected_collateral_item_version=item["version"], **overrides)
    resp = api_client.create_collateral_release_request(payload, make_issuer_headers(issuer_ref))
    return get_success_data(resp)


def verify_release_request(request_id, officer_id="officer-1"):
    resp = api_client.verify_collateral_release_request(
        request_id, make_trust_officer_headers(officer_id))
    return get_success_data(resp)


def decide_release_request(request_id, decision, manager_id="manager-1"):
    resp = api_client.decide_collateral_release_request(
        request_id, {"decision": decision}, make_trust_manager_headers(manager_id))
    return get_success_data(resp)


def effect_release_request(request_id, officer_id="officer-1"):
    resp = api_client.effect_collateral_release_request(
        request_id, make_trust_officer_headers(officer_id))
    return get_success_data(resp)


def setup_collateral_scenario(position_principal=1000000000,
                              item1_type="SECURITIES", item1_value=800000000,
                              item2_type="REAL_ESTATE", item2_value=500000000,
                              request_type="SUBSTITUTION",
                              substitute_value=470000000, issuer_ref="issuer-1"):
    """Active indenture + one position + two pledged items (C1 kept, C2 under
    request) + a SUBMITTED release/substitution request on C2.

    Returns dict(indenture, tranche, account, position, c1, c2, request).
    """
    set_clock(CLOCK_START)
    ctx = setup_indenture_with_positions(
        amounts=(position_principal,), holder_prefixes=("H-A",),
        indenture_overrides={"issuer_ref": issuer_ref}, reset_clock=False)
    indenture, tranche = ctx["indenture"], ctx["tranche"]
    c1 = register_collateral(indenture["id"], "C1", item1_type, item1_value)
    c2 = register_collateral(indenture["id"], "C2", item2_type, item2_value)
    extra = {}
    if request_type == "SUBSTITUTION":
        extra["substitute_appraised_value_cents"] = substitute_value
    request = create_release_request(c2, request_type=request_type, issuer_ref=issuer_ref, **extra)
    return {
        "indenture": indenture, "tranche": tranche,
        "account": ctx["accounts"][0], "position": ctx["positions"][0],
        "c1": c1, "c2": c2, "request": request,
    }


def setup_verified_release_request(**kwargs):
    """Collateral scenario with the request verified by officer-1."""
    ctx = setup_collateral_scenario(**kwargs)
    ctx["request"] = verify_release_request(ctx["request"]["id"], officer_id="officer-1")
    return ctx


# ---------------------------------------------------------------------------
# Tier 3f: Fee invoices
# ---------------------------------------------------------------------------

def create_annual_invoice(indenture_id, officer_id="officer-1", **overrides):
    resp = api_client.create_fee_invoice(
        create_fee_invoice_payload(indenture_id, **overrides),
        make_trust_officer_headers(officer_id))
    return get_success_data(resp)


def issue_invoice(invoice_id, manager_id="manager-1"):
    resp = api_client.issue_fee_invoice(invoice_id, make_trust_manager_headers(manager_id))
    return get_success_data(resp)


def setup_defaulted_indenture(issuer_ref="issuer-2", name="I2",
                              tranche_principal=100000000, default_type="PAYMENT"):
    """Active indenture pushed to DEFAULTED by a confirmed default (PRD §3.5).
    Returns dict(indenture, tranche, case)."""
    set_clock(CLOCK_START)
    ind = create_indenture(name=name, issuer_ref=issuer_ref)
    tranche = create_tranche(ind["id"], series_code="T2",
                             original_principal_cents=tranche_principal)
    get_success_data(api_client.activate_indenture(ind["id"], ADMIN))
    case = declare_default(ind["id"], default_type=default_type, officer_id="officer-1")
    case = confirm_default(case["id"], manager_id="manager-1")
    return {"indenture": get_indenture(ind["id"]), "tranche": tranche, "case": case}


def setup_active_indenture_with_cured_default(issuer_ref="issuer-1", name="I1"):
    """Indenture with a declare -> confirm -> cure history (extraordinary basis
    exists per PRD §3.8) back in ACTIVE. Returns dict(indenture, tranche, case)."""
    set_clock(CLOCK_START)
    ind = create_indenture(name=name, issuer_ref=issuer_ref)
    tranche = create_tranche(ind["id"], series_code="T1", original_principal_cents=1000000000)
    get_success_data(api_client.activate_indenture(ind["id"], ADMIN))
    case = declare_default(ind["id"], default_type="COVENANT_BREACH", officer_id="officer-1")
    confirm_default(case["id"], manager_id="manager-1")
    case = cure_default(case["id"], manager_id="manager-1")
    return {"indenture": get_indenture(ind["id"]), "tranche": tranche, "case": case}


# ---------------------------------------------------------------------------
# Tier 3g: Trustee appointments
# ---------------------------------------------------------------------------

def create_appointment(indenture, incoming_trustee_ref="trustee-beta",
                       reason="RESIGNATION", proposed_effective_date="2026-09-01"):
    """Propose an appointment with a fresh OCC version read of the indenture."""
    current = get_indenture(indenture["id"])
    resp = api_client.create_trustee_appointment(
        create_trustee_appointment_payload(
            indenture["id"], expected_indenture_version=current["version"],
            incoming_trustee_ref=incoming_trustee_ref, reason=reason,
            proposed_effective_date=proposed_effective_date),
        ADMIN)
    return get_success_data(resp)
