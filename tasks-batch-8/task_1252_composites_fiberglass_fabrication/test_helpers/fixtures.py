"""
Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database (the harness restarts the server
before each test), so each helper builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data() so failures
surface as clear "Setup failed" messages rather than confusing assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    T0,
    create_cure_cycle_payload,
    create_cure_equipment_payload,
    create_cure_log_payload,
    create_emission_permit_payload,
    create_inspection_payload,
    create_layup_session_payload,
    create_mold_payload,
    create_ply_book_payload,
    create_resin_batch_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS

SM = TEST_USERS["shop_manager_headers"]
TE = TEST_USERS["tooling_engineer_headers"]
LAM = TEST_USERS["laminator_headers"]
CT = TEST_USERS["cure_technician_headers"]
QI = TEST_USERS["quality_inspector_headers"]
EHS = TEST_USERS["ehs_officer_headers"]

_code_counters: dict = {}


def _uniq(prefix: str) -> str:
    """Deterministic unique code per test process to avoid collisions."""
    _code_counters[prefix] = _code_counters.get(prefix, 0) + 1
    return f"{prefix}-{_code_counters[prefix]:04d}"


# ─── Tier 0/1: single-resource helpers ──────────────────────────────


def set_clock(to_iso8601: str = T0):
    """Position the logical clock (PRD §2.5). Returns the response data."""
    return get_success_data(api_client.set_clock(to_iso8601, SM))


def create_permit(**overrides) -> dict:
    overrides.setdefault("permit_code", _uniq("PER"))
    return get_success_data(
        api_client.create_emission_permit(create_emission_permit_payload(**overrides), EHS)
    )


def create_mold(**overrides) -> dict:
    overrides.setdefault("mold_code", _uniq("MOLD"))
    return get_success_data(api_client.create_mold(create_mold_payload(**overrides), TE))


def create_draft_ply_book(**overrides) -> dict:
    return get_success_data(
        api_client.create_ply_book(create_ply_book_payload(**overrides), TE)
    )


def create_approved_ply_book(**overrides) -> dict:
    """Create + approve a ply book. Returns the APPROVED book."""
    book = create_draft_ply_book(**overrides)
    return get_success_data(api_client.approve_ply_book(book["id"], TE))


def create_oven(**overrides) -> dict:
    overrides.setdefault("equipment_code", _uniq("OVEN"))
    return get_success_data(
        api_client.create_cure_equipment(create_cure_equipment_payload(**overrides), SM)
    )


def create_batch(**overrides) -> dict:
    overrides.setdefault("batch_code", _uniq("BATCH"))
    return get_success_data(
        api_client.create_resin_batch(create_resin_batch_payload(**overrides), LAM)
    )


# ─── Tier 2: shop skeleton (permit + mold + approved book) ──────────


def setup_shop(
    mold_overrides=None,
    ply_book_overrides=None,
    permit_overrides=None,
    set_clock_to: str = T0,
    with_oven: bool = False,
    oven_overrides=None,
):
    """Clock positioned + ACTIVE permit + mold + APPROVED ply book.

    Returns dict with keys: permit, mold, ply_book, and oven when requested.
    """
    if set_clock_to is not None:
        set_clock(set_clock_to)
    permit = create_permit(**(permit_overrides or {}))
    mold = create_mold(**(mold_overrides or {}))
    ply_book = create_approved_ply_book(**(ply_book_overrides or {}))
    out = {"permit": permit, "mold": mold, "ply_book": ply_book}
    if with_oven:
        out["oven"] = create_oven(**(oven_overrides or {}))
    return out


def release_work_order(shop: dict, **overrides) -> dict:
    """Release a work order against the shop's mold and approved book."""
    overrides.setdefault("work_order_no", _uniq("WO"))
    return get_success_data(
        api_client.create_work_order(
            create_work_order_payload(
                shop["mold"]["id"], shop["ply_book"]["id"], **overrides
            ),
            SM,
        )
    )


# ─── Tier 3: work-order lifecycle shortcuts ─────────────────────────


def setup_work_order_in_layup(
    mold_overrides=None,
    ply_book_overrides=None,
    permit_overrides=None,
    work_order_overrides=None,
    batch_overrides=None,
    set_clock_to: str = T0,
):
    """Shop + RELEASED order + start-layup + one mixed batch.

    Returns dict: shop keys plus work_order and batch. The order is
    LAYUP_IN_PROGRESS; the batch is MIXED and not yet consumed.
    """
    shop = setup_shop(
        mold_overrides=mold_overrides,
        ply_book_overrides=ply_book_overrides,
        permit_overrides=permit_overrides,
        set_clock_to=set_clock_to,
    )
    work_order = release_work_order(shop, **(work_order_overrides or {}))
    get_success_data(api_client.start_layup(work_order["id"], LAM))
    batch = create_batch(**(batch_overrides or {}))
    return {**shop, "work_order": work_order, "batch": batch}


def record_session(ctx: dict, resin_used_g: float = 200, batch=None) -> dict:
    """Record one ACTIVE layup session on the context's order/batch."""
    return get_success_data(
        api_client.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"],
                (batch or ctx["batch"])["id"],
                resin_used_g=resin_used_g,
            ),
            LAM,
        )
    )


def setup_work_order_awaiting_cure(with_oven: bool = True, **kwargs):
    """Layup completed with one 200 g session; order is AWAITING_CURE."""
    ctx = setup_work_order_in_layup(**kwargs)
    record_session(ctx, 200)
    get_success_data(api_client.complete_layup(ctx["work_order"]["id"], LAM))
    if with_oven and "oven" not in ctx:
        ctx["oven"] = create_oven()
    return ctx


def schedule_cure(ctx: dict, **cycle_overrides) -> dict:
    """Schedule a cure cycle for the context's order. Returns the cycle."""
    return get_success_data(
        api_client.create_cure_cycle(
            create_cure_cycle_payload(
                ctx["work_order"]["id"], ctx["oven"]["id"], **cycle_overrides
            ),
            CT,
        )
    )


def run_cure(cycle: dict, log_overrides=None) -> dict:
    """Start + complete a scheduled cycle with a passing log by default."""
    get_success_data(api_client.start_cure_cycle(cycle["id"], CT))
    return get_success_data(
        api_client.complete_cure_cycle(
            cycle["id"], create_cure_log_payload(**(log_overrides or {})), CT
        )
    )


def setup_work_order_cured(**kwargs):
    """Order driven to CURED via one passing mold-bearing cure cycle.

    Returns context dict with an added cure_cycle key.
    """
    ctx = setup_work_order_awaiting_cure(**kwargs)
    cycle = schedule_cure(ctx)
    completed = run_cure(cycle)
    ctx["cure_cycle"] = completed
    return ctx


def demold(ctx: dict, actual_part_weight_g: float = 2000.0) -> dict:
    """Demold the context's order at the given measured weight."""
    return get_success_data(
        api_client.demold_work_order(ctx["work_order"]["id"], actual_part_weight_g, LAM)
    )


def setup_work_order_in_inspection(demold_weight: float = 2000.0, **kwargs):
    """Order demolded (weight acceptance PASS) and standing IN_INSPECTION."""
    ctx = setup_work_order_cured(**kwargs)
    demold(ctx, demold_weight)
    return ctx


def setup_work_order_accepted(**kwargs):
    """Full lifecycle through a PASS inspection; order is ACCEPTED."""
    ctx = setup_work_order_in_inspection(**kwargs)
    inspection = get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                ctx["work_order"]["id"], void_content_pct=1.0, delamination_area_cm2=0.0
            ),
            QI,
        )
    )
    ctx["inspection"] = inspection
    return ctx


def setup_work_order_in_repair(**kwargs):
    """Order in REPAIR with one OPEN auto-created repair.

    Returns context with inspection (REPAIR_REQUIRED) and repair keys.
    """
    ctx = setup_work_order_in_inspection(**kwargs)
    inspection = get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                ctx["work_order"]["id"],
                void_content_pct=3.0,
                delamination_area_cm2=10.0,
            ),
            QI,
        )
    )
    repair = get_success_data(api_client.get_repair(inspection["created_repair_id"], QI))
    ctx["inspection"] = inspection
    ctx["repair"] = repair
    return ctx
