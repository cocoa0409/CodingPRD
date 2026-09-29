"""Cascade A end to end, and the money invariant a release has to restore.

Finalizing a survey that flags a work for treatment aborts the routine visit the
flag has made pointless, releases the allocation that visit was holding and
credits the pool back — and a manual reserve/release pair has to leave the pool's
availability exactly where it began.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_funding_allocation,
    assert_pool_availability_identity,
)
from test_helpers.test_users import TEST_USERS


def _funded_visit_and_submitted_survey(api):
    """A booked, funded routine visit and a survey waiting for the conservator."""
    register = fixtures.setup_register(api)
    protocol = fixtures.create_protocol(api)
    visit = fixtures.schedule_visit(api, register["artwork"]["id"], protocol["id"])
    pool = fixtures.create_pool(api)
    assert pool["available_cents"] == 20_527_500
    allocation = fixtures.reserve_allocation(
        api, pool["id"], purpose="MAINTENANCE", amount_cents=250_000, visit_id=visit["id"]
    )
    assert fixtures.read_pool(api, pool["id"])["available_cents"] == 20_277_500

    assessment = fixtures.setup_assessment_submitted(api, register["artwork"]["id"])
    assert assessment["status"] == "SUBMITTED"
    return {
        **register,
        "protocol": protocol,
        "visit": visit,
        "pool": pool,
        "allocation": allocation,
        "assessment": assessment,
    }


def _finalize(api, assessment_id):
    return validate_success(
        api.finalize_condition_assessment(
            assessment_id,
            {"finalization_note": "treatment required"},
            TEST_USERS["chief_conservator_headers"],
        )
    )


def test_finalizing_a_failing_survey_flags_the_work_for_treatment(api):
    """PRD §3.2: "Hop 1: every other survey on the same work that was sitting in
    `FINALIZED` moves `FINALIZED → SUPERSEDED`, so a work has at most one finalized
    survey at a time."
    PRD §3.2: "Hop 2: because this survey is now finalized, the work's
    `condition_index` is set to the survey's index, its `treatment_priority_score` is
    recomputed under the single-assessment variant described in §3.9, its
    `priority_basis` is set to `SINGLE_ASSESSMENT`, and its conservation dimension
    moves `MONITORED → TREATMENT_REQUIRED` or `STABILIZED → TREATMENT_REQUIRED` when
    the new index is below 55.0."

    Design: Difficulty/transitive_cascade/finalize_supersedes_visit_then_releases_allocation_then_credits_pool
    """
    state = _funded_visit_and_submitted_survey(api)
    finalized = _finalize(api, state["assessment"]["id"])

    assert finalized["status"] == "FINALIZED"
    # Subscores 3/2/2/1/2 on BRONZE give a weighted defect of 2.15 and an urban
    # penalty of 1.5: 100 - 53.75 - 1.5 = 44.75, carried as 44.8.
    assert finalized["condition_index"] == 44.8
    assert finalized["recommendation"] == "PRIORITY"

    work = fixtures.read_artwork(api, state["artwork"]["id"])
    assert work["conservation_status"] == "TREATMENT_REQUIRED"
    assert work["custody_status"] == "ON_VIEW"
    assert work["condition_index"] == 44.8
    # Deficit 55.2 x LANDMARK 1.5 x URBAN 1.25 x deferral 1.0 = 103.50.
    assert work["treatment_priority_score"] == 103.50
    assert work["priority_basis"] == "SINGLE_ASSESSMENT"


def test_the_new_treatment_requirement_aborts_the_routine_visit(api):
    """PRD §3.2: "Hop 3: because the work now requires treatment, every maintenance
    visit on that work still sitting in `SCHEDULED` whose protocol does not require a
    conservator moves `SCHEDULED → ABORTED` with `abort_reason` set to
    `SUPERSEDED_BY_TREATMENT`; visits whose protocol does require a conservator are
    left alone."
    PRD §2.9: "**Cascade A** begins when a condition survey is finalized."

    Design: Difficulty/transitive_cascade/finalize_supersedes_visit_then_releases_allocation_then_credits_pool
    """
    state = _funded_visit_and_submitted_survey(api)
    assert state["protocol"]["requires_conservator"] is False

    _finalize(api, state["assessment"]["id"])

    visit = fixtures.read_visit(api, state["visit"]["id"])
    assert visit["status"] == "ABORTED"
    assert visit["abort_reason"] == "SUPERSEDED_BY_TREATMENT"
    assert visit["started_at"] is None


def test_the_aborted_visit_hands_its_money_back_to_the_pool(api):
    """PRD §3.2: "Hop 4: because those visits are now aborted, every funding allocation
    attached to them in `RESERVED` or `COMMITTED` moves to `RELEASED` with
    `release_reason` set to `VISIT_ABORTED`."
    PRD §3.2: "Hop 5: because those allocations are released, each affected pool's
    `available_cents` is recomputed and rises by the released `amount_cents`."
    PRD §3.10: "Allocations in `RELEASED` are excluded from that encumbrance total,
    which is precisely why a release raises availability."

    Design: Difficulty/transitive_cascade/finalize_supersedes_visit_then_releases_allocation_then_credits_pool
    """
    state = _funded_visit_and_submitted_survey(api)

    _finalize(api, state["assessment"]["id"])

    allocation = fixtures.read_allocation(api, state["allocation"]["id"])
    assert allocation["status"] == "RELEASED"
    assert allocation["release_reason"] == "VISIT_ABORTED"
    assert allocation["released_at"] is not None
    assert allocation["amount_cents"] == 250_000

    pool = fixtures.read_pool(api, state["pool"]["id"])
    assert pool["available_cents"] == 20_527_500
    assert pool["draw_authorized_cents"] == 20_527_500
    assert_pool_availability_identity(pool, 0)


def _pool_and_visit_to_fund(api):
    """A pool with its whole draw free and a visit to hang an allocation on."""
    register = fixtures.setup_register(api)
    protocol = fixtures.create_protocol(api)
    visit = fixtures.schedule_visit(api, register["artwork"]["id"], protocol["id"])
    pool = fixtures.create_pool(api)
    assert pool["available_cents"] == 20_527_500
    return pool, visit


def test_a_reservation_and_its_release_leave_the_pool_where_it_began(api):
    """PRD §3.10: "A successful reservation is created in `RESERVED` with
    `release_reason` of `NONE` and `released_at` null, lowers the pool's
    `available_cents` by `amount_cents`, and increments the pool's own `version` —
    which is what makes a second reservation from a stale read fail."
    PRD §3.10: "Releasing is the compensating action for reserving, and the money
    invariant must hold again afterwards."
    PRD §3.10: "A manual release stamps `release_reason` as `MANUAL_RELEASE`, stamps
    `released_at` from the logical clock, and raises the pool's `available_cents` by
    the allocation's `amount_cents`."

    Design: Difficulty/compensating_invariant/reserve_then_release_restores_pool_available_cents
    """
    pool, visit = _pool_and_visit_to_fund(api)

    allocation = fixtures.reserve_allocation(
        api, pool["id"], purpose="MAINTENANCE", amount_cents=683_269, visit_id=visit["id"]
    )
    assert allocation["status"] == "RESERVED"
    assert allocation["release_reason"] == "NONE"
    assert allocation["released_at"] is None
    assert_funding_allocation(allocation)
    encumbered = fixtures.read_pool(api, pool["id"])
    assert encumbered["available_cents"] == 19_844_231
    assert_pool_availability_identity(encumbered, 683_269)

    released = validate_success(
        api.release_funding_allocation(
            allocation["id"],
            {"release_note": "scope cancelled by the crew"},
            TEST_USERS["finance_headers"],
        )
    )
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "MANUAL_RELEASE"
    assert released["released_at"] is not None

    restored = fixtures.read_pool(api, pool["id"])
    assert restored["available_cents"] == 20_527_500
    assert restored["draw_authorized_cents"] == 20_527_500
    assert restored["admin_fee_cents"] == 472_500
    assert_pool_availability_identity(restored, 0)
    # The release touches only the money; the visit it funded is untouched.
    assert fixtures.read_visit(api, visit["id"])["status"] == "SCHEDULED"


def test_a_released_allocation_cannot_be_credited_back_twice(api):
    """PRD §3.10: "A `FinanceOfficer` may release an allocation directly, with an
    optional `release_note`, but only while it sits in `RESERVED`; an attempt against
    any other status draws `ERR_ALLOCATION_INVALID_STATE`."
    PRD §3.10: "`DISBURSED` and `RELEASED` are terminal."

    Design: Difficulty/compensating_invariant/reserve_then_release_restores_pool_available_cents
    """
    pool, visit = _pool_and_visit_to_fund(api)
    allocation = fixtures.reserve_allocation(
        api, pool["id"], purpose="MAINTENANCE", amount_cents=683_269, visit_id=visit["id"]
    )
    validate_success(
        api.release_funding_allocation(
            allocation["id"], {}, TEST_USERS["finance_headers"]
        )
    )
    assert fixtures.read_pool(api, pool["id"])["available_cents"] == 20_527_500

    refused = api.release_funding_allocation(
        allocation["id"], {"release_note": "again"}, TEST_USERS["finance_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_ALLOCATION_INVALID_STATE.value)

    # The refusal proves the credit is not applied twice: availability is capped at
    # the authorised draw either way.
    settled = fixtures.read_pool(api, pool["id"])
    assert settled["available_cents"] == 20_527_500
    assert_pool_availability_identity(settled, 0)

    # A second reserve/release pair drifts nothing either.
    again = fixtures.reserve_allocation(
        api, pool["id"], purpose="MAINTENANCE", amount_cents=250_000, visit_id=visit["id"]
    )
    assert fixtures.read_pool(api, pool["id"])["available_cents"] == 20_277_500
    validate_success(
        api.release_funding_allocation(again["id"], {}, TEST_USERS["finance_headers"])
    )
    assert fixtures.read_pool(api, pool["id"])["available_cents"] == 20_527_500
