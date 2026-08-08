"""The two acts of discharge and the three reconciliation gates between them."""

from test_helpers import (
    ApiErrorId,
    assert_day_ledger,
    assert_money,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMITTING_PHYSICIAN, PROGRAM_ADMIN


def test_unsigned_medication_reconciliation_wins_over_the_delivery_gate(api):
    """PRD §3.9: "**Completing** discharge requires the episode to be in
    `DISCHARGE_PENDING` and then clears three reconciliation gates in a fixed
    order. First, `med_rec_signed` must be true, or the request is refused with
    `ERR_MED_REC_UNSIGNED`. Second, every delivery order belonging to the episode
    must have reached one of `DELIVERED`, `FAILED` or `CANCELLED`, or the request
    is refused with `ERR_DELIVERY_NOT_TERMINAL`. Third, no component of the kit
    most recently deployed to the episode may still be sitting in `DEPLOYED` or
    in `PENDING_RECONCILIATION`, or the request is refused with
    `ERR_RECONCILIATION_INCOMPLETE`."
    PRD §2.5: "The ordering matters: an episode that is missing its medication
    reconciliation *and* has an in-flight delivery reports
    `ERR_MED_REC_UNSIGNED`, not `ERR_DELIVERY_NOT_TERMINAL`."

    Design: Difficulty/priority_pair_validation_conflict/discharge_med_rec_safety_gate_beats_referential_delivery_gate
    """
    parts = fx.setup_discharge_pending_with_deployed_kit(
        sign_the_med_rec=False, with_open_delivery_order=True
    )
    episode_id = parts["episode"]["id"]

    assert parts["delivery_order"]["status"] == "AUTHORIZED"
    assert (
        fx.read_component(parts["kit"]["id"], parts["component"]["id"])[
            "reconciliation_status"
        ]
        == "PENDING_RECONCILIATION"
    )

    error = validate_error(
        api.discharge_episode(episode_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_MED_REC_UNSIGNED.value,
    )
    assert error["error_id"] not in (
        "ERR_DELIVERY_NOT_TERMINAL",
        "ERR_RECONCILIATION_INCOMPLETE",
    )
    assert fx.read_episode(episode_id)["status"] == "DISCHARGE_PENDING"


def test_delivery_gate_takes_over_once_the_medication_gate_is_satisfied(api):
    """PRD §3.9: "**Completing** discharge requires the episode to be in
    `DISCHARGE_PENDING` and then clears three reconciliation gates in a fixed
    order. First, `med_rec_signed` must be true, or the request is refused with
    `ERR_MED_REC_UNSIGNED`. Second, every delivery order belonging to the episode
    must have reached one of `DELIVERED`, `FAILED` or `CANCELLED`, or the request
    is refused with `ERR_DELIVERY_NOT_TERMINAL`. Third, no component of the kit
    most recently deployed to the episode may still be sitting in `DEPLOYED` or
    in `PENDING_RECONCILIATION`, or the request is refused with
    `ERR_RECONCILIATION_INCOMPLETE`."
    PRD §3.2: "Signing it sets `med_rec_signed` to true, records the signing
    physician's opaque identifier in `med_rec_signed_by_user_id`, and advances
    the episode's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/discharge_med_rec_safety_gate_beats_referential_delivery_gate
    """
    parts = fx.setup_discharge_pending_with_deployed_kit(
        sign_the_med_rec=False, with_open_delivery_order=True
    )
    episode_id = parts["episode"]["id"]

    validate_error(
        api.discharge_episode(episode_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_MED_REC_UNSIGNED.value,
    )

    signed = validate_success(api.sign_med_rec(episode_id, ADMITTING_PHYSICIAN))
    assert signed["med_rec_signed"] is True

    validate_error(
        api.discharge_episode(episode_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_DELIVERY_NOT_TERMINAL.value,
    )
    assert fx.read_episode(episode_id)["status"] == "DISCHARGE_PENDING"


def test_discharging_an_active_episode_reports_the_state_precondition(api):
    """PRD §3.9: "**Completing** discharge requires the episode to be in
    `DISCHARGE_PENDING` and then clears three reconciliation gates in a fixed
    order."
    PRD §2.5: "**Rung 7 — Target state precondition.** The target row's current
    state is one of the states the requested transition may legally leave from.
    Violation: `ERR_INVALID_STATE` (409). Applies to every state-transition
    endpoint."

    Design: Corner/state_machines/episode_discharge_without_begin_discharge_is_rejected_as_invalid_state
    """
    parts = fx.setup_active_episode(mrn="MRN-DC", full_name="Dan Discharge")
    episode_id = parts["episode"]["id"]
    assert parts["episode"]["med_rec_signed"] is False

    error = validate_error(
        api.discharge_episode(episode_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert error["error_id"] != "ERR_MED_REC_UNSIGNED", (
        "the state precondition at rung 7 outranks the discharge gates at rung 15"
    )

    episode = fx.read_episode(episode_id)
    assert episode["status"] == "ACTIVE"
    assert episode["discharged_at"] is None


def test_unreconciled_component_blocks_discharge_until_it_is_written_off(api):
    """PRD §3.9: "Third, no component of the kit most recently deployed to the
    episode may still be sitting in `DEPLOYED` or in `PENDING_RECONCILIATION`, or
    the request is refused with `ERR_RECONCILIATION_INCOMPLETE`."
    PRD §3.5: "Reconciliation closes the custody chain component by component. A
    `FieldNurse` reconciles a component that is currently in
    `PENDING_RECONCILIATION` — a component still `IN_STOCK` or still `DEPLOYED`,
    or one already `RETURNED` or `WRITTEN_OFF`, is refused with
    `ERR_INVALID_STATE` — with an `outcome` of either `RETURNED`, meaning the
    item came back, or `WRITTEN_OFF`, meaning it did not and its
    `replacement_cost_usd` stands as the loss."

    Design: Corner/errors/discharge_with_signed_med_rec_and_terminal_deliveries_still_blocks_on_unreconciled_component
    """
    parts = fx.setup_discharge_pending_with_deployed_kit(
        component_type="THERMOMETER",
        replacement_cost_usd=35.00,
        sign_the_med_rec=True,
        with_open_delivery_order=False,
    )
    episode_id = parts["episode"]["id"]
    kit_id = parts["kit"]["id"]
    component_id = parts["component"]["id"]

    assert (
        fx.read_component(kit_id, component_id)["reconciliation_status"]
        == "PENDING_RECONCILIATION"
    )

    validate_error(
        api.discharge_episode(episode_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_RECONCILIATION_INCOMPLETE.value,
    )

    reconciled = fx.reconcile_component(component_id, "WRITTEN_OFF")
    assert reconciled["reconciliation_status"] == "WRITTEN_OFF"
    assert (
        validate_success(api.get_device_kit(kit_id, PROGRAM_ADMIN))["status"]
        == "AVAILABLE"
    )

    discharged = validate_success(
        api.discharge_episode(episode_id, ADMITTING_PHYSICIAN)
    )
    assert discharged["status"] == "DISCHARGED"
    assert (
        validate_success(api.get_patient(parts["patient"]["id"], PROGRAM_ADMIN))["status"]
        == "DISCHARGED"
    )
    assert (
        validate_success(
            api.get_referral(parts["referral"]["id"], ADMITTING_PHYSICIAN)
        )["status"]
        == "CLOSED"
    )


def test_discharge_response_already_reflects_the_whole_cascade(api):
    """PRD §3.9: "When those gates clear, discharge fires the program's closing
    cascade in this sequence: the episode moves `DISCHARGE_PENDING → DISCHARGED`
    and `discharged_at` is stamped from the logical clock; every visit of the
    episode whose `scheduling_status` is still `SCHEDULED` or `EN_ROUTE` is
    driven to `CANCELLED`; every compliance record of the episode still in
    `PENDING` is finalized to `COMPLIANT` or `CARVED_OUT` by the daily verdict of
    §3.4, with all the counter movements, `finalized_at` stamping,
    `carve_out_reason` writing and claim-voiding that finalization normally
    entails; the episode's meal plans are ended per §3.7 and their credits
    recomputed from that freshly finalized day set"
    PRD §3.7: "A plan that is `ACTIVE` at the moment of discharge moves `ACTIVE →
    COMPLETED`; its `credited_day_count` and `meal_credit_total_usd` are
    recomputed from the freshly finalized set of compliance days, the episode's
    `meal_credit_total_usd` is recomputed with them, and the plan's `version`
    advances by 1."

    Design: Corner/consistency_model/discharge_response_already_reflects_the_whole_cascade
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE", mrn="MRN-IC", full_name="Ira Immediate"
    )
    episode_id = parts["episode"]["id"]

    meal_plan = fx.open_meal_plan(episode_id, diet_code="NONE", daily_delivery_count=2)
    done_visit = fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", distance_km=5.0
    )
    open_visit = fx.schedule_visit(
        episode_id, "2026-06-01T14:00:00Z", "2026-06-01T14:45:00Z", distance_km=5.0
    )

    fx.sign_med_rec(episode_id)
    fx.begin_discharge(episode_id)

    discharged = validate_success(
        api.discharge_episode(episode_id, ADMITTING_PHYSICIAN)
    )
    assert discharged["status"] == "DISCHARGED"
    assert_day_ledger(discharged, service=1, billable=1, carved_out=0, pending=0)
    assert_money(
        discharged["reimbursement_amount_usd"], 9600.00, "reimbursement_amount_usd"
    )
    assert_money(discharged["meal_credit_total_usd"], 28.00, "meal_credit_total_usd")

    visits = validate_success(api.list_episode_visits(episode_id, PROGRAM_ADMIN))
    by_id = {row["id"]: row for row in visits}
    assert by_id[open_visit["id"]]["scheduling_status"] == "CANCELLED"
    assert by_id[done_visit["id"]]["scheduling_status"] == "COMPLETED"

    plan = fx.read_meal_plan(episode_id, meal_plan["id"])
    assert plan["status"] == "COMPLETED"
    assert plan["credited_day_count"] == 1

    assert (
        validate_success(api.get_patient(parts["patient"]["id"], PROGRAM_ADMIN))["status"]
        == "DISCHARGED"
    )
    assert (
        validate_success(
            api.get_referral(parts["referral"]["id"], ADMITTING_PHYSICIAN)
        )["status"]
        == "CLOSED"
    )
