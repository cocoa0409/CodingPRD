"""Multi-hop cascades: pathology finalization and the positive non-invasive result."""
from test_helpers import (
    active_recommendation,
    apply_block_action,
    book_slot,
    check_in,
    claim_for_booking,
    complete_exam,
    confirm_prep,
    create_block,
    finalize_report,
    is_iso8601_timestamp,
    move_clock,
    open_episode,
    order_noninvasive_test,
    post_test_result,
    read_booking,
    read_claim,
    read_episode,
    read_patient,
    receive_report,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    specimen,
    staff_block,
    start_exam,
)

PLAN_P1 = {
    "plan_code": "P1",
    "payer_name": "Meridian Health",
    "preventive_coverage_pct": 1.00,
    "diagnostic_coinsurance_pct": 0.20,
    "deductible_cents": 150000,
    "out_of_pocket_max_cents": 400000,
    "polypectomy_carveout": "DIAGNOSTIC_CONVERTED",
    "modifier_33_honored": True,
    "anesthesia_bundled": False,
}


def _single_adenoma_report_awaiting_finalization():
    """Run a MAC colonoscopy to completion, receive a one-adenoma report, then move the
    logical clock forward so the finalization stamp is unambiguous."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**PLAN_P1)
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician()
    patient = register_patient(plan["id"], birth_date="1975-04-10")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")
    staff_block(block["id"], anesthetist["id"])
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    provisional_claim = claim_for_booking(booking["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    complete_exam(booking["id"], endoscopist["id"], prep_quality_bbps=7,
                  polyps_removed_count=1, largest_polyp_mm=4, specimen_count=1)
    report = receive_report(booking["id"], [specimen("A", "TUBULAR_ADENOMA", 4)])
    move_clock("2026-09-18T09:30:00Z")
    return {
        "endoscopist_id": endoscopist["id"],
        "patient_id": patient["id"],
        "episode_id": episode["id"],
        "booking_id": booking["id"],
        "report_id": report["id"],
        "claim_id": provisional_claim["id"],
        "provisional_claim": provisional_claim,
        "received_report": report,
    }


def test_the_report_sits_in_received_against_a_completed_booking_before_the_cascade():
    """A new report is created in `status` `RECEIVED` with `amendment_count` at 0,
    `finalized_at` null, `routed_to_endoscopist_id` null, and `amendment_reason` null.

    A report may only be received against a booking that has reached `COMPLETED`;
    against a booking in any other status the request is rejected with
    `ERR_INVALID_BOOKING_STATE`.

    Design: Difficulty/transitive_cascade/pathology_finalize_four_hop_cascade
    """
    scenario = _single_adenoma_report_awaiting_finalization()
    received = scenario["received_report"]
    booking = read_booking(scenario["booking_id"])

    assert received["status"] == "RECEIVED"
    assert received["amendment_count"] == 0
    assert received["finalized_at"] is None
    assert received["routed_to_endoscopist_id"] is None
    assert booking["status"] == "COMPLETED"
    assert scenario["provisional_claim"]["patient_responsibility_cents"] == 8090


def test_hop_one_stamps_the_clock_and_routes_the_report_to_the_performing_endoscopist():
    """Hop one: the report moves `RECEIVED → FINALIZED` (or `AMENDED → FINALIZED`),
    `finalized_at` is stamped from the logical clock, and `routed_to_endoscopist_id` is
    set to the booking's `performing_endoscopist_id` — this is the routing act,
    delivering the result to the physician who did the exam.

    Design: Difficulty/transitive_cascade/pathology_finalize_four_hop_cascade
    """
    scenario = _single_adenoma_report_awaiting_finalization()
    finalized = finalize_report(scenario["report_id"])

    assert finalized["status"] == "FINALIZED"
    assert is_iso8601_timestamp(finalized["finalized_at"])
    assert finalized["finalized_at"][:19] == "2026-09-18T09:30:00"
    assert finalized["routed_to_endoscopist_id"] == scenario["endoscopist_id"]


def test_hops_two_and_three_set_the_eighty_four_month_guideline_interval_on_the_episode():
    """Hop two: because the report is now finalized, a `SurveillanceRecommendation` is
    created with `basis` `GUIDELINE` from the finalized-pathology aggregate, and any
    recommendation on that episode that was previously `ACTIVE` becomes `SUPERSEDED`,
    since only one recommendation per episode may be `ACTIVE` at a time.

    Otherwise the base is 84 months, seven years.

    Design: Difficulty/transitive_cascade/pathology_finalize_four_hop_cascade
    """
    scenario = _single_adenoma_report_awaiting_finalization()
    finalize_report(scenario["report_id"])

    recommendation = active_recommendation(scenario["episode_id"])
    episode = read_episode(scenario["episode_id"])

    assert recommendation["basis"] == "GUIDELINE"
    assert recommendation["computed_interval_months"] == 84
    assert recommendation["assigned_interval_months"] == 84
    assert recommendation["next_due_date"] == "2033-09-15"
    assert recommendation["pathology_report_id"] == scenario["report_id"]
    assert episode["clinical_status"] == "CLOSED_SURVEILLANCE_SET"
    assert episode["assigned_interval_months"] == 84
    assert episode["due_date"] == "2033-09-15"


def test_hop_four_reprices_the_claim_and_leaves_the_patient_ledgers_untouched():
    """Hop four: because the episode has closed, the booking's `BillingClaim` is repriced
    under the final pricing pass, moving `PROVISIONAL_PRICED → REPRICED`, incrementing
    the claim's `reprice_count`, and writing the booking's `final_classification`.

    Pricing reads the patient's `deductible_applied_cents` and `oop_applied_cents`
    ledgers as they stand at pricing time, and only claims that have reached `FINALIZED`
    have contributed to those ledgers.

    Design: Difficulty/transitive_cascade/pathology_finalize_four_hop_cascade
    """
    scenario = _single_adenoma_report_awaiting_finalization()
    finalize_report(scenario["report_id"])

    claim = read_claim(scenario["claim_id"])
    booking = read_booking(scenario["booking_id"])
    patient = read_patient(scenario["patient_id"])

    assert claim["variant"] == "FINAL"
    assert claim["status"] == "REPRICED"
    assert claim["reprice_count"] == 1
    assert claim["allowed_amount_cents"] == 224950
    assert claim["deductible_applied_cents"] == 150000
    assert claim["coinsurance_cents"] == 14990
    assert claim["patient_responsibility_cents"] == 164990
    assert claim["plan_paid_cents"] == 59960
    assert booking["planned_classification"] == "SCREENING_PREVENTIVE"
    assert booking["final_classification"] == "DIAGNOSTIC"
    assert patient["deductible_applied_cents"] == 0
    assert patient["oop_applied_cents"] == 0


def _positive_stool_test():
    """Order a FIT against a fresh average-risk episode and post a positive result."""
    move_clock("2026-08-10T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"], birth_date="1975-04-10")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    patient_before_test = read_patient(patient["id"])
    test = order_noninvasive_test(episode["id"], "FIT", "2026-08-08")
    patient_after_order = read_patient(patient["id"])
    return {
        "patient_id": patient["id"],
        "episode_id": episode["id"],
        "test_id": test["id"],
        "created_episode": episode,
        "created_test": test,
        "patient_before_test": patient_before_test,
        "patient_after_order": patient_after_order,
    }


def test_the_ordering_episode_is_direct_and_due_in_one_hundred_and_eighty_days():
    """It is `DIRECT` when both links are absent.

    A `DIAGNOSTIC_FOLLOWUP` episode is due in 90 days; every other indication is due in
    180 days.

    The test is created with `result` at `PENDING` and `resulted_at` null; its
    `episode_id` is the ordering episode, and `follow_up_episode_id` is null.

    Design: Difficulty/transitive_cascade/positive_noninvasive_test_four_hop_cascade
    """
    scenario = _positive_stool_test()

    assert scenario["created_episode"]["origin"] == "DIRECT"
    assert scenario["created_episode"]["due_date"] == "2027-02-06"
    assert scenario["created_test"]["result"] == "PENDING"
    assert scenario["created_test"]["resulted_at"] is None
    assert scenario["created_test"]["follow_up_episode_id"] is None
    assert scenario["patient_before_test"]["open_episode_count"] == 1
    assert scenario["patient_before_test"]["navigation_priority"] == "ROUTINE"
    assert scenario["patient_after_order"]["open_episode_count"] == 1
    assert scenario["patient_after_order"]["navigation_priority"] == "ROUTINE"


def test_positive_result_spawns_the_follow_up_episode_and_closes_the_laboratory_loop():
    """Hop one creates a new `ScreeningEpisode` for the same patient with `indication`
    `DIAGNOSTIC_FOLLOWUP`, `origin` `NONINVASIVE_POSITIVE`, and `preceding_episode_id`
    set to the episode that ordered this test.

    Hop two records the new episode's identifier on the test as `follow_up_episode_id`,
    closing the loop between laboratory result and clinical action.

    Posting a result stamps `resulted_at` from the logical clock in every case.

    Design: Difficulty/transitive_cascade/positive_noninvasive_test_four_hop_cascade
    """
    scenario = _positive_stool_test()
    resulted = post_test_result(scenario["test_id"], "POSITIVE")

    assert resulted["result"] == "POSITIVE"
    assert is_iso8601_timestamp(resulted["resulted_at"])
    assert resulted["resulted_at"][:19] == "2026-08-10T00:00:00"
    assert resulted["follow_up_episode_id"] is not None

    follow_up = read_episode(resulted["follow_up_episode_id"])
    assert follow_up["indication"] == "DIAGNOSTIC_FOLLOWUP"
    assert follow_up["origin"] == "NONINVASIVE_POSITIVE"
    assert follow_up["preceding_episode_id"] == scenario["episode_id"]
    assert follow_up["index_date"] == "2026-08-10"
    assert follow_up["eligibility_status"] == "ELIGIBLE"


def test_hops_three_and_four_flip_priority_then_recompute_the_thirty_day_due_date():
    """Hop three recomputes the patient's `open_episode_count` and, from it,
    `navigation_priority` — and because the patient now holds both the original episode
    and the follow-up, that count is frequently at two, which flips the priority to
    `HIGH`.

    Hop four then recomputes the new episode's `due_date`; since the priority was just
    recomputed, the 30-day high-priority window applies rather than the 90-day
    diagnostic-followup window, and the new episode's `navigation_status` is moved to
    `OUTREACH_ACTIVE` so the navigator picks it up immediately.

    Design: Difficulty/transitive_cascade/positive_noninvasive_test_four_hop_cascade
    """
    scenario = _positive_stool_test()
    resulted = post_test_result(scenario["test_id"], "POSITIVE")

    patient = read_patient(scenario["patient_id"])
    follow_up = read_episode(resulted["follow_up_episode_id"])
    original = read_episode(scenario["episode_id"])

    assert patient["open_episode_count"] == 2
    assert patient["navigation_priority"] == "HIGH"
    assert follow_up["due_date"] == "2026-09-09"
    assert follow_up["navigation_status"] == "OUTREACH_ACTIVE"
    assert original["due_date"] == "2027-02-06"
