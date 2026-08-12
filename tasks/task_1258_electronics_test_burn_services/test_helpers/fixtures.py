"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through the public API
(each test starts against an empty database). Setup calls use
get_success_data() so a setup failure surfaces as a clear error, not a
confusing assertion failure deep inside a test.

Identity threading: lot creation, CustomerRep unit registration, and RMA
creation are ownership-gated, so they always use
make_customer_rep_headers(customer_id) with the real Customer.id.
"""
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_BASE
from .factories import (
    DEFAULT_BIN_MAP,
    DEFAULT_BURN_PROFILE,
    create_chamber_payload,
    create_chamber_reservation_payload,
    create_customer_equipment_payload,
    create_customer_payload,
    create_esd_audit_payload,
    create_fixture_payload,
    create_lot_payload,
    create_maintenance_order_payload,
    create_retest_authorization_payload,
    create_rma_case_payload,
    create_test_program_payload,
    create_test_result_payload,
    create_unit_payload,
)
from .test_users import (
    make_customer_rep_headers,
    make_operations_manager_headers,
    make_quality_engineer_headers,
    make_test_engineer_headers,
)

OPS = make_operations_manager_headers("ops-1")
ENG1 = make_test_engineer_headers("eng-1")
ENG2 = make_test_engineer_headers("eng-2")
QE = make_quality_engineer_headers("qe-1")


# ─── Tier 1/2: program + fixture + customer setup ────────────────────

def create_customer(name: str = "TestCo", requires_esd_certification: bool = False,
                    tier: str = "STANDARD") -> dict:
    """Register a customer. Returns the customer dict."""
    return get_success_data(api_client.create_customer(
        create_customer_payload(
            name=name, tier=tier, requires_esd_certification=requires_esd_certification
        ),
        OPS,
    ))


def create_released_program(customer_id: str, part_number: str = "PN-1000",
                            bin_map: Optional[dict] = None,
                            max_retests_per_unit: int = 2,
                            burn_profile: Optional[list] = None,
                            fixture_serial: str = "FX-1",
                            engineer_headers: Optional[dict] = None) -> dict:
    """Create program + fixture, commission fixture, validate, release.

    Returns a context dict: {"customer_id", "program", "fixture"}.
    """
    eng = engineer_headers or ENG1
    program = get_success_data(api_client.create_test_program(
        create_test_program_payload(
            customer_id,
            part_number=part_number,
            bin_map=dict(bin_map or DEFAULT_BIN_MAP),
            max_retests_per_unit=max_retests_per_unit,
            burn_profile=[dict(s) for s in (burn_profile or DEFAULT_BURN_PROFILE)],
        ),
        eng,
    ))
    fixture = get_success_data(api_client.create_fixture(
        create_fixture_payload(program["id"], serial_number=fixture_serial), eng,
    ))
    get_success_data(api_client.commission_fixture(fixture["id"], eng))
    get_success_data(api_client.validate_program(program["id"], eng))
    program = get_success_data(api_client.release_program(program["id"], eng))
    return {"customer_id": customer_id, "program": program, "fixture": fixture}


def setup_released_program_with_fixture(customer_name: str = "TestCo",
                                        requires_esd_certification: bool = False,
                                        tier: str = "STANDARD",
                                        part_number: str = "PN-1000",
                                        bin_map: Optional[dict] = None,
                                        max_retests_per_unit: int = 2,
                                        burn_profile: Optional[list] = None,
                                        fixture_serial: str = "FX-1") -> dict:
    """Customer + RELEASED program + AVAILABLE fixture.

    Returns {"customer", "program", "fixture", "rep_headers"}.
    """
    customer = create_customer(
        name=customer_name,
        requires_esd_certification=requires_esd_certification,
        tier=tier,
    )
    ctx = create_released_program(
        customer["id"],
        part_number=part_number,
        bin_map=bin_map,
        max_retests_per_unit=max_retests_per_unit,
        burn_profile=burn_profile,
        fixture_serial=fixture_serial,
    )
    ctx["customer"] = customer
    ctx["rep_headers"] = make_customer_rep_headers(customer["id"])
    return ctx


# ─── Tier 2/3: lot pipeline ────────────────────────────────────────────

def create_lot_with_units(ctx: dict, quantity: int, serial_prefix: str = "SN",
                          registrar: str = "ops") -> tuple:
    """Create a lot (RECEIVED) and register `quantity` units on it.

    registrar: "ops" (OperationsManager on receipt) or "rep" (owning
    CustomerRep declaring serials). Returns (lot, [units]).
    """
    lot = get_success_data(api_client.create_lot(
        create_lot_payload(
            ctx["customer"]["id"], ctx["program"]["id"],
            part_number=ctx["program"]["part_number"], quantity=quantity,
        ),
        ctx["rep_headers"],
    ))
    headers = OPS if registrar == "ops" else ctx["rep_headers"]
    units = [
        get_success_data(api_client.create_unit(
            create_unit_payload(lot["id"], serial_number=f"{serial_prefix}-{i + 1}"),
            headers,
        ))
        for i in range(quantity)
    ]
    return lot, units


def setup_queued_lot(quantity: int = 1, **program_kwargs) -> dict:
    """Full setup through QUEUED: customer + released program + fixture +
    lot + all units registered + enqueue.

    Returns {"customer", "program", "fixture", "rep_headers", "lot", "units"}.
    """
    ctx = setup_released_program_with_fixture(**program_kwargs)
    lot, units = create_lot_with_units(ctx, quantity)
    lot = get_success_data(api_client.enqueue_lot(lot["id"], OPS))
    ctx["lot"] = lot
    ctx["units"] = units
    return ctx


def setup_in_test_lot(quantity: int = 1, **program_kwargs) -> dict:
    """Full setup through IN_TEST. Same return shape as setup_queued_lot."""
    ctx = setup_queued_lot(quantity=quantity, **program_kwargs)
    ctx["lot"] = get_success_data(api_client.start_test_lot(ctx["lot"]["id"], OPS))
    return ctx


# ─── Tier 3: result recording / retest loop ────────────────────────────

def record_result(unit_id: str, fixture_id: str, bin_code: int,
                  engineer_headers: Optional[dict] = None,
                  equipment_id: Optional[str] = None) -> dict:
    """Record a test insertion. Returns the created TestResult."""
    payload = create_test_result_payload(unit_id, fixture_id, bin_code=bin_code)
    if equipment_id is not None:
        payload["equipment_id"] = equipment_id
    return get_success_data(api_client.create_test_result(
        payload, engineer_headers or ENG1,
    ))


def authorize_retest(unit_id: str, reason: str = "authorized retest",
                     engineer_headers: Optional[dict] = None) -> dict:
    """Grant a retest authorization (defaults to eng-2, distinct from the
    default recorder eng-1, honoring segregation of duties)."""
    return get_success_data(api_client.create_retest_authorization(
        create_retest_authorization_payload(unit_id, reason=reason),
        engineer_headers or ENG2,
    ))


def record_pass(unit: dict, fixture_id: str, engineer_headers: Optional[dict] = None) -> dict:
    return record_result(unit["id"], fixture_id, 1, engineer_headers)


def record_soft_fail(unit: dict, fixture_id: str, engineer_headers: Optional[dict] = None) -> dict:
    return record_result(unit["id"], fixture_id, 2, engineer_headers)


def record_hard_fail(unit: dict, fixture_id: str, engineer_headers: Optional[dict] = None) -> dict:
    return record_result(unit["id"], fixture_id, 9, engineer_headers)


def setup_lot_with_results(bin_codes: List[int], **program_kwargs) -> dict:
    """IN_TEST lot with one first-insertion result per unit, in order.

    bin_codes maps one bin per unit (lot quantity == len(bin_codes)).
    Adds "results" to the returned context.
    """
    ctx = setup_in_test_lot(quantity=len(bin_codes), **program_kwargs)
    results = [
        record_result(u["id"], ctx["fixture"]["id"], bin_code)
        for u, bin_code in zip(ctx["units"], bin_codes)
    ]
    ctx["results"] = results
    return ctx


def setup_awaiting_disposition_lot(bin_codes: List[int], **program_kwargs) -> dict:
    """Lot driven to AWAITING_DISPOSITION with the given first-insertion bins."""
    ctx = setup_lot_with_results(bin_codes, **program_kwargs)
    ctx["lot"] = get_success_data(api_client.complete_test_lot(ctx["lot"]["id"], OPS))
    return ctx


def setup_shipped_lot(quantity: int = 1, **program_kwargs) -> dict:
    """Lot of `quantity` units, all passed first insertion, SHIPPED.

    FPY 1.0, retest rate 0, escapes 0 -> suggestion SHIP -> direct ship.
    """
    ctx = setup_awaiting_disposition_lot([1] * quantity, **program_kwargs)
    ctx["lot"] = get_success_data(api_client.ship_lot(ctx["lot"]["id"], OPS))
    return ctx


# ─── Tier 3: chamber scheduling ────────────────────────────────────────

def setup_chamber(name: str = "CH-1", area_code: str = "AREA-1",
                  slot_count: int = 4, supported_profile_classes: Optional[list] = None,
                  clock: Optional[str] = CLOCK_BASE) -> dict:
    """Register an ONLINE chamber and (optionally) position the logical clock."""
    chamber = get_success_data(api_client.create_chamber(
        create_chamber_payload(
            name=name, area_code=area_code, slot_count=slot_count,
            supported_profile_classes=supported_profile_classes or ["A"],
        ),
        OPS,
    ))
    if clock is not None:
        get_success_data(api_client.set_clock({"to_iso8601": clock}, OPS))
    return chamber


def setup_reservation_scenario(quantity: int = 1, slot_count: int = 4,
                               profile_classes: Optional[list] = None,
                               clock: Optional[str] = CLOCK_BASE,
                               **program_kwargs) -> dict:
    """QUEUED lot + ONLINE chamber + clock positioned. Ready for booking."""
    ctx = setup_queued_lot(quantity=quantity, **program_kwargs)
    ctx["chamber"] = setup_chamber(
        slot_count=slot_count,
        supported_profile_classes=profile_classes or ["A"],
        clock=clock,
    )
    return ctx


def reserve(ctx: dict, start_at: str = "2026-06-01T10:00:00Z",
            end_at: str = "2026-06-01T11:00:00Z", slot_count: int = 1,
            profile_class: str = "A") -> dict:
    """Create a RESERVED reservation for the scenario's chamber/lot/fixture."""
    return get_success_data(api_client.create_chamber_reservation(
        create_chamber_reservation_payload(
            ctx["chamber"]["id"], ctx["lot"]["id"], ctx["fixture"]["id"],
            profile_class=profile_class, start_at=start_at, end_at=end_at,
            slot_count=slot_count,
        ),
        OPS,
    ))


# ─── Tier 5: disposition reviews / RMA / terminal states ───────────────

def list_reviews_for_lot(lot_id: str) -> list:
    """Return all disposition reviews for a lot, in creation order."""
    data, _meta = validate_paginated(
        api_client.list_lot_disposition_reviews(QE, params={"lot_id": lot_id})
    )
    return data


def get_pending_review_id(lot_id: str) -> Optional[str]:
    """Return the id of the lot's PENDING disposition review, or None."""
    pending = [r for r in list_reviews_for_lot(lot_id) if r["status"] == "PENDING"]
    return pending[0]["id"] if pending else None


def setup_rma_in_fa(quantity: int = 1, **program_kwargs) -> dict:
    """SHIPPED lot + RMA case opened by the owning rep + FA started.

    Adds "rma" to the returned context (fa_status == FA_IN_PROGRESS).
    """
    ctx = setup_shipped_lot(quantity=quantity, **program_kwargs)
    rma = get_success_data(api_client.create_rma_case(
        create_rma_case_payload(ctx["lot"]["id"], ctx["units"][0]["id"]),
        ctx["rep_headers"],
    ))
    get_success_data(api_client.start_rma_fa(rma["id"], QE))
    ctx["rma"] = rma
    return ctx


# ─── Equipment / maintenance ───────────────────────────────────────────

def create_equipment(customer_id: str, **overrides) -> dict:
    """Register customer-owned equipment (IN_SERVICE)."""
    return get_success_data(api_client.create_customer_equipment(
        create_customer_equipment_payload(customer_id, **overrides), OPS,
    ))


def create_maintenance_order(target_type: str, target_id: str, **overrides) -> dict:
    """Schedule an OPEN maintenance order."""
    return get_success_data(api_client.create_maintenance_order(
        create_maintenance_order_payload(target_type, target_id, **overrides), OPS,
    ))


# ─── ESD ───────────────────────────────────────────────────────────────

def create_open_major_audit(area_code: str,
                            description: str = "MAJOR finding") -> dict:
    """Open an ESD audit carrying one MAJOR finding on the area."""
    return get_success_data(api_client.create_esd_audit(
        create_esd_audit_payload(
            area_code=area_code,
            findings=[{"severity": "MAJOR", "description": description}],
        ),
        QE,
    ))


# ─── Program revision minting ──────────────────────────────────────────

def mint_revision(source_program_id: str) -> dict:
    """Mint the next revision of a RELEASED program (OCC on current version)."""
    source = get_success_data(api_client.get_test_program(source_program_id, ENG1))
    return get_success_data(api_client.create_program_revision(
        source_program_id,
        {"expected_test_program_version": source["version"]},
        ENG1,
    ))


def supersede_program(ctx: dict, new_fixture_serial: str = "FX-2") -> dict:
    """Mint revision 2 of ctx's program, fixture it, validate, release.

    After this call ctx["program"] (revision 1) is OBSOLETE and its fixture
    is DECOMMISSIONED. Returns a context for the NEW revision:
    {"program": rev2_released, "fixture": fix2}.
    """
    rev2 = mint_revision(ctx["program"]["id"])
    fix2 = get_success_data(api_client.create_fixture(
        create_fixture_payload(rev2["id"], serial_number=new_fixture_serial), ENG1,
    ))
    get_success_data(api_client.commission_fixture(fix2["id"], ENG1))
    get_success_data(api_client.validate_program(rev2["id"], ENG1))
    rev2 = get_success_data(api_client.release_program(rev2["id"], ENG1))
    return {"program": rev2, "fixture": fix2}
