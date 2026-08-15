"""Difficulty queue A: cross-entity state dependencies — report creation
gated on the comparable set and assignment gated on appraiser status
(PRD 3.2, 3.4, 3.5, 3.6)."""
from test_helpers import (
    ApiErrorId,
    add_standard_locked_comps,
    create_appraiser,
    create_membership,
    lock_comparable,
    setup_accepted_order,
    setup_order_in_analysis,
    validate_error,
    validate_success,
)
from test_helpers import ADMIN
from test_helpers import create_report as create_report_fx


def _setup_two_locked_one_verified():
    """Desktop order in IN_ANALYSIS with exactly two eligible comps locked
    and a third verified but not yet locked."""
    ctx = setup_order_in_analysis()
    comps = add_standard_locked_comps(ctx, count=2)
    from test_helpers import STANDARD_COMP_ARGS, create_comparable, verify_comparable

    third = create_comparable(
        ctx["order"]["id"], ctx["appraiser"]["id"], **STANDARD_COMP_ARGS[2]
    )
    verify_comparable(third["id"], ctx["appraiser"]["id"])
    return ctx, third


def test_report_create_fails_with_two_locked_comps(api):
    """PRD 3.6: "Creation requires at least three `LOCKED` eligible
    comparables on the order, failing with `ERR_INSUFFICIENT_LOCKED_COMPS`
    otherwise."

    Design: Difficulty/cross_entity_state_dependency/report_create_gated_by_locked_comparable_count
    """
    ctx, _ = _setup_two_locked_one_verified()
    response = api.create_report(
        {
            "order_id": ctx["order"]["id"],
            "report_type": "FORM_1004",
            "condition_rating": "C3",
        },
        ctx["appraiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_LOCKED_COMPS, 422)


def test_report_create_succeeds_after_third_lock_with_weighted_value(api):
    """PRD 3.6: "Creation requires at least three `LOCKED` eligible
    comparables on the order, failing with `ERR_INSUFFICIENT_LOCKED_COMPS`
    otherwise."
    PRD 3.6: "The raw conclusion is the weighted mean — the sum of each
    weight times its comparable's `adjusted_price_cents`, divided by the sum
    of the weights — carried exactly, without intermediate rounding. The
    final `value_conclusion_cents` applies a single rounding: the mean,
    rounded half-up to the nearest 100000 cents — the nearest thousand
    dollars."

    Design: Difficulty/cross_entity_state_dependency/report_create_gated_by_locked_comparable_count
    """
    ctx, third = _setup_two_locked_one_verified()
    lock_comparable(third["id"], ctx["appraiser"]["id"])

    report = create_report_fx(ctx["order"]["id"], ctx["appraiser"]["id"])
    # weights 3/2/1 over adjusted 44500000/45700000/45000000
    # -> 269900000/6 = 44983333.33 -> round to 45000000
    assert report["value_conclusion_cents"] == 45000000
    assert report["status"] == "DRAFT"


def _setup_active_and_inactive_appraisers():
    """ACCEPTED order; appraiser A ACTIVE, appraiser B deactivated before any
    assignment; both on the client's panel."""
    ctx = setup_accepted_order(
        appraiser_overrides={"full_name": "Ann Appraiser", "license_number": "CR-1001"}
    )
    appraiser_b = create_appraiser(
        full_name="Bob Appraiser", license_level="LICENSED", license_number="LA-1002"
    )
    create_membership(ctx["client"]["id"], appraiser_b["id"])
    validate_success(api_deactivate(appraiser_b["id"]), 200)
    return ctx, appraiser_b


def api_deactivate(appraiser_id):
    from test_helpers import api_client

    return api_client.deactivate_appraiser(appraiser_id, ADMIN)


def test_assign_rejected_when_appraiser_inactive(api):
    """PRD 3.4: "The appraiser's `status` must be `ACTIVE`, `standing` must
    not be `PANEL_SUSPENDED`, and `sanction_override` must be false — any
    failure is `ERR_APPRAISER_NOT_ASSIGNABLE`."

    Design: Difficulty/cross_entity_state_dependency/assign_rejected_when_appraiser_inactive
    """
    ctx, appraiser_b = _setup_active_and_inactive_appraisers()
    response = api.assign_order(
        ctx["order"]["id"], {"appraiser_id": appraiser_b["id"]}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_APPRAISER_NOT_ASSIGNABLE, 422)


def test_assign_succeeds_for_active_appraiser_after_inactive_rejection(api):
    """PRD 3.4: "The appraiser's `status` must be `ACTIVE`, `standing` must
    not be `PANEL_SUSPENDED`, and `sanction_override` must be false — any
    failure is `ERR_APPRAISER_NOT_ASSIGNABLE`."
    PRD 3.4: "A successful assignment records `assigned_appraiser_id` on the
    order and sets `requires_supervisor_cosign` to true exactly when the
    assignee is a `TRAINEE`."

    Design: Difficulty/cross_entity_state_dependency/assign_rejected_when_appraiser_inactive
    """
    ctx, _ = _setup_active_and_inactive_appraisers()
    assigned = validate_success(
        api.assign_order(
            ctx["order"]["id"], {"appraiser_id": ctx["appraiser"]["id"]}, ADMIN
        ),
        200,
    )
    assert assigned["status"] == "ASSIGNED"
    assert assigned["assigned_appraiser_id"] == ctx["appraiser"]["id"]

# NOTE: the design instance
# "purge_gated_by_open_complaint_then_allowed_after_close" is intentionally
# not translated. Its first assertion (purge rejected with
# ERR_COMPLIANCE_HOLD_ACTIVE while a complaint is open) is not the outcome the
# PRD uniquely derives: complaint intake sweeps every ACTIVE workfile of the
# order into LEGAL_HOLD (PRD 3.8), and the purge of a LEGAL_HOLD record fails
# the earlier state check — "a record under `LEGAL_HOLD` cannot be purged, and
# any wrong state answers `ERR_INVALID_STATE`" (PRD 3.8), state priority 5
# beating the safety priority 7 hold per the PRD 2.7 pipeline order. The gap
# stays a gap.
