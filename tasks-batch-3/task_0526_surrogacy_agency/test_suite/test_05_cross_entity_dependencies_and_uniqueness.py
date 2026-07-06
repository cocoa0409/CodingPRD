"""Cross-entity state dependencies (carrier clearance needs an insurance review;
journey completion needs a BIRTH milestone + parentage GRANTED) and resource
uniqueness (milestone-type per journey; donor_code among non-terminal donors).

Covers difficulty queue rules cross_entity_state_dependency and
resource_temporal_overlap.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    create_carrier_in_screening,
    create_active_journey,
    add_and_achieve_milestone,
    add_milestone,
)
from test_helpers import factories as f

CM = TEST_USERS["case_manager_headers"]
SCREENER = TEST_USERS["screener_headers"]


# ==========================================================================
# Carrier clearance depends on InsuranceReview state
# ==========================================================================
def test_carrier_clear_without_insurance_review_rejected(api):
    """PRD §3.1: "this transition carries three requirements: the carrier is
    currently in `SCREENING`, its `psych_clearance` is `PASSED`, and an insurance
    review exists for this carrier whose status is either `APPROVED` or
    `GAP_IDENTIFIED`. If no such qualifying insurance review exists, clearing is
    rejected with `ERR_INSURANCE_REVIEW_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/carrier_clear_requires_insurance_review_state
    """
    car = create_carrier_in_screening(psych="PASSED")
    resp = api.clear_carrier(car["id"], SCREENER)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_REVIEW_REQUIRED.value)
    refreshed = validate_success(api.get_carrier(car["id"], CM))
    assert refreshed["intake_status"] == "SCREENING"


def test_carrier_clear_with_approved_insurance_review_succeeds(api):
    """PRD §3.1: "an insurance review exists for this carrier whose status is
    either `APPROVED` or `GAP_IDENTIFIED`." PRD §3.1: "Clearing a carrier
    advances `SCREENING` to `CLEARED`".

    Design: Difficulty/cross_entity_state_dependency/carrier_clear_requires_insurance_review_state
    """
    car = create_carrier_in_screening(psych="PASSED")
    ins = get_success_data(api.create_insurance_review(
        f.create_insurance_review_payload(car["id"], policy_kind="SURROGACY_FRIENDLY"), SCREENER))
    get_success_data(api.approve_insurance_review(ins["id"], SCREENER))
    data = validate_success(api.clear_carrier(car["id"], SCREENER))
    assert data["intake_status"] == "CLEARED"


# ==========================================================================
# Journey completion depends on BIRTH milestone + parentage GRANTED
# ==========================================================================
def test_journey_complete_without_birth_milestone_rejected(api):
    """PRD §3.5: "Completing a journey moves `ACTIVE` to the terminal
    `COMPLETED`, but only when the journey is `ACTIVE`, a milestone of type
    `BIRTH` exists on it with status `ACHIEVED`, and its `parentage_order_status`
    is `GRANTED`."

    Design: Difficulty/cross_entity_state_dependency/journey_complete_requires_birth_milestone_and_parentage_granted
    """
    ctx = create_active_journey()
    jr_id = ctx["journey"]["id"]
    add_and_achieve_milestone(jr_id, "EMBRYO_TRANSFER")
    add_and_achieve_milestone(jr_id, "HEARTBEAT", scheduled_utc="2026-05-20T00:00:00Z")
    get_success_data(api.file_parentage(jr_id, CM))
    get_success_data(api.decide_parentage(jr_id, f.parentage_decide_payload("GRANTED"), CM))

    resp = api.complete_journey(jr_id, CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = validate_success(api.get_journey(jr_id, CM))
    assert refreshed["status"] == "ACTIVE"


def test_journey_complete_with_birth_and_parentage_granted_succeeds(api):
    """PRD §3.5: "Completing a journey moves `ACTIVE` to the terminal
    `COMPLETED`, but only when the journey is `ACTIVE`, a milestone of type
    `BIRTH` exists on it with status `ACHIEVED`, and its `parentage_order_status`
    is `GRANTED`."

    Design: Difficulty/cross_entity_state_dependency/journey_complete_requires_birth_milestone_and_parentage_granted
    """
    ctx = create_active_journey()
    jr_id = ctx["journey"]["id"]
    add_and_achieve_milestone(jr_id, "EMBRYO_TRANSFER")
    add_and_achieve_milestone(jr_id, "HEARTBEAT", scheduled_utc="2026-05-20T00:00:00Z")
    add_and_achieve_milestone(jr_id, "BIRTH", scheduled_utc="2026-05-25T00:00:00Z")
    get_success_data(api.file_parentage(jr_id, CM))
    get_success_data(api.decide_parentage(jr_id, f.parentage_decide_payload("GRANTED"), CM))

    data = validate_success(api.complete_journey(jr_id, CM))
    assert data["status"] == "COMPLETED"


# ==========================================================================
# Resource uniqueness — milestone-type per journey
# ==========================================================================
def test_duplicate_milestone_type_rejected(api):
    """PRD §3.6: "At most one milestone of each `milestone_type` may exist per
    journey; a second milestone of a type already present is rejected with
    `ERR_DUPLICATE_MILESTONE`."

    Design: Difficulty/resource_temporal_overlap/milestone_type_uniqueness_point_occupancy_per_journey
    """
    ctx = create_active_journey()
    jr_id = ctx["journey"]["id"]
    add_milestone(jr_id, "EMBRYO_TRANSFER", scheduled_utc="2026-05-15T00:00:00Z")
    resp = api.create_milestone(
        jr_id, f.create_milestone_payload("EMBRYO_TRANSFER", scheduled_utc="2026-05-16T00:00:00Z"), CM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MILESTONE.value)


def test_distinct_milestone_types_allowed_on_same_journey(api):
    """PRD §3.6: "At most one milestone of each `milestone_type` may exist per
    journey; a second milestone of a type already present is rejected with
    `ERR_DUPLICATE_MILESTONE`."

    Design: Difficulty/resource_temporal_overlap/milestone_type_uniqueness_point_occupancy_per_journey
    """
    ctx = create_active_journey()
    jr_id = ctx["journey"]["id"]
    et = add_milestone(jr_id, "EMBRYO_TRANSFER", scheduled_utc="2026-05-15T00:00:00Z")
    hb = validate_success(api.create_milestone(
        jr_id, f.create_milestone_payload("HEARTBEAT", scheduled_utc="2026-05-20T00:00:00Z"), CM), 201)
    assert et["milestone_type"] == "EMBRYO_TRANSFER"
    assert hb["milestone_type"] == "HEARTBEAT"


# ==========================================================================
# Resource uniqueness — donor_code among non-terminal donors
# ==========================================================================
def test_duplicate_donor_code_among_non_terminal_rejected(api):
    """PRD §3.2: "Submitting a donor advances `DRAFT` to `SUBMITTED`, but only if
    the `donor_code` is unique among all donors that are not in a terminal state
    — that is, no other donor whose `intake_status` is `SUBMITTED`, `SCREENING`,
    or `CLEARED` already uses that code. A colliding `donor_code` is rejected with
    `ERR_CARRIER_INELIGIBLE`."

    Design: Difficulty/resource_temporal_overlap/donor_code_uniqueness_active_window_semantics
    """
    d1 = get_success_data(api.create_egg_donor(f.create_egg_donor_payload(donor_code="D-100"), CM))
    get_success_data(api.submit_egg_donor(d1["id"], CM))
    d2 = get_success_data(api.create_egg_donor(f.create_egg_donor_payload(donor_code="D-100"), CM))
    resp = api.submit_egg_donor(d2["id"], CM)
    validate_error(resp, ApiErrorId.ERR_CARRIER_INELIGIBLE.value)
    refreshed = validate_success(api.get_egg_donor(d2["id"], CM))
    assert refreshed["intake_status"] == "DRAFT"


def test_distinct_donor_codes_both_submit(api):
    """PRD §3.2: "Submitting a donor advances `DRAFT` to `SUBMITTED`, but only if
    the `donor_code` is unique among all donors that are not in a terminal state".

    Design: Difficulty/resource_temporal_overlap/donor_code_uniqueness_active_window_semantics
    """
    d1 = get_success_data(api.create_egg_donor(f.create_egg_donor_payload(donor_code="D-200"), CM))
    d2 = get_success_data(api.create_egg_donor(f.create_egg_donor_payload(donor_code="D-201"), CM))
    r1 = validate_success(api.submit_egg_donor(d1["id"], CM))
    r2 = validate_success(api.submit_egg_donor(d2["id"], CM))
    assert r1["intake_status"] == "SUBMITTED"
    assert r2["intake_status"] == "SUBMITTED"
