"""Compliance-variant divergences, decayed strike arithmetic, penalty and audit
component formulas, and the parallel/cyclic state machines behind them.

Every test builds its whole world through the public API: the harness restarts
the server (and empties the database) before each individual test.
"""
from test_helpers import (
    AGENT,
    OFFICER,
    assert_instant_equals,
    assert_money_int,
    assert_two_decimal_places,
    claims_of_notice,
    create_enrolled_rights_holder,
    create_forwarded_counter_notice,
    create_misrepresentation_case,
    create_notice,
    create_processed_notice,
    create_rights_holder,
    create_validated_notice,
    get_account,
    get_claim,
    get_content_item,
    get_counter_notice,
    get_provider,
    get_rights_holder,
    list_account_strikes,
    make_abuse_investigator_headers,
    make_compliance_officer_headers,
    make_subscriber_headers,
    parse_instant,
    process_notice,
    set_clock,
    setup_account_with_items,
    setup_documented_provider,
    setup_provider_with_agent,
    strike_summary,
    termination_cases_of_account,
    validate_notice,
    validate_paginated,
    validate_success,
)

# The statutory elements of a notice that omits only the accuracy statement:
# 8 + 18 + 20 + 10 + 18 + 18 = 92 of the 100 available weight.
_ELEMENTS_SCORING_92 = {
    "signature_present": True,
    "work_identification": "Sound recording: Orbit Vol. 1, track 3",
    "material_identification": "Track 3 posted at the claimed URL",
    "contact_email": "legal@orbit.example",
    "good_faith_statement": True,
    "accuracy_statement": False,
    "authority_statement": True,
    "sworn_under_penalty": True,
}

_CLAIMED_URL = "https://northstar.example/complained-of/1"


def _scene(item_count: int = 1, **policy_overrides) -> dict:
    """Documented provider (contact published, agent REGISTERED, policy
    PUBLISHED) plus one account owning `item_count` AVAILABLE items."""
    setup = setup_documented_provider(**policy_overrides)
    account_scene = setup_account_with_items(setup["provider"]["id"], item_count)
    return {
        "provider": setup["provider"],
        "policy": setup["policy"],
        "account": account_scene["account"],
        "items": account_scene["items"],
    }


# ---------------------------------------------------------------------------
# Notice compliance: one payload, two statutory variants
# ---------------------------------------------------------------------------

def test_same_payload_validates_on_web_form_and_is_rejected_on_api_bulk(api):
    """PRD §3.5: "It is `STRICT_COMPLIANCE` when the `submission_channel` is `API_BULK` or the complaining holder's `program_tier` is `TRUSTED`; in every other case — a web-form or email submission from a holder at `STANDARD` or `VERIFIED` — it is `SUBSTANTIAL_COMPLIANCE`."

    Design: Difficulty/dual_variant_calc/notice_compliance_strict_vs_substantial_same_payload
    """
    setup_provider_with_agent()
    holder = create_rights_holder()

    web_notice = create_notice(holder["id"], [_CLAIMED_URL],
                               submission_channel="WEB_FORM",
                               **_ELEMENTS_SCORING_92)
    bulk_notice = create_notice(holder["id"], [_CLAIMED_URL],
                                submission_channel="API_BULK",
                                **_ELEMENTS_SCORING_92)

    web = validate_success(api.validate_notice(web_notice["id"], AGENT),
                           expected_status=200)
    bulk = validate_success(api.validate_notice(bulk_notice["id"], AGENT),
                            expected_status=200)

    # Identical elements, identical score.
    assert web["completeness_score"] == 92
    assert bulk["completeness_score"] == 92

    # The web-form submission is held to the substantial standard and clears it.
    assert web["compliance_variant"] == "SUBSTANTIAL_COMPLIANCE"
    assert web["status"] == "VALIDATED"
    assert web["rejection_reason"] is None
    assert web["validated_at"] is not None

    # The bulk submission is held to the strict standard and fails it on score.
    assert bulk["compliance_variant"] == "STRICT_COMPLIANCE"
    assert bulk["compliance_variant"] != "SUBSTANTIAL_COMPLIANCE"
    assert bulk["status"] == "REJECTED"
    assert bulk["status"] != "VALIDATED"
    assert bulk["rejection_reason"] == "SCORE_BELOW_THRESHOLD"


def test_strict_variant_rejection_charges_the_complainant_without_opening_a_case(api):
    """PRD §3.5: "On this branch no claim is created and no access is disabled — but the rejection is held against the complainant: the holder's `rejected_count` increments by 1 and the abuse score of Section 3.9 is recomputed, and if that recomputed score reaches the auto-open floor the system opens a misrepresentation case against the holder with `opened_by_user_id` null, provided an eligible claim exists to attach it to."

    Design: Difficulty/dual_variant_calc/notice_compliance_strict_vs_substantial_same_payload
    """
    setup_provider_with_agent()
    holder = create_rights_holder()
    bulk_notice = create_notice(holder["id"], [_CLAIMED_URL],
                                submission_channel="API_BULK",
                                **_ELEMENTS_SCORING_92)

    bulk = validate_success(api.validate_notice(bulk_notice["id"], AGENT),
                            expected_status=200)
    assert bulk["status"] == "REJECTED"
    assert bulk["rejection_reason"] == "SCORE_BELOW_THRESHOLD"

    holder_after = get_rights_holder(holder["id"])
    assert holder_after["rejected_count"] == 1
    assert holder_after["notices_processed"] == 0
    assert holder_after["withdrawn_count"] == 0
    # 0*1 + 1*2 + 0*3 = 2, divided by the volume floor of 5, times 100.
    assert_two_decimal_places(holder_after["abuse_score"], "abuse_score")
    assert float(holder_after["abuse_score"]) == 40.00

    # The auto-open floor is reached, but this holder owns no eligible claim.
    cases, meta = validate_paginated(
        api.list_misrepresentation_cases(OFFICER, {"rights_holder_id": holder["id"]})
    )
    assert meta["total_count"] == 0
    assert cases == []


def test_api_bulk_needs_full_score_and_a_sworn_statement_to_validate(api):
    """PRD §3.5: "Under `STRICT_COMPLIANCE` the notice clears the threshold only when `completeness_score` is at least 100 **and** `sworn_under_penalty` is true; the very same payload that clears the substantial threshold at 92 does not clear the strict one."

    Design: Difficulty/dual_variant_calc/notice_compliance_strict_vs_substantial_same_payload
    """
    setup_provider_with_agent()
    holder = create_rights_holder()

    complete_elements = dict(_ELEMENTS_SCORING_92, accuracy_statement=True)
    sworn = create_notice(holder["id"], [_CLAIMED_URL],
                          submission_channel="API_BULK", **complete_elements)
    unsworn = create_notice(holder["id"], [_CLAIMED_URL],
                            submission_channel="API_BULK",
                            **dict(complete_elements, sworn_under_penalty=False))

    sworn_result = validate_success(api.validate_notice(sworn["id"], AGENT),
                                    expected_status=200)
    unsworn_result = validate_success(api.validate_notice(unsworn["id"], AGENT),
                                       expected_status=200)

    assert sworn_result["completeness_score"] == 100
    assert sworn_result["compliance_variant"] == "STRICT_COMPLIANCE"
    assert sworn_result["status"] == "VALIDATED"
    assert sworn_result["rejection_reason"] is None

    # Same score of 100, but the oath is missing, so the strict threshold is
    # not cleared and the reason is the unsworn one rather than the score one.
    assert unsworn_result["completeness_score"] == 100
    assert unsworn_result["compliance_variant"] == "STRICT_COMPLIANCE"
    assert unsworn_result["status"] == "REJECTED"
    assert unsworn_result["rejection_reason"] == "UNSWORN_UNDER_STRICT_VARIANT"
    assert unsworn_result["rejection_reason"] != "SCORE_BELOW_THRESHOLD"


# ---------------------------------------------------------------------------
# Strike points: per-strike rounding before the sum
# ---------------------------------------------------------------------------

def _two_strike_account_with_one_decayed_strike():
    """One VERIFIED-weight strike accrued at the clock start and decayed by a
    100-day clock advance, then one STANDARD-weight strike accrued fresh."""
    scene = _scene(item_count=2)
    account = scene["account"]
    verified_holder = create_enrolled_rights_holder("VERIFIED")
    standard_holder = create_rights_holder()

    first_notice = create_processed_notice(
        verified_holder["id"], [scene["items"][0]["content_url"]]
    )
    set_clock("2026-11-09T00:00:00Z")
    second_notice = create_validated_notice(
        standard_holder["id"], [scene["items"][1]["content_url"]]
    )
    return {
        "account": account,
        "policy": scene["policy"],
        "first_notice": first_notice,
        "second_notice": second_notice,
    }


def test_decayed_and_fresh_strike_total_is_rounded_per_strike_before_summing(api):
    """PRD §3.8: "The strike's contribution is the base of 10 points multiplied by the strike's snapshotted `weight` and then by its decay factor, **rounded half up to two decimal places for that strike alone**."

    Design: Difficulty/dual_variant_calc/strike_points_chronological_vs_snapshot_diverge_on_decayed_strike
    """
    scene = _two_strike_account_with_one_decayed_strike()
    validate_success(api.process_notice(scene["second_notice"]["id"], AGENT),
                     expected_status=200)

    account = get_account(scene["account"]["id"])
    # 10.00 (fresh, weight 1.0) + 9.75 (10 * 1.5 * 0.65, decay step 1).
    assert_two_decimal_places(account["strike_points"], "strike_points")
    assert float(account["strike_points"]) == 19.75
    # Summing the points snapshotted at accrual (15.00 + 10.00) is the
    # rejected reading, and only it would cross the limitation threshold.
    assert float(account["strike_points"]) != 25.00
    assert account["standing"] == "ACTIVE"
    assert account["upload_restricted"] is False


def test_clock_advance_decays_the_verified_weight_strike_to_effective_points(api):
    """PRD §3.8: "`ACTIVE → DECAYED` fires when the gap between the logical clock and the strike's `accrued_at` is at least `decay_step_days` and still less than `strike_expiry_days`; the transition recomputes that strike's `effective_points` with the applicable decay factor and recomputes the account's `strike_points`."

    Design: Difficulty/dual_variant_calc/strike_points_chronological_vs_snapshot_diverge_on_decayed_strike
    """
    scene = _two_strike_account_with_one_decayed_strike()
    validate_success(api.process_notice(scene["second_notice"]["id"], AGENT),
                     expected_status=200)

    strikes, meta = list_account_strikes(scene["account"]["id"])
    assert meta["total_count"] == 2

    decayed, fresh = strikes[0], strikes[1]
    assert decayed["status"] == "DECAYED"
    assert float(decayed["weight"]) == 1.5
    assert float(decayed["base_points"]) == 15.00
    assert_two_decimal_places(decayed["effective_points"], "effective_points")
    assert float(decayed["effective_points"]) == 9.75
    assert float(decayed["effective_points"]) != 15.00

    assert fresh["status"] == "ACTIVE"
    assert float(fresh["weight"]) == 1.0
    assert float(fresh["effective_points"]) == 10.00


def test_strike_summary_reports_the_pinned_decayed_total_and_breakdown(api):
    """PRD §3.2: "There is in addition a computed strike-accounting read on an account that returns, under the pinned point variant, the `account_id`, the current `strike_points`, the `active_strike_count`, `decayed_strike_count`, `expired_strike_count` and `voided_strike_count` breakdown of its strike records, the `limitation_threshold_points` and `termination_threshold_points` currently in force from the published policy, and the account's `standing`."

    Design: Difficulty/dual_variant_calc/strike_points_chronological_vs_snapshot_diverge_on_decayed_strike
    """
    scene = _two_strike_account_with_one_decayed_strike()
    validate_success(api.process_notice(scene["second_notice"]["id"], AGENT),
                     expected_status=200)

    summary = strike_summary(scene["account"]["id"])
    assert summary["account_id"] == scene["account"]["id"]
    assert float(summary["strike_points"]) == 19.75
    assert float(summary["strike_points"]) != 25.00
    assert summary["active_strike_count"] == 1
    assert summary["decayed_strike_count"] == 1
    assert summary["expired_strike_count"] == 0
    assert summary["voided_strike_count"] == 0
    assert float(summary["limitation_threshold_points"]) == 20
    assert float(summary["termination_threshold_points"]) == 40
    assert summary["standing"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Misrepresentation penalty: the surcharge tier is keyed on the base
# ---------------------------------------------------------------------------

def _substantiable_case(url_count: int, clock_at_case: str):
    """One notice disabling `url_count` items at the clock start, with an OPEN
    misrepresentation case opened at `clock_at_case` against its first claim."""
    scene = _scene(item_count=url_count)
    holder = create_rights_holder()
    notice = create_processed_notice(
        holder["id"], [item["content_url"] for item in scene["items"]]
    )
    claims = claims_of_notice(notice["id"])
    assert len(claims) == url_count
    set_clock(clock_at_case)
    case = create_misrepresentation_case(holder["id"], claims[0]["id"],
                                         investigator_user_id="investigator-01")
    return {"scene": scene, "holder": holder, "notice": notice,
            "claims": claims, "case": case}


def test_misrepresentation_surcharge_tier_is_selected_from_the_base_penalty(api):
    """PRD §3.9: "The surcharge tier is then selected **from the base amount** and never re-selected afterwards: the rate is 0.20 when `base_penalty_cents` is at least 500000, otherwise 0.10 when it is at least 100000, and otherwise zero."

    Design: Difficulty/combinatorial_formula/misrepresentation_penalty_surcharge_tier_keyed_on_base_not_total
    """
    world = _substantiable_case(url_count=3, clock_at_case="2026-10-25T00:00:00Z")

    case = validate_success(
        api.substantiate_misrepresentation_case(
            world["case"]["id"], make_abuse_investigator_headers("investigator-02")
        ),
        expected_status=200,
    )

    assert case["status"] == "SUBSTANTIATED"
    assert case["affected_claim_count"] == 3
    # 85 whole days of disabled access on each of the three claims.
    assert case["disabled_day_count"] == 255
    assert_money_int(case["base_penalty_cents"], "base_penalty_cents")
    # 3 * 25000 + 255 * 1500.
    assert case["base_penalty_cents"] == 457500
    # The base sits in the 10% tier, and the tier is never re-selected.
    assert case["surcharge_cents"] == 45750
    assert case["total_penalty_cents"] == 503250
    assert case["total_penalty_cents"] != 549000
    assert case["substantiated_by_user_id"] == "investigator-02"
    assert case["substantiated_at"] is not None


def test_substantiation_recomputes_abuse_score_without_suspending_the_holder(api):
    """PRD §3.9: "Divide the sum by the greater of `notices_processed` and a volume floor of 5 — the floor is what stops a holder with two notices and one withdrawal from registering an implausibly extreme figure — multiply by 100, and round half up to two decimal places."

    Design: Difficulty/combinatorial_formula/misrepresentation_penalty_surcharge_tier_keyed_on_base_not_total
    """
    world = _substantiable_case(url_count=3, clock_at_case="2026-10-25T00:00:00Z")
    validate_success(
        api.substantiate_misrepresentation_case(
            world["case"]["id"], make_abuse_investigator_headers("investigator-02")
        ),
        expected_status=200,
    )

    holder = get_rights_holder(world["holder"]["id"])
    assert holder["misrepresentation_count"] == 1
    assert holder["notices_processed"] == 1
    # (0*1 + 0*2 + 1*3) / max(1, 5) * 100 — the volume floor, not the one
    # processed notice, is the divisor.
    assert_two_decimal_places(holder["abuse_score"], "abuse_score")
    assert float(holder["abuse_score"]) == 60.00
    assert float(holder["abuse_score"]) != 300.00
    # 60.00 stays below the suspension floor of 70, so nothing steps down.
    assert holder["program_tier"] == "STANDARD"
    assert holder["enrollment_status"] == "PROSPECT"

    account = get_account(world["scene"]["account"]["id"])
    assert float(account["strike_points"]) == 30.00
    assert account["standing"] == "LIMITED"


def test_base_penalty_exactly_at_the_upper_tier_floor_takes_the_higher_rate(api):
    """PRD §3.9: "`base_penalty_cents` is 25000 cents for each affected claim plus 1500 cents for each disabled day."

    Design: Difficulty/combinatorial_formula/misrepresentation_penalty_surcharge_tier_keyed_on_base_not_total
    """
    world = _substantiable_case(url_count=2, clock_at_case="2026-12-29T00:00:00Z")

    case = validate_success(
        api.substantiate_misrepresentation_case(
            world["case"]["id"], make_abuse_investigator_headers("investigator-02")
        ),
        expected_status=200,
    )

    assert case["affected_claim_count"] == 2
    # 150 whole days of disabled access on each of the two claims.
    assert case["disabled_day_count"] == 300
    # 2 * 25000 + 300 * 1500 lands exactly on the upper tier floor, and the
    # comparison at that floor is inclusive.
    assert case["base_penalty_cents"] == 500000
    assert case["surcharge_cents"] == 100000
    assert case["surcharge_cents"] != 50000
    assert case["total_penalty_cents"] == 600000


# ---------------------------------------------------------------------------
# Safe-harbour audit: four components, one whole-number score
# ---------------------------------------------------------------------------

def _provider_with_two_latencies_and_one_overdue_restoration():
    """Two PROCESSED notices with latencies of 12 and 36 hours, plus one
    counter-notice forwarded on Monday 2026-08-03 and left unrestored."""
    scene = _scene(item_count=2)
    holder = create_rights_holder()

    first = create_notice(holder["id"], [scene["items"][0]["content_url"]])
    set_clock("2026-08-01T12:00:00Z")
    validate_notice(first["id"])
    process_notice(first["id"])

    second = create_notice(holder["id"], [scene["items"][1]["content_url"]])
    set_clock("2026-08-03T00:00:00Z")
    validate_notice(second["id"])
    process_notice(second["id"])

    first_claim = claims_of_notice(first["id"])[0]
    counter = create_forwarded_counter_notice(first_claim["id"],
                                              scene["account"]["id"])
    set_clock("2026-08-24T00:00:00Z")
    return {"provider": scene["provider"], "account": scene["account"],
            "counter": counter}


def test_audit_sums_four_components_and_demotes_the_provider_to_at_risk(api):
    """PRD §3.9: "`compliance_score` is the sum of the four components, rounded half up to a whole number, and therefore lands between 0 and 100."

    Design: Difficulty/combinatorial_formula/safe_harbor_posture_clamped_response_component_and_overdue_floor
    """
    world = _provider_with_two_latencies_and_one_overdue_restoration()
    provider_before = get_provider(world["provider"]["id"])
    assert provider_before["safe_harbor_status"] == "ELIGIBLE"

    counter = get_counter_notice(world["counter"]["id"])
    assert_instant_equals(counter["restoration_earliest_at"],
                          "2026-08-17T00:00:00Z", "restoration_earliest_at")
    assert_instant_equals(counter["restoration_deadline_at"],
                          "2026-08-21T00:00:00Z", "restoration_deadline_at")
    assert counter["status"] == "RESTORATION_SCHEDULED"

    audit = validate_success(api.create_safe_harbor_audit(world["provider"]["id"],
                                                          OFFICER),
                             expected_status=201)

    assert audit["gate_failure_reason"] is None
    assert float(audit["median_response_hours"]) == 24.00
    assert audit["overdue_restoration_count"] == 1
    assert float(audit["response_component"]) == 20.00
    assert float(audit["restoration_component"]) == 24
    assert float(audit["termination_component"]) == 20
    assert float(audit["contact_component"]) == 10
    assert audit["compliance_score"] == 74
    assert audit["resulting_status"] == "AT_RISK"

    provider_after = get_provider(world["provider"]["id"])
    assert provider_after["safe_harbor_status"] == "AT_RISK"
    assert provider_after["safe_harbor_score"] == 74


def test_even_latency_set_median_feeds_the_clamped_response_component(api):
    """PRD §3.9: "When the count is even, the median is the mean of the two middle values, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/safe_harbor_posture_clamped_response_component_and_overdue_floor
    """
    world = _provider_with_two_latencies_and_one_overdue_restoration()

    audit = validate_success(api.create_safe_harbor_audit(world["provider"]["id"],
                                                          OFFICER),
                             expected_status=201)

    # Latencies of 12.00 and 36.00 hours: the mean of the two middle values.
    assert_two_decimal_places(audit["median_response_hours"],
                              "median_response_hours")
    assert float(audit["median_response_hours"]) == 24.00
    assert float(audit["median_response_hours"]) != 12.00
    assert float(audit["median_response_hours"]) != 36.00
    # 40 * (48 - 24) / 48.
    assert float(audit["response_component"]) == 20.00
    assert audit["termination_compliance"] is True
    assert audit["contact_published"] is True


def test_median_beyond_the_forty_eight_hour_target_clamps_the_component_to_zero(api):
    """PRD §3.9: "`response_component` is then computed from a 48-hour target: subtract `median_response_hours` from 48, divide by 48, clamp the ratio so that it is never below 0 and never above 1, multiply the clamped ratio by a weight of 40, and round half up to two decimal places."

    Design: Difficulty/combinatorial_formula/safe_harbor_posture_clamped_response_component_and_overdue_floor
    """
    scene = _scene(item_count=1)
    holder = create_rights_holder()
    notice = create_notice(holder["id"], [scene["items"][0]["content_url"]])
    set_clock("2026-08-03T12:00:00Z")
    validate_success(api.validate_notice(notice["id"], AGENT), expected_status=200)
    validate_success(api.process_notice(notice["id"], AGENT), expected_status=200)

    audit = validate_success(api.create_safe_harbor_audit(scene["provider"]["id"],
                                                          OFFICER),
                             expected_status=201)

    # A single latency of 60.00 hours: the ratio is negative and clamps to 0.
    assert float(audit["median_response_hours"]) == 60.00
    assert float(audit["response_component"]) == 0
    assert audit["overdue_restoration_count"] == 0
    assert float(audit["restoration_component"]) == 30
    assert float(audit["termination_component"]) == 20
    assert float(audit["contact_component"]) == 10
    # 0 + 30 + 20 + 10, not the unclamped -10 + 30 + 20 + 10.
    assert audit["compliance_score"] == 60
    assert audit["compliance_score"] != 50
    assert audit["resulting_status"] == "AT_RISK"


# ---------------------------------------------------------------------------
# Hosted material: two independent state dimensions
# ---------------------------------------------------------------------------

def _forwarded_dispute_on_one_item():
    """One item DISABLED by a processed notice at the clock start, with its
    counter-notice validated and forwarded at the same instant."""
    scene = _scene(item_count=1)
    holder = create_rights_holder()
    notice = create_processed_notice(holder["id"],
                                     [scene["items"][0]["content_url"]])
    claim = claims_of_notice(notice["id"])[0]
    counter = create_forwarded_counter_notice(claim["id"],
                                              scene["account"]["id"])
    return {"scene": scene, "notice": notice, "claim": claim, "counter": counter}


def test_forwarding_advances_the_dispute_dimension_while_access_stays_disabled(api):
    """PRD §3.7: "Forwarding also moves the claim `COUNTER_NOTICED → RESTORATION_SCHEDULED`, copying `restoration_earliest_at` onto the claim's `restoration_due_at`, and moves the content item's dispute dimension `COUNTER_NOTICED → RESTORATION_PENDING`."

    Design: Difficulty/non_linear_state_machine/content_item_availability_and_dispute_dimensions_advance_independently
    """
    world = _forwarded_dispute_on_one_item()

    item = get_content_item(world["scene"]["items"][0]["id"])
    # Two dispute-dimension steps have run; the access dimension has not moved.
    assert item["availability_status"] == "DISABLED"
    assert item["dispute_status"] == "RESTORATION_PENDING"
    assert item["restored_at"] is None
    assert_instant_equals(item["disabled_at"], "2026-08-01T00:00:00Z", "disabled_at")

    claim = get_claim(world["claim"]["id"])
    assert claim["status"] == "RESTORATION_SCHEDULED"
    counter = get_counter_notice(world["counter"]["id"])
    assert counter["status"] == "FORWARDED"
    assert_instant_equals(claim["restoration_due_at"],
                          counter["restoration_earliest_at"], "restoration_due_at")

    account = get_account(world["scene"]["account"]["id"])
    assert account["available_content_count"] == 0


def test_restoration_bounds_count_business_days_from_the_forward_anchor(api):
    """PRD §3.7: "`restoration_earliest_at` is `forwarded_at` advanced by 10 business days and `restoration_deadline_at` is `forwarded_at` advanced by 14 business days."

    Design: Difficulty/non_linear_state_machine/content_item_availability_and_dispute_dimensions_advance_independently
    """
    world = _forwarded_dispute_on_one_item()

    counter = get_counter_notice(world["counter"]["id"])
    assert_instant_equals(counter["forwarded_at"], "2026-08-01T00:00:00Z",
                          "forwarded_at")
    # Saturday 2026-08-01 anchors the count; weekends do not qualify.
    assert_instant_equals(counter["restoration_earliest_at"],
                          "2026-08-14T00:00:00Z", "restoration_earliest_at")
    assert_instant_equals(counter["restoration_deadline_at"],
                          "2026-08-20T00:00:00Z", "restoration_deadline_at")
    # Ten and fourteen calendar days would be 2026-08-11 and 2026-08-15.
    assert parse_instant(counter["restoration_earliest_at"]) != parse_instant(
        "2026-08-11T00:00:00Z"
    )
    assert parse_instant(counter["restoration_deadline_at"]) != parse_instant(
        "2026-08-15T00:00:00Z"
    )

    claim = get_claim(world["claim"]["id"])
    assert_instant_equals(claim["restoration_due_at"], "2026-08-14T00:00:00Z",
                          "restoration_due_at")


def test_purging_a_disabled_item_leaves_its_resolved_dispute_status_intact(api):
    """PRD §3.2: "Purging touches only the access dimension; the item's `dispute_status` is left exactly as it was, which is how a purged item can carry `RESOLVED`."

    Design: Difficulty/non_linear_state_machine/content_item_availability_and_dispute_dimensions_advance_independently
    """
    scene = _scene(item_count=1)
    holder = create_rights_holder()
    notice = create_processed_notice(holder["id"],
                                     [scene["items"][0]["content_url"]])
    claim = claims_of_notice(notice["id"])[0]

    # The counter-notice window of 30 calendar days runs out unanswered.
    set_clock("2026-08-31T00:00:00Z")
    upheld = validate_success(api.uphold_claim(claim["id"], AGENT),
                              expected_status=200)
    assert upheld["status"] == "UPHELD"

    resolved = get_content_item(scene["items"][0]["id"])
    assert resolved["availability_status"] == "DISABLED"
    assert resolved["dispute_status"] == "RESOLVED"

    purged = validate_success(
        api.purge_content_item(scene["items"][0]["id"], OFFICER),
        expected_status=200,
    )
    assert purged["availability_status"] == "PURGED"
    assert purged["dispute_status"] == "RESOLVED"
    assert purged["dispute_status"] != "NONE"

    account = get_account(scene["account"]["id"])
    # The disabled item was already excluded from the live count.
    assert account["available_content_count"] == 0


# ---------------------------------------------------------------------------
# Account standing: a cycle, not a path
# ---------------------------------------------------------------------------

def _account_at_the_termination_threshold():
    """Four claims put one account at 40.00 points, which limits its standing
    and opens exactly one termination case against it."""
    scene = _scene(item_count=4)
    holder = create_rights_holder()
    create_processed_notice(holder["id"],
                            [item["content_url"] for item in scene["items"]])
    cases = termination_cases_of_account(scene["account"]["id"])
    assert len(cases) == 1
    return {"scene": scene, "case": cases[0]}


def test_account_cycles_back_to_active_when_the_appeal_is_vacated(api):
    """PRD §3.8: "A `VACATED` decision moves the case `APPEAL_FILED → VACATED` and unwinds the termination completely: every strike record of the account that is `ACTIVE` or `DECAYED` is voided, which recomputes `strike_points` to 0, so the account returns `TERMINATED → ACTIVE` with `terminated_at` cleared and `upload_restricted` false — and because the total is 0 rather than merely reduced, standing settles at `ACTIVE` instead of re-entering `LIMITED`."

    Design: Difficulty/non_linear_state_machine/account_standing_cycles_active_limited_terminated_active
    """
    world = _account_at_the_termination_threshold()
    account_id = world["scene"]["account"]["id"]
    case_id = world["case"]["id"]

    validate_success(
        api.execute_termination_case(case_id,
                                     make_compliance_officer_headers("officer-01")),
        expected_status=200,
    )
    validate_success(
        api.file_termination_appeal(case_id, make_subscriber_headers(account_id)),
        expected_status=200,
    )
    case = validate_success(
        api.decide_termination_appeal(
            case_id, "VACATED", make_compliance_officer_headers("officer-02")
        ),
        expected_status=200,
    )

    assert case["status"] == "VACATED"
    assert case["decision"] == "VACATED"
    assert float(case["trigger_points"]) == 40.00
    assert case["executed_by_user_id"] == "officer-01"
    assert case["decided_by_user_id"] == "officer-02"

    account = get_account(account_id)
    # The second visit to ACTIVE carries a cleared point total, not 40.00.
    assert account["standing"] == "ACTIVE"
    assert float(account["strike_points"]) == 0.00
    assert float(account["strike_points"]) != 40.00
    assert account["upload_restricted"] is False
    assert account["terminated_at"] is None

    voided, meta = list_account_strikes(account_id, params={"status": "VOIDED"})
    assert meta["total_count"] == 4
    assert len(voided) == 4

    # Vacating the termination does not undo the takedowns themselves.
    item = get_content_item(world["scene"]["items"][0]["id"])
    assert item["availability_status"] == "DISABLED"
    assert account["available_content_count"] == 0


def test_execution_terminates_the_limited_account_and_opens_the_appeal_window(api):
    """PRD §3.8: "Execution records the acting `X-User-ID` as the case's `executed_by_user_id`, stamps `executed_at` from the logical clock, and sets `appeal_deadline_at` to `executed_at` advanced by the policy's `appeal_window_days`."

    Design: Difficulty/non_linear_state_machine/account_standing_cycles_active_limited_terminated_active
    """
    world = _account_at_the_termination_threshold()
    account_id = world["scene"]["account"]["id"]

    before = get_account(account_id)
    assert before["standing"] == "LIMITED"
    assert float(before["strike_points"]) == 40.00

    case = validate_success(
        api.execute_termination_case(world["case"]["id"],
                                     make_compliance_officer_headers("officer-01")),
        expected_status=200,
    )
    assert case["status"] == "EXECUTED"
    assert case["executed_by_user_id"] == "officer-01"
    assert case["opened_by_user_id"] is None
    assert_instant_equals(case["executed_at"], "2026-08-01T00:00:00Z", "executed_at")
    assert_instant_equals(case["appeal_deadline_at"], "2026-08-15T00:00:00Z",
                          "appeal_deadline_at")

    account = get_account(account_id)
    assert account["standing"] == "TERMINATED"
    assert account["upload_restricted"] is True
    assert account["terminated_at"] is not None
    # The point total is untouched by execution: it is still the trigger total.
    assert float(account["strike_points"]) == 40.00
    assert account["available_content_count"] == 0


def test_upheld_appeal_leaves_the_account_terminated_with_its_points_intact(api):
    """PRD §3.8: "An `UPHELD` decision moves the case `APPEAL_FILED → CLOSED`, leaves the account `TERMINATED`, and touches no strike record."

    Design: Difficulty/non_linear_state_machine/account_standing_cycles_active_limited_terminated_active
    """
    world = _account_at_the_termination_threshold()
    account_id = world["scene"]["account"]["id"]
    case_id = world["case"]["id"]

    validate_success(
        api.execute_termination_case(case_id,
                                     make_compliance_officer_headers("officer-01")),
        expected_status=200,
    )
    validate_success(
        api.file_termination_appeal(case_id, make_subscriber_headers(account_id)),
        expected_status=200,
    )
    case = validate_success(
        api.decide_termination_appeal(
            case_id, "UPHELD", make_compliance_officer_headers("officer-02")
        ),
        expected_status=200,
    )

    assert case["status"] == "CLOSED"
    assert case["status"] != "VACATED"
    assert case["decision"] == "UPHELD"
    assert case["decided_by_user_id"] == "officer-02"

    account = get_account(account_id)
    # The cycle does not close on this branch: no return to ACTIVE.
    assert account["standing"] == "TERMINATED"
    assert account["standing"] != "ACTIVE"
    assert float(account["strike_points"]) == 40.00
    assert float(account["strike_points"]) != 0.00
    assert account["terminated_at"] is not None
    assert account["upload_restricted"] is True

    voided, voided_meta = list_account_strikes(account_id,
                                               params={"status": "VOIDED"})
    assert voided_meta["total_count"] == 0
    active, active_meta = list_account_strikes(account_id,
                                               params={"status": "ACTIVE"})
    assert active_meta["total_count"] == 4
