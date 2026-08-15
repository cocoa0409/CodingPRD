"""
Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every helper builds preconditions from scratch via PRD-declared endpoints,
using get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Naming: helpers return plain dicts (the `data` payload of each response).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_coating_spec_payload, create_paint_line_payload,
    create_cure_oven_payload, create_pretreatment_stage_payload,
    create_titration_reading_payload, create_adjustment_payload,
    create_lot_payload, create_run_slot_payload, create_complete_slot_payload,
    create_oven_cycle_payload, create_quality_test_payload,
    create_complete_strip_payload, create_color_change_payload,
    create_voc_permit_payload, create_clock_set_payload,
)
from .constants import TEST_DEFAULTS, CLOCK_STARTUP_DEFAULT
from .test_users import (
    TEST_USERS,
    make_qc_inspector_headers, make_quality_manager_headers, make_chemist_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
CHEM = TEST_USERS["chemist_headers"]
QC = TEST_USERS["qc_headers"]
QM = TEST_USERS["qm_headers"]

# Operator identities used across quality flows; segregation-of-duties (PRD §2.1)
# requires the releaser to differ from the recorder of the lot's quality tests.
QC_OPERATOR_1 = "qc-1"
QC_OPERATOR_2 = "qc-2"
QM_OPERATOR_1 = "qm-1"
QM_OPERATOR_2 = "qm-2"
CHEM_OPERATOR_1 = "chem-1"


# ---------------------------------------------------------------------------
# Tier 0: master data primitives
# ---------------------------------------------------------------------------

def create_customer(name=TEST_DEFAULTS["CUSTOMER_NAME"]):
    """Create a Customer. Returns the customer dict."""
    return get_success_data(api_client.create_customer(create_customer_payload(name=name), ADMIN))


def create_spec(customer_id, **overrides):
    """Create a CoatingSpec for a customer. Returns the spec dict."""
    return get_success_data(
        api_client.create_coating_spec(create_coating_spec_payload(customer_id, **overrides), ADMIN)
    )


def create_paint_line(**overrides):
    """Create a PaintLine (posture RUNNING, version 1). Returns the line dict."""
    return get_success_data(api_client.create_paint_line(create_paint_line_payload(**overrides), ADMIN))


def create_oven(**overrides):
    """Create a CureOven. Returns the oven dict."""
    return get_success_data(api_client.create_cure_oven(create_cure_oven_payload(**overrides), ADMIN))


def create_stage(paint_line_id, **overrides):
    """Create a PretreatmentStage (status IN_RANGE). Returns the stage dict."""
    return get_success_data(
        api_client.create_pretreatment_stage(
            create_pretreatment_stage_payload(paint_line_id, **overrides), ADMIN
        )
    )


def create_permit(**overrides):
    """Register a VocPermit (status ACTIVE, used/reserved zero). Returns the permit dict."""
    return get_success_data(api_client.create_voc_permit(create_voc_permit_payload(**overrides), ADMIN))


def create_lot(customer_id, spec_id, **overrides):
    """Book a Lot (status RECEIVED). Returns the lot dict."""
    return get_success_data(
        api_client.create_lot(create_lot_payload(customer_id, spec_id, **overrides), SCHED)
    )


def accept_lot(lot_id):
    """Accept a RECEIVED lot (status -> QUEUED, base charge priced). Returns the lot dict."""
    return get_success_data(api_client.accept_lot(lot_id, SCHED))


def create_and_accept_lot(customer_id, spec_id, **overrides):
    """Book + accept a lot. Returns the QUEUED lot dict."""
    lot = create_lot(customer_id, spec_id, **overrides)
    return accept_lot(lot["id"])


def read_line_version(line_id):
    """GET the line and return its current version (for expected_paint_line_version)."""
    return get_success_data(api_client.get_paint_line(line_id, SCHED))["version"]


def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, SCHED))


def get_line(line_id):
    return get_success_data(api_client.get_paint_line(line_id, SCHED))


def get_stage(stage_id):
    return get_success_data(api_client.get_pretreatment_stage(stage_id, SCHED))


def get_permit(permit_id):
    return get_success_data(api_client.get_voc_permit(permit_id, ADMIN))


def get_rework_order(order_id):
    return get_success_data(api_client.get_rework_order(order_id, QM))


def set_clock(to_iso8601):
    """Advance the server logical clock (PRD §2.11)."""
    return get_success_data(api_client.set_current_utc(create_clock_set_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: composite master-data scenarios
# ---------------------------------------------------------------------------

def setup_line_with_stage(line_overrides=None, stage_overrides=None):
    """PaintLine + one PretreatmentStage (IN_RANGE). Returns (line, stage)."""
    line = create_paint_line(**(line_overrides or {}))
    stage = create_stage(line["id"], **(stage_overrides or {}))
    return line, stage


def setup_master_data(
    line_overrides=None,
    spec_overrides=None,
    with_oven=True,
    with_permit=True,
    permit_overrides=None,
    with_stage=True,
):
    """
    Customer + CoatingSpec + PaintLine (+ PretreatmentStage) (+ CureOven) (+ VocPermit).
    Returns a dict with keys: customer, spec, line, stage, oven, permit
    (stage/oven/permit are None when not requested).
    """
    customer = create_customer()
    spec = create_spec(customer["id"], **(spec_overrides or {}))
    line = create_paint_line(**(line_overrides or {}))
    stage = create_stage(line["id"]) if with_stage else None
    oven = create_oven() if with_oven else None
    permit = create_permit(**(permit_overrides or {})) if with_permit else None
    return {
        "customer": customer,
        "spec": spec,
        "line": line,
        "stage": stage,
        "oven": oven,
        "permit": permit,
    }


def create_and_accept_lot_in_ctx(ctx, part_quantity=TEST_DEFAULTS["PART_QUANTITY"]):
    """Book + accept a lot inside a setup_master_data() context. Returns the QUEUED lot."""
    return create_and_accept_lot(ctx["customer"]["id"], ctx["spec"]["id"], part_quantity=part_quantity)


def create_run_slot_payload_for_ctx(ctx, lot_id, **overrides):
    """Build a run-slot payload with a freshly-read OCC version for ctx's line."""
    lv = read_line_version(ctx["line"]["id"])
    return create_run_slot_payload(ctx["line"]["id"], lot_id, lv, **overrides)


# ---------------------------------------------------------------------------
# Tier 3: production lifecycle shortcuts
# ---------------------------------------------------------------------------

def schedule_slot(line_id, lot_id, start_utc, end_utc, parts_per_hanger=TEST_DEFAULTS["PARTS_PER_HANGER"]):
    """
    Read the line version, then create a RunSlot with a fresh OCC token.
    Returns the created RunSlot dict (status SCHEDULED; lot moves to SCHEDULED).
    """
    lv = read_line_version(line_id)
    return get_success_data(
        api_client.create_run_slot(
            create_run_slot_payload(
                line_id, lot_id, lv,
                start_utc=start_utc, end_utc=end_utc, parts_per_hanger=parts_per_hanger,
            ),
            SCHED,
        )
    )


def setup_lot_scheduled(
    start_utc="2026-05-05T08:00:00Z",
    end_utc="2026-05-05T10:00:00Z",
    part_quantity=TEST_DEFAULTS["PART_QUANTITY"],
    parts_per_hanger=TEST_DEFAULTS["PARTS_PER_HANGER"],
    spec_overrides=None,
    line_overrides=None,
    permit_overrides=None,
    with_oven=True,
):
    """
    Master data + lot booked, accepted, and scheduled into a run slot.
    Returns dict(ctx) with an extra 'slot' key. Lot status: SCHEDULED.
    """
    ctx = setup_master_data(
        line_overrides=line_overrides,
        spec_overrides=spec_overrides,
        with_oven=with_oven,
        permit_overrides=permit_overrides,
    )
    lot = create_and_accept_lot(ctx["customer"]["id"], ctx["spec"]["id"], part_quantity=part_quantity)
    slot = schedule_slot(ctx["line"]["id"], lot["id"], start_utc, end_utc, parts_per_hanger)
    ctx["lot"] = lot
    ctx["slot"] = slot
    return ctx


def setup_lot_running(**kwargs):
    """setup_lot_scheduled + slot started. Lot status: ON_LINE; slot RUNNING."""
    ctx = setup_lot_scheduled(**kwargs)
    started = get_success_data(api_client.start_run_slot(ctx["slot"]["id"], SCHED))
    ctx["slot"] = started
    return ctx


def setup_lot_curing(paint_used_liters=TEST_DEFAULTS["PAINT_USED_LITERS"], **kwargs):
    """
    setup_lot_running + slot completed with a metered paint reading.
    Lot status: CURING; slot COMPLETED; a PAINT_USAGE_METERED entry posted.
    """
    ctx = setup_lot_running(**kwargs)
    completed = get_success_data(
        api_client.complete_run_slot(ctx["slot"]["id"], create_complete_slot_payload(
            paint_used_liters=paint_used_liters), SCHED)
    )
    ctx["slot"] = completed
    return ctx


def record_oven_cycle(ctx, **overrides):
    """Record an OvenCycle for ctx's lot/oven. Returns the OvenCycle dict."""
    return get_success_data(
        api_client.create_oven_cycle(
            create_oven_cycle_payload(ctx["lot"]["id"], ctx["oven"]["id"], **overrides),
            make_qc_inspector_headers(QC_OPERATOR_1),
        )
    )


def setup_lot_qc_pending(cycle_overrides=None, **kwargs):
    """
    setup_lot_curing + a passing oven cycle. Lot status: QC_PENDING.
    ctx gains 'cycle' (the PASS OvenCycle).
    """
    ctx = setup_lot_curing(**kwargs)
    cycle = record_oven_cycle(ctx, **(cycle_overrides or {}))
    ctx["cycle"] = cycle
    return ctx


def setup_lot_cure_failed(cycle_overrides=None, **kwargs):
    """
    setup_lot_curing + a failing oven cycle. Lot status: CURE_FAILED.
    ctx gains 'cycle' (the FAIL OvenCycle).
    """
    base = {"min_metal_temp_c": 170.0, "minutes_at_or_above_temp": 22}
    base.update(cycle_overrides or {})
    ctx = setup_lot_curing(**kwargs)
    cycle = record_oven_cycle(ctx, **base)
    ctx["cycle"] = cycle
    return ctx


def record_quality_test(lot_id, test_type, measured_value, operator=QC_OPERATOR_1):
    """Record a QualityTest. Returns the QualityTest dict."""
    return get_success_data(
        api_client.create_quality_test(
            create_quality_test_payload(lot_id, test_type=test_type, measured_value=measured_value),
            make_qc_inspector_headers(operator),
        )
    )


def setup_lot_qc_hold(fail_test_type="ADHESION", fail_value=1, **kwargs):
    """
    setup_lot_qc_pending + one FAIL quality test.
    Lot status: QC_HOLD; a DRAFT ReworkOrder auto-created.
    ctx gains 'failing_test' and 'rework_order'.
    """
    ctx = setup_lot_qc_pending(**kwargs)
    failing = record_quality_test(ctx["lot"]["id"], fail_test_type, fail_value)
    orders = get_success_data(api_client.list_rework_orders_of_lot(ctx["lot"]["id"], QM))
    ctx["failing_test"] = failing
    ctx["rework_order"] = orders[0]
    return ctx


def setup_rework_approved(**kwargs):
    """
    setup_lot_qc_hold + rework order approved.
    Lot status: STRIPPING; rework order APPROVED with strip cost priced.
    """
    ctx = setup_lot_qc_hold(**kwargs)
    approved = get_success_data(api_client.approve_rework_order(ctx["rework_order"]["id"], make_quality_manager_headers(QM_OPERATOR_1)))
    ctx["rework_order"] = approved
    return ctx


def setup_lot_requeued_after_rework(scrapped_quantity=0, **kwargs):
    """
    setup_rework_approved + complete-strip. Lot back in QUEUED (rework_count 1)
    when scrapped_quantity < parts_to_rework. ctx gains refreshed 'lot'.
    """
    ctx = setup_rework_approved(**kwargs)
    completed = get_success_data(
        api_client.complete_strip(
            ctx["rework_order"]["id"],
            create_complete_strip_payload(scrapped_quantity=scrapped_quantity),
            make_quality_manager_headers(QM_OPERATOR_1),
        )
    )
    ctx["rework_order"] = completed
    ctx["lot"] = get_lot(ctx["lot"]["id"])
    return ctx


def run_lot_through_second_pass(ctx, slot_start="2026-05-08T08:00:00Z", slot_end="2026-05-08T10:00:00Z",
                                cycle_overrides=None, paint_used_liters=TEST_DEFAULTS["PAINT_USED_LITERS"]):
    """
    Given a lot back in QUEUED after a rework cycle, schedule + run + cure it again.
    ctx gains 'slot2' and 'cycle2'. Lot status: QC_PENDING.
    """
    base = {
        "entered_at": "2026-05-08T10:05:00Z",
        "exited_at": "2026-05-08T10:45:00Z",
        "min_metal_temp_c": 182.0,
        "minutes_at_or_above_temp": 22,
    }
    base.update(cycle_overrides or {})
    slot2 = schedule_slot(ctx["line"]["id"], ctx["lot"]["id"], slot_start, slot_end)
    get_success_data(api_client.start_run_slot(slot2["id"], SCHED))
    get_success_data(api_client.complete_run_slot(slot2["id"], create_complete_slot_payload(
        paint_used_liters=paint_used_liters), SCHED))
    cycle2 = record_oven_cycle(ctx, **base)
    ctx["slot2"] = slot2
    ctx["cycle2"] = cycle2
    return ctx


def setup_lot_release_ready(**kwargs):
    """
    setup_lot_qc_pending + both evidence legs PASS recorded by qc-1.
    Lot status: QC_PENDING with ADHESION PASS + IMPACT PASS on file.
    """
    ctx = setup_lot_qc_pending(**kwargs)
    record_quality_test(ctx["lot"]["id"], "ADHESION", 3)
    record_quality_test(ctx["lot"]["id"], "IMPACT", 50.0)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: chemistry drives
# ---------------------------------------------------------------------------

def drive_stage_out_of_range(stage_id, measured=19.9, operator=CHEM_OPERATOR_1):
    """Post an out-of-range titration reading; stage -> OUT_OF_RANGE, line -> CHEM_HOLD."""
    return get_success_data(
        api_client.record_titration_reading(
            create_titration_reading_payload(stage_id, measured_conc_gpl=measured),
            make_chemist_headers(operator),
        )
    )


def drive_stage_in_range_reading(stage_id, measured=25.0, operator=CHEM_OPERATOR_1):
    """Post an in-range titration reading."""
    return get_success_data(
        api_client.record_titration_reading(
            create_titration_reading_payload(stage_id, measured_conc_gpl=measured),
            make_chemist_headers(operator),
        )
    )


def record_adjustment(stage_id, chemical_added_kg=1.0, operator=CHEM_OPERATOR_1):
    """Record a chemical adjustment; stage OUT_OF_RANGE -> ADJUSTING."""
    return get_success_data(
        api_client.record_adjustment(
            stage_id, create_adjustment_payload(chemical_added_kg=chemical_added_kg),
            make_chemist_headers(operator),
        )
    )
