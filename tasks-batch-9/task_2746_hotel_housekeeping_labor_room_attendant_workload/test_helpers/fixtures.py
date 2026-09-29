"""Composite scenario builders.

The harness restarts the server before every individual test, so each test
starts against an empty database and must build all of its own preconditions
through the public endpoints of PRD 4.  The helpers here encapsulate the long
setup chains that PRD 3 imposes — property, room types, rooms, attendants, linen
line, forecast day, publish, roster, clock-in, assignments, completions and
inspections — so that a test body contains only its own trigger and asserts.

All setup calls go through `get_success_data()`, which accepts any 2xx and
raises a readable AssertionError naming the failing error_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CATEGORY_STANDARD,
    DEFAULT_BUSINESS_DATE,
    DEFAULT_CLOCK,
    LINEN_SHEET_SET,
    OCCUPANCY_DUE_OUT,
    OCCUPANCY_VACANT,
    ORDINANCE_NONE,
    PROGRAM_OPT_OUT,
    SERVICE_CHECKOUT,
)
from .test_users import (
    COMPLIANCE_HEADERS,
    DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    LAUNDRY_LEAD_HEADERS,
    make_room_attendant_headers,
    make_supervisor_headers,
)

JsonDict = dict[str, Any]


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str = DEFAULT_CLOCK) -> None:
    """Pin the logical UTC clock (PRD 2.4)."""
    get_success_data(api.set_clock(to_iso8601, DIRECTOR_HEADERS))


def create_property(api: ApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_property(f.property_payload(**overrides), DIRECTOR_HEADERS)
    )


def create_room_type(api: ApiClient, property_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_room_type(
            f.room_type_payload(property_id, **overrides), DIRECTOR_HEADERS
        )
    )


def create_suite_room_type(api: ApiClient, property_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_room_type(
            f.suite_room_type_payload(property_id, **overrides), DIRECTOR_HEADERS
        )
    )


def create_room(
    api: ApiClient, property_id: str, room_type_id: str, room_number: str, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api.create_room(
            f.room_payload(property_id, room_type_id, room_number, **overrides),
            DIRECTOR_HEADERS,
        )
    )


def patch_room(api: ApiClient, room_id: str, **fields: Any) -> JsonDict:
    return get_success_data(api.patch_room(room_id, dict(fields), DIRECTOR_HEADERS))


def create_attendant(api: ApiClient, property_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_attendant(
            f.attendant_payload(property_id, **overrides), DIRECTOR_HEADERS
        )
    )


def create_inspector(api: ApiClient, property_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_attendant(
            f.inspector_payload(property_id, **overrides), DIRECTOR_HEADERS
        )
    )


def patch_attendant(api: ApiClient, attendant_id: str, **fields: Any) -> JsonDict:
    return get_success_data(
        api.patch_attendant(attendant_id, dict(fields), DIRECTOR_HEADERS)
    )


def create_linen_item(api: ApiClient, property_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_linen_item(
            f.linen_item_payload(property_id, **overrides), LAUNDRY_LEAD_HEADERS
        )
    )


def soil_linen(api: ApiClient, linen_item_id: str, sets: int) -> JsonDict:
    return get_success_data(
        api.soil_linen(linen_item_id, f.soil_payload(sets), LAUNDRY_LEAD_HEADERS)
    )


def create_forecast_day(api: ApiClient, property_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_forecast_day(
            f.forecast_day_payload(property_id, **overrides), DIRECTOR_HEADERS
        )
    )


def publish_day(api: ApiClient, day_id: str) -> JsonDict:
    return get_success_data(api.publish_forecast_day(day_id, DIRECTOR_HEADERS))


def close_day(api: ApiClient, day_id: str) -> JsonDict:
    return get_success_data(api.close_forecast_day(day_id, DIRECTOR_HEADERS))


def create_roster(api: ApiClient, forecast_day_id: str, attendant_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_shift_roster(
            f.shift_roster_payload(forecast_day_id, attendant_id, **overrides),
            DIRECTOR_HEADERS,
        )
    )


def clock_in(api: ApiClient, roster_id: str, attendant_id: str) -> JsonDict:
    """Clock in as the RoomAttendant who owns the roster (PRD 3.3)."""
    return get_success_data(
        api.clock_in(roster_id, make_room_attendant_headers(attendant_id))
    )


def read_roster(api: ApiClient, roster_id: str) -> JsonDict:
    return get_success_data(api.get_shift_roster(roster_id, DIRECTOR_HEADERS))


def read_room(api: ApiClient, room_id: str) -> JsonDict:
    return get_success_data(api.get_room(room_id, DIRECTOR_HEADERS))


def read_assignment(api: ApiClient, assignment_id: str) -> JsonDict:
    return get_success_data(api.get_room_assignment(assignment_id, DIRECTOR_HEADERS))


def read_attendant(api: ApiClient, attendant_id: str) -> JsonDict:
    return get_success_data(api.get_attendant(attendant_id, DIRECTOR_HEADERS))


def read_linen_item(api: ApiClient, linen_item_id: str) -> JsonDict:
    return get_success_data(api.get_linen_item(linen_item_id, DIRECTOR_HEADERS))


def read_day(api: ApiClient, day_id: str) -> JsonDict:
    return get_success_data(api.get_forecast_day(day_id, DIRECTOR_HEADERS))


def read_property(api: ApiClient, property_id: str) -> JsonDict:
    return get_success_data(api.get_property(property_id, DIRECTOR_HEADERS))


def read_cycle(api: ApiClient, cycle_id: str) -> JsonDict:
    return get_success_data(api.get_laundry_cycle(cycle_id, DIRECTOR_HEADERS))


def read_enrollment(api: ApiClient, enrollment_id: str) -> JsonDict:
    return get_success_data(api.get_service_enrollment(enrollment_id, DIRECTOR_HEADERS))


def read_item(api: ApiClient, item_id: str) -> JsonDict:
    return get_success_data(api.get_lost_found_item(item_id, DIRECTOR_HEADERS))


def read_sample_plan(api: ApiClient, roster_id: str) -> JsonDict:
    return get_success_data(api.get_sample_plan(roster_id, DIRECTOR_HEADERS))


# --------------------------------------------------------------------------
# Scenario handle
# --------------------------------------------------------------------------


@dataclass
class Scenario:
    """Handles onto everything a scenario built, plus chaining helpers.

    `roster_version` tracks the roster `version` the client last observed, so
    successive assignment creates can chain off `roster_version_after` exactly as
    PRD 2.7 intends.
    """

    api: ApiClient
    prop: JsonDict
    room_types: dict[str, JsonDict] = field(default_factory=dict)
    rooms: dict[str, JsonDict] = field(default_factory=dict)
    worker: Optional[JsonDict] = None
    inspector: Optional[JsonDict] = None
    linen: Optional[JsonDict] = None
    day: Optional[JsonDict] = None
    roster: Optional[JsonDict] = None
    roster_version: Optional[int] = None
    assignments: list[JsonDict] = field(default_factory=list)

    # -- identity ---------------------------------------------------------

    @property
    def property_id(self) -> str:
        return self.prop["id"]

    @property
    def worker_id(self) -> str:
        assert self.worker is not None, "scenario has no worker attendant"
        return self.worker["id"]

    @property
    def inspector_id(self) -> str:
        assert self.inspector is not None, "scenario has no inspector attendant"
        return self.inspector["id"]

    @property
    def day_id(self) -> str:
        assert self.day is not None, "scenario has no forecast day"
        return self.day["id"]

    @property
    def roster_id(self) -> str:
        assert self.roster is not None, "scenario has no shift roster"
        return self.roster["id"]

    @property
    def linen_id(self) -> str:
        assert self.linen is not None, "scenario has no linen line"
        return self.linen["id"]

    def attendant_headers(self) -> dict[str, str]:
        """`RoomAttendant` headers carrying the rostered attendant's own id."""
        return make_room_attendant_headers(self.worker_id)

    def supervisor_headers(self) -> dict[str, str]:
        """`Supervisor` headers carrying the credentialed inspector's own id."""
        return make_supervisor_headers(self.inspector_id)

    def room_id(self, room_number: str) -> str:
        assert room_number in self.rooms, (
            f"scenario has no room {room_number}; built {sorted(self.rooms)}"
        )
        return self.rooms[room_number]["id"]

    # -- assignment chaining ---------------------------------------------

    def assign_raw(
        self,
        room_number: str,
        service_type: str = SERVICE_CHECKOUT,
        expected_roster_version: Optional[int] = None,
        headers: Optional[dict[str, str]] = None,
        **overrides: Any,
    ):
        """POST a room assignment and return the raw response."""
        version = (
            self.roster_version
            if expected_roster_version is None
            else expected_roster_version
        )
        payload = f.assignment_payload(
            self.roster_id,
            self.room_id(room_number),
            version,
            service_type,
            **overrides,
        )
        return self.api.create_room_assignment(payload, headers or DIRECTOR_HEADERS)

    def assign(
        self,
        room_number: str,
        service_type: str = SERVICE_CHECKOUT,
        **overrides: Any,
    ) -> JsonDict:
        """Create an assignment, tracking the roster version it reports back."""
        data = get_success_data(self.assign_raw(room_number, service_type, **overrides))
        self._observe(data)
        self.assignments.append(data)
        return data

    def _observe(self, assignment: JsonDict) -> None:
        after = assignment.get("roster_version_after")
        if isinstance(after, int):
            self.roster_version = after

    def refresh_roster_version(self) -> int:
        """Re-read the roster and adopt its current `version`."""
        roster = read_roster(self.api, self.roster_id)
        self.roster = roster
        self.roster_version = roster["version"]
        return self.roster_version

    # -- cleaning ---------------------------------------------------------

    def start(
        self,
        assignment_id: str,
        started_at: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> JsonDict:
        data = get_success_data(
            self.api.start_assignment(
                assignment_id,
                f.start_payload(started_at),
                headers or self.attendant_headers(),
            )
        )
        self._observe(data)
        return data

    def complete(
        self,
        assignment_id: str,
        completed_at: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> JsonDict:
        data = get_success_data(
            self.api.complete_assignment(
                assignment_id,
                f.complete_payload(completed_at),
                headers or self.attendant_headers(),
            )
        )
        self._observe(data)
        return data

    def clean(
        self,
        room_number: str,
        service_type: str = SERVICE_CHECKOUT,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> JsonDict:
        """Create, start and complete one assignment; return the completed row."""
        created = self.assign(room_number, service_type)
        self.start(created["id"], started_at)
        return self.complete(created["id"], completed_at)

    # -- inspection -------------------------------------------------------

    def inspect_raw(self, assignment_id: str, headers: Optional[dict[str, str]] = None, **points: Any):
        return self.api.create_inspection(
            f.inspection_payload(assignment_id, **points),
            headers or self.supervisor_headers(),
        )

    def inspect(self, assignment_id: str, **points: Any) -> JsonDict:
        return get_success_data(self.inspect_raw(assignment_id, **points))

    # -- settlement -------------------------------------------------------

    def close_roster_raw(self, worked_minutes: int, break_minutes: int, headers=None):
        return self.api.close_roster(
            self.roster_id,
            f.roster_close_payload(worked_minutes, break_minutes),
            headers or DIRECTOR_HEADERS,
        )

    def close_roster(self, worked_minutes: int, break_minutes: int) -> JsonDict:
        data = get_success_data(self.close_roster_raw(worked_minutes, break_minutes))
        self.roster = data
        self.roster_version = data.get("version", self.roster_version)
        return data


# --------------------------------------------------------------------------
# The workhorse builder
# --------------------------------------------------------------------------

ROOM_TYPE_BUILDERS = {
    "KING": create_room_type,
    "SUITE": create_suite_room_type,
}


def _normalise_room_specs(rooms: Iterable[Any]) -> list[dict[str, Any]]:
    """Accept `"101"`, `("101", "SUITE")` or a full dict as a room spec."""
    normalised: list[dict[str, Any]] = []
    for spec in rooms:
        if isinstance(spec, str):
            normalised.append({"number": spec, "type": "KING"})
        elif isinstance(spec, (tuple, list)):
            number, type_code = spec[0], spec[1] if len(spec) > 1 else "KING"
            normalised.append({"number": number, "type": type_code})
        else:
            entry = dict(spec)
            entry.setdefault("type", "KING")
            normalised.append(entry)
    return normalised


def build_scenario(
    api: ApiClient,
    *,
    clock: Optional[str] = DEFAULT_CLOCK,
    property_overrides: Optional[JsonDict] = None,
    room_type_codes: Sequence[str] = ("KING",),
    room_type_overrides: Optional[dict[str, JsonDict]] = None,
    rooms: Iterable[Any] = (),
    linen: Optional[JsonDict] = None,
    forecast: Optional[JsonDict] = None,
    worker_overrides: Optional[JsonDict] = None,
    inspector_overrides: Optional[JsonDict] = None,
    with_worker: bool = True,
    with_inspector: bool = True,
    with_day: bool = True,
    publish: bool = True,
    with_roster: bool = True,
    clocked_in: bool = True,
) -> Scenario:
    """Build a property and as much of the shift chain as the caller asks for.

    The chain follows the order PRD 3 imposes: pin the logical clock, register
    the property, define its room types, add its rooms, open its linen line, hire
    its attendants, draft the forecast day, publish it, roster the worker and
    clock them in.
    """
    if clock is not None:
        set_clock(api, clock)

    prop = create_property(api, **(property_overrides or {}))
    scenario = Scenario(api=api, prop=prop)

    overrides_by_code = room_type_overrides or {}
    for code in room_type_codes:
        builder = ROOM_TYPE_BUILDERS[code]
        scenario.room_types[code] = builder(
            api, prop["id"], **overrides_by_code.get(code, {})
        )

    for spec in _normalise_room_specs(rooms):
        entry = dict(spec)
        number = entry.pop("number")
        type_code = entry.pop("type")
        scenario.rooms[number] = create_room(
            api, prop["id"], scenario.room_types[type_code]["id"], number, **entry
        )

    if linen is not None:
        scenario.linen = create_linen_item(api, prop["id"], **linen)

    if with_worker:
        scenario.worker = create_attendant(api, prop["id"], **(worker_overrides or {}))
    if with_inspector:
        scenario.inspector = create_inspector(
            api, prop["id"], **(inspector_overrides or {})
        )

    if with_day:
        scenario.day = create_forecast_day(api, prop["id"], **(forecast or {}))
        if publish:
            scenario.day = publish_day(api, scenario.day["id"])

    if with_roster:
        assert scenario.day is not None, "a roster needs a forecast day"
        assert scenario.worker is not None, "a roster needs an attendant"
        scenario.roster = create_roster(api, scenario.day["id"], scenario.worker["id"])
        scenario.roster_version = scenario.roster["version"]
        if clocked_in:
            scenario.roster = clock_in(
                api, scenario.roster["id"], scenario.worker["id"]
            )
            scenario.roster_version = scenario.roster["version"]

    return scenario


def build_second_property(
    api: ApiClient,
    *,
    name: str = "Seaside Inn",
    room_number: str = "901",
    room_overrides: Optional[JsonDict] = None,
    property_overrides: Optional[JsonDict] = None,
    with_attendant: bool = True,
) -> Scenario:
    """A second, independent property used by the scope-coherence scenarios."""
    prop = create_property(
        api, name=name, **(property_overrides or {})
    )
    scenario = Scenario(api=api, prop=prop)
    scenario.room_types["KING"] = create_room_type(api, prop["id"], code="KING")
    scenario.rooms[room_number] = create_room(
        api,
        prop["id"],
        scenario.room_types["KING"]["id"],
        room_number,
        **(room_overrides or {}),
    )
    if with_attendant:
        scenario.worker = create_attendant(api, prop["id"], employee_code="E-701")
    return scenario


# --------------------------------------------------------------------------
# Custody of guest property (PRD 3.9)
# --------------------------------------------------------------------------


@dataclass
class LostFoundContext:
    """A property, a room, an attendant and one recovered item."""

    api: ApiClient
    prop: JsonDict
    room: JsonDict
    finder: JsonDict
    supervisor: JsonDict
    item: JsonDict

    @property
    def item_id(self) -> str:
        return self.item["id"]

    def supervisor_headers(self) -> dict[str, str]:
        return make_supervisor_headers(self.supervisor["id"])

    def finder_headers(self) -> dict[str, str]:
        return make_room_attendant_headers(self.finder["id"])

    def store(self, storage_bin: str = "B-12", at: Optional[str] = None) -> JsonDict:
        """Bin the item, optionally moving the logical clock first."""
        if at is not None:
            set_clock(self.api, at)
        self.item = get_success_data(
            self.api.store_item(
                self.item_id, f.store_payload(storage_bin), self.supervisor_headers()
            )
        )
        return self.item

    def refresh(self) -> JsonDict:
        self.item = read_item(self.api, self.item_id)
        return self.item


def build_lost_found(
    api: ApiClient,
    *,
    clock: str = DEFAULT_CLOCK,
    category: str = CATEGORY_STANDARD,
    description: str = "Blue canvas tote bag left in the closet",
    stored: bool = False,
    storage_bin: str = "B-12",
    store_at: Optional[str] = None,
) -> LostFoundContext:
    """Log — and optionally bin — one recovered item at a fresh property."""
    set_clock(api, clock)
    prop = create_property(api)
    room_type = create_room_type(api, prop["id"])
    room = create_room(api, prop["id"], room_type["id"], "101")
    finder = create_attendant(api, prop["id"])
    supervisor = create_inspector(api, prop["id"])
    item = get_success_data(
        api.create_lost_found_item(
            f.lost_found_payload(
                prop["id"],
                room["id"],
                finder["id"],
                description=description,
                category=category,
            ),
            make_supervisor_headers(supervisor["id"]),
        )
    )
    context = LostFoundContext(
        api=api,
        prop=prop,
        room=room,
        finder=finder,
        supervisor=supervisor,
        item=item,
    )
    if stored:
        context.store(storage_bin=storage_bin, at=store_at)
    return context


# --------------------------------------------------------------------------
# Guest service programmes (PRD 3.9)
# --------------------------------------------------------------------------


@dataclass
class EnrollmentContext:
    api: ApiClient
    prop: JsonDict
    room: JsonDict
    enrollment: JsonDict

    @property
    def enrollment_id(self) -> str:
        return self.enrollment["id"]

    def accrue_raw(self, headers: Optional[dict[str, str]] = None):
        return self.api.accrue_enrollment(
            self.enrollment_id, None, headers or FRONT_DESK_HEADERS
        )

    def accrue(self) -> JsonDict:
        self.enrollment = get_success_data(self.accrue_raw())
        return self.enrollment

    def void(self) -> JsonDict:
        self.enrollment = get_success_data(
            self.api.void_enrollment(self.enrollment_id, None, FRONT_DESK_HEADERS)
        )
        return self.enrollment

    def refresh(self) -> JsonDict:
        self.enrollment = read_enrollment(self.api, self.enrollment_id)
        return self.enrollment


def build_enrollment(
    api: ApiClient,
    *,
    clock: str = DEFAULT_CLOCK,
    program: str = PROGRAM_OPT_OUT,
    nights: int = 2,
    room_overrides: Optional[JsonDict] = None,
    **enrollment_overrides: Any,
) -> EnrollmentContext:
    """Enrol one reservation on a freshly created room."""
    set_clock(api, clock)
    prop = create_property(api)
    room_type = create_room_type(api, prop["id"])
    room = create_room(
        api, prop["id"], room_type["id"], "101", **(room_overrides or {})
    )
    enrollment = get_success_data(
        api.create_service_enrollment(
            f.enrollment_payload(room["id"], program, nights, **enrollment_overrides),
            FRONT_DESK_HEADERS,
        )
    )
    return EnrollmentContext(api=api, prop=prop, room=room, enrollment=enrollment)


# --------------------------------------------------------------------------
# Linen and laundry (PRD 3.8)
# --------------------------------------------------------------------------


def dispatch_cycle(
    api: ApiClient,
    linen_item_id: str,
    batch_sets: int,
    dispatched_at: str,
    expected_return_at: str,
    expected_linen_item_version: int,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api.create_laundry_cycle(
            f.laundry_cycle_payload(
                linen_item_id,
                batch_sets,
                dispatched_at,
                expected_return_at,
                expected_linen_item_version,
                **overrides,
            ),
            LAUNDRY_LEAD_HEADERS,
        )
    )


def return_cycle(
    api: ApiClient,
    cycle_id: str,
    returned_at: Optional[str] = None,
    returned_sets: Optional[int] = None,
) -> JsonDict:
    return get_success_data(
        api.return_laundry_cycle(
            cycle_id,
            f.laundry_return_payload(returned_at, returned_sets),
            LAUNDRY_LEAD_HEADERS,
        )
    )


def void_cycle(api: ApiClient, cycle_id: str) -> JsonDict:
    return get_success_data(
        api.void_laundry_cycle(cycle_id, None, LAUNDRY_LEAD_HEADERS)
    )


# --------------------------------------------------------------------------
# Waivers (PRD 3.3)
# --------------------------------------------------------------------------


def request_waiver(
    api: ApiClient, roster_id: str, credits: float, supervisor_attendant_id: str
) -> JsonDict:
    return get_success_data(
        api.request_waiver(
            roster_id,
            f.waiver_request_payload(credits),
            make_supervisor_headers(supervisor_attendant_id),
        )
    )


def decide_waiver(api: ApiClient, roster_id: str, decision: str) -> JsonDict:
    return get_success_data(
        api.decide_waiver(
            roster_id, f.waiver_decision_payload(decision), COMPLIANCE_HEADERS
        )
    )
