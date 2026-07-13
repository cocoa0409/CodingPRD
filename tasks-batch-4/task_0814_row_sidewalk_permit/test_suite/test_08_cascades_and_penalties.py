"""Cross-entity state gates and the revocation cascade: activation on an expired
permit, penalty escalation to the revoke threshold, downstream voiding/forfeit,
and segment-count conservation."""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_applicant_headers,
    create_lane_closure_payload,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER_1 = TEST_USERS["reviewer_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _expired_permit_with_planned_closure(api):
    ctx = fixtures.setup_issued_permit(
        api, requested_start_date="2026-04-01", requested_end_date="2026-04-05"
    )
    closure = fixtures.create_closure(
        api, ctx["permit_id"], ctx["seg_id"], ctx["app_id"],
        start_date="2026-04-02", end_date="2026-04-04",
    )
    ctx["closure_id"] = closure["id"]
    fixtures.set_clock(api, "2026-04-06T00:00:00Z")
    ctx["expired_permit"] = get_success_data(api.expire_permit(ctx["permit_id"], ADMIN))
    return ctx


def test_activate_closure_on_expired_permit_rejected(api):
    """PRD §3.5: "The owning applicant activates a `PLANNED` closure, moving it to
    `ACTIVE`; activation requires the parent permit to be `ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/lane_activate_requires_permit_issued
    """
    ctx = _expired_permit_with_planned_closure(api)
    resp = api.activate_lane_closure(ctx["closure_id"], make_applicant_headers(ctx["app_id"]))
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED.value)


def test_permit_is_expired_after_valid_until_passes(api):
    """PRD §3.9: "A `PlatformAdmin` expires a permit that is `ISSUED`, moving it to
    `EXPIRED`, but only once the logical-clock date is strictly after the permit's
    `valid_until`."

    Design: Difficulty/cross_entity_state_dependency/lane_activate_requires_permit_issued
    """
    ctx = _expired_permit_with_planned_closure(api)
    assert ctx["expired_permit"]["status"] == "EXPIRED"


def test_second_violation_revokes_and_voids_closure(api):
    """PRD §3.9: "When a violation notice pushes `cumulative_penalty_cents` to at
    least 37500 cents while the permit is `ISSUED`, the permit transitions to
    `REVOKED` and a consistency cascade fires across its children. Every lane
    closure still in `PLANNED`, `ACTIVE`, or `RESTORATION_PENDING` is voided to
    `VOIDED`."

    Design: Difficulty/transitive_cascade/revoke_voids_closure_forfeits_bond_depth3
    """
    ctx = fixtures.setup_issued_permit_with_prior_violation(api, posted_cents=80000)
    get_success_data(
        api.create_violation(ctx["permit_id"], {"violation_type": "OVERSTAY"}, OFFICER)
    )
    permit = get_success_data(api.get_permit(ctx["permit_id"], REVIEWER_1))
    assert permit["status"] == "REVOKED"
    closures = get_success_data(api.list_lane_closures(ctx["permit_id"], REVIEWER_1))
    assert closures[0]["status"] == "VOIDED"


def test_revocation_forfeits_unrestored_bond(api):
    """PRD §3.9: "if any closure is voided without ever having reached `RESTORED`,
    the permit's restoration bond is driven from `POSTED` to `FORFEITED`: its
    `forfeited_cents` is set to the amount currently `held_cents`, and both
    `held_cents` and `refunded_cents` are set to 0."

    Design: Difficulty/transitive_cascade/revoke_voids_closure_forfeits_bond_depth3
    """
    ctx = fixtures.setup_issued_permit_with_prior_violation(api, posted_cents=80000)
    get_success_data(
        api.create_violation(ctx["permit_id"], {"violation_type": "OVERSTAY"}, OFFICER)
    )
    bonds = get_success_data(api.list_bond(ctx["permit_id"], REVIEWER_1))
    assert bonds[0]["status"] == "FORFEITED"
    assert bonds[0]["forfeited_cents"] == 80000


def test_cumulative_penalty_at_threshold_revokes(api):
    """PRD §3.8: "If, after the new penalty is added, the permit's
    `cumulative_penalty_cents` is at least 37500 cents and the permit is currently
    `ISSUED`, the system automatically revokes the permit as described next."

    Design: Difficulty/boundary_precision_check/penalty_revoke_threshold_boundary
    """
    ctx = fixtures.setup_issued_permit_with_prior_violation(api, posted_cents=80000)
    get_success_data(
        api.create_violation(ctx["permit_id"], {"violation_type": "OVERSTAY"}, OFFICER)
    )
    permit = get_success_data(api.get_permit(ctx["permit_id"], REVIEWER_1))
    assert permit["cumulative_penalty_cents"] == 37500
    assert permit["status"] == "REVOKED"


def test_single_violation_below_threshold_stays_issued(api):
    """PRD §3.8: "If, after the new penalty is added, the permit's
    `cumulative_penalty_cents` is at least 37500 cents and the permit is currently
    `ISSUED`, the system automatically revokes the permit as described next."

    Design: Difficulty/boundary_precision_check/penalty_revoke_threshold_boundary
    """
    ctx = fixtures.setup_issued_permit(api, posted_cents=80000)
    get_success_data(
        api.create_violation(ctx["permit_id"], {"violation_type": "TCP_VIOLATION"}, OFFICER)
    )
    permit = get_success_data(api.get_permit(ctx["permit_id"], REVIEWER_1))
    assert permit["cumulative_penalty_cents"] == 15000
    assert permit["status"] == "ISSUED"


def test_segment_count_returns_to_zero_after_void(api):
    """PRD §3.9: "each closure that had been counted against its segment — that is,
    one voided out of `ACTIVE` or `RESTORATION_PENDING` — decrements that segment's
    `active_lane_closure_count` by one."

    Design: Difficulty/compensating_invariant/segment_count_conservation_on_activate_then_void
    """
    ctx = fixtures.setup_issued_permit_with_prior_violation(api, posted_cents=80000)
    get_success_data(
        api.create_violation(ctx["permit_id"], {"violation_type": "OVERSTAY"}, OFFICER)
    )
    closures = get_success_data(api.list_lane_closures(ctx["permit_id"], REVIEWER_1))
    assert closures[0]["status"] == "VOIDED"
    seg = get_success_data(api.get_street_segment(ctx["seg_id"], REVIEWER_1))
    assert seg["active_lane_closure_count"] == 0


def test_segment_count_incremented_on_activate(api):
    """PRD §3.5: "Activation increments the occupied segment's
    `active_lane_closure_count` by one, and if the permit's `actual_start_date` is
    still unset, it is set to the current logical-clock date at this first
    activation."

    Design: Difficulty/compensating_invariant/segment_count_conservation_on_activate_then_void
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api, posted_cents=80000)
    seg = get_success_data(api.get_street_segment(ctx["seg_id"], REVIEWER_1))
    assert seg["active_lane_closure_count"] == 1
