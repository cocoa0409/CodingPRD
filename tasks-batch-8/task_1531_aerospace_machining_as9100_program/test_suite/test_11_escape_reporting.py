"""Post-shipment escape reports: spawn, 48-hour window, NCR close gate (PRD §3.7)."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_escape_report,
    assert_ncr,
    create_ncr,
    disposition_ncr,
    get_escape_report_for_ncr,
    get_success_data,
    set_clock,
    setup_ncr_in_mrb,
    setup_shipped_serial,
    setup_wo_completed,
    validate_error,
    validate_success,
)

MP = TEST_USERS["manufacturing_planner"]
QI = TEST_USERS["quality_inspector"]
QI2 = TEST_USERS["quality_inspector_2"]
QM = TEST_USERS["quality_manager"]
CQR = TEST_USERS["customer_quality_rep"]


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_verified_escape_ncr():
    """Ship one unit, then open a post-shipment NCR and walk it to VERIFIED
    (USE_AS_IS + recorded concession). Returns (bundle, ncr)."""
    bundle = setup_shipped_serial(wo_quantity=1, quantity=1)
    serial = bundle["serials"][0]
    ncr = setup_ncr_in_mrb(
        bundle["wo"]["id"],
        defect_code="FIELD_FAILURE",
        description="customer reports crack",
        quantity_affected=1,
        affected_serial_ids=[serial["id"]],
        detected_post_shipment=True,
    )
    disposition_ncr(
        ncr["id"],
        disposition="USE_AS_IS",
        rework_hours_per_unit=0.1,
        material_cost_per_unit_cents=0,
    )
    validate_success(
        api_client.record_customer_concession(
            ncr["id"], {"concession_reference": "CONC-2026-001"}, CQR
        )
    )
    verified = validate_success(api_client.verify_ncr(ncr["id"], {}, QI2))
    assert verified["status"] == "VERIFIED"
    return bundle, verified


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / ncr_close_requires_escape_acknowledged
# ---------------------------------------------------------------------------

def test_ncr_close_blocked_while_escape_draft(api):
    """PRD §3.7: "Closure moves `VERIFIED → CLOSED` under a `QualityManager`,
    from that state only (`ERR_INVALID_STATE` otherwise), with one escape
    gate: when `detected_post_shipment` is true, the linked escape report must
    already be `ACKNOWLEDGED`, failing with `ERR_ESCAPE_NOT_ACKNOWLEDGED`
    otherwise."

    Design: Difficulty/cross_entity_state_dependency/ncr_close_requires_escape_acknowledged
    """
    bundle, ncr = _setup_verified_escape_ncr()
    escape = get_escape_report_for_ncr(ncr["id"])
    assert escape["status"] == "DRAFT"
    resp = api_client.close_ncr(ncr["id"], QM)
    validate_error(resp, ApiErrorId.ERR_ESCAPE_NOT_ACKNOWLEDGED.value)


def test_ncr_close_succeeds_after_escape_acknowledged(api):
    """PRD §3.7: "Closure moves `VERIFIED → CLOSED` under a `QualityManager`,
    from that state only (`ERR_INVALID_STATE` otherwise), with one escape
    gate: when `detected_post_shipment` is true, the linked escape report must
    already be `ACKNOWLEDGED`, failing with `ERR_ESCAPE_NOT_ACKNOWLEDGED`
    otherwise."
    PRD §3.7: "A `QualityManager` submits — `DRAFT → SUBMITTED` — from `DRAFT`
    only (`ERR_INVALID_STATE` otherwise), and the submission must land within
    the window: the current logical clock at or before `due_at`, the 48-hour
    boundary being inclusive; a later attempt is rejected with
    `ERR_ESCAPE_WINDOW_EXCEEDED` (422). A successful submit stamps
    `submitted_at` with the logical clock. A `CustomerQualityRep` then
    acknowledges — `SUBMITTED → ACKNOWLEDGED`, the terminal state — supplying
    an `acknowledgement_reference`, from `SUBMITTED` only (`ERR_INVALID_STATE`
    otherwise)."

    Design: Difficulty/cross_entity_state_dependency/ncr_close_requires_escape_acknowledged
    """
    bundle, ncr = _setup_verified_escape_ncr()
    escape = get_escape_report_for_ncr(ncr["id"])
    validate_success(api_client.submit_escape_report(escape["id"], QM))
    acked = validate_success(
        api_client.acknowledge_escape_report(
            escape["id"], {"acknowledgement_reference": "ACK-001"}, CQR
        )
    )
    assert acked["status"] == "ACKNOWLEDGED"
    closed = validate_success(api_client.close_ncr(ncr["id"], QM))
    assert_ncr(closed)
    assert closed["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Corner: validations / escape_submit_window_boundary
# ---------------------------------------------------------------------------

def test_escape_submit_window_boundary(api):
    """PRD §3.7: "A `QualityManager` submits — `DRAFT → SUBMITTED` — from
    `DRAFT` only (`ERR_INVALID_STATE` otherwise), and the submission must land
    within the window: the current logical clock at or before `due_at`, the
    48-hour boundary being inclusive; a later attempt is rejected with
    `ERR_ESCAPE_WINDOW_EXCEEDED` (422)."
    PRD §3.7: "When `detected_post_shipment` is true, creation also spawns a
    `DRAFT` escape report whose `due_at` is exactly 48 hours after the
    report's `created_at`."

    Design: Corner/validations/escape_submit_window_boundary
    """
    bundle = setup_wo_completed(wo_quantity=2, quantity=2)
    s1, s2 = bundle["serials"][0], bundle["serials"][1]
    get_success_data(api_client.ship_serial(s1["id"], MP))
    get_success_data(api_client.ship_serial(s2["id"], MP))
    ncr1 = create_ncr(
        bundle["wo"]["id"], defect_code="FIELD_1", description="escape one",
        quantity_affected=1, affected_serial_ids=[s1["id"]],
        detected_post_shipment=True,
    )
    ncr2 = create_ncr(
        bundle["wo"]["id"], defect_code="FIELD_2", description="escape two",
        quantity_affected=1, affected_serial_ids=[s2["id"]],
        detected_post_shipment=True,
    )
    er1 = get_escape_report_for_ncr(ncr1["id"])
    er2 = get_escape_report_for_ncr(ncr2["id"])

    # Both reports were spawned at the default clock 2026-08-01T00:00:00Z, so
    # due_at is 2026-08-03T00:00:00Z; submitting exactly at the boundary works.
    set_clock("2026-08-03T00:00:00Z")
    submitted = validate_success(api_client.submit_escape_report(er1["id"], QM))
    assert_escape_report(submitted)
    assert submitted["status"] == "SUBMITTED", (
        "the 48-hour boundary is inclusive: submit at exactly due_at succeeds"
    )
    assert submitted.get("submitted_at"), "submit stamps submitted_at"

    # One second past due_at the window has closed.
    set_clock("2026-08-03T00:00:01Z")
    resp = api_client.submit_escape_report(er2["id"], QM)
    validate_error(resp, ApiErrorId.ERR_ESCAPE_WINDOW_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / ncr_post_shipment_spawns_escape_draft
# ---------------------------------------------------------------------------

def test_ncr_post_shipment_spawns_escape_draft(api):
    """PRD §3.7: "When `detected_post_shipment` is true, creation also spawns
    a `DRAFT` escape report whose `due_at` is exactly 48 hours after the
    report's `created_at`."
    PRD §3.7: "Escape reports carry the customer's statutory notification.
    Each report links back to its originating nonconformance via `ncr_id`,
    with `due_at` fixed at creation as described above."

    Design: Corner/cross_cutting_layers/ncr_post_shipment_spawns_escape_draft
    """
    bundle = setup_shipped_serial(wo_quantity=1, quantity=1)
    serial = bundle["serials"][0]
    ncr = create_ncr(
        bundle["wo"]["id"],
        defect_code="FIELD_CRACK",
        description="crack found in service",
        quantity_affected=1,
        affected_serial_ids=[serial["id"]],
        detected_post_shipment=True,
    )
    listed = get_success_data(
        api_client.list_escape_reports(QM, params={"ncr_id": ncr["id"]})
    )
    assert isinstance(listed, list) and len(listed) == 1, (
        f"exactly one escape report must be spawned, got {len(listed)}"
    )
    escape = listed[0]
    assert_escape_report(escape)
    assert escape["ncr_id"] == ncr["id"]
    assert escape["status"] == "DRAFT"
    delta = _parse_ts(escape["due_at"]) - _parse_ts(ncr["created_at"])
    assert delta == timedelta(hours=48), (
        f"due_at must be exactly 48 hours after the NCR's created_at, got "
        f"{delta}"
    )
