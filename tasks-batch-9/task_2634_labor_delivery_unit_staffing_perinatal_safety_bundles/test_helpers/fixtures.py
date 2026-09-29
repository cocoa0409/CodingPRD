"""Composite setup helpers.

Every helper drives the public API only, uses the lenient setup validator so
failures surface as clear "Setup step failed" messages, and threads the acting
StaffMember identity into every ownership-gated or duty-segregated call.

The logical clock starts at 2026-08-01T00:00:00Z on a freshly launched server;
helpers that depend on a particular instant set it explicitly.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assessment_payload,
    create_bed_payload,
    create_booking_payload,
    create_cesarean_payload,
    create_encounter_payload,
    create_hemorrhage_activation_payload,
    create_hypertension_activation_payload,
    create_pass_payload,
    create_review_payload,
    create_snapshot_payload,
    create_staff_member_payload,
    create_unit_payload,
    submit_findings_payload,
    unique_suffix,
)
from .test_users import (
    TEST_USERS,
    make_access_coordinator_headers,
    make_anesthesia_lead_headers,
    make_bedside_nurse_headers,
    make_charge_nurse_headers,
    make_obstetrician_headers,
    make_safety_officer_headers,
)

# Officer-role calls that stand a unit up happen before any StaffMember exists,
# so they use the shared operator constant; every later officer call re-binds to
# a real StaffMember id through make_safety_officer_headers.
BOOTSTRAP_OFFICER_HEADERS = TEST_USERS["safety_officer_headers"]

DEFAULT_CREDENTIAL_EXPIRY = "2027-12-31T00:00:00Z"

# Default staff roster created by bootstrap_unit(): key -> creation payload
# overrides. Every member is credentialed well past any clock instant these
# helpers use.
DEFAULT_STAFF_SPECS = {
    "charge": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "bedside": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "bedside2": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "ob": {"staff_role": "OB_ATTENDING", "fetal_monitoring_cert_level": "ADVANCED"},
    "anesthesia": {"staff_role": "ANESTHESIOLOGIST", "fetal_monitoring_cert_level": "BASIC"},
    "officer": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "BASIC"},
    "tech": {
        "staff_role": "SURGICAL_TECH",
        "fetal_monitoring_cert_level": "BASIC",
        "or_circulating_qualified": True,
    },
    "neonatal": {"staff_role": "NEONATAL_RESUSCITATOR", "fetal_monitoring_cert_level": "BASIC"},
}


class World:
    """Everything a test needs about one freshly built unit."""

    def __init__(self, unit: dict):
        self.unit = unit
        self.beds: Dict[str, dict] = {}
        self.staff: Dict[str, dict] = {}

    # -- ids -------------------------------------------------------------
    @property
    def unit_id(self) -> str:
        return self.unit["id"]

    def bed(self, label: str) -> dict:
        return self.beds[label]

    def bed_id(self, label: str) -> str:
        return self.beds[label]["id"]

    def staff_id(self, key: str) -> str:
        return self.staff[key]["id"]

    # -- identity-bound headers -----------------------------------------
    @property
    def charge_headers(self) -> dict:
        return make_charge_nurse_headers(self.staff_id("charge"))

    @property
    def bedside_headers(self) -> dict:
        return make_bedside_nurse_headers(self.staff_id("bedside"))

    @property
    def ob_headers(self) -> dict:
        return make_obstetrician_headers(self.staff_id("ob"))

    @property
    def anesthesia_headers(self) -> dict:
        return make_anesthesia_lead_headers(self.staff_id("anesthesia"))

    @property
    def officer_headers(self) -> dict:
        return make_safety_officer_headers(self.staff_id("officer"))

    @property
    def access_headers(self) -> dict:
        return make_access_coordinator_headers()

    def charge_headers_for(self, key: str) -> dict:
        return make_charge_nurse_headers(self.staff_id(key))

    def bedside_headers_for(self, key: str) -> dict:
        return make_bedside_nurse_headers(self.staff_id(key))

    def ob_headers_for(self, key: str) -> dict:
        return make_obstetrician_headers(self.staff_id(key))

    def officer_headers_for(self, key: str) -> dict:
        return make_safety_officer_headers(self.staff_id(key))

    def anesthesia_headers_for(self, key: str) -> dict:
        return make_anesthesia_lead_headers(self.staff_id(key))

    # -- convenience re-reads -------------------------------------------
    def reload_unit(self) -> dict:
        self.unit = get_success_data(api_client.get_unit(self.unit_id, self.charge_headers))
        return self.unit

    def unit_version(self) -> int:
        return self.reload_unit()["version"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(current_utc: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock. Setting it changes no other state."""
    return get_success_data(
        api_client.set_clock(
            {"current_utc": current_utc}, headers or BOOTSTRAP_OFFICER_HEADERS
        )
    )


def read_clock(headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_clock(headers or BOOTSTRAP_OFFICER_HEADERS))


# ---------------------------------------------------------------------------
# Tier 2: unit / bed / staff hierarchy
# ---------------------------------------------------------------------------

def create_unit(**overrides) -> dict:
    return get_success_data(
        api_client.create_unit(create_unit_payload(**overrides), BOOTSTRAP_OFFICER_HEADERS)
    )


def create_bed(unit_id: str, bed_label: str, bed_type: str = "LDR") -> dict:
    return get_success_data(
        api_client.create_bed(
            unit_id,
            create_bed_payload(bed_label=bed_label, bed_type=bed_type),
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )


def create_staff_member(unit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff_member(
            unit_id, create_staff_member_payload(**overrides), BOOTSTRAP_OFFICER_HEADERS
        )
    )


def bootstrap_unit(
    clock: Optional[str] = None,
    ldr_beds: int = 4,
    or_rooms: int = 1,
    max_daily_induction_bed_minutes: int = 2880,
    bed_specs: Optional[List[tuple]] = None,
    staff_specs: Optional[Dict[str, dict]] = None,
    unit_overrides: Optional[dict] = None,
) -> World:
    """Create one unit with beds and a full staff roster.

    `bed_specs` is a list of (bed_label, bed_type); it defaults to LDR-01 plus
    OR-01. `staff_specs` maps a roster key to creation-payload overrides.
    The unit opens OPEN with a zero coverage deficit and NOT_READY readiness.
    """
    if clock is not None:
        set_clock(clock)
    unit = create_unit(
        licensed_ldr_beds=ldr_beds,
        licensed_or_rooms=or_rooms,
        max_daily_induction_bed_minutes=max_daily_induction_bed_minutes,
        **(unit_overrides or {}),
    )
    world = World(unit)
    for label, bed_type in (bed_specs if bed_specs is not None else [("LDR-01", "LDR"), ("OR-01", "OR")]):
        world.beds[label] = create_bed(world.unit_id, label, bed_type)
    for key, spec in (staff_specs if staff_specs is not None else DEFAULT_STAFF_SPECS).items():
        payload = dict(spec)
        payload.setdefault("credential_expires_at", DEFAULT_CREDENTIAL_EXPIRY)
        payload.setdefault("full_name", f"Test {key.title()} {unique_suffix()}")
        world.staff[key] = create_staff_member(world.unit_id, **payload)
    return world


def add_bed(world: World, bed_label: str, bed_type: str = "LDR") -> dict:
    world.beds[bed_label] = create_bed(world.unit_id, bed_label, bed_type)
    return world.beds[bed_label]


def add_staff(world: World, key: str, **overrides) -> dict:
    overrides.setdefault("credential_expires_at", DEFAULT_CREDENTIAL_EXPIRY)
    overrides.setdefault("full_name", f"Test {key.title()} {unique_suffix()}")
    world.staff[key] = create_staff_member(world.unit_id, **overrides)
    return world.staff[key]


# ---------------------------------------------------------------------------
# Tier 1: shift state progression
# ---------------------------------------------------------------------------

def create_shift(
    world: World,
    staff_key: str = "bedside",
    role_slot: str = "BEDSIDE",
    shift_start_utc: str = "2026-08-20T06:00:00Z",
    shift_end_utc: str = "2026-08-20T16:00:00Z",
    acting_key: str = "charge",
    staff_id: Optional[str] = None,
) -> dict:
    """Create a SCHEDULED shift. capacity_units_effective stays null until activation."""
    return get_success_data(
        api_client.create_shift(
            {
                "unit_id": world.unit_id,
                "staff_id": staff_id or world.staff_id(staff_key),
                "role_slot": role_slot,
                "shift_start_utc": shift_start_utc,
                "shift_end_utc": shift_end_utc,
            },
            world.charge_headers_for(acting_key),
        )
    )


def activate_shift(world: World, shift: dict, acting_key: str = "charge") -> dict:
    """Activate a shift, snapshotting capacity_units_effective."""
    return get_success_data(
        api_client.activate_shift(shift["id"], world.charge_headers_for(acting_key))
    )


def create_active_shift(
    world: World,
    staff_key: str = "bedside",
    role_slot: str = "BEDSIDE",
    shift_start_utc: str = "2026-08-20T06:00:00Z",
    shift_end_utc: str = "2026-08-20T16:00:00Z",
    acting_key: str = "charge",
) -> dict:
    """Create a shift and walk it SCHEDULED -> ACTIVE. Returns the ACTIVE shift."""
    shift = create_shift(
        world, staff_key, role_slot, shift_start_utc, shift_end_utc, acting_key
    )
    return activate_shift(world, shift, acting_key)


# ---------------------------------------------------------------------------
# Encounters and coverage
# ---------------------------------------------------------------------------

def create_encounter(world: World, acting_key: str = "charge", **overrides) -> dict:
    """Create a walk-in encounter (ANTEPARTUM / UNASSIGNED, admitted_at = clock_now)."""
    return get_success_data(
        api_client.create_encounter(
            create_encounter_payload(world.unit_id, **overrides),
            world.charge_headers_for(acting_key),
        )
    )


def reload_encounter(world: World, encounter_id: str) -> dict:
    return get_success_data(
        api_client.get_encounter(encounter_id, world.charge_headers)
    )


def create_care_assignment(
    world: World,
    encounter: dict,
    shift: dict,
    coverage_mode: str = "RATIO_SHARED",
    acting_key: str = "charge",
    expected_encounter_version: Optional[int] = None,
) -> dict:
    """Attach a shift to an encounter. The encounter version is re-read first so
    the optimistic-concurrency guard never masks the rule under test."""
    version = expected_encounter_version
    if version is None:
        version = reload_encounter(world, encounter["id"])["version"]
    return get_success_data(
        api_client.create_care_assignment(
            {
                "encounter_id": encounter["id"],
                "shift_assignment_id": shift["id"],
                "coverage_mode": coverage_mode,
                "expected_encounter_version": version,
            },
            world.charge_headers_for(acting_key),
        )
    )


def setup_covered_encounter(
    world: World,
    staff_key: str = "bedside",
    role_slot: str = "BEDSIDE",
    shift_start_utc: str = "2026-08-20T06:00:00Z",
    shift_end_utc: str = "2026-08-20T16:00:00Z",
    coverage_mode: str = "RATIO_SHARED",
    encounter_overrides: Optional[dict] = None,
) -> dict:
    """One ACTIVE shift covering one encounter.

    Returns {"shift": ..., "encounter": ..., "assignment": ...} with the
    encounter re-read after the assignment so its staffing_state is current.
    """
    shift = create_active_shift(world, staff_key, role_slot, shift_start_utc, shift_end_utc)
    encounter = create_encounter(world, **(encounter_overrides or {}))
    assignment = create_care_assignment(world, encounter, shift, coverage_mode)
    return {
        "shift": get_success_data(api_client.get_shift(shift["id"], world.charge_headers)),
        "encounter": reload_encounter(world, encounter["id"]),
        "assignment": assignment,
    }


def assign_bed(world: World, encounter: dict, bed_label: str, acting_key: str = "charge") -> dict:
    return get_success_data(
        api_client.assign_bed(
            encounter["id"],
            {"bed_id": world.bed_id(bed_label)},
            world.charge_headers_for(acting_key),
        )
    )


def advance_phase(
    world: World, encounter: dict, target_phase: str, acting_key: str = "charge", **extra
) -> dict:
    payload = {"target_phase": target_phase}
    payload.update(extra)
    return get_success_data(
        api_client.advance_phase(
            encounter["id"], payload, world.charge_headers_for(acting_key)
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: readiness drills
# ---------------------------------------------------------------------------

def setup_validated_drill(
    world: World,
    scheduled_for_utc: str,
    decision_at: str,
    incision_at: str,
    documented_key: str = "anesthesia",
    validator_key: str = "officer",
    participant_keys: Optional[List[str]] = None,
    document_clock: Optional[str] = None,
) -> dict:
    """Walk one drill SCHEDULED -> IN_PROGRESS -> DOCUMENTED -> VALIDATED.

    A validated drill in currency is what lifts cesarean_readiness_state off
    NOT_READY; the measured decision-to-incision interval decides whether the
    unit lands on DEGRADED or READY.
    """
    keys = participant_keys or ["ob", "anesthesia"]
    drill = get_success_data(
        api_client.create_drill(
            world.unit_id,
            {
                "drill_type": "DECISION_TO_INCISION",
                "scheduled_for_utc": scheduled_for_utc,
                "participant_staff_ids": [world.staff_id(k) for k in keys],
            },
            world.anesthesia_headers,
        )
    )
    get_success_data(api_client.start_drill(drill["id"], world.charge_headers))
    if document_clock:
        set_clock(document_clock)
    get_success_data(
        api_client.document_drill(
            drill["id"],
            {
                "decision_at": decision_at,
                "incision_at": incision_at,
                "documented_by_staff_id": world.staff_id(documented_key),
            },
            world.anesthesia_headers_for(documented_key),
        )
    )
    return get_success_data(
        api_client.validate_drill(drill["id"], world.officer_headers_for(validator_key))
    )


READINESS_DRILL_STAFF = {
    "ob": {"staff_role": "OB_ATTENDING", "fetal_monitoring_cert_level": "ADVANCED"},
    "anesthesia": {"staff_role": "ANESTHESIOLOGIST", "fetal_monitoring_cert_level": "BASIC"},
    "officer": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "BASIC"},
}

_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _spell(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_INSTANT_FORMAT)


def lift_unit_off_not_ready(world: World, now_utc: str) -> dict:
    """Validate one passing drill so the unit's readiness leaves `NOT_READY`.

    PRD 3.1 opens every unit at `NOT_READY` "because no drill has yet been
    validated", and PRD 3.3 freezes such a unit: "`INDUCTION_FROZEN` when ... or
    `cesarean_readiness_state` is `NOT_READY`". A unit that is meant to read
    `OPEN` or `RATIO_STRAINED`, or to take an induction hold, therefore needs a
    current validated drill first. The simulated interval is 20 minutes, inside
    the 30-minute pass window, and the drill is scheduled on the current instant
    itself, "the boundary instant counting as due".
    """
    for key, spec in READINESS_DRILL_STAFF.items():
        if key not in world.staff:
            add_staff(world, key, **dict(spec))
    now = _instant(now_utc)
    return setup_validated_drill(
        world,
        scheduled_for_utc=_spell(now),
        decision_at=_spell(now - timedelta(minutes=25)),
        incision_at=_spell(now - timedelta(minutes=5)),
    )


def setup_ready_unit_drill(world: World) -> dict:
    """A drill whose measured interval is comfortably inside the pass window."""
    return setup_validated_drill(
        world,
        scheduled_for_utc="2026-08-02T08:00:00Z",
        decision_at="2026-08-02T08:00:00Z",
        incision_at="2026-08-02T08:20:00Z",
    )


# ---------------------------------------------------------------------------
# Tier 2: bundle activations and checklist items
# ---------------------------------------------------------------------------

def activate_hemorrhage_bundle(world: World, encounter: dict, acting_key: str = "ob", **overrides) -> dict:
    return get_success_data(
        api_client.create_activation(
            create_hemorrhage_activation_payload(encounter["id"], **overrides),
            world.ob_headers_for(acting_key),
        )
    )


def activate_hypertension_bundle(world: World, encounter: dict, acting_key: str = "ob", **overrides) -> dict:
    return get_success_data(
        api_client.create_activation(
            create_hypertension_activation_payload(encounter["id"], **overrides),
            world.ob_headers_for(acting_key),
        )
    )


def checklist_items(world: World, activation: dict, acting_key: str = "ob") -> List[dict]:
    body = api_client.list_checklist_items(
        activation["id"], world.ob_headers_for(acting_key), params={"limit": 100}
    ).json()
    return body["data"]


def checklist_items_by_code(
    world: World, activation: dict, acting_key: str = "ob"
) -> Dict[str, dict]:
    return {
        item["step_code"]: item for item in checklist_items(world, activation, acting_key)
    }


def complete_item(
    world: World,
    activation: dict,
    item: dict,
    completed_at: str,
    performed_key: str = "bedside",
    performed_by_staff_id: Optional[str] = None,
    acting_key: str = "bedside",
) -> dict:
    staff_id = performed_by_staff_id or world.staff_id(performed_key)
    return get_success_data(
        api_client.complete_checklist_item(
            activation["id"],
            item["id"],
            {"completed_at": completed_at, "performed_by_staff_id": staff_id},
            world.bedside_headers_for(acting_key),
        )
    )


def reload_activation(world: World, activation_id: str, acting_key: str = "ob") -> dict:
    return get_success_data(
        api_client.get_activation(activation_id, world.ob_headers_for(acting_key))
    )


# ---------------------------------------------------------------------------
# Tier 2: fetal monitoring assessments
# ---------------------------------------------------------------------------

def create_assessment(
    world: World,
    encounter: dict,
    interpreted_key: str = "bedside",
    acting_key: str = "bedside",
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_assessment(
            create_assessment_payload(
                encounter["id"], world.staff_id(interpreted_key), **overrides
            ),
            world.bedside_headers_for(acting_key),
        )
    )


def escalate_assessment(
    world: World,
    assessment: dict,
    target_tier: int,
    notified_key: Optional[str] = "ob",
    acting_key: str = "bedside",
) -> dict:
    payload: dict = {"target_tier": target_tier}
    if notified_key is not None:
        payload["notified_staff_id"] = world.staff_id(notified_key)
    return get_success_data(
        api_client.escalate_assessment(
            assessment["id"], payload, world.bedside_headers_for(acting_key)
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: emergency cesareans
# ---------------------------------------------------------------------------

def declare_cesarean(
    world: World, encounter: dict, urgency_class: str = "CATEGORY_2_URGENT", acting_key: str = "ob", **overrides
) -> dict:
    payload = create_cesarean_payload(
        encounter["id"], urgency_class=urgency_class, **overrides
    )
    return get_success_data(
        api_client.create_cesarean(payload, world.ob_headers_for(acting_key))
    )


def mobilize_cesarean(
    world: World,
    event: dict,
    or_bed_label: str = "OR-01",
    staff_keys: Optional[List[str]] = None,
    acting_key: str = "ob",
) -> dict:
    keys = staff_keys or ["ob", "anesthesia", "tech"]
    return get_success_data(
        api_client.mobilize_team(
            event["id"],
            {
                "or_bed_id": world.bed_id(or_bed_label),
                "staff_ids": [world.staff_id(k) for k in keys],
            },
            world.ob_headers_for(acting_key),
        )
    )


def reload_cesarean(world: World, event_id: str) -> dict:
    return get_success_data(api_client.get_cesarean(event_id, world.ob_headers))


# ---------------------------------------------------------------------------
# Tier 3: induction bookings
# ---------------------------------------------------------------------------

def create_booking(world: World, acting_key: str = "access", **overrides) -> dict:
    headers = (
        world.access_headers
        if acting_key == "access"
        else world.ob_headers_for(acting_key)
    )
    return get_success_data(
        api_client.create_booking(
            create_booking_payload(world.unit_id, **overrides), headers
        )
    )


def hold_booking(
    world: World,
    booking: dict,
    bed_label: str = "LDR-01",
    bed_id: Optional[str] = None,
    expected_unit_version: Optional[int] = None,
) -> dict:
    """Place a capacity hold. The unit version is re-read so the optimistic
    concurrency guard never fires by accident."""
    version = expected_unit_version
    if version is None:
        version = world.unit_version()
    return get_success_data(
        api_client.hold_capacity(
            booking["id"],
            {
                "bed_id": bed_id or world.bed_id(bed_label),
                "expected_unit_version": version,
            },
            world.access_headers,
        )
    )


def confirm_booking(world: World, booking: dict, acting_key: str = "ob") -> dict:
    return get_success_data(
        api_client.confirm_booking(booking["id"], world.ob_headers_for(acting_key))
    )


def held_booking(world: World, bed_label: str = "LDR-01", **overrides) -> dict:
    booking = create_booking(world, **overrides)
    return hold_booking(world, booking, bed_label)


def confirmed_booking(world: World, bed_label: str = "LDR-01", **overrides) -> dict:
    booking = create_booking(world, **overrides)
    hold_booking(world, booking, bed_label)
    return confirm_booking(world, booking)


def reload_booking(world: World, booking_id: str) -> dict:
    return get_success_data(api_client.get_booking(booking_id, world.access_headers))


# ---------------------------------------------------------------------------
# Tier 3: newborn complication reviews
# ---------------------------------------------------------------------------

def create_review(
    world: World, encounter: dict, facilitator_key: str = "neonatal", acting_key: str = "charge", **overrides
) -> dict:
    return get_success_data(
        api_client.create_review(
            create_review_payload(
                encounter["id"], world.staff_id(facilitator_key), **overrides
            ),
            world.charge_headers_for(acting_key),
        )
    )


def schedule_debrief(world: World, review: dict, debrief_scheduled_for_utc: str, acting_key: str = "charge") -> dict:
    return get_success_data(
        api_client.schedule_debrief(
            review["id"],
            {"debrief_scheduled_for_utc": debrief_scheduled_for_utc},
            world.charge_headers_for(acting_key),
        )
    )


def submit_findings(world: World, review: dict, acting_key: str = "charge", **overrides) -> dict:
    return get_success_data(
        api_client.submit_findings(
            review["id"], submit_findings_payload(**overrides), world.charge_headers_for(acting_key)
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: support person passes
# ---------------------------------------------------------------------------

def create_pass(world: World, encounter: dict, acting_key: str = "access", **overrides) -> dict:
    headers = (
        world.access_headers
        if acting_key == "access"
        else world.charge_headers_for(acting_key)
    )
    return get_success_data(
        api_client.create_pass(create_pass_payload(encounter["id"], **overrides), headers)
    )


def check_in_pass(world: World, support_pass: dict) -> dict:
    return get_success_data(
        api_client.check_in_pass(support_pass["id"], world.access_headers)
    )


def reload_pass(world: World, pass_id: str) -> dict:
    return get_success_data(api_client.get_pass(pass_id, world.access_headers))


# ---------------------------------------------------------------------------
# Tier 4: snapshots, sweeps and derived reports
# ---------------------------------------------------------------------------

def create_snapshot(
    world: World,
    period_start_utc: str,
    period_end_utc: str,
    acting_key: str = "officer",
    expected_unit_version: Optional[int] = None,
    **overrides,
) -> dict:
    version = expected_unit_version
    if version is None:
        version = world.unit_version()
    payload = create_snapshot_payload(
        period_start_utc,
        period_end_utc,
        expected_unit_version=version,
        **overrides,
    )
    return get_success_data(
        api_client.create_snapshot(
            world.unit_id, payload, world.officer_headers_for(acting_key)
        )
    )


def certify_snapshot(world: World, snapshot: dict, acting_key: str = "officer") -> dict:
    return get_success_data(
        api_client.certify_snapshot(
            snapshot["id"], world.officer_headers_for(acting_key)
        )
    )


def capacity_summary(world: World, params: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_capacity_summary(world.unit_id, world.charge_headers, params=params)
    )


def coverage_report(world: World) -> dict:
    return get_success_data(
        api_client.get_coverage_report(world.unit_id, world.charge_headers)
    )


def readiness_report(world: World) -> dict:
    return get_success_data(
        api_client.get_readiness_report(world.unit_id, world.charge_headers)
    )


def capacity_sweep(world: World, acting_key: str = "charge") -> dict:
    return get_success_data(
        api_client.capacity_sweep(world.unit_id, world.charge_headers_for(acting_key))
    )


def coverage_summary(world: World, encounter: dict) -> dict:
    return get_success_data(
        api_client.get_encounter_coverage_summary(encounter["id"], world.charge_headers)
    )


def timeliness_report(world: World, activation: dict) -> dict:
    return get_success_data(
        api_client.get_timeliness_report(activation["id"], world.ob_headers)
    )
