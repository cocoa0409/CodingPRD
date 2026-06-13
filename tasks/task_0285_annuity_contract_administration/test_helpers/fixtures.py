"""Composite setup helpers for multi-step test prerequisites.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, since the server database is empty before every test. Setup calls
use get_success_data() (lenient 2xx validator) so a broken precondition raises
a clear "Setup step failed" error rather than an opaque assertion failure.

All monetary amounts are integer cents. The default clock anchor is
2026-01-01T00:00:00Z; pass a different `clock` to relocate contract time.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_product_payload,
    create_contract_payload,
    create_premium_payload,
    create_sub_account_allocation_payload,
    create_index_segment_payload,
    create_crediting_event_payload,
    create_withdrawal_payload,
    create_beneficiary_payload,
    create_annuitization_payload,
    create_death_claim_payload,
    create_exchange_payload,
)
from .test_users import (
    TEST_USERS,
    make_contract_admin_headers,
    make_compliance_officer_headers,
)

ADMIN = TEST_USERS["contract_admin_headers"]
CREDITING = TEST_USERS["crediting_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

DEFAULT_CLOCK = "2026-01-01T00:00:00Z"


# ─── Low-level building blocks ────────────────────────────────────────────
def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Pin the server wall clock. Returns the clock response data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_product(**overrides) -> dict:
    """Create a Product (FIXED ACCOUNT_VALUE by default). Returns the product."""
    return get_success_data(api_client.create_product(create_product_payload(**overrides), ADMIN))


def create_contract(product_id: str, **overrides) -> dict:
    """Create a PENDING contract under a product. Returns the contract."""
    return get_success_data(
        api_client.create_contract(create_contract_payload(product_id, **overrides), ADMIN)
    )


def submit_premium(contract_id: str, expected_contract_version: int, **overrides) -> dict:
    """Submit a SUBMITTED premium. Returns the premium."""
    return get_success_data(
        api_client.create_premium(
            create_premium_payload(contract_id, expected_contract_version, **overrides), ADMIN
        )
    )


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, ADMIN))


# ─── Tier 1/2: Active funded contracts of each product family ─────────────
def setup_active_fixed_contract(
    gross_premium_cents: int = 2_000_000,
    fixed_annual_rate_bps: int = 0,
    free_withdrawal_corridor_bps: int = None,
    surrender_charge_schedule=None,
    mva_enabled: bool = None,
    death_benefit_type: str = "ACCOUNT_VALUE",
    min_initial_premium_cents: int = 1_000_000,
    clock: str = DEFAULT_CLOCK,
):
    """FIXED contract funded to ACTIVE via a cleared initial premium.

    Returns (product, contract, premium). The returned contract is a fresh GET
    so its version field reflects the post-clear state.
    """
    set_clock(clock)
    product_kwargs = dict(
        contract_type="FIXED",
        fixed_annual_rate_bps=fixed_annual_rate_bps,
        death_benefit_type=death_benefit_type,
        min_initial_premium_cents=min_initial_premium_cents,
    )
    if free_withdrawal_corridor_bps is not None:
        product_kwargs["free_withdrawal_corridor_bps"] = free_withdrawal_corridor_bps
    if surrender_charge_schedule is not None:
        product_kwargs["surrender_charge_schedule"] = surrender_charge_schedule
    if mva_enabled is not None:
        product_kwargs["mva_enabled"] = mva_enabled
    product = create_product(**product_kwargs)
    contract = create_contract(product["id"], annuitant_age=60)
    premium = submit_premium(contract["id"], contract["version"],
                             gross_premium_cents=gross_premium_cents)
    get_success_data(api_client.clear_premium(premium["id"], ADMIN))
    return product, get_contract(contract["id"]), premium


def setup_active_indexed_contract(
    gross_premium_cents: int = 2_000_000,
    surrender_charge_schedule=None,
    clock: str = DEFAULT_CLOCK,
):
    """INDEXED contract funded to ACTIVE. Returns (product, contract, premium)."""
    set_clock(clock)
    product_kwargs = dict(
        contract_type="INDEXED",
        fixed_annual_rate_bps=None,
        death_benefit_type="ACCOUNT_VALUE",
        min_initial_premium_cents=1_000_000,
    )
    if surrender_charge_schedule is not None:
        product_kwargs["surrender_charge_schedule"] = surrender_charge_schedule
    else:
        product_kwargs["surrender_charge_schedule"] = [{"contract_year": 0, "charge_bps": 700}]
    product = create_product(**product_kwargs)
    contract = create_contract(product["id"], annuitant_age=60)
    premium = submit_premium(contract["id"], contract["version"],
                             gross_premium_cents=gross_premium_cents)
    get_success_data(api_client.clear_premium(premium["id"], ADMIN))
    return product, get_contract(contract["id"]), premium


def setup_active_variable_contract(
    gross_premium_cents: int = 2_000_000,
    allocations=((6000, "EQUITY"), (4000, "BOND")),
    free_withdrawal_corridor_bps: int = None,
    surrender_charge_schedule=None,
    clock: str = DEFAULT_CLOCK,
):
    """VARIABLE contract with complete (sum 10000) allocations, funded to ACTIVE.

    Returns (product, contract, premium, allocation_ids).
    """
    set_clock(clock)
    product_kwargs = dict(
        contract_type="VARIABLE",
        fixed_annual_rate_bps=None,
        death_benefit_type="ACCOUNT_VALUE",
        min_initial_premium_cents=1_000_000,
    )
    if free_withdrawal_corridor_bps is not None:
        product_kwargs["free_withdrawal_corridor_bps"] = free_withdrawal_corridor_bps
    if surrender_charge_schedule is not None:
        product_kwargs["surrender_charge_schedule"] = surrender_charge_schedule
    product = create_product(**product_kwargs)
    contract = create_contract(product["id"], annuitant_age=60)
    alloc_ids = []
    for bps, name in allocations:
        alloc = get_success_data(api_client.create_sub_account_allocation(
            create_sub_account_allocation_payload(
                contract["id"], division_name=name, allocation_bps=bps, unit_value_cents=1000),
            ADMIN))
        alloc_ids.append(alloc["id"])
    premium = submit_premium(contract["id"], contract["version"],
                             gross_premium_cents=gross_premium_cents)
    get_success_data(api_client.clear_premium(premium["id"], ADMIN))
    return product, get_contract(contract["id"]), premium, alloc_ids


# ─── Tier 1/3: Open index segment ─────────────────────────────────────────
def setup_indexed_with_open_segment(
    segment_premium_cents: int = 1_000_000,
    cap_bps: int = 800,
    floor_bps: int = 0,
    participation_bps: int = 10000,
    term_start_date: str = "2026-01-01T00:00:00Z",
    term_end_date: str = "2027-01-01T00:00:00Z",
    index_name: str = "SP500",
    clock: str = DEFAULT_CLOCK,
):
    """INDEXED ACTIVE contract + one OPEN IndexSegment.

    Returns (product, contract, segment).
    """
    product, contract, _ = setup_active_indexed_contract(clock=clock)
    segment = get_success_data(api_client.create_index_segment(
        create_index_segment_payload(
            contract["id"], index_name=index_name,
            term_start_date=term_start_date, term_end_date=term_end_date,
            segment_premium_cents=segment_premium_cents, cap_bps=cap_bps,
            floor_bps=floor_bps, participation_bps=participation_bps),
        ADMIN))
    return product, contract, segment


# ─── Tier 1: Requested withdrawal awaiting settle ─────────────────────────
def setup_requested_withdrawal(
    requested_amount_cents: int,
    is_full_surrender: bool = False,
    fixed_annual_rate_bps: int = 0,
    free_withdrawal_corridor_bps: int = None,
    surrender_charge_schedule=None,
    mva_enabled: bool = None,
    gross_premium_cents: int = 2_000_000,
    min_initial_premium_cents: int = 1_000_000,
    clock: str = DEFAULT_CLOCK,
):
    """FIXED ACTIVE contract + one REQUESTED withdrawal.

    Returns (product, contract, withdrawal). The withdrawal carries the
    contract version observed immediately before request.
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=gross_premium_cents,
        fixed_annual_rate_bps=fixed_annual_rate_bps,
        free_withdrawal_corridor_bps=free_withdrawal_corridor_bps,
        surrender_charge_schedule=surrender_charge_schedule,
        mva_enabled=mva_enabled,
        min_initial_premium_cents=min_initial_premium_cents,
        clock=clock,
    )
    overrides = {}
    if is_full_surrender:
        overrides["is_full_surrender"] = True
    withdrawal = get_success_data(api_client.create_withdrawal(
        create_withdrawal_payload(
            contract["id"], requested_amount_cents, contract["version"], **overrides),
        ADMIN))
    return product, contract, withdrawal


# ─── Tier 2: Beneficiaries ────────────────────────────────────────────────
def add_beneficiaries(contract_id: str, shares):
    """Add ACTIVE beneficiaries in order. `shares` is an iterable of share_bps
    ints (or (share_bps, full_name) tuples). Returns list of beneficiary ids."""
    ids = []
    for i, share in enumerate(shares):
        if isinstance(share, (tuple, list)):
            share_bps, name = share
        else:
            share_bps, name = share, f"Beneficiary {i + 1}"
        ben = get_success_data(api_client.create_beneficiary(
            create_beneficiary_payload(contract_id, share_bps, full_name=name), ADMIN))
        ids.append(ben["id"])
    return ids


# ─── Tier 3: Death-claim progressions ─────────────────────────────────────
def setup_death_claim_filed(
    gross_premium_cents: int = 2_000_000,
    death_benefit_type: str = "ACCOUNT_VALUE",
    beneficiary_shares=(10000,),
    clock: str = DEFAULT_CLOCK,
):
    """ACTIVE contract (one or more beneficiaries) with a FILED DeathClaim.

    Returns (product, contract, claim, beneficiary_ids).
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=gross_premium_cents,
        death_benefit_type=death_benefit_type,
        clock=clock,
    )
    ben_ids = add_beneficiaries(contract["id"], beneficiary_shares)
    claim = get_success_data(api_client.create_death_claim(
        create_death_claim_payload(contract["id"], clock), ADMIN))
    return product, contract, claim, ben_ids


def setup_death_claim_verifying(**kwargs):
    """As setup_death_claim_filed, then verify-identity (-> VERIFYING)."""
    product, contract, claim, ben_ids = setup_death_claim_filed(**kwargs)
    get_success_data(api_client.verify_identity(claim["id"], COMPLIANCE))
    return product, contract, claim, ben_ids


def setup_death_claim_valued(**kwargs):
    """As setup_death_claim_verifying, then value-benefit (-> VALUED)."""
    product, contract, claim, ben_ids = setup_death_claim_verifying(**kwargs)
    get_success_data(api_client.value_benefit(claim["id"], COMPLIANCE))
    return product, contract, claim, ben_ids


# ─── Tier 3: Annuitization ────────────────────────────────────────────────
def setup_elected_annuitization(
    payout_option: str = "LIFE_ONLY",
    period_certain_years: int = None,
    gross_premium_cents: int = 2_000_000,
    annuitant_age: int = 60,
    clock: str = DEFAULT_CLOCK,
):
    """ACTIVE contract + one ELECTED annuitization. Returns (contract, annuitization)."""
    set_clock(clock)
    product = create_product(contract_type="FIXED", fixed_annual_rate_bps=0,
                             death_benefit_type="ACCOUNT_VALUE",
                             surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}],
                             min_initial_premium_cents=1_000_000)
    contract = create_contract(product["id"], annuitant_age=annuitant_age)
    premium = submit_premium(contract["id"], contract["version"],
                             gross_premium_cents=gross_premium_cents)
    get_success_data(api_client.clear_premium(premium["id"], ADMIN))
    overrides = {}
    if period_certain_years is not None:
        overrides["period_certain_years"] = period_certain_years
    annuitization = get_success_data(api_client.create_annuitization(
        create_annuitization_payload(contract["id"], payout_option, **overrides), ADMIN))
    return get_contract(contract["id"]), annuitization


# ─── Tier 3: 1035 exchanges ───────────────────────────────────────────────
def setup_outbound_exchange_draft(
    transfer_amount_cents: int = 1_000_000,
    cost_basis_cents: int = 600_000,
    clock: str = DEFAULT_CLOCK,
):
    """A source contract + an OUTBOUND Exchange1035 in DRAFT.

    Returns (source_contract, exchange).
    """
    set_clock(clock)
    product = create_product(contract_type="FIXED", fixed_annual_rate_bps=0,
                             death_benefit_type="ACCOUNT_VALUE",
                             surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}],
                             min_initial_premium_cents=1_000_000)
    source = create_contract(product["id"], annuitant_age=60)
    exchange = get_success_data(api_client.create_exchange(
        create_exchange_payload("OUTBOUND", transfer_amount_cents, cost_basis_cents,
                                source_contract_id=source["id"], external_carrier="OtherCarrier"),
        ADMIN))
    return source, exchange


def setup_outbound_exchange_submitted(
    submitter_user_id: str = "submitter-1",
    transfer_amount_cents: int = 1_000_000,
    cost_basis_cents: int = 600_000,
    clock: str = DEFAULT_CLOCK,
):
    """An OUTBOUND Exchange1035 SUBMITTED by `submitter_user_id`.

    Returns (source_contract, exchange) where the exchange GET reflects the
    SUBMITTED version.
    """
    source, exchange = setup_outbound_exchange_draft(
        transfer_amount_cents=transfer_amount_cents, cost_basis_cents=cost_basis_cents, clock=clock)
    submitter_headers = make_contract_admin_headers(submitter_user_id)
    get_success_data(api_client.submit_exchange(exchange["id"], submitter_headers))
    exchange = get_success_data(api_client.get_exchange(exchange["id"], COMPLIANCE))
    return source, exchange


def setup_outbound_exchange_revision_requested(
    submitter_user_id: str = "submitter-1",
    clock: str = DEFAULT_CLOCK,
):
    """An OUTBOUND Exchange1035 driven SUBMITTED -> REVISION_REQUESTED.

    Returns (source_contract, exchange).
    """
    source, exchange = setup_outbound_exchange_submitted(
        submitter_user_id=submitter_user_id, clock=clock)
    get_success_data(api_client.request_revision_exchange(exchange["id"], COMPLIANCE))
    exchange = get_success_data(api_client.get_exchange(exchange["id"], COMPLIANCE))
    return source, exchange


def setup_inbound_exchange_approved_premium_submitted(
    submitter_user_id: str = "admin-submitter",
    approver_user_id: str = "compliance-approver",
    transfer_amount_cents: int = 2_000_000,
    cost_basis_cents: int = 1_500_000,
    clock: str = DEFAULT_CLOCK,
):
    """An INBOUND Exchange1035 APPROVED, with a still-SUBMITTED funding premium
    on the target contract carrying source_exchange_id.

    Returns (target_contract, exchange, premium).
    """
    set_clock(clock)
    product = create_product(contract_type="FIXED", fixed_annual_rate_bps=0,
                             death_benefit_type="ACCOUNT_VALUE",
                             surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}],
                             min_initial_premium_cents=1_000_000)
    target = create_contract(product["id"], annuitant_age=60)
    exchange = get_success_data(api_client.create_exchange(
        create_exchange_payload("INBOUND", transfer_amount_cents, cost_basis_cents,
                                target_contract_id=target["id"], external_carrier="OldCarrier"),
        ADMIN))
    submitter_headers = make_contract_admin_headers(submitter_user_id)
    get_success_data(api_client.submit_exchange(exchange["id"], submitter_headers))
    ex_v = get_success_data(api_client.get_exchange(exchange["id"], COMPLIANCE))["version"]
    approver_headers = make_compliance_officer_headers(approver_user_id)
    get_success_data(api_client.approve_exchange(
        exchange["id"], {"expected_exchange_version": ex_v}, approver_headers))
    premium = submit_premium(target["id"], target["version"],
                             gross_premium_cents=transfer_amount_cents,
                             source_exchange_id=exchange["id"])
    exchange = get_success_data(api_client.get_exchange(exchange["id"], COMPLIANCE))
    return target, exchange, premium
