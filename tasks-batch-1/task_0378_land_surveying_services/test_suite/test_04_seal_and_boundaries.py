"""Boundary-precision gates, cross-entity state dependencies, and resource
temporal-overlap conflicts: the closure-tolerance ceiling at sealing, the
zero-encumbrance research-clear edge, the order/packet and deliverable/invoice
cross-entity guards, half-open crew double-booking, and buffered instrument
reservation overlap.

Difficulty queue: boundary_precision_check, cross_entity_state_dependency,
resource_temporal_overlap.
"""
from test_helpers import (
    fixtures as fx,
    make_coordinator_headers,
    make_researcher_headers,
    make_surveyor_headers,
    create_field_assignment_payload,
    create_instrument_payload,
    create_instrument_reservation_payload,
    seal_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    ApiErrorId,
)


# ════════════════════════════════════════════════════════════════════════
# Difficulty/boundary_precision_check/closure_ppm_exactly_at_max_seals_one_over_rejected
# ════════════════════════════════════════════════════════════════════════
def test_closure_ppm_exactly_at_max_seals(api):
    """PRD §3.5: "the source dataset's traverse closure error must be within
    tolerance: `closure_error_ppm` must be at most one hundred parts-per-million —
    a closure error of exactly one hundred seals, one hundred one is too coarse and
    is rejected with `ERR_CLOSURE_OUT_OF_TOLERANCE`."

    A dataset with closure_error_ppm exactly 100 (== the inclusive ceiling) seals
    successfully, advancing the order to SEALED.

    Design: Difficulty/boundary_precision_check/closure_ppm_exactly_at_max_seals_one_over_rejected
    """
    ctx = fx.plat_under_review(survey_type="BOUNDARY", acreage=3, rush=False,
                               recorded_by="tech", closure_error_ppm=100)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    pls_id = crew["pls"]["id"]
    ov = fx.order_version(ctx)

    sealed = validate_success(
        api.seal_plat(ctx["plat_id"], seal_payload(pls_id, ov), make_surveyor_headers(pls_id)), 200)
    assert sealed["status"] == "SEALED"
    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["status"] == "SEALED"


def test_closure_ppm_one_over_max_rejected(api):
    """PRD §3.5: "a closure error of exactly one hundred seals, one hundred one is
    too coarse and is rejected with `ERR_CLOSURE_OUT_OF_TOLERANCE`."

    A dataset with closure_error_ppm 101 (one over the ceiling) cannot be sealed:
    the seal is rejected with ERR_CLOSURE_OUT_OF_TOLERANCE and the plat stays
    UNDER_REVIEW.

    Design: Difficulty/boundary_precision_check/closure_ppm_exactly_at_max_seals_one_over_rejected
    """
    ctx = fx.plat_under_review(survey_type="BOUNDARY", acreage=3, rush=False,
                               recorded_by="tech", closure_error_ppm=101)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    pls_id = crew["pls"]["id"]
    ov = fx.order_version(ctx)

    resp = api.seal_plat(ctx["plat_id"], seal_payload(pls_id, ov), make_surveyor_headers(pls_id))
    validate_error(resp, ApiErrorId.ERR_CLOSURE_OUT_OF_TOLERANCE)
    plat = validate_success(api.get_plat_drawing(ctx["plat_id"], make_coordinator_headers(cid)), 200)
    assert plat["status"] == "UNDER_REVIEW"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/boundary_precision_check/research_clear_at_zero_encumbrance_hold_at_one
# ════════════════════════════════════════════════════════════════════════
def test_research_clear_rejected_at_one_encumbrance(api):
    """PRD §3.2: "Clearing is permitted **only** at exactly zero encumbrances;
    attempting to clear while `encumbrance_count` is one or more is rejected with
    `ERR_TITLE_NOT_CLEAR`."

    An IN_PROGRESS packet with encumbrance_count 1 cannot be cleared: clear is
    rejected with ERR_TITLE_NOT_CLEAR and the packet stays IN_PROGRESS.

    Design: Difficulty/boundary_precision_check/research_clear_at_zero_encumbrance_hold_at_one
    """
    ctx = fx.order_at_in_progress_packet(encumbrance_count=1, survey_type="BOUNDARY", acreage=3)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]
    pid = ctx["packet_id"]

    resp = api.clear_research_packet(pid, make_researcher_headers(rid))
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_CLEAR)
    packet = validate_success(api.get_research_packet(pid, make_coordinator_headers(cid)), 200)
    assert packet["status"] == "IN_PROGRESS"


def test_research_clear_succeeds_at_zero_encumbrance(api):
    """PRD §3.2: "If the investigation found no encumbrances — that is,
    `encumbrance_count` is exactly zero — the `Researcher` may clear it, moving the
    packet to `CLEARED` and, as a side effect, setting the parent order's
    `research_clear` flag to true."

    An IN_PROGRESS packet with encumbrance_count exactly 0 clears: status CLEARED
    and the order's research_clear becomes true.

    Design: Difficulty/boundary_precision_check/research_clear_at_zero_encumbrance_hold_at_one
    """
    ctx = fx.order_at_in_progress_packet(encumbrance_count=0, survey_type="BOUNDARY", acreage=3)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]
    pid = ctx["packet_id"]

    cleared = validate_success(api.clear_research_packet(pid, make_researcher_headers(rid)), 200)
    assert cleared["status"] == "CLEARED"
    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["research_clear"] is True


# ════════════════════════════════════════════════════════════════════════
# Difficulty/cross_entity_state_dependency/order_clear_research_requires_packet_cleared
# ════════════════════════════════════════════════════════════════════════
def test_clear_research_blocked_while_packet_in_progress(api):
    """PRD §3.2: "With title cleared, the `Coordinator` advances the order from
    `RESEARCH` to `FIELD_READY`. This transition is permitted only when the order's
    `research_clear` is true, which is the case only after the order's research
    packet reached `CLEARED`; it changes no fee."

    With the packet still IN_PROGRESS (research_clear false), clear-research is
    rejected; the order stays RESEARCH and research_clear stays false.

    The cited sentence names no error_id and §2.9 does not uniquely classify a
    research_clear-flag gate as "state-machine legality" vs a domain business rule,
    so either ERR_INVALID_STATE or the generic ERR_VALIDATION is a faithful reading.

    Design: Difficulty/cross_entity_state_dependency/order_clear_research_requires_packet_cleared
    """
    ctx = fx.order_at_in_progress_packet(encumbrance_count=0, survey_type="BOUNDARY", acreage=3)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]

    resp = api.clear_research(ctx["order_id"], make_coordinator_headers(cid))
    validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_VALIDATION])
    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["status"] == "RESEARCH"
    assert order["research_clear"] is False


def test_clear_research_succeeds_after_packet_cleared(api):
    """PRD §3.2: "With title cleared, the `Coordinator` advances the order from
    `RESEARCH` to `FIELD_READY`. This transition is permitted only when the order's
    `research_clear` is true, which is the case only after the order's research
    packet reached `CLEARED`; it changes no fee."

    Once the packet is CLEARED (research_clear true), clear-research advances the
    order RESEARCH->FIELD_READY.

    Design: Difficulty/cross_entity_state_dependency/order_clear_research_requires_packet_cleared
    """
    ctx = fx.order_at_in_progress_packet(encumbrance_count=0, survey_type="BOUNDARY", acreage=3)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]
    validate_success(api.clear_research_packet(ctx["packet_id"], make_researcher_headers(rid)), 200)

    advanced = validate_success(api.clear_research(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert advanced["status"] == "FIELD_READY"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/cross_entity_state_dependency/deliverable_release_requires_invoice_issued
# ════════════════════════════════════════════════════════════════════════
def test_deliverable_release_blocked_without_issued_invoice(api):
    """PRD §3.6: "That order delivery is gated on two cross-entity conditions: the
    released deliverable must reference a `SEALED` plat for the order, and the order
    must already have an `Invoice` whose `lifecycle_status` is `ISSUED`."

    With the only invoice still DRAFT, releasing an ASSEMBLED deliverable is rejected;
    the order stays SEALED and the deliverable stays ASSEMBLED.

    The cited sentence names no error_id; §2.9 calls cross-entity referential checks
    "business-referential" rules that run after state legality, so a faithful reader
    may surface either ERR_INVALID_STATE or the generic ERR_VALIDATION here.

    Design: Difficulty/cross_entity_state_dependency/deliverable_release_requires_invoice_issued
    """
    ctx = fx.draft_invoice_on_sealed_order(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    from test_helpers import create_deliverable_payload
    deliverable = validate_success(
        api.create_deliverable(create_deliverable_payload(ctx["order_id"], ctx["plat_id"], "PDF"),
                               make_coordinator_headers(cid)), 201)

    resp = api.release_deliverable(deliverable["id"], make_coordinator_headers(cid))
    validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_VALIDATION])
    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["status"] == "SEALED"
    after = validate_success(api.get_deliverable(deliverable["id"], make_coordinator_headers(cid)), 200)
    assert after["status"] == "ASSEMBLED"


def test_deliverable_release_succeeds_after_invoice_issued(api):
    """PRD §3.6: "Releasing the deliverable — a `Coordinator` action — moves it from
    `ASSEMBLED` to `RELEASED` (terminal) and drives the parent order from `SEALED` to
    `DELIVERED`."

    With an ISSUED invoice present, releasing the deliverable advances the order
    SEALED->DELIVERED.

    Design: Difficulty/cross_entity_state_dependency/deliverable_release_requires_invoice_issued
    """
    ctx = fx.issued_invoice(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    from test_helpers import create_deliverable_payload
    deliverable = validate_success(
        api.create_deliverable(create_deliverable_payload(ctx["order_id"], ctx["plat_id"], "PDF"),
                               make_coordinator_headers(cid)), 201)

    released = validate_success(api.release_deliverable(deliverable["id"], make_coordinator_headers(cid)), 200)
    assert released["status"] == "RELEASED"
    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["status"] == "DELIVERED"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/resource_temporal_overlap/crew_double_book_half_open_adjacency_allowed
# ════════════════════════════════════════════════════════════════════════
def test_crew_adjacent_assignment_allowed(api):
    """PRD §3.3: "Adjacency is allowed — an assignment whose start equals another's
    end does not overlap and is accepted."

    A TECH with a 09:00-13:00 assignment accepts a second 13:00-15:00 assignment
    (start == prior end, half-open intervals do not overlap).

    Design: Difficulty/resource_temporal_overlap/crew_double_book_half_open_adjacency_allowed
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    oid = ctx["order_id"]

    validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(oid, tid, "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    adjacent = validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(oid, tid, "2026-07-01T13:00:00.000Z", "2026-07-01T15:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    assert adjacent["status"] == "SCHEDULED"


def test_crew_overlapping_assignment_double_booked(api):
    """PRD §3.3: "if that member already holds another assignment in `SCHEDULED` or
    `IN_PROGRESS` status whose half-open interval from its start (inclusive) to its
    end (exclusive) overlaps this one, the request is rejected with
    `ERR_CREW_DOUBLE_BOOKED`."

    A TECH with a 09:00-13:00 assignment is rejected on a truly overlapping
    12:00-14:00 window with ERR_CREW_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/crew_double_book_half_open_adjacency_allowed
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    oid = ctx["order_id"]

    validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(oid, tid, "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    resp = api.create_field_assignment(
        create_field_assignment_payload(oid, tid, "2026-07-01T12:00:00.000Z", "2026-07-01T14:00:00.000Z"),
        make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)


# ════════════════════════════════════════════════════════════════════════
# Difficulty/resource_temporal_overlap/instrument_reservation_buffered_interval_conflict
# ════════════════════════════════════════════════════════════════════════
def test_instrument_reservation_buffered_overlap_rejected(api):
    """PRD §3.3: "if any other `HELD` reservation exists whose window, after being
    expanded by a turnaround buffer on each side, overlaps this window, the request
    is rejected with `ERR_INSTRUMENT_UNAVAILABLE`; the buffer is a sixty-minute
    turnaround pad applied symmetrically before the start and after the end of each
    reservation interval when testing for overlap."

    An instrument HELD for 09:00-13:00 cannot be reserved again for 14:30-16:00:
    the 60-minute buffers ([08:00,14:00) vs [13:30,17:00)) overlap, so the second
    reservation is rejected with ERR_INSTRUMENT_UNAVAILABLE and the instrument stays
    RESERVED.

    Design: Difficulty/resource_temporal_overlap/instrument_reservation_buffered_interval_conflict
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    oid = ctx["order_id"]
    # A second TECH so the second assignment is not itself crew-double-booked.
    tech2 = fx.make_crew(cid, "TECH")
    instrument = validate_success(
        api.create_instrument(create_instrument_payload(instrument_type="SCANNER"),
                              make_coordinator_headers(cid)), 201)
    instr_id = instrument["id"]

    fa1 = validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(oid, tid, "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    validate_success(
        api.create_instrument_reservation(
            create_instrument_reservation_payload(fa1["id"], instr_id), make_coordinator_headers(cid)), 201)
    fa2 = validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(oid, tech2["id"], "2026-07-01T14:30:00.000Z", "2026-07-01T16:00:00.000Z"),
            make_coordinator_headers(cid)), 201)

    resp = api.create_instrument_reservation(
        create_instrument_reservation_payload(fa2["id"], instr_id), make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_UNAVAILABLE)
    after = validate_success(api.get_instrument(instr_id, make_coordinator_headers(cid)), 200)
    assert after["status"] == "RESERVED"


def test_instrument_reservation_outside_buffer_succeeds(api):
    """PRD §3.3: "if any other `HELD` reservation exists whose window, after being
    expanded by a turnaround buffer on each side, overlaps this window, the request
    is rejected with `ERR_INSTRUMENT_UNAVAILABLE`; the buffer is a sixty-minute
    turnaround pad applied symmetrically before the start and after the end of each
    reservation interval when testing for overlap."
    PRD §3.3: "On success the reservation's `status` is `HELD` and the instrument's
    `status` flips from `AVAILABLE` to `RESERVED`."

    An instrument HELD for 09:00-13:00 (buffered to [08:00,14:00)) CAN be reserved
    again for 15:00-17:00 (buffered to [14:00,18:00)): the buffered windows are
    adjacent at 14:00 and do not overlap, so the second reservation succeeds (HELD).

    Design: Difficulty/resource_temporal_overlap/instrument_reservation_buffered_interval_conflict
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    oid = ctx["order_id"]
    tech2 = fx.make_crew(cid, "TECH")
    instrument = validate_success(
        api.create_instrument(create_instrument_payload(instrument_type="SCANNER"),
                              make_coordinator_headers(cid)), 201)
    instr_id = instrument["id"]

    fa1 = validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(oid, tid, "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    validate_success(
        api.create_instrument_reservation(
            create_instrument_reservation_payload(fa1["id"], instr_id), make_coordinator_headers(cid)), 201)
    fa2 = validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(oid, tech2["id"], "2026-07-01T15:00:00.000Z", "2026-07-01T17:00:00.000Z"),
            make_coordinator_headers(cid)), 201)

    second = validate_success(
        api.create_instrument_reservation(
            create_instrument_reservation_payload(fa2["id"], instr_id), make_coordinator_headers(cid)), 201)
    assert second["status"] == "HELD"
