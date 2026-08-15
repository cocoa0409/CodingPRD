"""Repeat-failure cases: the comeback cycle, charge-policy windows, and the
payment cascade that resolves the case."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    create_invoice_for_call,
    create_technician,
    get_call,
    get_success_data,
    issue_invoice,
    open_repeat_failure_case,
    open_triaged_call,
    post_payment,
    repair_existing_call,
    setup_closed_original_call,
    setup_confirmed_comeback,
    stock_van,
    validate_error,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestComebackCycleNoCharge:
    def _no_charge_cycle(self):
        """Original retail call CLOSED via full payment; comeback received
        2026-08-20T14:00:00Z (16 whole days, 300 miles -> NO_CHARGE);
        confirmed; repaired with a SHOP_GUARANTEE part; invoiced."""
        original = setup_closed_original_call()
        new_call, case = setup_confirmed_comeback(
            original, new_received_at="2026-08-20T14:00:00Z",
            vehicle_odometer=120750)
        return original, new_call, case

    def test_confirm_comeback_reopens_original_call(self, api):
        """PRD: "Confirming the comeback — allowed only when the
        `charge_policy` is not `FULL`, else `ERR_REPEAT_WINDOW_EXPIRED` —
        marks the new call with `is_comeback` true and points its
        `repeat_of_call_id` at the original, records `decided_by`, and
        reopens the original call from `CLOSED` to `REOPENED` with its
        `reopened_count` incremented and a `CALL_REOPENED` event appended."

        Design: Difficulty/non_linear_state_machine/service_call_closed_reopened_closed_cycle
        """
        original, new_call, case = self._no_charge_cycle()
        assert case["status"] == "CONFIRMED_COMEBACK"
        # 16 whole days (floor of 16d 21.5h) and 300 miles: NO_CHARGE.
        assert case["charge_policy"] == "NO_CHARGE"
        reopened = get_call(original["call"]["id"])
        assert reopened["status"] == "REOPENED"
        assert reopened["reopened_count"] == 1
        comeback = get_call(new_call["id"])
        assert comeback["is_comeback"] is True
        assert comeback["repeat_of_call_id"] == original["call"]["id"]

    def test_no_charge_zero_total_issue_closes_the_loop(self, api):
        """PRD: "A zero-total invoice — the hallmark of a `NO_CHARGE`
        comeback — skips the collection lifecycle entirely: at issue its
        `payment_status` goes straight to `PAID` and the call moves from
        `INVOICED` directly to `CLOSED`." and "The loop closes when the
        comeback call itself reaches `CLOSED`: the case moves to `RESOLVED`
        and the original call returns from `REOPENED` to `CLOSED`".

        Design: Difficulty/non_linear_state_machine/service_call_closed_reopened_closed_cycle
        """
        original, new_call, case = self._no_charge_cycle()
        tech, tech_headers = create_technician(full_name="Comeback Tech")
        stock = stock_van(tech["id"], part_number="ALT-104", qty_on_hand=10,
                          unit_cost_cents=21000, unit_retail_cents=34999)
        repair_existing_call(
            new_call["id"], tech["id"], tech_headers,
            window=("2026-08-20T14:00:00Z", "2026-08-20T18:00:00Z"),
            depart_at="2026-08-20T14:30:00Z",
            arrive_at="2026-08-20T15:30:00Z", actual_travel_miles=35,
            labor_hours_actual=1.5, completion_odometer_miles=120760,
            parts=[{"item_id": stock["id"], "qty": 1,
                    "charge_type": "SHOP_GUARANTEE"}],
            diagnosis_summary="replacement alternator failed")
        invoice = create_invoice_for_call(new_call["id"])
        # NO_CHARGE zeroes labor/travel/time/callout; the SHOP_GUARANTEE
        # line is never summed; tax on a zero subtotal is zero.
        assert invoice["total_cents"] == 0
        issued = issue_invoice(invoice["id"])
        assert issued["payment_status"] == "PAID", (
            "zero-total issue settles without any Payment row")
        assert get_call(new_call["id"])["status"] == "CLOSED"
        assert get_call(original["call"]["id"])["status"] == "CLOSED", (
            "the original returns from REOPENED to CLOSED")
        final_case = get_success_data(
            api.get_repeat_failure_case(case["id"], DISPATCHER))
        assert final_case["status"] == "RESOLVED"


class TestComebackFinalPaymentCascade:
    def _reduced_comeback_issued(self):
        """Original CLOSED 2026-08-03; comeback received 2026-09-10T14:00:00Z
        (37 whole days, 550 miles -> REDUCED); confirmed; repaired with
        SHOP_GUARANTEE parts; REDUCED invoice 30750 issued."""
        original = setup_closed_original_call()
        new_call, case = setup_confirmed_comeback(
            original, new_received_at="2026-09-10T14:00:00Z",
            vehicle_odometer=121000)
        tech, tech_headers = create_technician(full_name="Comeback Tech")
        stock = stock_van(tech["id"], part_number="ALT-104", qty_on_hand=10,
                          unit_cost_cents=21000, unit_retail_cents=34999)
        repair_existing_call(
            new_call["id"], tech["id"], tech_headers,
            window=("2026-09-10T14:00:00Z", "2026-09-10T18:00:00Z"),
            planned_travel_miles=35, depart_at=None,
            arrive_at="2026-09-10T15:00:00Z", actual_travel_miles=35,
            labor_hours_actual=2.0, completion_odometer_miles=121010,
            parts=[{"item_id": stock["id"], "qty": 1,
                    "charge_type": "SHOP_GUARANTEE"}],
            diagnosis_summary="replacement failed")
        invoice = create_invoice_for_call(new_call["id"])
        issue_invoice(invoice["id"])
        return original, new_call, case, invoice

    def test_reduced_comeback_invoice_math(self, api):
        """PRD: "a `REDUCED` comeback halves the computed labor amount with
        round-half-up" and guarantee lines "are simply never summed into the
        invoice".

        Design: Difficulty/transitive_cascade/cascade_final_payment_closes_call_and_resolves_comeback
        """
        _o, _n, case, invoice = self._reduced_comeback_issued()
        assert case["charge_policy"] == "REDUCED", (
            "37 days and 550 miles: within the 45-day / 2000-mile band")
        # labor 29000 halved = 14500; travel (35-25) x 425 = 4250;
        # time 60 x 200 = 12000; SHOP_GUARANTEE parts excluded; tax on 0.
        assert invoice["total_cents"] == 30750

    def test_final_payment_closes_call_and_resolves_comeback(self, api):
        """PRD: "When a payment brings the outstanding balance to zero,
        `payment_status` becomes `PAID` and the call cascades from `INVOICED`
        to `CLOSED` with a `CALL_CLOSED` event — and if that call was the
        comeback call of a confirmed repeat-failure case, the cascade
        continues one hop further" — the case resolves and the reopened
        original returns to `CLOSED`.

        Design: Difficulty/transitive_cascade/cascade_final_payment_closes_call_and_resolves_comeback
        """
        original, new_call, case, invoice = self._reduced_comeback_issued()
        post_payment(invoice["id"], 30750, method="CARD")
        after = get_success_data(api.get_invoice(invoice["id"], BILLING))
        assert after["payment_status"] == "PAID"
        assert after["outstanding_cents"] == 0
        assert get_call(new_call["id"])["status"] == "CLOSED"
        final_case = get_success_data(
            api.get_repeat_failure_case(case["id"], DISPATCHER))
        assert final_case["status"] == "RESOLVED"
        original_now = get_call(original["call"]["id"])
        assert original_now["status"] == "CLOSED"
        assert original_now["reopened_count"] == 1


class TestRepeatCaseGuards:
    def test_repeat_symptom_mismatch_rejected(self, api):
        """PRD: "The two calls must belong to the same vehicle
        (`ERR_VEHICLE_MISMATCH` otherwise) and share the same
        `symptom_category` — the case copies the new call's category and
        compares it to the original's, rejecting a mismatch with
        `ERR_REPEAT_SYMPTOM_MISMATCH`."

        Design: Corner/errors/repeat_symptom_mismatch_rejected
        """
        original = setup_closed_original_call()
        advance_clock("2026-08-10T14:00:00Z")
        new_call = open_triaged_call(
            original["veh"]["id"], symptom_category="BRAKE_FAULT",
            severity="DRIVABLE", received_at=None,
            breakdown_location_text="I-70 mm 300",
            distance_miles_from_depot=35, symptom_description="brake fade")
        resp = api.create_repeat_failure_case(
            {"vehicle_id": original["veh"]["id"],
             "original_service_call_id": original["call"]["id"],
             "new_service_call_id": new_call["id"]},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_REPEAT_SYMPTOM_MISMATCH)

    def test_duplicate_open_repeat_case_rejected(self, api):
        """PRD: "At most one case per vehicle may be open at a time across
        `OPEN`, `UNDER_REVIEW`, and `CONFIRMED_COMEBACK`
        (`ERR_DUPLICATE_OPEN_CASE` otherwise)."

        Design: Corner/consistency_model/duplicate_open_repeat_case_rejected
        """
        original = setup_closed_original_call()
        advance_clock("2026-08-10T14:00:00Z")
        new_call_1 = open_triaged_call(
            original["veh"]["id"], severity="DRIVABLE", received_at=None,
            breakdown_location_text="I-70 mm 300",
            distance_miles_from_depot=35,
            symptom_description="no start again")
        open_repeat_failure_case(original["veh"]["id"],
                                 original["call"]["id"], new_call_1["id"])
        new_call_2 = open_triaged_call(
            original["veh"]["id"], severity="DRIVABLE", received_at=None,
            breakdown_location_text="I-70 mm 305",
            distance_miles_from_depot=36, symptom_description="and again")
        resp = api.create_repeat_failure_case(
            {"vehicle_id": original["veh"]["id"],
             "original_service_call_id": original["call"]["id"],
             "new_service_call_id": new_call_2["id"]},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_CASE)

    def test_repeat_window_expired_confirm_rejected(self, api):
        """PRD: "Confirming the comeback — allowed only when the
        `charge_policy` is not `FULL`, else `ERR_REPEAT_WINDOW_EXPIRED` —
        marks the new call with `is_comeback` true"; a FULL-policy case can
        still be rejected: "Rejecting the case records `decided_by` and an
        optional `decision_note` and terminates the case as `REJECTED`."

        Design: Corner/consistency_model/repeat_window_expired_confirm_rejected
        """
        original = setup_closed_original_call()
        # Odometer is monotone non-decreasing: 121000 stays above the
        # original completion reading (120450).
        get_success_data(api.patch_vehicle(
            original["veh"]["id"], {"odometer_miles": 121000}, DISPATCHER))
        # 52 whole days after the 2026-08-03 completion -> FULL policy.
        new_call = open_triaged_call(
            original["veh"]["id"], severity="DRIVABLE",
            received_at="2026-09-24T14:00:00Z",
            breakdown_location_text="I-70 mm 300",
            distance_miles_from_depot=35,
            symptom_description="no start again")
        case = open_repeat_failure_case(original["veh"]["id"],
                                        original["call"]["id"],
                                        new_call["id"])
        assert case["charge_policy"] == "FULL"
        get_success_data(api.review_repeat_failure_case(case["id"],
                                                        DISPATCHER))
        resp = api.decide_repeat_failure_case(
            case["id"], {"decision": "CONFIRMED_COMEBACK"}, OPS)
        validate_error(resp, ApiErrorId.ERR_REPEAT_WINDOW_EXPIRED)
        rejected = get_success_data(api.decide_repeat_failure_case(
            case["id"], {"decision": "REJECTED",
                         "decision_note": "outside comeback window"}, OPS))
        assert rejected["status"] == "REJECTED"
