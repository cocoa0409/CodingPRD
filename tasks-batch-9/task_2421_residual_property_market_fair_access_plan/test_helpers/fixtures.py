"""State builders and pytest fixtures.

The API server is restarted before each test, so every test begins against an
empty store.  Everything a test needs must therefore be built here, through the
plan's own endpoints, in the order the plan's own lifecycles require:

1. the logical clock is pinned,
2. the registries are populated (member insurers, a catastrophe zone, an
   appointed producer) and a rate filing is approved for the zone,
3. an application is walked forward one lifecycle step at a time,
4. accumulations are driven to a chosen threshold (zone concentration, take-out
   credits), and
5. terminal states are reached (a settled or cancelled assessment, a cancelled
   or taken-out policy).

Builders are ordinary functions so a test can stop at whatever step it needs;
the pytest fixtures at the bottom bundle the most frequently reused stops.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import FairPlanApiClient
from .assertions import shift_date
from .constants import (
    BASIS_MARKET_SHARE,
    CLOCK_BASE,
    CLOCK_BASE_DATE,
    DECISION_APPROVE,
    ELIGIBILITY_DECISION_ADVANCE,
    INSPECTION_RESULT_PASS,
    PACKAGE_BASIC_FIRE_EO,
)
from .test_users import (
    admin_headers,
    binder_headers,
    inspector_headers,
    make_member_insurer_headers,
    make_policyholder_headers,
    make_producer_headers,
    rate_analyst_headers,
    regulator_headers,
    reviewer_headers,
)
from .types import Record

# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------


@dataclass
class Foundations:
    """The registry state every downstream lifecycle depends on."""

    client: FairPlanApiClient
    members: List[Record] = field(default_factory=list)
    zone: Optional[Record] = None
    producer: Optional[Record] = None
    filing: Optional[Record] = None

    @property
    def member_ids(self) -> List[str]:
        return [member["id"] for member in self.members]

    @property
    def zone_id(self) -> str:
        assert self.zone is not None
        return self.zone["id"]

    @property
    def producer_id(self) -> str:
        assert self.producer is not None
        return self.producer["id"]

    @property
    def filing_id(self) -> str:
        assert self.filing is not None
        return self.filing["id"]

    @property
    def producer_headers(self) -> Dict[str, str]:
        return make_producer_headers(self.producer_id)

    def member_headers(self, index: int = 0) -> Dict[str, str]:
        return make_member_insurer_headers(self.members[index]["id"])

    def zone_version(self) -> int:
        return read_zone(self.client, self.zone_id)["version"]


@dataclass
class ApplicationChain:
    """One applicant / property / application triple and its dependants."""

    client: FairPlanApiClient
    foundations: Foundations
    applicant: Record
    property: Record
    application: Record
    declinations: List[Record] = field(default_factory=list)
    inspection: Optional[Record] = None
    requirements: List[Record] = field(default_factory=list)
    policy: Optional[Record] = None

    @property
    def applicant_id(self) -> str:
        return self.applicant["id"]

    @property
    def property_id(self) -> str:
        return self.property["id"]

    @property
    def application_id(self) -> str:
        return self.application["id"]

    @property
    def inspection_id(self) -> str:
        assert self.inspection is not None
        return self.inspection["id"]

    @property
    def policy_id(self) -> str:
        assert self.policy is not None
        return self.policy["id"]

    @property
    def producer_headers(self) -> Dict[str, str]:
        return self.foundations.producer_headers

    @property
    def policyholder_headers(self) -> Dict[str, str]:
        return make_policyholder_headers(self.applicant_id)

    def refresh_application(self) -> Record:
        self.application = read_application(self.client, self.application_id)
        return self.application

    def refresh_policy(self) -> Record:
        assert self.policy is not None
        self.policy = read_policy(self.client, self.policy_id)
        return self.policy


# ---------------------------------------------------------------------------
# Tier 1 — clock and read-back helpers
# ---------------------------------------------------------------------------


def pin_clock(client: FairPlanApiClient, instant: str = CLOCK_BASE) -> Record:
    """Move the logical clock to a chosen instant."""
    return get_success_data(client.set_clock(instant, admin_headers()))


def read_zone(client: FairPlanApiClient, zone_id: str) -> Record:
    return get_success_data(client.get_cat_zone(zone_id, admin_headers()))


def read_member(client: FairPlanApiClient, member_id: str) -> Record:
    return get_success_data(client.get_member_insurer(member_id, admin_headers()))


def read_producer(client: FairPlanApiClient, producer_id: str) -> Record:
    return get_success_data(client.get_producer(producer_id, admin_headers()))


def read_application(client: FairPlanApiClient, application_id: str) -> Record:
    return get_success_data(client.get_application(application_id, admin_headers()))


def read_inspection(client: FairPlanApiClient, inspection_id: str) -> Record:
    return get_success_data(client.get_inspection(inspection_id, admin_headers()))


def read_policy(client: FairPlanApiClient, policy_id: str) -> Record:
    return get_success_data(client.get_policy(policy_id, admin_headers()))


def read_filing(client: FairPlanApiClient, filing_id: str) -> Record:
    return get_success_data(client.get_rate_filing(filing_id, admin_headers()))


def read_offer(client: FairPlanApiClient, offer_id: str) -> Record:
    return get_success_data(client.get_takeout_offer(offer_id, admin_headers()))


def read_event(client: FairPlanApiClient, event_id: str) -> Record:
    return get_success_data(client.get_assessment_event(event_id, admin_headers()))


def read_allocations(client: FairPlanApiClient, event_id: str) -> List[Record]:
    data, _meta = validate_paginated(
        client.list_assessment_event_allocations(
            event_id, admin_headers(), {"limit": 100}
        )
    )
    return data


def read_requirements(client: FairPlanApiClient, inspection_id: str) -> List[Record]:
    data, _meta = validate_paginated(
        client.list_inspection_requirements(
            inspection_id, admin_headers(), {"limit": 100}
        )
    )
    return data


# ---------------------------------------------------------------------------
# Tier 2 — registries and an approved rate
# ---------------------------------------------------------------------------


#: The three carriers used throughout: two at a 30.00 market share and a 10.00
#: premium share, and a third at 40.00 / 80.00 so that the two allocation bases
#: rank the members differently.
DEFAULT_MEMBER_SPECS = (
    {"name": "Carrier One", "naic_code": "10001", "market_share_pct": 30.0, "written_premium_share_pct": 10.0},
    {"name": "Carrier Two", "naic_code": "10002", "market_share_pct": 30.0, "written_premium_share_pct": 10.0},
    {"name": "Carrier Three", "naic_code": "10003", "market_share_pct": 40.0, "written_premium_share_pct": 80.0},
)


def create_member_insurer(client: FairPlanApiClient, **overrides: Any) -> Record:
    payload = f.member_insurer_payload(**overrides)
    return get_success_data(client.create_member_insurer(payload, admin_headers()))


def create_member_insurers(
    client: FairPlanApiClient, specs: Any = DEFAULT_MEMBER_SPECS
) -> List[Record]:
    return [create_member_insurer(client, **spec) for spec in specs]


def create_zone(client: FairPlanApiClient, **overrides: Any) -> Record:
    payload = f.cat_zone_payload(**overrides)
    return get_success_data(client.create_cat_zone(payload, admin_headers()))


def create_appointed_producer(
    client: FairPlanApiClient,
    agreement_effective_date: str = "2026-08-01",
    **overrides: Any,
) -> Record:
    producer = get_success_data(
        client.create_producer(f.producer_payload(**overrides), admin_headers())
    )
    return get_success_data(
        client.execute_producer_agreement(
            producer["id"],
            f.agreement_execution_payload(agreement_effective_date),
            admin_headers(),
        )
    )


def file_rate(client: FairPlanApiClient, zone_id: str, **overrides: Any) -> Record:
    """File a rate for the zone, reading the zone version immediately first."""
    zone_version = read_zone(client, zone_id)["version"]
    payload = f.rate_filing_payload(
        cat_zone_id=zone_id, expected_zone_version=zone_version, **overrides
    )
    return get_success_data(client.create_rate_filing(payload, rate_analyst_headers()))


def review_filing(
    client: FairPlanApiClient,
    filing_id: str,
    decision: str = DECISION_APPROVE,
    **overrides: Any,
) -> Record:
    payload = f.filing_review_payload(decision=decision, **overrides)
    return get_success_data(
        client.review_rate_filing(filing_id, payload, regulator_headers())
    )


def create_approved_filing(
    client: FairPlanApiClient, zone_id: str, **overrides: Any
) -> Record:
    filing = file_rate(client, zone_id, **overrides)
    return review_filing(client, filing["id"], DECISION_APPROVE)


def build_foundations(
    client: FairPlanApiClient,
    clock: Optional[str] = CLOCK_BASE,
    member_specs: Any = DEFAULT_MEMBER_SPECS,
    zone_overrides: Optional[Dict[str, Any]] = None,
    producer_overrides: Optional[Dict[str, Any]] = None,
    filing_overrides: Optional[Dict[str, Any]] = None,
) -> Foundations:
    """Clock, three carriers, one zone, one appointed producer, one approved rate."""
    if clock is not None:
        pin_clock(client, clock)
    members = create_member_insurers(client, member_specs)
    zone = create_zone(client, **(zone_overrides or {}))
    producer = create_appointed_producer(client, **(producer_overrides or {}))
    filing = create_approved_filing(client, zone["id"], **(filing_overrides or {}))
    return Foundations(
        client=client, members=members, zone=zone, producer=producer, filing=filing
    )


# ---------------------------------------------------------------------------
# Tier 3 — the application lifecycle, one step per function
# ---------------------------------------------------------------------------


def create_applicant(
    client: FairPlanApiClient, foundations: Foundations, **overrides: Any
) -> Record:
    return get_success_data(
        client.create_applicant(
            f.applicant_payload(**overrides), foundations.producer_headers
        )
    )


def create_property(
    client: FairPlanApiClient,
    foundations: Foundations,
    zone_id: Optional[str] = None,
    **overrides: Any,
) -> Record:
    payload = f.property_payload(cat_zone_id=zone_id or foundations.zone_id, **overrides)
    return get_success_data(
        client.create_property(payload, foundations.producer_headers)
    )


def create_draft_application(
    client: FairPlanApiClient,
    foundations: Foundations,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    zone_id: Optional[str] = None,
) -> ApplicationChain:
    applicant = create_applicant(client, foundations, **(applicant_overrides or {}))
    prop = create_property(
        client, foundations, zone_id=zone_id, **(property_overrides or {})
    )
    application = get_success_data(
        client.create_application(
            f.application_payload(
                property_id=prop["id"],
                applicant_id=applicant["id"],
                **(application_overrides or {}),
            ),
            foundations.producer_headers,
        )
    )
    return ApplicationChain(
        client=client,
        foundations=foundations,
        applicant=applicant,
        property=prop,
        application=application,
    )


def add_declination(
    chain: ApplicationChain, member_insurer_id: str, **overrides: Any
) -> Record:
    payload = f.declination_payload(member_insurer_id=member_insurer_id, **overrides)
    record = get_success_data(
        chain.client.create_declination(
            chain.application_id, payload, chain.producer_headers
        )
    )
    chain.declinations.append(record)
    return record


def add_three_declinations(
    chain: ApplicationChain, declined_on: str = "2026-07-03"
) -> List[Record]:
    """One declination per distinct carrier, which is what sufficiency counts."""
    payloads = f.three_declination_payloads(
        chain.foundations.member_ids, declined_on=declined_on
    )
    records = [
        get_success_data(
            chain.client.create_declination(
                chain.application_id, payload, chain.producer_headers
            )
        )
        for payload in payloads
    ]
    chain.declinations.extend(records)
    return records


def submit(chain: ApplicationChain) -> Record:
    chain.application = get_success_data(
        chain.client.submit_application(
            chain.application_id, {}, chain.producer_headers
        )
    )
    return chain.application


def review_eligibility(
    chain: ApplicationChain,
    decision: str = ELIGIBILITY_DECISION_ADVANCE,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Record:
    chain.application = get_success_data(
        chain.client.review_application_eligibility(
            chain.application_id,
            f.eligibility_review_payload(decision=decision, **overrides),
            headers or reviewer_headers(),
        )
    )
    return chain.application


def order_inspection(
    chain: ApplicationChain, headers: Optional[Dict[str, str]] = None
) -> Record:
    chain.inspection = get_success_data(
        chain.client.order_inspection(
            chain.application_id, {}, headers or reviewer_headers()
        )
    )
    return chain.inspection


def complete_inspection(
    chain: ApplicationChain,
    observed_condition_score: int = 72,
    result: str = INSPECTION_RESULT_PASS,
    requirements: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    inspection_id: Optional[str] = None,
) -> Record:
    payload = f.inspection_completion_payload(
        observed_condition_score=observed_condition_score,
        result=result,
        requirements=requirements,
    )
    chain.inspection = get_success_data(
        chain.client.complete_inspection(
            inspection_id or chain.inspection_id,
            payload,
            headers or inspector_headers(),
        )
    )
    if requirements:
        chain.requirements = read_requirements(chain.client, chain.inspection["id"])
    return chain.inspection


def build_submitted_application(
    client: FairPlanApiClient,
    foundations: Foundations,
    declined_on: str = "2026-07-03",
    **kwargs: Any,
) -> ApplicationChain:
    """Draft, three declinations, submission — the application is SUBMITTED."""
    chain = create_draft_application(client, foundations, **kwargs)
    add_three_declinations(chain, declined_on=declined_on)
    submit(chain)
    return chain


def build_inspection_pending_application(
    client: FairPlanApiClient, foundations: Foundations, **kwargs: Any
) -> ApplicationChain:
    """Submitted, advanced by a reviewer, inspection ordered."""
    chain = build_submitted_application(client, foundations, **kwargs)
    review_eligibility(chain)
    order_inspection(chain)
    return chain


def build_bindable_application(
    client: FairPlanApiClient,
    foundations: Foundations,
    observed_condition_score: int = 72,
    **kwargs: Any,
) -> ApplicationChain:
    """Carried all the way to APPROVED_TO_BIND by a passing inspection."""
    chain = build_inspection_pending_application(client, foundations, **kwargs)
    complete_inspection(
        chain,
        observed_condition_score=observed_condition_score,
        result=INSPECTION_RESULT_PASS,
    )
    chain.refresh_application()
    return chain


def bind(
    chain: ApplicationChain,
    effective_date: str = CLOCK_BASE_DATE,
    headers: Optional[Dict[str, str]] = None,
) -> Record:
    chain.policy = get_success_data(
        chain.client.bind_policy(
            f.bind_payload(chain.application_id, effective_date),
            headers or binder_headers(),
        )
    )
    return chain.policy


def build_bound_policy(
    client: FairPlanApiClient,
    foundations: Foundations,
    effective_date: str = CLOCK_BASE_DATE,
    observed_condition_score: int = 72,
    **kwargs: Any,
) -> ApplicationChain:
    """A freshly bound policy: coverage BOUND, depopulation NOT_OFFERED."""
    chain = build_bindable_application(
        client, foundations, observed_condition_score=observed_condition_score, **kwargs
    )
    bind(chain, effective_date=effective_date)
    return chain


def run_sweep(client: FairPlanApiClient) -> Record:
    """Run the nightly batch at the clock's current instant."""
    return get_success_data(client.run_expiration_sweep({}, admin_headers()))


def build_in_force_policy(
    client: FairPlanApiClient,
    foundations: Foundations,
    effective_date: str = CLOCK_BASE_DATE,
    **kwargs: Any,
) -> ApplicationChain:
    """A bound policy carried to IN_FORCE by the nightly batch."""
    chain = build_bound_policy(
        client, foundations, effective_date=effective_date, **kwargs
    )
    run_sweep(client)
    chain.refresh_policy()
    return chain


# ---------------------------------------------------------------------------
# Tier 4 — driving accumulations to a chosen threshold
# ---------------------------------------------------------------------------


def bind_exposure(
    client: FairPlanApiClient,
    foundations: Foundations,
    dwelling_limit_cents: int,
    address_line: str,
    zip_code: str = "33101",
    naic_suffix: str = "",
    construction_type: Optional[str] = None,
    condition_score: int = 88,
    observed_condition_score: int = 72,
    replacement_cost_cents: Optional[int] = None,
    effective_date: str = CLOCK_BASE_DATE,
    peril_package: str = PACKAGE_BASIC_FIRE_EO,
) -> ApplicationChain:
    """Bind one extra policy purely to move the zone's accumulated exposure.

    Every bound policy adds its exposure to the zone, so a test that needs the
    zone sitting at a particular concentration binds a filler of exactly the
    right dwelling limit.
    """
    property_overrides: Dict[str, Any] = {
        "address_line": address_line,
        "zip_code": zip_code,
        "condition_score": condition_score,
        "replacement_cost_cents": replacement_cost_cents
        if replacement_cost_cents is not None
        else max(dwelling_limit_cents, 100_000_000),
    }
    if construction_type is not None:
        property_overrides["construction_type"] = construction_type
    return build_bound_policy(
        client,
        foundations,
        effective_date=effective_date,
        observed_condition_score=observed_condition_score,
        applicant_overrides={
            "full_name": f"Filler {address_line}",
            "email": f"filler{naic_suffix or address_line.replace(' ', '')}@example.com",
        },
        property_overrides=property_overrides,
        application_overrides={
            "requested_dwelling_limit_cents": dwelling_limit_cents,
            "requested_peril_package": peril_package,
        },
    )


def create_offer(
    chain: ApplicationChain,
    member_index: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Record:
    """A member insurer extends a take-out offer on the in-force policy."""
    member_id = chain.foundations.members[member_index]["id"]
    payload = f.takeout_offer_payload(member_insurer_id=member_id, **overrides)
    return get_success_data(
        chain.client.create_takeout_offer(
            chain.policy_id,
            payload,
            headers or make_member_insurer_headers(member_id),
        )
    )


def build_outstanding_offer(
    client: FairPlanApiClient,
    foundations: Foundations,
    member_index: int = 0,
    offer_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Any:
    """An in-force policy with one OUTSTANDING take-out offer against it."""
    chain = build_in_force_policy(client, foundations, **kwargs)
    offer = create_offer(chain, member_index=member_index, **(offer_overrides or {}))
    return chain, offer


def elect_offer(
    chain: ApplicationChain, offer_id: str, election: str, **overrides: Any
) -> Record:
    return get_success_data(
        chain.client.elect_takeout_offer(
            offer_id,
            f.election_payload(election=election, **overrides),
            chain.policyholder_headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 — assessments and terminal states
# ---------------------------------------------------------------------------


def create_event(
    client: FairPlanApiClient,
    zone_id: str,
    trigger_loss_cents: int,
    reserve_balance_cents_at_trigger: int,
    allocation_basis: str = BASIS_MARKET_SHARE,
    **overrides: Any,
) -> Record:
    payload = f.assessment_event_payload(
        cat_zone_id=zone_id,
        trigger_loss_cents=trigger_loss_cents,
        reserve_balance_cents_at_trigger=reserve_balance_cents_at_trigger,
        allocation_basis=allocation_basis,
        **overrides,
    )
    return get_success_data(client.create_assessment_event(payload, admin_headers()))


def allocate_event(
    client: FairPlanApiClient, event: Record, expected_version: Optional[int] = None
) -> Record:
    version = event["version"] if expected_version is None else expected_version
    return get_success_data(
        client.run_allocation(
            event["id"], f.allocation_run_payload(version), admin_headers()
        )
    )


def build_allocated_event(
    client: FairPlanApiClient,
    zone_id: str,
    trigger_loss_cents: int,
    reserve_balance_cents_at_trigger: int,
    allocation_basis: str = BASIS_MARKET_SHARE,
) -> Record:
    event = create_event(
        client,
        zone_id,
        trigger_loss_cents,
        reserve_balance_cents_at_trigger,
        allocation_basis,
    )
    return allocate_event(client, event)


def build_invoiced_event(
    client: FairPlanApiClient,
    zone_id: str,
    trigger_loss_cents: int,
    reserve_balance_cents_at_trigger: int,
    allocation_basis: str = BASIS_MARKET_SHARE,
) -> Record:
    """An allocated event carried to INVOICED, so its allocations are payable."""
    event = build_allocated_event(
        client,
        zone_id,
        trigger_loss_cents,
        reserve_balance_cents_at_trigger,
        allocation_basis,
    )
    return get_success_data(client.invoice_assessment(event["id"], {}, admin_headers()))


def pay_allocation(
    client: FairPlanApiClient, allocation: Record, amount_cents: Optional[int] = None
) -> Record:
    """A member pays its own allocation, which only the owning member may do."""
    amount = allocation["net_due_cents"] if amount_cents is None else amount_cents
    return get_success_data(
        client.pay_allocation(
            allocation["id"],
            f.payment_payload(amount),
            make_member_insurer_headers(allocation["member_insurer_id"]),
        )
    )


def cancel_policy(
    chain: ApplicationChain,
    cancel_reason: str,
    cancel_date: str = CLOCK_BASE_DATE,
    headers: Optional[Dict[str, str]] = None,
) -> Record:
    chain.policy = get_success_data(
        chain.client.cancel_policy(
            chain.policy_id,
            f.cancellation_payload(cancel_reason, cancel_date),
            headers or binder_headers(),
        )
    )
    return chain.policy


def renew_policy(
    chain: ApplicationChain,
    effective_date: str = "2027-09-01",
    headers: Optional[Dict[str, str]] = None,
) -> Record:
    return get_success_data(
        chain.client.renew_policy(
            chain.policy_id,
            f.renewal_payload(effective_date),
            headers or binder_headers(),
        )
    )


def next_year(date_str: str) -> str:
    """The same calendar day one 365-day term later."""
    return shift_date(date_str, 365)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> FairPlanApiClient:
    """A client pointed at the freshly restarted API server."""
    return FairPlanApiClient()


@pytest.fixture
def admin(client: FairPlanApiClient) -> Dict[str, str]:
    return admin_headers()


@pytest.fixture
def clock_pinned(client: FairPlanApiClient) -> FairPlanApiClient:
    """The logical clock pinned to the shared base instant."""
    pin_clock(client, CLOCK_BASE)
    return client


@pytest.fixture
def members(clock_pinned: FairPlanApiClient) -> List[Record]:
    return create_member_insurers(clock_pinned)


@pytest.fixture
def foundations(client: FairPlanApiClient) -> Foundations:
    """Clock, three carriers, one HURRICANE zone, appointed producer, approved rate."""
    return build_foundations(client)


@pytest.fixture
def roomy_foundations(client: FairPlanApiClient) -> Foundations:
    """Foundations whose zone cap is large enough not to disturb pricing.

    A generous exposure cap keeps the concentration ratio below the surcharge
    threshold, so a test about some other rule is not perturbed by a
    catastrophe surcharge or by a posture change.
    """
    return build_foundations(
        client, zone_overrides={"exposure_cap_cents": 900_000_000}
    )


@pytest.fixture
def bindable_application(
    roomy_foundations: Foundations,
) -> ApplicationChain:
    return build_bindable_application(roomy_foundations.client, roomy_foundations)


@pytest.fixture
def bound_policy(roomy_foundations: Foundations) -> ApplicationChain:
    return build_bound_policy(roomy_foundations.client, roomy_foundations)


@pytest.fixture
def in_force_policy(roomy_foundations: Foundations) -> ApplicationChain:
    return build_in_force_policy(roomy_foundations.client, roomy_foundations)
