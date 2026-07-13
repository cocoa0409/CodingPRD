"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors, not confusing assertion failures. Every fixture
builds its preconditions from scratch using only PRD-declared endpoints, since
the server restarts (empty database) before every individual test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_hazard_plan_payload,
    create_pod_payload,
    create_staff_member_payload,
    create_shift_assignment_payload,
    create_countermeasure_payload,
    create_inventory_lot_payload,
    create_allocation_request_payload,
    create_dispensing_event_payload,
    create_drill_payload,
    create_situation_report_payload,
)
from .test_users import TEST_USERS, make_volunteer_headers

ADMIN = TEST_USERS["public_health_admin_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
PARTNER = TEST_USERS["mutual_aid_partner_headers"]
CLINICAL = TEST_USERS["clinical_lead_headers"]
VOLUNTEER = TEST_USERS["volunteer_headers"]


# ─── Tier 1: State Progression ─────────────────────────────────────────────

def create_hazard_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_hazard_plan(create_hazard_plan_payload(**overrides), ADMIN)
    )


def activate_hazard_plan(hazard_plan_id: str) -> dict:
    return get_success_data(api_client.activate_hazard_plan(hazard_plan_id, ADMIN))


def create_activated_hazard_plan(**overrides) -> dict:
    """Create HazardPlan + transition DRAFT -> ACTIVATED. Returns activated entity."""
    hp = create_hazard_plan(**overrides)
    return activate_hazard_plan(hp["id"])


def create_pod(hazard_plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_pod(create_pod_payload(hazard_plan_id, **overrides), ADMIN)
    )


def open_pod(pod_id: str) -> dict:
    return get_success_data(api_client.open_pod(pod_id, ADMIN))


def create_open_pod(hazard_plan_id: str, **overrides) -> dict:
    """Create POD + transition STAGING -> OPERATIONAL. Returns opened POD."""
    pod = create_pod(hazard_plan_id, **overrides)
    return open_pod(pod["id"])


def restrict_pod(pod_id: str) -> dict:
    return get_success_data(api_client.restrict_pod(pod_id, ADMIN))


def resume_pod(pod_id: str) -> dict:
    return get_success_data(api_client.resume_pod(pod_id, ADMIN))


def close_pod(pod_id: str) -> dict:
    return get_success_data(api_client.close_pod(pod_id, ADMIN))


def get_pod_version(pod_id: str) -> int:
    return get_success_data(api_client.get_pod(pod_id, ADMIN))["version"]


def create_verified_staff_member(**overrides) -> dict:
    """Create StaffMember + transition PENDING -> VERIFIED. Returns verified entity."""
    staff = get_success_data(
        api_client.create_staff_member(create_staff_member_payload(**overrides), ADMIN)
    )
    return get_success_data(api_client.verify_staff_credential(staff["id"], ADMIN))


def create_unverified_staff_member(**overrides) -> dict:
    return get_success_data(
        api_client.create_staff_member(create_staff_member_payload(**overrides), ADMIN)
    )


# ─── Tier 2: Entity Hierarchy ───────────────────────────────────────────────

def setup_activated_plan_with_open_pod(hazard_plan_overrides=None, pod_overrides=None):
    """Active HazardPlan + one OPERATIONAL POD under it. Returns (hazard_plan, pod)."""
    hp = create_activated_hazard_plan(**(hazard_plan_overrides or {}))
    pod = create_open_pod(hp["id"], **(pod_overrides or {}))
    return hp, pod


def create_countermeasure(**overrides) -> dict:
    return get_success_data(
        api_client.create_countermeasure(create_countermeasure_payload(**overrides), ADMIN)
    )


def create_central_inventory_lot(countermeasure_id: str, **overrides) -> dict:
    """Create a central SNS-cache InventoryLot (pod_id omitted/null)."""
    payload = create_inventory_lot_payload(countermeasure_id, pod_id=None, **overrides)
    return get_success_data(api_client.create_inventory_lot(payload, LOGISTICS))


def create_pod_inventory_lot(countermeasure_id: str, pod_id: str, **overrides) -> dict:
    """Create a POD-scoped InventoryLot."""
    payload = create_inventory_lot_payload(countermeasure_id, pod_id=pod_id, **overrides)
    return get_success_data(api_client.create_inventory_lot(payload, LOGISTICS))


def get_lot_version(lot_id: str) -> int:
    return get_success_data(api_client.get_inventory_lot(lot_id, LOGISTICS))["version"]


def setup_pod_with_countermeasure_and_lot(
    doses_required=1, reorder_point_quantity=10, on_hand_quantity=100, lot_scoped_to_pod=True,
    hazard_plan_overrides=None, pod_overrides=None, countermeasure_overrides=None, lot_overrides=None,
):
    """Active HazardPlan + open POD + Countermeasure + one InventoryLot for it.
    Returns (hazard_plan, pod, countermeasure, lot)."""
    hp, pod = setup_activated_plan_with_open_pod(hazard_plan_overrides, pod_overrides)
    cm = create_countermeasure(
        doses_required=doses_required,
        reorder_point_quantity=reorder_point_quantity,
        **(countermeasure_overrides or {}),
    )
    if lot_scoped_to_pod:
        lot = create_pod_inventory_lot(
            cm["id"], pod["id"], on_hand_quantity=on_hand_quantity, **(lot_overrides or {})
        )
    else:
        lot = create_central_inventory_lot(
            cm["id"], on_hand_quantity=on_hand_quantity, **(lot_overrides or {})
        )
    return hp, pod, cm, lot


# ─── Tier 3: Full Lifecycle Shortcuts (ShiftAssignment) ────────────────────

def create_shift_assignment(pod_id: str, staff_member_id: str, headers=None, **overrides) -> dict:
    payload = create_shift_assignment_payload(pod_id, staff_member_id, **overrides)
    return get_success_data(api_client.create_shift_assignment(payload, headers or ADMIN))


def confirm_shift_assignment(shift_assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.confirm_shift_assignment(shift_assignment_id, headers or CLINICAL)
    )


def create_confirmed_shift_assignment(pod_id: str, staff_member_id: str, **overrides) -> dict:
    """Create ShiftAssignment + confirm. Returns CONFIRMED assignment."""
    shift = create_shift_assignment(pod_id, staff_member_id, **overrides)
    return confirm_shift_assignment(shift["id"])


def check_in_shift_assignment(shift_assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.check_in_shift_assignment(shift_assignment_id, headers or CLINICAL)
    )


def create_checked_in_shift_assignment(pod_id: str, staff_member_id: str, **overrides) -> dict:
    """Create -> confirm -> check_in. Returns CHECKED_IN assignment."""
    confirmed = create_confirmed_shift_assignment(pod_id, staff_member_id, **overrides)
    return check_in_shift_assignment(confirmed["id"])


def cancel_shift_assignment(shift_assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.cancel_shift_assignment(shift_assignment_id, headers or ADMIN)
    )


# ─── Tier 3: Full Lifecycle Shortcuts (DispensingEvent) ────────────────────

def create_dispensing_event(pod_id: str, countermeasure_id: str, headers=None, **overrides) -> dict:
    payload = create_dispensing_event_payload(pod_id, countermeasure_id, **overrides)
    return get_success_data(api_client.create_dispensing_event(payload, headers or CLINICAL))


def screen_dispensing_event(dispensing_event_id: str, screened_by_staff_member_id: str) -> dict:
    return get_success_data(
        api_client.screen_dispensing_event(
            dispensing_event_id,
            {"screened_by_staff_member_id": screened_by_staff_member_id},
            CLINICAL,
        )
    )


def create_screened_dispensing_event(
    pod_id: str, countermeasure_id: str, screened_by_staff_member_id: str, **overrides
) -> dict:
    """Create -> screen. Returns SCREENED event."""
    de = create_dispensing_event(pod_id, countermeasure_id, **overrides)
    return screen_dispensing_event(de["id"], screened_by_staff_member_id)


def defer_dispensing_event(dispensing_event_id: str, deferral_reason: str) -> dict:
    return get_success_data(
        api_client.defer_dispensing_event(
            dispensing_event_id, {"deferral_reason": deferral_reason}, CLINICAL
        )
    )


def create_deferred_dispensing_event(
    pod_id: str, countermeasure_id: str, screened_by_staff_member_id: str,
    deferral_reason="Registrant needs physician clearance", **overrides
) -> dict:
    """Create -> screen -> defer. Returns DEFERRED event."""
    screened = create_screened_dispensing_event(
        pod_id, countermeasure_id, screened_by_staff_member_id, **overrides
    )
    return defer_dispensing_event(screened["id"], deferral_reason)


def rescreen_dispensing_event(dispensing_event_id: str) -> dict:
    return get_success_data(api_client.rescreen_dispensing_event(dispensing_event_id, CLINICAL))


def dispense_dispensing_event(dispensing_event_id: str, dispensed_by_staff_member_id: str) -> dict:
    return get_success_data(
        api_client.dispense_dispensing_event(
            dispensing_event_id,
            {"dispensed_by_staff_member_id": dispensed_by_staff_member_id},
            CLINICAL,
        )
    )


def create_dispensed_dispensing_event(
    pod_id: str, countermeasure_id: str, staff_member_id: str, **overrides
) -> dict:
    """Create -> screen -> dispense. Requires a POD-scoped InventoryLot with
    sufficient available_quantity to already exist. Returns DISPENSED event."""
    screened = create_screened_dispensing_event(pod_id, countermeasure_id, staff_member_id, **overrides)
    return dispense_dispensing_event(screened["id"], staff_member_id)


def setup_dispensing_events_mixed_states(
    pod_id: str, countermeasure_id: str, staff_member_id: str,
    registered=0, screened=0, deferred=0, dispensed=0, dose_count=1,
):
    """Create N DispensingEvent rows landing in each requested terminal/non-terminal
    status. Returns dict of lists keyed by status name."""
    result = {"registered": [], "screened": [], "deferred": [], "dispensed": []}
    for _ in range(registered):
        result["registered"].append(
            create_dispensing_event(pod_id, countermeasure_id, dose_count=dose_count)
        )
    for _ in range(screened):
        result["screened"].append(
            create_screened_dispensing_event(pod_id, countermeasure_id, staff_member_id, dose_count=dose_count)
        )
    for _ in range(deferred):
        result["deferred"].append(
            create_deferred_dispensing_event(pod_id, countermeasure_id, staff_member_id, dose_count=dose_count)
        )
    for _ in range(dispensed):
        result["dispensed"].append(
            create_dispensed_dispensing_event(pod_id, countermeasure_id, staff_member_id, dose_count=dose_count)
        )
    return result


# ─── Tier 3: Full Lifecycle Shortcuts (AllocationRequest) ──────────────────

def create_allocation_request(pod_id: str, countermeasure_id: str, expected_pod_version=None, **overrides) -> dict:
    if expected_pod_version is None:
        expected_pod_version = get_pod_version(pod_id)
    payload = create_allocation_request_payload(
        pod_id, countermeasure_id, expected_pod_version, **overrides
    )
    return get_success_data(api_client.create_allocation_request(payload, LOGISTICS))


def reserve_allocation_request(allocation_request_id: str, source_lot_id: str, headers=None) -> dict:
    expected_version = get_lot_version(source_lot_id)
    return get_success_data(
        api_client.reserve_allocation_request(
            allocation_request_id,
            {"expected_inventory_lot_version": expected_version},
            headers or LOGISTICS,
        )
    )


def deny_allocation_request(allocation_request_id: str, headers=None) -> dict:
    return get_success_data(api_client.deny_allocation_request(allocation_request_id, headers or LOGISTICS))


def fulfill_allocation_request(allocation_request_id: str, headers=None) -> dict:
    return get_success_data(api_client.fulfill_allocation_request(allocation_request_id, headers or LOGISTICS))


def cancel_allocation_request(allocation_request_id: str, headers=None) -> dict:
    return get_success_data(api_client.cancel_allocation_request(allocation_request_id, headers or LOGISTICS))


def create_reserved_sns_allocation_request(
    pod_id: str, countermeasure_id: str, source_lot_id: str, requested_quantity: int, **overrides
) -> dict:
    """Create SNS_CACHE AllocationRequest -> reserve. Returns RESERVED request."""
    ar = create_allocation_request(
        pod_id, countermeasure_id, source_type="SNS_CACHE",
        requested_quantity=requested_quantity, **overrides,
    )
    return reserve_allocation_request(ar["id"], source_lot_id, LOGISTICS)


def create_reserved_mutual_aid_allocation_request(
    pod_id: str, countermeasure_id: str, partner_pod_id: str, source_lot_id: str,
    requested_quantity: int, **overrides
) -> dict:
    """Create MUTUAL_AID AllocationRequest -> reserve (as MutualAidPartner). Returns RESERVED request."""
    ar = create_allocation_request(
        pod_id, countermeasure_id, source_type="MUTUAL_AID", partner_pod_id=partner_pod_id,
        requested_quantity=requested_quantity, **overrides,
    )
    return reserve_allocation_request(ar["id"], source_lot_id, PARTNER)


def create_fulfilled_sns_allocation_request(
    pod_id: str, countermeasure_id: str, source_lot_id: str, requested_quantity: int, **overrides
) -> dict:
    reserved = create_reserved_sns_allocation_request(
        pod_id, countermeasure_id, source_lot_id, requested_quantity, **overrides
    )
    return fulfill_allocation_request(reserved["id"])


def create_fulfilled_mutual_aid_allocation_request(
    pod_id: str, countermeasure_id: str, partner_pod_id: str, source_lot_id: str,
    requested_quantity: int, **overrides
) -> dict:
    reserved = create_reserved_mutual_aid_allocation_request(
        pod_id, countermeasure_id, partner_pod_id, source_lot_id, requested_quantity, **overrides
    )
    return fulfill_allocation_request(reserved["id"])


# ─── Tier 4: Accumulation / Threshold Targeting ────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server's logical clock (PRD §2.5). PublicHealthAdmin-only."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def setup_pod_with_staffed_lanes(
    hazard_plan_overrides=None,
    pod_overrides=None,
    checked_in_count=0,
    confirmed_only_count=0,
    shift_window=("2026-03-02T08:00:00Z", "2026-03-02T16:00:00Z"),
    clock="2026-03-02T10:00:00Z",
    assigned_role="VACCINATOR",
):
    """Active HazardPlan + open POD, clock set inside shift_window, with
    `checked_in_count` staff CHECKED_IN and `confirmed_only_count` additional
    staff CONFIRMED (not checked in) on identical [start,end) windows.
    Returns (hazard_plan, pod)."""
    hp, pod = setup_activated_plan_with_open_pod(hazard_plan_overrides, pod_overrides)
    set_clock(clock)
    start_time, end_time = shift_window
    for _ in range(checked_in_count):
        staff = create_verified_staff_member(primary_role=assigned_role)
        create_checked_in_shift_assignment(
            pod["id"], staff["id"], assigned_role=assigned_role,
            start_time=start_time, end_time=end_time,
        )
    for _ in range(confirmed_only_count):
        staff = create_verified_staff_member(primary_role=assigned_role)
        create_confirmed_shift_assignment(
            pod["id"], staff["id"], assigned_role=assigned_role,
            start_time=start_time, end_time=end_time,
        )
    return hp, pod


# ─── Tier 5: Drills / HazardPlan Readiness ─────────────────────────────────

def create_drill(hazard_plan_id: str, **overrides) -> dict:
    payload = create_drill_payload(hazard_plan_id, **overrides)
    return get_success_data(api_client.create_drill(payload, ADMIN))


def complete_drill(drill_id: str, **payload_overrides) -> dict:
    return get_success_data(api_client.complete_drill(drill_id, payload_overrides, ADMIN))


def cancel_drill(drill_id: str) -> dict:
    return get_success_data(api_client.cancel_drill(drill_id, ADMIN))


def close_drill_corrective_action(drill_id: str) -> dict:
    return get_success_data(api_client.close_drill_corrective_action(drill_id, ADMIN))


def create_situation_report(hazard_plan_id: str, **overrides) -> dict:
    payload = create_situation_report_payload(hazard_plan_id, **overrides)
    return get_success_data(api_client.create_situation_report(payload, ADMIN))
