"""Composite setup helpers: multi-step PRD workflow preconditions.

Every test starts against an empty database; these fixtures build the
canonical TX chain (license -> broker -> insured -> policy -> case -> screening
-> LE report -> UW approval -> disclosures -> offer -> acceptance -> closing
package -> escrow) using only PRD-declared endpoints.

Clock discipline: the startup default clock is 2026-08-01T00:00:00Z
(PRD §2.4). Tests that need escrow release wait by moving the clock; fixtures
therefore accept the clock checkpoints used by each scenario.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .factories import (
    DEFAULTS,
    DISCLOSURE_PACKET_TYPES,
    TX_REQUIRED_DOC_TYPES,
    create_broker_payload,
    create_insured_payload,
    create_policy_payload,
    create_license_payload,
    create_offer_payload,
    create_portfolio_payload,
)
from .test_users import (
    TEST_USERS,
    make_broker_headers,
    make_compliance_headers,
    make_finance_headers,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
CM = TEST_USERS["case_manager_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
CO_1 = make_compliance_headers("co_1")
FO_1 = make_finance_headers("fo_1")


def set_clock(to_iso8601):
    resp = _api.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_broker(**overrides) -> dict:
    return get_success_data(_api.create_broker(create_broker_payload(**overrides), ADMIN))


def create_investor(**overrides) -> dict:
    from .factories import create_investor_payload
    return get_success_data(_api.create_investor(create_investor_payload(**overrides), ADMIN))


def create_tx_license(**overrides) -> dict:
    return get_success_data(_api.create_license(create_license_payload(**overrides), ADMIN))


def create_broker_owned_insured(broker, **overrides) -> dict:
    bh = make_broker_headers(broker["id"])
    return get_success_data(_api.create_insured(create_insured_payload(**overrides), bh))


def create_policy_for(broker, insured, **overrides) -> dict:
    bh = make_broker_headers(broker["id"])
    return get_success_data(_api.create_policy(create_policy_payload(insured["id"], **overrides), bh))


def create_case_for(broker, policy) -> dict:
    bh = make_broker_headers(broker["id"])
    return get_success_data(_api.create_case({"policy_id": policy["id"]}, bh))


def submit_case(broker, case) -> dict:
    return get_success_data(_api.submit_case(case["id"], make_broker_headers(broker["id"])))


def run_screening(case) -> dict:
    return get_success_data(_api.create_screening(case["id"], CM))


def order_and_deliver_le(case, tier="A", base_le_months=DEFAULTS["LE_BASE"],
                         impairment_debits=None) -> dict:
    debits = list(DEFAULTS["LE_DEBITS"]) if impairment_debits is None else impairment_debits
    report = get_success_data(_api.order_le_report(case["id"], {"underwriter_tier": tier}, UW))
    delivered = get_success_data(
        _api.deliver_le_report(
            report["id"],
            {"base_le_months": base_le_months, "impairment_debits": debits},
            UW,
        )
    )
    return delivered


def approve_case(case) -> dict:
    return get_success_data(_api.uw_decision(case["id"], {"decision": "APPROVE"}, UW))


def deliver_disclosures(case) -> dict:
    return get_success_data(
        _api.deliver_disclosures(case["id"], {"packet_types": list(DISCLOSURE_PACKET_TYPES)}, CM)
    )


def create_offer(case, amount_cents=DEFAULTS["OFFER_AMOUNT"], **extra) -> dict:
    payload = create_offer_payload(amount_cents=amount_cents, **extra)
    return get_success_data(_api.create_offer(case["id"], payload, UW))


def sign_documents(package_id, doc_types=None, exclude=None):
    """Record signatures for the given checklist rows (default: all TX-required)."""
    docs = list(TX_REQUIRED_DOC_TYPES if doc_types is None else doc_types)
    if exclude:
        docs = [d for d in docs if d not in set(exclude)]
    for doc_type in docs:
        get_success_data(_api.record_signature(package_id, {"doc_type": doc_type}, CM))


def get_case_package(case_id) -> dict:
    data, _meta = _unwrap_list(_api.get_case_closing_package(case_id, CM))
    assert len(data) == 1, f"expected exactly one closing package for case {case_id}, got {len(data)}"
    return data[0]


def get_case_escrow(case_id) -> dict:
    data, _meta = _unwrap_list(_api.get_case_escrow_account(case_id, CM))
    assert len(data) == 1, f"expected exactly one escrow account for case {case_id}, got {len(data)}"
    return data[0]


def _unwrap_list(resp):
    body = resp.json()
    return body["data"], body.get("meta", {})


def current_case_version(case_id) -> int:
    return get_success_data(_api.get_case(case_id, PM))["version"]


def current_portfolio_version(portfolio_id) -> int:
    return get_success_data(_api.get_portfolio(portfolio_id, PM))["version"]


# ----------------------------------------------------------------------------
# Tier 1/2: registry + case progression
# ----------------------------------------------------------------------------

def setup_broker_insured_policy(state="TX", policy_overrides=None, insured_overrides=None,
                                broker_overrides=None, with_license=True,
                                license_overrides=None, return_license=False):
    """License (TX by default) + broker + broker-owned insured + one policy.

    Returns (broker, insured, policy), or (broker, insured, policy, license)
    when return_license is True."""
    lic = None
    if with_license:
        lic_kw = {"state_code": state}
        if license_overrides:
            lic_kw.update(license_overrides)
        lic = create_tx_license(**lic_kw)
    broker = create_broker(**(broker_overrides or {}))
    insured = create_broker_owned_insured(broker, state_code=state, **(insured_overrides or {}))
    policy = create_policy_for(broker, insured, **(policy_overrides or {}))
    if return_license:
        return broker, insured, policy, lic
    return broker, insured, policy


def setup_case_in_underwriting(**kwargs):
    """Canonical chain through screening PASS: case in UNDERWRITING.

    Returns (broker, insured, policy, case)."""
    broker, insured, policy, lic = setup_broker_insured_policy(return_license=True, **kwargs)
    case = create_case_for(broker, policy)
    submit_case(broker, case)
    run_screening(case)
    case = get_success_data(_api.get_case(case["id"], CM))
    return broker, insured, policy, case


def setup_case_marketed(with_disclosures=True, with_offer=False,
                        offer_amount=DEFAULTS["OFFER_AMOUNT"], offer_extra=None, **kwargs):
    """Canonical chain through UW APPROVE: case MARKETED with blended LE.

    Returns dict with broker/insured/policy/case/le_report/license
    (+ offer when requested)."""
    broker, insured, policy, lic = setup_broker_insured_policy(return_license=True, **kwargs)
    case = create_case_for(broker, policy)
    submit_case(broker, case)
    run_screening(case)
    le = order_and_deliver_le(case)
    case = approve_case(case)
    if with_disclosures:
        case = deliver_disclosures(case)
    out = {"broker": broker, "insured": insured, "policy": policy, "case": case,
           "le_report": le, "license": lic}
    if with_offer:
        out["offer"] = create_offer(case, offer_amount, **(offer_extra or {}))
    return out


# ----------------------------------------------------------------------------
# Tier 3: closing + escrow lifecycle
# ----------------------------------------------------------------------------

def setup_case_in_closing(portfolio=True, offer_amount=DEFAULTS["OFFER_AMOUNT"],
                          portfolio_method="PROSPECTIVE", portfolio_allocations=None,
                          **kwargs):
    """MARKETED case with disclosures + one offer accepted -> IN_CLOSING,
    ClosingPackage ASSEMBLED and EscrowAccount OPEN created by the cascade.

    Returns dict with broker/insured/policy/case/offer/package/escrow (+portfolio)."""
    ctx = setup_case_marketed(with_disclosures=True, with_offer=False, **kwargs)
    offer = create_offer(ctx["case"], offer_amount)
    accepted = get_success_data(
        _api.accept_offer(offer["id"], {"broker_commission_bps": DEFAULTS["COMMISSION_BPS"]},
                          make_broker_headers(ctx["broker"]["id"]))
    )
    case = get_success_data(_api.get_case(ctx["case"]["id"], CM))
    package = get_case_package(case["id"])
    escrow = get_case_escrow(case["id"])
    ctx.update({"offer": accepted, "case": case, "package": package, "escrow": escrow})
    if portfolio:
        pf = get_success_data(_api.create_portfolio(
            create_portfolio_payload(
                valuation_method=portfolio_method,
                allocations=portfolio_allocations if portfolio_allocations is not None else [],
            ), PM))
        get_success_data(_api.assign_portfolio(case["id"], {"portfolio_id": pf["id"]}, PM))
        ctx["portfolio"] = pf
    return ctx


def setup_package_compliance_review(signed_docs=None, exclude_docs=None, **kwargs):
    """IN_CLOSING with the package advanced to COMPLIANCE_REVIEW."""
    ctx = setup_case_in_closing(**kwargs)
    get_success_data(_api.send_for_signature(ctx["package"]["id"], CM))
    sign_documents(ctx["package"]["id"], doc_types=signed_docs, exclude=exclude_docs)
    get_success_data(_api.submit_review(ctx["package"]["id"], CM))
    ctx["package"] = get_success_data(_api.get_closing_package(ctx["package"]["id"], CM))
    return ctx


def setup_package_approved(**kwargs):
    """IN_CLOSING with the package APPROVED (by compliance user co_1)."""
    ctx = setup_package_compliance_review(**kwargs)
    get_success_data(_api.approve_package(ctx["package"]["id"], CO_1))
    ctx["package"] = get_success_data(_api.get_closing_package(ctx["package"]["id"], CM))
    return ctx


def setup_escrow_funded(clock_after=None, **kwargs):
    """Package APPROVED and escrow FUNDED with the exact expected amount.

    `clock_after` optionally moves the logical clock right after funding (used
    to model funding at the startup default vs. an explicit timestamp)."""
    ctx = setup_package_approved(**kwargs)
    esc = ctx["escrow"]
    funded = get_success_data(
        _api.fund_escrow(esc["id"], {"amount_cents": esc["expected_funding_cents"]}, FO_1)
    )
    ctx["escrow"] = funded
    if clock_after:
        set_clock(clock_after)
    return ctx


def setup_ownership_confirmed(**kwargs):
    """Package APPROVED + escrow FUNDED + CARRIER_SUBMITTED + OWNERSHIP_CONFIRMED.

    Funding happens at whatever clock the chain reached (the startup default
    2026-08-01 unless the caller moved it first), so releasable_at =
    funded_at + 15 days (PRD §3.5)."""
    ctx = setup_escrow_funded(**kwargs)
    get_success_data(_api.submit_carrier(ctx["package"]["id"], CM))
    get_success_data(_api.confirm_ownership(ctx["package"]["id"], CM))
    ctx["package"] = get_success_data(_api.get_closing_package(ctx["package"]["id"], CM))
    return ctx


def setup_case_acquired(release_clock="2026-08-16T00:00:00Z", fund_clock=None,
                        start_clock=None, **kwargs):
    """Full chain to ACQUIRED: package approved, escrow funded, carrier
    submitted, ownership confirmed, clock past releasable_at, escrow released.

    `start_clock` optionally pins the logical clock before any entity is
    created (so LE delivered_at / marketed_at land on that instant).
    `fund_clock` moves the clock to the funding instant (default: the chain's
    current clock, i.e. `start_clock` or the startup default 2026-08-01), so
    releasable_at = fund_clock + 15 days; `release_clock` must be >= it."""
    if start_clock:
        set_clock(start_clock)
    ctx = setup_package_approved(**kwargs)
    if fund_clock:
        set_clock(fund_clock)
    esc = ctx["escrow"]
    ctx["escrow"] = get_success_data(
        _api.fund_escrow(esc["id"], {"amount_cents": esc["expected_funding_cents"]}, FO_1)
    )
    get_success_data(_api.submit_carrier(ctx["package"]["id"], CM))
    get_success_data(_api.confirm_ownership(ctx["package"]["id"], CM))
    set_clock(release_clock)
    get_success_data(_api.release_escrow(ctx["escrow"]["id"], FO_1))
    ctx["escrow"] = get_success_data(_api.get_escrow_account(ctx["escrow"]["id"], CM))
    ctx["case"] = get_success_data(_api.get_case(ctx["case"]["id"], CM))
    ctx["package"] = get_success_data(_api.get_closing_package(ctx["package"]["id"], CM))
    return ctx


# ----------------------------------------------------------------------------
# Tier 4: schedules, tracking, claims
# ----------------------------------------------------------------------------

def create_schedule(case_id, **kwargs) -> dict:
    return get_success_data(
        _api.create_premium_schedule(case_id, {"expected_case_version": current_case_version(case_id)}, PM)
    )


def list_payments(schedule_id):
    """Fetch ALL payment rows of a schedule, paging through the list endpoint.

    PRD §2.3 caps `limit` at 100 with a default of 10, while §3.7 allows up to
    360 payment rows per schedule — a single default-page call cannot return
    them all."""
    rows = []
    offset = 0
    while True:
        data, meta = _unwrap_list(
            _api.list_schedule_payments(schedule_id, CM, params={"limit": 100, "offset": offset})
        )
        rows.extend(data)
        if not meta.get("has_more"):
            return rows
        offset += len(data)


def add_verified_death_event(case_id, channel, event_type, event_date="2026-08-20") -> dict:
    ev = get_success_data(
        _api.create_tracking_event(
            case_id,
            {
                "event_type": event_type,
                "outcome": "DEATH_INDICATED",
                "source_channel": channel,
                "event_date": event_date,
            },
            CM,
        )
    )
    return get_success_data(_api.verify_tracking_event(ev["id"], CO_1))


def setup_case_with_reported_claim(date_of_death="2026-08-20", claim_clock="2026-08-20T00:00:00Z",
                                   **kwargs):
    """ACQUIRED case + one VERIFIED DEATH_INDICATED event + REPORTED claim."""
    ctx = setup_case_acquired(**kwargs)
    set_clock(claim_clock)
    te1 = add_verified_death_event(ctx["case"]["id"], "OBIT", "OBIT_SEARCH", event_date=date_of_death)
    claim = get_success_data(
        _api.create_death_claim(ctx["case"]["id"], {"date_of_death": date_of_death}, CO_1)
    )
    ctx.update({"te1": te1, "claim": claim})
    return ctx


def setup_case_with_filed_claim(date_of_death="2026-08-20", **kwargs):
    """ACQUIRED case + two distinct-channel VERIFIED DEATH_INDICATED events +
    claim VERIFIED + FILED."""
    ctx = setup_case_with_reported_claim(date_of_death=date_of_death, **kwargs)
    te2 = add_verified_death_event(ctx["case"]["id"], "DMF", "DMF_MATCH", event_date=date_of_death)
    claim = get_success_data(
        _api.verify_death_claim(ctx["claim"]["id"], {"certificate_received": True}, CO_1)
    )
    claim = get_success_data(_api.file_death_claim(claim["id"], CM))
    ctx.update({"te2": te2, "claim": claim})
    return ctx
