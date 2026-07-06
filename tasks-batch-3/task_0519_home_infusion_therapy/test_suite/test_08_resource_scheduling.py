"""Resource scheduling overlaps: the pump's trailing-only half-open buffer and the
nurse's symmetric closed-interval buffer — two deliberately distinct geometries.

Translates Queue A (Difficulty) rule: resource_temporal_overlap.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visiting_nurse_headers,
    fixtures,
    factories as F,
)

PHARM = TEST_USERS["pharmacist_headers"]

VANCO_NONSPEC = {
    "therapy_category": "AMINOGLYCOSIDE_OR_VANCO",
    "vial_size_mg": 1000,
    "awp_per_vial_cents": 4250,
    "is_specialty": False,
}
PA_PLAN = {
    "per_diem_rate_cents": {"AMINOGLYCOSIDE_OR_VANCO": 12500},
    "awp_discount_pct": 0.18,
    "coinsurance_pct": 0.20,
    "deductible_remaining_cents": 30000,
    "oop_max_remaining_cents": 50000,
}
CEF_NONSPEC = {
    "therapy_category": "ANTI_INFECTIVE",
    "vial_size_mg": 1000,
    "awp_per_vial_cents": 2000,
    "is_specialty": False,
}
PB_PLAN = {
    "per_diem_rate_cents": {"ANTI_INFECTIVE": 12500},
    "awp_discount_pct": 0.10,
    "coinsurance_pct": 0.20,
    "deductible_remaining_cents": 10000,
    "oop_max_remaining_cents": 500000,
}


# === resource_temporal_overlap / pump_trailing_buffer_overlap_asymmetric ===
def test_pump_reservation_inside_trailing_buffer_conflicts(api):
    """PRD 3.5: "A candidate compound conflicts with such an existing reservation when the candidate's `delivery_at` falls strictly before the existing reservation's `retrieval_at` plus the 1,440-minute buffer, and at the same time the candidate's `retrieval_at` falls strictly after the existing reservation's `delivery_at`."

    Design: Difficulty/resource_temporal_overlap/pump_trailing_buffer_overlap_asymmetric
    """
    # existing [06-10 09:00, 06-17 09:00); buffer 1440min -> effective end 06-18 09:00.
    # new delivery 06-18 08:59 is one minute inside the trailing buffer => conflict.
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**VANCO_NONSPEC, "lot_total_vials": 200},
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 7},
    )
    pump = fixtures.create_pump()
    c1 = validate_success(
        api.create_compound(
            F.create_compound_payload(
                order_id=ctx["order"]["id"], pump_id=pump["id"],
                delivery_at="2026-06-10T09:00:00Z", retrieval_at="2026-06-17T09:00:00Z",
            ),
            PHARM,
        ),
        expected_status=201,
    )
    validate_success(api.compound_compound(c1["id"], PHARM))
    c2 = validate_success(
        api.create_compound(
            F.create_compound_payload(
                order_id=ctx["order"]["id"], pump_id=pump["id"],
                delivery_at="2026-06-18T08:59:00Z", retrieval_at="2026-06-25T08:59:00Z",
            ),
            PHARM,
        ),
        expected_status=201,
    )
    resp = api.compound_compound(c2["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_PUMP_DOUBLE_BOOKED.value)
    c2_now = validate_success(api.get_compound(c2["id"], PHARM))
    assert c2_now["status"] == "ORDERED", "rejected compound stays ORDERED, no vials reserved"


def test_pump_reservation_at_buffer_boundary_is_allowed(api):
    """PRD 3.5: "a new reservation whose `delivery_at` is exactly at the existing `retrieval_at` plus the buffer does not conflict — the boundary is inclusive on the start side, so starting precisely when the buffer ends is allowed."

    Design: Difficulty/resource_temporal_overlap/pump_trailing_buffer_overlap_asymmetric
    """
    # existing [06-10 09:00, 06-17 09:00); buffer ends 06-18 09:00. New delivery exactly
    # 06-18 09:00 is allowed (>=, not >).
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**VANCO_NONSPEC, "lot_total_vials": 200},
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 7},
    )
    pump = fixtures.create_pump()
    c1 = validate_success(
        api.create_compound(
            F.create_compound_payload(
                order_id=ctx["order"]["id"], pump_id=pump["id"],
                delivery_at="2026-06-10T09:00:00Z", retrieval_at="2026-06-17T09:00:00Z",
            ),
            PHARM,
        ),
        expected_status=201,
    )
    validate_success(api.compound_compound(c1["id"], PHARM))
    c2 = validate_success(
        api.create_compound(
            F.create_compound_payload(
                order_id=ctx["order"]["id"], pump_id=pump["id"],
                delivery_at="2026-06-18T09:00:00Z", retrieval_at="2026-06-25T09:00:00Z",
            ),
            PHARM,
        ),
        expected_status=201,
    )
    resp = api.compound_compound(c2["id"], PHARM)
    data = validate_success(resp)
    assert data["status"] == "COMPOUNDED", "start exactly at buffer end does not conflict"


# === resource_temporal_overlap / nurse_symmetric_travel_buffer_overlap_closed ===
def test_nurse_visit_inside_travel_buffer_conflicts(api):
    """PRD 3.6: "A candidate conflicts when the candidate's `start_at` falls before the existing visit's `start_at` plus its `duration_min` plus 60 minutes, and at the same time the candidate's `start_at` plus its `duration_min` plus 60 minutes falls after the existing visit's `start_at`. A detected overlap is rejected with `ERR_NURSE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/nurse_symmetric_travel_buffer_overlap_closed
    """
    # v1 06-12 10:00 dur 120 -> ends 12:00, buffered end 13:00. v2 at 12:59 < 13:00 conflicts.
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**CEF_NONSPEC}, plan_overrides=PB_PLAN,
        order_overrides={"daily_dose_mg": 1000, "scheduled_days": 5},
    )
    nurse = fixtures.add_nurse(ctx)
    nid = nurse["id"]
    fixtures.schedule_visit(
        ctx["order"]["id"], nid, start_at="2026-06-12T10:00:00Z", duration_min=120
    )
    resp = api.create_visit(
        F.create_visit_payload(
            order_id=ctx["order"]["id"], nurse_id=nid,
            start_at="2026-06-12T12:59:00Z", duration_min=60,
        ),
        make_visiting_nurse_headers(nid),
    )
    validate_error(resp, ApiErrorId.ERR_NURSE_DOUBLE_BOOKED.value)


def test_nurse_visit_outside_travel_buffer_allowed(api):
    """PRD 3.6: "a visit occupies the **closed** interval from its `start_at` through `start_at` plus its `duration_min`, expanded by a **symmetric** travel buffer of 60 minutes on **both** ends."

    Design: Difficulty/resource_temporal_overlap/nurse_symmetric_travel_buffer_overlap_closed
    """
    # v1 06-12 10:00 dur 120 -> buffered end 13:00. v2 starting exactly 13:00 is allowed
    # (the candidate's start is not before existing.start+dur+60).
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**CEF_NONSPEC}, plan_overrides=PB_PLAN,
        order_overrides={"daily_dose_mg": 1000, "scheduled_days": 5},
    )
    nurse = fixtures.add_nurse(ctx)
    nid = nurse["id"]
    fixtures.schedule_visit(
        ctx["order"]["id"], nid, start_at="2026-06-12T10:00:00Z", duration_min=120
    )
    resp = api.create_visit(
        F.create_visit_payload(
            order_id=ctx["order"]["id"], nurse_id=nid,
            start_at="2026-06-12T13:00:00Z", duration_min=60,
        ),
        make_visiting_nurse_headers(nid),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"
