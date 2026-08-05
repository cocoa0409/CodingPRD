"""Composite setup helpers.

The test harness restarts the API server before every test, so each helper
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() (lenient) so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data
from . import factories as F
from .test_users import (
    TEST_USERS,
    make_member_headers,
)

VM = TEST_USERS["vault_manager_headers"]
CT = TEST_USERS["concierge_tech_headers"]
BA = TEST_USERS["billing_admin_headers"]


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance the logical clock (VaultManager)."""
    return get_success_data(api.set_clock(iso, VM))


def create_facility(api, total_units: int = 10, name: str = "Test Vault") -> dict:
    return get_success_data(api.create_facility(
        F.create_facility_payload(name=name, total_units=total_units), VM))


def create_unit(api, facility_id: str, unit_class: str = "STANDARD",
                monthly_rate_cents: int = 30000, unit_code: str = None) -> dict:
    payload = F.create_unit_payload(unit_class=unit_class, monthly_rate_cents=monthly_rate_cents)
    if unit_code is not None:
        payload["unit_code"] = unit_code
    return get_success_data(api.create_unit(facility_id, payload, VM))


def create_member(api, membership_tier: str = None, full_name: str = "Test Member",
                  email: str = None) -> dict:
    payload = F.create_member_payload(full_name=full_name)
    if email is not None:
        payload["email"] = email
    if membership_tier is not None:
        payload["membership_tier"] = membership_tier
    return get_success_data(api.create_member(payload, VM))


def create_vehicle(api, member_id: str, declared_value_cents: int = 10_000_000,
                   vin: str = None, fuel_type: str = "ICE") -> dict:
    payload = F.create_vehicle_payload(member_id, declared_value_cents=declared_value_cents,
                                       fuel_type=fuel_type)
    if vin is not None:
        payload["vin"] = vin
    return get_success_data(api.create_vehicle(payload, VM))


def document_vehicle(api, vehicle_id: str) -> dict:
    """Run an INTAKE inspection and pass it, moving the vehicle to DOCUMENTED."""
    insp = get_success_data(api.create_inspection(
        F.create_inspection_payload(vehicle_id, inspection_type="INTAKE"), VM))
    get_success_data(api.pass_inspection(insp["id"], {}, VM))
    return get_success_data(api.get_vehicle(vehicle_id, VM))


def create_coi(api, vehicle_id: str, coverage_amount_cents: int = 10_000_000,
               effective_at: str = "2026-05-01T00:00:00Z",
               expiry_at: str = "2027-01-01T00:00:00Z") -> dict:
    return get_success_data(api.create_coi(
        vehicle_id,
        F.create_coi_payload(coverage_amount_cents=coverage_amount_cents,
                             effective_at=effective_at, expiry_at=expiry_at),
        VM))


def create_transporter(api, buffer_minutes: int = 60, name: str = None) -> dict:
    payload = F.create_transporter_payload()
    if name is not None:
        payload["name"] = name
    payload["buffer_minutes"] = buffer_minutes
    return get_success_data(api.create_transporter(payload, VM))


def unit_version(api, unit_id: str) -> int:
    return get_success_data(api.get_unit(unit_id, VM))["version"]


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_pending_agreement(api, unit_class: str = "STANDARD",
                            monthly_rate_cents: int = 30000,
                            membership_tier: str = "BRONZE",
                            declared_value_cents: int = 10_000_000,
                            clock: str = "2026-06-01T00:00:00Z",
                            move_in_at: str = "2026-06-01T00:00:00Z",
                            planned_move_out_at: str = "2026-12-01T00:00:00Z",
                            document: bool = True,
                            total_units: int = 4) -> dict:
    """Facility + unit + member + vehicle + PENDING agreement.

    When document=True the vehicle is intake-documented (required for a later
    move-in). Returns a context dict with all created entities/ids.
    """
    fac = create_facility(api, total_units=total_units)
    unit = create_unit(api, fac["id"], unit_class=unit_class, monthly_rate_cents=monthly_rate_cents)
    mem = create_member(api, membership_tier=membership_tier)
    veh = create_vehicle(api, mem["id"], declared_value_cents=declared_value_cents)
    if document:
        veh = document_vehicle(api, veh["id"])
    set_clock(api, clock)
    uv = unit_version(api, unit["id"])
    agr = get_success_data(api.create_agreement(
        F.create_agreement_payload(mem["id"], veh["id"], unit["id"], uv,
                                   move_in_at=move_in_at,
                                   planned_move_out_at=planned_move_out_at),
        VM))
    return {
        "facility": fac, "unit": unit, "member": mem, "vehicle": veh,
        "agreement": agr,
        "facility_id": fac["id"], "unit_id": unit["id"], "member_id": mem["id"],
        "vehicle_id": veh["id"], "agreement_id": agr["id"],
    }


def setup_stored_agreement(api, **kwargs) -> dict:
    """As setup_pending_agreement, then move-in so the agreement is IN_STORAGE."""
    ctx = setup_pending_agreement(api, **kwargs)
    ctx["agreement"] = get_success_data(api.move_in(ctx["agreement_id"], VM))
    return ctx


def setup_approved_service_order(api, service_type: str = "DETAIL",
                                 estimated_labor_hours: float = 1.0,
                                 scheduled_at: str = "2026-06-02T09:00:00Z",
                                 **kwargs) -> dict:
    """Stored agreement + a service order approved (APPROVED)."""
    ctx = setup_stored_agreement(api, **kwargs)
    so = get_success_data(api.create_service_order(
        F.create_service_order_payload(ctx["agreement_id"], service_type=service_type,
                                       estimated_labor_hours=estimated_labor_hours), VM))
    so = get_success_data(api.approve_service_order(so["id"], {"scheduled_at": scheduled_at}, VM))
    ctx["service_order"] = so
    ctx["service_order_id"] = so["id"]
    return ctx


def setup_in_progress_service_order(api, **kwargs) -> dict:
    """Stored agreement + a service order started (IN_PROGRESS)."""
    ctx = setup_approved_service_order(api, **kwargs)
    ctx["service_order"] = get_success_data(api.start_service_order(ctx["service_order_id"], CT))
    return ctx


def setup_vehicle_with_active_coi(api, declared_value_cents: int = 5_000_000,
                                  coverage_amount_cents: int = 5_000_000,
                                  membership_tier: str = "GOLD",
                                  clock: str = "2026-06-01T00:00:00Z",
                                  fuel_type: str = "ICE") -> dict:
    """Member + vehicle + an ACTIVE covering COI; clock set. Returns context."""
    mem = create_member(api, membership_tier=membership_tier)
    veh = create_vehicle(api, mem["id"], declared_value_cents=declared_value_cents,
                         fuel_type=fuel_type)
    set_clock(api, clock)
    coi = create_coi(api, veh["id"], coverage_amount_cents=coverage_amount_cents)
    veh = get_success_data(api.get_vehicle(veh["id"], VM))
    return {
        "member": mem, "vehicle": veh, "coi": coi,
        "member_id": mem["id"], "vehicle_id": veh["id"], "coi_id": coi["id"],
    }


def setup_scheduled_delivery(api, buffer_minutes: int = 60,
                             pickup_at: str = "2026-06-20T09:00:00Z",
                             dropoff_at: str = "2026-06-20T18:00:00Z",
                             **coi_kwargs) -> dict:
    """Vehicle with ACTIVE adequate COI + transporter + one SCHEDULED delivery job."""
    ctx = setup_vehicle_with_active_coi(api, **coi_kwargs)
    tr = create_transporter(api, buffer_minutes=buffer_minutes)
    dj = get_success_data(api.create_delivery_job(
        F.create_delivery_job_payload(ctx["vehicle_id"], tr["id"],
                                      pickup_at=pickup_at, dropoff_at=dropoff_at), VM))
    ctx["transporter"] = tr
    ctx["transporter_id"] = tr["id"]
    ctx["delivery_job"] = dj
    ctx["delivery_job_id"] = dj["id"]
    return ctx


def setup_occupied_unit_with_waiter(api, unit_class: str = "CLIMATE",
                                    monthly_rate_cents: int = 40000,
                                    waiter_tier: str = "SILVER") -> dict:
    """Single-unit facility: member A occupies the only unit (IN_STORAGE) with an
    ACTIVE monitoring sub; member B is WAITING for that unit class. Returns context."""
    ctx = setup_stored_agreement(api, unit_class=unit_class,
                                 monthly_rate_cents=monthly_rate_cents,
                                 membership_tier="GOLD", total_units=1)
    mon = get_success_data(api.create_monitoring(
        ctx["agreement_id"], F.create_monitoring_payload(monitor_type="BATTERY_TENDER",
                                                         monthly_fee_cents=5000), CT))
    memB = create_member(api, membership_tier=waiter_tier)
    wlB = get_success_data(api.create_waitlist(
        F.create_waitlist_payload(memB["id"], ctx["facility_id"], desired_unit_class=unit_class),
        make_member_headers(memB["id"])))
    ctx["monitoring"] = mon
    ctx["monitoring_id"] = mon["id"]
    ctx["waiter_member"] = memB
    ctx["waitlist_entry"] = wlB
    ctx["waitlist_id"] = wlB["id"]
    return ctx


def setup_draft_invoice(api, monthly_rate_cents: int = 50000,
                        membership_tier: str = "BRONZE",
                        proration_mode: str = None,
                        document: bool = False, move_in: bool = False,
                        **kwargs) -> dict:
    """Member + agreement + one DRAFT invoice over the June period. Returns context
    with the invoice under 'invoice'."""
    if move_in:
        ctx = setup_stored_agreement(api, monthly_rate_cents=monthly_rate_cents,
                                     membership_tier=membership_tier, document=True, **kwargs)
    else:
        ctx = setup_pending_agreement(api, monthly_rate_cents=monthly_rate_cents,
                                      membership_tier=membership_tier, document=document, **kwargs)
    payload = F.generate_invoice_payload(ctx["member_id"], ctx["agreement_id"])
    if proration_mode is not None:
        payload["proration_mode"] = proration_mode
    inv = get_success_data(api.generate_invoice(payload, BA))
    ctx["invoice"] = inv
    ctx["invoice_id"] = inv["id"]
    return ctx
