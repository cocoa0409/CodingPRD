"""Composite fixtures for the Surplus Lines Placement Tax API.

The harness restarts the API server before every individual test, so every
fixture here builds its preconditions from scratch through the public
endpoints. The fixtures are layered: each one composes the previous one, so a
test can enter the chain at whatever depth it needs -- configured states, an
approved carrier, a white-listed carrier, a draft placement, a completed
diligent search, an issued policy, a calculated policy, or an endorsed policy.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import ApiClient
from .constants import DEFAULT_CLOCK
from .factories import (
    affidavit_payload,
    ca_program_payload,
    carrier_eligibility_payload,
    carrier_payload,
    declination_payload,
    endorsement_payload,
    exposure,
    filing_batch_payload,
    nv_program_payload,
    placement_payload,
    policy_payload,
    tx_program_payload,
)
from .test_users import (
    COMPLIANCE_OFFICER_ANDERS,
    PLATFORM_ADMIN,
    STATE_REGULATOR_CA,
    STATE_REGULATOR_NV,
    STATE_REGULATOR_TX,
    TAX_FILER_NINA,
    TAX_FILER_OWEN,
    make_placement_broker_headers,
)

#: The three canonical declinations recorded against the base placement: all
#: in Texas, none using ``NOT_LICENSED_FOR_CLASS``, all inside the ninety-day
#: lookback from the default clock.
CANONICAL_DECLINATIONS = [
    {
        "admitted_carrier_name": "Republic Admitted Mutual",
        "state_code": "TX",
        "reason_code": "NO_APPETITE",
        "declined_on": "2026-07-10T00:00:00Z",
    },
    {
        "admitted_carrier_name": "Pecos Standard Insurance",
        "state_code": "TX",
        "reason_code": "CAPACITY",
        "declined_on": "2026-07-12T00:00:00Z",
    },
    {
        "admitted_carrier_name": "Trinity Mutual Casualty",
        "state_code": "TX",
        "reason_code": "UNDERWRITING",
        "declined_on": "2026-07-14T00:00:00Z",
    },
]


class World:
    """A mutable handle on the regulatory landscape under construction.

    Every method drives a real endpoint and asserts the documented success
    status, so a failure inside a fixture is reported where it happens rather
    than surfacing as a confusing assertion later in the test.
    """

    def __init__(self, api: ApiClient):
        self.api = api
        self.programs: Dict[str, Dict[str, Any]] = {}
        self.broker: Optional[Dict[str, Any]] = None
        self.broker_headers: Optional[Dict[str, str]] = None
        self.carrier: Optional[Dict[str, Any]] = None
        self.review: Optional[Dict[str, Any]] = None
        self.eligibilities: Dict[str, Dict[str, Any]] = {}
        self.placement: Optional[Dict[str, Any]] = None
        self.declinations: List[Dict[str, Any]] = []
        self.policy: Optional[Dict[str, Any]] = None
        self.endorsement: Optional[Dict[str, Any]] = None
        self.affidavit: Optional[Dict[str, Any]] = None
        self.clock: str = DEFAULT_CLOCK

    # -- the logical clock -------------------------------------------------
    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        data = validate_success(self.api.set_clock(current_utc, PLATFORM_ADMIN), 200)
        self.clock = current_utc
        return data

    # -- brokerages --------------------------------------------------------
    def create_broker(self, **overrides) -> Dict[str, Any]:
        from .factories import broker_payload

        broker = validate_success(
            self.api.create_broker(broker_payload(**overrides), PLATFORM_ADMIN), 201
        )
        self.broker = broker
        self.broker_headers = make_placement_broker_headers(broker["id"])
        return broker

    def add_license(self, broker_id: Optional[str] = None, **overrides) -> Dict[str, Any]:
        from .factories import broker_license_payload

        target = broker_id or self.broker["id"]
        return validate_success(
            self.api.create_broker_license(
                target, broker_license_payload(**overrides), PLATFORM_ADMIN
            ),
            201,
        )

    def suspend_broker(self, broker_id: Optional[str] = None) -> Dict[str, Any]:
        target = broker_id or self.broker["id"]
        return validate_success(self.api.suspend_broker(target, PLATFORM_ADMIN), 200)

    # -- state programs ----------------------------------------------------
    def create_program(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        program = validate_success(self.api.create_state_program(payload, PLATFORM_ADMIN), 201)
        self.programs[program["state_code"]] = program
        return program

    def program(self, state_code: str) -> Dict[str, Any]:
        return self.programs[state_code]

    def program_id(self, state_code: str) -> str:
        return self.programs[state_code]["id"]

    def patch_program(self, state_code: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        program = validate_success(
            self.api.patch_state_program(self.program_id(state_code), payload, PLATFORM_ADMIN),
            200,
        )
        self.programs[state_code] = program
        return program

    # -- carriers ----------------------------------------------------------
    def create_carrier(self, **overrides) -> Dict[str, Any]:
        carrier = validate_success(
            self.api.create_carrier(carrier_payload(**overrides), PLATFORM_ADMIN), 201
        )
        self.carrier = carrier
        return carrier

    def get_carrier(self, carrier_id: Optional[str] = None) -> Dict[str, Any]:
        target = carrier_id or self.carrier["id"]
        carrier = validate_success(self.api.get_carrier(target, PLATFORM_ADMIN), 200)
        if self.carrier is not None and carrier["id"] == self.carrier["id"]:
            self.carrier = carrier
        return carrier

    def open_review(
        self, carrier: Optional[Dict[str, Any]] = None, reviewer=COMPLIANCE_OFFICER_ANDERS
    ) -> Dict[str, Any]:
        target = (carrier or self.carrier)["id"]
        review = validate_success(self.api.create_security_review(target, reviewer), 201)
        self.review = review
        return review

    def start_review(
        self, review: Optional[Dict[str, Any]] = None, reviewer=COMPLIANCE_OFFICER_ANDERS
    ) -> Dict[str, Any]:
        target = (review or self.review)["id"]
        started = validate_success(self.api.start_security_review(target, reviewer), 200)
        self.review = started
        return started

    def decide_review(
        self,
        decision: str,
        review: Optional[Dict[str, Any]] = None,
        carrier: Optional[Dict[str, Any]] = None,
        reviewer=COMPLIANCE_OFFICER_ANDERS,
        conditions_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        review_id = (review or self.review)["id"]
        carrier_version = (carrier or self.carrier)["version"]
        payload: Dict[str, Any] = {
            "decision": decision,
            "expected_carrier_version": carrier_version,
        }
        if conditions_note is not None:
            payload["conditions_note"] = conditions_note
        decided = validate_success(
            self.api.decide_security_review(review_id, payload, reviewer), 200
        )
        self.review = decided
        # The decision mirrors onto the carrier and increments its version.
        self.get_carrier((carrier or self.carrier)["id"])
        return decided

    def review_carrier(
        self,
        decision: str = "APPROVE",
        carrier: Optional[Dict[str, Any]] = None,
        reviewer=COMPLIANCE_OFFICER_ANDERS,
        conditions_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open, start and decide a review of the carrier in one step."""
        target = carrier or self.carrier
        review = self.open_review(target, reviewer)
        self.start_review(review, reviewer)
        return self.decide_review(
            decision, review=review, carrier=target, reviewer=reviewer,
            conditions_note=conditions_note,
        )

    # -- the white list ----------------------------------------------------
    def white_list(
        self,
        state_code: str,
        carrier: Optional[Dict[str, Any]] = None,
        regulator=STATE_REGULATOR_TX,
        **overrides,
    ) -> Dict[str, Any]:
        target = (carrier or self.carrier)["id"]
        entry = validate_success(
            self.api.create_carrier_eligibility(
                carrier_eligibility_payload(target, self.program_id(state_code), **overrides),
                regulator,
            ),
            201,
        )
        self.eligibilities[state_code] = entry
        return entry

    # -- placements --------------------------------------------------------
    def create_placement(self, **overrides) -> Dict[str, Any]:
        placement = validate_success(
            self.api.create_placement(placement_payload(**overrides), self.broker_headers), 201
        )
        self.placement = placement
        return placement

    def get_placement(self, placement_id: Optional[str] = None) -> Dict[str, Any]:
        target = placement_id or self.placement["id"]
        placement = validate_success(self.api.get_placement(target, PLATFORM_ADMIN), 200)
        if self.placement is not None and placement["id"] == self.placement["id"]:
            self.placement = placement
        return placement

    def begin_search(self, placement: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = (placement or self.placement)["id"]
        updated = validate_success(self.api.begin_search(target, self.broker_headers), 200)
        self.placement = updated
        return updated

    def record_declination(
        self, placement: Optional[Dict[str, Any]] = None, **overrides
    ) -> Dict[str, Any]:
        target = (placement or self.placement)["id"]
        declination = validate_success(
            self.api.create_declination(
                target, declination_payload(**overrides), self.broker_headers
            ),
            201,
        )
        self.declinations.append(declination)
        return declination

    def record_canonical_declinations(
        self, placement: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        return [self.record_declination(placement, **spec) for spec in CANONICAL_DECLINATIONS]

    def complete_search(self, placement: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = (placement or self.placement)["id"]
        updated = validate_success(self.api.complete_search(target, self.broker_headers), 200)
        self.placement = updated
        return updated

    def request_changes(
        self,
        placement: Optional[Dict[str, Any]] = None,
        officer=COMPLIANCE_OFFICER_ANDERS,
    ) -> Dict[str, Any]:
        target = (placement or self.placement)["id"]
        updated = validate_success(self.api.request_changes(target, officer), 200)
        self.placement = updated
        return updated

    def invalidate_declination(
        self, declination: Dict[str, Any], officer=COMPLIANCE_OFFICER_ANDERS
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.invalidate_declination(declination["id"], officer), 200
        )

    def searched_placement(self, **overrides) -> Dict[str, Any]:
        """Create a placement, open the search, record three declinations and
        complete the search."""
        placement = self.create_placement(**overrides)
        self.begin_search(placement)
        self.record_canonical_declinations(placement)
        return self.complete_search(placement)

    # -- policies ----------------------------------------------------------
    def issue_policy(
        self,
        placement: Optional[Dict[str, Any]] = None,
        carrier: Optional[Dict[str, Any]] = None,
        **overrides,
    ) -> Dict[str, Any]:
        target_placement = placement or self.placement
        target_carrier = carrier or self.carrier
        payload = policy_payload(
            target_placement["id"],
            target_carrier["id"],
            target_placement["version"],
            **overrides,
        )
        policy = validate_success(self.api.create_policy(payload, self.broker_headers), 201)
        self.policy = policy
        self.get_placement(target_placement["id"])
        return policy

    def get_policy(self, policy_id: Optional[str] = None) -> Dict[str, Any]:
        target = policy_id or self.policy["id"]
        policy = validate_success(self.api.get_policy(target, PLATFORM_ADMIN), 200)
        if self.policy is not None and policy["id"] == self.policy["id"]:
            self.policy = policy
        return policy

    def affix_notices(
        self, notice_codes: List[str], policy: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        target = (policy or self.policy)["id"]
        updated = validate_success(
            self.api.affix_notices(target, {"notice_codes": notice_codes}, self.broker_headers),
            200,
        )
        self.policy = updated
        return updated

    def calculate_tax(self, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = (policy or self.policy)["id"]
        updated = validate_success(self.api.calculate_tax(target, TAX_FILER_NINA), 200)
        self.policy = updated
        return updated

    def submit_stamping(self, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = (policy or self.policy)["id"]
        updated = validate_success(self.api.submit_stamping(target, TAX_FILER_NINA), 200)
        self.policy = updated
        return updated

    def stamping_decision(
        self,
        decision: str,
        rejection_reason: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
        regulator=STATE_REGULATOR_TX,
    ) -> Dict[str, Any]:
        target = (policy or self.policy)["id"]
        payload: Dict[str, Any] = {"decision": decision}
        if rejection_reason is not None:
            payload["rejection_reason"] = rejection_reason
        updated = validate_success(
            self.api.stamping_decision(target, payload, regulator), 200
        )
        self.policy = updated
        return updated

    def allocations(
        self, policy: Optional[Dict[str, Any]] = None, params: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        target = (policy or self.policy)["id"]
        return validate_success(self.api.list_allocations(target, PLATFORM_ADMIN, params), 200)

    def filing_lines(self, **params) -> List[Dict[str, Any]]:
        params.setdefault("limit", 100)
        return validate_success(self.api.list_tax_filing_lines(PLATFORM_ADMIN, params), 200)

    # -- endorsements and cancellations ------------------------------------
    def draft_endorsement(
        self, policy: Optional[Dict[str, Any]] = None, **overrides
    ) -> Dict[str, Any]:
        target = policy or self.policy
        endorsement = validate_success(
            self.api.create_endorsement(
                target["id"], endorsement_payload(target["version"], **overrides),
                self.broker_headers,
            ),
            201,
        )
        self.endorsement = endorsement
        self.get_policy(target["id"])
        return endorsement

    def issue_endorsement(self, endorsement: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = (endorsement or self.endorsement)["id"]
        issued = validate_success(self.api.issue_endorsement(target, self.broker_headers), 200)
        self.endorsement = issued
        if self.policy is not None:
            self.get_policy()
        return issued

    def void_endorsement(self, endorsement: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = (endorsement or self.endorsement)["id"]
        voided = validate_success(self.api.void_endorsement(target, self.broker_headers), 200)
        self.endorsement = voided
        if self.policy is not None:
            self.get_policy()
        return voided

    def request_cancellation(
        self, policy: Optional[Dict[str, Any]] = None, **overrides
    ) -> Dict[str, Any]:
        from .factories import cancellation_payload

        target = (policy or self.policy)["id"]
        return validate_success(
            self.api.create_cancellation(
                target, cancellation_payload(**overrides), self.broker_headers
            ),
            201,
        )

    def process_cancellation(self, cancellation: Dict[str, Any]) -> Dict[str, Any]:
        processed = validate_success(
            self.api.process_cancellation(cancellation["id"], self.broker_headers), 200
        )
        if self.policy is not None:
            self.get_policy()
        return processed

    # -- filing batches ----------------------------------------------------
    def open_batch(
        self, state_code: str, period_key: str = "2026-08", preparer=TAX_FILER_NINA
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.create_filing_batch(
                filing_batch_payload(self.program_id(state_code), self.broker["id"], period_key),
                preparer,
            ),
            201,
        )

    def prepare_batch(self, batch: Dict[str, Any], preparer=TAX_FILER_NINA) -> Dict[str, Any]:
        return validate_success(self.api.prepare_filing_batch(batch["id"], preparer), 200)

    def submit_batch(self, batch: Dict[str, Any], filer=TAX_FILER_NINA) -> Dict[str, Any]:
        return validate_success(self.api.submit_filing_batch(batch["id"], filer), 200)

    def remit_batch(
        self,
        batch: Dict[str, Any],
        remitted_amount_cents: int,
        filer=TAX_FILER_OWEN,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.remit_filing_batch(
                batch["id"], {"remitted_amount_cents": remitted_amount_cents}, filer
            ),
            200,
        )

    # -- affidavits --------------------------------------------------------
    def draft_affidavit(
        self, policy: Optional[Dict[str, Any]] = None, **overrides
    ) -> Dict[str, Any]:
        target = (policy or self.policy)["id"]
        affidavit = validate_success(
            self.api.create_affidavit(
                target, affidavit_payload(**overrides), self.broker_headers
            ),
            201,
        )
        self.affidavit = affidavit
        return affidavit

    def sign_affidavit(
        self, affidavit: Optional[Dict[str, Any]] = None, signer=None
    ) -> Dict[str, Any]:
        target = (affidavit or self.affidavit)["id"]
        headers = signer if signer is not None else self.broker_headers
        signed = validate_success(self.api.sign_affidavit(target, headers), 200)
        self.affidavit = signed
        if self.policy is not None:
            self.get_policy()
        return signed

    # -- lenient read, for probing state without asserting shape ----------
    def peek(self, response) -> Any:
        return get_success_data(response)


# ---------------------------------------------------------------------------
# Layered pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def world(api: ApiClient) -> World:
    """An empty world with the logical clock parked at its documented default."""
    w = World(api)
    w.set_clock(DEFAULT_CLOCK)
    return w


@pytest.fixture
def configured_world(world: World) -> World:
    """A registered brokerage with an active Texas surplus lines licence, plus
    the Texas, Nevada and California state programs."""
    world.create_broker()
    world.add_license(state_code="TX", license_number="SL-TX-1001")
    world.create_program(tx_program_payload())
    world.create_program(nv_program_payload())
    world.create_program(ca_program_payload())
    return world


@pytest.fixture
def approved_carrier_world(configured_world: World) -> World:
    """The configured world plus an Atlas Specialty carrier whose market
    security review has been approved."""
    configured_world.create_carrier(
        naic_number="12345", legal_name="Atlas Specialty Insurance Company"
    )
    configured_world.review_carrier("APPROVE")
    return configured_world


@pytest.fixture
def white_listed_world(approved_carrier_world: World) -> World:
    """The approved carrier, added to the Texas white list from 2026-01-01."""
    approved_carrier_world.white_list("TX")
    return approved_carrier_world


@pytest.fixture
def placement_world(white_listed_world: World) -> World:
    """A draft placement on a Texas-homed risk with equal exposure in Texas,
    Nevada and California."""
    white_listed_world.create_placement()
    return white_listed_world


@pytest.fixture
def searched_world(placement_world: World) -> World:
    """The placement carried through a completed diligent search with three
    valid Texas declinations."""
    placement_world.begin_search()
    placement_world.record_canonical_declinations()
    placement_world.complete_search()
    return placement_world


@pytest.fixture
def policy_world(searched_world: World) -> World:
    """A policy issued against the completed placement."""
    searched_world.issue_policy()
    return searched_world


@pytest.fixture
def calculated_world(policy_world: World) -> World:
    """The issued policy with its premium tax and stamping fee calculated."""
    policy_world.calculate_tax()
    return policy_world


@pytest.fixture
def endorsed_world(calculated_world: World) -> World:
    """The calculated policy with a +200,000 cent premium increase issued."""
    calculated_world.draft_endorsement()
    calculated_world.issue_endorsement()
    return calculated_world


@pytest.fixture
def affixed_world(policy_world: World) -> World:
    """The issued policy with both Texas notice codes affixed."""
    policy_world.affix_notices(["TX-SL-1", "TX-SL-2"])
    return policy_world


@pytest.fixture
def stamping_submitted_world(affixed_world: World) -> World:
    """Notices affixed, tax calculated and the policy sitting at the stamping
    office awaiting a decision."""
    affixed_world.calculate_tax()
    affixed_world.submit_stamping()
    return affixed_world


@pytest.fixture
def affidavit_world(affixed_world: World) -> World:
    """A draft diligent-search affidavit attesting the placement's pinned count
    of three declinations, on a policy whose notices are already affixed."""
    affixed_world.draft_affidavit(declination_count_attested=3)
    return affixed_world


@pytest.fixture
def ca_home_world(white_listed_world: World) -> World:
    """A second risk homed in California -- the `HOME_STATE_SINGLE` state --
    carried through a completed diligent search with three Californian
    declinations."""
    world = white_listed_world
    world.add_license(state_code="CA", license_number="SL-CA-2002")
    world.white_list("CA", regulator=STATE_REGULATOR_CA)
    placement = world.create_placement(
        insured_name="Golden Bear Fabricators LLC",
        principal_place_of_business_state="CA",
        state_exposures=[
            exposure("TX", 300_000_000),
            exposure("NV", 300_000_000),
            exposure("CA", 300_000_000),
        ],
    )
    world.begin_search(placement)
    for spec in (
        ("Golden State Admitted Mutual", "NO_APPETITE", "2026-07-10T00:00:00Z"),
        ("Sierra Standard Insurance", "CAPACITY", "2026-07-12T00:00:00Z"),
        ("Pacific Mutual Casualty", "UNDERWRITING", "2026-07-14T00:00:00Z"),
    ):
        world.record_declination(
            placement,
            admitted_carrier_name=spec[0],
            state_code="CA",
            reason_code=spec[1],
            declined_on=spec[2],
        )
    world.complete_search(placement)
    return world


@pytest.fixture
def nv_home_world(approved_carrier_world: World) -> World:
    """A risk homed in Nevada -- a state with no stamping office -- carried
    through a completed diligent search with two Nevadan declinations."""
    world = approved_carrier_world
    world.add_license(state_code="NV", license_number="SL-NV-4004")
    world.white_list("NV", regulator=STATE_REGULATOR_NV)
    placement = world.create_placement(
        insured_name="Silver State Fabricators LLC",
        principal_place_of_business_state="NV",
        state_exposures=[exposure("NV", 300_000_000)],
    )
    world.begin_search(placement)
    for spec in (
        ("Comstock Admitted Mutual", "NO_APPETITE", "2026-07-10T00:00:00Z"),
        ("Washoe Standard Insurance", "CAPACITY", "2026-07-12T00:00:00Z"),
    ):
        world.record_declination(
            placement,
            admitted_carrier_name=spec[0],
            state_code="NV",
            reason_code=spec[1],
            declined_on=spec[2],
        )
    world.complete_search(placement)
    return world
