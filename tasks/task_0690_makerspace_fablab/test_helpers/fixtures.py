"""Composite setup helpers.

The test harness restarts the API server before EVERY test, so each fixture
builds all of its preconditions from scratch using only PRD-declared endpoints.
Fixtures use get_success_data() (lenient) internally so setup failures surface as
clear "Setup failed" errors.

Identity threading: Member and StaffInstructor are entity-backed roles. After a
fixture creates a Member, any ownership-gated call uses make_member_headers(id)
/ make_staff_headers(id) with that member's real id — never the shared fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as _api
from .factories import (
    create_tier_payload,
    create_member_payload,
    create_machine_payload,
    create_certification_payload,
    create_reservation_payload,
    create_locker_payload,
    create_material_item_payload,
    create_material_purchase_payload,
    create_workshop_payload,
    create_enrollment_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_staff_headers,
    make_facility_admin_headers,
)

ADMIN = TEST_USERS["facility_admin_headers"]
STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Advance the server logical clock to the given instant."""
    return get_success_data(_api.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: configuration + member-state progression
# ---------------------------------------------------------------------------
def create_tier(**overrides) -> dict:
    """Create a MembershipTier as FacilityAdmin."""
    return get_success_data(_api.create_tier(create_tier_payload(**overrides), ADMIN))


def create_machine(**overrides) -> dict:
    """Create a Machine as FacilityAdmin."""
    return get_success_data(_api.create_machine(create_machine_payload(**overrides), ADMIN))


def create_material_item(**overrides) -> dict:
    """Create a MaterialItem as FacilityAdmin."""
    return get_success_data(
        _api.create_material_item(create_material_item_payload(**overrides), ADMIN)
    )


def register_member(tier_id, **overrides) -> dict:
    """Register a member (PENDING_WAIVER). Returns the member record."""
    return get_success_data(
        _api.create_member(create_member_payload(tier_id, **overrides), ADMIN)
    )


def create_active_member(tier_overrides=None, topup_cents=10000, **member_overrides) -> dict:
    """Create a tier + member, sign waiver, top up wallet, and activate.

    Returns the activated Member record (subscription_status == ACTIVE).
    """
    tier = create_tier(**(tier_overrides or {}))
    return _activate_member_on_tier(tier, topup_cents, **member_overrides)


def create_active_member_on_tier(tier, topup_cents=10000, **member_overrides) -> dict:
    """Same as create_active_member but against an already-created tier."""
    return _activate_member_on_tier(tier, topup_cents, **member_overrides)


def _activate_member_on_tier(tier, topup_cents, **member_overrides) -> dict:
    member = register_member(tier["id"], **member_overrides)
    mh = make_member_headers(member["id"])
    get_success_data(_api.sign_waiver(member["id"], mh))
    if topup_cents:
        get_success_data(_api.topup(member["id"], topup_cents, mh))
    return get_success_data(_api.activate_member(member["id"], mh))


def create_certification_for(member_id, machine_class="LASER", **overrides) -> dict:
    """Grant an ACTIVE certification (StaffInstructor path)."""
    return get_success_data(
        _api.create_certification(
            create_certification_payload(member_id, machine_class, **overrides),
            make_staff_headers(member_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2/3: reservation lifecycle
# ---------------------------------------------------------------------------
def setup_member_machine_cert(
    machine_class="LASER",
    tier_overrides=None,
    machine_overrides=None,
    cert_overrides=None,
    topup_cents=20000,
):
    """Active member + a machine + an ACTIVE certification on that machine_class.

    Returns (member, machine, certification). The member is ACTIVE, waiver-signed,
    and topped up. Use the returned member id for ownership-gated headers.
    """
    member = create_active_member(tier_overrides=tier_overrides, topup_cents=topup_cents)
    mo = {"machine_class": machine_class}
    mo.update(machine_overrides or {})
    machine = create_machine(**mo)
    cert = create_certification_for(member["id"], machine_class, **(cert_overrides or {}))
    return member, machine, cert


def create_held_reservation(
    member, machine, cert, start_at, end_at, supervision_mode="SUPERVISED"
) -> dict:
    """Create a HELD reservation referencing the given cert. Returns the reservation."""
    payload = create_reservation_payload(
        member["id"],
        machine["id"],
        start_at,
        end_at,
        supervision_mode=supervision_mode,
        certification_id=cert["id"] if cert else None,
    )
    if cert is None:
        payload.pop("certification_id", None)
    return get_success_data(
        _api.create_reservation(payload, make_member_headers(member["id"]))
    )


def current_member_version(member_id) -> int:
    """Read the member's current version (for OCC tokens)."""
    data = get_success_data(_api.get_member(member_id, make_member_headers(member_id)))
    return data["version"]


def confirm_reservation(reservation_id, member_id) -> dict:
    """Confirm a HELD reservation using the member's current version. Returns reservation."""
    v = current_member_version(member_id)
    return get_success_data(
        _api.confirm_reservation(reservation_id, v, make_member_headers(member_id))
    )


def setup_confirmed_reservation(
    machine_class="LASER",
    tier_overrides=None,
    machine_overrides=None,
    cert_overrides=None,
    topup_cents=20000,
    start_at="2026-04-10T10:00:00Z",
    end_at="2026-04-10T11:00:00Z",
    supervision_mode="SUPERVISED",
):
    """Full chain to a CONFIRMED reservation (HOLD_PLACED).

    Returns (member, machine, cert, reservation). The reservation is CONFIRMED;
    the member's wallet has been debited by the forward estimate.
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class=machine_class,
        tier_overrides=tier_overrides,
        machine_overrides=machine_overrides,
        cert_overrides=cert_overrides,
        topup_cents=topup_cents,
    )
    res = create_held_reservation(member, machine, cert, start_at, end_at, supervision_mode)
    res = confirm_reservation(res["id"], member["id"])
    return member, machine, cert, res


# ---------------------------------------------------------------------------
# Workshop lifecycle
# ---------------------------------------------------------------------------
def create_instructor(tier=None) -> dict:
    """Create a member to act as a workshop instructor (StaffInstructor)."""
    tier = tier or create_tier()
    return register_member(tier["id"])


def setup_workshop(
    instructor_id=None,
    tier=None,
    capacity=5,
    machine_class=None,
    starts_at="2026-05-25T09:00:00Z",
    title="Test Workshop",
):
    """Create an OPEN workshop. Returns (instructor, workshop)."""
    tier = tier or create_tier()
    if instructor_id is None:
        instructor = register_member(tier["id"])
        instructor_id = instructor["id"]
    else:
        instructor = {"id": instructor_id}
    overrides = {"title": title, "capacity": capacity}
    if machine_class is not None:
        overrides["machine_class"] = machine_class
    ws = get_success_data(
        _api.create_workshop(
            create_workshop_payload(instructor_id, starts_at, **overrides),
            make_staff_headers(instructor_id),
        )
    )
    return instructor, ws


def enroll_member(workshop_id, member_id) -> dict:
    """Enroll a member in a workshop. Returns the enrollment."""
    return get_success_data(
        _api.create_enrollment(
            create_enrollment_payload(workshop_id, member_id),
            make_member_headers(member_id),
        )
    )


def setup_running_workshop_with_enrollment(
    capacity=3, machine_class=None, starts_at="2026-04-05T09:00:00Z"
):
    """Workshop started to RUNNING with one ENROLLED member.

    Returns (instructor, student, workshop, enrollment). Advances the clock to
    starts_at so the workshop can be started.
    """
    tier = create_tier()
    instructor = register_member(tier["id"])
    student = register_member(tier["id"])
    _, ws = setup_workshop(
        instructor_id=instructor["id"],
        capacity=capacity,
        machine_class=machine_class,
        starts_at=starts_at,
    )
    enr = enroll_member(ws["id"], student["id"])
    set_clock(starts_at)
    ws = get_success_data(_api.start_workshop(ws["id"], make_staff_headers(instructor["id"])))
    return instructor, student, ws, enr


# ---------------------------------------------------------------------------
# Locker
# ---------------------------------------------------------------------------
def assign_locker(member, used_liters=0, capacity_liters=100, **overrides) -> dict:
    """Assign a locker to an active member using the member's current version."""
    v = current_member_version(member["id"])
    payload = create_locker_payload(
        member["id"], v, capacity_liters=capacity_liters, used_liters=used_liters, **overrides
    )
    return get_success_data(
        _api.create_locker(payload, make_member_headers(member["id"]))
    )


# ---------------------------------------------------------------------------
# Material purchase
# ---------------------------------------------------------------------------
def create_draft_purchase(member, lines, waste_surcharge_bps=0) -> dict:
    """Create a DRAFT material purchase for the member. Returns the purchase."""
    return get_success_data(
        _api.create_material_purchase(
            create_material_purchase_payload(
                member["id"], lines, waste_surcharge_bps=waste_surcharge_bps
            ),
            make_member_headers(member["id"]),
        )
    )
