"""Which refusal wins when two gates fail at once, and where each gate flips.

This file covers two neighbouring parts of the contract. First, the single global
order of the validation tiers: a package submission that violates both a state
gate and the fiscal gate, and a change request that violates both interval sanity
and the quiet-buffer rule, must each report the earlier tier and never the later
one, leaving no partial state behind. Second, the exact points at which a
computation changes value: the overdue multiplier at the deadline instant rather
than one second earlier, the confirmed-category set at cardinality zero versus
one, and a slot's hours at exactly the unallocated pool versus one hundredth of
an hour above it.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSESSMENT_BUDGET_EXCEEDED,
    ERR_CHANGE_WINDOW_BUFFER_VIOLATION,
    ERR_CRM_COVERAGE_INSUFFICIENT,
    ERR_ENGAGEMENT_HOURS_EXHAUSTED,
    ERR_ENGAGEMENT_REPORT_NOT_DELIVERED,
    ERR_NO_CONFIRMED_DATA_CATEGORY,
    ERR_OVERDUE_HIGH_FINDINGS,
    ERR_RESIDUAL_RISK_TOO_HIGH,
    ERR_WINDOW_INVALID,
    VALIDATION_TIER,
)
from test_helpers.test_users import BOARD_1, make_board_headers

# ---------------------------------------------------------------------------
# Shared preludes
# ---------------------------------------------------------------------------

#: A budget deliberately smaller than the engagement rollup below it.
TIGHT_BUDGET_USD = 100000.00

#: 120000.00 labour draws a 0.06 surcharge (7200.00) and 200 contracted hours
#: sit inside the 900-hour MODERATE allowance, so the rollup is 127200.00.
ENGAGEMENT_LABOR_USD = 120000.00
ENGAGEMENT_HOURS = 200.00
ENGAGEMENT_TOTAL_USD = 127200.00


def _offering_over_budget(client, *, families=None):
    """An offering IN_ASSESSMENT whose engagement rollup overruns its budget."""
    env = fx.seed_reference_data(client, families=families)
    env = fx.seed_path_selected_offering(
        client, env, assessment_budget_usd=TIGHT_BUDGET_USD
    )
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(
        client,
        env,
        contracted_hours=ENGAGEMENT_HOURS,
        labor_cost_usd=ENGAGEMENT_LABOR_USD,
    )
    return env


def _package_with_engagement_still_testing(client):
    """A DRAFT package whose engagement is in TESTING and over budget."""
    env = _offering_over_budget(client)
    env = fx.seed_test_slot(client, env)
    return fx.seed_package(client, env)


def _package_with_thin_coverage(client):
    """A DRAFT package on a REPORT_DELIVERED engagement with 33.34 coverage."""
    env = _offering_over_budget(client, families=f.SPLIT_ROUNDING_FAMILIES)
    env = fx.seed_report_delivered(client, env, report_at=fx.AUTHORIZATION_CLOCK)
    return fx.seed_package(client, env)


def _authorized_offering_with_approved_may_window(client):
    """An AUTHORIZED offering carrying an APPROVED 2026-05-01..2026-05-10 window."""
    env = fx.seed_authorized_offering(client)
    return fx.seed_change_request(
        client,
        env,
        change_kind="TECH_REFRESH",
        description="Refresh the hypervisor fleet.",
        window_start="2026-05-01T00:00:00Z",
        window_end="2026-05-10T00:00:00Z",
        decision="APPROVE",
        key="approved_change",
    )


def _file_inverted_window(client, env):
    """File a change request whose window_start falls after its window_end."""
    return client.create_change_request(
        f.build_change_request_payload(
            env["offering_id"],
            "2026-05-12T00:00:00Z",
            "2026-05-11T00:00:00Z",
            change_kind="BOUNDARY_CHANGE",
            description="Extend the boundary to a second region.",
        ),
        env["lead_headers"],
    )


#: A MODERATE finding detected at the authorization instant is due 90 days later.
FINDING_DETECTED_AT = fx.AUTHORIZATION_CLOCK
FINDING_DEADLINE_AT = A.expected_deadline(FINDING_DETECTED_AT, "MODERATE")


def _authorization_with_moderate_finding(client):
    """A live authorization carrying one open MODERATE self-identified finding."""
    env = fx.seed_authorized_offering(client)
    return fx.seed_poam_item(
        client,
        env,
        severity="MODERATE",
        detected_at=FINDING_DETECTED_AT,
        control_id="AC-2",
        source="SELF_IDENTIFIED",
        key="finding",
    )


def _draft_offering_with_one_declared_category(client):
    """A DRAFT offering whose only data category is still DECLARED."""
    env = fx.seed_reference_data(client)
    env = fx.seed_draft_offering(client, env)
    return fx.declare_categories(
        client,
        env,
        [
            {
                "category_code": "PII",
                "confidentiality_impact": "MODERATE",
                "integrity_impact": "MODERATE",
                "availability_impact": "LOW",
            }
        ],
    )


def _engagement_with_eight_unallocated_hours(client):
    """A TESTING engagement of 100.00 hours with 92.00 already allocated."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_engagement(
        client, env, contracted_hours=100.00, labor_cost_usd=ENGAGEMENT_LABOR_USD
    )
    return fx.seed_test_slot(
        client,
        env,
        start_at="2026-03-02T00:00:00Z",
        end_at="2026-03-05T20:00:00Z",
        hours=92.00,
        family_code="AC",
        key="bulk",
    )


def _create_free_interval_slot(client, env, hours):
    """Request a slot on an interval no other slot of the engagement occupies."""
    return client.create_test_slot(
        f.build_test_slot_payload(
            env["engagement_id"],
            start_at="2026-03-06T00:00:00Z",
            end_at="2026-03-06T09:00:00Z",
            hours=hours,
            family_code="SC",
        ),
        env["assessor_headers"],
    )


# ---------------------------------------------------------------------------
# The engagement-report gate outranks the assessment-budget gate
# ---------------------------------------------------------------------------


def test_undelivered_report_outranks_exceeded_assessment_budget_on_submit(client):
    """A submission failing both the report gate and the budget gate reports the report gate.

    PRD: "It is performed by the offering's owning compliance lead on a package in `DRAFT` or `REVISION_REQUESTED`, and it enforces, in the order given by §2.7: the backing engagement must be in `REPORT_DELIVERED`, else `ERR_ENGAGEMENT_REPORT_NOT_DELIVERED`; customer-responsibility-matrix coverage computed as in §3.4 must be at least 90.00 percent, else `ERR_CRM_COVERAGE_INSUFFICIENT`; the submission-variant residual risk score must be strictly below 50.00, else `ERR_RESIDUAL_RISK_TOO_HIGH`; no finding of the offering may be `HIGH` severity, not `CLOSED`, and already at or past its deadline as of the submission instant, else `ERR_OVERDUE_HIGH_FINDINGS`; and the engagement's `total_cost_usd` must not exceed the offering's `assessment_budget_usd`, else `ERR_ASSESSMENT_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_outranks_fiscal_gate_on_package_submit
    """
    env = _package_with_engagement_still_testing(client)

    response = client.submit_package(env["package_id"], env["lead_headers"])

    assert (
        VALIDATION_TIER[ERR_ENGAGEMENT_REPORT_NOT_DELIVERED]
        < VALIDATION_TIER[ERR_ASSESSMENT_BUDGET_EXCEEDED]
    )
    error = validate_error(response, ERR_ENGAGEMENT_REPORT_NOT_DELIVERED, 409)
    assert error["error_id"] != ERR_ASSESSMENT_BUDGET_EXCEEDED


def test_report_gate_refusal_leaves_the_package_in_draft_with_nothing_frozen(client):
    """A refused submission leaves the package's frozen figures null and its round at zero.

    PRD: "On success the package opens in status `DRAFT` with `submission_round` 0, `submitted_at`, `crm_coverage_pct`, `residual_risk_score_at_submission`, `open_findings_at_submission`, `reviewed_by_user_id`, `revision_note` and `letter_reference` all null, and with `authorization_path` copied from the offering — that copy is what later decides who may issue the decision."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_outranks_fiscal_gate_on_package_submit
    """
    env = _package_with_engagement_still_testing(client)

    validate_error(
        client.submit_package(env["package_id"], env["lead_headers"]),
        ERR_ENGAGEMENT_REPORT_NOT_DELIVERED,
        409,
    )

    package = fx.read_package(client, env["package_id"])
    assert package["status"] == "DRAFT"
    A.assert_integer(package["submission_round"], 0, "submission_round")
    assert package["submitted_at"] is None
    assert package["crm_coverage_pct"] is None
    assert package["residual_risk_score_at_submission"] is None
    assert package["open_findings_at_submission"] is None

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "IN_ASSESSMENT"


def test_budget_overrun_is_real_yet_its_error_never_fires_behind_the_report_gate(client):
    """The budget really is overrun, and the earlier tier still owns the response.

    PRD: "Checks are therefore evaluated in one fixed global order, and the first failing check determines the response."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_outranks_fiscal_gate_on_package_submit
    """
    env = _package_with_engagement_still_testing(client)

    engagement = fx.read_engagement(client, env["engagement_id"])
    A.assert_engagement_costs(
        engagement, ENGAGEMENT_LABOR_USD, ENGAGEMENT_HOURS, "MODERATE"
    )
    A.assert_money(engagement["total_cost_usd"], ENGAGEMENT_TOTAL_USD, "total_cost_usd")
    offering = fx.read_offering(client, env["offering_id"])
    A.assert_money(
        offering["assessment_budget_usd"], TIGHT_BUDGET_USD, "assessment_budget_usd"
    )
    assert float(engagement["total_cost_usd"]) > float(
        offering["assessment_budget_usd"]
    ), "the fiscal gate must genuinely be violated for the pair to discriminate"
    assert engagement["status"] == "TESTING"

    error = validate_error(
        client.submit_package(env["package_id"], env["lead_headers"]),
        ERR_ENGAGEMENT_REPORT_NOT_DELIVERED,
        409,
    )
    assert error["error_id"] != ERR_ASSESSMENT_BUDGET_EXCEEDED


# ---------------------------------------------------------------------------
# Interval sanity outranks the change-window buffer
# ---------------------------------------------------------------------------


def test_inverted_change_window_outranks_the_quiet_buffer_violation(client):
    """A window that both inverts itself and crowds an approved window reports the inversion.

    PRD: "Interval sanity: a start strictly precedes its end, for test slots, change windows and assessment plans — `ERR_WINDOW_INVALID` (422)."

    Design: Difficulty/priority_pair_validation_conflict/window_sanity_outranks_change_window_buffer_on_change_request_create
    """
    env = _authorized_offering_with_approved_may_window(client)

    response = _file_inverted_window(client, env)

    assert (
        VALIDATION_TIER[ERR_WINDOW_INVALID]
        < VALIDATION_TIER[ERR_CHANGE_WINDOW_BUFFER_VIOLATION]
    )
    error = validate_error(response, ERR_WINDOW_INVALID, 422)
    assert error["error_id"] != ERR_CHANGE_WINDOW_BUFFER_VIOLATION


def test_refused_change_window_files_no_request_and_leaves_the_offering_authorized(client):
    """The refused filing writes no request row and does not move the offering under review.

    PRD: "Filing requires the offering to be in status `AUTHORIZED`, moves it `AUTHORIZED → CHANGE_UNDER_REVIEW`, increments its `version` by one, and opens the request in status `SUBMITTED` with `decided_by_user_id` null."

    Design: Difficulty/priority_pair_validation_conflict/window_sanity_outranks_change_window_buffer_on_change_request_create
    """
    env = _authorized_offering_with_approved_may_window(client)

    validate_error(_file_inverted_window(client, env), ERR_WINDOW_INVALID, 422)

    rows, meta = validate_paginated(
        client.list_change_requests(
            env["lead_headers"], {"offering_id": env["offering_id"]}
        )
    )
    assert A.ids_of(rows) == [env["approved_change_id"]]
    A.assert_integer(meta["total_count"], 1, "meta.total_count")

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "AUTHORIZED"


def test_approved_tech_refresh_window_survives_the_refusal_without_bumping_the_boundary(
    client,
):
    """The approved TECH_REFRESH window stays approved and leaves boundary_version at one.

    PRD: "An `APPROVE` of a `BOUNDARY_CHANGE` or a `NEW_SERVICE` increments the offering's `boundary_version` by one, and an `APPROVE` of a `NEW_SERVICE` additionally increases the offering's `included_service_count` by the request's `added_service_count`; an `APPROVE` of a `TECH_REFRESH` leaves both untouched."

    Design: Difficulty/priority_pair_validation_conflict/window_sanity_outranks_change_window_buffer_on_change_request_create
    """
    env = _authorized_offering_with_approved_may_window(client)

    validate_error(_file_inverted_window(client, env), ERR_WINDOW_INVALID, 422)

    approved = get_success_data(
        client.get_change_request(env["approved_change_id"], env["lead_headers"]), 200
    )
    assert approved["status"] == "APPROVED"
    A.assert_instant(approved["window_end"], "2026-05-10T00:00:00Z", "window_end")

    offering = fx.read_offering(client, env["offering_id"])
    A.assert_integer(offering["boundary_version"], 1, "boundary_version")


# ---------------------------------------------------------------------------
# The coverage safety gate outranks the assessment-budget gate
# ---------------------------------------------------------------------------


def test_insufficient_crm_coverage_outranks_exceeded_assessment_budget_on_submit(client):
    """A submission failing both coverage and budget reports the coverage gate.

    PRD: "It is performed by the offering's owning compliance lead on a package in `DRAFT` or `REVISION_REQUESTED`, and it enforces, in the order given by §2.7: the backing engagement must be in `REPORT_DELIVERED`, else `ERR_ENGAGEMENT_REPORT_NOT_DELIVERED`; customer-responsibility-matrix coverage computed as in §3.4 must be at least 90.00 percent, else `ERR_CRM_COVERAGE_INSUFFICIENT`; the submission-variant residual risk score must be strictly below 50.00, else `ERR_RESIDUAL_RISK_TOO_HIGH`; no finding of the offering may be `HIGH` severity, not `CLOSED`, and already at or past its deadline as of the submission instant, else `ERR_OVERDUE_HIGH_FINDINGS`; and the engagement's `total_cost_usd` must not exceed the offering's `assessment_budget_usd`, else `ERR_ASSESSMENT_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/coverage_safety_gate_outranks_fiscal_gate_on_package_submit
    """
    env = _package_with_thin_coverage(client)

    engagement = fx.read_engagement(client, env["engagement_id"])
    assert engagement["status"] == "REPORT_DELIVERED"
    A.assert_money(engagement["total_cost_usd"], ENGAGEMENT_TOTAL_USD, "total_cost_usd")

    response = client.submit_package(env["package_id"], env["lead_headers"])

    assert (
        VALIDATION_TIER[ERR_CRM_COVERAGE_INSUFFICIENT]
        < VALIDATION_TIER[ERR_ASSESSMENT_BUDGET_EXCEEDED]
    )
    error = validate_error(response, ERR_CRM_COVERAGE_INSUFFICIENT, 422)
    assert error["error_id"] != ERR_ASSESSMENT_BUDGET_EXCEEDED
    assert error["error_id"] != ERR_RESIDUAL_RISK_TOO_HIGH
    assert error["error_id"] != ERR_OVERDUE_HIGH_FINDINGS


def test_two_step_rounding_leaves_coverage_at_thirty_three_point_three_four(client):
    """Coverage over AC 2/3 and SC 1/6 is 33.34, the figure the pinned rounding order gives.

    PRD: "The order of those two roundings is pinned and is not interchangeable: round each family percentage first, then round the weighted mean of the family percentages."

    Design: Difficulty/priority_pair_validation_conflict/coverage_safety_gate_outranks_fiscal_gate_on_package_submit
    """
    env = _package_with_thin_coverage(client)

    coverage = get_success_data(
        client.get_crm_coverage(env["offering_id"], env["lead_headers"]), 200
    )

    expected = A.expected_overall_coverage([(2, 3), (1, 6)])
    A.assert_money(expected, 33.34, "expected overall coverage")
    A.assert_money(coverage["overall_coverage_pct"], expected, "overall_coverage_pct")
    assert coverage["overall_coverage_pct"] != 33.33, (
        "33.33 is the collapsed single-ratio figure, not the pinned two-step figure"
    )
    A.assert_money(coverage["weight_total"], 9.00, "weight_total")


def test_coverage_gate_refusal_freezes_nothing_onto_the_package(client):
    """A submission refused on coverage freezes no coverage figure onto the package.

    PRD: "Three figures are frozen onto the package at that instant and never move again: `crm_coverage_pct` from the coverage computation, `residual_risk_score_at_submission` from the submission variant of the risk score, and `open_findings_at_submission` as the count of the offering's findings whose `remediation_status` is not `CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/coverage_safety_gate_outranks_fiscal_gate_on_package_submit
    """
    env = _package_with_thin_coverage(client)

    validate_error(
        client.submit_package(env["package_id"], env["lead_headers"]),
        ERR_CRM_COVERAGE_INSUFFICIENT,
        422,
    )

    package = fx.read_package(client, env["package_id"])
    assert package["status"] == "DRAFT"
    A.assert_integer(package["submission_round"], 0, "submission_round")
    assert package["crm_coverage_pct"] is None
    assert package["residual_risk_score_at_submission"] is None
    assert package["open_findings_at_submission"] is None

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "IN_ASSESSMENT"


# ---------------------------------------------------------------------------
# The overdue multiplier engages at the deadline instant itself
# ---------------------------------------------------------------------------


def test_moderate_finding_is_due_ninety_days_after_the_instant_it_was_detected(client):
    """A MODERATE finding detected at the authorization instant is due 2026-06-28T00:00:00Z.

    PRD: "At creation an item's `anchor_at` equals its `detected_at`, and its `deadline_at` is `anchor_at` advanced by the severity base allowance and then by `granted_extension_days` further days."

    Design: Difficulty/boundary_precision_check/overdue_multiplier_engages_at_the_exact_deadline_instant_not_one_second_earlier
    """
    env = _authorization_with_moderate_finding(client)

    finding = fx.read_poam_item(client, env["finding_id"])

    A.assert_instant(finding["anchor_at"], FINDING_DETECTED_AT, "anchor_at")
    A.assert_integer(finding["granted_extension_days"], 0, "granted_extension_days")
    A.assert_instant(finding["deadline_at"], "2026-06-28T00:00:00Z", "deadline_at")
    A.assert_instant(finding["deadline_at"], FINDING_DEADLINE_AT, "deadline_at")


def test_residual_risk_stays_at_four_one_second_before_the_deadline_instant(client):
    """One second before its deadline the MODERATE finding is not yet overdue.

    PRD: "A finding counts as overdue as of a given instant when that instant is at or after `deadline_at` — the boundary instant itself is already overdue, not still on time."

    Design: Difficulty/boundary_precision_check/overdue_multiplier_engages_at_the_exact_deadline_instant_not_one_second_earlier
    """
    env = _authorization_with_moderate_finding(client)
    one_second_early = A.shift_instant(FINDING_DEADLINE_AT, seconds=-1)

    fx.set_clock(client, one_second_early)
    summary = fx.read_risk_summary(client, env["authorization_id"])

    # 4.0 MODERATE weight x 1.0 disposition x 1.0 (not overdue).
    A.assert_money(summary["residual_risk_score"], 4.00, "residual_risk_score")
    assert summary["poam_risk_tier"] == "LOW"
    A.assert_risk_tier_matches_score(summary, "risk summary")
    A.assert_integer(summary["overdue_high_count"], 0, "overdue_high_count")
    A.assert_integer(summary["open_findings_count"], 1, "open_findings_count")
    A.assert_instant(summary["evaluated_at"], one_second_early, "evaluated_at")


def test_residual_risk_rises_to_six_at_exactly_the_deadline_instant(client):
    """At the deadline instant itself the finding's contribution takes the 1.5 multiplier.

    PRD: "Walk that population in ascending `created_at` order; for each finding multiply its severity weight by its disposition factor and then by 1.5 if the finding is overdue as of the applicable instant (or by 1.0 if it is not), rounding each finding's contribution half up to two decimal places; sum the contributions; round the sum half up to two decimal places; and take the lesser of that sum and 100.00, which is the ceiling."

    Design: Difficulty/boundary_precision_check/overdue_multiplier_engages_at_the_exact_deadline_instant_not_one_second_earlier
    """
    env = _authorization_with_moderate_finding(client)

    fx.set_clock(client, FINDING_DEADLINE_AT)
    summary = fx.read_risk_summary(client, env["authorization_id"])

    # 4.0 MODERATE weight x 1.0 disposition x 1.5 (overdue at the boundary).
    A.assert_money(summary["residual_risk_score"], 6.00, "residual_risk_score")
    assert float(summary["residual_risk_score"]) != 4.00, (
        "a strictly-greater-than comparison on the deadline would still read 4.00 here"
    )
    assert summary["poam_risk_tier"] == "LOW"
    A.assert_integer(summary["open_findings_count"], 1, "open_findings_count")


def test_stored_risk_score_lags_the_live_score_once_the_clock_crosses_the_deadline(
    client,
):
    """Two reads across the deadline move the live score while the stored score stays put.

    PRD: "The stored value on the authorization is refreshed only by the mutations named in this section and in §3.7 and §3.8, which means it can lag the live figure once the logical clock advances past a deadline without any write occurring."

    Design: Difficulty/boundary_precision_check/overdue_multiplier_engages_at_the_exact_deadline_instant_not_one_second_earlier
    """
    env = _authorization_with_moderate_finding(client)

    fx.set_clock(client, A.shift_instant(FINDING_DEADLINE_AT, seconds=-1))
    before = fx.read_risk_summary(client, env["authorization_id"])
    stored_before = before["stored_residual_risk_score"]

    fx.set_clock(client, FINDING_DEADLINE_AT)
    after = fx.read_risk_summary(client, env["authorization_id"])

    A.assert_money(
        after["stored_residual_risk_score"], stored_before, "stored_residual_risk_score"
    )
    A.assert_money(after["residual_risk_score"], 6.00, "live residual_risk_score")
    assert float(after["residual_risk_score"]) != float(
        after["stored_residual_risk_score"]
    ), "the live figure must have moved away from the lagging stored figure"

    authorization = fx.read_authorization(client, env["authorization_id"])
    A.assert_money(
        authorization["residual_risk_score"],
        after["stored_residual_risk_score"],
        "Authorization.residual_risk_score",
    )


# ---------------------------------------------------------------------------
# Impact determination at the empty confirmed-category set
# ---------------------------------------------------------------------------


def test_impact_determination_refused_when_no_category_has_been_confirmed(client):
    """With the confirmed set empty the determination is refused and binds no baseline.

    PRD: "If the offering has no confirmed category at all, the request fails with `ERR_NO_CONFIRMED_DATA_CATEGORY`."

    Design: Difficulty/boundary_precision_check/impact_determination_needs_one_confirmed_category_at_the_empty_set_boundary
    """
    env = _draft_offering_with_one_declared_category(client)

    response = client.determine_impact(
        env["offering_id"], {}, make_board_headers(BOARD_1)
    )

    validate_error(response, ERR_NO_CONFIRMED_DATA_CATEGORY, 422)
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "DRAFT"
    assert offering["final_impact_level"] is None
    assert offering["baseline_id"] is None


def test_preliminary_impact_is_moderate_while_the_confirmed_set_is_still_empty(client):
    """The declared-only category already carries the preliminary level to MODERATE.

    PRD: "This variant deliberately treats a merely declared category as if it were already confirmed, and it ignores `external_dependency_impact_level` entirely — so the preliminary figure can sit strictly above the level the offering ultimately lands on."

    Design: Difficulty/boundary_precision_check/impact_determination_needs_one_confirmed_category_at_the_empty_set_boundary
    """
    env = _draft_offering_with_one_declared_category(client)

    validate_error(
        client.determine_impact(env["offering_id"], {}, make_board_headers(BOARD_1)),
        ERR_NO_CONFIRMED_DATA_CATEGORY,
        422,
    )

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["preliminary_impact_level"] == "MODERATE"
    assert offering["final_impact_level"] is None

    categories = get_success_data(
        client.list_data_categories(env["offering_id"], env["lead_headers"]), 200
    )
    assert [row["status"] for row in categories] == ["DECLARED"]
    assert categories[0]["confirmed_by_user_id"] is None


def test_confirming_the_single_category_records_the_reviewing_board_member(client):
    """Confirmation moves the category to CONFIRMED and stamps the reviewer's identity.

    PRD: "Both legs require the category to still be `DECLARED` and the parent offering to still be in `DRAFT`, both write `confirmed_by_user_id` from the reviewer's `X-User-ID`, and both recompute the offering's `preliminary_impact_level` and increment the offering's `version` by one."

    Design: Difficulty/boundary_precision_check/impact_determination_needs_one_confirmed_category_at_the_empty_set_boundary
    """
    env = _draft_offering_with_one_declared_category(client)
    category_id = env["data_categories"]["PII"]["id"]

    confirmed = validate_success(
        client.confirm_data_category(
            category_id,
            f.build_category_decision_payload("CONFIRM"),
            make_board_headers(BOARD_1),
        ),
        200,
    )

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_by_user_id"] == BOARD_1


def test_impact_determination_succeeds_once_exactly_one_category_is_confirmed(client):
    """At cardinality one the same determination call binds the MODERATE baseline.

    PRD: "On success the offering moves `DRAFT → CATEGORIZED`, `final_impact_level` and `baseline_id` are written, and the offering's `version` increments by one."

    Design: Difficulty/boundary_precision_check/impact_determination_needs_one_confirmed_category_at_the_empty_set_boundary
    """
    env = _draft_offering_with_one_declared_category(client)
    validate_error(
        client.determine_impact(env["offering_id"], {}, make_board_headers(BOARD_1)),
        ERR_NO_CONFIRMED_DATA_CATEGORY,
        422,
    )
    get_success_data(
        client.confirm_data_category(
            env["data_categories"]["PII"]["id"],
            f.build_category_decision_payload("CONFIRM"),
            make_board_headers(BOARD_1),
        ),
        200,
    )

    offering = validate_success(
        client.determine_impact(env["offering_id"], {}, make_board_headers(BOARD_1)), 200
    )

    assert offering["status"] == "CATEGORIZED"
    assert offering["final_impact_level"] == "MODERATE"
    assert offering["baseline_id"] == env["baseline_id"]


# ---------------------------------------------------------------------------
# Slot hours at exactly the unallocated pool
# ---------------------------------------------------------------------------


def test_slot_of_one_hundredth_above_the_unallocated_pool_is_refused(client):
    """8.01 hours against an 8.00-hour pool is refused and writes no slot row.

    PRD: "Before a slot row is written the requested hours are compared against `unallocated_hours`: hours exceeding the unallocated pool are refused with `ERR_ENGAGEMENT_HOURS_EXHAUSTED`, while hours exactly equal to the pool are accepted and drive `unallocated_hours` to 0.00."

    Design: Difficulty/boundary_precision_check/test_slot_hours_boundary_at_exactly_the_unallocated_pool
    """
    env = _engagement_with_eight_unallocated_hours(client)
    A.assert_money(env["engagement"]["unallocated_hours"], 8.00, "unallocated_hours")

    response = _create_free_interval_slot(client, env, 8.01)

    validate_error(response, ERR_ENGAGEMENT_HOURS_EXHAUSTED, 422)
    assert A.ids_of(fx.list_test_slots(client, env["engagement_id"])) == [
        env["bulk_id"]
    ]
    engagement = fx.read_engagement(client, env["engagement_id"])
    A.assert_money(engagement["allocated_hours"], 92.00, "allocated_hours")
    A.assert_money(engagement["unallocated_hours"], 8.00, "unallocated_hours")


def test_slot_of_exactly_the_unallocated_pool_is_accepted_and_empties_it(client):
    """8.00 hours against an 8.00-hour pool is scheduled and drives the pool to 0.00.

    PRD: "Before a slot row is written the requested hours are compared against `unallocated_hours`: hours exceeding the unallocated pool are refused with `ERR_ENGAGEMENT_HOURS_EXHAUSTED`, while hours exactly equal to the pool are accepted and drive `unallocated_hours` to 0.00."

    Design: Difficulty/boundary_precision_check/test_slot_hours_boundary_at_exactly_the_unallocated_pool
    """
    env = _engagement_with_eight_unallocated_hours(client)

    slot = validate_success(_create_free_interval_slot(client, env, 8.00), 201)

    assert slot["status"] == "SCHEDULED"
    A.assert_money(slot["hours"], 8.00, "hours")
    engagement = fx.read_engagement(client, env["engagement_id"])
    A.assert_money(engagement["allocated_hours"], 100.00, "allocated_hours")
    A.assert_money(engagement["unallocated_hours"], 0.00, "unallocated_hours")


def test_hour_ledger_stays_conserved_across_the_boundary_pair(client):
    """The refused and the accepted request both leave contracted hours fully accounted for.

    PRD: "An engagement's `contracted_hours` always equals its `allocated_hours` plus its `unallocated_hours`."

    Design: Difficulty/boundary_precision_check/test_slot_hours_boundary_at_exactly_the_unallocated_pool
    """
    env = _engagement_with_eight_unallocated_hours(client)

    validate_error(
        _create_free_interval_slot(client, env, 8.01), ERR_ENGAGEMENT_HOURS_EXHAUSTED, 422
    )
    after_refusal = fx.read_engagement(client, env["engagement_id"])
    A.assert_hour_conservation(after_refusal)
    A.assert_money(after_refusal["contracted_hours"], 100.00, "contracted_hours")

    validate_success(_create_free_interval_slot(client, env, 8.00), 201)
    after_acceptance = fx.read_engagement(client, env["engagement_id"])
    A.assert_hour_conservation(after_acceptance)
    A.assert_money(after_acceptance["contracted_hours"], 100.00, "contracted_hours")
    assert after_acceptance["status"] == "TESTING"
