"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database with the logical clock at its startup
default, PRD §2.4). Setup calls use get_success_data() so a setup failure
surfaces as a clear "Setup step failed" message rather than a confusing
assertion failure deep inside a test.

Statutory dates (opt_out_deadline, enrollment_effective_on) are computed by
the server from notice_mailed_on (PRD §3.2); helpers read the stamped values
back from the notice instead of assuming particular constants.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_BOOT, TEST_DEFAULTS
from .factories import (
    create_account_spec,
    create_authority_payload,
    create_bad_debt_pool_payload,
    create_billing_extract_payload,
    create_billing_line_payload,
    create_compliance_filing_payload,
    create_ingest_payload,
    create_load_forecast_payload,
    create_notice_payload,
    create_opt_out_request_payload,
    create_product_payload,
    create_rate_schedule_payload,
    create_rec_retirement_payload,
    create_remittance_file_payload,
    create_supply_contract_payload,
)
from .test_users import (
    TEST_USERS,
    make_billing_coordinator_headers,
    make_board_director_headers,
    make_compliance_officer_headers,
    make_customer_service_headers,
    make_finance_controller_headers,
    make_portfolio_manager_headers,
    make_program_operator_headers,
    make_rate_analyst_headers,
    make_utility_liaison_headers,
)

BD = TEST_USERS["board_director_headers"]
RA = TEST_USERS["rate_analyst_headers"]
PO = TEST_USERS["program_operator_headers"]
CS = TEST_USERS["customer_service_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
BC = TEST_USERS["billing_coordinator_headers"]
FC = TEST_USERS["finance_controller_headers"]
CO = TEST_USERS["compliance_officer_headers"]
UL = TEST_USERS["utility_liaison_headers"]


# ---------------------------------------------------------------------------
# Clock helpers (PRD §2.4)
# ---------------------------------------------------------------------------

def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fmt_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, BD)
    )


def advance_epoch() -> dict:
    """Run the epoch-advance ops checkpoint. Returns the summary counts."""
    return get_success_data(api_client.advance_epoch({}, BD))


# ---------------------------------------------------------------------------
# Authority bootstrap / lifecycle (PRD §3.1)
# ---------------------------------------------------------------------------

def bootstrap_authority(**overrides) -> dict:
    return get_success_data(api_client.create_authority(create_authority_payload(**overrides), BD))


def get_authority() -> dict:
    """PRD §4: the Authority read returns an array of length 1."""
    data = get_success_data(api_client.get_authority(BD))
    assert isinstance(data, list) and len(data) == 1, (
        "Authority read must return an array of length 1"
    )
    return data[0]


def activate_authority() -> dict:
    return get_success_data(api_client.activate_authority({}, BD))


def suspend_authority() -> dict:
    return get_success_data(api_client.suspend_authority({}, BD))


def reinstate_authority() -> dict:
    return get_success_data(api_client.reinstate_authority({}, BD))


# ---------------------------------------------------------------------------
# Products & rate schedules (PRD §3.4)
# ---------------------------------------------------------------------------

def create_adopted_product_with_schedule(
    product_code=TEST_DEFAULTS["PRODUCT_CODE"],
    election_key="DEFAULT",
    renewable_pct=0.50,
    energy_rate=TEST_DEFAULTS["ENERGY_RATE_CENTS_PER_KWH"],
    pcia_rate=TEST_DEFAULTS["PCIA_RATE_CENTS_PER_KWH"],
    benchmark_rate=TEST_DEFAULTS["INCUMBENT_BENCHMARK_CENTS_PER_KWH"],
    period_start=TEST_DEFAULTS["PERIOD_START"],
    period_end=TEST_DEFAULTS["PERIOD_END"],
    proposer_id="analyst-1",
    adopter_id="director-1",
):
    """Create product + schedule, propose (RateAnalyst), adopt schedule and
    product (BoardDirector) — two distinct operator ids for the two-key chain.
    Returns (product, schedule) both ADOPTED."""
    product = get_success_data(
        api_client.create_product(
            create_product_payload(
                product_code=product_code,
                election_key=election_key,
                renewable_pct=renewable_pct,
            ),
            RA,
        )
    )
    schedule = get_success_data(
        api_client.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=product["id"],
                period_start=period_start,
                period_end=period_end,
                energy_rate_cents_per_kwh=energy_rate,
                pcia_rate_cents_per_kwh=pcia_rate,
                incumbent_benchmark_rate_cents_per_kwh=benchmark_rate,
            ),
            RA,
        )
    )
    get_success_data(
        api_client.propose_rate_schedule(
            schedule["id"], {}, make_rate_analyst_headers(proposer_id)
        )
    )
    schedule = get_success_data(
        api_client.adopt_rate_schedule(
            schedule["id"], {}, make_board_director_headers(adopter_id)
        )
    )
    product = get_success_data(api_client.adopt_product(product["id"], {}, BD))
    return product, schedule


def setup_active_authority(
    rate_setting_policy="COST_PLUS",
    discount_floor_bps=0,
    rps_target_pct=TEST_DEFAULTS["RPS_TARGET_PCT"],
    bad_debt_trueup_cap_pct=TEST_DEFAULTS["BAD_DEBT_TRUEUP_CAP_PCT"],
    set_clock_to=CLOCK_BOOT,
    **product_kwargs,
) -> dict:
    """Bootstrap authority + adopted default product with covering adopted
    schedule + activate (PRD §3.1 preconditions). Returns a context dict."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    bootstrap_authority(
        rate_setting_policy=rate_setting_policy,
        discount_floor_bps=discount_floor_bps,
        rps_target_pct=rps_target_pct,
        bad_debt_trueup_cap_pct=bad_debt_trueup_cap_pct,
    )
    product, schedule = create_adopted_product_with_schedule(**product_kwargs)
    authority = activate_authority()
    return {"authority": authority, "product": product, "schedule": schedule}


# ---------------------------------------------------------------------------
# Service accounts & enrollment waves (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------

def ingest_accounts(specs) -> list:
    """Bulk-ingest account specs; returns the minted account ids in order."""
    data = get_success_data(api_client.ingest_service_accounts(create_ingest_payload(specs), PO))
    return data["account_ids"]


def get_account(account_id) -> dict:
    return get_success_data(api_client.get_service_account(account_id, CS))


def create_notice(
    wave_label="W1",
    notice_mailed_on=CLOCK_BOOT,
    target_service_classes=("RESIDENTIAL",),
) -> dict:
    return get_success_data(
        api_client.create_enrollment_notice(
            create_notice_payload(
                wave_label=wave_label,
                notice_mailed_on=notice_mailed_on,
                target_service_classes=list(target_service_classes),
            ),
            PO,
        )
    )


def get_notice(notice_id) -> dict:
    return get_success_data(api_client.get_enrollment_notice(notice_id, PO))


def issue_notice(notice_id) -> dict:
    """Issue a DRAFT notice with the currently-observed Authority version
    (OCC field expected_authority_version, PRD §2.8). Returns the issued
    notice with opt_out_deadline / enrollment_effective_on stamped."""
    authority = get_authority()
    return get_success_data(
        api_client.issue_enrollment_notice(
            notice_id, {"expected_authority_version": authority["version"]}, PO
        )
    )


def close_notice_at_deadline(notice_id) -> dict:
    """Move the logical clock to the notice's stamped opt_out_deadline and
    close it (PRD §3.2: close is permitted once the clock reaches the
    deadline)."""
    notice = get_notice(notice_id)
    set_clock(notice["opt_out_deadline"])
    return get_success_data(api_client.close_enrollment_notice(notice_id, {}, PO))


def advance_through_enrollment(notice_id):
    """Move the logical clock to the notice's stamped enrollment_effective_on
    and run the epoch-advance checkpoint (PRD §2.4, §3.2). Returns
    (settled_notice, epoch_summary)."""
    notice = get_notice(notice_id)
    set_clock(notice["enrollment_effective_on"])
    epoch = advance_epoch()
    return get_notice(notice_id), epoch


def setup_enrolled_accounts(
    specs=None,
    target_service_classes=("RESIDENTIAL",),
    wave_label="W1",
    notice_mailed_on=CLOCK_BOOT,
) -> dict:
    """Ingest accounts, run a full notice wave (issue -> close at deadline ->
    epoch advance at enrollment_effective_on). Returns dict with notice and
    account ids (all eligible accounts end ENROLLED)."""
    if specs is None:
        specs = [create_account_spec()]
    account_ids = ingest_accounts(specs)
    notice = create_notice(
        wave_label=wave_label,
        notice_mailed_on=notice_mailed_on,
        target_service_classes=target_service_classes,
    )
    issue_notice(notice["id"])
    close_notice_at_deadline(notice["id"])
    notice, epoch = advance_through_enrollment(notice["id"])
    return {"notice": notice, "account_ids": account_ids, "epoch": epoch}


def record_opt_out(account_id, notice_id, election_type="OPT_OUT", channel="WEB",
                   reversal_of_request_id=None):
    payload = create_opt_out_request_payload(
        service_account_id=account_id,
        enrollment_notice_id=notice_id,
        election_type=election_type,
        channel=channel,
    )
    if reversal_of_request_id is not None:
        payload["reversal_of_request_id"] = reversal_of_request_id
    return api_client.create_opt_out_request(payload, CS)


# ---------------------------------------------------------------------------
# Billing (PRD §3.6)
# ---------------------------------------------------------------------------

def create_extract(billing_month="2026-05") -> dict:
    return get_success_data(
        api_client.create_billing_extract(
            create_billing_extract_payload(billing_month=billing_month), BC
        )
    )


def post_line(extract_id, account_id, usage_kwh) -> dict:
    return get_success_data(
        api_client.post_billing_line(
            extract_id,
            create_billing_line_payload(
                service_account_id=account_id, usage_kwh=usage_kwh
            ),
            BC,
        )
    )


def get_extract(extract_id) -> dict:
    return get_success_data(api_client.get_billing_extract(extract_id, BC))


def setup_draft_extract_with_lines(billing_month, lines) -> dict:
    """lines: list of (account_id, usage_kwh). Returns the DRAFT extract."""
    extract = create_extract(billing_month)
    for account_id, usage_kwh in lines:
        post_line(extract["id"], account_id, usage_kwh)
    return get_extract(extract["id"])


def setup_accepted_extract(billing_month, lines) -> dict:
    """DRAFT extract + lines -> submit -> utility accept (PRD §3.6). Returns
    the ACCEPTED extract (whose version the remittance OCC check needs)."""
    extract = setup_draft_extract_with_lines(billing_month, lines)
    get_success_data(api_client.submit_billing_extract(extract["id"], {}, BC))
    return get_success_data(api_client.utility_accept_extract(extract["id"], {}, UL))


# ---------------------------------------------------------------------------
# Remittance (PRD §3.7)
# ---------------------------------------------------------------------------

def create_remittance(remittance_period, gross_remittance_cents, utility_fee_bps=0) -> dict:
    return get_success_data(
        api_client.create_remittance_file(
            create_remittance_file_payload(
                remittance_period=remittance_period,
                gross_remittance_cents=gross_remittance_cents,
                utility_fee_bps=utility_fee_bps,
            ),
            BC,
        )
    )


def reconcile_remittance(remittance_id, expected_extract_version, reconciler_id="bc-1") -> dict:
    return get_success_data(
        api_client.reconcile_remittance_file(
            remittance_id,
            {"expected_extract_version": expected_extract_version},
            make_billing_coordinator_headers(reconciler_id),
        )
    )


def settle_remittance(remittance_id, settler_id="fc-1") -> dict:
    return get_success_data(
        api_client.settle_remittance_file(
            remittance_id, {}, make_finance_controller_headers(settler_id)
        )
    )


def setup_settled_extract(billing_month, lines, gross_remittance_cents=None,
                          utility_fee_bps=0, reconciler_id="bc-1", settler_id="fc-1"):
    """Full billing loop: accepted extract + remittance reconciled and
    settled (extract lands SETTLED via the settle cascade, PRD §3.7).
    Returns (extract, remittance), both re-read."""
    extract = setup_accepted_extract(billing_month, lines)
    if gross_remittance_cents is None:
        gross_remittance_cents = extract["total_billed_cents"]
    remittance = create_remittance(billing_month, gross_remittance_cents, utility_fee_bps)
    reconcile_remittance(remittance["id"], extract["version"], reconciler_id)
    settle_remittance(remittance["id"], settler_id)
    return get_extract(extract["id"]), get_success_data(
        api_client.get_remittance_file(remittance["id"], FC)
    )


# ---------------------------------------------------------------------------
# Supply portfolio & forecasts (PRD §3.5)
# ---------------------------------------------------------------------------

def create_contract(**overrides) -> dict:
    return get_success_data(
        api_client.create_supply_contract(create_supply_contract_payload(**overrides), PM)
    )


def create_executed_contract(**overrides) -> dict:
    contract = create_contract(**overrides)
    return get_success_data(api_client.execute_supply_contract(contract["id"], {}, PM))


def create_forecast(snapshot_label, forecast_variant, period_year) -> dict:
    return get_success_data(
        api_client.create_load_forecast(
            create_load_forecast_payload(
                snapshot_label=snapshot_label,
                forecast_variant=forecast_variant,
                period_year=period_year,
            ),
            PM,
        )
    )


# ---------------------------------------------------------------------------
# Bad debt (PRD §3.8)
# ---------------------------------------------------------------------------

def create_pool(pool_period="2026-Q2") -> dict:
    return get_success_data(
        api_client.create_bad_debt_pool(
            create_bad_debt_pool_payload(pool_period=pool_period), FC
        )
    )


def get_pool(pool_id) -> dict:
    return get_success_data(api_client.get_bad_debt_pool(pool_id, FC))


def setup_pool_closed_after_writeoff(
    pool_period="2026-Q2",
    april_gross_remittance_cents=261400,
    may_usage_kwh=2500000,
    close_clock="2026-07-01T00:00:00Z",
    writeoff_clock="2026-06-15T00:00:00Z",
    closer_id="controller-f1",
):
    """Authority ACTIVE with the reserve seeded by an April overpayment
    remittance; a second account billed (accepted, never remitted) and written
    off inside the pool period; the pool then closed. Returns the CLOSED pool.
    Caller controls amounts so the sharing split lands on known literals."""
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[
            create_account_spec(utility_account_number="U-6001"),
            create_account_spec(
                utility_account_number="U-6002",
                service_class="SMALL_COMMERCIAL",
                annual_kwh_estimate=30000000,
                annual_peak_kw=40.0,
            ),
        ],
        target_service_classes=("RESIDENTIAL", "SMALL_COMMERCIAL"),
    )
    a1, a2 = enrolled["account_ids"]

    # April: fully settled with an overpayment that seeds the reserve.
    setup_settled_extract(
        "2026-04", [(a1, 1000)], gross_remittance_cents=april_gross_remittance_cents
    )

    # May: second account billed, accepted but never remitted.
    setup_accepted_extract("2026-05", [(a2, may_usage_kwh)])

    pool = create_pool(pool_period)
    set_clock(writeoff_clock)
    get_success_data(api_client.write_off_service_account(a2, {}, FC))

    set_clock(close_clock)
    closed = get_success_data(
        api_client.close_bad_debt_pool(
            pool["id"], {}, make_finance_controller_headers(closer_id)
        )
    )
    return closed


# ---------------------------------------------------------------------------
# Compliance filings & REC retirements (PRD §3.9)
# ---------------------------------------------------------------------------

def create_filing(filing_type="RPS_ANNUAL", compliance_year=2026) -> dict:
    return get_success_data(
        api_client.create_compliance_filing(
            create_compliance_filing_payload(
                filing_type=filing_type, compliance_year=compliance_year
            ),
            CO,
        )
    )


def attach_rec(filing_id, contract_id, retired_mwh=100, retirement_serial="WREGIS-0001") -> dict:
    return get_success_data(
        api_client.create_rec_retirement(
            create_rec_retirement_payload(
                compliance_filing_id=filing_id,
                supply_contract_id=contract_id,
                retired_mwh=retired_mwh,
                retirement_serial=retirement_serial,
            ),
            CO,
        )
    )


def create_filing_with_rec(filing_type="RPS_ANNUAL", compliance_year=2026,
                           retired_mwh=100, retirement_serial="WREGIS-0001",
                           contract_overrides=None):
    """Filing in DRAFT with one REC retirement attached (PRD §3.9 prepare
    gate needs at least one). Returns (filing, rec, contract)."""
    contract = create_executed_contract(**(contract_overrides or {}))
    filing = create_filing(filing_type, compliance_year)
    rec = attach_rec(filing["id"], contract["id"], retired_mwh, retirement_serial)
    return filing, rec, contract


def get_filing(filing_id) -> dict:
    return get_success_data(api_client.get_compliance_filing(filing_id, CO))


def prepare_filing(filing_id, officer_id="officer-ann") -> dict:
    return get_success_data(
        api_client.prepare_compliance_filing(
            filing_id, {}, make_compliance_officer_headers(officer_id)
        )
    )


def review_filing(filing_id, officer_id="officer-bob") -> dict:
    return get_success_data(
        api_client.review_compliance_filing(
            filing_id, {}, make_compliance_officer_headers(officer_id)
        )
    )


def file_filing(filing_id) -> dict:
    return get_success_data(api_client.file_compliance_filing(filing_id, {}, BD))


def setup_prepared_filing(officer_id="officer-ann", **kwargs) -> dict:
    """Filing with one REC attached, moved DRAFT -> PREPARED by officer_id."""
    filing, rec, contract = create_filing_with_rec(**kwargs)
    return prepare_filing(filing["id"], officer_id)


def setup_accepted_filing(preparer_id="officer-ann", reviewer_id="officer-bob", **kwargs) -> dict:
    """Full two-key chain: prepare -> review -> file -> cpuc-accept."""
    filing = setup_prepared_filing(preparer_id, **kwargs)
    review_filing(filing["id"], reviewer_id)
    file_filing(filing["id"])
    return get_success_data(api_client.cpuc_accept_filing(filing["id"], {}, UL))
