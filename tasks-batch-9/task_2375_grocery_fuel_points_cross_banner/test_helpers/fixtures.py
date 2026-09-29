"""Setup builders.

Every helper here builds real state through the endpoints the PRD declares —
there is no direct database access anywhere.  The server is restarted with an
empty database before each individual test, so every builder starts from
nothing.

Two conventions:

* Where an operation is guarded by resource ownership, the builder threads the
  real entity identity (the acting site's `id`, the acting member's `id`) into
  the headers rather than using a shared placeholder.
* Where ownership never applies (the three operator roles), the builder acts as
  `ProgramAdmin` so that setup never trips a rule the test is not about.
"""
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import MID_AUGUST, MONTH_WINDOWS, TEST_DEFAULTS
from . import factories as f
from .test_users import (
    ADMIN,
    ANALYST,
    SUPERVISOR,
    make_member_headers,
    make_pump_terminal_headers,
    make_settlement_clerk_headers,
    make_store_operator_headers,
)

Gallons = Union[str, float, int]


# ==========================================================================
# The logical clock
# ==========================================================================
def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical UTC clock. Performs no writes of its own."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ==========================================================================
# Banner, cycles, sites
# ==========================================================================
def create_banner(headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_banner(f.banner_payload(**overrides), headers), 201
    )


def suspend_banner(banner_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.suspend_banner(banner_id, headers))


def create_cycle(banner_id: str, cycle_month: str = "2026-08", headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_point_cycle(
            f.point_cycle_payload(banner_id, cycle_month, **overrides), headers
        ),
        201,
    )


def create_month_cycles(
    banner_id: str, months: Sequence[str] = ("2026-08", "2026-09"), headers=ADMIN
) -> dict:
    """Define one cycle per named month, keyed by `cycle_month`.

    Accrual needs the month immediately after the open one to exist, so the
    two-month default is the minimum a posting test can work with.
    """
    return {m: create_cycle(banner_id, m, headers) for m in months}


def create_grocery_site(banner_id: str, site_number: str = "G-001", headers=ADMIN) -> dict:
    return get_success_data(
        api_client.create_site(f.grocery_site_payload(banner_id, site_number), headers), 201
    )


def create_owned_fuel_center(banner_id: str, site_number: str = "F-001", headers=ADMIN) -> dict:
    return get_success_data(
        api_client.create_site(f.owned_fuel_center_payload(banner_id, site_number), headers), 201
    )


def create_partner_station(
    banner_id: str,
    site_number: str = "P-001",
    partner_code: str = "PTR001",
    per_gallon_cap_cents: int = TEST_DEFAULTS["PARTNER_PER_GALLON_CAP_CENTS"],
    max_gallons_per_redemption: int = TEST_DEFAULTS["PARTNER_MAX_GALLONS_PER_REDEMPTION"],
    headers=ADMIN,
) -> dict:
    return get_success_data(
        api_client.create_site(
            f.partner_station_payload(
                banner_id,
                site_number=site_number,
                partner_code=partner_code,
                per_gallon_cap_cents=per_gallon_cap_cents,
                max_gallons_per_redemption=max_gallons_per_redemption,
            ),
            headers,
        ),
        201,
    )


def suspend_site(site_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.suspend_site(site_id, headers))


def site_version(site_id: str, headers=ADMIN) -> int:
    """The site `version` a settlement batch must guard against."""
    return get_success_data(api_client.get_site(site_id, headers))["version"]


# ==========================================================================
# Members, households, linkage
# ==========================================================================
def create_member(
    banner_id: str,
    alt_id: str = "5550000001",
    card_number: str = "4000000000000001",
    full_name: str = "Test Member",
    headers=ADMIN,
) -> dict:
    return get_success_data(
        api_client.create_member(
            f.member_payload(banner_id, alt_id, card_number, full_name), headers
        ),
        201,
    )


def create_household(banner_id: str, household_code: str = "HH-0001", headers=ADMIN) -> dict:
    return get_success_data(
        api_client.create_household(f.household_payload(banner_id, household_code), headers), 201
    )


def create_link(
    household_id: str,
    member_id: str,
    link_role: str = "PRIMARY",
    activate: bool = True,
    headers=ADMIN,
) -> dict:
    """Propose a linkage and, by default, activate it.

    A `PENDING` linkage grants nothing, so tests that need real household
    coverage must activate.
    """
    link = get_success_data(
        api_client.create_household_link(
            f.household_link_payload(household_id, member_id, link_role), headers
        ),
        201,
    )
    if activate:
        link = get_success_data(api_client.activate_household_link(link["id"], headers))
    return link


def get_link(link_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_household_link(link_id, headers))


def activate_link(link_id: str, headers=ANALYST) -> dict:
    return get_success_data(api_client.activate_household_link(link_id, headers))


def suspend_link(link_id: str, headers=ANALYST) -> dict:
    return get_success_data(api_client.suspend_household_link(link_id, headers))


def revoke_link(link_id: str, headers=ANALYST) -> dict:
    return get_success_data(api_client.revoke_household_link(link_id, headers))


def freeze_household(household_id: str, headers=SUPERVISOR) -> dict:
    return get_success_data(api_client.freeze_household(household_id, headers))


def unfreeze_household(household_id: str, headers=SUPERVISOR) -> dict:
    return get_success_data(api_client.unfreeze_household(household_id, headers))


def get_household(household_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_household(household_id, headers))


def get_member(member_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_member(member_id, headers))


def member_version(member_id: str, headers=ADMIN) -> int:
    """The member `version` a pump authorization must guard against."""
    return get_member(member_id, headers)["version"]


def points_summary(member_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_points_summary(member_id, headers))


# ==========================================================================
# Promotional events
# ==========================================================================
def create_promo(
    banner_id: str,
    promo_code: str = "P_DOUBLE",
    multiplier: int = 2,
    applies_to_categories: Optional[List[str]] = None,
    starts_at: str = "2026-08-01T00:00:00Z",
    ends_at: str = "2026-09-01T00:00:00Z",
    stack_priority: int = 10,
    activate: bool = True,
    headers=ADMIN,
) -> dict:
    """Schedule a promotional event and, by default, activate it.

    A `SCHEDULED` event contributes nothing to accrual, so a promotion that is
    meant to affect points must be activated.
    """
    promo = get_success_data(
        api_client.create_promo_event(
            f.promo_event_payload(
                banner_id,
                promo_code=promo_code,
                multiplier=multiplier,
                applies_to_categories=applies_to_categories,
                starts_at=starts_at,
                ends_at=ends_at,
                stack_priority=stack_priority,
            ),
            headers,
        ),
        201,
    )
    if activate:
        promo = get_success_data(api_client.activate_promo_event(promo["id"], headers))
    return promo


# ==========================================================================
# Baskets
# ==========================================================================
def record_basket(
    member_id: str,
    site_id: str,
    lines: Optional[List[dict]] = None,
    transacted_at: str = MID_AUGUST,
    headers=None,
) -> dict:
    """Record a basket at a grocery site, acting as that site's operator."""
    return get_success_data(
        api_client.create_purchase_transaction(
            f.purchase_transaction_payload(member_id, site_id, transacted_at, lines),
            headers if headers is not None else make_store_operator_headers(site_id),
        ),
        201,
    )


def post_basket(transaction_id: str, site_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.post_purchase_transaction(
            transaction_id,
            headers if headers is not None else make_store_operator_headers(site_id),
        )
    )


def void_basket(transaction_id: str, site_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.void_purchase_transaction(
            transaction_id,
            headers if headers is not None else make_store_operator_headers(site_id),
        )
    )


def accrue_points(
    member_id: str,
    grocery_site_id: str,
    points: int,
    transacted_at: str = MID_AUGUST,
) -> dict:
    """Give a member exactly `points` points through a posted grocery basket.

    A `GROCERY` line's base is its `amount_cents` divided by one hundred times
    the banner's `base_points_per_dollar`, and a grocery line's category
    multiplier is 1 — so at the default configuration, and with no promotional
    event live, a line of `points * 100` cents awards exactly `points` points.
    Returns the posted transaction.
    """
    txn = record_basket(
        member_id,
        grocery_site_id,
        [f.purchase_line("GROCERY", points * 100, 1)],
        transacted_at,
    )
    return post_basket(txn["id"], grocery_site_id)


# ==========================================================================
# Ledger
# ==========================================================================
def ledger_entries(member_id: str, headers=ADMIN, **filters) -> List[dict]:
    """Every ledger row of a member in `created_at` ascending order."""
    params = {"member_id": member_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_point_ledger_entries(headers, params))


def ledger_sum(member_id: str, headers=ADMIN) -> int:
    return sum(e["points_delta"] for e in ledger_entries(member_id, headers))


# ==========================================================================
# Transfers
# ==========================================================================
def transfer_points(
    member_id: str, recipient_member_id: str, points: int = 100, headers=ANALYST
) -> dict:
    return get_success_data(
        api_client.create_point_transfer(
            f.point_transfer_payload(member_id, recipient_member_id, points), headers
        ),
        201,
    )


# ==========================================================================
# Pump authorizations and fills
# ==========================================================================
def authorize_redemption(
    member_id: str,
    site_id: str,
    alt_id_presented: str,
    points_committed: int,
    expected_member_version: Optional[int] = None,
    headers=None,
) -> dict:
    """Authorize a per-gallon discount, acting as the pump at `site_id`.

    When `expected_member_version` is omitted the member's current `version` is
    read first, which is what a real pump does between the alternate-ID lookup
    and the commitment.
    """
    if expected_member_version is None:
        expected_member_version = member_version(member_id)
    return get_success_data(
        api_client.create_fuel_redemption(
            f.fuel_redemption_payload(
                member_id,
                site_id,
                alt_id_presented,
                points_committed,
                expected_member_version,
            ),
            headers if headers is not None else make_pump_terminal_headers(site_id),
        ),
        201,
    )


def complete_fill(
    redemption_id: str, site_id: str, gallons_dispensed: Gallons, headers=None
) -> dict:
    return get_success_data(
        api_client.complete_fuel_redemption(
            redemption_id,
            {"gallons_dispensed": gallons_dispensed},
            headers if headers is not None else make_pump_terminal_headers(site_id),
        )
    )


def void_redemption(redemption_id: str, site_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.void_fuel_redemption(
            redemption_id,
            headers if headers is not None else make_pump_terminal_headers(site_id),
        )
    )


def get_redemption(redemption_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_fuel_redemption(redemption_id, headers))


# ==========================================================================
# Settlement
# ==========================================================================
def open_batch(
    site_id: str,
    period_start: str,
    period_end: str,
    expected_site_version: Optional[int] = None,
    headers=None,
) -> dict:
    """Draft a settlement batch, acting as that partner station's clerk."""
    if expected_site_version is None:
        expected_site_version = site_version(site_id)
    return get_success_data(
        api_client.create_settlement_batch(
            f.settlement_batch_payload(
                site_id, period_start, period_end, expected_site_version
            ),
            headers if headers is not None else make_settlement_clerk_headers(site_id),
        ),
        201,
    )


def submit_batch(batch_id: str, site_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.submit_settlement_batch(
            batch_id,
            headers if headers is not None else make_settlement_clerk_headers(site_id),
        )
    )


def approve_batch(batch_id: str, headers=ADMIN) -> dict:
    """Approve a submitted batch. The approver must differ from the submitter,
    which the clerk-submits-then-admin-approves default satisfies."""
    return get_success_data(api_client.approve_settlement_batch(batch_id, headers))


def reject_batch(batch_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.reject_settlement_batch(batch_id, headers))


def get_batch(batch_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_settlement_batch(batch_id, headers))


def get_site(site_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_site(site_id, headers))


# ==========================================================================
# Cycle close
# ==========================================================================
def begin_close(cycle_id: str, headers=SUPERVISOR) -> dict:
    return get_success_data(api_client.begin_close_point_cycle(cycle_id, headers))


def close_cycle(cycle_id: str, headers=SUPERVISOR) -> dict:
    return get_success_data(api_client.close_point_cycle(cycle_id, headers))


def run_close(cycle_id: str, at_instant: str, headers=SUPERVISOR) -> dict:
    """Advance the clock past the cycle's window and run both close phases."""
    set_clock(at_instant)
    begin_close(cycle_id, headers)
    return close_cycle(cycle_id, headers)


# ==========================================================================
# Fraud signals
# ==========================================================================
def raise_signal(
    household_id: str,
    signal_type: str = "RAPID_TRANSFER",
    severity_weight: int = 25,
    headers=ANALYST,
) -> dict:
    return get_success_data(
        api_client.create_fraud_signal(
            f.fraud_signal_payload(household_id, signal_type, severity_weight), headers
        ),
        201,
    )


def clear_signal(signal_id: str, headers=ANALYST) -> dict:
    return get_success_data(api_client.clear_fraud_signal(signal_id, headers))


# ==========================================================================
# Disputes
# ==========================================================================
def file_dispute(
    member_id: str,
    disputed_ledger_entry_id: str,
    claimed_points: int = 100,
    reason_code: str = "MISSING_ACCRUAL",
    headers=ANALYST,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_point_dispute(
            f.point_dispute_payload(
                member_id, disputed_ledger_entry_id, claimed_points, reason_code, **overrides
            ),
            headers,
        ),
        201,
    )


def investigate_dispute(dispute_id: str, headers=ANALYST) -> dict:
    return get_success_data(api_client.investigate_point_dispute(dispute_id, headers))


def propose_adjustment(
    dispute_id: str,
    proposed_points_delta: int = 100,
    authority_tier: str = "TIER1",
    headers=ANALYST,
) -> dict:
    return get_success_data(
        api_client.propose_dispute_adjustment(
            dispute_id,
            f.propose_adjustment_payload(proposed_points_delta, authority_tier),
            headers,
        )
    )


def approve_adjustment(dispute_id: str, headers=SUPERVISOR) -> dict:
    """Approve a proposed adjustment. The approver must differ from the
    proposer, which the analyst-proposes-then-supervisor-approves default
    satisfies."""
    return get_success_data(api_client.approve_dispute_adjustment(dispute_id, headers))


def deny_dispute(dispute_id: str, headers=SUPERVISOR) -> dict:
    return get_success_data(api_client.deny_point_dispute(dispute_id, headers))


# ==========================================================================
# Composite scenarios
# ==========================================================================
def standard_program(
    months: Sequence[str] = ("2026-08", "2026-09"), **banner_overrides
) -> dict:
    """A banner with its cycles and one grocery lane.

    Returns `{"banner", "cycles", "grocery"}` where `cycles` is keyed by
    `cycle_month`.
    """
    banner = create_banner(**banner_overrides)
    cycles = create_month_cycles(banner["id"], months)
    grocery = create_grocery_site(banner["id"])
    return {"banner": banner, "cycles": cycles, "grocery": grocery}


def program_with_member(
    points: int = 0,
    alt_id: str = "5550000001",
    months: Sequence[str] = ("2026-08", "2026-09"),
    **banner_overrides,
) -> dict:
    """A standard program plus one enrolled member, optionally pre-funded.

    Returns `{"banner", "cycles", "grocery", "member"}`.
    """
    program = standard_program(months, **banner_overrides)
    member = create_member(program["banner"]["id"], alt_id=alt_id)
    if points:
        accrue_points(member["id"], program["grocery"]["id"], points)
        member = get_member(member["id"])
    program["member"] = member
    return program


def program_with_household(
    points: int = 0,
    alt_id: str = "5550000001",
    months: Sequence[str] = ("2026-08", "2026-09"),
    **banner_overrides,
) -> dict:
    """A funded member holding an `ACTIVE` `PRIMARY` linkage to a household.

    Returns `{"banner", "cycles", "grocery", "member", "household", "link"}`.
    """
    program = program_with_member(points, alt_id, months, **banner_overrides)
    household = create_household(program["banner"]["id"])
    link = create_link(household["id"], program["member"]["id"], "PRIMARY", activate=True)
    program["household"] = household
    program["link"] = link
    return program


def owned_fuel_program(
    points: int = 1000,
    alt_id: str = "5550000001",
    months: Sequence[str] = ("2026-08", "2026-09"),
    **banner_overrides,
) -> dict:
    """A funded member and an owned fuel center at the same banner.

    Returns the `program_with_member` keys plus `"fuel"`.
    """
    program = program_with_member(points, alt_id, months, **banner_overrides)
    program["fuel"] = create_owned_fuel_center(program["banner"]["id"])
    return program


def partner_fuel_program(
    points: int = 1000,
    alt_id: str = "5550000001",
    per_gallon_cap_cents: int = TEST_DEFAULTS["PARTNER_PER_GALLON_CAP_CENTS"],
    max_gallons_per_redemption: int = TEST_DEFAULTS["PARTNER_MAX_GALLONS_PER_REDEMPTION"],
    months: Sequence[str] = ("2026-08", "2026-09"),
    **banner_overrides,
) -> dict:
    """A funded member and a partner station at the same banner.

    A partner station at the member's own banner needs no cross-banner linkage,
    which keeps settlement scenarios to a single banner.  Returns the
    `program_with_member` keys plus `"partner"`.
    """
    program = program_with_member(points, alt_id, months, **banner_overrides)
    program["partner"] = create_partner_station(
        program["banner"]["id"],
        per_gallon_cap_cents=per_gallon_cap_cents,
        max_gallons_per_redemption=max_gallons_per_redemption,
    )
    return program


def cross_banner_program(
    points: int = 1000,
    alt_id: str = "5550000001",
    months: Sequence[str] = ("2026-08", "2026-09"),
    home_overrides: Optional[dict] = None,
    away_overrides: Optional[dict] = None,
) -> dict:
    """A member enrolled at one banner who may fuel at a second banner's pump.

    The member holds an `ACTIVE` linkage to a household of the *away* banner,
    which is the entire mechanism by which a shopper enrolled at one banner
    fuels at another.  Returns
    `{"home", "away", "member", "household", "link", "fuel"}` where `home` and
    `away` are `standard_program` dicts.
    """
    home = standard_program(months, banner_code="HOME", **(home_overrides or {}))
    away = standard_program(
        months, banner_code="AWAY", name="Away Grocery Banner", **(away_overrides or {})
    )
    member = create_member(home["banner"]["id"], alt_id=alt_id)
    if points:
        accrue_points(member["id"], home["grocery"]["id"], points)
        member = get_member(member["id"])
    household = create_household(away["banner"]["id"], "HH-AWAY")
    link = create_link(household["id"], member["id"], "PRIMARY", activate=True)
    fuel = create_owned_fuel_center(away["banner"]["id"], "F-AWAY")
    return {
        "home": home,
        "away": away,
        "member": member,
        "household": household,
        "link": link,
        "fuel": fuel,
    }


def dispensed_partner_fill(
    points_committed: int,
    gallons_dispensed: Gallons,
    per_gallon_cap_cents: int = TEST_DEFAULTS["PARTNER_PER_GALLON_CAP_CENTS"],
    max_gallons_per_redemption: int = TEST_DEFAULTS["PARTNER_MAX_GALLONS_PER_REDEMPTION"],
    points: int = 10000,
    **banner_overrides,
) -> dict:
    """One completed fill at a partner station, sitting `PENDING` on the
    settlement dimension and therefore in the site's unbatched pool.

    Returns the `partner_fuel_program` keys plus `"redemption"`.
    """
    program = partner_fuel_program(
        points=points,
        per_gallon_cap_cents=per_gallon_cap_cents,
        max_gallons_per_redemption=max_gallons_per_redemption,
        **banner_overrides,
    )
    redemption = authorize_redemption(
        program["member"]["id"],
        program["partner"]["id"],
        program["member"]["alt_id"],
        points_committed,
    )
    program["redemption"] = complete_fill(
        redemption["id"], program["partner"]["id"], gallons_dispensed
    )
    return program


def add_dispensed_fill(
    program: dict,
    points_committed: int,
    gallons_dispensed: Gallons,
    member: Optional[dict] = None,
) -> dict:
    """Authorize and complete one more fill at the program's partner station."""
    target = member if member is not None else program["member"]
    redemption = authorize_redemption(
        target["id"], program["partner"]["id"], target["alt_id"], points_committed
    )
    return complete_fill(redemption["id"], program["partner"]["id"], gallons_dispensed)
