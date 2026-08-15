"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints and returns PRD-shaped data dicts extracted with get_success_data().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_attest_engagement_payload,
    create_compliance_report_payload,
    create_obligation_year_payload,
    create_price_quote_payload,
    create_retirement_batch_payload,
    create_rin_lot_payload,
    create_rin_trade_payload,
    create_separation_payload,
    create_state_credit_report_payload,
    create_state_program_payload,
    create_vendor_payload,
)
from .test_users import (
    make_auditor_headers,
    make_compliance_manager_headers,
    make_ops_admin_headers,
    make_trader_headers,
)

# Canonical operator ids used across setups (opaque identities per PRD §2.1).
OPS = make_ops_admin_headers("ops-1")
CM = make_compliance_manager_headers("cm-1")
CM2 = make_compliance_manager_headers("cm-2")
TRADER = make_trader_headers("tr-1")
AUD1 = make_auditor_headers("aud-1")


# ---------------------------------------------------------------------------
# Tier 1: base entities
# ---------------------------------------------------------------------------

def create_account(epa_registration_id=None, company_name=None, **overrides):
    payload = create_account_payload(**overrides)
    if epa_registration_id is not None:
        payload["epa_registration_id"] = epa_registration_id
    if company_name is not None:
        payload["company_name"] = company_name
    resp = api_client.create_compliance_account(payload, OPS)
    return get_success_data(resp)


def create_year(account_id, **overrides):
    payload = create_obligation_year_payload(account_id=account_id, **overrides)
    resp = api_client.create_obligation_year(payload, CM)
    return get_success_data(resp)


def create_account_and_year(year=2026, epa_registration_id=None, **year_overrides):
    """Account + OPEN obligation year. Returns (account, year)."""
    acct = create_account(epa_registration_id=epa_registration_id)
    yr = create_year(acct["id"], year=year, **year_overrides)
    return acct, yr


def create_vendor(account_id, headers=None, **overrides):
    payload = create_vendor_payload(account_id=account_id, **overrides)
    resp = api_client.create_vendor(payload, headers or TRADER)
    return get_success_data(resp)


def create_approved_vendor(account_id, headers=None, **overrides):
    """Vendor onboarded then diligence-APPROVED. Returns vendor dict."""
    ven = create_vendor(account_id, headers=headers, **overrides)
    resp = api_client.record_diligence(ven["id"], {"outcome": "APPROVED"}, CM)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: RIN lots and separations
# ---------------------------------------------------------------------------

def create_generated_lot(account_id, d_code="D6", vintage_year=2026,
                         gallon_qty=100, equivalence_value=1.0):
    payload = create_rin_lot_payload(
        account_id=account_id, d_code=d_code, vintage_year=vintage_year,
        gallon_qty=gallon_qty, equivalence_value=equivalence_value,
    )
    resp = api_client.create_rin_lot(payload, CM)
    return get_success_data(resp)


def separate_lot(lot_id, blended_gallons):
    resp = api_client.create_separation(
        lot_id, create_separation_payload(blended_gallons=blended_gallons), CM,
    )
    return get_success_data(resp)


def create_separated_lot(account_id, d_code="D6", vintage_year=2026,
                         gallon_qty=100, equivalence_value=1.0,
                         separate_gallons=None):
    """GENERATED lot then separation. Default separates the full gallon_qty."""
    lot = create_generated_lot(
        account_id, d_code=d_code, vintage_year=vintage_year,
        gallon_qty=gallon_qty, equivalence_value=equivalence_value,
    )
    separate_lot(lot["id"], gallon_qty if separate_gallons is None else separate_gallons)
    resp = api_client.get_rin_lot(lot["id"], CM)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: trade lifecycle
# ---------------------------------------------------------------------------

def create_trade(account_id, vendor_id, trader_headers=None, **overrides):
    payload = create_rin_trade_payload(
        account_id=account_id, vendor_id=vendor_id, **overrides,
    )
    resp = api_client.create_rin_trade(payload, trader_headers or TRADER)
    return get_success_data(resp)


def pay_trade(trade_id, trader_headers=None):
    resp = api_client.pay_trade(trade_id, trader_headers or TRADER)
    return get_success_data(resp)


def deliver_trade(trade_id, trader_headers=None):
    resp = api_client.deliver_trade(trade_id, trader_headers or TRADER)
    return get_success_data(resp)


def verify_trade(trade_id, verifier_headers=None):
    resp = api_client.verify_trade(trade_id, verifier_headers or CM)
    return get_success_data(resp)


def create_delivered_trade(account_id, vendor_id, trader_headers=None, **overrides):
    """Trade created, paid, delivered. Returns the trade dict (DELIVERED)."""
    trd = create_trade(account_id, vendor_id, trader_headers=trader_headers, **overrides)
    h = trader_headers or TRADER
    pay_trade(trd["id"], trader_headers=h)
    return deliver_trade(trd["id"], trader_headers=h)


def get_purchased_lot_for_trade(trade_id):
    """Fetch the PURCHASED lot minted by delivery of the given trade."""
    resp = api_client.list_rin_lots(CM, params={"trade_id": trade_id})
    lots = get_success_data(resp)
    assert isinstance(lots, list) and len(lots) == 1, (
        f"expected exactly one purchased lot for trade {trade_id}, got {lots!r}"
    )
    return lots[0]


def create_verified_trade(account_id, vendor_id, trader_headers=None,
                          verifier_headers=None, **overrides):
    """Trade created, paid, delivered, verified. Returns (trade, purchased_lot)."""
    trd = create_delivered_trade(
        account_id, vendor_id, trader_headers=trader_headers, **overrides,
    )
    lot = get_purchased_lot_for_trade(trd["id"])
    trd = verify_trade(trd["id"], verifier_headers=verifier_headers or CM)
    return trd, lot


# ---------------------------------------------------------------------------
# Tier 4: retirement batches
# ---------------------------------------------------------------------------

def create_batch(obligation_year_id, category="TOTAL_RENEWABLE", d_code="D6",
                 rin_qty=10):
    payload = create_retirement_batch_payload(
        obligation_year_id=obligation_year_id, category=category,
        d_code=d_code, rin_qty=rin_qty,
    )
    resp = api_client.create_retirement_batch(payload, CM)
    return get_success_data(resp)


def submit_batch(batch_id):
    resp = api_client.submit_retirement_batch(batch_id, CM)
    return get_success_data(resp)


def decide_batch(batch_id, decision):
    resp = api_client.decide_retirement_batch(batch_id, {"decision": decision}, OPS)
    return get_success_data(resp)


def create_submitted_batch(obligation_year_id, category="TOTAL_RENEWABLE",
                           d_code="D6", rin_qty=10):
    batch = create_batch(obligation_year_id, category=category, d_code=d_code,
                         rin_qty=rin_qty)
    return submit_batch(batch["id"])


def create_accepted_batch(obligation_year_id, category="TOTAL_RENEWABLE",
                          d_code="D6", rin_qty=10):
    batch = create_submitted_batch(
        obligation_year_id, category=category, d_code=d_code, rin_qty=rin_qty,
    )
    return decide_batch(batch["id"], "ACCEPT")


# ---------------------------------------------------------------------------
# Tier 5: compliance reports and attest engagements
# ---------------------------------------------------------------------------

def get_year_version(year_id):
    resp = api_client.get_obligation_year(year_id, CM)
    return get_success_data(resp)["version"]


def create_report(obligation_year_id, report_type="QUARTERLY",
                  quarter_end_date="2026-06-30T00:00:00Z",
                  expected_obligation_year_version=None, headers=None):
    if expected_obligation_year_version is None:
        expected_obligation_year_version = get_year_version(obligation_year_id)
    payload = create_compliance_report_payload(
        obligation_year_id=obligation_year_id, report_type=report_type,
        expected_obligation_year_version=expected_obligation_year_version,
    )
    if report_type == "ANNUAL":
        payload.pop("quarter_end_date", None)
    elif quarter_end_date is not None:
        payload["quarter_end_date"] = quarter_end_date
    resp = api_client.create_compliance_report(payload, headers or CM)
    return get_success_data(resp)


def submit_report(report_id, headers=None):
    resp = api_client.submit_compliance_report(report_id, headers or CM)
    return get_success_data(resp)


def decide_report(report_id, decision):
    resp = api_client.decide_compliance_report(report_id, {"decision": decision}, OPS)
    return get_success_data(resp)


def create_engagement(obligation_year_id, auditor_user_id="aud-1", **overrides):
    payload = create_attest_engagement_payload(
        obligation_year_id=obligation_year_id,
        auditor_user_id=auditor_user_id,
        **overrides,
    )
    resp = api_client.create_attest_engagement(payload, CM)
    return get_success_data(resp)


def drive_engagement_to_closed_clean(engagement_id, auditor_user_id="aud-1"):
    """ENGAGED -> FIELDWORK -> FINDINGS_ISSUED(CLEAN) -> CLOSED_CLEAN."""
    aud = make_auditor_headers(auditor_user_id)
    get_success_data(api_client.begin_fieldwork(engagement_id, aud))
    get_success_data(api_client.issue_findings(engagement_id, {"findings": "CLEAN"}, aud))
    resp = api_client.close_engagement(engagement_id, aud)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 6: state overlay + price quotes
# ---------------------------------------------------------------------------

def create_state_program(account_id, **overrides):
    payload = create_state_program_payload(account_id=account_id, **overrides)
    resp = api_client.create_state_program(payload, CM)
    return get_success_data(resp)


def create_credit_report(state_program_id, **overrides):
    payload = create_state_credit_report_payload(
        state_program_id=state_program_id, **overrides,
    )
    resp = api_client.create_state_credit_report(payload, CM)
    return get_success_data(resp)


def create_price_quote(account_id, **overrides):
    payload = create_price_quote_payload(account_id=account_id, **overrides)
    resp = api_client.create_price_quote(payload, OPS)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, OPS)
    return get_success_data(resp)
