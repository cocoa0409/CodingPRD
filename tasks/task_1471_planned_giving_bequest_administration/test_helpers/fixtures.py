"""Composite setup helpers.

Each helper drives a multi-step scenario through PRD-declared endpoints and
returns the resource dicts tests assert against. Setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup failed"
errors instead of confusing assertion output.

Header conventions (all roles are opaque per the PRD):
  - creation calls use the role's canonical shared headers from TEST_USERS;
  - SoD-anchored calls (execute / valuation post / begin-distribution) accept
    explicit `admin_headers` / `poster_headers` / `actor_headers` overrides so
    tests can match or differ from the recorded originator id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_designation_payload,
    create_donor_payload,
    create_estate_payload,
    create_fund_payload,
    create_gift_agreement_payload,
    create_gift_asset_payload,
    create_illustration_payload,
    create_probate_milestone_payload,
    create_rate_table_payload,
    create_valuation_run_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_headers,
)

OFFICER = TEST_USERS["gift_officer_headers"]
ADMIN = TEST_USERS["gift_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
ESTATE_MGR = TEST_USERS["estate_manager_headers"]
FINANCE = TEST_USERS["finance_steward_headers"]


# ---------------------------------------------------------------------------
# Tier 1: leaf resources
# ---------------------------------------------------------------------------

def make_donor(full_name="Test Donor", date_of_birth="1956-03-01T00:00:00Z") -> dict:
    """Register a donor. Returns the Donor resource."""
    return get_success_data(
        api_client.create_donor(
            create_donor_payload(full_name=full_name, date_of_birth=date_of_birth),
            OFFICER,
        )
    )


def make_active_rate_table(
    label="7520-5pct",
    discount_rate_bps=500,
    effective_from="2026-01-01T00:00:00Z",
    effective_to=None,
) -> dict:
    """Create a rate table and ACTIVATE it. Returns the ACTIVE RateTable."""
    payload = create_rate_table_payload(
        label=label,
        discount_rate_bps=discount_rate_bps,
        effective_from=effective_from,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    table = get_success_data(api_client.create_rate_table(payload, COMPLIANCE))
    return get_success_data(
        api_client.transition_rate_table(table["id"], {"action": "ACTIVATE"}, COMPLIANCE)
    )


def make_draft_agreement(
    donor_id,
    vehicle_type="CRT_ANNUITY",
    gift_amount_cents=10000000,
    payout_rate_bps=500,
    payment_frequency="QUARTERLY",
    lives=1,
    annuitant_1_age=80,
    annuitant_2_age=None,
    funding_month="2026-08",
    **extra,
) -> dict:
    """Create a DRAFT gift agreement directly (no illustration)."""
    payload = create_gift_agreement_payload(
        donor_id=donor_id,
        vehicle_type=vehicle_type,
        gift_amount_cents=gift_amount_cents,
        payment_frequency=payment_frequency,
        lives=lives,
        annuitant_1_age=annuitant_1_age,
        funding_month=funding_month,
        **extra,
    )
    if vehicle_type != "BEQUEST":
        payload["payout_rate_bps"] = payout_rate_bps
    else:
        # Bequests carry no annuity fields at all.
        for key in ("payout_rate_bps", "payment_frequency", "lives",
                    "annuitant_1_age", "annuitant_2_age"):
            payload.pop(key, None)
    if vehicle_type != "BEQUEST" and lives == 2 and annuitant_2_age is not None:
        payload["annuitant_2_age"] = annuitant_2_age
    return get_success_data(api_client.create_gift_agreement(payload, OFFICER))


def make_illustration(
    donor_id,
    vehicle_type="CGA",
    gift_amount_cents=10000000,
    payout_rate_bps=600,
    payment_frequency="QUARTERLY",
    lives=1,
    annuitant_1_age=70,
    annuitant_2_age=None,
    funding_month="2026-08",
    creator_headers=None,
    **extra,
) -> dict:
    """Create an OPEN illustration. `creator_headers` sets the SoD anchor."""
    payload = create_illustration_payload(
        donor_id=donor_id,
        vehicle_type=vehicle_type,
        gift_amount_cents=gift_amount_cents,
        payment_frequency=payment_frequency,
        lives=lives,
        annuitant_1_age=annuitant_1_age,
        funding_month=funding_month,
        **extra,
    )
    if vehicle_type != "BEQUEST":
        payload["payout_rate_bps"] = payout_rate_bps
    else:
        for key in ("payout_rate_bps", "payment_frequency", "lives",
                    "annuitant_1_age", "annuitant_2_age"):
            payload.pop(key, None)
    if vehicle_type != "BEQUEST" and lives == 2 and annuitant_2_age is not None:
        payload["annuitant_2_age"] = annuitant_2_age
    return get_success_data(
        api_client.create_illustration(payload, creator_headers or OFFICER)
    )


def make_verified_designation(
    agreement_id, slot="PRIMARY_1", beneficiary_name="University", document_received=True
) -> dict:
    """Create a designation and walk it DRAFT -> SUBMITTED -> VERIFIED."""
    designation = get_success_data(
        api_client.create_beneficiary_designation(
            create_designation_payload(
                gift_agreement_id=agreement_id,
                slot=slot,
                beneficiary_name=beneficiary_name,
                document_received=document_received,
            ),
            OFFICER,
        )
    )
    get_success_data(
        api_client.transition_beneficiary_designation(
            designation["id"], {"action": "SUBMIT"}, OFFICER
        )
    )
    return get_success_data(
        api_client.transition_beneficiary_designation(
            designation["id"], {"action": "VERIFY"}, ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: reserve fund helpers (OCC chains always read the version first)
# ---------------------------------------------------------------------------

def get_reserve_fund() -> dict:
    """Read the reserve-fund singleton."""
    return get_success_data(api_client.get_reserve_fund(COMPLIANCE))


def reserve_version() -> int:
    """Current reserve-fund version (OCC guard input)."""
    return get_reserve_fund()["version"]


def adjust_reserve(direction: str, amount_cents: int) -> dict:
    """Post a CONTRIBUTION or WITHDRAWAL against the current reserve version."""
    version = reserve_version()
    return get_success_data(
        api_client.create_reserve_adjustment(
            {
                "direction": direction,
                "amount_cents": amount_cents,
                "expected_reserve_fund_version": version,
            },
            COMPLIANCE,
        )
    )


def contribute_reserve(amount_cents: int) -> dict:
    return adjust_reserve("CONTRIBUTION", amount_cents)


def withdraw_reserve(amount_cents: int) -> dict:
    return adjust_reserve("WITHDRAWAL", amount_cents)


# ---------------------------------------------------------------------------
# Tier 3: agreement lifecycle ladders
# ---------------------------------------------------------------------------

def make_executed_agreement(
    donor_id,
    vehicle_type="CRT_ANNUITY",
    gift_amount_cents=10000000,
    payout_rate_bps=500,
    payment_frequency="QUARTERLY",
    lives=1,
    annuitant_1_age=80,
    annuitant_2_age=None,
    funding_month="2026-08",
    admin_headers=None,
    **extra,
) -> dict:
    """DRAFT -> VERIFIED PRIMARY_1 designation -> EXECUTED.

    For CGA the caller must pre-fund the reserve BEFORE calling (the execution
    reserve gate reads the current balance).
    """
    agreement = make_draft_agreement(
        donor_id,
        vehicle_type=vehicle_type,
        gift_amount_cents=gift_amount_cents,
        payout_rate_bps=payout_rate_bps,
        payment_frequency=payment_frequency,
        lives=lives,
        annuitant_1_age=annuitant_1_age,
        annuitant_2_age=annuitant_2_age,
        funding_month=funding_month,
        **extra,
    )
    make_verified_designation(agreement["id"])
    return get_success_data(
        api_client.execute_gift_agreement(agreement["id"], admin_headers or ADMIN)
    )


def make_funded_agreement(
    donor_id,
    vehicle_type="CRT_ANNUITY",
    gift_amount_cents=10000000,
    payout_rate_bps=500,
    payment_frequency="QUARTERLY",
    lives=1,
    annuitant_1_age=80,
    annuitant_2_age=None,
    funding_month="2026-08",
    admin_headers=None,
    **extra,
) -> dict:
    """EXECUTED -> FUNDED via a CASH asset received at exactly the gift value
    (inclusive funding boundary)."""
    agreement = make_executed_agreement(
        donor_id,
        vehicle_type=vehicle_type,
        gift_amount_cents=gift_amount_cents,
        payout_rate_bps=payout_rate_bps,
        payment_frequency=payment_frequency,
        lives=lives,
        annuitant_1_age=annuitant_1_age,
        annuitant_2_age=annuitant_2_age,
        funding_month=funding_month,
        admin_headers=admin_headers,
        **extra,
    )
    asset = get_success_data(
        api_client.create_gift_asset(
            create_gift_asset_payload(
                gift_agreement_id=agreement["id"],
                asset_kind="CASH",
                pledged_value_cents=gift_amount_cents,
            ),
            ESTATE_MGR,
        )
    )
    get_success_data(
        api_client.transition_gift_asset(asset["id"], {"action": "RECEIVE"}, ESTATE_MGR)
    )
    return get_success_data(api_client.get_gift_agreement(agreement["id"], ADMIN))


def make_active_agreement(
    donor_id,
    vehicle_type="CRT_ANNUITY",
    gift_amount_cents=10000000,
    payout_rate_bps=500,
    payment_frequency="QUARTERLY",
    lives=1,
    annuitant_1_age=80,
    annuitant_2_age=None,
    funding_month="2026-08",
    admin_headers=None,
    **extra,
) -> tuple:
    """FUNDED -> ACTIVE with the full payment schedule generated.

    Returns (agreement_dict, payments_list) with payments sorted by
    period_index ascending.
    """
    agreement = make_funded_agreement(
        donor_id,
        vehicle_type=vehicle_type,
        gift_amount_cents=gift_amount_cents,
        payout_rate_bps=payout_rate_bps,
        payment_frequency=payment_frequency,
        lives=lives,
        annuitant_1_age=annuitant_1_age,
        annuitant_2_age=annuitant_2_age,
        funding_month=funding_month,
        admin_headers=admin_headers,
        **extra,
    )
    payments = get_success_data(
        api_client.generate_payment_schedule(agreement["id"], admin_headers or ADMIN)
    )
    return agreement, payments


def make_funded_cga_with_reserve(
    donor_id,
    gift_amount_cents=10000000,
    payout_rate_bps=600,
    payment_frequency="QUARTERLY",
    annuitant_1_age=80,
    funding_month="2026-08",
    reserve_cents=7570148,
    admin_headers=None,
) -> dict:
    """CGA EXECUTED then FUNDED, with `reserve_cents` contributed to the
    reserve fund before execution (the CGA execution reserve gate requires
    balance >= booked target + other EXECUTED requirements + candidate's own
    requirement). For the standard economics (10M gift, 600bps, age 80) the
    requirement is 7_570_148 cents, so the default lands the fund at exactly
    10000 bps booked coverage once funded."""
    agreement = make_draft_agreement(
        donor_id,
        vehicle_type="CGA",
        gift_amount_cents=gift_amount_cents,
        payout_rate_bps=payout_rate_bps,
        payment_frequency=payment_frequency,
        annuitant_1_age=annuitant_1_age,
        funding_month=funding_month,
    )
    make_verified_designation(agreement["id"])
    if reserve_cents:
        contribute_reserve(reserve_cents)
    agreement = get_success_data(
        api_client.execute_gift_agreement(agreement["id"], admin_headers or ADMIN)
    )
    asset = get_success_data(
        api_client.create_gift_asset(
            create_gift_asset_payload(
                gift_agreement_id=agreement["id"],
                asset_kind="CASH",
                pledged_value_cents=gift_amount_cents,
            ),
            ESTATE_MGR,
        )
    )
    get_success_data(
        api_client.transition_gift_asset(asset["id"], {"action": "RECEIVE"}, ESTATE_MGR)
    )
    return get_success_data(api_client.get_gift_agreement(agreement["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: clock / payment queries
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (sweeps run atomically with the write)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, COMPLIANCE)
    )


def list_payments(agreement_id, status=None, limit=100) -> tuple:
    """(payments, meta) for an agreement, optionally status-filtered."""
    params = {"gift_agreement_id": agreement_id, "limit": limit}
    if status is not None:
        params["status"] = status
    return validate_paginated(api_client.list_annuity_payments(ADMIN, params=params))


def list_assets(params) -> tuple:
    return validate_paginated(api_client.list_gift_assets(ESTATE_MGR, params=params))


# ---------------------------------------------------------------------------
# Tier 5: estates / probate / funds / valuation runs
# ---------------------------------------------------------------------------

def make_deceased_donor(
    full_name="Estate Donor",
    date_of_birth="1935-01-01T00:00:00Z",
    deceased_on="2026-08-03T00:00:00Z",
    recorder_headers=None,
) -> dict:
    """Register a donor and record the death. Returns the DECEASED donor."""
    donor = make_donor(full_name=full_name, date_of_birth=date_of_birth)
    return get_success_data(
        api_client.record_death(
            donor["id"], {"deceased_on": deceased_on}, recorder_headers or ESTATE_MGR
        )
    )


def make_estate(
    donor_id,
    notified_on="2026-08-04T00:00:00Z",
    gift_agreement_id=None,
    recorder_headers=None,
) -> dict:
    """Open an estate file for a DECEASED donor (recorder = SoD anchor)."""
    payload = create_estate_payload(donor_id=donor_id, notified_on=notified_on)
    if gift_agreement_id is not None:
        payload["gift_agreement_id"] = gift_agreement_id
    return get_success_data(
        api_client.create_estate(payload, recorder_headers or ESTATE_MGR)
    )


def make_probate_open_estate(
    donor_id,
    notified_on="2026-08-04T00:00:00Z",
    gift_agreement_id=None,
    recorder_headers=None,
) -> dict:
    """Estate walked NOTIFIED -> PROBATE_OPEN."""
    estate = make_estate(
        donor_id,
        notified_on=notified_on,
        gift_agreement_id=gift_agreement_id,
        recorder_headers=recorder_headers,
    )
    return get_success_data(
        api_client.transition_estate(
            estate["id"], {"action": "OPEN_PROBATE"}, recorder_headers or ESTATE_MGR
        )
    )


def make_milestone(estate_id, kind="PETITION", due_date="2027-01-01T00:00:00Z") -> dict:
    """Add a PENDING probate milestone to an estate."""
    return get_success_data(
        api_client.create_probate_milestone(
            create_probate_milestone_payload(
                estate_id=estate_id, kind=kind, due_date=due_date
            ),
            ESTATE_MGR,
        )
    )


def close_milestone(milestone_id) -> dict:
    """Walk a milestone PENDING -> FILED -> CLOSED."""
    get_success_data(
        api_client.transition_probate_milestone(milestone_id, {"action": "FILE"}, ESTATE_MGR)
    )
    return get_success_data(
        api_client.transition_probate_milestone(milestone_id, {"action": "CLOSE"}, ESTATE_MGR)
    )


def make_liquidated_cash_asset(estate_id, value_cents, liquidation_costs_cents=0) -> dict:
    """Estate-linked CASH asset walked PLEDGED -> RECEIVED -> LIQUIDATED with
    gross proceeds equal to the pledged value."""
    asset = get_success_data(
        api_client.create_gift_asset(
            create_gift_asset_payload(
                estate_id=estate_id, asset_kind="CASH", pledged_value_cents=value_cents
            ),
            ESTATE_MGR,
        )
    )
    get_success_data(
        api_client.transition_gift_asset(asset["id"], {"action": "RECEIVE"}, ESTATE_MGR)
    )
    return get_success_data(
        api_client.transition_gift_asset(
            asset["id"],
            {
                "action": "LIQUIDATE",
                "gross_proceeds_cents": value_cents,
                "liquidation_costs_cents": liquidation_costs_cents,
            },
            ESTATE_MGR,
        )
    )


def make_fund(agreement_id, name="Test Fund", restriction_type="SCHOLARSHIP", **extra) -> dict:
    """Create a PROPOSED fund linked to an agreement."""
    return get_success_data(
        api_client.create_fund(
            create_fund_payload(
                name=name,
                restriction_type=restriction_type,
                gift_agreement_id=agreement_id,
                **extra,
            ),
            FINANCE,
        )
    )


def make_valuation_run(
    coverage_start="2026-01-01T00:00:00Z",
    coverage_end="2026-06-30T00:00:00Z",
    valuation_date="2026-03-01T00:00:00Z",
    corpus_updates=None,
    creator_headers=None,
) -> dict:
    """Create a DRAFT valuation run (creator = SoD anchor)."""
    payload = create_valuation_run_payload(
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        valuation_date=valuation_date,
    )
    if corpus_updates is not None:
        payload["corpus_updates"] = corpus_updates
    return get_success_data(
        api_client.create_valuation_run(payload, creator_headers or COMPLIANCE)
    )


def make_posted_valuation_run(
    coverage_start="2026-01-01T00:00:00Z",
    coverage_end="2026-06-30T00:00:00Z",
    valuation_date="2026-03-01T00:00:00Z",
    corpus_updates=None,
    creator_headers=None,
    poster_headers=None,
) -> dict:
    """DRAFT -> POSTED valuation run. Poster defaults to a different
    ComplianceOfficer user id than the creator to satisfy segregation of
    duties."""
    creator = creator_headers or make_compliance_headers("co-1")
    poster = poster_headers or make_compliance_headers("co-2")
    run = make_valuation_run(
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        valuation_date=valuation_date,
        corpus_updates=corpus_updates,
        creator_headers=creator,
    )
    return get_success_data(api_client.post_valuation_run(run["id"], poster))
