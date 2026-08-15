"""Composite setup helpers (multi-step preconditions built only from
PRD-declared endpoints). Every helper replays from an empty database; the
logical clock starts at 2026-08-01T00:00:00Z before any adjustment
(PRD §2.5)."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_owner_payload,
    create_dormancy_rule_payload,
    create_property_payload,
    create_contact_event_payload,
    create_report_payload,
    create_securities_detail_payload,
)
from .test_users import TEST_USERS, make_claimant_headers

HA = TEST_USERS["holder_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
SA = TEST_USERS["state_auditor_headers"]
TO = TEST_USERS["treasury_ops_headers"]
CE = TEST_USERS["claims_examiner_headers"]
AP = TEST_USERS["claims_approver_headers"]
READER = TEST_USERS["reader_headers"]

# The clock reading used across fixtures to expire a letter sent at the
# default clock: sent 2026-08-01, response_deadline 2026-08-31, so a sweep at
# 2026-09-01 expires it (PRD §3.2 pass three).
EXPIRY_CLOCK = "2026-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: single-resource primitives
# ---------------------------------------------------------------------------

def create_owner(state_code="CA", full_name="Test Owner", **overrides):
    payload = create_owner_payload(
        full_name=full_name, state_code=state_code,
        last_known_address=f"1 Main St, {state_code}", **overrides,
    )
    return get_success_data(api_client.create_owner(payload, CO), 201)


def create_rule(state_code="CA", property_type="SAVINGS", dormancy_years=3,
                effective_from="2020-01-01", **overrides):
    payload = create_dormancy_rule_payload(
        state_code=state_code, property_type=property_type,
        dormancy_years=dormancy_years, effective_from=effective_from, **overrides,
    )
    return get_success_data(api_client.create_dormancy_rule(payload, HA), 201)


def create_property(owner_id, property_type="SAVINGS", state_code="CA",
                    original_value_cents=60000, last_contact_date="2023-03-15"):
    payload = create_property_payload(
        owner_id=owner_id, property_type=property_type, state_code=state_code,
        original_value_cents=original_value_cents,
        last_contact_date=last_contact_date,
    )
    return get_success_data(api_client.create_property(payload, CO), 201)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, HA), 200)


def run_sweep():
    return get_success_data(api_client.run_dormancy_sweep(HA), 200)


def send_letter(property_id):
    return get_success_data(api_client.create_letter(property_id, CO), 201)


def record_contact(property_id, contact_type="WITHDRAWAL",
                   contact_date="2026-08-01", evidence_ref="ev-1",
                   headers=None):
    payload = create_contact_event_payload(
        contact_type=contact_type, contact_date=contact_date,
        evidence_ref=evidence_ref,
    )
    return get_success_data(
        api_client.create_contact_event(property_id, payload, headers or CO), 201
    )


def create_report(state_code="CA", report_year=2026):
    payload = create_report_payload(state_code=state_code, report_year=report_year)
    return get_success_data(api_client.create_report(payload, CO), 201)


def get_report(report_id):
    return get_success_data(api_client.get_report(report_id, READER), 200)


def get_property(property_id):
    return get_success_data(api_client.get_property(property_id, READER), 200)


def add_line_item(report_id, property_id, expected_report_version=None):
    """Add a line with a fresh OCC version unless one is pinned explicitly."""
    if expected_report_version is None:
        expected_report_version = get_report(report_id)["version"]
    payload = {
        "property_id": property_id,
        "expected_report_version": expected_report_version,
    }
    return get_success_data(api_client.add_line_item(report_id, payload, CO), 201)


def submit_report(report_id):
    return get_success_data(api_client.submit_report(report_id, CO), 200)


def accept_report(report_id, headers=None):
    return get_success_data(api_client.accept_report(report_id, headers or SA), 200)


def create_remittance(report_id, amount_cents):
    return get_success_data(
        api_client.create_remittance(report_id, {"amount_cents": amount_cents}, TO), 201
    )


def confirm_remittance(remittance_id):
    return get_success_data(api_client.confirm_remittance(remittance_id, SA), 200)


def create_claim(property_id, owner_id, **overrides):
    payload = {"property_id": property_id}
    payload.update(overrides)
    return get_success_data(
        api_client.create_claim(payload, make_claimant_headers(owner_id)), 201
    )


def start_claim_review(claim_id, headers=None):
    return get_success_data(api_client.start_claim_review(claim_id, headers or CE), 200)


# ---------------------------------------------------------------------------
# Tier 1: state progression — dormant / reportable property
# ---------------------------------------------------------------------------

def create_dormant_property(owner=None, state_code="CA", property_type="SAVINGS",
                            original_value_cents=60000,
                            last_contact_date="2023-03-15",
                            dormancy_years=3, rule_overrides=None):
    """Rule + owner + property + one sweep at the default clock -> DORMANT.

    Returns (rule, owner, property). Only for over-threshold values when the
    caller next wants the letter path; the sweep leaves the property DORMANT
    (one step per sweep, PRD §3.2).
    """
    rule = create_rule(state_code=state_code, property_type=property_type,
                       dormancy_years=dormancy_years, **(rule_overrides or {}))
    if owner is None:
        owner = create_owner(state_code=state_code)
    prop = create_property(
        owner["id"], property_type=property_type, state_code=state_code,
        original_value_cents=original_value_cents,
        last_contact_date=last_contact_date,
    )
    run_sweep()
    return rule, owner, prop


def create_reportable_property(owner=None, state_code="CA", property_type="SAVINGS",
                               original_value_cents=60000,
                               last_contact_date="2023-03-15",
                               dormancy_years=3, rule_overrides=None,
                               with_securities=None):
    """Full letter path: DORMANT -> DUE_DILIGENCE -> (letter EXPIRED) REPORTABLE.

    Letter is sent at the default clock 2026-08-01 (inside the default send
    window); the clock then advances to 2026-09-01 and a second sweep expires
    it. Returns (rule, owner, property, letter).
    """
    rule, owner, prop = create_dormant_property(
        owner=owner, state_code=state_code, property_type=property_type,
        original_value_cents=original_value_cents,
        last_contact_date=last_contact_date, dormancy_years=dormancy_years,
        rule_overrides=rule_overrides,
    )
    if with_securities is not None:
        detail = get_success_data(
            api_client.create_securities_detail(
                prop["id"], create_securities_detail_payload(**with_securities), CO
            ),
            201,
        )
    letter = send_letter(prop["id"])
    set_clock(EXPIRY_CLOCK)
    run_sweep()
    return rule, owner, prop, letter


# ---------------------------------------------------------------------------
# Tier 2/3: report lifecycle — REPORTED and REMITTED properties
# ---------------------------------------------------------------------------

def create_reportable_properties(line_values, owner=None, state_code="CA",
                                 property_type="SAVINGS",
                                 last_contact_date="2023-03-15",
                                 dormancy_years=3, rule_overrides=None):
    """N same-rule cash properties driven to REPORTABLE together.

    All properties are created while the clock is at its default, swept once
    to DORMANT, lettered, then a second sweep at 2026-09-01 expires every
    letter (PRD §3.2: one dormancy step per sweep). Returns
    (rule, owner, [properties], [letters]).
    """
    rule = create_rule(state_code=state_code, property_type=property_type,
                       dormancy_years=dormancy_years, **(rule_overrides or {}))
    if owner is None:
        owner = create_owner(state_code=state_code)
    props = [
        create_property(owner["id"], property_type=property_type,
                        state_code=state_code, original_value_cents=v,
                        last_contact_date=last_contact_date)
        for v in line_values
    ]
    run_sweep()  # all ACTIVE -> DORMANT at the default clock
    letters = [send_letter(p["id"]) for p in props]
    set_clock(EXPIRY_CLOCK)
    run_sweep()  # every letter EXPIRED; properties REPORTABLE
    return rule, owner, props, letters


def setup_draft_report_with_lines(line_values, state_code="CA",
                                  property_type="SAVINGS", report_year=2026,
                                  last_contact_date="2023-03-15",
                                  rule_overrides=None):
    """REPORTABLE properties + DRAFT report + one INCLUDED line each.

    Returns dict(rule, owner, report, properties, lines).
    """
    rule, owner, props, letters = create_reportable_properties(
        line_values, state_code=state_code, property_type=property_type,
        last_contact_date=last_contact_date, rule_overrides=rule_overrides,
    )
    report = create_report(state_code=state_code, report_year=report_year)
    lines = [add_line_item(report["id"], p["id"]) for p in props]
    return {"rule": rule, "owner": owner, "report": report,
            "properties": props, "lines": lines}


def setup_reported_property(owner=None, state_code="CA", property_type="SAVINGS",
                            original_value_cents=60000,
                            last_contact_date="2023-03-15",
                            report_year=2026, with_securities=None,
                            rule_overrides=None):
    """Property REPORTABLE -> DRAFT report -> line -> submit -> accept.

    The property ends REPORTED. Returns dict(report, lines, properties, owner).
    """
    rule, owner, prop, letter = create_reportable_property(
        owner=owner, state_code=state_code, property_type=property_type,
        original_value_cents=original_value_cents,
        last_contact_date=last_contact_date, rule_overrides=rule_overrides,
        with_securities=with_securities,
    )
    report = create_report(state_code=state_code, report_year=report_year)
    line = add_line_item(report["id"], prop["id"])
    submit_report(report["id"])
    accept_report(report["id"])
    return {"report": report, "lines": [line], "properties": [prop],
            "owner": owner, "rule": rule}


def submit_and_accept(report_id, accept_headers=None):
    submitted = submit_report(report_id)
    accepted = accept_report(report_id, headers=accept_headers)
    return submitted, accepted


def setup_remitted_cash_property(original_value_cents=100000,
                                 state_code="CA", property_type="SAVINGS",
                                 report_year=2026, remittance_amount=None):
    """Full cash chain through remittance confirm: property REMITTED.

    Returns dict(owner, property, report, line, remittance).
    """
    rule, owner, prop, letter = create_reportable_property(
        state_code=state_code, property_type=property_type,
        original_value_cents=original_value_cents,
    )
    report = create_report(state_code=state_code, report_year=report_year)
    line = add_line_item(report["id"], prop["id"])
    submit_report(report["id"])
    accept_report(report["id"])
    amount = original_value_cents if remittance_amount is None else remittance_amount
    remittance = create_remittance(report["id"], amount)
    confirm_remittance(remittance["id"])
    return {"owner": owner, "property": prop, "report": report,
            "line": line, "remittance": remittance, "rule": rule}


def setup_under_review_claim(original_value_cents=150000, examiner_headers=None,
                             **kwargs):
    """Remitted cash property + claim SUBMITTED by its owner + UNDER_REVIEW.

    Returns dict with the remitted chain plus claim.
    """
    chain = setup_remitted_cash_property(original_value_cents=original_value_cents)
    claim = create_claim(chain["property"]["id"], chain["owner"]["id"])
    start_claim_review(claim["id"], headers=examiner_headers)
    chain["claim"] = get_success_data(api_client.get_claim(claim["id"], READER), 200)
    return chain


def setup_reported_securities_property(shares=100, close_price=4500, dividends=12500,
                                       original_value_cents=462500,
                                       cusip="ESC1828A", state_code="NV",
                                       report_year=2026):
    """Securities property REPORTED via an ACCEPTED report; line is INCLUDED
    with the provisional valuation. Returns dict(owner, property, detail,
    report, line, rule).
    """
    detail_kwargs = {
        "cusip": cusip, "shares_quantity": shares,
        "last_close_price_cents": close_price, "accrued_dividends_cents": dividends,
    }
    rule, owner, prop, letter = create_reportable_property(
        state_code=state_code, property_type="BROKERAGE_SHARES",
        original_value_cents=original_value_cents, with_securities=detail_kwargs,
    )
    report = create_report(state_code=state_code, report_year=report_year)
    line = add_line_item(report["id"], prop["id"])
    submit_report(report["id"])
    accept_report(report["id"])
    detail = get_success_data(api_client.get_securities_detail(prop["id"], READER), 200)
    return {"owner": owner, "property": prop, "detail": detail[0],
            "report": report, "line": line, "rule": rule}


def setup_accepted_single_line_report(value=80000, state_code="CA",
                                      report_year=2026):
    """One REPORTABLE cash property -> DRAFT report -> line -> submit -> accept.

    Returns dict(report, line, property, owner, accepted_version).
    """
    _, owner, prop, _ = create_reportable_property(
        state_code=state_code, original_value_cents=value
    )
    report = create_report(state_code=state_code, report_year=report_year)
    line = add_line_item(report["id"], prop["id"])
    submit_report(report["id"])
    accepted = accept_report(report["id"])
    return {"report": report, "line": line, "property": prop, "owner": owner,
            "accepted_version": accepted["version"]}


def setup_remitted_securities_property(shares=100, close_price=4500, dividends=12500,
                                       fee=2500, exec_price=4700,
                                       original_value_cents=462500,
                                       state_code="NV", report_year=2026):
    """Full securities chain: REPORTED -> order -> execute -> settle ->
    remittance of net proceeds -> confirm. Property ends REMITTED.

    Returns dict with the reported chain plus order and remittance.
    """
    chain = setup_reported_securities_property(
        shares=shares, close_price=close_price, dividends=dividends,
        original_value_cents=original_value_cents, state_code=state_code,
        report_year=report_year,
    )
    order = get_success_data(
        api_client.create_liquidation_order(
            {"property_id": chain["property"]["id"], "liquidation_fee_cents": fee}, TO
        ),
        201,
    )
    get_success_data(
        api_client.execute_liquidation_order(
            order["id"], {"execution_price_cents_per_share": exec_price}, TO
        ),
        200,
    )
    settled = get_success_data(api_client.settle_liquidation_order(order["id"], TO), 200)
    remittance = create_remittance(chain["report"]["id"], settled["net_proceeds_cents"])
    confirm_remittance(remittance["id"])
    chain["order"] = settled
    chain["remittance"] = remittance
    return chain
