"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its 2026-08-01T00:00:00Z default). Setup
calls use get_success_data so failures surface as clear "Setup failed"
errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_advance_payload,
    create_agreement_payload,
    create_assignment_payload,
    create_certification_payload,
    create_claim_payload,
    create_dealer_payload,
    create_lead_payload,
    create_parts_return_payload,
    create_sales_target_payload,
    create_unit_sale_payload,
)
from .test_users import TEST_USERS, make_dealer_user_headers

ADMIN = TEST_USERS["oem_admin_headers"]
SALES_OPS = TEST_USERS["sales_ops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

DEFAULT_AGREEMENT_WINDOW = ("2026-01-01", "2026-12-31")
DEFAULT_ASSIGNMENT_WINDOW = ("2026-01-01", "2026-12-31")


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected=None):
    data = get_success_data(resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, "
            f"got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — dealer onboarding ladder (create -> certify -> agree -> activate)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PRD 2.6)."""
    return _ok("set_clock", api_client.set_clock(
        {"to_iso8601": to_iso8601}, ADMIN))


def create_dealer(dealer_code, name=None, region="West",
                  credit_limit_cents=500000, min_stock_value_cents=0):
    resp = api_client.create_dealer(
        create_dealer_payload(
            name=name or f"Dealer {dealer_code}",
            dealer_code=dealer_code,
            region=region,
            credit_limit_cents=credit_limit_cents,
            min_stock_value_cents=min_stock_value_cents,
        ),
        ADMIN,
    )
    return _ok("create_dealer", resp, expected="ONBOARDING")


def get_dealer(dealer_id):
    return _ok("get_dealer", api_client.get_dealer(dealer_id, ADMIN))


def get_agreement(agreement_id):
    return _ok("get_agreement",
               api_client.get_agreement(agreement_id, ADMIN))


def get_assignment(assignment_id):
    return _ok("get_assignment",
               api_client.get_assignment(assignment_id, ADMIN))


def register_certification(dealer_id, cert_code, earned_on="2026-01-10",
                           expires_on="2028-01-10"):
    resp = api_client.create_certification(
        create_certification_payload(
            dealer_id=dealer_id, cert_code=cert_code,
            earned_on=earned_on, expires_on=expires_on,
        ),
        make_dealer_user_headers(dealer_id),
    )
    return _ok("register_certification", resp, expected="PENDING_VERIFICATION")


def verify_certification(certification_id):
    resp = api_client.decide_certification(
        certification_id, {"decision": "VERIFY"}, AUDITOR)
    return _ok("verify_certification", resp, expected="ACTIVE")


def create_and_verify_certification(dealer_id, cert_code, **kwargs):
    cert = register_certification(dealer_id, cert_code, **kwargs)
    return verify_certification(cert["id"])


def create_agreement(dealer_id, agreement_code,
                     effective_date=DEFAULT_AGREEMENT_WINDOW[0],
                     expiry_date=DEFAULT_AGREEMENT_WINDOW[1]):
    resp = api_client.create_agreement(
        create_agreement_payload(
            dealer_id=dealer_id, agreement_code=agreement_code,
            effective_date=effective_date, expiry_date=expiry_date,
        ),
        ADMIN,
    )
    return _ok("create_agreement", resp, expected="DRAFT")


def activate_agreement(agreement_id, expected_dealer_version,
                       supersede_existing=None):
    payload = {"expected_dealer_version": expected_dealer_version}
    if supersede_existing is not None:
        payload["supersede_existing"] = supersede_existing
    resp = api_client.activate_agreement(agreement_id, payload, ADMIN)
    return _ok("activate_agreement", resp, expected="ACTIVE")


def setup_active_dealer(dealer_code, *, name=None, region="West",
                        credit_limit_cents=500000, min_stock_value_cents=0,
                        cert_codes=("CTE-1", "CTE-2"),
                        agreement_code=None,
                        effective_date=DEFAULT_AGREEMENT_WINDOW[0],
                        expiry_date=DEFAULT_AGREEMENT_WINDOW[1]):
    """Dealer + verified certs + activated agreement -> Dealer ACTIVE.

    Returns dict(dealer, agreement, certifications). The returned dealer is
    re-read after activation so its version/status reflect the activation.
    """
    dealer = create_dealer(
        dealer_code, name=name, region=region,
        credit_limit_cents=credit_limit_cents,
        min_stock_value_cents=min_stock_value_cents,
    )
    certs = [create_and_verify_certification(dealer["id"], code)
             for code in cert_codes]
    agreement = create_agreement(
        dealer["id"], agreement_code or f"AGR-{dealer_code}",
        effective_date, expiry_date)
    activate_agreement(agreement["id"], dealer["version"])
    dealer = get_dealer(dealer["id"])
    return {"dealer": dealer, "agreement": agreement,
            "certifications": certs}


# ---------------------------------------------------------------------------
# Tier 2 — territory coverage and leads
# ---------------------------------------------------------------------------

def create_assignment(dealer_id, agreement_id, territory_code,
                      coverage_type="EXCLUSIVE",
                      starts_on=DEFAULT_ASSIGNMENT_WINDOW[0],
                      ends_on=DEFAULT_ASSIGNMENT_WINDOW[1]):
    resp = api_client.create_assignment(
        create_assignment_payload(
            dealer_id, agreement_id,
            territory_code=territory_code, coverage_type=coverage_type,
            starts_on=starts_on, ends_on=ends_on,
        ),
        ADMIN,
    )
    return _ok("create_assignment", resp, expected="ACTIVE")


def setup_active_dealer_with_assignment(dealer_code, territory_code,
                                        coverage_type="EXCLUSIVE", **kwargs):
    """ACTIVE dealer + ACTIVE agreement + ACTIVE assignment on the territory."""
    ctx = setup_active_dealer(dealer_code, **kwargs)
    ctx["assignment"] = create_assignment(
        ctx["dealer"]["id"], ctx["agreement"]["id"], territory_code,
        coverage_type=coverage_type)
    return ctx


def create_lead(territory_code, product_line="DOZER",
                estimated_value_cents=100000, contact_name="Pat"):
    resp = api_client.create_lead(
        create_lead_payload(
            territory_code=territory_code, product_line=product_line,
            estimated_value_cents=estimated_value_cents,
            contact_name=contact_name,
        ),
        SALES_OPS,
    )
    return _ok("create_lead", resp, expected="NEW")


def get_lead(lead_id):
    return _ok("get_lead", api_client.get_lead(lead_id, ADMIN))


def route_lead(lead_id):
    """Route (or re-route); may land ROUTED or ORPHANED — caller asserts."""
    return _ok("route_lead", api_client.route_lead(lead_id, SALES_OPS))


def setup_routed_lead(dealer_code, territory_code, coverage_type="EXCLUSIVE",
                      **kwargs):
    """ACTIVE dealer with territory coverage + one ROUTED lead."""
    ctx = setup_active_dealer_with_assignment(
        dealer_code, territory_code, coverage_type=coverage_type, **kwargs)
    lead = create_lead(territory_code)
    lead = route_lead(lead["id"])
    assert lead["status"] == "ROUTED", (
        f"Setup failed at route_lead: expected ROUTED, got {lead['status']}"
    )
    ctx["lead"] = lead
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — sales targets and unit sales
# ---------------------------------------------------------------------------

def create_sales_target(dealer_id, period_year=2026, period_quarter=3,
                        target_units=5):
    resp = api_client.create_sales_target(
        create_sales_target_payload(
            dealer_id=dealer_id, period_year=period_year,
            period_quarter=period_quarter, target_units=target_units,
        ),
        SALES_OPS,
    )
    return _ok("create_sales_target", resp, expected="OPEN")


def get_sales_target(target_id):
    return _ok("get_sales_target",
               api_client.get_sales_target(target_id, ADMIN))


def close_sales_target(target_id):
    """Close a target; may land CLOSED_MET or CLOSED_MISSED — caller asserts."""
    return _ok("close_sales_target",
               api_client.close_sales_target(target_id, SALES_OPS))


def report_sale(dealer_id, unit_serial, sale_date="2026-08-05",
                list_price_cents=10000):
    resp = api_client.create_unit_sale(
        create_unit_sale_payload(
            dealer_id=dealer_id, unit_serial=unit_serial,
            sale_date=sale_date, list_price_cents=list_price_cents,
        ),
        make_dealer_user_headers(dealer_id),
    )
    return _ok("report_sale", resp, expected="REPORTED")


def get_unit_sale(sale_id):
    return _ok("get_unit_sale", api_client.get_unit_sale(sale_id, ADMIN))


def decide_sale(sale_id, decision):
    expected = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    resp = api_client.decide_unit_sale(sale_id, {"decision": decision},
                                       SALES_OPS)
    return _ok("decide_sale", resp, expected=expected)


def accept_sale(sale_id):
    """Accept a REPORTED sale. Returns the ACCEPTED sale."""
    return decide_sale(sale_id, "ACCEPT")


def report_and_accept_sale(dealer_id, unit_serial, sale_date="2026-08-05",
                           list_price_cents=10000):
    sale = report_sale(dealer_id, unit_serial, sale_date, list_price_cents)
    return decide_sale(sale["id"], "ACCEPT")


def setup_dealer_with_open_target(dealer_code, target_units=5, **kwargs):
    """ACTIVE dealer + OPEN Q3-2026 target. Returns ctx with target."""
    ctx = setup_active_dealer(dealer_code, **kwargs)
    ctx["target"] = create_sales_target(
        ctx["dealer"]["id"], target_units=target_units)
    return ctx


def setup_dealer_with_closed_quarters(dealer_code, quarters=(1, 2),
                                      target_units=10, **kwargs):
    """ACTIVE dealer with the given 2026 quarters created and CLOSED.

    With no sales reported, every quarter closes CLOSED_MISSED; the default
    clock (2026-08-01) is past Q1/Q2 quarter-end, satisfying the close gate.
    """
    ctx = setup_active_dealer(dealer_code, **kwargs)
    targets = []
    for quarter in quarters:
        target = create_sales_target(
            ctx["dealer"]["id"], period_quarter=quarter,
            target_units=target_units)
        targets.append(close_sales_target(target["id"]))
    ctx["closed_targets"] = targets
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — floor-plan financing
# ---------------------------------------------------------------------------

def create_advance(dealer_id, unit_serial, advance_cents=50000):
    resp = api_client.create_advance(
        create_advance_payload(
            dealer_id=dealer_id, unit_serial=unit_serial,
            advance_cents=advance_cents,
        ),
        ADMIN,
    )
    return _ok("create_advance", resp, expected="OPEN")


def get_advance(advance_id):
    return _ok("get_advance", api_client.get_advance(advance_id, ADMIN))


def record_payment(advance_id, amount_cents):
    """Curtailment or payoff; status depends on amount — caller asserts."""
    return _ok("record_payment", api_client.record_advance_payment(
        advance_id, {"amount_cents": amount_cents}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 5 — warranty claim lifecycle
# ---------------------------------------------------------------------------

def create_claim(dealer_id, unit_serial, parts_cost_cents=10000,
                 labor_hours=0, failure_description="test failure"):
    resp = api_client.create_claim(
        create_claim_payload(
            dealer_id=dealer_id, unit_serial=unit_serial,
            parts_cost_cents=parts_cost_cents, labor_hours=labor_hours,
            failure_description=failure_description,
        ),
        make_dealer_user_headers(dealer_id),
    )
    return _ok("create_claim", resp, expected="SUBMITTED")


def get_claim(claim_id):
    return _ok("get_claim", api_client.get_claim(claim_id, ADMIN))


def decide_claim(claim_id, decision):
    expected = "APPROVED" if decision == "APPROVE" else "REJECTED"
    resp = api_client.decide_claim(claim_id, {"decision": decision}, AUDITOR)
    return _ok("decide_claim", resp, expected=expected)


def pay_claim(claim_id):
    return _ok("pay_claim", api_client.pay_claim(claim_id, AUDITOR),
               expected="PAID")


def flag_claim(claim_id):
    return _ok("flag_claim", api_client.flag_claim_audit(claim_id, AUDITOR),
               expected="AUDIT_FLAGGED")


def chargeback_claim(claim_id, finding="FULL"):
    return _ok("chargeback_claim", api_client.chargeback_claim(
        claim_id, {"finding": finding}, AUDITOR), expected="CHARGED_BACK")


def setup_claim_in_state(dealer_id, unit_serial, target_state,
                         parts_cost_cents=10000, labor_hours=0,
                         finding="FULL"):
    """Walk a claim to SUBMITTED / APPROVED / PAID / AUDIT_FLAGGED /
    CHARGED_BACK. Returns the claim as of the target state."""
    claim = create_claim(dealer_id, unit_serial, parts_cost_cents, labor_hours)
    if target_state == "SUBMITTED":
        return claim
    claim = decide_claim(claim["id"], "APPROVE")
    if target_state == "APPROVED":
        return claim
    claim = pay_claim(claim["id"])
    if target_state == "PAID":
        return claim
    claim = flag_claim(claim["id"])
    if target_state == "AUDIT_FLAGGED":
        return claim
    claim = chargeback_claim(claim["id"], finding)
    return claim


# ---------------------------------------------------------------------------
# Tier 6 — parts stocking, purchases, returns
# ---------------------------------------------------------------------------

def record_stock_audit(dealer_id, observed_stock_value_cents):
    return _ok("record_stock_audit", api_client.record_stock_audit(
        dealer_id, {"observed_stock_value_cents": observed_stock_value_cents},
        AUDITOR))


def make_stock_compliant(dealer_id, observed_stock_value_cents=1500):
    """Record a passing stock audit (observed >= min) -> stock_compliant true."""
    return record_stock_audit(dealer_id, observed_stock_value_cents)


def record_parts_purchase(dealer_id, amount_cents):
    return _ok("record_parts_purchase", api_client.record_parts_purchase(
        dealer_id, {"amount_cents": amount_cents}, ADMIN))


def create_parts_return(dealer_id, return_year=2026, lines=None):
    payload = create_parts_return_payload(dealer_id=dealer_id,
                                          return_year=return_year)
    if lines is not None:
        payload["lines"] = lines
    resp = api_client.create_parts_return(
        payload, make_dealer_user_headers(dealer_id))
    return _ok("create_parts_return", resp, expected="DRAFT")


def get_parts_return(return_id):
    return _ok("get_parts_return",
               api_client.get_parts_return(return_id, ADMIN))


def submit_parts_return(return_id, dealer_id):
    return _ok("submit_parts_return", api_client.submit_parts_return(
        return_id, make_dealer_user_headers(dealer_id)), expected="SUBMITTED")


def decide_parts_return(return_id, decision):
    expected = "CREDITED" if decision == "CREDIT" else "REJECTED"
    resp = api_client.decide_parts_return(return_id, {"decision": decision},
                                          SALES_OPS)
    return _ok("decide_parts_return", resp, expected=expected)


def setup_dealer_return_ready(dealer_code, *, purchases_cents=10000,
                              min_stock_value_cents=1000,
                              observed_stock_value_cents=1500, **kwargs):
    """ACTIVE dealer that is stock-compliant with parts purchases recorded,
    ready for return submission. Returns ctx."""
    ctx = setup_active_dealer(
        dealer_code, min_stock_value_cents=min_stock_value_cents, **kwargs)
    make_stock_compliant(ctx["dealer"]["id"], observed_stock_value_cents)
    record_parts_purchase(ctx["dealer"]["id"], purchases_cents)
    ctx["dealer"] = get_dealer(ctx["dealer"]["id"])
    return ctx
