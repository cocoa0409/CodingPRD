"""Awards refused for reasons outside the request's own aggregate, and the
community impact fund conserving itself across an award, its compensation and a
re-award.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_AWARD_ALREADY_REPORTED,
    ERR_CYCLE_RESTRICTED,
    ERR_STALE_VERSION,
)
from test_helpers.assertions import (
    assert_date_equals,
    assert_decimal_equals,
    assert_is_false,
    assert_is_null,
    assert_is_true,
    assert_money,
    assert_pool_conservation,
)
from test_helpers.factories import (
    award_payload,
    certify_payload,
    outcome_report_payload,
    reinstate_payload,
    rescind_payload,
)
from test_helpers.fixtures import (
    certify_review,
    create_agency,
    create_open_cycle,
    create_panel_approved_request,
    create_submitted_request,
    current_cycle_version,
    file_review,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_agency_rep_headers,
    make_allocations_director_headers,
    make_finance_reviewer_headers,
)


PROBATION_AUDIT = {
    "audited_program_expense_ratio": "0.7400",
    "audited_admin_expense_ratio": "0.2700",
    "audited_months_operating_reserve": "3.00",
}
PERFECT_TRIPLE = {
    "priority_alignment_score": 100,
    "outcome_evidence_score": 100,
    "capacity_score": 100,
}


def _agency_certified_at_one_hundred(legal_name, ein, priority_area, fiscal_year=2025):
    """An agency whose certified review scores 100.00, so it is GOOD_STANDING."""
    agency = create_agency(
        legal_name=legal_name, ein=ein, primary_priority_area=priority_area
    )
    review = file_review(
        agency["id"],
        fiscal_year=fiscal_year,
        program_expense_ratio="0.9000",
        admin_expense_ratio="0.1000",
        months_operating_reserve="6.00",
        governance_checklist_passed_count=10,
        audit_opinion="UNQUALIFIED",
    )
    certify_review(
        agency["id"],
        review["id"],
        audited_program_expense_ratio="0.9000",
        audited_admin_expense_ratio="0.1000",
        audited_months_operating_reserve="6.00",
    )
    return validate_success(api_client.get_agency(agency["id"], make_admin_headers()))


def _open_cycle():
    """An OPEN cycle with a 300000.00 pool and three conflict-free seats."""
    return create_open_cycle(
        3,
        cycle_year=2026,
        focus_priority_area="FINANCIAL_STABILITY",
        opening_undesignated_pool="300000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-12-31",
    )


def _award_attempt(cycle_id, request_id, cycle_version=None):
    if cycle_version is None:
        cycle_version = current_cycle_version(cycle_id)
    return api_client.create_award(
        cycle_id,
        award_payload(request_id, cycle_version),
        make_allocations_director_headers(),
    )


def _read_request(request_id):
    return validate_success(
        api_client.get_allocation_request(request_id, make_admin_headers())
    )


def _read_cycle(cycle_id):
    return validate_success(
        api_client.get_allocation_cycle(cycle_id, make_admin_headers())
    )


def _third_party_restriction_scenario():
    """A cycle restricted by another agency's probation, plus a blameless request."""
    agency_x = _agency_certified_at_one_hundred(
        "Oakfield Neighborhood House", "130000001", "BASIC_NEEDS", fiscal_year=2024
    )
    agency_y = _agency_certified_at_one_hundred(
        "Trailhead Health Coalition", "130000002", "HEALTH"
    )
    cycle, panelists = _open_cycle()
    request_x = create_submitted_request(
        cycle["id"],
        agency_x["id"],
        requested_amount="30000.00",
        priority_area="BASIC_NEEDS",
        narrative_summary="Neighborhood food pantry.",
    )
    request_y = create_panel_approved_request(
        cycle["id"],
        agency_y["id"],
        panelists,
        PERFECT_TRIPLE,
        requested_amount="60000.00",
        priority_area="HEALTH",
        narrative_summary="Chronic disease self-management.",
    )
    second_review = file_review(agency_x["id"], fiscal_year=2025)
    validate_success(
        api_client.certify_agency_review(
            agency_x["id"],
            second_review["id"],
            certify_payload(**PROBATION_AUDIT),
            make_finance_reviewer_headers(),
        )
    )
    return agency_x, cycle, request_x, request_y


def test_a_cycle_restricted_by_a_third_partys_probation_refuses_a_blameless_award():
    """PRD 3.7: "The middle posture, `RESTRICTED`, is never requested by a client; it
    arrives through the probation cascade and it blocks awards only — scoring and
    review finalization remain perfectly legal while a cycle is restricted, and an
    award attempt against a restricted cycle is refused with `ERR_CYCLE_RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/award_gated_by_cycle_posture_restricted_by_another_agency
    """
    _, cycle, _, request_y = _third_party_restriction_scenario()

    restricted = _read_cycle(cycle["id"])
    assert restricted["posture"] == "RESTRICTED"
    assert_is_true(restricted["awards_blocked"], "awards_blocked")
    assert restricted["suspended_request_count"] == 1
    assert restricted["submitted_request_count"] == 2
    assert_decimal_equals(
        restricted["suspended_request_ratio"], "0.5000", "suspended_request_ratio"
    )

    blameless = _read_request(request_y["id"])
    assert blameless["status"] == "PANEL_APPROVED", "the request itself is faultless"
    assert_money(blameless["composite_score"], "100.00", "composite_score")
    assert_money(
        restricted["available_undesignated_pool"], "300000.00", "available_undesignated_pool"
    )

    validate_error(
        _award_attempt(cycle["id"], request_y["id"]), ERR_CYCLE_RESTRICTED, 409
    )


def test_the_refused_award_leaves_the_request_and_the_cycle_ledger_untouched():
    """PRD 3.8: "It then re-derives the cycle's `awarded_total` as the sum of
    `total_award` over that cycle's requests whose status is `AWARDED`, `REPORTING` or
    `CLOSED_SATISFIED`, and `available_undesignated_pool` as
    `opening_undesignated_pool` minus `awarded_total`."

    Design: Difficulty/cross_entity_state_dependency/award_gated_by_cycle_posture_restricted_by_another_agency
    """
    _, cycle, _, request_y = _third_party_restriction_scenario()

    validate_error(
        _award_attempt(cycle["id"], request_y["id"]), ERR_CYCLE_RESTRICTED, 409
    )

    inert = _read_request(request_y["id"])
    assert inert["status"] == "PANEL_APPROVED"
    assert_is_null(inert["total_award"], "total_award")
    assert_is_null(inert["base_award"], "base_award")
    assert_is_null(inert["awarded_at"], "awarded_at")

    ledger = _read_cycle(cycle["id"])
    assert_money(ledger["awarded_total"], "0.00", "awarded_total")
    assert_money(
        ledger["available_undesignated_pool"], "300000.00", "available_undesignated_pool"
    )
    assert_pool_conservation(ledger)


def test_reinstating_the_other_agency_reverses_the_cascade_and_reopens_the_cycle():
    """PRD 3.6: "Each affected cycle's `suspended_request_count` and
    `suspended_request_ratio` are then re-derived, and when the recomputed ratio has
    fallen strictly below 0.34 the cycle moves `RESTRICTED → OPEN` with
    `awards_blocked` cleared to false."

    Design: Difficulty/cross_entity_state_dependency/award_gated_by_cycle_posture_restricted_by_another_agency
    """
    agency_x, cycle, request_x, _ = _third_party_restriction_scenario()

    validate_success(
        api_client.reinstate_agency(
            agency_x["id"],
            reinstate_payload(
                justification="Corrective action plan accepted by the finance committee."
            ),
            make_admin_headers(),
        )
    )

    reread_agency = validate_success(
        api_client.get_agency(agency_x["id"], make_admin_headers())
    )
    assert reread_agency["membership_status"] == "GOOD_STANDING"

    restored = _read_request(request_x["id"])
    assert restored["status"] == "SUBMITTED", "the request returns to where it was pulled from"
    assert_is_null(restored["status_before_suspension"], "status_before_suspension")

    reopened = _read_cycle(cycle["id"])
    assert reopened["posture"] == "OPEN"
    assert_is_false(reopened["awards_blocked"], "awards_blocked")
    assert reopened["suspended_request_count"] == 0
    assert_decimal_equals(
        reopened["suspended_request_ratio"], "0.0000", "suspended_request_ratio"
    )


def test_the_identical_award_payload_succeeds_once_only_the_cycle_has_changed():
    """PRD 3.8: "`designation_offset` is `base_award` multiplied by that rate, rounded
    half up to two decimals, and then capped at the agency's
    `designated_passthrough_ytd` — an agency cannot be offset by more designation
    income than it actually received."

    The 0.15 tier rate would produce 9000.00, but the agency holds no designation
    income at all, so the cap takes the offset to 0.00.

    Design: Difficulty/cross_entity_state_dependency/award_gated_by_cycle_posture_restricted_by_another_agency
    """
    agency_x, cycle, _, request_y = _third_party_restriction_scenario()

    validate_error(
        _award_attempt(cycle["id"], request_y["id"]), ERR_CYCLE_RESTRICTED, 409
    )
    validate_success(
        api_client.reinstate_agency(
            agency_x["id"],
            reinstate_payload(
                justification="Corrective action plan accepted by the finance committee."
            ),
            make_admin_headers(),
        )
    )

    validate_success(_award_attempt(cycle["id"], request_y["id"]))

    awarded = _read_request(request_y["id"])
    assert awarded["status"] == "AWARDED"
    assert_money(awarded["base_award"], "60000.00", "base_award")
    assert_money(awarded["designation_offset"], "0.00", "designation_offset")
    assert awarded["designation_offset"] not in ("9000.00", 9000.00), (
        "9000.00 is the uncapped rated figure; the ledger cap of 0.00 wins"
    )
    assert_money(awarded["strategic_supplement"], "1800.00", "strategic_supplement")
    assert_money(awarded["total_award"], "61800.00", "total_award")

    ledger = _read_cycle(cycle["id"])
    assert_money(ledger["awarded_total"], "61800.00", "awarded_total")
    assert_money(
        ledger["available_undesignated_pool"], "238200.00", "available_undesignated_pool"
    )
    assert_pool_conservation(ledger)


def _conservation_scenario():
    """One PANEL_APPROVED 60000.00 request against the 300000.00 pool."""
    agency = _agency_certified_at_one_hundred(
        "Keystone Financial Coaching", "150000001", "FINANCIAL_STABILITY"
    )
    cycle, panelists = _open_cycle()
    request = create_panel_approved_request(
        cycle["id"],
        agency["id"],
        panelists,
        PERFECT_TRIPLE,
        requested_amount="60000.00",
        priority_area="HEALTH",
        narrative_summary="Financial coaching for shift workers.",
    )
    return agency, cycle, request


def _rescind(request_id):
    return api_client.rescind_award(
        request_id,
        rescind_payload(reason_code="PROGRAM_WITHDRAWN"),
        make_allocations_director_headers(),
    )


def _file_report(request_id, agency_id):
    return api_client.create_outcome_report(
        request_id,
        outcome_report_payload(
            reporting_period_end="2026-07-31",
            persons_served=210,
            outcome_metric_name="households_coached",
            outcome_metric_value="210.00",
            funds_expended="61800.00",
        ),
        make_agency_rep_headers(agency_id),
    )


def test_the_award_draws_exactly_its_total_out_of_the_undesignated_pool():
    """PRD 3.8: "The cycle's invariant holds at all times and with zero drift:
    `available_undesignated_pool` plus `awarded_total` always equals
    `opening_undesignated_pool`."

    Design: Difficulty/compensating_invariant/cycle_pool_conservation_survives_award_rescind_reaward
    """
    _, cycle, request = _conservation_scenario()

    before = _read_cycle(cycle["id"])
    assert_money(before["available_undesignated_pool"], "300000.00", "pool before")
    assert_money(before["awarded_total"], "0.00", "awarded_total before")
    assert_pool_conservation(before)

    validate_success(_award_attempt(cycle["id"], request["id"]))

    awarded = _read_request(request["id"])
    assert awarded["status"] == "AWARDED"
    assert_money(awarded["base_award"], "60000.00", "base_award")
    assert_money(awarded["designation_offset"], "0.00", "designation_offset")
    assert_money(awarded["strategic_supplement"], "1800.00", "strategic_supplement")
    assert_money(awarded["total_award"], "61800.00", "total_award")
    assert_date_equals(
        awarded["outcome_report_due_date"], "2027-01-28", "outcome_report_due_date"
    )

    after = _read_cycle(cycle["id"])
    assert_money(after["available_undesignated_pool"], "238200.00", "pool after")
    assert_money(after["awarded_total"], "61800.00", "awarded_total after")
    assert_pool_conservation(after)


def test_rescinding_nulls_every_component_and_returns_the_exact_amount_to_the_pool():
    """PRD 3.8: "A successful rescission sets `base_award`, `designation_offset`,
    `strategic_supplement`, `total_award`, `awarded_at` and `outcome_report_due_date`
    all back to null, then re-derives `awarded_total` and
    `available_undesignated_pool` so that the pool is restored exactly — the same
    conservation invariant must hold before and after with no residue."

    Design: Difficulty/compensating_invariant/cycle_pool_conservation_survives_award_rescind_reaward
    """
    _, cycle, request = _conservation_scenario()

    validate_success(_award_attempt(cycle["id"], request["id"]))
    validate_success(_rescind(request["id"]))

    rescinded = _read_request(request["id"])
    assert rescinded["status"] == "PANEL_APPROVED"
    for field in (
        "base_award",
        "designation_offset",
        "strategic_supplement",
        "total_award",
        "awarded_at",
        "outcome_report_due_date",
    ):
        assert_is_null(rescinded[field], field)
    assert_money(rescinded["composite_score"], "100.00", "composite_score is untouched")

    restored = _read_cycle(cycle["id"])
    assert_money(restored["available_undesignated_pool"], "300000.00", "pool restored")
    assert_money(restored["awarded_total"], "0.00", "awarded_total restored")
    assert_pool_conservation(restored)


def test_re_awarding_reproduces_the_identical_figures_under_the_refreshed_version():
    """PRD 2.6: "If that value does not equal the cycle's current `version`, the award
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Difficulty/compensating_invariant/cycle_pool_conservation_survives_award_rescind_reaward
    """
    _, cycle, request = _conservation_scenario()

    validate_success(_award_attempt(cycle["id"], request["id"]))
    version_after_award = current_cycle_version(cycle["id"])
    validate_success(_rescind(request["id"]))
    version_after_rescind = current_cycle_version(cycle["id"])
    assert version_after_rescind > version_after_award, (
        "the rescission is a mutation, so the cycle version advanced again"
    )

    validate_error(
        _award_attempt(cycle["id"], request["id"], version_after_award),
        ERR_STALE_VERSION,
        412,
    )
    still_approved = _read_request(request["id"])
    assert still_approved["status"] == "PANEL_APPROVED", "the stale attempt changed nothing"

    validate_success(
        _award_attempt(cycle["id"], request["id"], version_after_rescind)
    )

    reawarded = _read_request(request["id"])
    assert reawarded["status"] == "AWARDED"
    assert_money(reawarded["base_award"], "60000.00", "base_award")
    assert_money(reawarded["designation_offset"], "0.00", "designation_offset")
    assert_money(reawarded["strategic_supplement"], "1800.00", "strategic_supplement")
    assert_money(reawarded["total_award"], "61800.00", "total_award")

    ledger = _read_cycle(cycle["id"])
    assert_money(ledger["available_undesignated_pool"], "238200.00", "pool after re-award")
    assert_money(ledger["awarded_total"], "61800.00", "awarded_total after re-award")
    assert_pool_conservation(ledger)


def test_filing_the_report_keeps_the_award_inside_the_ledgers_status_set():
    """PRD 3.9: "Filing also computes `expenditure_variance_pct`: `funds_expended`
    minus the request's `total_award`, divided by that `total_award`, expressed as a
    percentage and rounded half up to two decimals — a negative figure when the agency
    underspent."

    Design: Difficulty/compensating_invariant/cycle_pool_conservation_survives_award_rescind_reaward
    """
    agency, cycle, request = _conservation_scenario()

    validate_success(_award_attempt(cycle["id"], request["id"]))
    report = validate_success(_file_report(request["id"], agency["id"]), 201)

    assert report["status"] == "SUBMITTED"
    assert report["revision_round_count"] == 0
    assert_decimal_equals(
        report["expenditure_variance_pct"], "0.00", "expenditure_variance_pct"
    )

    reporting = _read_request(request["id"])
    assert reporting["status"] == "REPORTING"
    assert_money(reporting["total_award"], "61800.00", "total_award")

    ledger = _read_cycle(cycle["id"])
    assert_money(ledger["awarded_total"], "61800.00", "awarded_total")
    assert_money(
        ledger["available_undesignated_pool"], "238200.00", "available_undesignated_pool"
    )
    assert_pool_conservation(ledger)


def test_the_compensation_window_closes_once_an_outcome_report_exists():
    """PRD 3.8: "It is refused with `ERR_AWARD_ALREADY_REPORTED` once any outcome report
    exists for the request, which is the sole reason a `REPORTING` request is admitted
    past the status gate at all."

    Design: Difficulty/compensating_invariant/cycle_pool_conservation_survives_award_rescind_reaward
    """
    agency, cycle, request = _conservation_scenario()

    validate_success(_award_attempt(cycle["id"], request["id"]))
    validate_success(_file_report(request["id"], agency["id"]), 201)

    validate_error(_rescind(request["id"]), ERR_AWARD_ALREADY_REPORTED, 409)

    unchanged = _read_request(request["id"])
    assert unchanged["status"] == "REPORTING"
    assert_money(unchanged["total_award"], "61800.00", "total_award")

    ledger = _read_cycle(cycle["id"])
    assert_money(ledger["awarded_total"], "61800.00", "awarded_total")
    assert_money(
        ledger["available_undesignated_pool"], "238200.00", "available_undesignated_pool"
    )
    assert_pool_conservation(ledger)
