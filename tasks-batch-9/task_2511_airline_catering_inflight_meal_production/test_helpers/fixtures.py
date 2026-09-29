"""Composite setup helpers and the pytest fixtures built on them.

The harness relaunches the service before every single test, so each fixture
below builds its world from an empty database through published endpoints only.
Every step advances the logical clock to the instant that phase of the service
day happens at, because "Every timestamp the service writes ... is the logical
clock reading of its own request" (PRD §2.4) and the pinned release deadlines,
cutoffs and slot bands are all read off that clock.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_CART,
    CLOCK_COMPLETE,
    CLOCK_DELIVER,
    CLOCK_DISPATCH,
    CLOCK_LOCK,
    CLOCK_MANIFEST,
    CLOCK_PLAN,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    CLOCK_SETUP,
    CLOCK_UPLIFT,
    CLOCK_ARRIVE,
    EVENT_ARRIVE,
    EVENT_DELIVER,
    EVENT_DISPATCH,
    PASSING_TEMPS,
    SPEC_AN_C,
    SPEC_AN_F,
    SPEC_AN_V,
    SPEC_AN_Y,
)
from .test_users import TEST_USERS, make_airline_rep_headers

# The canonical chain's cart, seal and window literals.
CART_CODE_CHILL = "CHL-01"
CART_CODE_CHILL_2 = "CHL-02"
CART_CODE_HOT = "HOT-01"
SEAL_PRIMARY = "SEAL-AN411-01"
SEAL_SECONDARY = "SEAL-AN411-02"
WINDOW_START = "2026-09-15T07:30:00Z"
WINDOW_END = "2026-09-15T08:00:00Z"

ADMIN = TEST_USERS["platform_admin_headers"]
FEED = TEST_USERS["schedule_feed_operator_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
SUPERVISOR_2 = TEST_USERS["second_production_supervisor_headers"]
QA = TEST_USERS["qa_officer_headers"]
LM_ALICE = TEST_USERS["load_master_alice_headers"]
LM_BOB = TEST_USERS["load_master_bob_headers"]
LM_CAROL = TEST_USERS["load_master_carol_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def created(response) -> Dict[str, Any]:
    """"Creation operations return `201 Created`" (PRD §4)."""
    return validate_success(response, 201)


def ok(response) -> Dict[str, Any]:
    """"every other successful operation ... returns `200 OK`" (PRD §4)."""
    return validate_success(response, 200)


def any_2xx(response) -> Any:
    """For the two calls whose success code §4 leaves open to reading: fitting a
    seal, which only moves an axis on an existing cart, and cutting the plan,
    which both transitions the flight and materialises batch rows."""
    return get_success_data(response)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    return ok(api.set_clock(instant, ADMIN))


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


def register_airline(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(api.create_airline(f.airline_payload(**overrides), ADMIN))


def register_spec(
    api: ApiClient, airline_id: str, template: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    return created(
        api.create_meal_specification(
            f.spec_payload(airline_id, template, **overrides), ADMIN
        )
    )


def register_canonical_specs(api: ApiClient, airline_id: str) -> Dict[str, Any]:
    """The four specifications the canonical service day is priced against."""
    return {
        "F": register_spec(api, airline_id, SPEC_AN_F),
        "C": register_spec(api, airline_id, SPEC_AN_C),
        "Y": register_spec(api, airline_id, SPEC_AN_Y),
        "V": register_spec(api, airline_id, SPEC_AN_V),
    }


def register_truck(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(api.create_truck(f.truck_payload(**overrides), ADMIN))


def register_stand(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(api.create_stand(f.stand_payload(**overrides), ADMIN))


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------


def ingest_flight(api: ApiClient, airline_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(api.create_flight(f.flight_payload(airline_id, **overrides), FEED))


def lock_counts(api: ApiClient, flight_id: str) -> Dict[str, Any]:
    return ok(api.lock_counts(flight_id, {}, FEED))


def cut_plan(api: ApiClient, flight_id: str) -> List[Dict[str, Any]]:
    """Cutting the plan answers with the array of batches it materialised."""
    return any_2xx(api.cut_production_plan(flight_id, {}, SUPERVISOR))


def read_flight(api: ApiClient, flight_id: str) -> Dict[str, Any]:
    return ok(api.get_flight(flight_id, FEED))


def flight_batches(api: ApiClient, flight_id: str) -> List[Dict[str, Any]]:
    # `validate_success` already unwraps the envelope, so a list endpoint hands
    # back the row array itself.
    return ok(api.list_production_batches(FEED, {"flight_id": flight_id, "limit": 100}))


# ---------------------------------------------------------------------------
# Special meal orders
# ---------------------------------------------------------------------------


def capture_order(
    api: ApiClient,
    airline_id: str,
    flight_id: str,
    meal_specification_id: str,
    seat_number: str,
    **overrides: Any
) -> Dict[str, Any]:
    return created(
        api.create_special_meal_order(
            f.order_payload(
                flight_id, meal_specification_id, seat_number, **overrides
            ),
            make_airline_rep_headers(airline_id),
        )
    )


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


def start_batch(
    api: ApiClient, batch_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return ok(api.start_batch(batch_id, {}, headers or SUPERVISOR))


def record_check(
    api: ApiClient,
    batch_id: str,
    step_code: str,
    measured_temp_c: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    temp = PASSING_TEMPS[step_code] if measured_temp_c is None else measured_temp_c
    return created(
        api.record_haccp_check(
            batch_id, f.haccp_payload(step_code, temp), headers or QA
        )
    )


def record_passing_checks(
    api: ApiClient, batch_id: str, steps: List[str]
) -> List[Dict[str, Any]]:
    return [record_check(api, batch_id, step) for step in steps]


def complete_batch(
    api: ApiClient,
    batch_id: str,
    produced_qty: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return ok(
        api.complete_batch(
            batch_id, f.complete_payload(produced_qty), headers or SUPERVISOR
        )
    )


def release_batch(
    api: ApiClient, batch_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return ok(api.release_batch(batch_id, {}, headers or SUPERVISOR))


def produce_and_release(
    api: ApiClient,
    batch: Dict[str, Any],
    steps: List[str],
    produced_qty: Optional[int] = None,
    release_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Walk one batch `PLANNED → IN_PRODUCTION → COMPLETED → RELEASED`."""
    set_clock(api, CLOCK_PRODUCTION)
    start_batch(api, batch["id"])
    set_clock(api, CLOCK_QA)
    record_passing_checks(api, batch["id"], steps)
    set_clock(api, CLOCK_COMPLETE)
    complete_batch(
        api, batch["id"], batch["planned_qty"] if produced_qty is None else produced_qty
    )
    return release_batch(api, batch["id"], release_headers)


# ---------------------------------------------------------------------------
# Carts, items, manifests
# ---------------------------------------------------------------------------


def register_cart(
    api: ApiClient,
    flight_id: str,
    cart_code: str = CART_CODE_CHILL,
    cart_type: str = "STD_FULL",
    storage_class: str = "CHILL",
    capacity_units: int = 200,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    return created(
        api.create_cart(
            f.cart_payload(
                flight_id,
                cart_code,
                cart_type,
                storage_class,
                capacity_units,
                **overrides
            ),
            headers or LM_ALICE,
        )
    )


def load_item(
    api: ApiClient,
    cart_id: str,
    batch_id: str,
    qty_units: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return created(
        api.load_cart_item(
            cart_id, f.cart_item_payload(batch_id, qty_units), headers or LM_ALICE
        )
    )


def sign_off_build(
    api: ApiClient, cart_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return ok(api.complete_cart_build(cart_id, {}, headers or LM_ALICE))


def read_cart(api: ApiClient, cart_id: str) -> Dict[str, Any]:
    return ok(api.get_cart(cart_id, LM_ALICE))


def seal_cart(
    api: ApiClient,
    cart_id: str,
    seal_number: str = SEAL_PRIMARY,
    expected_cart_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    version = (
        read_cart(api, cart_id)["version"]
        if expected_cart_version is None
        else expected_cart_version
    )
    return any_2xx(
        api.seal_cart(
            cart_id, f.seal_payload(version, seal_number), headers or LM_ALICE
        )
    )


def open_manifest(
    api: ApiClient,
    flight_id: str,
    expected_flight_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    version = (
        read_flight(api, flight_id)["version"]
        if expected_flight_version is None
        else expected_flight_version
    )
    return created(
        api.open_loading_manifest(
            flight_id, f.manifest_payload(version), headers or LM_BOB
        )
    )


def issue_manifest(
    api: ApiClient, manifest_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return ok(api.issue_loading_manifest(manifest_id, {}, headers or LM_BOB))


# ---------------------------------------------------------------------------
# Delivery runs
# ---------------------------------------------------------------------------


def reserve_run(
    api: ApiClient,
    manifest_id: str,
    truck_id: str,
    stand_id: str,
    window_start_utc: str = WINDOW_START,
    window_end_utc: str = WINDOW_END,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return created(
        api.create_delivery_run(
            f.run_payload(
                manifest_id, truck_id, stand_id, window_start_utc, window_end_utc
            ),
            headers or LM_BOB,
        )
    )


def run_event(
    api: ApiClient,
    run_id: str,
    event_type: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    return ok(
        api.record_run_event(
            run_id, f.event_payload(event_type, **overrides), headers or LM_BOB
        )
    )


def deliver_run(
    api: ApiClient,
    run_id: str,
    dispatch_at: str = CLOCK_DISPATCH,
    arrive_at: str = CLOCK_ARRIVE,
    deliver_at: str = CLOCK_DELIVER,
) -> Dict[str, Any]:
    """Walk one run `RESERVED → EN_ROUTE → AT_AIRCRAFT → DELIVERED`."""
    set_clock(api, dispatch_at)
    run_event(api, run_id, EVENT_DISPATCH)
    set_clock(api, arrive_at)
    run_event(api, run_id, EVENT_ARRIVE)
    set_clock(api, deliver_at)
    return run_event(api, run_id, EVENT_DELIVER)


# ---------------------------------------------------------------------------
# Uplift, disposition and waste
# ---------------------------------------------------------------------------


def reconcile(
    api: ApiClient,
    flight_id: str,
    lines: List[Dict[str, Any]],
    observed_seals: Optional[List[str]] = None,
    expected_flight_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    version = (
        read_flight(api, flight_id)["version"]
        if expected_flight_version is None
        else expected_flight_version
    )
    return created(
        api.create_uplift_record(
            flight_id,
            f.uplift_payload(version, lines, observed_seals),
            headers or COMPLIANCE,
        )
    )


def record_dispositions(
    api: ApiClient,
    uplift_record_id: str,
    dispositions: List[Dict[str, Any]],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return ok(
        api.record_dispositions(
            uplift_record_id,
            f.dispositions_payload(dispositions),
            headers or COMPLIANCE,
        )
    )


def raise_waste_manifest(
    api: ApiClient,
    uplift_record_id: str,
    disposal_method: str = "INCINERATION",
    seal_number: str = "WM-AN411-01",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return created(
        api.create_waste_manifest(
            f.waste_manifest_payload(uplift_record_id, disposal_method, seal_number),
            headers or COMPLIANCE,
        )
    )


def transition_waste_manifest(
    api: ApiClient,
    waste_manifest_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    return ok(
        api.transition_waste_manifest(
            waste_manifest_id,
            f.waste_transition_payload(action, **overrides),
            headers or COMPLIANCE,
        )
    )


# ---------------------------------------------------------------------------
# The audit docket
# ---------------------------------------------------------------------------


def raise_finding(
    api: ApiClient,
    airline_id: str,
    flight_id: Optional[str],
    finding_type: str,
    severity: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    return created(
        api.create_audit_finding(
            f.finding_payload(airline_id, flight_id, finding_type, severity, **overrides),
            headers or COMPLIANCE,
        )
    )


def resolve_finding(
    api: ApiClient,
    finding_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    return ok(
        api.resolve_audit_finding(
            finding_id,
            f.resolution_payload(action, **overrides),
            headers or COMPLIANCE,
        )
    )


# ---------------------------------------------------------------------------
# The composite environment
# ---------------------------------------------------------------------------


@dataclass
class Env:
    """One canonical service day, assembled step by step."""

    api: ApiClient
    airline: Dict[str, Any]
    specs: Dict[str, Dict[str, Any]]
    truck: Dict[str, Any]
    stand: Dict[str, Any]
    flight: Optional[Dict[str, Any]] = None
    batches: List[Dict[str, Any]] = field(default_factory=list)
    carts: List[Dict[str, Any]] = field(default_factory=list)
    items: List[Dict[str, Any]] = field(default_factory=list)
    manifest: Optional[Dict[str, Any]] = None
    runs: List[Dict[str, Any]] = field(default_factory=list)
    uplift: Optional[Dict[str, Any]] = None
    waste: Optional[Dict[str, Any]] = None

    # -- convenience accessors ------------------------------------------------

    @property
    def airline_id(self) -> str:
        return self.airline["id"]

    @property
    def flight_id(self) -> str:
        assert self.flight is not None
        return self.flight["id"]

    @property
    def batch(self) -> Dict[str, Any]:
        return self.batches[0]

    @property
    def cart(self) -> Dict[str, Any]:
        return self.carts[0]

    @property
    def item(self) -> Dict[str, Any]:
        return self.items[0]

    @property
    def run(self) -> Dict[str, Any]:
        return self.runs[0]

    @property
    def rep_headers(self) -> Dict[str, str]:
        return make_airline_rep_headers(self.airline_id)

    # -- refreshers -----------------------------------------------------------

    def reload_flight(self) -> Dict[str, Any]:
        self.flight = read_flight(self.api, self.flight_id)
        return self.flight

    def reload_batches(self) -> List[Dict[str, Any]]:
        self.batches = flight_batches(self.api, self.flight_id)
        return self.batches

    def reload_cart(self, index: int = 0) -> Dict[str, Any]:
        self.carts[index] = read_cart(self.api, self.carts[index]["id"])
        return self.carts[index]

    def reload_airline(self) -> Dict[str, Any]:
        self.airline = ok(self.api.get_airline(self.airline_id, ADMIN))
        return self.airline

    def reload_manifest(self) -> Dict[str, Any]:
        assert self.manifest is not None
        self.manifest = ok(
            self.api.get_loading_manifest(self.manifest["id"], LM_BOB)
        )
        return self.manifest

    def reload_run(self, index: int = 0) -> Dict[str, Any]:
        self.runs[index] = ok(
            self.api.get_delivery_run(self.runs[index]["id"], LM_BOB)
        )
        return self.runs[index]

    def reload_uplift(self) -> Dict[str, Any]:
        assert self.uplift is not None
        self.uplift = ok(self.api.get_uplift_record(self.uplift["id"], COMPLIANCE))
        return self.uplift


# ---------------------------------------------------------------------------
# The step-wise builders the fixtures chain together
# ---------------------------------------------------------------------------


def build_base(api: ApiClient, **airline_overrides: Any) -> Env:
    """Clock at the setup instant, one airline, four specifications, one truck,
    one stand."""
    set_clock(api, CLOCK_SETUP)
    airline = register_airline(api, **airline_overrides)
    specs = register_canonical_specs(api, airline["id"])
    truck = register_truck(api)
    stand = register_stand(api)
    return Env(api=api, airline=airline, specs=specs, truck=truck, stand=stand)


def add_flight(env: Env, **overrides: Any) -> Env:
    """The canonical 180-passenger economy flight."""
    payload = {"pax_economy": 180}
    payload.update(overrides)
    env.flight = ingest_flight(env.api, env.airline_id, **payload)
    return env


def advance_to_locked(env: Env) -> Env:
    set_clock(env.api, CLOCK_LOCK)
    env.flight = lock_counts(env.api, env.flight_id)
    return env


def advance_to_planned(env: Env) -> Env:
    set_clock(env.api, CLOCK_PLAN)
    env.batches = cut_plan(env.api, env.flight_id)
    env.reload_flight()
    return env


def advance_to_released(env: Env) -> Env:
    steps = SPEC_AN_Y["required_haccp_steps"]
    for batch in list(env.batches):
        produce_and_release(env.api, batch, list(steps))
    env.reload_batches()
    env.reload_flight()
    return env


def advance_to_built_cart(env: Env, qty_units: Optional[int] = None) -> Env:
    set_clock(env.api, CLOCK_CART)
    cart = register_cart(env.api, env.flight_id)
    env.carts.append(cart)
    qty = env.batch["planned_qty"] if qty_units is None else qty_units
    env.items.append(load_item(env.api, cart["id"], env.batch["id"], qty))
    env.carts[0] = sign_off_build(env.api, cart["id"])
    env.reload_flight()
    return env


def advance_to_sealed(env: Env, seal_number: str = SEAL_PRIMARY) -> Env:
    env.carts[0] = seal_cart(env.api, env.cart["id"], seal_number, headers=LM_ALICE)
    return env


def advance_to_issued(env: Env) -> Env:
    set_clock(env.api, CLOCK_MANIFEST)
    env.manifest = open_manifest(env.api, env.flight_id, headers=LM_BOB)
    env.manifest = issue_manifest(env.api, env.manifest["id"], headers=LM_BOB)
    env.reload_flight()
    return env


def advance_to_departed(env: Env) -> Env:
    assert env.manifest is not None
    run = reserve_run(env.api, env.manifest["id"], env.truck["id"], env.stand["id"])
    env.runs.append(run)
    env.runs[0] = deliver_run(env.api, run["id"])
    env.reload_flight()
    return env


def advance_to_reconciled(
    env: Env,
    consumed_units: int = 170,
    returned_units: int = 10,
    observed_seals: Optional[List[str]] = None,
) -> Env:
    set_clock(env.api, CLOCK_UPLIFT)
    env.uplift = reconcile(
        env.api,
        env.flight_id,
        [f.uplift_line(env.specs["Y"]["id"], consumed_units, returned_units)],
        observed_seals,
    )
    env.reload_flight()
    return env


def advance_to_dispositioned(
    env: Env,
    reuse_units: int = 0,
    donate_units: int = 0,
    destroy_units: int = 10,
) -> Env:
    assert env.uplift is not None
    env.uplift = record_dispositions(
        env.api,
        env.uplift["id"],
        [
            f.disposition_line(
                env.specs["Y"]["id"], reuse_units, donate_units, destroy_units
            )
        ],
    )
    return env


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def base_env(api: ApiClient) -> Env:
    """Reference data only: airline, four specifications, truck and stand."""
    return build_base(api)


@pytest.fixture
def flight_env(base_env: Env) -> Env:
    """The canonical flight in `SCHEDULED`."""
    return add_flight(base_env)


@pytest.fixture
def locked_env(flight_env: Env) -> Env:
    """The canonical flight in `COUNTS_LOCKED`."""
    return advance_to_locked(flight_env)


@pytest.fixture
def planned_env(locked_env: Env) -> Env:
    """The canonical flight in `PLANNED` with its one chill batch of 180."""
    return advance_to_planned(locked_env)


@pytest.fixture
def released_env(planned_env: Env) -> Env:
    """The chill batch produced in full and `RELEASED`."""
    return advance_to_released(planned_env)


@pytest.fixture
def built_cart_env(released_env: Env) -> Env:
    """One chill cart holding all 180 units, signed off `BUILT`, still unsealed."""
    return advance_to_built_cart(released_env)


@pytest.fixture
def sealed_env(built_cart_env: Env) -> Env:
    """The built cart sealed with `SEAL-AN411-01` by `lm_alice`."""
    return advance_to_sealed(built_cart_env)


@pytest.fixture
def issued_env(sealed_env: Env) -> Env:
    """The manifest issued by `lm_bob`, so the flight is `LOADED`."""
    return advance_to_issued(sealed_env)


@pytest.fixture
def departed_env(issued_env: Env) -> Env:
    """The one run delivered inside its window, so the flight is `DEPARTED`."""
    return advance_to_departed(issued_env)


@pytest.fixture
def reconciled_env(departed_env: Env) -> Env:
    """A `DRAFT` uplift record of 170 consumed and 10 returned units."""
    return advance_to_reconciled(departed_env)


@pytest.fixture
def dispositioned_env(reconciled_env: Env) -> Env:
    """All ten returned units destroyed, so the record is `DISPOSITIONED`."""
    return advance_to_dispositioned(reconciled_env)


@pytest.fixture
def platform_admin_headers() -> Dict[str, str]:
    return ADMIN


@pytest.fixture
def schedule_feed_operator_headers() -> Dict[str, str]:
    return FEED


@pytest.fixture
def production_supervisor_headers() -> Dict[str, str]:
    return SUPERVISOR


@pytest.fixture
def second_production_supervisor_headers() -> Dict[str, str]:
    return SUPERVISOR_2


@pytest.fixture
def qa_officer_headers() -> Dict[str, str]:
    return QA


@pytest.fixture
def load_master_alice_headers() -> Dict[str, str]:
    return LM_ALICE


@pytest.fixture
def load_master_bob_headers() -> Dict[str, str]:
    return LM_BOB


@pytest.fixture
def load_master_carol_headers() -> Dict[str, str]:
    return LM_CAROL


@pytest.fixture
def compliance_officer_headers() -> Dict[str, str]:
    return COMPLIANCE
