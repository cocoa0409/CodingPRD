"""Non-linear lifecycles: parallel order dimensions, a referral reschedule cycle, a repair fork-join.

Each suite exercises a shape a linear state machine cannot represent: two
independent status fields on one row, a state the entity re-enters, and one
predecessor state with two structurally different terminal branches.
"""
from datetime import datetime

from test_helpers import (
    CARE_OPS,
    REPAIR_TECH,
    ApiErrorId,
    api_client,
    create_provider,
    create_state_policy,
    get_referral_for_patient,
    issue_return_authorization,
    make_licensed_audiologist_headers,
    make_patient_headers,
    register_patient,
    scan_shipment,
    screen_patient,
    set_clock,
    setup_active_care_plan,
    setup_delivered_order,
    validate_error,
    validate_success,
)

CA_POLICY = {
    "state_code": "CA",
    "otc_sales_permitted": True,
    "telehealth_fitting_permitted": True,
    "min_age_years": 18,
    "trial_period_days": 30,
    "restocking_fee_mode": "FLAT_PCT",
    "restocking_fee_pct": 0.1000,
    "restocking_fee_cap_cents": 0,
    "shipping_refundable": False,
    "referral_validity_days": 180,
    "waiver_required": False,
}

NEO_M_OPEN_POOL = {"sku": "NEO-M-OPEN", "model": "NEO", "dome_size": "M", "tip_type": "OPEN"}

CANONICAL_ORDER = {
    "model": "NEO",
    "dome_size": "M",
    "tip_type": "OPEN",
    "list_price_cents": 199900,
    "discount_cents": 9900,
    "accessory_subtotal_cents": 4500,
    "shipping_cents": 1495,
}


def _instant(value: str) -> datetime:
    """Parse a logical-clock instant so equality is on the instant, not its rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Shared setup chains
# ---------------------------------------------------------------------------
def _setup_delivered_order_with_issued_return() -> dict:
    """Delivered, captured order with a return authorization issued on trial day six."""
    env = setup_delivered_order(
        policy_overrides=CA_POLICY,
        pool_overrides=NEO_M_OPEN_POOL,
        restock_units=5,
        patient_overrides={"age_years": 67},
        order_overrides=CANONICAL_ORDER,
    )
    issue_return_authorization(env, at_iso="2026-08-07T00:00:00Z")
    return env


def _setup_referral_cycled_back_to_open_twice() -> dict:
    """One referral traverses OPEN → SCHEDULED → OPEN twice, through a no-show then a cancel."""
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy(**CA_POLICY)
    audiologist = create_provider(
        provider_type="LICENSED_AUDIOLOGIST",
        npi="1932105678",
        full_name="Dr. Ben Ortiz",
        licensed_state_codes=["CA"],
        daily_capacity_minutes=480,
        buffer_minutes=10,
    )
    patient = register_patient(
        policy["id"], email="rc@example.com", full_name="Rae Cobb", age_years=64
    )
    screen_patient(
        patient["id"],
        pure_tone_avg_db=45.0,
        asymmetry_db=5.0,
        self_reported_difficulty_score=20,
        speech_in_noise_pct=70.0,
        symptom_codes=["VERTIGO"],
    )
    referral = get_referral_for_patient(patient["id"])

    patient_headers = make_patient_headers(patient["id"])
    audiologist_headers = make_licensed_audiologist_headers(audiologist["id"])

    def book(start_utc: str, end_utc: str):
        return api_client.create_remote_fitting_session(
            {
                "patient_id": patient["id"],
                "session_type": "REFERRAL_EVALUATION",
                "scheduled_start_utc": start_utc,
                "scheduled_end_utc": end_utc,
                "provider_id": audiologist["id"],
                "provider_referral_id": referral["id"],
            },
            patient_headers,
        )

    # Loop pass one: book, then let the patient miss the whole window.
    session_one = validate_success(book("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"), 201)
    referral_booked_once = validate_success(
        api_client.get_provider_referral(referral["id"], CARE_OPS)
    )
    set_clock("2026-08-05T11:00:00Z")
    session_one_after = validate_success(
        api_client.no_show_fitting_session(session_one["id"], audiologist_headers)
    )
    referral_after_no_show = validate_success(
        api_client.get_provider_referral(referral["id"], CARE_OPS)
    )

    # Loop pass two: book again, then cancel before the new start instant.
    session_two = validate_success(book("2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z"), 201)
    referral_booked_twice = validate_success(
        api_client.get_provider_referral(referral["id"], CARE_OPS)
    )
    session_two_after = validate_success(
        api_client.cancel_fitting_session(session_two["id"], patient_headers)
    )
    referral_after_cancel = validate_success(
        api_client.get_provider_referral(referral["id"], CARE_OPS)
    )

    return {
        "policy": policy,
        "audiologist": audiologist,
        "patient": patient,
        "referral": referral,
        "book": book,
        "session_one": session_one,
        "session_one_after_no_show": session_one_after,
        "session_two": session_two,
        "session_two_after_cancel": session_two_after,
        "referral_booked_once": referral_booked_once,
        "referral_after_no_show": referral_after_no_show,
        "referral_booked_twice": referral_booked_twice,
        "referral_after_cancel": referral_after_cancel,
    }


def _setup_two_repairs_through_both_fork_branches() -> dict:
    """One device is repaired once and then declared unrepairable, under a PREMIUM plan."""
    env = setup_active_care_plan(
        policy_overrides=CA_POLICY,
        pool_overrides=NEO_M_OPEN_POOL,
        restock_units=5,
        patient_overrides={"age_years": 71},
        order_overrides={
            "model": "NEO",
            "dome_size": "M",
            "tip_type": "OPEN",
            "list_price_cents": 100000,
            "discount_cents": 0,
            "accessory_subtotal_cents": 0,
            "shipping_cents": 0,
        },
        plan_overrides={
            "plan_tier": "PREMIUM",
            "base_fee_cents": 9900,
            "firmware_auto_update_enabled": True,
        },
    )
    device_id = env["assigned_device"]["id"]
    patient_headers = make_patient_headers(env["patient"]["id"])

    # Branch A: the repairable path.
    set_clock("2026-08-04T00:00:00Z")
    repair_one = validate_success(
        api_client.create_repair_order(
            {"device_id": device_id, "fault_code": "NO_SOUND"}, patient_headers
        ),
        201,
    )
    validate_success(api_client.send_repair_kit(repair_one["id"], CARE_OPS))
    set_clock("2026-08-05T00:00:00Z")
    validate_success(api_client.receive_repair_order(repair_one["id"], REPAIR_TECH))
    validate_success(api_client.start_repair_order(repair_one["id"], REPAIR_TECH))
    validate_success(
        api_client.resolve_repair_order(repair_one["id"], {"resolution": "REPAIRED"}, REPAIR_TECH)
    )
    set_clock("2026-08-14T00:00:00Z")
    repair_one = validate_success(
        api_client.return_repair_to_patient(repair_one["id"], REPAIR_TECH)
    )

    # Branch B: the unrepairable path, from the very same predecessor state.
    set_clock("2026-08-20T00:00:00Z")
    repair_two = validate_success(
        api_client.create_repair_order(
            {"device_id": device_id, "fault_code": "MOISTURE"}, patient_headers
        ),
        201,
    )
    validate_success(api_client.send_repair_kit(repair_two["id"], CARE_OPS))
    validate_success(api_client.receive_repair_order(repair_two["id"], REPAIR_TECH))
    validate_success(api_client.start_repair_order(repair_two["id"], REPAIR_TECH))
    validate_success(
        api_client.resolve_repair_order(
            repair_two["id"], {"resolution": "UNREPAIRABLE"}, REPAIR_TECH
        )
    )
    set_clock("2026-08-27T00:00:00Z")

    # Trigger: escalation is branch B's closure.
    repair_two = validate_success(api_client.escalate_repair_order(repair_two["id"], REPAIR_TECH))

    env["repair_one"] = repair_one
    env["repair_two"] = repair_two
    return env


# ---------------------------------------------------------------------------
# non_linear_state_machine: two independent dimensions on one DeviceOrder row
# ---------------------------------------------------------------------------
class TestDeviceOrderParallelDimensions:
    """Payment and fulfillment advance under separate triggers on the same row."""

    def test_return_pickup_moves_only_the_fulfillment_dimension(self, api):
        """PRD §3.5: "An order carries **two independent state dimensions on the same row**, and they advance under separate triggers."

        PRD §3.5: "A scan with `event` `RETURN_PICKED_UP` moves fulfillment `DELIVERED → RETURN_IN_TRANSIT` and advances the matching return authorization `ISSUED → IN_TRANSIT`, and requires such an authorization in `ISSUED` to exist."

        PRD §2.6: "`open_balance_cents` is defined as `captured_cents` minus `refunded_cents` minus `retained_cents`."

        Design: Difficulty/non_linear_state_machine/device_order_payment_and_fulfillment_dimensions_advance_independently
        """
        env = _setup_delivered_order_with_issued_return()

        scan_shipment(env["order"]["id"], "RETURN_PICKED_UP")

        order = validate_success(api.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["fulfillment_status"] == "RETURN_IN_TRANSIT", (
            "the pickup scan advances only the fulfillment dimension, got "
            f"{order['fulfillment_status']}"
        )
        assert order["payment_status"] == "CAPTURED", (
            "the payment dimension is untouched by a carrier scan, got "
            f"{order['payment_status']}"
        )
        assert order["refunded_cents"] == 0, (
            f"no money has moved yet, got refunded_cents {order['refunded_cents']}"
        )
        assert order["retained_cents"] == 0, (
            f"no money has been retained yet, got retained_cents {order['retained_cents']}"
        )
        assert order["open_balance_cents"] == 210096, (
            "the whole captured amount is still an open balance, got "
            f"{order['open_balance_cents']}"
        )

    def test_inspection_settles_on_the_authorization_and_leaves_both_order_dimensions_put(self, api):
        """PRD §3.6: "Inspection supplies an `inspection_grade` of `RESELLABLE`, `REFURBISHABLE` or `DAMAGED` and moves the authorization `RECEIVED → INSPECTED`; a `RESELLABLE` grade credits the unit straight back to stock by decrementing the pool's `dispatched_units` and incrementing its `on_hand_units`"

        PRD §3.5: "An order carries **two independent state dimensions on the same row**, and they advance under separate triggers."

        Design: Difficulty/non_linear_state_machine/device_order_payment_and_fulfillment_dimensions_advance_independently
        """
        env = _setup_delivered_order_with_issued_return()

        scan_shipment(env["order"]["id"], "RETURN_PICKED_UP")
        validate_success(api.receive_return_authorization(env["rma"]["id"], CARE_OPS))
        validate_success(
            api.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
            )
        )

        rma = validate_success(api.get_return_authorization(env["rma"]["id"], CARE_OPS))
        assert rma["status"] == "INSPECTED", (
            f"inspection moves the authorization to INSPECTED, got {rma['status']}"
        )
        assert rma["restocking_fee_cents"] == 19225, (
            f"the settlement retains 19225 cents of restocking, got {rma['restocking_fee_cents']}"
        )
        assert rma["refund_amount_cents"] == 189376, (
            f"the computed refund is 189376 cents, got {rma['refund_amount_cents']}"
        )

        order = validate_success(api.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["fulfillment_status"] == "RETURN_IN_TRANSIT", (
            "inspection does not advance the fulfillment dimension, got "
            f"{order['fulfillment_status']}"
        )
        assert order["payment_status"] == "CAPTURED", (
            "inspection does not advance the payment dimension, got "
            f"{order['payment_status']}"
        )
        assert order["refunded_cents"] == 0, (
            "the settlement lives on the authorization until it is settled, got "
            f"refunded_cents {order['refunded_cents']}"
        )

    def test_settlement_advances_both_dimensions_in_the_same_request(self, api):
        """PRD §3.6: "Settling an inspected authorization moves it `INSPECTED → REFUND_SETTLED`, stamps `settled_at`, and runs the five-hop return cascade of §2.8."

        PRD §3.6: "On the payment dimension, a settlement whose `restocking_fee_cents` plus `non_refundable_shipping_cents` exceeds 0 with a positive `refund_amount_cents` moves `CAPTURED → PARTIALLY_REFUNDED`, adding `refund_amount_cents` to `refunded_cents` and adding the retained restocking plus non-refundable shipping to `retained_cents`, then recomputing `open_balance_cents` — which should reach 0 on a whole-order return."

        Design: Difficulty/non_linear_state_machine/device_order_payment_and_fulfillment_dimensions_advance_independently
        """
        env = _setup_delivered_order_with_issued_return()

        scan_shipment(env["order"]["id"], "RETURN_PICKED_UP")
        validate_success(api.receive_return_authorization(env["rma"]["id"], CARE_OPS))
        validate_success(
            api.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
            )
        )
        validate_success(api.settle_return_authorization(env["rma"]["id"], CARE_OPS))

        order = validate_success(api.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["fulfillment_status"] == "RETURNED", (
            f"settlement closes the fulfillment dimension, got {order['fulfillment_status']}"
        )
        assert order["payment_status"] == "PARTIALLY_REFUNDED", (
            "a partial refund with retained restocking moves the payment dimension to "
            f"PARTIALLY_REFUNDED, got {order['payment_status']}"
        )
        assert order["captured_cents"] == 210096, (
            f"the captured amount never changes on settlement, got {order['captured_cents']}"
        )
        assert order["refunded_cents"] == 189376, (
            f"the computed refund lands in refunded_cents, got {order['refunded_cents']}"
        )
        assert order["retained_cents"] == 20720, (
            "the retained restocking 19225 plus the non-refundable shipping 1495 is 20720, got "
            f"{order['retained_cents']}"
        )
        assert order["open_balance_cents"] == 0, (
            f"a whole-order return leaves no open balance, got {order['open_balance_cents']}"
        )

        rma = validate_success(api.get_return_authorization(env["rma"]["id"], CARE_OPS))
        assert rma["status"] == "REFUND_SETTLED", (
            f"the authorization reaches REFUND_SETTLED, got {rma['status']}"
        )
        assert _instant(rma["settled_at"]) == _instant("2026-08-07T00:00:00Z"), (
            f"settled_at is stamped from the logical clock, got {rma['settled_at']}"
        )


# ---------------------------------------------------------------------------
# non_linear_state_machine: the referral reschedule cycle
# ---------------------------------------------------------------------------
class TestProviderReferralRescheduleCycle:
    """The referral re-enters OPEN twice, through two different session exits."""

    def test_no_show_cycles_the_referral_back_to_open_and_clears_the_provider(self, api):
        """PRD §3.3: "Booking the evaluation moves the referral `OPEN → SCHEDULED` and stamps its `provider_id` with the booked provider."

        PRD §3.3: "Should the evaluation appointment collapse — a no-show or a cancellation — the referral cycles `SCHEDULED → OPEN`, incrementing `reschedule_count` and clearing `provider_id` so a different audiologist may be booked."

        PRD §3.4: "it moves the session `SCHEDULED → NO_SHOW` and sets `no_show_charged_cents` to 2,500 cents (twenty-five dollars) when the patient holds a plan whose `status` is `ACTIVE` or `PAST_DUE`, and to 0 otherwise."

        Design: Difficulty/non_linear_state_machine/provider_referral_reschedule_cycle_hits_reschedule_cap
        """
        env = _setup_referral_cycled_back_to_open_twice()

        booked = env["referral_booked_once"]
        assert booked["status"] == "SCHEDULED", (
            f"the first booking moves the referral to SCHEDULED, got {booked['status']}"
        )
        assert booked["provider_id"] == env["audiologist"]["id"], (
            "the booked audiologist is stamped on the referral, got "
            f"{booked['provider_id']}"
        )
        assert booked["reschedule_count"] == 0, (
            f"no reschedule has happened yet, got {booked['reschedule_count']}"
        )

        session = env["session_one_after_no_show"]
        assert session["status"] == "NO_SHOW", (
            f"the missed session is recorded as NO_SHOW, got {session['status']}"
        )
        assert session["no_show_charged_cents"] == 0, (
            "the patient holds no care plan, so no fee is charged, got "
            f"{session['no_show_charged_cents']}"
        )

        cycled = env["referral_after_no_show"]
        assert cycled["status"] == "OPEN", (
            f"the referral cycles back to OPEN, got {cycled['status']}"
        )
        assert cycled["provider_id"] is None, (
            f"the provider is cleared so another may be booked, got {cycled['provider_id']}"
        )
        assert cycled["reschedule_count"] == 1, (
            f"the first collapse increments the counter to 1, got {cycled['reschedule_count']}"
        )

    def test_cancellation_traverses_the_same_cycle_a_second_time(self, api):
        """PRD §3.3: "Should the evaluation appointment collapse — a no-show or a cancellation — the referral cycles `SCHEDULED → OPEN`, incrementing `reschedule_count` and clearing `provider_id` so a different audiologist may be booked."

        PRD §3.4: "A patient (or a care operator) cancelling a `SCHEDULED` session before its start instant moves it `SCHEDULED → CANCELLED` and sets `no_show_charged_cents` to 1,000 cents (ten dollars) when the cancellation lands within 24 hours of `scheduled_start_utc` and the patient holds a plan in `ACTIVE` or `PAST_DUE`, and to 0 otherwise; provider capacity and utilization are recomputed, and a `REFERRAL_EVALUATION` drives its referral back to `OPEN`."

        Design: Difficulty/non_linear_state_machine/provider_referral_reschedule_cycle_hits_reschedule_cap
        """
        env = _setup_referral_cycled_back_to_open_twice()

        rebooked = env["referral_booked_twice"]
        assert rebooked["status"] == "SCHEDULED", (
            f"the referral re-enters SCHEDULED on the second booking, got {rebooked['status']}"
        )
        assert rebooked["reschedule_count"] == 1, (
            "booking does not reset the reschedule counter, got "
            f"{rebooked['reschedule_count']}"
        )

        session = env["session_two_after_cancel"]
        assert session["status"] == "CANCELLED", (
            f"the cancelled session is terminal in CANCELLED, got {session['status']}"
        )
        assert session["no_show_charged_cents"] == 0, (
            "the patient holds no care plan, so no cancellation fee is charged, got "
            f"{session['no_show_charged_cents']}"
        )

        cycled = env["referral_after_cancel"]
        assert cycled["status"] == "OPEN", (
            f"the referral cycles back to OPEN a second time, got {cycled['status']}"
        )
        assert cycled["provider_id"] is None, (
            f"the provider is cleared again, got {cycled['provider_id']}"
        )
        assert cycled["reschedule_count"] == 2, (
            "the counter is monotonic across the loop and reaches 2, got "
            f"{cycled['reschedule_count']}"
        )

    def test_third_booking_attempt_is_refused_once_the_reschedule_cap_is_reached(self, api):
        """PRD §3.3: "The cycle is capped: a booking attempted when `reschedule_count` has already reached 2 is rejected with `ERR_MAX_RESCHEDULES_EXCEEDED`."

        PRD §3.3: "computing `expires_at` as `issued_at` plus the patient's policy `referral_validity_days` days"

        Design: Difficulty/non_linear_state_machine/provider_referral_reschedule_cycle_hits_reschedule_cap
        """
        env = _setup_referral_cycled_back_to_open_twice()

        response = env["book"]("2026-08-07T10:00:00Z", "2026-08-07T11:00:00Z")
        validate_error(response, ApiErrorId.ERR_MAX_RESCHEDULES_EXCEEDED.value)

        referral = validate_success(api.get_provider_referral(env["referral"]["id"], CARE_OPS))
        assert referral["status"] == "OPEN", (
            f"the refused booking leaves the referral OPEN, got {referral['status']}"
        )
        assert referral["reschedule_count"] == 2, (
            f"the refused booking does not move the counter, got {referral['reschedule_count']}"
        )
        assert _instant(referral["expires_at"]) == _instant("2027-01-28T00:00:00Z"), (
            "180 validity days after the 2026-08-01 issue instant is 2027-01-28, got "
            f"{referral['expires_at']}"
        )

    def test_refused_booking_creates_no_session_and_leaves_the_audiologist_unbooked(self, api):
        """PRD §3.3: "The cycle is capped: a booking attempted when `reschedule_count` has already reached 2 is rejected with `ERR_MAX_RESCHEDULES_EXCEEDED`."

        PRD §3.4: "`booked_minutes_on_focus_date` is the sum of `duration_minutes` over that provider's sessions whose `status` is `SCHEDULED`, `IN_PROGRESS` or `COMPLETED` and whose own `scheduled_start_utc` falls on that same UTC date. Sessions in `NO_SHOW`, `CANCELLED` or `REQUESTED` are excluded"

        PRD §3.4: "the latter as 100 multiplied by `booked_minutes_on_focus_date` divided by `daily_capacity_minutes`, rounded half up to one decimal place."

        Design: Difficulty/non_linear_state_machine/provider_referral_reschedule_cycle_hits_reschedule_cap
        """
        env = _setup_referral_cycled_back_to_open_twice()

        validate_error(
            env["book"]("2026-08-07T10:00:00Z", "2026-08-07T11:00:00Z"),
            ApiErrorId.ERR_MAX_RESCHEDULES_EXCEEDED.value,
        )

        sessions = validate_success(
            api.list_remote_fitting_sessions(
                CARE_OPS, params={"provider_referral_id": env["referral"]["id"]}
            )
        )
        assert len(sessions) == 2, (
            f"only the two collapsed sessions exist for this referral, got {len(sessions)}"
        )

        provider = validate_success(api.get_provider(env["audiologist"]["id"], CARE_OPS))
        assert provider["booked_minutes_on_focus_date"] == 0, (
            "no session of this provider is SCHEDULED, IN_PROGRESS or COMPLETED, got "
            f"{provider['booked_minutes_on_focus_date']}"
        )
        assert provider["utilization_pct"] == 0.0, (
            f"zero booked minutes against 480 of capacity is 0.0 percent, got "
            f"{provider['utilization_pct']}"
        )


# ---------------------------------------------------------------------------
# non_linear_state_machine: the repair fork and its rejoin
# ---------------------------------------------------------------------------
class TestRepairOrderForkJoin:
    """IN_REPAIR forks into two terminal shapes with different side-effect sets."""

    def test_repairable_branch_returns_the_unit_and_creates_no_warranty_claim(self, api):
        """PRD §3.7: "Branch A closes by returning the unit, moving `REPAIRED → RETURNED_TO_PATIENT`. Closure stamps `closed_at`, computes `turnaround_days` and `sla_credit_cents`, credits the linked plan's `credit_balance_cents` by the credit amount when a plan exists, sets the device back to `WITH_PATIENT`, and — when this repair paused the trial — drives the trial `PAUSED → ACTIVE`, extending `effective_end_utc` by the accumulated `paused_days`."

        PRD §3.7: "Branch A never creates a claim; that is the whole difference in the fork's side-effect sets."

        PRD §3.7: "`sla_days` is 5 when a plan is linked whose `plan_tier` is `PREMIUM`, 10 when the linked plan's tier is `STANDARD`, and 15 when there is no plan at all"

        PRD §3.7: "`sla_credit_cents` is the days over multiplied by 500 cents per day and by that multiplier, rounded half up, and then capped at 5,000 cents ($50.00) — the cap is applied **after** the multiplied product has been rounded."

        Design: Difficulty/non_linear_state_machine/repair_order_fork_join_repaired_versus_unrepairable
        """
        env = _setup_two_repairs_through_both_fork_branches()

        repair = validate_success(api.get_repair_order(env["repair_one"]["id"], CARE_OPS))
        assert repair["status"] == "RETURNED_TO_PATIENT", (
            f"branch A terminates in RETURNED_TO_PATIENT, got {repair['status']}"
        )
        assert repair["sla_days"] == 5, (
            f"a PREMIUM plan sets the SLA at 5 days, got {repair['sla_days']}"
        )
        assert repair["turnaround_days"] == 9, (
            "receipt on 2026-08-05 and closure on 2026-08-14 is 9 whole days, got "
            f"{repair['turnaround_days']}"
        )
        assert repair["sla_credit_cents"] == 4000, (
            "4 days over at 500 cents a day times the PREMIUM 2.0 multiplier is 4000, below "
            f"the 5000 cap, got {repair['sla_credit_cents']}"
        )

        claims = validate_success(
            api.list_warranty_claims(
                CARE_OPS, params={"originating_repair_order_id": env["repair_one"]["id"]}
            )
        )
        assert len(claims) == 0, (
            f"branch A never mints a warranty claim, got {len(claims)}"
        )

    def test_unrepairable_branch_escalates_into_exactly_one_filed_defect_claim(self, api):
        """PRD §3.7: "A `resolution` of `UNREPAIRABLE` moves the repair `IN_REPAIR → UNREPAIRABLE` — branch B — and sets the device to `REPLACED` pending a warranty determination."

        PRD §3.7: "Branch B closes by escalating, moving `UNREPAIRABLE → ESCALATED_TO_WARRANTY`, which requires either that the device's `warranty_expires_at` is strictly after the logical clock or that the `fault_code` is `FIRMWARE_BRICK`. Escalation performs the same `closed_at`, `turnaround_days`, `sla_credit_cents` and plan-credit work as branch A, likewise drives a paused trial back to `ACTIVE`, and additionally creates a `WarrantyClaim` in `FILED` whose `claim_kind` is `DEFECT` and whose `originating_repair_order_id` names this repair."

        Design: Difficulty/non_linear_state_machine/repair_order_fork_join_repaired_versus_unrepairable
        """
        env = _setup_two_repairs_through_both_fork_branches()

        repair = validate_success(api.get_repair_order(env["repair_two"]["id"], CARE_OPS))
        assert repair["status"] == "ESCALATED_TO_WARRANTY", (
            f"branch B terminates in ESCALATED_TO_WARRANTY, got {repair['status']}"
        )
        assert repair["turnaround_days"] == 7, (
            "receipt on 2026-08-20 and closure on 2026-08-27 is 7 whole days, got "
            f"{repair['turnaround_days']}"
        )
        assert repair["sla_credit_cents"] == 2000, (
            "2 days over at 500 cents a day times the PREMIUM 2.0 multiplier is 2000, got "
            f"{repair['sla_credit_cents']}"
        )
        assert _instant(repair["closed_at"]) == _instant("2026-08-27T00:00:00Z"), (
            f"closed_at is stamped from the logical clock, got {repair['closed_at']}"
        )

        claims = validate_success(
            api.list_warranty_claims(
                CARE_OPS, params={"originating_repair_order_id": env["repair_two"]["id"]}
            )
        )
        assert len(claims) == 1, (
            f"escalation mints exactly one warranty claim, got {len(claims)}"
        )
        assert claims[0]["status"] == "FILED", (
            f"the escalated claim starts in FILED, got {claims[0]['status']}"
        )
        assert claims[0]["claim_kind"] == "DEFECT", (
            f"an escalated repair files a DEFECT claim, got {claims[0]['claim_kind']}"
        )

        device = validate_success(api.get_device(env["assigned_device"]["id"], CARE_OPS))
        assert device["status"] == "REPLACED", (
            f"the unrepairable unit is left REPLACED pending the determination, got "
            f"{device['status']}"
        )

    def test_both_branches_rejoin_by_crediting_the_plan_and_resuming_the_trial(self, api):
        """PRD §3.7: "Escalation performs the same `closed_at`, `turnaround_days`, `sla_credit_cents` and plan-credit work as branch A, likewise drives a paused trial back to `ACTIVE`"

        PRD §3.6: "Returning the repaired unit closes the open interval at the current logical clock and moves the trial `PAUSED → ACTIVE`, recomputing `paused_days`, `days_used` and `effective_end_utc`. The pause-and-resume cycle repeats once per repair."

        PRD §3.6: "`paused_days` is the total merged paused duration in seconds divided by 86,400 seconds (24 hours) and floored. Elapsed days are the counting-window end minus `started_at`, in seconds, divided by 86,400 and floored, so a span of exactly 86,400 seconds counts as one day while 86,399 counts as zero. `days_used` is the elapsed days minus `paused_days`, floored at 0. And `effective_end_utc` — the deadline that actually gates a return — is `nominal_end_utc` plus `paused_days` days plus `extension_days_granted` days."

        Design: Difficulty/non_linear_state_machine/repair_order_fork_join_repaired_versus_unrepairable
        """
        env = _setup_two_repairs_through_both_fork_branches()

        plan = validate_success(api.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
        assert plan["credit_balance_cents"] == 6000, (
            "4000 credited by branch A plus 2000 credited by branch B is 6000, got "
            f"{plan['credit_balance_cents']}"
        )

        trials = validate_success(
            api.list_trial_periods(CARE_OPS, params={"device_order_id": env["order"]["id"]})
        )
        assert len(trials) == 1, f"the delivered order has exactly one trial, got {len(trials)}"
        trial = trials[0]
        assert trial["status"] == "ACTIVE", (
            f"both closures drive the paused trial back to ACTIVE, got {trial['status']}"
        )
        assert len(trial["pause_intervals"]) == 2, (
            "one pause interval per repair was recorded, got "
            f"{len(trial['pause_intervals'])}"
        )
        assert trial["paused_days"] == 16, (
            "the 9-day and 7-day pauses total 16 paused days, got "
            f"{trial['paused_days']}"
        )
        assert trial["days_used"] == 10, (
            "26 elapsed days minus 16 paused days is 10, got "
            f"{trial['days_used']}"
        )
        assert _instant(trial["effective_end_utc"]) == _instant("2026-09-16T00:00:00Z"), (
            "the 2026-08-31 nominal end pushed out by 16 paused days is 2026-09-16, got "
            f"{trial['effective_end_utc']}"
        )
