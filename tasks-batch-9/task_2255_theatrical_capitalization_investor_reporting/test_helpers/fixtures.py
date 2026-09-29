"""
Composite state builders.

The suite runs against a server that is restarted with an empty database before
every single test, so nothing here may assume a pre-existing row. Every builder
walks the documented endpoints in the order the PRD allows, in tiers: a house
and a show, then an active operating budget, then an offering and an investor,
then capitalization, then the operating calendar, then a certified wrap. Each
tier returns the same mutable `World` so a test can stop at whatever depth it
needs.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as K
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    COMPTROLLER_HEADERS,
    COMPTROLLER_USER_ID,
    COUNSEL_HEADERS,
    GM_HEADERS,
    GM_USER_ID,
    PRODUCER_HEADERS,
    make_investor_headers,
)


@dataclass
class World:
    """Ids and headers for one built-up production."""

    client: ApiClient
    theatre_id: str
    production_id: str
    operating_budget_id: Optional[str] = None
    offering_document_id: Optional[str] = None
    investor_id: Optional[str] = None
    investor_headers: Optional[Dict[str, str]] = None
    subscription_id: Optional[str] = None
    wrap_id: Optional[str] = None
    participant_ids: List[str] = field(default_factory=list)
    reserve_line_id: Optional[str] = None
    closing_notice_id: Optional[str] = None

    # ─── Convenience reads ────────────────────────────────────────────────

    def production(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Read the production row back."""
        response = self.client.get_production(
            self.production_id, headers or COMPTROLLER_HEADERS
        )
        return get_success_data(response, 200)

    def production_version(self) -> int:
        """The current OCC token for the two endpoints that demand one."""
        return int(self.production()["version"])

    def set_clock(self, date_str: str) -> None:
        """Move the logical clock to midnight on a calendar date."""
        response = self.client.set_clock(K.iso_midnight(date_str), GM_HEADERS)
        get_success_data(response, 200)


# ─── Tier 0: a house and a show ───────────────────────────────────────────


def new_theatre(client: ApiClient, **overrides: Any) -> str:
    """Book a house. The General Manager is the office that creates theatres."""
    payload = F.theatre_payload(**{**K.PALACE, **overrides})
    response = client.create_theatre(payload, GM_HEADERS)
    return get_success_data(response, 201)["id"]


def new_production(client: ApiClient, theatre_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open a production file against a house, returning the whole row."""
    spelled = {
        key: value
        for key, value in K.UNDERSTUDY.items()
        if key not in ("title", "offering_entity_type")
    }
    payload = F.production_payload(
        theatre_id,
        title=overrides.pop("title", K.UNDERSTUDY["title"]),
        offering_entity_type=overrides.pop(
            "offering_entity_type", K.UNDERSTUDY["offering_entity_type"]
        ),
        **{**spelled, **overrides},
    )
    response = client.create_production(payload, GM_HEADERS)
    return get_success_data(response, 201)


def base_world(client: ApiClient, **production_overrides: Any) -> World:
    """A house plus a DRAFT production file: the floor every other tier stands on."""
    theatre_id = new_theatre(client)
    production = new_production(client, theatre_id, **production_overrides)
    return World(
        client=client, theatre_id=theatre_id, production_id=production["id"]
    )


# ─── Tier 1: an active operating budget ───────────────────────────────────


def with_active_operating_budget(world: World, **overrides: Any) -> World:
    """Draft a weekly running-cost model and activate it."""
    payload = F.operating_budget_payload(
        world.production_id,
        **{**K.LEDGER_OPERATING_BUDGET, **overrides},
    )
    created = get_success_data(
        world.client.create_operating_budget(payload, GM_HEADERS), 201
    )
    get_success_data(
        world.client.activate_operating_budget(created["id"], COMPTROLLER_HEADERS), 200
    )
    world.operating_budget_id = created["id"]
    return world


# ─── Tier 2: an offering, a document and an accredited investor ───────────


def open_offering(world: World) -> World:
    """Counsel moves the syndication axis from DRAFT to OFFERING."""
    get_success_data(
        world.client.open_offering(world.production_id, COUNSEL_HEADERS), 200
    )
    return world


def with_effective_document(world: World, **doc_overrides: Any) -> World:
    """Create an offering document and make it EFFECTIVE."""
    payload = F.offering_document_payload(world.production_id, **doc_overrides)
    created = get_success_data(
        world.client.create_offering_document(payload, COUNSEL_HEADERS), 201
    )
    get_success_data(
        world.client.make_offering_document_effective(created["id"], COUNSEL_HEADERS),
        200,
    )
    world.offering_document_id = created["id"]
    return world


def new_accredited_investor(
    world: World,
    legal_name: str = "Amelia Hart",
    contact_email: str = "amelia.hart@example.com",
    **overrides: Any,
) -> str:
    """Register an investor and record an ACCREDITED determination for it."""
    payload = F.investor_payload(
        legal_name=legal_name, contact_email=contact_email, **overrides
    )
    investor = get_success_data(
        world.client.create_investor(payload, COUNSEL_HEADERS), 201
    )
    get_success_data(
        world.client.accredit_investor(
            investor["id"], F.accreditation_payload("ACCREDITED"), COUNSEL_HEADERS
        ),
        200,
    )
    return investor["id"]


def new_subscription(world: World, investor_id: str, units: int = 1) -> str:
    """An investor subscribes for units in its own name."""
    payload = F.subscription_payload(
        world.offering_document_id or "", investor_id, units
    )
    response = world.client.create_subscription(
        payload, make_investor_headers(investor_id)
    )
    return get_success_data(response, 201)["id"]


def accept_subscription(world: World, subscription_id: str) -> Dict[str, Any]:
    """Counsel accepts a subscription, which opens or grows a capital account."""
    return get_success_data(
        world.client.accept_subscription(subscription_id, COUNSEL_HEADERS), 200
    )


def with_accepted_subscription(world: World, **doc_overrides: Any) -> World:
    """Walk the whole syndication tier: offering, document, investor, acceptance."""
    open_offering(world)
    with_effective_document(world, **doc_overrides)
    world.investor_id = new_accredited_investor(world)
    world.investor_headers = make_investor_headers(world.investor_id)
    world.subscription_id = new_subscription(world, world.investor_id)
    accept_subscription(world, world.subscription_id)
    return world


# ─── Tier 3: capitalization ───────────────────────────────────────────────


def capitalize(world: World) -> Dict[str, Any]:
    """The Comptroller releases escrow into the production's working capital."""
    return get_success_data(
        world.client.capitalize(world.production_id, COMPTROLLER_HEADERS), 200
    )


def capitalized_world(client: ApiClient, **production_overrides: Any) -> World:
    """A production whose single accepted unit filled the target, then capitalized."""
    world = base_world(client, **production_overrides)
    with_active_operating_budget(world)
    with_accepted_subscription(world)
    capitalize(world)
    return world


# ─── Tier 4: the operating calendar ───────────────────────────────────────


def advance_operating_status(world: World, *statuses: str) -> Dict[str, Any]:
    """Walk the operating axis one documented hop at a time."""
    data: Dict[str, Any] = {}
    for status in statuses:
        data = get_success_data(
            world.client.set_operating_status(
                world.production_id, F.operating_status_payload(status), PRODUCER_HEADERS
            ),
            200,
        )
    return data


def running_world(client: ApiClient, **production_overrides: Any) -> World:
    """A capitalized production that has reached operating_status RUNNING."""
    world = capitalized_world(client, **production_overrides)
    advance_operating_status(world, "REHEARSAL", "PREVIEWS", "RUNNING")
    return world


# ─── Tier 5: a certified week ─────────────────────────────────────────────


def new_wrap(world: World, **overrides: Any) -> str:
    """Record a week of box office against the pinned active operating budget."""
    payload = F.standard_week_payload(world.production_id, **overrides)
    response = world.client.create_weekly_wrap(payload, GM_HEADERS)
    return get_success_data(response, 201)["id"]


def submit_wrap(world: World, wrap_id: str) -> Dict[str, Any]:
    """Submit a wrap for certification as `u-gm-1`."""
    return get_success_data(world.client.submit_weekly_wrap(wrap_id, GM_HEADERS), 200)


def certify_wrap(world: World, wrap_id: str) -> Dict[str, Any]:
    """Certify a wrap as `u-ct-1`, an operator other than the submitter."""
    return get_success_data(
        world.client.certify_weekly_wrap(wrap_id, COMPTROLLER_HEADERS), 200
    )


def with_submitted_standard_week(world: World, **overrides: Any) -> World:
    """Move the clock past the week, record the standard week, and submit it."""
    world.set_clock("2026-09-07")
    world.wrap_id = new_wrap(world, **overrides)
    submit_wrap(world, world.wrap_id)
    return world


def certified_week_world(client: ApiClient, **production_overrides: Any) -> World:
    """A RUNNING production carrying exactly one CERTIFIED standard week."""
    world = running_world(client, **production_overrides)
    with_submitted_standard_week(world)
    certify_wrap(world, world.wrap_id or "")
    return world


# ─── Royalty participants ─────────────────────────────────────────────────


def with_standard_participants(world: World) -> World:
    """Sign the three royalty participants the depth scenarios settle against."""
    for spec in (
        K.PARTICIPANT_AUTHOR,
        K.PARTICIPANT_COMPOSER,
        K.PARTICIPANT_DIRECTOR,
    ):
        created = get_success_data(
            world.client.create_royalty_participant(
                F.participant_payload_from(world.production_id, spec), GM_HEADERS
            ),
            201,
        )
        world.participant_ids.append(created["id"])
    return world


def convert_to_pool(world: World) -> Dict[str, Any]:
    """The Lead Producer flips the royalty basis to POOL, one way only."""
    return get_success_data(
        world.client.convert_royalties_to_pool(world.production_id, PRODUCER_HEADERS),
        200,
    )


# ─── The depth scenario: Belasco House and "The Ledger" ───────────────────


def ledger_world(
    client: ApiClient,
    capitalization_target_cents: int = 120_000_000,
    unit_price_cents: int = 120_000_000,
    pool_basis: bool = False,
    **production_overrides: Any,
) -> World:
    """Belasco House, "The Ledger", three participants, one filled unit, RUNNING.

    `capitalization_target_cents` and `unit_price_cents` move together in the
    threshold-targeting variants, because one accepted unit has to raise exactly
    the target for the recoupment boundary tests to land on the cent.
    """
    theatre_id = new_theatre(client, **K.BELASCO)
    production = new_production(
        client,
        theatre_id,
        title=K.LEDGER["title"],
        offering_entity_type=K.LEDGER["offering_entity_type"],
        capitalization_target_cents=capitalization_target_cents,
        reserve_target_cents=K.LEDGER["reserve_target_cents"],
        pre_recoupment_pool_pct=K.LEDGER["pre_recoupment_pool_pct"],
        post_recoupment_pool_pct=K.LEDGER["post_recoupment_pool_pct"],
        subsidiary_rights_investor_share_pct=K.LEDGER[
            "subsidiary_rights_investor_share_pct"
        ],
        closing_notice_min_days=K.LEDGER["closing_notice_min_days"],
        **production_overrides,
    )
    world = World(
        client=client, theatre_id=theatre_id, production_id=production["id"]
    )
    with_active_operating_budget(world)
    with_standard_participants(world)
    if pool_basis:
        convert_to_pool(world)
    with_accepted_subscription(
        world,
        offering_amount_cents=capitalization_target_cents,
        unit_price_cents=unit_price_cents,
        max_investors=5,
        effective_date="2026-08-01",
    )
    capitalize(world)
    advance_operating_status(world, "REHEARSAL", "PREVIEWS", "RUNNING")
    return world


# ─── Reserve line and closing notice chains ───────────────────────────────


def with_reserve_line(world: World, amount_cents: int = 20_000_000) -> World:
    """Add a RESERVE budget line, quoting the production's current version."""
    payload = F.reserve_line_payload(
        world.production_id, amount_cents, world.production_version()
    )
    created = get_success_data(
        world.client.create_budget_line(payload, GM_HEADERS), 201
    )
    world.reserve_line_id = created["id"]
    return world


def with_issued_closing_notice(
    world: World,
    notice_date: str = "2026-08-01",
    final_performance_date: str = "2026-08-20",
    reason: str = "ECONOMIC",
) -> World:
    """The Lead Producer `u-lp-1` issues the notice that closes the run."""
    payload = F.closing_notice_payload(
        world.production_id, notice_date, final_performance_date, reason
    )
    created = get_success_data(
        world.client.create_closing_notice(payload, PRODUCER_HEADERS), 201
    )
    world.closing_notice_id = created["id"]
    return world


def settle_closing_notice(world: World, closing_costs_cents: int = 5_000_000):
    """The Comptroller `u-ct-1` settles a notice another operator issued."""
    return world.client.settle_closing_notice(
        world.closing_notice_id or "",
        F.settle_payload(closing_costs_cents),
        COMPTROLLER_HEADERS,
    )


# ─── Distributions ────────────────────────────────────────────────────────


def declare_distribution(
    world: World,
    total_amount_cents: int,
    distribution_type: str = "RECOUPMENT_RETURN",
    expected_production_version: Optional[int] = None,
):
    """Declare a distribution, quoting the production version as the OCC token."""
    version = (
        world.production_version()
        if expected_production_version is None
        else expected_production_version
    )
    payload = F.distribution_payload(
        world.production_id, total_amount_cents, version, distribution_type
    )
    return world.client.declare_investor_distribution(payload, COMPTROLLER_HEADERS)


def sole_account(world: World) -> Dict[str, Any]:
    """The one capital account of a single-investor production."""
    response = world.client.list_investor_accounts(
        COMPTROLLER_HEADERS, {"production_id": world.production_id}
    )
    data = get_success_data(response, 200)
    assert len(data) == 1, f"expected exactly one capital account, got {len(data)}"
    return data[0]


# ─── Subsidiary rights income ─────────────────────────────────────────────


def with_recorded_income(world: World, gross_income_cents: int = 10_000_000, **overrides: Any):
    """Record a licensing receipt against the production."""
    payload = F.income_payload(
        world.production_id, gross_income_cents=gross_income_cents, **overrides
    )
    return get_success_data(
        world.client.create_subsidiary_rights_income(payload, GM_HEADERS), 201
    )


# Re-exported so tests can name the two operators the duty rules separate.
SUBMITTER_USER_ID = GM_USER_ID
CERTIFIER_USER_ID = COMPTROLLER_USER_ID
