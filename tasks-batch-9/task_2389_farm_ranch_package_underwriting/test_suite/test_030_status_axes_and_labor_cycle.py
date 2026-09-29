"""The two independent policy status axes, and the closed workers-compensation
coordination cycle."""

from test_helpers import (
    UW,
    ApiErrorId,
    bind_policy_ok,
    complete_inspection_ok,
    get_success_data,
    read_labor_profile,
    read_policy,
    read_recommendations,
    review_recommendation,
    run_sweep_ok,
    set_clock,
    setup_rated_dwelling_policy,
    setup_rated_policy_with_inspector,
    submit_evidence,
    upsert_labor_profile,
    validate_error,
    validate_success,
    verify_wc,
)

PROOF = {
    "wc_carrier_name": "Heartland Mutual",
    "wc_policy_number": "WC-77120",
    "wc_expiry_date": "2026-08-20",
}

MAJOR_FINDING = {
    "severity": "MAJOR",
    "description": "Install PTO shield",
    "due_date": "2026-09-30",
}


def test_compliance_axis_advances_while_the_underwriting_axis_holds_at_rated(api):
    """"A farm policy carries two status fields that advance independently and
    must never be conflated." Completing an inspection with one MAJOR finding
    scores 22 and moves the loss-control axis to `RECS_OPEN`, and accepting the
    remediation evidence moves it on to `COMPLIANT`, while `uw_status` sits at
    `RATED` throughout and no premium figure moves.

    Design: Difficulty/non_linear_state_machine/policy_uw_and_compliance_axes_move_independently
    """
    scenario = setup_rated_policy_with_inspector()

    completed = complete_inspection_ok(
        scenario.inspection["id"],
        scenario.inspector_id,
        findings_summary="Guard missing on PTO shaft",
        findings=[MAJOR_FINDING],
    )
    assert completed["hazard_score"] == 22
    assert completed["recommendation_count"] == 1

    after_completion = read_policy(scenario.policy_id)
    assert after_completion["compliance_status"] == "RECS_OPEN"
    assert after_completion["uw_status"] == "RATED"
    assert after_completion["total_premium_cents"] == 269_200

    recommendation = read_recommendations(scenario.inspection["id"])[0]
    assert recommendation["status"] == "OPEN"
    submitted = get_success_data(
        submit_evidence(scenario.agent_headers, recommendation["id"], completed_date="2026-08-18")
    )
    assert submitted["status"] == "SUBMITTED"
    verified = get_success_data(
        review_recommendation(recommendation["id"], "ACCEPT", review_note="Verified from photo")
    )
    assert verified["status"] == "VERIFIED"

    after_review = read_policy(scenario.policy_id)
    assert after_review["compliance_status"] == "COMPLIANT"
    assert after_review["uw_status"] == "RATED"
    assert after_review["total_premium_cents"] == 269_200


def test_binding_moves_only_the_underwriting_axis(api):
    """"A policy can be `BOUND` while `RECS_OVERDUE`, or `DRAFT` while
    `COMPLIANT`; the axes constrain each other only where §3 says so." After the
    file has been driven to `COMPLIANT`, the bind advances `uw_status` to
    `BOUND`, stamps `bound_at` and `bound_by_user_id`, and leaves the compliance
    axis and the premium untouched.

    Design: Difficulty/non_linear_state_machine/policy_uw_and_compliance_axes_move_independently
    """
    scenario = setup_rated_policy_with_inspector()
    complete_inspection_ok(
        scenario.inspection["id"],
        scenario.inspector_id,
        findings_summary="Guard missing on PTO shaft",
        findings=[MAJOR_FINDING],
    )
    recommendation = read_recommendations(scenario.inspection["id"])[0]
    submit_evidence(scenario.agent_headers, recommendation["id"], completed_date="2026-08-18")
    review_recommendation(recommendation["id"], "ACCEPT")

    bound = bind_policy_ok(scenario.policy_id)

    assert bound["uw_status"] == "BOUND"
    assert bound["compliance_status"] == "COMPLIANT"
    assert bound["total_premium_cents"] == 269_200
    assert bound["bound_at"].startswith("2026-08-15T00:00:00")
    assert bound["bound_by_user_id"] == UW["X-User-ID"]


def test_coordination_status_traverses_the_pending_verified_lapsed_cycle(api):
    """"A verified proof does not stay verified forever: the compliance
    checkpoint moves `VERIFIED → LAPSED` once `wc_expiry_date` falls before the
    current clock date, clearing `verified_at` and `verified_by_user_id` and
    closing the coordination cycle that a fresh submission then reopens at
    `PENDING_PROOF`." Four year-round and four seasonal workers score 6.00, so
    the profile enters `PENDING_PROOF`, is verified, lapses at the checkpoint and
    is verified once more after a renewal certificate is filed.

    Design: Difficulty/non_linear_state_machine/labor_profile_pending_verified_lapsed_cycle
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=True)
    labor_profile_id = scenario.labor_profile["id"]
    assert scenario.labor_profile["coordination_status"] == "NOT_REQUIRED"

    pending = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        **PROOF,
    )
    assert float(pending["labor_exposure_units"]) == 6.00
    assert pending["wc_required"] is True
    assert pending["coordination_status"] == "PENDING_PROOF"

    verified = get_success_data(verify_wc(labor_profile_id, note="Certificate on file"))
    assert verified["coordination_status"] == "VERIFIED"
    assert verified["verified_at"].startswith("2026-08-15T00:00:00")

    set_clock("2026-08-21T00:00:00Z")
    counters = run_sweep_ok(scenario.policy_id)
    assert counters["labor_profiles_lapsed"] == 1

    lapsed = read_labor_profile(labor_profile_id)
    assert lapsed["coordination_status"] == "LAPSED"
    assert lapsed["verified_at"] is None
    assert lapsed["verified_by_user_id"] is None

    renewed = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        wc_carrier_name="Heartland Mutual",
        wc_policy_number="WC-88431",
        wc_expiry_date="2027-08-20",
    )
    assert renewed["coordination_status"] == "PENDING_PROOF"
    assert renewed["wc_policy_number"] == "WC-88431"

    reverified = get_success_data(verify_wc(labor_profile_id, note="Renewal certificate on file"))
    assert reverified["coordination_status"] == "VERIFIED"
    assert reverified["verified_at"].startswith("2026-08-21T00:00:00")


def test_verifying_an_already_verified_profile_is_rejected_not_ignored(api):
    """"Three conditions guard it: the `coordination_status` must actually be
    `PENDING_PROOF`, or the call is rejected with `ERR_WC_STATE_INVALID`." A
    second verification against a row that is already `VERIFIED` is therefore an
    error rather than a no-op, and the failed call applies no side effect at all.

    Design: Difficulty/non_linear_state_machine/labor_profile_pending_verified_lapsed_cycle
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=True)
    labor_profile_id = scenario.labor_profile["id"]
    upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        **PROOF,
    )
    first = get_success_data(verify_wc(labor_profile_id, note="Certificate on file"))

    duplicate = verify_wc(labor_profile_id, note="Duplicate verification attempt")

    validate_error(duplicate, ApiErrorId.ERR_WC_STATE_INVALID.value, 409)
    unchanged = read_labor_profile(labor_profile_id)
    assert unchanged["coordination_status"] == "VERIFIED"
    assert unchanged["version"] == first["version"]
    assert unchanged["verified_at"] == first["verified_at"]


def test_the_upsert_keeps_one_profile_row_and_climbs_its_version(api):
    """"A policy has at most one labor profile, and the producer maintains it as
    a whole-record upsert: the first submission creates the row, every later
    submission overwrites it in place and lifts its `version` by 1." A
    verification lifts the same row again, so the coordination cycle never
    produces a second profile for the policy.

    Design: Difficulty/non_linear_state_machine/labor_profile_pending_verified_lapsed_cycle
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=True)
    labor_profile_id = scenario.labor_profile["id"]
    assert scenario.labor_profile["version"] == 1

    second = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        **PROOF,
    )
    assert second["id"] == labor_profile_id
    assert second["version"] == 2

    verified = get_success_data(verify_wc(labor_profile_id))
    assert verified["version"] == 3

    listed = validate_success(api.get_policy_labor_profile(scenario.policy_id, UW))
    assert isinstance(listed, list)
    assert len(listed) == 1
    assert listed[0]["id"] == labor_profile_id
