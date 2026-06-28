"""Composite setup helpers.

Every fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before each test). Setup calls use the lenient
get_success_data() validator so a setup failure surfaces as a clear "Setup failed".

Identity note: all four roles are opaque (PRD §2.1); headers are role-based shared
constants, never tied to an entity id.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tier 1 / 2: catalog + intake building blocks
# ---------------------------------------------------------------------------
def create_kit(on_hand_count=5, sku=None, name="Birth Kit"):
    """Create a SupplyKit. Returns the kit dict."""
    sku = sku or _uniq("BK")
    resp = api_client.create_supply_kit(
        f.create_supply_kit_payload(sku=sku, name=name, on_hand_count=on_hand_count), ADMIN
    )
    return get_success_data(resp)


def create_package(kit_sku, code=None, global_fee_cents=800000,
                   prenatal_visits_included=3, postpartum_visits_included=2,
                   package_type="BIRTH"):
    """Create a CarePackage bound to kit_sku. Returns the package dict."""
    code = code or _uniq("PKG")
    resp = api_client.create_care_package(
        f.create_care_package_payload(
            code=code, kit_sku=kit_sku, global_fee_cents=global_fee_cents,
            prenatal_visits_included=prenatal_visits_included,
            postpartum_visits_included=postpartum_visits_included,
            package_type=package_type,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def create_client(**overrides):
    """Register a client. Returns the client dict."""
    resp = api_client.create_client(f.create_client_payload(**overrides), INTAKE)
    return get_success_data(resp)


def create_catalog(kit_on_hand=5, global_fee_cents=800000,
                   prenatal_visits_included=3, postpartum_visits_included=2):
    """Create a kit + package pair sharing a kit_sku. Returns (kit, package)."""
    kit = create_kit(on_hand_count=kit_on_hand)
    package = create_package(
        kit["sku"], global_fee_cents=global_fee_cents,
        prenatal_visits_included=prenatal_visits_included,
        postpartum_visits_included=postpartum_visits_included,
    )
    return kit, package


def open_episode(package_code, client_id=None, edd="2026-08-01"):
    """Open an episode under an existing package. Returns the episode dict."""
    if client_id is None:
        client_id = create_client()["id"]
    resp = api_client.create_episode(
        f.create_episode_payload(client_id, package_code=package_code, edd=edd), INTAKE
    )
    return get_success_data(resp)


def setup_episode(kit_on_hand=5, global_fee_cents=800000,
                  prenatal_visits_included=3, postpartum_visits_included=2,
                  edd="2026-08-01"):
    """Standard kit+package+client+episode (clinical PLANNING, financial UNBILLED).

    Returns dict with keys: kit, package, client, episode.
    """
    kit, package = create_catalog(
        kit_on_hand=kit_on_hand, global_fee_cents=global_fee_cents,
        prenatal_visits_included=prenatal_visits_included,
        postpartum_visits_included=postpartum_visits_included,
    )
    client = create_client()
    episode = open_episode(package["code"], client_id=client["id"], edd=edd)
    return {"kit": kit, "package": package, "client": client, "episode": episode}


def setup_active_episode(**kwargs):
    """Standard setup then activate the episode to ACTIVE. Returns the same dict,
    with episode re-read to the activated state."""
    ctx = setup_episode(**kwargs)
    ep_id = ctx["episode"]["id"]
    get_success_data(api_client.activate_episode(ep_id, MIDWIFE))
    ctx["episode"] = get_success_data(api_client.get_episode(ep_id, ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 1: state progression — visits
# ---------------------------------------------------------------------------
def schedule_visit(episode_id, visit_kind="PRENATAL", scheduled_at="2026-04-01T10:00:00Z"):
    """Schedule a prenatal visit. Returns the visit dict."""
    resp = api_client.create_prenatal_visit(
        f.create_prenatal_visit_payload(episode_id, visit_kind=visit_kind, scheduled_at=scheduled_at),
        MIDWIFE,
    )
    return get_success_data(resp)


def complete_visit(visit_id, risk_flag="NONE", blood_pressure_systolic=None):
    """Complete a scheduled visit with a screening outcome. Returns the visit dict."""
    payload = f.complete_visit_payload(risk_flag=risk_flag)
    if blood_pressure_systolic is not None:
        payload["blood_pressure_systolic"] = blood_pressure_systolic
    resp = api_client.complete_prenatal_visit(visit_id, payload, MIDWIFE)
    return get_success_data(resp)


def setup_episode_with_completed_visit(risk_flag="TRANSFER", blood_pressure_systolic=130, **kwargs):
    """Standard episode (PLANNING) + one completed visit recording the given screening.

    Returns dict: kit, package, client, episode (re-read), visit.
    """
    ctx = setup_episode(**kwargs)
    ep_id = ctx["episode"]["id"]
    visit = schedule_visit(ep_id)
    complete_visit(visit["id"], risk_flag=risk_flag, blood_pressure_systolic=blood_pressure_systolic)
    ctx["visit"] = visit
    ctx["episode"] = get_success_data(api_client.get_episode(ep_id, ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: room booking lifecycle
# ---------------------------------------------------------------------------
def create_room(turnover_minutes=0, name="Garden Suite"):
    """Create a room. Returns the room dict (carries version)."""
    resp = api_client.create_room(
        f.create_room_payload(name=name, turnover_minutes=turnover_minutes), ADMIN
    )
    return get_success_data(resp)


def create_booking(episode_id, room_id, expected_room_version,
                   starts_at="2026-01-02T00:00:00Z", ends_at="2026-01-03T00:00:00Z"):
    """Hold a booking. Returns the booking dict."""
    resp = api_client.create_booking(
        f.create_booking_payload(
            episode_id, room_id, expected_room_version,
            starts_at=starts_at, ends_at=ends_at,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def setup_in_use_booking(**kwargs):
    """Active episode + room + booking driven all the way to IN_USE.

    Steps: standard setup -> activate -> create room -> hold booking -> confirm ->
    advance clock past starts_at -> check-in.
    Returns dict: kit, package, client, episode (ACTIVE, re-read), room, booking (IN_USE, re-read).
    """
    ctx = setup_active_episode(**kwargs)
    ep_id = ctx["episode"]["id"]
    room = create_room(turnover_minutes=0)
    booking = create_booking(ep_id, room["id"], room["version"])
    get_success_data(api_client.confirm_booking(booking["id"], ADMIN))
    get_success_data(api_client.set_clock("2026-01-02T01:00:00Z", ADMIN))
    get_success_data(api_client.check_in_booking(booking["id"], ADMIN))
    ctx["room"] = room
    ctx["booking"] = get_success_data(api_client.get_booking(booking["id"], ADMIN))
    return ctx


def setup_born_episode(**kwargs):
    """IN_USE booking setup, then record-birth so clinical_status == BORN.

    Returns dict: kit, package, client, episode (BORN, re-read), room, booking.
    """
    ctx = setup_in_use_booking(**kwargs)
    ep_id = ctx["episode"]["id"]
    get_success_data(api_client.record_birth(ep_id, MIDWIFE))
    ctx["episode"] = get_success_data(api_client.get_episode(ep_id, ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: on-call assignment lifecycle
# ---------------------------------------------------------------------------
def create_provider(max_active_episodes=2, license_number=None, full_name="Pri Midwife"):
    """Create a provider. Returns the provider dict."""
    license_number = license_number or _uniq("L")
    resp = api_client.create_provider(
        f.create_provider_payload(
            max_active_episodes=max_active_episodes,
            license_number=license_number, full_name=full_name,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def assign_primary(episode_id, provider_id,
                   coverage_start="2026-07-25T00:00:00Z", coverage_end="2026-08-10T00:00:00Z"):
    """Create a PRIMARY on-call assignment. Returns the assignment dict."""
    resp = api_client.create_on_call_assignment(
        f.create_on_call_assignment_payload(
            episode_id, provider_id,
            coverage_start=coverage_start, coverage_end=coverage_end,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def setup_primary_assignment(max_active_episodes=2, **kwargs):
    """Active episode + provider PRI + PRIMARY assignment (ASSIGNED).

    Returns dict: kit, package, client, episode (ACTIVE), provider, assignment.
    """
    ctx = setup_active_episode(**kwargs)
    ep_id = ctx["episode"]["id"]
    provider = create_provider(max_active_episodes=max_active_episodes, full_name="Pri Midwife")
    assignment = assign_primary(ep_id, provider["id"])
    ctx["provider"] = provider
    ctx["assignment"] = assignment
    return ctx


def setup_primary_with_backup(max_active_episodes=2, **kwargs):
    """Active episode + PRI PRIMARY (ASSIGNED) + BAK BACKUP (ASSIGNED) linked.

    Returns dict: kit, package, client, episode, provider (PRI), backup_provider (BAK),
    assignment (primary), backup_assignment.
    """
    ctx = setup_primary_assignment(max_active_episodes=max_active_episodes, **kwargs)
    bak = create_provider(max_active_episodes=max_active_episodes, full_name="Bak Midwife")
    resp = api_client.name_backup(
        ctx["assignment"]["id"], f.name_backup_payload(bak["id"]), ADMIN
    )
    backup_assignment = get_success_data(resp)
    ctx["backup_provider"] = bak
    ctx["backup_assignment"] = backup_assignment
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 / 4: claims, charges, balance
# ---------------------------------------------------------------------------
def submit_claim(episode_id):
    """Submit a global-fee insurance claim. Returns the claim dict."""
    resp = api_client.create_insurance_claim(
        f.create_insurance_claim_payload(episode_id), BILLING
    )
    return get_success_data(resp)


def setup_episode_with_submitted_claim(**kwargs):
    """Standard episode + SUBMITTED insurance claim.

    Returns dict: kit, package, client, episode, claim.
    """
    ctx = setup_episode(**kwargs)
    ctx["claim"] = submit_claim(ctx["episode"]["id"])
    return ctx


def get_global_fee_charge(episode_id):
    """Fetch the single GLOBAL_FEE charge on an episode. Returns the charge dict."""
    resp = api_client.list_episode_charges(episode_id, BILLING)
    charges = get_success_data(resp)
    if isinstance(charges, dict):
        charges = charges.get("items") or charges.get("data") or []
    for c in charges:
        if c.get("charge_kind") == "GLOBAL_FEE":
            return c
    return charges[0] if charges else None


def episode_version(episode_id):
    """Read and return the episode's current version (for OCC fields)."""
    ep = get_success_data(api_client.get_episode(episode_id, BILLING))
    return ep["version"]


def create_plan(episode_id, installment_count, expected_episode_version=None):
    """Create a payment plan; reads the current episode version if not supplied.

    Returns the plan dict.
    """
    if expected_episode_version is None:
        expected_episode_version = episode_version(episode_id)
    resp = api_client.create_payment_plan(
        f.create_payment_plan_payload(episode_id, installment_count, expected_episode_version),
        BILLING,
    )
    return get_success_data(resp)


def setup_plan_active_episode(installment_count=1, **kwargs):
    """Standard episode (estimate balance 160000) + OPEN plan; episode PLAN_ACTIVE.

    Returns dict: kit, package, client, episode (re-read), plan.
    """
    ctx = setup_episode(**kwargs)
    ep_id = ctx["episode"]["id"]
    plan = create_plan(ep_id, installment_count)
    ctx["plan"] = plan
    ctx["episode"] = get_success_data(api_client.get_episode(ep_id, BILLING))
    return ctx


def setup_billed_plan_episode(installment_count=1, **kwargs):
    """Standard episode with the GLOBAL_FEE charge BILLED, then a plan created on the
    estimate balance (160000). Episode financial_status PLAN_ACTIVE.

    Returns dict: kit, package, client, episode (re-read), global_charge, plan.
    """
    ctx = setup_episode(**kwargs)
    ep_id = ctx["episode"]["id"]
    global_charge = get_global_fee_charge(ep_id)
    get_success_data(api_client.bill_charge(global_charge["id"], BILLING))
    plan = create_plan(ep_id, installment_count)
    ctx["global_charge"] = global_charge
    ctx["plan"] = plan
    ctx["episode"] = get_success_data(api_client.get_episode(ep_id, BILLING))
    return ctx
