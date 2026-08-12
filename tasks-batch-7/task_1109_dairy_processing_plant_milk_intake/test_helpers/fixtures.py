"""Composite setup helpers for multi-step test prerequisites.

All helpers use get_success_data() (lenient) so setup failures surface as
clear "Setup step failed" errors rather than confusing assertion failures.
Every helper builds its preconditions from scratch against PRD-declared
endpoints because the server restarts (empty database) before every test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ANNOUNCE_DATE_ISO,
    DEFAULT_CLOCK_ISO,
    PERIOD_END_ISO,
    PERIOD_START_ISO,
)
from .factories import (
    create_batch_payload,
    create_cip_cycle_payload,
    create_clock_payload,
    create_component_assay_payload,
    create_distribution_route_payload,
    create_grade_a_permit_payload,
    create_hauler_payload,
    create_lab_test_payload,
    create_pasteurizer_run_payload,
    create_pool_payload,
    create_producer_payload,
    create_settlement_payload,
    create_tanker_receipt_payload,
)
from .test_users import TEST_USERS

PC = TEST_USERS["plant_controller_headers"]
QA = TEST_USERS["qa_manager_headers"]
LAB = TEST_USERS["lab_technician_headers"]
OP = TEST_USERS["pasteurizer_operator_headers"]
SI = TEST_USERS["state_inspector_headers"]


# ─── Tier 0: Clock and single-entity creation ─────────

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    """Advance the server logical clock (PRD §2.6)."""
    res = api_client.set_clock(create_clock_payload(to_iso8601), PC)
    get_success_data(res)


def make_producer(hauling_rate: int = 100, **overrides) -> dict:
    res = api_client.create_producer(
        create_producer_payload(base_hauling_rate_cents_per_cwt=hauling_rate, **overrides), PC
    )
    return get_success_data(res)


def make_hauler(**overrides) -> dict:
    return get_success_data(api_client.create_hauler(create_hauler_payload(**overrides), PC))


def make_permit(**overrides) -> dict:
    return get_success_data(
        api_client.create_grade_a_permit(create_grade_a_permit_payload(**overrides), SI)
    )


def make_pool(**overrides) -> dict:
    return get_success_data(
        api_client.create_marketing_order_pool(create_pool_payload(**overrides), PC)
    )


def make_route(**overrides) -> dict:
    return get_success_data(
        api_client.create_distribution_route(create_distribution_route_payload(**overrides), PC)
    )


def make_receipt(producer_id: str, hauler_id: str, **overrides) -> dict:
    """Record a tanker receipt (lands in QUARANTINE)."""
    return get_success_data(
        api_client.create_tanker_receipt(
            create_tanker_receipt_payload(producer_id, hauler_id, **overrides), QA
        )
    )


def get_producer(producer_id: str) -> dict:
    return get_success_data(api_client.get_producer(producer_id, PC))


def get_receipt(receipt_id: str) -> dict:
    return get_success_data(api_client.get_tanker_receipt(receipt_id, QA))


def get_pool(pool_id: str) -> dict:
    return get_success_data(api_client.get_marketing_order_pool(pool_id, PC))


def get_settlement(producer_id: str, settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(producer_id, settlement_id, PC))


def get_run(run_id: str) -> dict:
    return get_success_data(api_client.get_pasteurizer_run(run_id, OP))


def get_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_grade_a_permit(permit_id, SI))


# ─── Tier 1: Lab work and receipt disposition ─────────

def record_lab_result(receipt_id: str, test_type: str, result_value) -> dict:
    """Create a lab test and complete it. Returns the COMPLETED LabTest."""
    test = get_success_data(
        api_client.create_lab_test(
            receipt_id,
            create_lab_test_payload(test_type=test_type, result_value=result_value),
            LAB,
        )
    )
    return get_success_data(api_client.complete_lab_test(receipt_id, test["id"], {}, LAB))


def setup_releasable_receipt(
    producer_id: str,
    hauler_id: str,
    scc: int = 300000,
    antibiotic=0,
    temp=40,
    gross=50000,
    tare=30000,
    **receipt_overrides,
) -> dict:
    """Receipt in QUARANTINE with both required lab tests COMPLETED and passing.

    Returns the receipt dict (freshly fetched, so receipt-side fields updated
    by lab completion are visible).
    """
    receipt = make_receipt(
        producer_id, hauler_id, temperature_f=temp,
        gross_weight_lbs=gross, tare_weight_lbs=tare, **receipt_overrides,
    )
    record_lab_result(receipt["id"], "ANTIBIOTIC", antibiotic)
    record_lab_result(receipt["id"], "SCC", scc)
    return get_receipt(receipt["id"])


def release_receipt(receipt_id: str, producer_id: str) -> dict:
    """Release a receipt, reading the producer's current version first so the
    OCC guard (PRD §2.7) passes. Returns the released receipt."""
    producer = get_producer(producer_id)
    res = api_client.release_tanker_receipt(
        receipt_id, {"expected_producer_version": producer["version"]}, QA
    )
    return get_success_data(res)


def setup_released_receipt(
    producer_id: str,
    hauler_id: str,
    gross=50000,
    tare=30000,
    assay=None,
    **receipt_overrides,
) -> dict:
    """Receipt fully through labs and release (RELEASED_FOR_PROCESSING).

    If `assay` is a dict of percentage overrides, a ComponentAssay is recorded
    and attached as receipt["assay"].
    """
    receipt = setup_releasable_receipt(
        producer_id, hauler_id, gross=gross, tare=tare, **receipt_overrides
    )
    released = release_receipt(receipt["id"], producer_id)
    if assay is not None:
        released_assay = get_success_data(
            api_client.create_component_assay(
                receipt["id"], create_component_assay_payload(**assay), LAB
            )
        )
        released["assay"] = released_assay
    return released


def setup_rejected_receipt(
    producer_id: str,
    hauler_id: str,
    antibiotic=5,
    **receipt_overrides,
) -> dict:
    """Receipt rejected via a POSITIVE antibiotic result. Returns the receipt."""
    receipt = make_receipt(producer_id, hauler_id, **receipt_overrides)
    record_lab_result(receipt["id"], "ANTIBIOTIC", antibiotic)
    res = api_client.reject_tanker_receipt(receipt["id"], {}, QA)
    return get_success_data(res)


def setup_producer_with_rejections(producer_id: str, hauler_id: str, count: int):
    """Drive `count` rejections against the producer (updates rolling count and
    quality flag per PRD §3.4)."""
    for i in range(count):
        setup_rejected_receipt(
            producer_id, hauler_id, arrived_at=f"2026-05-{5 + i:02d}T08:00:00Z"
        )


# ─── Tier 2: Intake environment bundles ───────────────

def setup_intake_env(hauling_rate: int = 100, pool: bool = False) -> dict:
    """Producer + hauler + ACTIVE Grade A permit (+ optional May pool).

    Returns dict with keys: producer, hauler, permit, pool (pool may be None).
    """
    set_clock()
    producer = make_producer(hauling_rate=hauling_rate)
    hauler = make_hauler()
    permit = make_permit()
    pool_obj = make_pool() if pool else None
    return {"producer": producer, "hauler": hauler, "permit": permit, "pool": pool_obj}


# ─── Tier 3: Settlements and pool lifecycle ───────────

def make_settlement(producer_id: str, **overrides) -> dict:
    """Create a DRAFT settlement (PROVISIONAL variant) for the May 2026 period."""
    payload = create_settlement_payload(**overrides)
    return get_success_data(api_client.create_settlement(producer_id, payload, PC))


def announce_pool(pool_id: str) -> dict:
    """Advance the clock to the FMMO announcement date and announce the pool."""
    set_clock(ANNOUNCE_DATE_ISO)
    return get_success_data(api_client.announce_pool(pool_id, {}, PC))


def finalize_pool(pool_id: str) -> dict:
    """Finalize an ANNOUNCED pool with its current version (OCC, PRD §2.7)."""
    pool = get_pool(pool_id)
    return get_success_data(
        api_client.finalize_pool(pool_id, {"expected_pool_version": pool["version"]}, PC)
    )


def setup_settlement_with_released_receipt(
    hauling_rate: int = 200,
    gross: int = 230000,
    tare: int = 30000,
    assay=None,
) -> dict:
    """Full settlement scenario: env + pool + one RELEASED receipt (with assay)
    + DRAFT settlement. Net weight = gross - tare.

    Returns dict: producer, hauler, permit, pool, receipt, settlement.
    """
    env = setup_intake_env(hauling_rate=hauling_rate, pool=True)
    receipt = setup_released_receipt(
        env["producer"]["id"], env["hauler"]["id"],
        gross=gross, tare=tare, assay=assay if assay is not None else {},
    )
    settlement = make_settlement(env["producer"]["id"])
    return {**env, "receipt": receipt, "settlement": settlement}


# ─── Tier 4: Pasteurizer runs, CIP, batches ───────────

def make_run(**overrides) -> dict:
    return get_success_data(
        api_client.create_pasteurizer_run(create_pasteurizer_run_payload(**overrides), OP)
    )


def make_cip_cycle(run_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_cip_cycle(run_id, create_cip_cycle_payload(**overrides), OP)
    )


def validate_cip(run_id: str, cip_id: str) -> dict:
    return get_success_data(api_client.validate_cip_cycle(run_id, cip_id, {}, QA))


def fail_cip(run_id: str, cip_id: str) -> dict:
    return get_success_data(api_client.fail_cip_cycle(run_id, cip_id, {}, QA))


def setup_validated_cip(run_id: str, **cip_overrides) -> dict:
    """Record a passing CIP cycle for the run and validate it (VALIDATED/PASS)."""
    cip = make_cip_cycle(run_id, **cip_overrides)
    return validate_cip(run_id, cip["id"])


def setup_running_run(
    pasteurizer_id: str = "HTST-1",
    start: str = "2026-05-10T08:00:00Z",
    end: str = "2026-05-10T12:00:00Z",
    clock: str = "2026-05-10T06:00:00Z",
    with_permit: bool = True,
) -> dict:
    """Run walked to RUNNING: clock set, (optional) ACTIVE permit, run created,
    passing CIP validated, run started. Returns the started run."""
    set_clock(clock)
    if with_permit:
        make_permit()
    run = make_run(
        pasteurizer_id=pasteurizer_id,
        scheduled_start_at=start,
        scheduled_end_at=end,
    )
    setup_validated_cip(run["id"], started_at=clock)
    return get_success_data(api_client.start_pasteurizer_run(run["id"], {}, OP))


def make_batch(run_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_batch(run_id, create_batch_payload(**overrides), OP)
    )


def get_batch(run_id: str, batch_id: str) -> dict:
    batches = get_success_data(api_client.list_batches(run_id, OP))
    for batch in batches:
        if batch["id"] == batch_id:
            return batch
    raise AssertionError(f"Setup failed: batch {batch_id} not found under run {run_id}")


# ─── Tier 5: Permit inspection lifecycle ──────────────

def setup_under_review_permit(score: int = 75, violations: int = 3, **permit_overrides) -> dict:
    """Permit driven ACTIVE → UNDER_REVIEW via a failing inspection."""
    permit = make_permit(**permit_overrides)
    res = api_client.record_inspection(
        permit["id"], {"inspection_score": score, "violations_found": violations}, SI
    )
    return get_success_data(res)
