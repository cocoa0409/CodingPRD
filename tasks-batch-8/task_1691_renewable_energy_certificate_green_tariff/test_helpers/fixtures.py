"""Composite setup helpers for the green power registry test suite.

Most interesting claims require 6-20 API calls of setup (register generator
-> submit -> verify -> reading -> attest -> accept -> mint-run -> accounts ->
transfers -> trades). These helpers encapsulate those chains so tests focus
on assertions. All helpers use get_success_data() so setup failures surface
as clear "Setup step failed" errors.

Identity threading (PRD §2.1): GeneratorOperator calls thread the real
Generator.id through X-User-ID via make_generator_operator_headers, and
BrokerTrader calls thread the real Account.id via make_broker_trader_headers.
"""
import uuid

from prd_bench_local_runner.testing import build_user_headers, get_success_data

from .api_client import api_client
from .constants import JULY_PERIOD_END, JULY_PERIOD_START
from .factories import (
    create_account_payload,
    create_bill_payload,
    create_claim_report_payload,
    create_generator_payload,
    create_meter_reading_payload,
    create_obligation_payload,
    create_program_payload,
    create_retirement_payload,
    create_subscription_payload,
    create_trade_payload,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_broker_trader_headers,
    make_generator_operator_headers,
    make_meter_attester_headers,
    make_program_manager_headers,
)

ADMIN = TEST_USERS["registry_admin_headers"]
ATTESTER = TEST_USERS["meter_attester_headers"]
PM = TEST_USERS["program_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _uniq(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tier 0: clock and single-call wrappers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock (PRD §2.4). Returns {current_utc}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: generator lifecycle
# ---------------------------------------------------------------------------

def create_generator(**overrides) -> dict:
    """Register a generator (lands in REGISTERED)."""
    return get_success_data(api_client.create_generator(create_generator_payload(**overrides), ADMIN))


def get_generator(generator_id: str) -> dict:
    return get_success_data(api_client.get_generator(generator_id, ADMIN))


def patch_generator(generator_id: str, **fields) -> dict:
    """OCC-guarded generator amendment; reads the live version when
    expected_generator_version is not supplied."""
    if "expected_generator_version" not in fields:
        fields["expected_generator_version"] = get_generator(generator_id)["version"]
    return get_success_data(api_client.patch_generator(generator_id, fields, ADMIN))


def submit_generator_for_verification(generator_id: str) -> dict:
    return get_success_data(
        api_client.submit_generator_verification(
            generator_id, make_generator_operator_headers(generator_id)
        )
    )


def verify_generator(generator_id: str) -> dict:
    return get_success_data(api_client.verify_generator(generator_id, ADMIN))


def create_active_generator(**overrides) -> dict:
    """Full chain: register -> submit-verification -> verify. Returns the
    ACTIVE generator (which now has an auto-created GENERATOR account)."""
    gen = create_generator(**overrides)
    submit_generator_for_verification(gen["id"])
    return verify_generator(gen["id"])


def get_generator_account(generator_id: str) -> dict:
    """The auto-created GENERATOR account, found via the account list filter."""
    data = get_success_data(api_client.list_accounts(ADMIN, params={"generator_id": generator_id}))
    assert len(data) == 1, f"expected exactly 1 GENERATOR account for {generator_id}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 1: meter readings
# ---------------------------------------------------------------------------

def create_meter_reading(
    generator_id: str,
    period_start: str = JULY_PERIOD_START,
    period_end: str = JULY_PERIOD_END,
    metered_kwh: int = 1000,
) -> dict:
    payload = create_meter_reading_payload(
        generator_id=generator_id,
        period_start=period_start,
        period_end=period_end,
        metered_kwh=metered_kwh,
    )
    return get_success_data(
        api_client.create_meter_reading(payload, make_generator_operator_headers(generator_id))
    )


def get_meter_reading(reading_id: str) -> dict:
    return get_success_data(api_client.get_meter_reading(reading_id, ADMIN))


def attest_reading(reading_id: str, attester_id: str = "att-1") -> dict:
    return get_success_data(
        api_client.attest_reading(reading_id, make_meter_attester_headers(attester_id))
    )


def accept_reading(reading_id: str) -> dict:
    return get_success_data(api_client.accept_reading(reading_id, ADMIN))


def create_accepted_reading(
    generator_id: str,
    period_start: str = JULY_PERIOD_START,
    period_end: str = JULY_PERIOD_END,
    metered_kwh: int = 1000,
    attester_id: str = "att-1",
) -> dict:
    """Submit -> attest -> accept. Returns the ACCEPTED reading."""
    reading = create_meter_reading(generator_id, period_start, period_end, metered_kwh)
    attest_reading(reading["id"], attester_id)
    return accept_reading(reading["id"])


# ---------------------------------------------------------------------------
# Tier 2: minting and certificates
# ---------------------------------------------------------------------------

def run_mint(generator_id: str) -> dict:
    """Execute a mint run; returns the summary object {minted_count,
    total_minted_mwh, carryover_kwh, certificate_ids}."""
    return get_success_data(api_client.mint_run(generator_id, ADMIN))


def list_certificates(**params) -> list:
    return get_success_data(api_client.list_certificates(ADMIN, params=params))


def get_certificate(certificate_id: str) -> dict:
    return get_success_data(api_client.get_certificate(certificate_id, ADMIN))


def setup_minted_generator(readings=None, **gen_overrides) -> dict:
    """ACTIVE generator + accepted readings + one mint run.

    readings: list of dicts {period_start, period_end, metered_kwh, clock?};
    each entry is submitted/attested/accepted in order (setting the logical
    clock first when the entry carries "clock"). Defaults to a single
    1000-kWh July 2026 reading (one 1-MWh certificate, serial range [1,1]).

    Returns {"generator", "account", "certificates" (serial order), "mint"}.
    """
    if readings is None:
        readings = [{"period_start": JULY_PERIOD_START, "period_end": JULY_PERIOD_END,
                     "metered_kwh": 1000}]
    gen = create_active_generator(**gen_overrides)
    for r in readings:
        if r.get("clock"):
            set_clock(r["clock"])
        create_accepted_reading(
            gen["id"], r["period_start"], r["period_end"], r["metered_kwh"]
        )
    mint = run_mint(gen["id"])
    certs = list_certificates(generator_id=gen["id"])
    certs.sort(key=lambda c: c["serial_start"])
    return {
        "generator": get_generator(gen["id"]),
        "account": get_generator_account(gen["id"]),
        "certificates": certs,
        "mint": mint,
    }


# ---------------------------------------------------------------------------
# Tier 1/2: accounts, transfers, trades
# ---------------------------------------------------------------------------

def create_account(**overrides) -> dict:
    return get_success_data(api_client.create_account(create_account_payload(**overrides), ADMIN))


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, ADMIN))


def create_broker_account(owner_name=None) -> dict:
    return create_account(account_type="BROKER", owner_name=owner_name or _uniq("Broker"))


def transfer_certificate(certificate_id: str, to_account_id: str) -> dict:
    """RegistryAdmin bilateral whole-batch transfer (admin may transfer any)."""
    return get_success_data(
        api_client.transfer_certificate(
            certificate_id, {"to_account_id": to_account_id}, ADMIN
        )
    )


def setup_brokers_with_certificates(readings=None, **gen_overrides) -> dict:
    """Minted generator + broker accounts b1 (holding all certificates) and
    b2 (empty). Returns {"generator", "gacc", "b1", "b2", "certificates"}."""
    setup = setup_minted_generator(readings, **gen_overrides)
    b1 = create_broker_account("Broker One")
    b2 = create_broker_account("Broker Two")
    for cert in setup["certificates"]:
        transfer_certificate(cert["id"], b1["id"])
    return {
        "generator": setup["generator"],
        "gacc": setup["account"],
        "b1": b1,
        "b2": b2,
        "certificates": [get_certificate(c["id"]) for c in setup["certificates"]],
    }


def propose_trade(
    from_account_id: str,
    to_account_id: str,
    items: list,
    unit_price_cents_per_mwh: int = 300,
    settlement_mode: str = "GROSS",
) -> dict:
    """Propose a trade as the selling broker (ownership-threaded)."""
    payload = create_trade_payload(
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        items=items,
        unit_price_cents_per_mwh=unit_price_cents_per_mwh,
        settlement_mode=settlement_mode,
    )
    return get_success_data(
        api_client.create_trade(payload, make_broker_trader_headers(from_account_id))
    )


def get_trade(trade_id: str) -> dict:
    return get_success_data(api_client.get_trade(trade_id, ADMIN))


def expire_trade(trade_id: str) -> dict:
    """RegistryAdmin expires an ACCEPTED trade past its deadline."""
    return get_success_data(api_client.expire_trade(trade_id, ADMIN))


def accept_trade(trade_id: str, buyer_account_id: str) -> dict:
    return get_success_data(
        api_client.accept_trade(trade_id, make_broker_trader_headers(buyer_account_id))
    )


def settle_trade(trade_id: str, buyer_account_id: str) -> dict:
    return get_success_data(
        api_client.settle_trade(trade_id, make_broker_trader_headers(buyer_account_id))
    )


def propose_and_accept_trade(
    from_account_id: str,
    to_account_id: str,
    items: list,
    unit_price_cents_per_mwh: int = 300,
    settlement_mode: str = "GROSS",
) -> dict:
    """PROPOSED -> ACCEPTED (buyer accepts; item certificates lock)."""
    trade = propose_trade(
        from_account_id, to_account_id, items, unit_price_cents_per_mwh, settlement_mode
    )
    return accept_trade(trade["id"], to_account_id)


def settle_accepted_trade(
    from_account_id: str,
    to_account_id: str,
    items: list,
    unit_price_cents_per_mwh: int = 300,
    settlement_mode: str = "GROSS",
) -> dict:
    """Full lifecycle: PROPOSED -> ACCEPTED -> SETTLED. Returns the settled trade."""
    trade = propose_and_accept_trade(
        from_account_id, to_account_id, items, unit_price_cents_per_mwh, settlement_mode
    )
    return settle_trade(trade["id"], to_account_id)


# ---------------------------------------------------------------------------
# Tier 1/2: programs and subscriptions
# ---------------------------------------------------------------------------

def create_program(**overrides) -> dict:
    """Create a program (lands in DRAFT)."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides), ADMIN))


def get_program(program_id: str) -> dict:
    return get_success_data(api_client.get_program(program_id, ADMIN))


def patch_program(program_id: str, **fields) -> dict:
    """OCC-guarded program amendment; reads the live version when
    expected_program_version is not supplied."""
    if "expected_program_version" not in fields:
        fields["expected_program_version"] = get_program(program_id)["version"]
    return get_success_data(api_client.patch_program(program_id, fields, ADMIN))


def wire_and_open_program(program_id: str) -> dict:
    """Create the PROGRAM holding account wired to this program, PATCH the
    program's holding_account_id (OCC-guarded), then open. Returns
    {"program" (OPEN), "holding_account"}."""
    holding = create_account(
        account_type="PROGRAM", owner_name=_uniq("Holding"), program_id=program_id
    )
    patch_program(program_id, holding_account_id=holding["id"])
    program = get_success_data(api_client.open_program(program_id, ADMIN))
    return {"program": program, "holding_account": holding}


def setup_open_program(**program_overrides) -> dict:
    """Create + wire + open a program. Returns {"program", "holding_account"}."""
    program = create_program(**program_overrides)
    return wire_and_open_program(program["id"])


def create_subscription(
    program_id: str,
    expected_program_version=None,
    **overrides,
) -> dict:
    """Enroll a subscription (lands in PENDING) as ProgramManager. Reads the
    program's live version for the OCC field when not supplied."""
    if expected_program_version is None:
        expected_program_version = get_program(program_id)["version"]
    payload = create_subscription_payload(
        program_id=program_id,
        expected_program_version=expected_program_version,
        **overrides,
    )
    return get_success_data(api_client.create_subscription(payload, PM))


def get_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def activate_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.activate_subscription(subscription_id, PM))


def terminate_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.terminate_subscription(subscription_id, PM))


def setup_active_subscription(
    allocation_kw: int = 100,
    estimated_usage_kwh: int = 900,
    activate_at: str = None,
    **program_overrides,
) -> dict:
    """OPEN program + one subscription driven PENDING -> ACTIVE.

    activate_at: when given, the logical clock is moved to that instant
    immediately before activation (controls activated_at, and hence bill
    proration day counts). Returns {"program", "holding_account",
    "subscription"} with the subscription ACTIVE."""
    setup = setup_open_program(**program_overrides)
    sub = create_subscription(
        setup["program"]["id"],
        allocation_kw=allocation_kw,
        estimated_usage_kwh=estimated_usage_kwh,
    )
    if activate_at is not None:
        set_clock(activate_at)
    sub = activate_subscription(sub["id"])
    setup["subscription"] = sub
    return setup


# ---------------------------------------------------------------------------
# Tier 1/2: bills
# ---------------------------------------------------------------------------

def create_bill(subscription_id: str, period_month: str = "2026-07",
                usage_kwh: int = 1000, charges_cents: int = 20000) -> dict:
    payload = create_bill_payload(
        subscription_id=subscription_id,
        period_month=period_month,
        usage_kwh=usage_kwh,
        charges_cents=charges_cents,
    )
    return get_success_data(api_client.create_bill(payload, PM))


def get_bill(bill_id: str) -> dict:
    return get_success_data(api_client.get_bill(bill_id, ADMIN))


def issue_bill(bill_id: str) -> dict:
    return get_success_data(api_client.issue_bill(bill_id, PM))


# ---------------------------------------------------------------------------
# Tier 1/2: retirements, obligations, claim reports
# ---------------------------------------------------------------------------

def retire_voluntary(certificate_id: str, program_id: str) -> dict:
    payload = create_retirement_payload(
        certificate_id=certificate_id, purpose="VOLUNTARY_PROGRAM", program_id=program_id
    )
    return get_success_data(api_client.create_retirement(payload, PM))


def retire_compliance(certificate_id: str, obligation_id: str) -> dict:
    payload = create_retirement_payload(
        certificate_id=certificate_id, purpose="COMPLIANCE", obligation_id=obligation_id
    )
    return get_success_data(api_client.create_retirement(payload, CO))


def retire_wholesale(certificate_id: str, holder_account_id: str,
                     external_claim_reference: str) -> dict:
    payload = create_retirement_payload(
        certificate_id=certificate_id,
        purpose="WHOLESALE_CLAIM",
        external_claim_reference=external_claim_reference,
    )
    return get_success_data(
        api_client.create_retirement(
            payload, make_broker_trader_headers(holder_account_id)
        )
    )


def get_retirement(retirement_id: str) -> dict:
    return get_success_data(api_client.get_retirement(retirement_id, ADMIN))


def list_retirements(**params) -> list:
    return get_success_data(api_client.list_retirements(ADMIN, params=params))


def create_obligation(**overrides) -> dict:
    return get_success_data(
        api_client.create_obligation(create_obligation_payload(**overrides), CO)
    )


def get_obligation(obligation_id: str) -> dict:
    return get_success_data(api_client.get_obligation(obligation_id, CO))


def patch_obligation(obligation_id: str, **fields) -> dict:
    """OCC-guarded amendment; reads the live version when
    expected_obligation_version is not supplied."""
    if "expected_obligation_version" not in fields:
        fields["expected_obligation_version"] = get_obligation(obligation_id)["version"]
    return get_success_data(api_client.patch_obligation(obligation_id, fields, CO))


def close_obligation(obligation_id: str) -> dict:
    return get_success_data(api_client.close_obligation(obligation_id, CO))


def _report_write_headers(scope: str, user_id: str) -> dict:
    """Scope-role match (PRD §2.1): VOLUNTARY_PROGRAM reports are
    ProgramManager work, COMPLIANCE_OBLIGATION reports ComplianceOfficer."""
    if scope == "COMPLIANCE_OBLIGATION":
        return build_user_headers(user_id, "ComplianceOfficer")
    return make_program_manager_headers(user_id)


def create_claim_report(scope: str = "VOLUNTARY_PROGRAM", report_year: int = 2026,
                        program_id: str = None, obligation_id: str = None,
                        user_id: str = "pm-1") -> dict:
    payload = create_claim_report_payload(
        scope=scope, report_year=report_year, program_id=program_id,
        obligation_id=obligation_id,
    )
    return get_success_data(
        api_client.create_claim_report(payload, _report_write_headers(scope, user_id))
    )


def get_claim_report(report_id: str) -> dict:
    return get_success_data(api_client.get_claim_report(report_id, ADMIN))


def submit_claim_report(report_id: str, scope: str = "VOLUNTARY_PROGRAM",
                        user_id: str = "pm-1") -> dict:
    return get_success_data(
        api_client.submit_claim_report(report_id, _report_write_headers(scope, user_id))
    )


def accept_claim_report(report_id: str, auditor_id: str = "aud-1") -> dict:
    return get_success_data(
        api_client.accept_claim_report(report_id, make_auditor_headers(auditor_id))
    )


def reject_claim_report(report_id: str, auditor_id: str = "aud-1",
                        reason: str = "incomplete evidence") -> dict:
    return get_success_data(
        api_client.reject_claim_report(report_id, {"reason": reason},
                                       make_auditor_headers(auditor_id))
    )


def revise_claim_report(report_id: str, scope: str = "VOLUNTARY_PROGRAM",
                        user_id: str = "pm-1") -> dict:
    return get_success_data(
        api_client.revise_claim_report(report_id, _report_write_headers(scope, user_id))
    )
