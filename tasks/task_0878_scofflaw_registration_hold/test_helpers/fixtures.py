"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures. Every helper
builds its preconditions from scratch — the server DB is empty before each test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_owner_payload, create_vehicle_payload, create_hearing_officer_payload,
    create_tow_yard_payload, create_case_payload, create_violation_payload,
    create_dispute_payload, create_boot_tow_order_payload,
)
from .constants import DEFAULT_ISSUED_AT, DEFAULT_DUE_AT
from .test_users import TEST_USERS, make_owner_headers, make_enforcement_headers

ADMIN = TEST_USERS["platform_admin_headers"]
EO = TEST_USERS["enforcement_officer_headers"]
CLERK = TEST_USERS["hearing_clerk_headers"]
COLLECTIONS = TEST_USERS["collections_admin_headers"]


# ─── Primitive builders ────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_owner(**overrides) -> dict:
    return get_success_data(api_client.create_owner(create_owner_payload(**overrides), ADMIN))


def create_vehicle(owner_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(owner_id, **overrides), ADMIN))


def create_hearing_officer(**overrides) -> dict:
    return get_success_data(
        api_client.create_hearing_officer(create_hearing_officer_payload(**overrides), ADMIN))


def create_tow_yard(**overrides) -> dict:
    return get_success_data(
        api_client.create_tow_yard(create_tow_yard_payload(**overrides), ADMIN))


def open_case(vehicle_id: str) -> dict:
    return get_success_data(api_client.create_case(create_case_payload(vehicle_id), EO))


def file_violation(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_violation(case_id, create_violation_payload(**overrides), EO))


def get_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_case(case_id, headers or EO))


def case_version(case_id: str, headers=None) -> int:
    return get_case(case_id, headers)["version"]


def file_dispute(violation_id: str, owner_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_dispute(
        violation_id, create_dispute_payload(**overrides), make_owner_headers(owner_id)))


def schedule_dispute(dispute_id: str, officer_id: str, start: str, end: str) -> dict:
    payload = {"officer_id": officer_id, "scheduled_start": start, "scheduled_end": end}
    return get_success_data(api_client.schedule_dispute(dispute_id, payload, CLERK))


# ─── Tier 2/4: cases pre-loaded with violations ────────────────────────────

def setup_owner_vehicle_case(owner_overrides=None, vehicle_overrides=None):
    """Owner + Vehicle + freshly opened COMPLIANT case. Returns (owner, vehicle, case)."""
    owner = create_owner(**(owner_overrides or {}))
    vehicle = create_vehicle(owner["id"], **(vehicle_overrides or {}))
    case = open_case(vehicle["id"])
    return owner, vehicle, case


def setup_case_with_violations(count, fine_each, issued_at=DEFAULT_ISSUED_AT,
                               due_at=DEFAULT_DUE_AT, violation_type="METER_EXPIRED",
                               owner_overrides=None, vehicle_overrides=None):
    """Owner + Vehicle + case + `count` OUTSTANDING violations of `fine_each`.

    Returns (owner, vehicle, case, [violations]). The case's posture is whatever
    the balances imply after the last filing (fetched fresh, not returned here).
    """
    owner, vehicle, case = setup_owner_vehicle_case(owner_overrides, vehicle_overrides)
    violations = []
    for _ in range(count):
        violations.append(file_violation(
            case["id"], fine_amount_cents=fine_each, issued_at=issued_at,
            due_at=due_at, violation_type=violation_type))
    return owner, vehicle, case, violations


def setup_scofflaw_boot_eligible(fine_each=13000, count=5):
    """Case pushed to SCOFFLAW and boot-eligible (>= 5 OUTSTANDING).

    Default 5 x 13000 = collectible 65000 (>= 50000) with count 5 (>= 5).
    Returns (owner, vehicle, case, [violations]).
    """
    return setup_case_with_violations(count, fine_each)


def setup_scofflaw_tow_eligible(fine_each=25000, count=5):
    """Case pushed to SCOFFLAW and tow-eligible (collectible >= 100000).

    Default 5 x 25000 = collectible 125000. Returns (owner, vehicle, case, [violations]).
    """
    return setup_case_with_violations(count, fine_each)


# ─── Tier 3: enforcement-order lifecycle shortcuts ─────────────────────────

def dispatch_boot(case_id: str, dispatcher="eo-dispatch") -> dict:
    """Dispatch a BOOT order against a SCOFFLAW boot-eligible case (reads OCC version)."""
    ver = case_version(case_id)
    payload = create_boot_tow_order_payload(ver, action_type="BOOT")
    return get_success_data(api_client.create_boot_tow_order(
        case_id, payload, make_enforcement_headers(dispatcher)))


def dispatch_tow(case_id: str, tow_yard_id: str, stored_from: str, stored_until: str,
                 dispatcher="eo-dispatch") -> dict:
    """Dispatch a TOW order (reads OCC version)."""
    ver = case_version(case_id)
    payload = create_boot_tow_order_payload(
        ver, action_type="TOW", tow_yard_id=tow_yard_id,
        stored_from=stored_from, stored_until=stored_until)
    return get_success_data(api_client.create_boot_tow_order(
        case_id, payload, make_enforcement_headers(dispatcher)))


def apply_order(order_id: str, applier="eo-apply") -> dict:
    return get_success_data(api_client.apply_order(order_id, make_enforcement_headers(applier)))


def setup_applied_boot_order(fine_each=25000, count=5):
    """SCOFFLAW boot-eligible case with a BOOT order DISPATCHED then APPLIED.

    Returns (owner, vehicle, case, order).
    """
    owner, vehicle, case, _ = setup_scofflaw_boot_eligible(fine_each=fine_each, count=count)
    order = dispatch_boot(case["id"])
    order = apply_order(order["id"])
    return owner, vehicle, case, order


def setup_applied_tow_order(stored_from, stored_until, final_clock=None,
                            yard_capacity=5, fine_each=25000, count=5):
    """SCOFFLAW tow-eligible case with a TOW order DISPATCHED then APPLIED.

    If final_clock is given, the logical clock is advanced to it AFTER apply so
    release-fee storage accrual can be exercised.
    Returns (owner, vehicle, case, yard, order).
    """
    owner, vehicle, case, _ = setup_scofflaw_tow_eligible(fine_each=fine_each, count=count)
    yard = create_tow_yard(capacity=yard_capacity)
    order = dispatch_tow(case["id"], yard["id"], stored_from, stored_until)
    order = apply_order(order["id"])
    if final_clock:
        set_clock(final_clock)
    return owner, vehicle, case, yard, order


def setup_boot_and_tow_applied(final_clock, tow_stored_from, tow_stored_until):
    """Two cases: one with an APPLIED BOOT order, one with an APPLIED TOW order.

    The clock is advanced to final_clock before the TOW dispatch so tow storage
    accrues. Returns (boot_order, tow_order).
    """
    # BOOT case (5 x 25000 -> boot-eligible, count 5)
    _, _, boot_case, _ = setup_scofflaw_boot_eligible(fine_each=25000, count=5)
    boot_order = dispatch_boot(boot_case["id"])
    boot_order = apply_order(boot_order["id"])
    # TOW case (5 x 25000 -> collectible 125000, tow-eligible)
    _, _, tow_case, _ = setup_scofflaw_tow_eligible(fine_each=25000, count=5)
    yard = create_tow_yard(capacity=5)
    set_clock(final_clock)
    tow_order = dispatch_tow(tow_case["id"], yard["id"], tow_stored_from, tow_stored_until)
    tow_order = apply_order(tow_order["id"])
    return boot_order, tow_order


# ─── Dispute / hearing shortcuts ───────────────────────────────────────────

def setup_case_with_scheduled_dispute(fine=30000, officer_name="Hearing Officer",
                                      start="2026-05-20T09:00:00Z", end="2026-05-20T10:00:00Z"):
    """One OUTSTANDING violation -> disputed -> scheduled hearing.

    Returns (owner, vehicle, case, violation, officer, dispute).
    """
    owner, vehicle, case, violations = setup_case_with_violations(1, fine)
    violation = violations[0]
    officer = create_hearing_officer(full_name=officer_name)
    dispute = file_dispute(violation["id"], owner["id"])
    dispute = schedule_dispute(dispute["id"], officer["id"], start, end)
    return owner, vehicle, case, violation, officer, dispute
