"""Non-linear state machines and multi-hop cascades in the shore-excursion API.

Covers the bounded vetting information-request loop, the two independent booking
state dimensions, the weather-versus-operational cancellation fork, and the two
chains that start at a safety audit and at a recorded port delay.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS


# ---------------------------------------------------------------------------
# non_linear_state_machine / operator_vetting_info_request_loop_is_capped_at_three_cycles
# ---------------------------------------------------------------------------

def test_vetting_info_request_loop_revisits_submitted_three_times(api):
    """PRD §3.2: "Reviewers who need more paperwork move `SUBMITTED → INFO_REQUESTED`, which has no preconditions and increases `vetting_cycle_count` by 1."

    PRD §3.2: "The pair of edges forms a genuine cycle: `SUBMITTED → INFO_REQUESTED → SUBMITTED` may repeat until the cycle cap bites."

    Design: Difficulty/non_linear_state_machine/operator_vetting_info_request_loop_is_capped_at_three_cycles
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)
    operator = fixtures.create_operator(api, port["id"])
    fixtures.record_safety_audit(api, operator["id"], auditor_user_id="u_aud_1")

    submitted = fixtures.vetting_action(api, operator["id"], "SUBMIT")
    assert submitted["vetting_status"] == "SUBMITTED"
    assert submitted["vetting_cycle_count"] == 0

    for expected_cycle in (1, 2, 3):
        requested = fixtures.vetting_action(
            api, operator["id"], "REQUEST_INFO", note=f"cycle {expected_cycle}"
        )
        assert requested["vetting_status"] == "INFO_REQUESTED"
        assert requested["vetting_cycle_count"] == expected_cycle
        resubmitted = fixtures.vetting_action(api, operator["id"], "RESUBMIT")
        assert resubmitted["vetting_status"] == "SUBMITTED"
        assert resubmitted["vetting_cycle_count"] == expected_cycle


def test_fourth_resubmission_is_refused_and_leaves_the_operator_in_info_requested(api):
    """PRD §3.2: "The operator answers and the officer moves `INFO_REQUESTED → SUBMITTED`, permitted only while `vetting_cycle_count` is at most 3 — a fourth round is refused with `ERR_VETTING_CYCLE_EXHAUSTED` — and only while `insurance_expiry_date` is strictly later than the logical clock, else `ERR_INSURANCE_EXPIRED`."

    PRD §3.2: "Reviewers who need more paperwork move `SUBMITTED → INFO_REQUESTED`, which has no preconditions and increases `vetting_cycle_count` by 1."

    PRD §3.2: "Assign base weights of 0.5, 0.3 and 0.2 to the audits in that order, truncated to however many audits are in the window, then divide each base weight by the sum of the base weights actually used, so that with three audits the weights stay 0.5, 0.3 and 0.2, with two they become 0.625 and 0.375, and with one it becomes 1.0."

    Design: Difficulty/non_linear_state_machine/operator_vetting_info_request_loop_is_capped_at_three_cycles
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)
    operator = fixtures.create_operator(api, port["id"])
    fixtures.record_safety_audit(api, operator["id"], auditor_user_id="u_aud_1")
    fixtures.vetting_action(api, operator["id"], "SUBMIT")
    for cycle in (1, 2, 3):
        fixtures.vetting_action(api, operator["id"], "REQUEST_INFO", note=f"cycle {cycle}")
        fixtures.vetting_action(api, operator["id"], "RESUBMIT")

    parked = fixtures.vetting_action(api, operator["id"], "REQUEST_INFO", note="cycle 4")
    assert parked["vetting_status"] == "INFO_REQUESTED"
    assert parked["vetting_cycle_count"] == 4

    refused = api.vetting_action(
        operator["id"], {"action": "RESUBMIT"}, TEST_USERS["vetting_officer_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_VETTING_CYCLE_EXHAUSTED.value, 422)

    after = fixtures.get_operator(api, operator["id"])
    assert after["vetting_status"] == "INFO_REQUESTED"
    assert after["vetting_cycle_count"] == 4
    assert after["safety_score"] == 82


# ---------------------------------------------------------------------------
# non_linear_state_machine / booking_fulfillment_and_financial_dimensions_advance_independently
# ---------------------------------------------------------------------------

def test_guest_cancellation_inside_the_7500_bps_tier_only_partially_refunds(api):
    """PRD §3.7: "Measure the minutes from the logical clock to the departure's `meeting_time_utc`."

    PRD §3.7: "Below that but at 1440 minutes or more, the refund is 7500 basis points of `quoted_total_cents`."

    PRD §3.7: "`financial_status` then follows from the arithmetic: add the refund to the booking's existing `refunded_cents`, and if the new total is zero the status is `RETAINED`, if it is at least `charge_total_cents` the status is `REFUNDED`, and otherwise it is `PARTIALLY_REFUNDED`, with `retained_cents` set to `charge_total_cents` less the new refunded total."

    PRD §3.5: "`precruise_sold_seats` counts the seats consumed by bookings on this departure whose `channel` is `PRE_CRUISE` and whose `fulfillment_status` is neither `CANCELLED_BY_GUEST` nor `CANCELLED_BY_LINE`; `onboard_sold_seats` counts the same for `ONBOARD`."

    Design: Difficulty/non_linear_state_machine/booking_fulfillment_and_financial_dimensions_advance_independently
    """
    world = fixtures.setup_ticketed_booking(
        api, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )
    assert world.booking["quoted_total_cents"] == 48508
    assert world.booking["service_fee_cents"] == 1455
    assert world.booking["charge_total_cents"] == 49963

    # 4319 minutes before the 2026-09-15T09:00:00Z meeting time — one minute
    # inside the 7500 bps tier.
    fixtures.set_clock(api, "2026-09-12T09:01:00Z")
    cancelled = fixtures.cancel_booking(
        api, world.booking["id"], reason_code="GUEST_CHANGED_PLANS"
    )

    assert cancelled["fulfillment_status"] == "CANCELLED_BY_GUEST"
    assert cancelled["financial_status"] == "PARTIALLY_REFUNDED"
    assert cancelled["refunded_cents"] == 36381
    assert cancelled["retained_cents"] == 13582

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 0
    assert departure["seats_available_total"] == 40


def test_weather_cancellation_advances_only_the_financial_dimension_of_a_guest_cancelled_booking(api):
    """PRD §3.6: "The two advance on their own schedules — a booking can be `CANCELLED_BY_GUEST` and `PARTIALLY_REFUNDED`, and later become `REFUNDED` without its `fulfillment_status` changing at all."

    PRD §3.7: "A booking that had already been cancelled by the guest keeps its `fulfillment_status` of `CANCELLED_BY_GUEST` untouched, but if its `financial_status` was `PARTIALLY_REFUNDED` the retained remainder is refunded too, moving `PARTIALLY_REFUNDED → REFUNDED` with a `REFUND` entry for `charge_total_cents` less `refunded_cents`; a booking already `RETAINED`, `REFUNDED` or `VOIDED` is left entirely alone."

    PRD §3.7: "The `WEATHER` branch stops there: no goodwill credit, no reliability strike for the operator, no settlement penalty."

    PRD §2.3: "Two collections deviate deliberately, and both deviations exist to make the collection reconcile with a calculation: the safety-audit collection is ordered by `conducted_on` descending and then `created_at` descending, matching the scoring window described in §3.2, while the refund-ledger collection is ordered by `created_at` ascending so a booking's money history reads in the order the money actually moved."

    Design: Difficulty/non_linear_state_machine/booking_fulfillment_and_financial_dimensions_advance_independently
    """
    world = fixtures.setup_ticketed_booking(
        api, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )
    fixtures.set_clock(api, "2026-09-12T09:01:00Z")
    fixtures.cancel_booking(api, world.booking["id"], reason_code="GUEST_CHANGED_PLANS")

    # A later logical instant, so the two ledger rows carry distinct created_at
    # values and the ascending money history is unambiguous.
    fixtures.set_clock(api, "2026-09-13T00:00:00Z")
    departure = fixtures.cancel_departure(
        api, world.departure["id"], "WEATHER",
        note="Tropical storm advisory for the tender basin.",
    )
    assert departure["status"] == "CANCELLED_WEATHER"

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "CANCELLED_BY_GUEST"
    assert booking["financial_status"] == "REFUNDED"
    assert booking["refunded_cents"] == 49963
    assert booking["retained_cents"] == 0

    refund_rows, refund_meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={
                "booking_id": world.booking["id"],
                "entry_kind": "REFUND",
                "limit": 100,
            },
        )
    )
    assert refund_meta["total_count"] == 2
    assert [row["amount_cents"] for row in refund_rows] == [36381, 13582]

    _, goodwill_meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={
                "booking_id": world.booking["id"],
                "entry_kind": "GOODWILL_CREDIT",
                "limit": 100,
            },
        )
    )
    assert goodwill_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# non_linear_state_machine / departure_cancellation_forks_weather_versus_operational_side_effect_sets
# ---------------------------------------------------------------------------

def test_weather_cancellation_refunds_in_full_without_goodwill_or_a_reliability_strike(api):
    """PRD §3.7: "A booking whose `financial_status` was `CHARGED` or `PARTIALLY_REFUNDED` moves to `REFUNDED` with a `REFUND` entry of `refund_pct_bps` 10000 and `amount_cents` equal to `charge_total_cents` less whatever `refunded_cents` the booking had already accumulated, so the guest ends up whole including the service fee."

    PRD §3.7: "The `WEATHER` branch stops there: no goodwill credit, no reliability strike for the operator, no settlement penalty."

    PRD §3.7: "In both branches seats return to each booking's own channel bucket and `seats_available_total` is recomputed, the assigned tender wave's `assigned_guest_count` is reduced by the departure's `total_capacity` where a wave was assigned, every booking line's `commission_accrued_cents` is set to 0, and any draft commission statement in scope is recomputed."

    PRD §3.7: "An entry records the `booking_id` it belongs to, an `entry_kind` of `REFUND`, `AUTH_VOID`, `GOODWILL_CREDIT`, `REPATRIATION_ALLOWANCE` or `RETENTION`, a non-negative `amount_cents` (an `AUTH_VOID` always carries 0), a `refund_pct_bps` giving the basis points of `quoted_total_cents` that the entry applied (0 for `AUTH_VOID` and `RETENTION`), a `basis` naming the policy branch that produced it — `GUEST_INITIATED`, `LINE_CANCELLED_WEATHER`, `LINE_CANCELLED_OPERATIONAL`, `NO_SHOW` or `RETURN_GUARANTEE_BREACH` — and a free-form `reason_code` kept for audit."

    Design: Difficulty/non_linear_state_machine/departure_cancellation_forks_weather_versus_operational_side_effect_sets
    """
    world = fixtures.setup_ticketed_booking(
        api, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )

    departure = fixtures.cancel_departure(
        api, world.departure["id"], "WEATHER", note="Small craft advisory."
    )
    assert departure["status"] == "CANCELLED_WEATHER"
    assert departure["cancellation_cause"] == "WEATHER"

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "CANCELLED_BY_LINE"
    assert booking["financial_status"] == "REFUNDED"
    assert booking["refunded_cents"] == 49963
    assert booking["retained_cents"] == 0
    assert booking["goodwill_credit_cents"] == 0
    assert booking["commission_accrued_cents"] == 0

    refund_rows, refund_meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={
                "booking_id": world.booking["id"],
                "entry_kind": "REFUND",
                "limit": 100,
            },
        )
    )
    assert refund_meta["total_count"] == 1
    assert refund_rows[0]["amount_cents"] == 49963
    assert refund_rows[0]["refund_pct_bps"] == 10000
    assert refund_rows[0]["basis"] == "LINE_CANCELLED_WEATHER"

    _, goodwill_meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={
                "booking_id": world.booking["id"],
                "entry_kind": "GOODWILL_CREDIT",
                "limit": 100,
            },
        )
    )
    assert goodwill_meta["total_count"] == 0

    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["reliability_strikes"] == 0
    assert operator["vetting_status"] == "APPROVED"


def test_operational_cancellation_adds_a_goodwill_credit_and_one_reliability_strike(api):
    """PRD §3.7: "The `OPERATIONAL` branch adds all three, because the operator is at fault."

    PRD §3.7: "Every booking that had reached `CHARGED` additionally receives a `GOODWILL_CREDIT` entry of 1000 basis points of `quoted_total_cents` rounded half up, on the `LINE_CANCELLED_OPERATIONAL` `basis` — but a booking the guest had already walked away from receives no goodwill, since the guest had already left before the operator failed."

    PRD §3.7: "The operator's `reliability_strikes` increases by 1, and when it reaches 3 the operator moves `APPROVED → SUSPENDED`, which itself starts the four-hop suspension cascade of §3.2."

    PRD §3.7: "The departure's `status` becomes `CANCELLED_WEATHER` or `CANCELLED_OPERATIONAL` accordingly and `cancellation_cause` records `WEATHER` or `OPERATIONAL`."

    Design: Difficulty/non_linear_state_machine/departure_cancellation_forks_weather_versus_operational_side_effect_sets
    """
    world = fixtures.setup_ticketed_booking(
        api, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )

    departure = fixtures.cancel_departure(
        api, world.departure["id"], "OPERATIONAL", note="Operator vehicle breakdown."
    )
    assert departure["status"] == "CANCELLED_OPERATIONAL"
    assert departure["cancellation_cause"] == "OPERATIONAL"

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "CANCELLED_BY_LINE"
    assert booking["financial_status"] == "REFUNDED"
    assert booking["refunded_cents"] == 49963
    assert booking["goodwill_credit_cents"] == 4851
    assert booking["commission_accrued_cents"] == 0

    goodwill_rows, goodwill_meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={
                "booking_id": world.booking["id"],
                "entry_kind": "GOODWILL_CREDIT",
                "limit": 100,
            },
        )
    )
    assert goodwill_meta["total_count"] == 1
    assert goodwill_rows[0]["amount_cents"] == 4851
    assert goodwill_rows[0]["basis"] == "LINE_CANCELLED_OPERATIONAL"

    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["reliability_strikes"] == 1
    assert operator["vetting_status"] == "APPROVED"

    excursion = validate_success(
            api.get_excursion(world.excursion["id"], TEST_USERS["manager_headers"]), 200
        )
    
    assert excursion["catalog_status"] == "PUBLISHED"


def test_two_causes_on_one_operator_yield_exactly_one_strike_and_one_goodwill_credit(api):
    """PRD §3.7: "The `WEATHER` branch stops there: no goodwill credit, no reliability strike for the operator, no settlement penalty."

    PRD §3.7: "The `OPERATIONAL` branch adds all three, because the operator is at fault."

    PRD §3.7: "The operator's `reliability_strikes` increases by 1, and when it reaches 3 the operator moves `APPROVED → SUSPENDED`, which itself starts the four-hop suspension cascade of §3.2."

    Design: Difficulty/non_linear_state_machine/departure_cancellation_forks_weather_versus_operational_side_effect_sets
    """
    world = fixtures.setup_selling_departure(api)
    departure_x = world.departure
    departure_y = fixtures.create_departure(
        api, world.excursion["id"], world.port_call["id"], world.meeting_point["id"]
    )

    _, booking_x = fixtures.create_guest_and_booking(
        api, world, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )
    guest_y = fixtures.create_guest(
        api,
        full_name="Ben Ortiz",
        birth_date="1979-11-20T00:00:00Z",
        voyage_code=world.port_call["voyage_code"],
        loyalty_tier="GOLD",
    )
    booking_y = fixtures.create_booking(
        api, departure_y["id"], guest_y["id"], party_size=4
    )
    fixtures.ticket_booking(api, booking_x["id"])
    fixtures.ticket_booking(api, booking_y["id"])

    cancelled_x = fixtures.cancel_departure(
        api, departure_x["id"], "WEATHER", note="Small craft advisory."
    )
    assert cancelled_x["status"] == "CANCELLED_WEATHER"
    assert fixtures.get_operator(api, world.operator["id"])["reliability_strikes"] == 0

    cancelled_y = fixtures.cancel_departure(
        api, departure_y["id"], "OPERATIONAL", note="Operator vehicle breakdown."
    )
    assert cancelled_y["status"] == "CANCELLED_OPERATIONAL"

    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["reliability_strikes"] == 1
    assert operator["vetting_status"] == "APPROVED"

    settled_x = fixtures.get_booking(api, booking_x["id"])
    settled_y = fixtures.get_booking(api, booking_y["id"])
    assert settled_x["refunded_cents"] == 49963
    assert settled_y["refunded_cents"] == 49963
    assert settled_x["goodwill_credit_cents"] == 0
    assert settled_y["goodwill_credit_cents"] == 4851


# ---------------------------------------------------------------------------
# transitive_cascade / cascade_a_audit_score_drop_suspends_operator_withdraws_catalog_cancels_departure_and_refunds_booking
# ---------------------------------------------------------------------------

def test_audit_dropping_the_score_to_59_suspends_withdraws_and_cancels(api):
    """PRD §3.2: "Assign base weights of 0.5, 0.3 and 0.2 to the audits in that order, truncated to however many audits are in the window, then divide each base weight by the sum of the base weights actually used, so that with three audits the weights stay 0.5, 0.3 and 0.2, with two they become 0.625 and 0.375, and with one it becomes 1.0."

    PRD §3.2: "From that average subtract 8 points for every critical finding, counting `critical_finding_count` summed across the audits in the window only, and subtract a further 5 points for every liability claim against this operator whose `status` is `ADJUDICATED_UPHELD` or `SETTLED`."

    PRD §3.2: "The system suspends automatically when a recomputed `safety_score` lands below 60 — whether the recomputation followed a new safety audit or an upheld liability claim."

    PRD §3.2: "Hop one is the operator's own move to `SUSPENDED`."

    PRD §3.2: "Hop two withdraws catalog: every excursion belonging to this operator whose `catalog_status` is `PUBLISHED` moves `PUBLISHED → WITHDRAWN`."

    PRD §3.2: "Hop three cancels schedule: each of those withdrawn excursions cancels its own departures in `SCHEDULED`, `SELLING` or `CLOSED`, recording `cancellation_cause` `OPERATIONAL`."

    PRD §3.4: "A new departure lands in `status` `SCHEDULED`, or straight into `SELLING` when its excursion is already `PUBLISHED` and its port call is already `OPEN_FOR_SALE`."

    Design: Difficulty/transitive_cascade/cascade_a_audit_score_drop_suspends_operator_withdraws_catalog_cancels_departure_and_refunds_booking
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)
    meeting_point = fixtures.create_meeting_point(api, port["id"])
    operator = fixtures.create_operator(api, port["id"])
    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_1", audit_type="INITIAL",
        conducted_on="2026-06-01T00:00:00Z", raw_score=63, critical_finding_count=0,
    )
    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_2", audit_type="ANNUAL",
        conducted_on="2026-07-01T00:00:00Z", raw_score=66, critical_finding_count=0,
    )
    fixtures.vetting_action(api, operator["id"], "SUBMIT")
    approved = fixtures.vetting_action(api, operator["id"], "APPROVE")
    assert approved["vetting_status"] == "APPROVED"
    assert approved["safety_score"] == 65

    excursion = fixtures.create_published_excursion(api, port["id"], operator["id"])
    port_call = fixtures.create_port_call(api, port["id"])
    fixtures.open_port_call_sales(api, port_call["id"])
    departure = fixtures.create_departure(
        api, excursion["id"], port_call["id"], meeting_point["id"]
    )
    assert departure["status"] == "SELLING"
    guest = fixtures.create_guest(api, loyalty_tier="GOLD")
    booking = fixtures.create_booking(api, departure["id"], guest["id"], party_size=4)
    fixtures.ticket_booking(api, booking["id"])

    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_2",
        audit_type="INCIDENT_TRIGGERED", conducted_on="2026-07-20T00:00:00Z",
        raw_score=70, critical_finding_count=1,
    )

    suspended = fixtures.get_operator(api, operator["id"])
    assert suspended["safety_score"] == 59
    assert suspended["vetting_status"] == "SUSPENDED"

    withdrawn = validate_success(
            api.get_excursion(excursion["id"], TEST_USERS["manager_headers"]), 200
        )
    
    assert withdrawn["catalog_status"] == "WITHDRAWN"

    cancelled = fixtures.get_departure(api, departure["id"])
    assert cancelled["status"] == "CANCELLED_OPERATIONAL"
    assert cancelled["cancellation_cause"] == "OPERATIONAL"


def test_the_suspension_cascade_refunds_and_goodwill_credits_the_ticketed_booking(api):
    """PRD §3.2: "Hop four settles guests: each cancelled departure drives its bookings down the line-cancellation path — `fulfillment_status` to `CANCELLED_BY_LINE`, `financial_status` to `REFUNDED` for charged bookings or `VOIDED` for merely authorised ones, a ledger entry appended for each, seats returned to each booking's own channel bucket, and the assigned tender wave's counters released."

    PRD §3.7: "A booking whose `financial_status` was `CHARGED` or `PARTIALLY_REFUNDED` moves to `REFUNDED` with a `REFUND` entry of `refund_pct_bps` 10000 and `amount_cents` equal to `charge_total_cents` less whatever `refunded_cents` the booking had already accumulated, so the guest ends up whole including the service fee."

    PRD §3.7: "Every booking that had reached `CHARGED` additionally receives a `GOODWILL_CREDIT` entry of 1000 basis points of `quoted_total_cents` rounded half up, on the `LINE_CANCELLED_OPERATIONAL` `basis` — but a booking the guest had already walked away from receives no goodwill, since the guest had already left before the operator failed."

    PRD §3.7: "In both branches seats return to each booking's own channel bucket and `seats_available_total` is recomputed, the assigned tender wave's `assigned_guest_count` is reduced by the departure's `total_capacity` where a wave was assigned, every booking line's `commission_accrued_cents` is set to 0, and any draft commission statement in scope is recomputed."

    Design: Difficulty/transitive_cascade/cascade_a_audit_score_drop_suspends_operator_withdraws_catalog_cancels_departure_and_refunds_booking
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)
    meeting_point = fixtures.create_meeting_point(api, port["id"])
    operator = fixtures.create_operator(api, port["id"])
    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_1", audit_type="INITIAL",
        conducted_on="2026-06-01T00:00:00Z", raw_score=63, critical_finding_count=0,
    )
    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_2", audit_type="ANNUAL",
        conducted_on="2026-07-01T00:00:00Z", raw_score=66, critical_finding_count=0,
    )
    fixtures.vetting_action(api, operator["id"], "SUBMIT")
    fixtures.vetting_action(api, operator["id"], "APPROVE")
    excursion = fixtures.create_published_excursion(api, port["id"], operator["id"])
    port_call = fixtures.create_port_call(api, port["id"])
    fixtures.open_port_call_sales(api, port_call["id"])
    departure = fixtures.create_departure(
        api, excursion["id"], port_call["id"], meeting_point["id"]
    )
    guest = fixtures.create_guest(api, loyalty_tier="GOLD")
    booking = fixtures.create_booking(api, departure["id"], guest["id"], party_size=4)
    ticketed = fixtures.ticket_booking(api, booking["id"])
    assert ticketed["charge_total_cents"] == 49963
    assert ticketed["financial_status"] == "CHARGED"

    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_2",
        audit_type="INCIDENT_TRIGGERED", conducted_on="2026-07-20T00:00:00Z",
        raw_score=70, critical_finding_count=1,
    )

    settled = fixtures.get_booking(api, booking["id"])
    assert settled["fulfillment_status"] == "CANCELLED_BY_LINE"
    assert settled["financial_status"] == "REFUNDED"
    assert settled["refunded_cents"] == 49963
    assert settled["retained_cents"] == 0
    assert settled["goodwill_credit_cents"] == 4851
    assert settled["commission_accrued_cents"] == 0

    refund_rows, refund_meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={"booking_id": booking["id"], "entry_kind": "REFUND", "limit": 100},
        )
    )
    assert refund_meta["total_count"] == 1
    assert refund_rows[0]["amount_cents"] == 49963
    assert refund_rows[0]["refund_pct_bps"] == 10000
    assert refund_rows[0]["basis"] == "LINE_CANCELLED_OPERATIONAL"

    goodwill_rows, goodwill_meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={
                "booking_id": booking["id"],
                "entry_kind": "GOODWILL_CREDIT",
                "limit": 100,
            },
        )
    )
    assert goodwill_meta["total_count"] == 1
    assert goodwill_rows[0]["amount_cents"] == 4851
    assert goodwill_rows[0]["basis"] == "LINE_CANCELLED_OPERATIONAL"

    released = fixtures.get_departure(api, departure["id"])
    assert released["precruise_sold_seats"] == 0
    assert released["seats_available_total"] == 40


# ---------------------------------------------------------------------------
# transitive_cascade / cascade_b_port_delay_flips_band_red_closes_selling_departure_and_voids_never_charged_bookings
# ---------------------------------------------------------------------------

def test_a_75_minute_delay_flips_the_actual_band_red_while_the_scheduled_band_stays_green(api):
    """PRD §3.1: "Each report adds to `delay_minutes`, which may never be negative, and `effective_arrival_utc` is recomputed as `arrival_utc` shifted later by `delay_minutes`."

    PRD §3.4: "First compute the egress leg: at an `ALONGSIDE` port it is zero minutes; at a `TENDER` port it is the port's `tender_egress_minutes`, plus a further 20 minutes of penalty when the departure has no `tender_wave_id` assigned, because an unscheduled group waits for whatever boat it can get."

    PRD §3.4: "The ashore leg is then the excursion's `duration_minutes` plus 30 minutes of transfer buffer — 15 minutes at each end — plus the egress leg."

    PRD §3.4: "On the **scheduled basis**, the group is assumed to start at its ticketed `meeting_time_utc`, ignoring both the call's accumulated `delay_minutes` and the assigned wave's landing window entirely."

    PRD §3.4: "So when a wave is assigned, the start is the later of `meeting_time_utc` and the wave's `window_end_utc` advanced by the call's `delay_minutes`; when no wave is assigned, the start is `meeting_time_utc` advanced by `delay_minutes`."

    PRD §3.4: "`projected_return_actual_utc` is that start advanced by the same ashore leg, and `slack_minutes_actual` is the minutes from it to `all_aboard_utc`, less `risk_buffer_minutes`."

    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    Design: Difficulty/transitive_cascade/cascade_b_port_delay_flips_band_red_closes_selling_departure_and_voids_never_charged_bookings
    """
    world = fixtures.setup_selling_departure(api, tender=True)
    fixtures.create_guest_and_booking(
        api, world, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )

    before = fixtures.get_departure(api, world.departure["id"])
    assert before["slack_minutes_actual"] == 65
    assert before["timing_risk_band_actual"] == "GREEN"

    port_call = fixtures.record_delay(
        api, world.port_call["id"], 75, reason_code="PILOT_UNAVAILABLE"
    )
    assert port_call["delay_minutes"] == 75
    assert datetime.fromisoformat(
        port_call["effective_arrival_utc"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 15, 9, 15, tzinfo=timezone.utc)

    departure = fixtures.get_departure(api, world.departure["id"])
    assert datetime.fromisoformat(
        departure["projected_return_actual_utc"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)
    assert departure["slack_minutes_actual"] == 0
    assert departure["timing_risk_band_actual"] == "RED"

    assert datetime.fromisoformat(
        departure["projected_return_scheduled_utc"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 15, 14, 55, tzinfo=timezone.utc)
    assert departure["slack_minutes_scheduled"] == 65
    assert departure["timing_risk_band_scheduled"] == "GREEN"


def test_the_red_band_closes_the_departure_and_voids_its_never_charged_booking(api):
    """PRD §3.1: "Every departure on the call has its actual-basis projection and `timing_risk_band_actual` recomputed on the spot, and the recomputation can cascade: each departure that is `SELLING` and whose `timing_risk_band_actual` has just become `RED` moves `SELLING → CLOSED`, and each of that departure's never-charged bookings — those still in `BOOKED` with `financial_status` `AUTHORIZED` — moves to `CANCELLED_BY_LINE` with `financial_status` `VOIDED`, an `AUTH_VOID` ledger entry of `amount_cents` 0 on the `LINE_CANCELLED_OPERATIONAL` `basis`, and its seats returned to its own channel bucket."

    PRD §3.5: "`precruise_sold_seats` counts the seats consumed by bookings on this departure whose `channel` is `PRE_CRUISE` and whose `fulfillment_status` is neither `CANCELLED_BY_GUEST` nor `CANCELLED_BY_LINE`; `onboard_sold_seats` counts the same for `ONBOARD`."

    Design: Difficulty/transitive_cascade/cascade_b_port_delay_flips_band_red_closes_selling_departure_and_voids_never_charged_bookings
    """
    world = fixtures.setup_selling_departure(api, tender=True)
    _, booking = fixtures.create_guest_and_booking(
        api, world, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )
    assert booking["fulfillment_status"] == "BOOKED"
    assert booking["financial_status"] == "AUTHORIZED"

    fixtures.record_delay(api, world.port_call["id"], 75, reason_code="PILOT_UNAVAILABLE")

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["status"] == "CLOSED"
    assert departure["precruise_sold_seats"] == 0
    assert departure["seats_available_total"] == 40

    voided = fixtures.get_booking(api, booking["id"])
    assert voided["fulfillment_status"] == "CANCELLED_BY_LINE"
    assert voided["financial_status"] == "VOIDED"
    assert voided["refunded_cents"] == 0

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={
                "booking_id": booking["id"],
                "entry_kind": "AUTH_VOID",
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == 0
    assert rows[0]["refund_pct_bps"] == 0
    assert rows[0]["basis"] == "LINE_CANCELLED_OPERATIONAL"
