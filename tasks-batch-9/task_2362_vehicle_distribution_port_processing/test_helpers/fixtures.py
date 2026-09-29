"""Pytest fixtures and the workflow driver.

The harness relaunches the API before every individual test, so every test
starts against an empty store and must build each precondition it needs from
the declared endpoints.  The fixtures below are layered so a test only pays for
the depth of setup it actually uses:

* tier 1 -- transport: the client and the error-catalogue registration.
* tier 2 -- reference data: a processing center, a berth, an open voyage,
  kit stock, a consignee dealer and an inland carrier.
* tier 3 -- single entities: a discharged unit, a submitted survey.
* tier 4 -- composite workflow states: a shipping-ready unit, an allocated
  unit, a released unit, a gated-out unit.
* tier 5 -- scenario builders: the :class:`Vpc` driver, which exposes one
  method per step of the unit's path so a test can compose any shape it needs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import VpcApiClient
from .api_errors import install_error_status_map
from .constants import (
    DAMAGE_ZONE_INTERIOR,
    DEFAULT_FREE_STORAGE_DAYS,
    DEFAULT_TURNAROUND_BUFFER_MINUTES,
    MODEL_LINE_LX500,
    OUTCOME_PASS,
    vin,
)
from .test_users import (
    INSPECTOR,
    MANAGER,
    PLANNER,
    SURVEYOR,
    TECHNICIAN,
    TestUser,
    dealer_user,
)

#: The berth window the reference voyage reserves.
REFERENCE_WINDOW_START = "2026-08-01T06:00:00Z"
REFERENCE_WINDOW_END = "2026-08-01T18:00:00Z"
#: The instant the reference voyage begins discharging units.
REFERENCE_DISCHARGE_CLOCK = "2026-08-02T00:00:00Z"

#: A single interior damage line scoring below the damage-open threshold, used
#: whenever a test needs a unit to reach ``SURVEYED`` without opening damage.
COSMETIC_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 10, 5_000)


def created(response) -> Dict[str, Any]:
    """Unwrap a creation response, which answers 201."""
    return validate_success(response, 201)


def ok(response) -> Dict[str, Any]:
    """Unwrap a read or transition response, which answers 200."""
    return validate_success(response, 200)


def open_port(
    flow: "Vpc",
    *,
    discharge_clock: str = REFERENCE_DISCHARGE_CLOCK,
    turnaround_buffer_minutes: int = DEFAULT_TURNAROUND_BUFFER_MINUTES,
    **center_overrides: Any,
) -> "Vpc":
    """Register a center on the reference rate card, a berth, and open a voyage.

    Every figure that drives a cent total is stated explicitly rather than left
    to a declared default, so a test asserting a charge never depends on one.
    """
    center = flow.create_center(free_storage_days=DEFAULT_FREE_STORAGE_DAYS, **center_overrides)
    berth = flow.create_berth(center["id"], turnaround_buffer_minutes=turnaround_buffer_minutes)
    return flow.bootstrap(center=center, berth=berth, discharge_clock=discharge_clock)


class Vpc:
    """Workflow driver: one method per step of a unit's path through the port."""

    def __init__(self, api: VpcApiClient) -> None:
        self.api = api
        self.center: Dict[str, Any] = {}
        self.berth: Dict[str, Any] = {}
        self.vessel: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, user: TestUser = PLANNER) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(current_utc, user))

    def read_clock(self, user: TestUser = PLANNER) -> Dict[str, Any]:
        return ok(self.api.get_clock(user))

    # ------------------------------------------------------------------
    # tier 2: reference data
    # ------------------------------------------------------------------
    def create_center(self, **overrides: Any) -> Dict[str, Any]:
        data = created(self.api.create_center(f.center_payload(**overrides), PLANNER))
        if not self.center:
            self.center = data
        return data

    def create_berth(self, center_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        data = created(
            self.api.create_berth(
                f.berth_payload(center_id or self.center["id"], **overrides), PLANNER
            )
        )
        if not self.berth:
            self.berth = data
        return data

    def create_vessel(
        self,
        center_id: Optional[str] = None,
        berth_id: Optional[str] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        payload = f.vessel_payload(
            center_id or self.center["id"], berth_id or self.berth["id"], **overrides
        )
        data = created(self.api.create_vessel(payload, PLANNER))
        if not self.vessel:
            self.vessel = data
        return data

    def create_dealer(self, **overrides: Any) -> Dict[str, Any]:
        return created(self.api.create_dealer(f.dealer_payload(**overrides), MANAGER))

    def create_carrier(self, **overrides: Any) -> Dict[str, Any]:
        return created(self.api.create_carrier(f.carrier_payload(**overrides), MANAGER))

    def create_kit(self, center_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        return created(
            self.api.create_kit(center_id or self.center["id"], f.kit_payload(**overrides), TECHNICIAN)
        )

    # ------------------------------------------------------------------
    # tier 2: an open voyage
    # ------------------------------------------------------------------
    def bootstrap(
        self,
        *,
        discharge_clock: str = REFERENCE_DISCHARGE_CLOCK,
        center: Optional[Dict[str, Any]] = None,
        berth: Optional[Dict[str, Any]] = None,
        vessel: Optional[Dict[str, Any]] = None,
    ) -> "Vpc":
        """Register a center and berth, schedule a voyage, and open discharge."""
        self.center = center or self.create_center()
        self.berth = berth or self.create_berth()
        self.vessel = vessel or self.create_vessel(
            berth_window_start=REFERENCE_WINDOW_START,
            berth_window_end=REFERENCE_WINDOW_END,
        )
        self.set_clock(discharge_clock)
        self.vessel = ok(self.api.start_discharge(self.vessel["id"], PLANNER))
        return self

    def start_discharge(self, vessel_id: Optional[str] = None) -> Dict[str, Any]:
        return ok(self.api.start_discharge(vessel_id or self.vessel["id"], PLANNER))

    def complete_voyage(self, vessel_id: Optional[str] = None) -> Dict[str, Any]:
        data = ok(self.api.complete_discharge(vessel_id or self.vessel["id"], PLANNER))
        if not vessel_id or vessel_id == self.vessel.get("id"):
            self.vessel = data
        return data

    # ------------------------------------------------------------------
    # tier 3: units
    # ------------------------------------------------------------------
    def discharge(
        self,
        serial: str,
        *,
        model_line: str = MODEL_LINE_LX500,
        vessel_id: Optional[str] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        payload = f.vehicle_payload(vin(serial), model_line=model_line, **overrides)
        return created(self.api.discharge_vehicle(vessel_id or self.vessel["id"], payload, PLANNER))

    def survey(
        self,
        vehicle_id: str,
        line_items: Optional[Sequence[Dict[str, Any]]] = None,
        user: TestUser = SURVEYOR,
    ) -> Dict[str, Any]:
        return created(self.api.create_survey(vehicle_id, f.survey_payload(line_items), user))

    def submit_survey(self, survey_id: str, user: TestUser = SURVEYOR) -> Dict[str, Any]:
        return ok(self.api.submit_survey(survey_id, user))

    def surveyed(
        self,
        vehicle_id: str,
        line_items: Optional[Sequence[Dict[str, Any]]] = None,
        user: TestUser = SURVEYOR,
    ) -> Dict[str, Any]:
        """Open a survey and submit it; returns the submitted survey."""
        survey = self.survey(vehicle_id, line_items, user)
        return self.submit_survey(survey["id"], user)

    # ------------------------------------------------------------------
    # tier 3: claims and repairs
    # ------------------------------------------------------------------
    def file_claim(
        self,
        survey_id: str,
        expected_version: int,
        user: TestUser = SURVEYOR,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return created(
            self.api.file_claim(survey_id, f.claim_payload(expected_version, **overrides), user)
        )

    def accept_claim(self, claim_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.carrier_response(claim_id, f.accept_payload(), user))

    def dispute_claim(self, claim_id: str, conceded: int, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.carrier_response(claim_id, f.dispute_payload(conceded), user))

    def deny_claim(self, claim_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.carrier_response(claim_id, f.deny_payload(), user))

    def resubmit_claim(self, claim_id: str, revised: int, user: TestUser = SURVEYOR) -> Dict[str, Any]:
        return ok(self.api.resubmit_claim(claim_id, f.resubmit_payload(revised), user))

    def settle_claim(self, claim_id: str, amount: int, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.settle_claim(claim_id, f.settle_payload(amount), user))

    def repair_order(
        self,
        vehicle_id: str,
        estimate_cents: int,
        user: TestUser = SURVEYOR,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return created(
            self.api.create_repair_order(
                vehicle_id, f.repair_order_payload(estimate_cents, **overrides), user
            )
        )

    def authorize_repair(self, repair_order_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.authorize_repair(repair_order_id, f.authorize_payload(), user))

    def reject_repair(self, repair_order_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.authorize_repair(repair_order_id, f.reject_payload(), user))

    def complete_repair(
        self, repair_order_id: str, actual_cost_cents: int, user: TestUser = SURVEYOR
    ) -> Dict[str, Any]:
        return ok(
            self.api.complete_repair(
                repair_order_id, f.repair_complete_payload(actual_cost_cents), user
            )
        )

    # ------------------------------------------------------------------
    # tier 3: accessory work
    # ------------------------------------------------------------------
    def plan_work_order(
        self, vehicle_id: str, kit_id: str, qty: int = 1, user: TestUser = TECHNICIAN
    ) -> Dict[str, Any]:
        return created(
            self.api.create_work_order(vehicle_id, f.work_order_payload(kit_id, qty=qty), user)
        )

    def kit_work_order(self, work_order_id: str, user: TestUser = TECHNICIAN) -> Dict[str, Any]:
        return ok(self.api.kit_work_order(work_order_id, user))

    def install_work_order(self, work_order_id: str, user: TestUser = TECHNICIAN) -> Dict[str, Any]:
        return ok(self.api.install_work_order(work_order_id, user))

    def void_work_order(self, work_order_id: str, user: TestUser = TECHNICIAN) -> Dict[str, Any]:
        return ok(self.api.void_work_order(work_order_id, user))

    def installed_work_order(
        self, vehicle_id: str, kit_id: str, qty: int = 1, user: TestUser = TECHNICIAN
    ) -> Dict[str, Any]:
        """Plan, kit and install one work order in a single step."""
        order = self.plan_work_order(vehicle_id, kit_id, qty, user)
        self.kit_work_order(order["id"], user)
        return self.install_work_order(order["id"], user)

    # ------------------------------------------------------------------
    # tier 3: inspection and preparation
    # ------------------------------------------------------------------
    def open_inspection(self, vehicle_id: str, user: TestUser = INSPECTOR) -> Dict[str, Any]:
        return created(self.api.open_inspection(vehicle_id, user))

    def complete_inspection(
        self, inspection_id: str, outcome: str, defect_count: int, user: TestUser = INSPECTOR
    ) -> Dict[str, Any]:
        payload = (
            f.pass_payload(defect_count) if outcome == OUTCOME_PASS else f.fail_payload(defect_count)
        )
        return ok(self.api.complete_inspection(inspection_id, payload, user))

    def pass_inspection(self, vehicle_id: str, user: TestUser = INSPECTOR) -> Dict[str, Any]:
        inspection = self.open_inspection(vehicle_id, user)
        return self.complete_inspection(inspection["id"], OUTCOME_PASS, 0, user)

    def prep_complete(self, vehicle_id: str, user: TestUser = INSPECTOR) -> Dict[str, Any]:
        return ok(self.api.prep_complete(vehicle_id, user))

    # ------------------------------------------------------------------
    # tier 3: holds
    # ------------------------------------------------------------------
    def apply_model_line_hold(
        self,
        model_line: str,
        center_id: Optional[str] = None,
        user: TestUser = MANAGER,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return created(
            self.api.apply_hold(
                center_id or self.center["id"],
                f.model_line_hold_payload(model_line, **overrides),
                user,
            )
        )

    def apply_single_vin_hold(
        self,
        vehicle_id: str,
        center_id: Optional[str] = None,
        user: TestUser = MANAGER,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return created(
            self.api.apply_hold(
                center_id or self.center["id"],
                f.single_vin_hold_payload(vehicle_id, **overrides),
                user,
            )
        )

    def lift_hold(self, hold_order_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.lift_hold(hold_order_id, user))

    # ------------------------------------------------------------------
    # tier 4: allocation and release
    # ------------------------------------------------------------------
    def allocate(
        self,
        vehicle_id: str,
        dealer_id: str,
        expected_version: int,
        user: TestUser = MANAGER,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return created(
            self.api.allocate(
                vehicle_id, f.allocation_payload(dealer_id, expected_version, **overrides), user
            )
        )

    def dispatch(self, release_order_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.dispatch(release_order_id, user))

    def gate_out(self, release_order_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.gate_out(release_order_id, user))

    def cancel(self, release_order_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.cancel_release_order(release_order_id, user))

    def confirm_delivery(self, release_order_id: str, dealer_id: str) -> Dict[str, Any]:
        return ok(self.api.confirm_delivery(release_order_id, dealer_user(dealer_id)))

    # ------------------------------------------------------------------
    # tier 4: composite unit states
    # ------------------------------------------------------------------
    def shipping_ready_unit(
        self,
        serial: str,
        *,
        model_line: str = MODEL_LINE_LX500,
        line_items: Optional[Sequence[Dict[str, Any]]] = None,
        complete_voyage: bool = True,
        vessel_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Discharge a unit and walk it to ``SHIPPING_READY``.

        The default survey scores below the damage-open threshold so the damage
        dimension stays ``NONE`` and the preparation gate is clear.
        """
        vehicle = self.discharge(serial, model_line=model_line, vessel_id=vessel_id)
        self.surveyed(vehicle["id"], line_items if line_items is not None else [COSMETIC_LINE])
        if complete_voyage:
            self.complete_voyage(vessel_id)
        self.pass_inspection(vehicle["id"])
        return self.prep_complete(vehicle["id"])

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def get_center(self, center_id: Optional[str] = None, user: TestUser = PLANNER) -> Dict[str, Any]:
        return ok(self.api.get_center(center_id or self.center["id"], user))

    def get_vessel(self, vessel_id: Optional[str] = None, user: TestUser = PLANNER) -> Dict[str, Any]:
        return ok(self.api.get_vessel(vessel_id or self.vessel["id"], user))

    def get_vehicle(self, vehicle_id: str, user: TestUser = PLANNER) -> Dict[str, Any]:
        return ok(self.api.get_vehicle(vehicle_id, user))

    def get_survey(self, survey_id: str, user: TestUser = SURVEYOR) -> Dict[str, Any]:
        return ok(self.api.get_survey(survey_id, user))

    def get_claim(self, claim_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.get_claim(claim_id, user))

    def get_repair_order(self, repair_order_id: str, user: TestUser = SURVEYOR) -> Dict[str, Any]:
        return ok(self.api.get_repair_order(repair_order_id, user))

    def get_kit(self, kit_id: str, user: TestUser = TECHNICIAN) -> Dict[str, Any]:
        return ok(self.api.get_kit(kit_id, user))

    def get_work_order(self, work_order_id: str, user: TestUser = TECHNICIAN) -> Dict[str, Any]:
        return ok(self.api.get_work_order(work_order_id, user))

    def get_inspection(self, inspection_id: str, user: TestUser = INSPECTOR) -> Dict[str, Any]:
        return ok(self.api.get_inspection(inspection_id, user))

    def get_hold(self, hold_order_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.get_hold(hold_order_id, user))

    def get_dealer(self, dealer_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.get_dealer(dealer_id, user))

    def get_carrier(self, carrier_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.get_carrier(carrier_id, user))

    def get_release_order(self, release_order_id: str, user: TestUser = MANAGER) -> Dict[str, Any]:
        return ok(self.api.get_release_order(release_order_id, user))

    def dwell_metrics(self, center_id: Optional[str] = None, user: TestUser = PLANNER) -> Dict[str, Any]:
        return ok(self.api.get_dwell_metrics(center_id or self.center["id"], user))

    # ------------------------------------------------------------------
    # list helpers
    # ------------------------------------------------------------------
    def list_release_orders(
        self, params: Optional[Dict[str, Any]] = None, user: TestUser = MANAGER
    ) -> List[Dict[str, Any]]:
        return ok(self.api.list_release_orders(user, params=params))

    def list_holds(self, params: Optional[Dict[str, Any]] = None, user: TestUser = MANAGER) -> List[Dict[str, Any]]:
        return ok(self.api.list_holds(user, params=params))

    def list_claims(self, params: Optional[Dict[str, Any]] = None, user: TestUser = MANAGER) -> List[Dict[str, Any]]:
        return ok(self.api.list_claims(user, params=params))

    def list_work_orders(
        self, params: Optional[Dict[str, Any]] = None, user: TestUser = TECHNICIAN
    ) -> List[Dict[str, Any]]:
        return ok(self.api.list_work_orders(user, params=params))


# ==========================================================================
# tier 1: transport
# ==========================================================================
@pytest.fixture(autouse=True)
def _error_catalogue() -> None:
    """Register the error catalogue so error assertions cross-check status."""
    install_error_status_map()


@pytest.fixture
def api() -> VpcApiClient:
    return VpcApiClient()


@pytest.fixture
def flow(api: VpcApiClient) -> Vpc:
    """The workflow driver, with nothing created yet."""
    return Vpc(api)


# ==========================================================================
# tier 2: reference data
# ==========================================================================
@pytest.fixture
def center(flow: Vpc) -> Dict[str, Any]:
    return flow.create_center()


@pytest.fixture
def berth(flow: Vpc, center: Dict[str, Any]) -> Dict[str, Any]:
    return flow.create_berth(center["id"])


@pytest.fixture
def scheduled_vessel(flow: Vpc, center: Dict[str, Any], berth: Dict[str, Any]) -> Dict[str, Any]:
    return flow.create_vessel(
        center["id"],
        berth["id"],
        berth_window_start=REFERENCE_WINDOW_START,
        berth_window_end=REFERENCE_WINDOW_END,
    )


@pytest.fixture
def port(flow: Vpc) -> Vpc:
    """A center, a berth and a voyage already discharging at 2026-08-02."""
    return flow.bootstrap()


@pytest.fixture
def dealer(flow: Vpc) -> Dict[str, Any]:
    return flow.create_dealer()


@pytest.fixture
def carrier(flow: Vpc) -> Dict[str, Any]:
    return flow.create_carrier()


@pytest.fixture
def kit(port: Vpc) -> Dict[str, Any]:
    return port.create_kit()


# ==========================================================================
# tier 3: single entities
# ==========================================================================
@pytest.fixture
def vehicle(port: Vpc) -> Dict[str, Any]:
    """One unit discharged into the yard at 2026-08-02T00:00:00Z."""
    return port.discharge("000901")


@pytest.fixture
def surveyed_vehicle(port: Vpc, vehicle: Dict[str, Any]) -> Dict[str, Any]:
    """The same unit after a cosmetic survey has been submitted."""
    port.surveyed(vehicle["id"], [COSMETIC_LINE])
    return port.get_vehicle(vehicle["id"])


# ==========================================================================
# tier 4: composite workflow states
# ==========================================================================
@pytest.fixture
def shipping_ready_vehicle(port: Vpc) -> Dict[str, Any]:
    """A unit in ``SHIPPING_READY`` off a closed voyage, damage never opened."""
    return port.shipping_ready_unit("000902")


@pytest.fixture
def allocated(port: Vpc, dealer: Dict[str, Any], carrier: Dict[str, Any]) -> Dict[str, Any]:
    """A shipping-ready unit allocated to a dealer with a server-chosen carrier.

    Returns the unit, the dealer, the carrier and the release order.
    """
    unit = port.shipping_ready_unit("000903")
    order = port.allocate(unit["id"], dealer["id"], unit["version"])
    return {
        "vehicle": port.get_vehicle(unit["id"]),
        "dealer": port.get_dealer(dealer["id"]),
        "carrier": port.get_carrier(carrier["id"]),
        "release_order": order,
    }


@pytest.fixture
def released(port: Vpc, allocated: Dict[str, Any]) -> Dict[str, Any]:
    """The allocated unit after dispatch, with freight settled."""
    order = port.dispatch(allocated["release_order"]["id"])
    return {
        "vehicle": port.get_vehicle(allocated["vehicle"]["id"]),
        "dealer": port.get_dealer(allocated["dealer"]["id"]),
        "carrier": port.get_carrier(allocated["carrier"]["id"]),
        "release_order": order,
    }


@pytest.fixture
def gated_out(port: Vpc, released: Dict[str, Any]) -> Dict[str, Any]:
    """The released unit after gate-out, with storage finalized."""
    order = port.gate_out(released["release_order"]["id"])
    return {
        "vehicle": port.get_vehicle(released["vehicle"]["id"]),
        "dealer": port.get_dealer(released["dealer"]["id"]),
        "carrier": port.get_carrier(released["carrier"]["id"]),
        "release_order": order,
        "center": port.get_center(),
    }
