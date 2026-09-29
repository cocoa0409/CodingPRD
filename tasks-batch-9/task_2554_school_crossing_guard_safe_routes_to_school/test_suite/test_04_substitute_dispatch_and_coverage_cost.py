"""Offering an open duty day to substitutes, and pricing the coverage.

Dispatch is a loop: each decline pushes the report back to DISPATCH_PENDING with
the declining guard excluded and the attempt counter still climbing, and the
price of the eventual acceptance is assembled in a pinned order of steps. These
tests walk the loop to exhaustion and pin the cost arithmetic.
"""
from test_helpers import validate_success
from test_helpers.assertions import (
    assert_absence_report,
    assert_dispatch_offer,
    assert_same_instant,
)
from test_helpers.factories import offer_response_payload
from test_helpers.fixtures import (
    SUPERVISOR,
    answer_offer,
    dispatch,
    read_absence,
    read_post,
    setup_absence_ready_for_dispatch,
)
from test_helpers.test_users import make_crossing_guard_headers


def test_declining_an_offer_returns_the_report_to_dispatch_pending(api):
    """A decline clears the live offer, excludes the decliner and leaves the
    attempt counter where it was.

    PRD: "so the repeat-dispatch penalty in the cost formula grows with every
    round of declines and lapses."

    Design: Difficulty/non_linear_state_machine/absence_offer_decline_loop_revisits_offer_out_then_exhausts_pool
    """
    scenario = setup_absence_ready_for_dispatch()
    sam, nia = scenario["substitutes"]
    offered = dispatch(scenario["absence"]["id"])
    assert offered["status"] == "OFFER_OUT"
    assert offered["current_offer_guard_id"] == sam["id"]

    declined = validate_success(api.respond_to_offer(
        scenario["absence"]["id"], offer_response_payload("DECLINE"),
        make_crossing_guard_headers(sam["id"])))

    assert_absence_report(declined)
    assert declined["status"] == "DISPATCH_PENDING"
    assert declined["dispatch_attempt_count"] == 1
    assert declined["current_offer_guard_id"] is None
    assert declined["current_offer_expires_at"] is None
    assert declined["excluded_guard_ids"] == [sam["id"]]
    assert_dispatch_offer(declined["dispatch_offers"][0], 1, sam["id"], "DECLINED")
    assert nia["id"] not in declined["excluded_guard_ids"]


def test_a_dispatch_with_an_exhausted_pool_records_an_uncovered_gap(api):
    """Once both substitutes have declined nobody qualifies, and the empty pool is
    a legal transition rather than an error.

    PRD: "no offer object is appended, `dispatch_attempt_count` is left
    untouched, and the response is 200 OK carrying the report."

    Design: Difficulty/non_linear_state_machine/absence_offer_decline_loop_revisits_offer_out_then_exhausts_pool
    """
    scenario = setup_absence_ready_for_dispatch()
    sam, nia = scenario["substitutes"]
    absence_id = scenario["absence"]["id"]
    dispatch(absence_id)
    answer_offer(absence_id, sam["id"], "DECLINE")
    second = dispatch(absence_id)
    assert second["current_offer_guard_id"] == nia["id"]
    answer_offer(absence_id, nia["id"], "DECLINE")

    response = api.dispatch_absence_report(absence_id, SUPERVISOR)

    report = validate_success(response)
    assert report["status"] == "UNCOVERED_GAP"
    assert report["dispatch_attempt_count"] == 2
    assert len(report["excluded_guard_ids"]) == 2
    assert set(report["excluded_guard_ids"]) == {sam["id"], nia["id"]}
    assert len(report["dispatch_offers"]) == 2
    assert_dispatch_offer(report["dispatch_offers"][0], 1, sam["id"], "DECLINED")
    assert_dispatch_offer(report["dispatch_offers"][1], 2, nia["id"], "DECLINED")
    assert report["current_offer_guard_id"] is None
    assert report["current_offer_expires_at"] is None
    assert report["substitute_guard_id"] is None
    assert report["substitute_cost_cents"] is None
    post = read_post(scenario["post"]["id"])
    assert post["coverage_status"] == "UNCOVERED"
    assert post["open_gap_count"] == 1


def test_the_administrative_fee_tier_reads_the_subtotal_not_the_final_total(api):
    """A same-day single shift on the second dispatch attempt costs 4183 cents: the
    subtotal of 3746 stays in the 5 percent band even though the total clears 4000.

    PRD: "Seventh, the administrative fee is 8 percent of that subtotal when the
    subtotal is 4000 cents or more and 5 percent otherwise, rounded half up to a
    whole cent; a final total that happens to cross 4000 cents does not
    retroactively promote the tier."

    Design: Difficulty/combinatorial_formula/substitute_cost_fee_tier_keyed_on_subtotal_not_total
    """
    scenario = setup_absence_ready_for_dispatch()
    sam, nia = scenario["substitutes"]
    absence_id = scenario["absence"]["id"]
    dispatch(absence_id)
    answer_offer(absence_id, sam["id"], "DECLINE")
    dispatch(absence_id)

    covered = validate_success(api.respond_to_offer(
        absence_id, offer_response_payload("ACCEPT"),
        make_crossing_guard_headers(nia["id"])))

    assert_absence_report(covered)
    assert covered["status"] == "COVERED"
    assert covered["substitute_guard_id"] == nia["id"]
    assert covered["substitute_cost_cents"] == 4183
    assert covered["substitute_cost_cents"] != 4296


def test_the_pinned_urgency_tier_and_attempt_count_drive_the_price(api):
    """The tier is read off the report rather than recomputed at acceptance, and the
    repeat-dispatch penalty counts every attempt after the first.

    PRD: "Third, the notice horizon is read straight off the report's pinned
    `urgency_tier`, never recomputed." ... "Eighth, the repeat-dispatch penalty is
    250 cents for every dispatch attempt after the first".

    Design: Difficulty/combinatorial_formula/substitute_cost_fee_tier_keyed_on_subtotal_not_total
    """
    scenario = setup_absence_ready_for_dispatch()
    sam, nia = scenario["substitutes"]
    absence_id = scenario["absence"]["id"]
    dispatch(absence_id)
    answer_offer(absence_id, sam["id"], "DECLINE")
    dispatch(absence_id)

    covered = validate_success(api.respond_to_offer(
        absence_id, offer_response_payload("ACCEPT"),
        make_crossing_guard_headers(nia["id"])))

    assert covered["urgency_tier"] == "SAME_DAY"
    assert covered["notice_hours"] == 6.25
    assert covered["dispatch_attempt_count"] == 2
    assert covered["excluded_guard_ids"] == [sam["id"]]
    assert covered["current_offer_guard_id"] is None
    assert_dispatch_offer(covered["dispatch_offers"][1], 2, nia["id"], "ACCEPTED")


def test_a_certification_expiring_on_the_absence_date_is_still_eligible(api):
    """The eligibility date boundary is inclusive: expiry on the absence date keeps
    a substitute in the pool while expiry the day before removes them.

    PRD: "`certification_expires_on` is on or after the `absence_date`, so a
    certification expiring exactly on the absence date is still valid".

    Design: Difficulty/boundary_precision_check/substitute_certification_expiring_on_absence_date_is_still_eligible
    """
    scenario = setup_absence_ready_for_dispatch(
        substitutes=[("Sam Okafor", "Z-NORTH"), ("Nia Brandt", "Z-NORTH")],
        substitute_expiries=["2026-09-16", "2026-09-15"])
    sam, nia = scenario["substitutes"]

    response = api.dispatch_absence_report(scenario["absence"]["id"], SUPERVISOR)

    report = validate_success(response)
    assert report["status"] == "OFFER_OUT"
    assert report["status"] != "UNCOVERED_GAP"
    assert report["current_offer_guard_id"] == sam["id"]
    assert report["dispatch_attempt_count"] == 1
    assert len(report["dispatch_offers"]) == 1
    assert_dispatch_offer(report["dispatch_offers"][0], 1, sam["id"], "OPEN")
    assert report["excluded_guard_ids"] == []
    offered_ids = [offer["offered_guard_id"] for offer in report["dispatch_offers"]]
    assert nia["id"] not in offered_ids


def test_an_offer_expires_forty_five_minutes_after_the_clock(api):
    """The offer window is measured from the logical clock, not from wall time.

    PRD: "`offer_expires_at` set to the logical clock plus **45 minutes**, and
    `offer_status` set to `OPEN`".

    Design: Difficulty/boundary_precision_check/substitute_certification_expiring_on_absence_date_is_still_eligible
    """
    scenario = setup_absence_ready_for_dispatch(
        substitutes=[("Sam Okafor", "Z-NORTH"), ("Nia Brandt", "Z-NORTH")],
        substitute_expiries=["2026-09-16", "2026-09-15"])

    report = dispatch(scenario["absence"]["id"])

    assert_same_instant(report["current_offer_expires_at"], "2026-09-16T01:45:00Z",
                        "AbsenceReport.current_offer_expires_at")
    offer = report["dispatch_offers"][0]
    assert_same_instant(offer["offered_at"], "2026-09-16T01:00:00Z",
                        "DispatchOffer.offered_at")
    assert_same_instant(offer["offer_expires_at"], "2026-09-16T01:45:00Z",
                        "DispatchOffer.offer_expires_at")
    assert read_absence(scenario["absence"]["id"])["status"] == "OFFER_OUT"
