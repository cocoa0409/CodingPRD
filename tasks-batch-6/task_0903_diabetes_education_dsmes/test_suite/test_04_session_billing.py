"""Session completion billing math and the independent billing axis.

Queue A (Difficulty): combinatorial_formula (billing), non_linear_state_machine
(parallel encounter/billing axes).
Queue B (Corner): calculations (group rate), validations (adjudicate state).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


# --- cb_billing_units_min_and_modality_rate ---
def test_billing_units_are_min_of_raw_and_remaining(api):
    """PRD §3.7: "The `billable_units` are the smaller of those raw units and the
    remaining benefit units, where the remaining benefit units are floored at 0 so
    the program never bills below zero".

    A 90-min INDIVIDUAL completion has raw units floor(90/30)=3 against 20
    remaining benefit units, so billable_units = min(3, 20) = 3.

    Design: Difficulty/combinatorial_formula/cb_billing_units_min_and_modality_rate
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-07T09:00:00Z", "2026-05-07T10:30:00Z")
    completed = th.complete(api, ctx, sess["id"], 90)
    assert completed["billable_units"] == 3, \
        f"billable_units must be 3, got {completed['billable_units']}"


def test_individual_rate_and_submission_status(api):
    """PRD §3.7: "an `INDIVIDUAL` session bills at 5000 cents per unit and a
    `GROUP` session at 1500 cents per unit. The `charge_cents` is `billable_units`
    multiplied by that per-unit rate, expressed as whole integer cents."
    PRD §3.7: "on encounter completion it automatically becomes `SUBMITTED`, at
    which point `billable_units` and `charge_cents` are pinned."

    3 units at the INDIVIDUAL rate of 5000 = 15000 cents; billing_status SUBMITTED.

    Design: Difficulty/combinatorial_formula/cb_billing_units_min_and_modality_rate
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-07T09:00:00Z", "2026-05-07T10:30:00Z")
    completed = th.complete(api, ctx, sess["id"], 90)
    assert completed["charge_cents"] == 15000, \
        f"charge_cents must be 15000, got {completed['charge_cents']}"
    assert completed["billing_status"] == "SUBMITTED", \
        f"billing_status must be SUBMITTED after completion, got {completed['billing_status']}"


# --- nl_session_parallel_encounter_billing_axes ---
def test_adjudicate_paid_moves_billing_axis(api):
    """PRD §3.7: "A decision of `PAID` moves the billing status to `PAID`".

    After a completed session is adjudicated PAID the billing axis advances to
    PAID.

    Design: Difficulty/non_linear_state_machine/nl_session_parallel_encounter_billing_axes
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-12T09:00:00Z", "2026-05-12T10:00:00Z")
    th.complete(api, ctx, sess["id"], 60)
    adjudicated = validate_success(
        api.adjudicate_session(sess["id"], {"billing_decision": "PAID"}, BILLING), 200
    )
    assert adjudicated["billing_status"] == "PAID", \
        f"billing_status must be PAID, got {adjudicated['billing_status']}"


def test_encounter_axis_unchanged_by_adjudication(api):
    """PRD §3.7: "neither alters the encounter axis — a session that already
    reached `COMPLETED` continues to evolve only on the billing axis."

    Adjudication moves only the billing axis; encounter_status stays COMPLETED.

    Design: Difficulty/non_linear_state_machine/nl_session_parallel_encounter_billing_axes
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-12T09:00:00Z", "2026-05-12T10:00:00Z")
    th.complete(api, ctx, sess["id"], 60)
    adjudicated = validate_success(
        api.adjudicate_session(sess["id"], {"billing_decision": "PAID"}, BILLING), 200
    )
    assert adjudicated["encounter_status"] == "COMPLETED", \
        f"encounter_status must stay COMPLETED, got {adjudicated['encounter_status']}"


# --- Queue B: calc_group_session_billing_group_rate ---
def test_group_session_bills_at_group_rate(api):
    """PRD §3.7: "an `INDIVIDUAL` session bills at 5000 cents per unit and a
    `GROUP` session at 1500 cents per unit. The `charge_cents` is `billable_units`
    multiplied by that per-unit rate, expressed as whole integer cents."

    A completed GROUP session of 60 actual minutes bills 2 units at 1500 = 3000.

    Design: Corner/calculations/calc_group_session_billing_group_rate
    """
    ctx = setup_active_enrollment(api)
    gc = th.make_group_class_ok(
        api, ctx, room_id="ROOM-9", scheduled_start="2026-05-24T13:00:00Z",
        scheduled_end="2026-05-24T14:00:00Z", capacity=5, topic="Group Session",
    )
    seat = th.reserve_seat_ok(api, ctx, gc["id"], ctx["enrollment_id"])
    completed = th.complete(api, ctx, seat["id"], 60)
    assert completed["billable_units"] == 2, \
        f"group billable_units must be 2, got {completed['billable_units']}"
    assert completed["charge_cents"] == 3000, \
        f"group charge_cents must be 3000, got {completed['charge_cents']}"


# --- Queue B: val_billing_invalid_state_on_adjudicate ---
def test_adjudicate_unbilled_session_rejected(api):
    """PRD §3.7: "The session's `billing_status` must be `SUBMITTED`, or the
    request is rejected with `ERR_BILLING_INVALID_STATE`."

    A still-SCHEDULED session is UNBILLED, so adjudication is rejected.

    Design: Corner/validations/val_billing_invalid_state_on_adjudicate
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-26T09:00:00Z", "2026-05-26T10:00:00Z")
    resp = api.adjudicate_session(sess["id"], {"billing_decision": "PAID"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_BILLING_INVALID_STATE.value)
