"""Depth probes: validation-priority conflicts, boundary precision, and
temporal-overlap conflicts.

Covers Difficulty rules priority_pair_validation_conflict,
boundary_precision_check, and resource_temporal_overlap.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_owner_headers,
    setup_active_facility_order,
    setup_lab_pending_specimen,
    add_lab_pending_case_for_region,
    create_owner,
    create_animal,
    create_bite_case,
    create_facility,
    issue_citation,
    issue_quarantine_order,
    refetch_region,
    refetch_order,
    set_clock,
)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / safety_outranks_state_on_complete
# ---------------------------------------------------------------------------
def test_complete_converted_order_symptomatic_returns_safety_error(api, veterinarian_headers):
    """PRD §3.4: "Completion enforces three checks, evaluated in this order:
    first the safety check — an order may not be completed when the observation
    outcome is `SYMPTOMATIC` or `DECEASED`, in which case it is rejected with
    `ERR_ANIMAL_SYMPTOMATIC` and the animal must instead be converted to a
    specimen; then the state check — the order must currently be `ACTIVE`,
    otherwise `ERR_INVALID_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/safety_outranks_state_on_complete
    """
    state = setup_active_facility_order(vaccination_status="NONE", region_code="RB-PP1")
    # Drive the order to a terminal (non-ACTIVE) state first.
    validate_success(api.convert_quarantine_order(
        state["order"]["id"],
        {"collected_datetime": "2026-03-03T00:00:00Z", "condition": "SATISFACTORY"},
        veterinarian_headers), 200)
    # State check would fail, but the higher-priority safety check wins.
    resp = api.complete_quarantine_order(
        state["order"]["id"], {"observation_outcome": "SYMPTOMATIC"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_SYMPTOMATIC)


def test_complete_converted_order_deceased_returns_safety_error(api, veterinarian_headers):
    """PRD §3.4: "Completion enforces three checks, evaluated in this order:
    first the safety check — an order may not be completed when the observation
    outcome is `SYMPTOMATIC` or `DECEASED`, in which case it is rejected with
    `ERR_ANIMAL_SYMPTOMATIC` and the animal must instead be converted to a
    specimen; then the state check — the order must currently be `ACTIVE`,
    otherwise `ERR_INVALID_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/safety_outranks_state_on_complete
    """
    state = setup_active_facility_order(vaccination_status="NONE", region_code="RB-PP1b")
    validate_success(api.convert_quarantine_order(
        state["order"]["id"],
        {"collected_datetime": "2026-03-03T00:00:00Z", "condition": "SATISFACTORY"},
        veterinarian_headers), 200)
    resp = api.complete_quarantine_order(
        state["order"]["id"], {"observation_outcome": "DECEASED"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_SYMPTOMATIC)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / referential_outranks_fiscal_on_pay
# ---------------------------------------------------------------------------
def _setup_two_owners_and_citation():
    owner1 = create_owner(full_name="Owner One", phone="555-0106")
    owner2 = create_owner(full_name="Owner Two", phone="555-0107")
    case = create_bite_case(region_code="RB-PP2", wound_category="CATEGORY_I",
                            exposure_type="SCRATCH")
    citation = issue_citation(owner1["id"], case["id"],
                              ["NO_CURRENT_VACCINATION", "UNLICENSED_ANIMAL"])
    return owner1, owner2, citation


def test_pay_wrong_owner_and_wrong_amount_returns_ownership_error(api):
    """PRD §3.7: "Three checks apply in order: the citation must be in a payable
    state (`ISSUED` or `UPHELD`), otherwise `ERR_INVALID_STATE`; the acting owner
    must own the citation, otherwise `ERR_NOT_CITATION_OWNER`; and the
    `payment_amount_cents` must exactly equal the citation's `total_fine_cents`,
    otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/referential_outranks_fiscal_on_pay
    """
    _owner1, owner2, citation = _setup_two_owners_and_citation()
    resp = api.pay_citation(citation["id"], {"payment_amount_cents": 1},
                            make_owner_headers(owner2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_CITATION_OWNER)


def test_pay_wrong_owner_correct_amount_returns_ownership_error(api):
    """PRD §3.7: "Three checks apply in order: the citation must be in a payable
    state (`ISSUED` or `UPHELD`), otherwise `ERR_INVALID_STATE`; the acting owner
    must own the citation, otherwise `ERR_NOT_CITATION_OWNER`; and the
    `payment_amount_cents` must exactly equal the citation's `total_fine_cents`,
    otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/referential_outranks_fiscal_on_pay
    """
    _owner1, owner2, citation = _setup_two_owners_and_citation()
    # Even with the exact correct amount, the ownership check fires first.
    resp = api.pay_citation(citation["id"],
                            {"payment_amount_cents": citation["total_fine_cents"]},
                            make_owner_headers(owner2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_CITATION_OWNER)


# ---------------------------------------------------------------------------
# boundary_precision_check / quarantine_completion_10day_boundary
# ---------------------------------------------------------------------------
def test_complete_one_second_before_scheduled_end_rejected(api, veterinarian_headers):
    """PRD §3.4: "then the temporal check — the logical clock must be at or after
    the order's `scheduled_end_date`, meaning the full ten-day window has elapsed
    (the boundary is inclusive), otherwise `ERR_QUARANTINE_NOT_ELAPSED`."

    Design: Difficulty/boundary_precision_check/quarantine_completion_10day_boundary
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-BND1")
    set_clock("2026-03-10T23:59:59Z")
    resp = api.complete_quarantine_order(
        state["order"]["id"], {"observation_outcome": "HEALTHY"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_QUARANTINE_NOT_ELAPSED)


def test_complete_exactly_at_scheduled_end_succeeds(api, veterinarian_headers):
    """PRD §3.4: "then the temporal check — the logical clock must be at or after
    the order's `scheduled_end_date`, meaning the full ten-day window has elapsed
    (the boundary is inclusive), otherwise `ERR_QUARANTINE_NOT_ELAPSED`."

    Design: Difficulty/boundary_precision_check/quarantine_completion_10day_boundary
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-BND1b")
    set_clock("2026-03-11T00:00:00Z")
    order = validate_success(api.complete_quarantine_order(
        state["order"]["id"], {"observation_outcome": "HEALTHY"}, veterinarian_headers), 200)
    assert order["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# boundary_precision_check / surveillance_outbreak_count_boundary
# ---------------------------------------------------------------------------
def test_first_positive_below_threshold_stays_elevated(api, veterinarian_headers):
    """PRD §3.8: "it is `NORMAL` when `confirmed_positive_count` is zero,
    `ELEVATED` when the count is greater than zero but less than the region's
    `positive_threshold`, and `OUTBREAK` when the count is at or above the
    `positive_threshold` (the threshold comparison is inclusive)."

    Design: Difficulty/boundary_precision_check/surveillance_outbreak_count_boundary
    """
    state = setup_lab_pending_specimen(region_code="RB-BND2", positive_threshold=2)
    validate_success(api.report_result(
        state["specimen"]["id"], {"test_method": "DFA", "result": "POSITIVE"},
        veterinarian_headers), 200)
    region = refetch_region(state["region"]["id"])
    assert region["confirmed_positive_count"] == 1
    assert region["alert_status"] == "ELEVATED"


def test_second_positive_at_threshold_reaches_outbreak(api, veterinarian_headers):
    """PRD §3.8: "and `OUTBREAK` when the count is at or above the
    `positive_threshold` (the threshold comparison is inclusive)."

    Design: Difficulty/boundary_precision_check/surveillance_outbreak_count_boundary
    """
    state = setup_lab_pending_specimen(region_code="RB-BND2b", positive_threshold=2,
                                       species="FOX", animal_class="WILD")
    validate_success(api.report_result(
        state["specimen"]["id"], {"test_method": "DFA", "result": "POSITIVE"},
        veterinarian_headers), 200)
    second = add_lab_pending_case_for_region("RB-BND2b", species="SKUNK", animal_class="WILD")
    validate_success(api.report_result(
        second["specimen"]["id"], {"test_method": "DFA", "result": "POSITIVE"},
        veterinarian_headers), 200)
    region = refetch_region(state["region"]["id"])
    assert region["confirmed_positive_count"] == 2
    assert region["alert_status"] == "OUTBREAK"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / animal_single_occupancy_overlap_rejected
# ---------------------------------------------------------------------------
def test_second_order_interior_overlap_same_animal_rejected(api, veterinarian_headers):
    """PRD §3.3: "First, the new order's window must not overlap any existing
    `ACTIVE` order for the same animal; an order whose window overlaps such an
    order is rejected with `ERR_ANIMAL_QUARANTINE_OVERLAP`, though adjacency
    where the new order's `start_date` equals the old order's
    `scheduled_end_date` is permitted."

    Design: Difficulty/resource_temporal_overlap/animal_single_occupancy_overlap_rejected
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-TO1")
    case2 = create_bite_case(region_code="RB-TO1", wound_category="CATEGORY_II",
                             body_site="ARM", animal_id=state["animal"]["id"])
    resp = api.create_quarantine_order(case2["id"], {
        "expected_bite_case_version": case2["version"],
        "animal_id": state["animal"]["id"],
        "order_type": "HOME_CONFINEMENT",
        "start_date": "2026-03-05T00:00:00Z"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_QUARANTINE_OVERLAP)


def test_second_order_boundary_interior_overlap_same_animal_rejected(api, veterinarian_headers):
    """PRD §3.3: "First, the new order's window must not overlap any existing
    `ACTIVE` order for the same animal; an order whose window overlaps such an
    order is rejected with `ERR_ANIMAL_QUARANTINE_OVERLAP`, though adjacency
    where the new order's `start_date` equals the old order's
    `scheduled_end_date` is permitted."

    Design: Difficulty/resource_temporal_overlap/animal_single_occupancy_overlap_rejected
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-TO1b")
    case2 = create_bite_case(region_code="RB-TO1b", wound_category="CATEGORY_II",
                             body_site="ARM", animal_id=state["animal"]["id"])
    # start 2026-03-10 < old scheduled_end 2026-03-11, so the windows still overlap.
    resp = api.create_quarantine_order(case2["id"], {
        "expected_bite_case_version": case2["version"],
        "animal_id": state["animal"]["id"],
        "order_type": "HOME_CONFINEMENT",
        "start_date": "2026-03-10T00:00:00Z"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_QUARANTINE_OVERLAP)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / facility_capacity_aggregate_overlap_rejected
# ---------------------------------------------------------------------------
def _setup_capacity_one_facility_with_animal_a():
    facility = create_facility(name="Tiny Clinic", facility_type="VET_CLINIC",
                               capacity=1, daily_boarding_cents=4000)
    animal_a = create_animal(species="DOG", animal_class="DOMESTIC", vaccination_status="CURRENT")
    case_a = create_bite_case(region_code="RB-TO2", wound_category="CATEGORY_II",
                              animal_id=animal_a["id"])
    set_clock("2026-03-01T00:00:00Z")
    issue_quarantine_order(case_a["id"], case_a["version"], animal_a["id"],
                           order_type="FACILITY", facility_id=facility["id"],
                           start_date="2026-03-01T00:00:00Z")
    return facility


def test_second_facility_order_overlapping_window_exceeds_capacity_rejected(api, veterinarian_headers):
    """PRD §3.3: "Second, for `FACILITY` orders the facility's capacity must hold
    at every instant of the new window: if at any instant within `[start_date,
    scheduled_end_date)` the count of `ACTIVE` facility orders whose windows
    include that instant would rise above the facility's `capacity`, the order is
    rejected with `ERR_FACILITY_AT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/facility_capacity_aggregate_overlap_rejected
    """
    facility = _setup_capacity_one_facility_with_animal_a()
    animal_b = create_animal(species="CAT", animal_class="DOMESTIC", vaccination_status="CURRENT")
    case_b = create_bite_case(region_code="RB-TO2", wound_category="CATEGORY_II",
                              body_site="ARM", animal_id=animal_b["id"])
    resp = api.create_quarantine_order(case_b["id"], {
        "expected_bite_case_version": case_b["version"],
        "animal_id": animal_b["id"],
        "order_type": "FACILITY",
        "facility_id": facility["id"],
        "start_date": "2026-03-05T00:00:00Z"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_FACILITY_AT_CAPACITY)


def test_second_facility_order_adjacent_window_within_capacity_allowed(api, veterinarian_headers):
    """PRD §3.3: "Second, for `FACILITY` orders the facility's capacity must hold
    at every instant of the new window: if at any instant within `[start_date,
    scheduled_end_date)` the count of `ACTIVE` facility orders whose windows
    include that instant would rise above the facility's `capacity`, the order is
    rejected with `ERR_FACILITY_AT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/facility_capacity_aggregate_overlap_rejected
    """
    facility = _setup_capacity_one_facility_with_animal_a()
    animal_b = create_animal(species="CAT", animal_class="DOMESTIC", vaccination_status="CURRENT")
    case_b = create_bite_case(region_code="RB-TO2", wound_category="CATEGORY_II",
                              body_site="ARM", animal_id=animal_b["id"])
    # The [2026-03-11, 2026-03-21) window shares no instant with the first order's
    # half-open [2026-03-01, 2026-03-11) window, so capacity holds.
    order = validate_success(api.create_quarantine_order(case_b["id"], {
        "expected_bite_case_version": case_b["version"],
        "animal_id": animal_b["id"],
        "order_type": "FACILITY",
        "facility_id": facility["id"],
        "start_date": "2026-03-11T00:00:00Z"}, veterinarian_headers), 201)
    assert order["status"] == "ACTIVE"
