"""Resource-scheduling overlap geometries: sequencer runs (closed interval +
turnaround buffer) and counselor slots (half-open, no buffer), with both the
conflicting and boundary-allowed sides.

Translates queue A resource_temporal_overlap/{sequencer_run_closed_interval_buffer_conflict,
counselor_slot_half_open_overlap_conflict}, plus queue B
calculations/{sequencer_run_exact_buffer_gap_allowed, counselor_slot_adjacency_allowed}.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ApiErrorId

DIRECTOR = TEST_USERS["director_headers"]
ACCESSIONING = TEST_USERS["accessioning_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]


def test_sequencer_run_closed_buffer_conflict(api):
    """PRD §3.12: "Letting B be the instrument's `turnaround_buffer_minutes`, two
    runs are clear of each other only if the new run's end plus B is at or before
    the existing run's start, or the existing run's end plus B is at or before the
    new run's start; if neither of those holds, they conflict. ... A conflicting
    run is rejected with `ERR_RUN_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/sequencer_run_closed_interval_buffer_conflict
    """
    FX.set_clock()
    seq = FX.create_sequencer(instrument_name="NovaSeq-A", turnaround_buffer_minutes=60)
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", gene_symbols=("GS1",), name="PS1")
    FX.schedule_run(seq["id"], ctx["order"]["id"],
                    "2026-06-20T10:00:00.000Z", "2026-06-20T12:00:00.000Z")
    # New [12:30,13:30] is only 30 min after existing end 12:00 < buffer 60 -> conflict.
    resp = api.schedule_run(seq["id"],
                            F.schedule_run_payload(ctx["order"]["id"],
                                                   "2026-06-20T12:30:00.000Z",
                                                   "2026-06-20T13:30:00.000Z"),
                            ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_RUN_WINDOW_CONFLICT.value, 409)


def test_sequencer_run_exact_buffer_gap_allowed(api):
    """PRD §3.12: "two runs are clear of each other only if the new run's end plus B
    is at or before the existing run's start, or the existing run's end plus B is
    at or before the new run's start."

    Design: Corner/calculations/sequencer_run_exact_buffer_gap_allowed
    """
    FX.set_clock()
    seq = FX.create_sequencer(instrument_name="NovaSeq-GAP", turnaround_buffer_minutes=60)
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GCALC7",), name="CALC7")
    FX.schedule_run(seq["id"], ctx["order"]["id"],
                    "2026-06-20T10:00:00.000Z", "2026-06-20T12:00:00.000Z")
    # New [13:00,14:00]: existing end 12:00 + 60 == 13:00 (at-or-before) -> allowed.
    resp = api.schedule_run(seq["id"],
                            F.schedule_run_payload(ctx["order"]["id"],
                                                   "2026-06-20T13:00:00.000Z",
                                                   "2026-06-20T14:00:00.000Z"),
                            ACCESSIONING)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_counselor_slot_half_open_overlap_conflict(api):
    """PRD §3.12: "the server rejects it if there is another referral for the
    **same** `counselor_id`, in `SCHEDULED` status, whose half-open interval
    `[slot_start, slot_end)` overlaps the new `[slot_start, slot_end)`. Two
    half-open intervals overlap when the new slot's start is before the existing
    slot's end and the existing slot's start is before the new slot's end. ... A
    conflicting slot is rejected with `ERR_COUNSELOR_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/counselor_slot_half_open_overlap_conflict
    """
    FX.set_clock()
    gc = FX.create_counselor("GC Solo")
    ctx1 = FX.setup_ordered(gene_symbols=("GC1",), name="PC1")
    ref1 = FX.request_referral(ctx1["order"]["id"], gc["id"])
    FX.schedule_referral(ctx1["order"]["id"], ref1["id"],
                         "2026-06-25T10:00:00.000Z", "2026-06-25T11:00:00.000Z")
    # Second order/referral to the same counselor; slot [10:30,11:30) overlaps -> conflict.
    panel = ctx1["panel"]
    provider = ctx1["provider"]
    order2 = FX.place_order(panel["id"], provider["id"], patient_mrn="MRN-Q")
    ref2 = FX.request_referral(order2["id"], gc["id"])
    resp = api.schedule_referral(order2["id"], ref2["id"],
                                 F.schedule_referral_payload("2026-06-25T10:30:00.000Z",
                                                             "2026-06-25T11:30:00.000Z"),
                                 COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_COUNSELOR_SLOT_CONFLICT.value, 409)
    ref2_re = validate_success(api.get_referral(ref2["id"], DIRECTOR), 200)
    assert ref2_re["status"] == "REQUESTED"


def test_counselor_slot_adjacency_allowed(api):
    """PRD §3.12: "Because the interval is half-open and there is no buffer, adjacency
    is allowed: a new slot whose start equals an existing slot's end does **not**
    conflict."

    Design: Corner/calculations/counselor_slot_adjacency_allowed
    """
    FX.set_clock()
    gc = FX.create_counselor("GC Adj")
    ctx1 = FX.setup_ordered(gene_symbols=("GCALC8",), name="CALC8")
    ref1 = FX.request_referral(ctx1["order"]["id"], gc["id"])
    FX.schedule_referral(ctx1["order"]["id"], ref1["id"],
                         "2026-06-25T10:00:00.000Z", "2026-06-25T11:00:00.000Z")
    order2 = FX.place_order(ctx1["panel"]["id"], ctx1["provider"]["id"], patient_mrn="MRN-Q2")
    ref2 = FX.request_referral(order2["id"], gc["id"])
    # New [11:00,12:00): start == existing end 11:00 -> adjacency allowed.
    resp = api.schedule_referral(order2["id"], ref2["id"],
                                 F.schedule_referral_payload("2026-06-25T11:00:00.000Z",
                                                             "2026-06-25T12:00:00.000Z"),
                                 COUNSELOR)
    data = validate_success(resp, 200)
    assert data["status"] == "SCHEDULED"


def test_sequencer_run_touching_intervals_conflict(api):
    """PRD §3.12: "Because the interval is closed and the comparison is at-or-before
    rather than strictly-before, two runs that merely touch (the new run starting
    exactly when the existing one ends) do conflict."

    Design: Difficulty/resource_temporal_overlap/sequencer_run_closed_interval_buffer_conflict
    """
    FX.set_clock()
    seq = FX.create_sequencer(instrument_name="NovaSeq-T", turnaround_buffer_minutes=60)
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", gene_symbols=("GS2",), name="PS2")
    FX.schedule_run(seq["id"], ctx["order"]["id"],
                    "2026-06-20T10:00:00.000Z", "2026-06-20T12:00:00.000Z")
    # New [12:00,13:00] touches existing end 12:00 (and is within buffer) -> conflict.
    resp = api.schedule_run(seq["id"],
                            F.schedule_run_payload(ctx["order"]["id"],
                                                   "2026-06-20T12:00:00.000Z",
                                                   "2026-06-20T13:00:00.000Z"),
                            ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_RUN_WINDOW_CONFLICT.value, 409)


def test_counselor_slot_containment_overlap_conflict(api):
    """PRD §3.12: "Two half-open intervals overlap when the new slot's start is
    before the existing slot's end and the existing slot's start is before the new
    slot's end. ... A conflicting slot is rejected with
    `ERR_COUNSELOR_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/counselor_slot_half_open_overlap_conflict
    """
    FX.set_clock()
    gc = FX.create_counselor("GC Contain")
    ctx1 = FX.setup_ordered(gene_symbols=("GC3",), name="PC3")
    ref1 = FX.request_referral(ctx1["order"]["id"], gc["id"])
    FX.schedule_referral(ctx1["order"]["id"], ref1["id"],
                         "2026-06-25T10:00:00.000Z", "2026-06-25T12:00:00.000Z")
    order2 = FX.place_order(ctx1["panel"]["id"], ctx1["provider"]["id"], patient_mrn="MRN-CN")
    ref2 = FX.request_referral(order2["id"], gc["id"])
    # New [10:30,11:00) fully inside existing [10:00,12:00) -> overlaps -> conflict.
    resp = api.schedule_referral(order2["id"], ref2["id"],
                                 F.schedule_referral_payload("2026-06-25T10:30:00.000Z",
                                                             "2026-06-25T11:00:00.000Z"),
                                 COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_COUNSELOR_SLOT_CONFLICT.value, 409)
