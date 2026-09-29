"""Precondition builders.

Every test starts against an empty database, so all preconditions are built by
calling the API. The :class:`World` object below owns the identities and the
identifiers that the built-up state produced, and exposes one method per
domain step (register, underwrite, file, depart, report, hold, claim, petition,
sweep). The module-level ``build_*`` functions compose those steps into the
recurring scenarios that the test suite reuses.

Builders use the lenient success reader: a builder's job is to reach a state,
not to assert the contract — the tests do the asserting.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import InBondApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    CBP_OFFICER_1,
    CBP_OFFICER_2,
    FPF_OFFICER,
    make_bonded_carrier_headers,
    make_surety_agent_headers,
)

JsonDict = Dict[str, Any]

# ---------------------------------------------------------------------------
# Derived values of the reference consignment (1,234.60 / 100.28 kg / 3 pkgs
# moving 4601 -> 3901 as an IT filed at the default clock).
# ---------------------------------------------------------------------------
#: 40.12 + 1.25 + 0.38, each component rounded before the sum.
M1_OBLIGATION = 41.75
#: 30 base days for an IT plus the 5-day interport surcharge (NE -> MW).
M1_TRANSIT_DAYS = 35
M1_DEADLINE = "2026-09-05T00:00:00Z"
M1_SEAL = "SEAL-100"

#: A second identical consignment, used whenever two movements are needed.
M2_SEAL = "SEAL-200"

#: The instant at which the reference movement is seven days overdue.
LATE_ARRIVAL_CLOCK = "2026-09-11T12:00:00Z"
#: Assessed damages for a seven-day late arrival, capped at the cargo value.
LATE_ARRIVAL_ASSESSED = 1234.60


@dataclass
class World:
    """The state built up for one test, plus the identities that built it."""

    client: InBondApiClient
    officer: Dict[str, str] = field(default_factory=lambda: dict(CBP_OFFICER_1))
    second_officer: Dict[str, str] = field(default_factory=lambda: dict(CBP_OFFICER_2))
    fpf_officer: Dict[str, str] = field(default_factory=lambda: dict(FPF_OFFICER))

    carrier_id: Optional[str] = None
    bond_id: Optional[str] = None
    ports: Dict[str, str] = field(default_factory=dict)
    movements: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Identities
    # ------------------------------------------------------------------
    @property
    def carrier(self) -> Dict[str, str]:
        """Headers for the carrier that owns the built movements."""
        assert self.carrier_id is not None, "no carrier has been registered yet"
        return make_bonded_carrier_headers(self.carrier_id)

    @property
    def surety(self) -> Dict[str, str]:
        """Headers for the surety agent of the built bond."""
        assert self.bond_id is not None, "no bond has been underwritten yet"
        return make_surety_agent_headers(self.bond_id)

    def carrier_headers(self, carrier_id: str) -> Dict[str, str]:
        return make_bonded_carrier_headers(carrier_id)

    def surety_headers(self, bond_id: str) -> Dict[str, str]:
        return make_surety_agent_headers(bond_id)

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def set_clock(self, instant: str) -> JsonDict:
        return get_success_data(self.client.set_clock(instant, self.officer))

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_port(self, alias: str, payload: JsonDict) -> str:
        port = get_success_data(self.client.create_port(payload, self.officer))
        self.ports[alias] = port["id"]
        return port["id"]

    def register_carrier(self, payload: Optional[JsonDict] = None) -> str:
        payload = payload if payload is not None else factories.carrier_payload()
        carrier = get_success_data(self.client.create_carrier(payload, self.officer))
        if self.carrier_id is None:
            self.carrier_id = carrier["id"]
        return carrier["id"]

    def underwrite_bond(self, payload: Optional[JsonDict] = None) -> str:
        if payload is None:
            assert self.carrier_id is not None, "register a carrier first"
            payload = factories.continuous_bond_payload(self.carrier_id)
        bond = get_success_data(self.client.create_bond(payload, self.officer))
        if self.bond_id is None:
            self.bond_id = bond["id"]
        return bond["id"]

    # ------------------------------------------------------------------
    # Movements
    # ------------------------------------------------------------------
    def file_movement(
        self,
        manifest_reference: str,
        origin: str = "ny",
        destination: str = "chicago",
        bond_id: Optional[str] = None,
        name_the_bond: bool = True,
        carrier_id: Optional[str] = None,
        **overrides: Any,
    ) -> str:
        carrier_id = carrier_id or self.carrier_id
        assert carrier_id is not None, "register a carrier first"
        payload = factories.movement_payload(
            carrier_id,
            self.ports[origin],
            self.ports[destination],
            manifest_reference,
            **overrides,
        )
        if name_the_bond and "bond_id" not in payload:
            resolved_bond = bond_id or self.bond_id
            if resolved_bond is not None:
                payload["bond_id"] = resolved_bond
        movement = get_success_data(
            self.client.file_movement(payload, self.carrier_headers(carrier_id))
        )
        self.movements[manifest_reference] = movement["id"]
        return movement["id"]

    def depart(self, movement_id: str, seal_number: str = M1_SEAL) -> JsonDict:
        return get_success_data(
            self.client.depart_movement(
                movement_id, factories.departure_payload(seal_number), self.carrier
            )
        )

    def cancel(self, movement_id: str, reason_code: str = "SHIPPER_WITHDREW") -> JsonDict:
        return get_success_data(
            self.client.cancel_movement(
                movement_id, factories.cancellation_payload(reason_code), self.carrier
            )
        )

    def release_cargo(
        self, movement_id: str, reason_code: str = "ENTRY_FILED"
    ) -> JsonDict:
        return get_success_data(
            self.client.release_cargo(
                movement_id, factories.cargo_release_payload(reason_code), self.officer
            )
        )

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def report_arrival(
        self,
        movement_id: str,
        port: str = "chicago",
        packages_reported: int = factories.PACKAGE_COUNT,
    ) -> JsonDict:
        return get_success_data(
            self.client.file_report(
                factories.arrival_report_payload(
                    movement_id, self.ports[port], packages_reported
                ),
                self.carrier,
            )
        )

    def report_export(
        self, movement_id: str, port: str = "chicago", **overrides: Any
    ) -> JsonDict:
        return get_success_data(
            self.client.file_report(
                factories.export_report_payload(
                    movement_id, self.ports[port], **overrides
                ),
                self.carrier,
            )
        )

    def submit_export_proof(self, report_id: str, **overrides: Any) -> JsonDict:
        return get_success_data(
            self.client.submit_export_proof(
                report_id, factories.export_proof_payload(**overrides), self.carrier
            )
        )

    # ------------------------------------------------------------------
    # Seals
    # ------------------------------------------------------------------
    def record_seal_event(
        self,
        movement_id: str,
        event_type: str,
        seal_number: str,
        port_code: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> JsonDict:
        return get_success_data(
            self.client.record_seal_event(
                factories.seal_event_payload(
                    movement_id, event_type, seal_number, port_code
                ),
                headers if headers is not None else self.carrier,
            )
        )

    # ------------------------------------------------------------------
    # Holds
    # ------------------------------------------------------------------
    def place_unscheduled_hold(
        self,
        movement_id: str,
        port: str = "chicago",
        hold_type: str = "DOCUMENT",
        reason_code: str = "MANIFEST_REVIEW",
        headers: Optional[Dict[str, str]] = None,
    ) -> JsonDict:
        return get_success_data(
            self.client.place_hold(
                factories.unscheduled_hold_payload(
                    movement_id, self.ports[port], hold_type, reason_code
                ),
                headers if headers is not None else self.officer,
            )
        )

    def place_scheduled_hold(
        self,
        movement_id: str,
        scheduled_start: str,
        scheduled_end: str,
        port: str = "chicago",
        hold_type: str = "EXAM_PHYSICAL",
        reason_code: str = "TARGETED_EXAM",
        headers: Optional[Dict[str, str]] = None,
    ) -> JsonDict:
        return get_success_data(
            self.client.place_hold(
                factories.scheduled_hold_payload(
                    movement_id,
                    self.ports[port],
                    scheduled_start,
                    scheduled_end,
                    hold_type,
                    reason_code,
                ),
                headers if headers is not None else self.officer,
            )
        )

    def release_hold(
        self,
        hold_id: str,
        findings_code: str = "CLEAR",
        discrepancy_pieces: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> JsonDict:
        return get_success_data(
            self.client.release_hold(
                hold_id,
                factories.hold_release_payload(findings_code, discrepancy_pieces),
                headers if headers is not None else self.second_officer,
            )
        )

    # ------------------------------------------------------------------
    # Amendments
    # ------------------------------------------------------------------
    def submit_extension(
        self,
        movement_id: str,
        requested_days: int,
        justification_code: str = "PORT_CONGESTION",
        expected_movement_version: Optional[int] = None,
    ) -> JsonDict:
        version = (
            expected_movement_version
            if expected_movement_version is not None
            else self.read_movement(movement_id)["version"]
        )
        return get_success_data(
            self.client.submit_amendment(
                factories.extension_payload(
                    movement_id, version, requested_days, justification_code
                ),
                self.carrier,
            )
        )

    def submit_diversion(
        self,
        movement_id: str,
        requested_destination_port_code: str,
        requested_in_bond_type: str = "IT",
        justification_code: str = "CONSIGNEE_CHANGE",
        expected_movement_version: Optional[int] = None,
    ) -> JsonDict:
        version = (
            expected_movement_version
            if expected_movement_version is not None
            else self.read_movement(movement_id)["version"]
        )
        return get_success_data(
            self.client.submit_amendment(
                factories.diversion_payload(
                    movement_id,
                    version,
                    requested_destination_port_code,
                    requested_in_bond_type,
                    justification_code,
                ),
                self.carrier,
            )
        )

    def approve_amendment(
        self,
        amendment_id: str,
        decision_reason_code: str,
        granted_days: Optional[int] = None,
    ) -> JsonDict:
        return get_success_data(
            self.client.decide_amendment(
                amendment_id,
                factories.amendment_approval_payload(decision_reason_code, granted_days),
                self.officer,
            )
        )

    # ------------------------------------------------------------------
    # Claims and petitions
    # ------------------------------------------------------------------
    def issue_claim(
        self,
        movement_id: str,
        claim_type: str,
        reason_code: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> JsonDict:
        return get_success_data(
            self.client.issue_claim(
                factories.claim_payload(movement_id, claim_type, reason_code),
                headers if headers is not None else self.officer,
            )
        )

    def file_petition(
        self,
        claim_id: str,
        mitigation_factors: List[str],
        narrative_reference: str,
        expected_claim_version: Optional[int] = None,
    ) -> JsonDict:
        version = (
            expected_claim_version
            if expected_claim_version is not None
            else self.read_claim(claim_id)["version"]
        )
        return get_success_data(
            self.client.file_petition(
                factories.petition_payload(
                    claim_id, version, mitigation_factors, narrative_reference
                ),
                self.carrier,
            )
        )

    def supplement_petition(
        self,
        petition_id: str,
        mitigation_factors: List[str],
        narrative_reference: str,
    ) -> JsonDict:
        return get_success_data(
            self.client.supplement_petition(
                petition_id,
                factories.petition_supplement_payload(
                    mitigation_factors, narrative_reference
                ),
                self.carrier,
            )
        )

    def decide_petition(
        self,
        petition_id: str,
        decision: str,
        decision_reason_code: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> JsonDict:
        return get_success_data(
            self.client.decide_petition(
                petition_id,
                factories.petition_decision_payload(decision, decision_reason_code),
                headers if headers is not None else self.fpf_officer,
            )
        )

    def pay_claim(self, claim_id: str, paid_amount: float) -> JsonDict:
        return get_success_data(
            self.client.dispose_claim(
                claim_id, factories.claim_payment_payload(paid_amount), self.carrier
            )
        )

    def cancel_claim(
        self,
        claim_id: str,
        reason_code: str = "CLAIM_ISSUED_IN_ERROR",
        headers: Optional[Dict[str, str]] = None,
    ) -> JsonDict:
        return get_success_data(
            self.client.dispose_claim(
                claim_id,
                factories.claim_cancellation_payload(reason_code),
                headers if headers is not None else self.fpf_officer,
            )
        )

    # ------------------------------------------------------------------
    # Sweeps
    # ------------------------------------------------------------------
    def run_sweep(self, note: str) -> JsonDict:
        return get_success_data(
            self.client.run_sweep(factories.sweep_payload(note), self.officer)
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def read_movement(self, movement_id: str) -> JsonDict:
        return get_success_data(self.client.get_movement(movement_id, self.officer))

    def read_bond(self, bond_id: Optional[str] = None) -> JsonDict:
        target = bond_id or self.bond_id
        assert target is not None, "no bond has been underwritten yet"
        return get_success_data(self.client.get_bond(target, self.officer))

    def read_carrier(self, carrier_id: Optional[str] = None) -> JsonDict:
        target = carrier_id or self.carrier_id
        assert target is not None, "no carrier has been registered yet"
        return get_success_data(self.client.get_carrier(target, self.officer))

    def read_port(self, alias: str) -> JsonDict:
        return get_success_data(self.client.get_port(self.ports[alias], self.officer))

    def read_hold(self, hold_id: str) -> JsonDict:
        return get_success_data(self.client.get_hold(hold_id, self.officer))

    def read_claim(self, claim_id: str) -> JsonDict:
        return get_success_data(self.client.get_claim(claim_id, self.officer))

    def read_report(self, report_id: str) -> JsonDict:
        return get_success_data(self.client.get_report(report_id, self.officer))

    def ledger_entries(self, **params: Any) -> List[JsonDict]:
        rows, _meta = validate_paginated(
            self.client.list_ledger_entries(self.officer, params=params or None)
        )
        return rows

    def ledger_page(self, **params: Any) -> Any:
        return validate_paginated(
            self.client.list_ledger_entries(self.officer, params=params or None)
        )

    def seal_events(self, movement_id: str, **params: Any) -> List[JsonDict]:
        rows, _meta = validate_paginated(
            self.client.list_seal_events(movement_id, self.officer, params=params or None)
        )
        return rows

    def holds(self, **params: Any) -> List[JsonDict]:
        rows, _meta = validate_paginated(
            self.client.list_holds(self.officer, params=params or None)
        )
        return rows

    def movement_list(self, **params: Any) -> Any:
        return validate_paginated(
            self.client.list_movements(self.officer, params=params or None)
        )

    def amendments(self, movement_id: str, **params: Any) -> Any:
        return validate_paginated(
            self.client.list_movement_amendments(
                movement_id, self.officer, params=params or None
            )
        )

    def reports(self, **params: Any) -> Any:
        return validate_paginated(
            self.client.list_reports(self.officer, params=params or None)
        )

    def claims(self, **params: Any) -> Any:
        return validate_paginated(
            self.client.list_claims(self.officer, params=params or None)
        )

    def petitions(self, claim_id: str, **params: Any) -> Any:
        return validate_paginated(
            self.client.list_claim_petitions(
                claim_id, self.officer, params=params or None
            )
        )

    def sweeps(self, **params: Any) -> Any:
        return validate_paginated(
            self.client.list_sweeps(self.officer, params=params or None)
        )


# ---------------------------------------------------------------------------
# Tier 1: an empty world with the clock pinned to its default
# ---------------------------------------------------------------------------
def build_empty_world(client: InBondApiClient) -> World:
    """A world with nothing in it, the clock explicitly set to its default."""
    world = World(client=client)
    world.set_clock(DEFAULT_CLOCK)
    return world


# ---------------------------------------------------------------------------
# Tier 2: ports, carrier, bond
# ---------------------------------------------------------------------------
def build_ports(world: World, aliases: Optional[List[str]] = None) -> World:
    """Register the standard ports. ``ny`` and ``chicago`` are the default pair."""
    builders = {
        "ny": factories.port_ny_payload,
        "chicago": factories.port_chicago_payload,
        "la": factories.port_la_payload,
        "detroit": factories.port_detroit_payload,
    }
    for alias in aliases or ["ny", "chicago"]:
        world.register_port(alias, builders[alias]())
    return world


def build_registered_world(
    client: InBondApiClient,
    port_aliases: Optional[List[str]] = None,
    bond_payload: Optional[JsonDict] = None,
) -> World:
    """Ports, an ACTIVE carrier, and one bond ready to secure filings."""
    world = build_empty_world(client)
    build_ports(world, port_aliases)
    world.register_carrier()
    if bond_payload is None:
        world.underwrite_bond()
    else:
        world.underwrite_bond(bond_payload)
    return world


def build_carrier_without_bond(
    client: InBondApiClient, port_aliases: Optional[List[str]] = None
) -> World:
    """Ports and an ACTIVE carrier, but no bond at all."""
    world = build_empty_world(client)
    build_ports(world, port_aliases)
    world.register_carrier()
    return world


# ---------------------------------------------------------------------------
# Tier 3: filed and in-transit movements
# ---------------------------------------------------------------------------
def build_filed_movement(
    client: InBondApiClient,
    manifest_reference: str = "MAN-0001",
    port_aliases: Optional[List[str]] = None,
    bond_payload: Optional[JsonDict] = None,
    **movement_overrides: Any,
) -> World:
    """The reference IT movement 4601 -> 3901, FILED and BONDED."""
    world = build_registered_world(client, port_aliases, bond_payload)
    world.file_movement(manifest_reference, **movement_overrides)
    return world


def build_departed_movement(
    client: InBondApiClient,
    manifest_reference: str = "MAN-0001",
    seal_number: str = M1_SEAL,
    port_aliases: Optional[List[str]] = None,
    bond_payload: Optional[JsonDict] = None,
    **movement_overrides: Any,
) -> World:
    """The reference movement sealed and IN_TRANSIT out of 4601."""
    world = build_filed_movement(
        client, manifest_reference, port_aliases, bond_payload, **movement_overrides
    )
    world.depart(world.movements[manifest_reference], seal_number)
    return world


def build_two_departed_movements(
    client: InBondApiClient,
    port_aliases: Optional[List[str]] = None,
    second_overrides: Optional[JsonDict] = None,
) -> World:
    """Two identical consignments, both IN_TRANSIT, sealed SEAL-100 / SEAL-200."""
    world = build_departed_movement(client, "MAN-0001", M1_SEAL, port_aliases)
    world.file_movement("MAN-0002", **(second_overrides or {}))
    world.depart(world.movements["MAN-0002"], M2_SEAL)
    return world


# ---------------------------------------------------------------------------
# Tier 4: arrived, overdue and broken-seal worlds
# ---------------------------------------------------------------------------
def build_arrived_movement(
    client: InBondApiClient,
    arrival_clock: str = "2026-08-10T00:00:00Z",
    packages_reported: int = factories.PACKAGE_COUNT,
    port_aliases: Optional[List[str]] = None,
) -> World:
    """The reference movement ARRIVED at 3901, still BONDED, well inside its
    deadline."""
    world = build_departed_movement(client, port_aliases=port_aliases)
    world.set_clock(arrival_clock)
    world.report_arrival(world.movements["MAN-0001"], packages_reported=packages_reported)
    return world


def build_overdue_movement(
    client: InBondApiClient,
    sweep_clock: str = "2026-09-06T00:00:00Z",
    note: str = "mark overdue",
    port_aliases: Optional[List[str]] = None,
) -> World:
    """The reference movement swept into OVERDUE one day past its deadline."""
    world = build_departed_movement(client, port_aliases=port_aliases)
    world.set_clock(sweep_clock)
    world.run_sweep(note)
    return world


def build_broken_seal_in_transit(
    client: InBondApiClient,
    break_clock: str = "2026-08-10T00:00:00Z",
    port_aliases: Optional[List[str]] = None,
) -> World:
    """The reference movement IN_TRANSIT with its seal broken without
    authorisation at 3901, so a system hold is open and custody is EXAM_HOLD."""
    world = build_departed_movement(client, port_aliases=port_aliases)
    world.set_clock(break_clock)
    world.record_seal_event(
        world.movements["MAN-0001"],
        "BROKEN_UNAUTHORIZED",
        M1_SEAL,
        factories.PORT_CHICAGO_CODE,
    )
    return world


# ---------------------------------------------------------------------------
# Tier 5: claims and petitions
# ---------------------------------------------------------------------------
def build_late_arrival_claim(
    client: InBondApiClient,
    arrival_clock: str = LATE_ARRIVAL_CLOCK,
    port_aliases: Optional[List[str]] = None,
) -> Any:
    """The reference movement arrives seven days late and draws a LATE_ARRIVAL
    claim assessed at the cargo value.

    Returns ``(world, claim)``.
    """
    world = build_departed_movement(client, port_aliases=port_aliases)
    world.set_clock(arrival_clock)
    world.report_arrival(world.movements["MAN-0001"])
    claim = world.issue_claim(
        world.movements["MAN-0001"], "LATE_ARRIVAL", "OVERDUE_ARRIVAL"
    )
    return world, claim


def build_four_factor_petition(
    client: InBondApiClient,
    narrative_reference: str = "PET-0001",
    arrival_clock: str = LATE_ARRIVAL_CLOCK,
) -> Any:
    """A round-one petition against the reference late-arrival claim carrying
    four mitigation factors, so the raw credit exceeds the round-one cap.

    Returns ``(world, claim, petition)``.
    """
    world, claim = build_late_arrival_claim(client, arrival_clock)
    petition = world.file_petition(
        claim["id"],
        factories.FOUR_FACTOR_MITIGATION,
        narrative_reference,
        expected_claim_version=claim["version"],
    )
    return world, claim, petition


def build_supplement_requested_petition(
    client: InBondApiClient,
    narrative_reference: str = "PET-0001",
    reason_code: str = "NEED_SEAL_EVIDENCE",
) -> Any:
    """A four-factor petition the FPF officer has sent back for more
    information, so it sits in SUPPLEMENT_REQUESTED at round 1.

    Returns ``(world, claim, petition)``.
    """
    world, claim, petition = build_four_factor_petition(client, narrative_reference)
    world.decide_petition(petition["id"], "REQUEST_SUPPLEMENT", reason_code)
    return world, claim, petition


def build_suspension_cascade_world(client: InBondApiClient) -> Any:
    """Two filings, a broken seal on the departed one, and enough violations to
    take the carrier to the auto-suspension threshold.

    The reference movement M1 departs and has its seal broken without
    authorisation, drawing a SEAL_VIOLATION claim worth 4.0 points; M3 is filed
    and never departs, so it is still FILED when the cascade runs.

    Returns ``(world, seal_claim)``.
    """
    world = build_filed_movement(client, "MAN-0001")
    world.file_movement("MAN-0003")
    world.depart(world.movements["MAN-0001"], M1_SEAL)
    world.set_clock("2026-08-10T00:00:00Z")
    world.record_seal_event(
        world.movements["MAN-0001"],
        "BROKEN_UNAUTHORIZED",
        M1_SEAL,
        factories.PORT_CHICAGO_CODE,
    )
    seal_claim = world.issue_claim(
        world.movements["MAN-0001"], "SEAL_VIOLATION", "SEAL_BROKEN_IN_TRANSIT"
    )
    world.set_clock("2026-09-06T00:00:00Z")
    world.run_sweep("mark overdue")
    return world, seal_claim


def build_export_pending_proof(client: InBondApiClient) -> Any:
    """A TE movement reported exported without proof, so the report sits in
    PENDING_PROOF and the movement stays ARRIVED, its export unperfected.

    Returns ``(world, report)``.
    """
    world = build_registered_world(client)
    world.file_movement("MAN-0060", in_bond_type="TE")
    movement_id = world.movements["MAN-0060"]
    world.depart(movement_id, "SEAL-600")
    world.set_clock("2026-08-10T00:00:00Z")
    world.report_arrival(movement_id)
    world.set_clock("2026-08-12T00:00:00Z")
    report = world.report_export(movement_id)
    return world, report


def build_general_order_world(
    client: InBondApiClient,
    arrival_clock: str = "2026-08-10T00:00:00Z",
    sweep_clock: str = "2026-08-26T00:00:00Z",
) -> World:
    """The reference movement arrives, sits past its general-order deadline, and
    a sweep pushes it into GENERAL_ORDER custody."""
    world = build_arrived_movement(client, arrival_clock)
    world.set_clock(sweep_clock)
    world.run_sweep("general order sweep")
    return world
