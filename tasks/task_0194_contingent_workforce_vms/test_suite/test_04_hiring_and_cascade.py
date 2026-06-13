"""Hiring: the fill cascade, OCC version guard, worker double-booking, and the
close/cancel cascades (§3.5, §3.2, §2.7).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    get_success_data, make_supplier_headers, TEST_USERS,
    create_program, create_supplier, create_worker, create_requisition,
    distribute, create_submittal, setup_distributed_requisition,
    setup_submitted_submittal, setup_offered_submittal, setup_active_assignment,
)
from test_helpers import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]


def _advance_to_offered(api, req_id, sub_id, sh, pay=8000):
    get_success_data(api.shortlist_submittal(sub_id, HM))
    get_success_data(api.start_interview(sub_id, HM))
    get_success_data(api.propose_rate(sub_id, {"pay_rate_cents": pay}, sh))
    get_success_data(api.offer_submittal(sub_id, HM))


def _dist_for_supplier(api, req_id, supplier_id):
    dists, _ = validate_paginated(api.list_distributions(PM, params={"requisition_id": req_id}))
    matches = [d for d in dists if d["supplier_id"] == supplier_id]
    assert len(matches) == 1
    return matches[0]


# ===========================================================================
# Queue A: transitive_cascade / hire_fills_requisition_revokes_distributions_and_rejects_siblings
# ===========================================================================

def test_hire_filling_requisition_drives_filled_and_rejects_sibling(api):
    """PRD §3.5: "If that increment brings `filled_count` up to `openings`, the
    requisition is driven from `DISTRIBUTED` to `FILLED`; on that transition the
    system revokes every still-`PENDING` or `RELEASED` distribution (status to
    `REVOKED`) and rejects every remaining non-terminal submittal on the
    requisition (status to `REJECTED`)."

    openings 1, two suppliers/submittals; hiring A drives FILLED and rejects
    sibling B.

    Design: Difficulty/transitive_cascade/hire_fills_requisition_revokes_distributions_and_rejects_siblings
    """
    program = create_program()
    s1 = create_supplier(program["id"], name="S1", tier=1)
    s2 = create_supplier(program["id"], name="S2", tier=1)
    wkr_a = create_worker(program["id"], full_name="W A", national_id_hash="ha")
    wkr_b = create_worker(program["id"], full_name="W B", national_id_hash="hb")
    req = create_requisition(program["id"], openings=1, tier_release_interval_hours=0)
    dist = distribute(req["id"], [s1["id"], s2["id"]])
    sub_a = create_submittal(req["id"], s1["id"], wkr_a["id"], pay_rate_cents=8000)
    create_submittal(req["id"], s2["id"], wkr_b["id"], pay_rate_cents=8000)
    sh1 = make_supplier_headers(s1["id"])
    _advance_to_offered(api, req["id"], sub_a["id"], sh1)
    req_now = get_success_data(api.get_requisition(req["id"], PM))
    get_success_data(api.hire_submittal(
        sub_a["id"],
        F.hire_payload(req_now["version"], "2026-01-01T00:00:00.000Z",
                       "2026-06-01T00:00:00.000Z"),
        PM,
    ))
    req_after = get_success_data(api.get_requisition(req["id"], PM))
    assert req_after["status"] == "FILLED", f"got {req_after['status']}"
    assert req_after["filled_count"] == 1
    d2 = _dist_for_supplier(api, req["id"], s2["id"])
    assert d2["status"] == "REVOKED", f"got {d2['status']}"


def test_hire_filling_requisition_rejects_remaining_submittal(api):
    """PRD §3.5: "the system ... rejects every remaining non-terminal submittal
    on the requisition (status to `REJECTED`)."

    The sibling submittal B is REJECTED after the fill cascade.

    Design: Difficulty/transitive_cascade/hire_fills_requisition_revokes_distributions_and_rejects_siblings
    """
    program = create_program()
    s1 = create_supplier(program["id"], name="S1", tier=1)
    s2 = create_supplier(program["id"], name="S2", tier=1)
    wkr_a = create_worker(program["id"], full_name="W A", national_id_hash="ha")
    wkr_b = create_worker(program["id"], full_name="W B", national_id_hash="hb")
    req = create_requisition(program["id"], openings=1, tier_release_interval_hours=0)
    distribute(req["id"], [s1["id"], s2["id"]])
    sub_a = create_submittal(req["id"], s1["id"], wkr_a["id"], pay_rate_cents=8000)
    sub_b = create_submittal(req["id"], s2["id"], wkr_b["id"], pay_rate_cents=8000)
    sh1 = make_supplier_headers(s1["id"])
    _advance_to_offered(api, req["id"], sub_a["id"], sh1)
    req_now = get_success_data(api.get_requisition(req["id"], PM))
    get_success_data(api.hire_submittal(
        sub_a["id"],
        F.hire_payload(req_now["version"], "2026-01-01T00:00:00.000Z",
                       "2026-06-01T00:00:00.000Z"),
        PM,
    ))
    sub_b_after = get_success_data(api.get_submittal(sub_b["id"], PM))
    assert sub_b_after["status"] == "REJECTED", f"got {sub_b_after['status']}"


# ===========================================================================
# Queue A: resource_temporal_overlap / worker_double_booking_closed_interval_overlap_on_hire
# ===========================================================================

def test_worker_double_booking_shared_endpoint_rejected(api):
    """PRD §3.5: "the closed interval from `start_date` through `planned_end_date`
    must not overlap the closed interval of any non-`ENDED` assignment already
    held by the same worker — and because both intervals are closed, a shared
    endpoint counts as an overlap — otherwise the hire is rejected with
    `ERR_WORKER_DOUBLE_BOOKED`."

    Worker active on [2026-01-01, 2026-06-01]; hiring into [2026-06-01,
    2026-09-01] shares endpoint 2026-06-01 -> ERR_WORKER_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/worker_double_booking_closed_interval_overlap_on_hire
    """
    program = create_program(coemployment_tenure_limit_days=3650,
                             tenure_warning_threshold_days=3000)
    supplier = create_supplier(program["id"])
    worker = create_worker(program["id"])
    sh = make_supplier_headers(supplier["id"])
    # First requisition + hire.
    req1 = create_requisition(program["id"], title="R1")
    distribute(req1["id"], [supplier["id"]])
    sub1 = create_submittal(req1["id"], supplier["id"], worker["id"], pay_rate_cents=8000)
    _advance_to_offered(api, req1["id"], sub1["id"], sh)
    req1_now = get_success_data(api.get_requisition(req1["id"], PM))
    get_success_data(api.hire_submittal(sub1["id"], F.hire_payload(
        req1_now["version"], "2026-01-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"), PM))
    # Second requisition, same worker, overlapping closed interval at endpoint.
    req2 = create_requisition(program["id"], title="R2")
    distribute(req2["id"], [supplier["id"]])
    sub2 = create_submittal(req2["id"], supplier["id"], worker["id"], pay_rate_cents=8000)
    _advance_to_offered(api, req2["id"], sub2["id"], sh)
    req2_now = get_success_data(api.get_requisition(req2["id"], PM))
    validate_error(
        api.hire_submittal(sub2["id"], F.hire_payload(
            req2_now["version"], "2026-06-01T00:00:00.000Z", "2026-09-01T00:00:00.000Z"), PM),
        ApiErrorId.ERR_WORKER_DOUBLE_BOOKED.value,
    )


def test_worker_non_overlapping_interval_hire_succeeds(api):
    """PRD §3.5: "the closed interval from `start_date` through
    `planned_end_date` must not overlap the closed interval of any non-`ENDED`
    assignment already held by the same worker"

    A second engagement on a disjoint interval [2026-06-02, 2026-09-01] (one day
    after the first ends) does not overlap -> hire succeeds.

    Design: Difficulty/resource_temporal_overlap/worker_double_booking_closed_interval_overlap_on_hire
    """
    program = create_program(coemployment_tenure_limit_days=3650,
                             tenure_warning_threshold_days=3000)
    supplier = create_supplier(program["id"])
    worker = create_worker(program["id"])
    sh = make_supplier_headers(supplier["id"])
    req1 = create_requisition(program["id"], title="R1")
    distribute(req1["id"], [supplier["id"]])
    sub1 = create_submittal(req1["id"], supplier["id"], worker["id"], pay_rate_cents=8000)
    _advance_to_offered(api, req1["id"], sub1["id"], sh)
    req1_now = get_success_data(api.get_requisition(req1["id"], PM))
    get_success_data(api.hire_submittal(sub1["id"], F.hire_payload(
        req1_now["version"], "2026-01-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"), PM))
    req2 = create_requisition(program["id"], title="R2")
    distribute(req2["id"], [supplier["id"]])
    sub2 = create_submittal(req2["id"], supplier["id"], worker["id"], pay_rate_cents=8000)
    _advance_to_offered(api, req2["id"], sub2["id"], sh)
    req2_now = get_success_data(api.get_requisition(req2["id"], PM))
    data = validate_success(api.hire_submittal(sub2["id"], F.hire_payload(
        req2_now["version"], "2026-06-02T00:00:00.000Z", "2026-09-01T00:00:00.000Z"), PM))
    assert data["status"] == "HIRED"


# ===========================================================================
# Queue B: cross_cutting_complexity_layers / occ_correct_version_hire_succeeds
# ===========================================================================

def test_hire_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.7: "If `expected_requisition_version` does not equal the
    requisition's current `version`, the hire is rejected with
    `ERR_STALE_VERSION`, which returns HTTP 412."
    PRD §3.5: "The hire then increments the requisition's `filled_count` by one
    and increments the requisition's `version` by one."

    hire with the current version succeeds; version increments by 1 after.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_hire_succeeds
    """
    base = setup_offered_submittal(program_overrides={"coemployment_tenure_limit_days": 3650,
                                                      "tenure_warning_threshold_days": 3000})
    req_before = get_success_data(api.get_requisition(base["requisition"]["id"], PM))
    data = validate_success(api.hire_submittal(
        base["submittal"]["id"],
        F.hire_payload(req_before["version"], "2026-01-01T00:00:00.000Z",
                       "2026-06-01T00:00:00.000Z"),
        PM,
    ))
    assert data["status"] == "HIRED"
    req_after = get_success_data(api.get_requisition(base["requisition"]["id"], PM))
    assert req_after["version"] == req_before["version"] + 1, \
        f"version {req_before['version']} -> {req_after['version']}"


# ===========================================================================
# Queue B: cross_cutting_complexity_layers / occ_stale_version_hire_rejected
# ===========================================================================

def test_stale_version_hire_rejected(api):
    """PRD §2.7: "If `expected_requisition_version` does not equal the
    requisition's current `version`, the hire is rejected with
    `ERR_STALE_VERSION`, which returns HTTP 412. A version advances every time
    the requisition is distributed and every time a candidate is hired against
    it"

    Two OFFERED submittals on an openings-2 requisition; hiring A bumps the
    version, so B's hire carrying the pre-hire version -> ERR_STALE_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_hire_rejected
    """
    program = create_program(coemployment_tenure_limit_days=3650,
                             tenure_warning_threshold_days=3000)
    supplier = create_supplier(program["id"])
    wkr_a = create_worker(program["id"], full_name="W A", national_id_hash="ha")
    wkr_b = create_worker(program["id"], full_name="W B", national_id_hash="hb")
    sh = make_supplier_headers(supplier["id"])
    req = create_requisition(program["id"], openings=2)
    distribute(req["id"], [supplier["id"]])
    sub_a = create_submittal(req["id"], supplier["id"], wkr_a["id"], pay_rate_cents=8000)
    sub_b = create_submittal(req["id"], supplier["id"], wkr_b["id"], pay_rate_cents=8000)
    _advance_to_offered(api, req["id"], sub_a["id"], sh)
    _advance_to_offered(api, req["id"], sub_b["id"], sh)
    req_v0 = get_success_data(api.get_requisition(req["id"], PM))["version"]
    # First hire advances the version.
    get_success_data(api.hire_submittal(sub_a["id"], F.hire_payload(
        req_v0, "2026-01-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"), PM))
    # Second hire reuses the now-stale version.
    resp = api.hire_submittal(sub_b["id"], F.hire_payload(
        req_v0, "2026-07-01T00:00:00.000Z", "2026-12-01T00:00:00.000Z"), PM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# ===========================================================================
# Queue B: state_machines / error_hire_stale_requisition_version_occ
#   -> STUB (excluded_because cites transitive_cascade /
#      hire_fills_requisition_revokes_distributions_and_rejects_siblings;
#      OCC negative is owned by occ_stale_version_hire_rejected above). NOT translated.
# ===========================================================================


# ===========================================================================
# Queue B: cross_cutting_complexity_layers / cascade_close_requisition_revokes_and_rejects
# ===========================================================================

def test_close_requisition_revokes_distribution_and_rejects_submittal(api):
    """PRD §3.2: "Closing a `DISTRIBUTED` requisition moves it to `CLOSED`,
    revokes every non-terminal distribution (setting their `status` to
    `REVOKED`), and rejects every non-terminal submittal on it (setting their
    `status` to `REJECTED`)."

    Design: Corner/cross_cutting_complexity_layers/cascade_close_requisition_revokes_and_rejects
    """
    base = setup_submitted_submittal()
    get_success_data(api.close_requisition(base["requisition"]["id"], PM))
    sub_after = get_success_data(api.get_submittal(base["submittal"]["id"], PM))
    assert sub_after["status"] == "REJECTED", f"got {sub_after['status']}"
    d = _dist_for_supplier(api, base["requisition"]["id"], base["supplier"]["id"])
    assert d["status"] == "REVOKED", f"got {d['status']}"


# ===========================================================================
# Queue B: consistency_model / immediate_consistency_hire_visible_in_same_response
# ===========================================================================

def test_hire_filled_count_immediately_visible(api):
    """PRD §3.5: "The hire then increments the requisition's `filled_count` by
    one and increments the requisition's `version` by one."
    PRD §2.8: "the system propagates the consequence to every affected record
    within the same request, immediately and atomically."

    After hiring one of two openings, an immediate GET shows filled_count==1 and
    the requisition still DISTRIBUTED (one seat remains).

    Design: Corner/consistency_model/immediate_consistency_hire_visible_in_same_response
    """
    base = setup_offered_submittal(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000},
        req_overrides={"openings": 2},
    )
    req_now = get_success_data(api.get_requisition(base["requisition"]["id"], PM))
    get_success_data(api.hire_submittal(base["submittal"]["id"], F.hire_payload(
        req_now["version"], "2026-01-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"), PM))
    req_after = get_success_data(api.get_requisition(base["requisition"]["id"], PM))
    assert req_after["filled_count"] == 1, f"got {req_after['filled_count']}"
    assert req_after["status"] == "DISTRIBUTED", f"got {req_after['status']}"


# ===========================================================================
# Queue B: state_machines / cancel_distributed_requisition_with_hire_rejected
# ===========================================================================

def test_cancel_distributed_requisition_with_hire_rejected(api):
    """PRD §3.2: "cancelling a `DISTRIBUTED` requisition is permitted only when
    no `HIRED` submittal exists against it — otherwise the cancel is refused with
    `ERR_REQUISITION_HAS_HIRES`"

    openings 2 so the fill cascade does not auto-terminate after one hire; the
    requisition stays DISTRIBUTED with a HIRED submittal, and cancel fails.

    Design: Corner/state_machines/cancel_distributed_requisition_with_hire_rejected
    """
    base = setup_offered_submittal(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000},
        req_overrides={"openings": 2},
    )
    req_now = get_success_data(api.get_requisition(base["requisition"]["id"], PM))
    get_success_data(api.hire_submittal(base["submittal"]["id"], F.hire_payload(
        req_now["version"], "2026-01-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"), PM))
    validate_error(api.cancel_requisition(base["requisition"]["id"], PM),
                   ApiErrorId.ERR_REQUISITION_HAS_HIRES.value)
