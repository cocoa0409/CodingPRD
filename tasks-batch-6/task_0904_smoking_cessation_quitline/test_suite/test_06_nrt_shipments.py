"""NRT shipment lifecycle: delivery counters, returns, approval gate, overlap, dosing."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_shipment_at, setup_active_enrollment, create_quit_attempt,
    read_enrollment,
)
from test_helpers import factories as F

CM = TEST_USERS["case_manager_headers"]


def test_delivery_increments_used_and_flips_exhausted(api):
    """PRD §3.6: "delivery recomputes the enrollment's `nrt_courses_used` and
    `nrt_courses_remaining` to include this row and then recomputes `nrt_eligibility`,
    flipping it to `EXHAUSTED` when used reaches or passes the allotment."
    PRD §2.10: "`nrt_courses_remaining` is `nrt_courses_allotted` minus
    `nrt_courses_used`".

    Design: Difficulty/transitive_cascade/nrt_delivery_increments_used_flips_exhausted_depth3
    """
    ctx = setup_shipment_at(api, target_status="SHIPPED", nrt_allotted=1, cpd=15)
    ship = validate_success(
        api.transition_nrt_shipment(ctx["shipment_id"], {"to_status": "DELIVERED"}, CM)
    )
    assert ship["status"] == "DELIVERED"
    enr = read_enrollment(api, ctx["enrollment_id"])
    assert enr["nrt_courses_used"] == 1
    assert enr["nrt_courses_remaining"] == 0
    assert enr["nrt_eligibility"] == "EXHAUSTED"


def test_shipped_not_yet_counted_toward_used(api):
    """PRD §2.10: "`nrt_courses_used` is the count of the enrollment's shipments in
    `DELIVERED` status; `nrt_courses_remaining` is `nrt_courses_allotted` minus
    `nrt_courses_used`; and `nrt_eligibility` is `EXHAUSTED` exactly when
    `nrt_courses_used` is greater than or equal to `nrt_courses_allotted`, and
    `ELIGIBLE` otherwise."

    Design: Difficulty/transitive_cascade/nrt_delivery_increments_used_flips_exhausted_depth3
    """
    ctx = setup_shipment_at(api, target_status="SHIPPED", nrt_allotted=1, cpd=15)
    enr = read_enrollment(api, ctx["enrollment_id"])
    assert enr["nrt_courses_used"] == 0
    assert enr["nrt_eligibility"] == "ELIGIBLE"


def test_return_restores_course_count(api):
    """PRD §3.6: "A delivered shipment may be returned (`DELIVERED` to `RETURNED`),
    which recomputes `nrt_courses_used` and `nrt_courses_remaining` dropping this row
    and recomputes `nrt_eligibility`, flipping it back to `ELIGIBLE` when used falls
    below the allotment."

    Design: Difficulty/compensating_invariant/nrt_course_count_conserved_on_return
    """
    ctx = setup_shipment_at(api, target_status="DELIVERED", nrt_allotted=3, cpd=15)
    validate_success(
        api.transition_nrt_shipment(ctx["shipment_id"], {"to_status": "RETURNED"}, CM)
    )
    enr = read_enrollment(api, ctx["enrollment_id"])
    assert enr["nrt_courses_used"] == 0
    assert enr["nrt_courses_remaining"] == 3
    assert enr["nrt_courses_used"] + enr["nrt_courses_remaining"] == 3


def test_course_count_conserved_through_deliver_and_return(api):
    """PRD §2.10: "`nrt_courses_used` is the count of the enrollment's shipments in
    `DELIVERED` status; `nrt_courses_remaining` is `nrt_courses_allotted` minus
    `nrt_courses_used`".

    Design: Difficulty/compensating_invariant/nrt_course_count_conserved_on_return
    """
    ctx = setup_shipment_at(api, target_status="DELIVERED", nrt_allotted=3, cpd=15)
    delivered = read_enrollment(api, ctx["enrollment_id"])
    assert delivered["nrt_courses_used"] == 1
    assert delivered["nrt_courses_used"] + delivered["nrt_courses_remaining"] == 3
    api.transition_nrt_shipment(ctx["shipment_id"], {"to_status": "RETURNED"}, CM)
    returned = read_enrollment(api, ctx["enrollment_id"])
    assert returned["nrt_courses_used"] + returned["nrt_courses_remaining"] == 3


def test_approval_without_quit_attempt_rejected(api):
    """PRD §3.6: "Approval (`REQUESTED` to `APPROVED`) requires the enrollment to be
    `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`) and requires the enrollment to have a
    quit attempt in `COMMITTED` or `QUIT_ACHIEVED` (else
    `ERR_NO_COMMITTED_QUIT_ATTEMPT`)."

    Design: Difficulty/cross_entity_state_dependency/nrt_approval_requires_committed_quit_attempt
    """
    ctx = setup_shipment_at(
        api, target_status="REQUESTED", with_quit_attempt=False, cpd=15,
        course_start="2026-06-05T00:00:00Z", course_end="2026-06-30T00:00:00Z",
    )
    resp = api.transition_nrt_shipment(ctx["shipment_id"], {"to_status": "APPROVED"}, CM)
    validate_error(resp, ApiErrorId.ERR_NO_COMMITTED_QUIT_ATTEMPT.value)


def test_approval_with_only_relapsed_attempt_rejected(api):
    """PRD §3.6: "Approval (`REQUESTED` to `APPROVED`) requires the enrollment to be
    `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`) and requires the enrollment to have a
    quit attempt in `COMMITTED` or `QUIT_ACHIEVED` (else
    `ERR_NO_COMMITTED_QUIT_ATTEMPT`)."

    Design: Difficulty/cross_entity_state_dependency/nrt_approval_requires_committed_quit_attempt
    """
    ctx = setup_active_enrollment(api, cpd=15, sponsored=False, clock="2026-06-01T00:00:00Z")
    qa = create_quit_attempt(api, ctx["enrollment_id"], "2026-06-02T00:00:00Z", "NRT_ASSISTED")
    api.transition_quit_attempt(qa["id"], {"to_status": "RELAPSED"}, CM)
    ship = validate_success(
        api.create_nrt_shipment(
            ctx["enrollment_id"],
            F.create_nrt_shipment_payload(
                medication_type="PATCH",
                course_start_date="2026-06-05T00:00:00Z",
                course_end_date="2026-06-30T00:00:00Z",
            ),
            CM,
        ),
        201,
    )
    resp = api.transition_nrt_shipment(ship["id"], {"to_status": "APPROVED"}, CM)
    validate_error(resp, ApiErrorId.ERR_NO_COMMITTED_QUIT_ATTEMPT.value)


def test_nrt_course_date_adjacency_overlap_rejected(api):
    """PRD §2.6: "a new course's date interval, from `course_start_date` through
    `course_end_date` inclusive, must not overlap the interval of any of the
    enrollment's existing shipments that are not in `CANCELED` status. An overlap is
    rejected with `ERR_NRT_COURSE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/nrt_course_date_adjacency_overlap
    """
    ctx = setup_shipment_at(
        api, target_status="REQUESTED", nrt_allotted=3, cpd=15,
        course_start="2026-06-10T00:00:00Z", course_end="2026-06-24T00:00:00Z",
    )
    # Second course [06-24, 07-01] shares the 06-24 endpoint (inclusive) -> overlap.
    resp = api.create_nrt_shipment(
        ctx["enrollment_id"],
        F.create_nrt_shipment_payload(
            medication_type="GUM",
            course_start_date="2026-06-24T00:00:00Z",
            course_end_date="2026-07-01T00:00:00Z",
        ),
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_NRT_COURSE_OVERLAP.value)


def test_nrt_non_overlapping_course_accepted(api):
    """PRD §2.6: "a new course's date interval, from `course_start_date` through
    `course_end_date` inclusive, must not overlap the interval of any of the
    enrollment's existing shipments that are not in `CANCELED` status. An overlap is
    rejected with `ERR_NRT_COURSE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/nrt_course_date_adjacency_overlap
    """
    ctx = setup_shipment_at(
        api, target_status="REQUESTED", nrt_allotted=3, cpd=15,
        course_start="2026-06-10T00:00:00Z", course_end="2026-06-24T00:00:00Z",
    )
    # Second course [06-25, 07-01] is disjoint from [06-10, 06-24] -> accepted.
    data = validate_success(
        api.create_nrt_shipment(
            ctx["enrollment_id"],
            F.create_nrt_shipment_payload(
                medication_type="GUM",
                course_start_date="2026-06-25T00:00:00Z",
                course_end_date="2026-07-01T00:00:00Z",
            ),
            CM,
        ),
        201,
    )
    assert data["status"] == "REQUESTED"


def test_weeks_supply_and_dose_heavy_smoker_patch(api):
    """PRD §3.6: "The `weeks_supply` is 12 when the participant's `cigarettes_per_day`
    is 21 or more, 10 when it is between 11 and 20 inclusive, and 8 when it is 10 or
    fewer. The `dose_mg` applies only to a `PATCH`: it is 21 milligrams when
    `cigarettes_per_day` is 11 or more and 14 milligrams otherwise; for every other
    `medication_type` the `dose_mg` is null."

    Design: Corner/calculations/nrt_weeks_supply_heavy_smoker_patch
    """
    ctx = setup_active_enrollment(api, cpd=25, sponsored=False, clock="2026-06-01T00:00:00Z")
    data = validate_success(
        api.create_nrt_shipment(
            ctx["enrollment_id"],
            F.create_nrt_shipment_payload(
                medication_type="PATCH",
                course_start_date="2026-06-05T00:00:00Z",
                course_end_date="2026-07-01T00:00:00Z",
            ),
            CM,
        ),
        201,
    )
    assert data["weeks_supply"] == 12
    assert data["dose_mg"] == 21


def test_nrt_skip_states_returns_invalid_state(api):
    """PRD §3.6: "An approved shipment may be shipped (`APPROVED` to `SHIPPED`) and
    then delivered (`SHIPPED` to `DELIVERED`)".
    PRD §2.5: "State admissibility — the target resource is in a state that admits the
    requested transition ... else `ERR_INVALID_STATE` or `ERR_ENROLLMENT_NOT_ACTIVE`
    (409)."

    Design: Corner/state_machines/nrt_skip_states_returns_invalid_state
    """
    ctx = setup_shipment_at(
        api, target_status="REQUESTED", nrt_allotted=3, cpd=15,
        course_start="2026-06-05T00:00:00Z", course_end="2026-06-30T00:00:00Z",
    )
    resp = api.transition_nrt_shipment(ctx["shipment_id"], {"to_status": "DELIVERED"}, CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_nrt_exhausted_blocks_new_request(api):
    """PRD §3.6: "The request must not exhaust the allotment: if the enrollment's
    `nrt_courses_used` is already greater than or equal to its `nrt_courses_allotted`,
    it is rejected with `ERR_NRT_EXHAUSTED`."

    Design: Corner/validations/nrt_exhausted_blocks_new_request
    """
    ctx = setup_shipment_at(
        api, target_status="DELIVERED", nrt_allotted=1, cpd=15,
        course_start="2026-06-02T00:00:00Z", course_end="2026-06-20T00:00:00Z",
    )
    resp = api.create_nrt_shipment(
        ctx["enrollment_id"],
        F.create_nrt_shipment_payload(
            medication_type="GUM",
            course_start_date="2026-06-25T00:00:00Z",
            course_end_date="2026-07-10T00:00:00Z",
        ),
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_NRT_EXHAUSTED.value)
