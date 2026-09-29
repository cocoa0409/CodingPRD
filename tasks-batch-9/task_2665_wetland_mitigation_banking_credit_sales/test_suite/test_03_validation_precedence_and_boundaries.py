"""Validation-order precedence conflicts and inclusive-boundary arithmetic.

Two families of behaviour are exercised here. The first drives requests that
violate two rules of the PRD validation pipeline at once and pins which of the
two error identifiers the server must name; each conflict is paired with a
control call that cures only the winning violation and exposes the loser, so the
losing rule is demonstrably armed rather than merely unreachable. The second
sits measurements, credit quantities and vote counts exactly on their declared
thresholds and one unit either side of them, so an implementation that reads a
non-inclusive comparator is caught.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    TEST_DEFAULTS,
    add_milestone,
    api_client,
    approve_release_payload,
    assert_cents,
    assert_credits,
    assert_score,
    bank_state,
    claim_milestone,
    create_credit_sale_payload,
    create_monitoring_report_payload,
    create_vote_payload,
    ledger_rows,
    milestone_state,
    open_monitoring_report,
    permittee_state,
    review_report_payload,
    set_clock,
    setup_bank_under_review,
    setup_monitoring_ready_bank,
    setup_sellable_bank,
    submit_monitoring_report,
    validate_error,
    validate_paginated,
    validate_success,
)

# The four canonical standards of the shared work plan, measured exactly on
# their thresholds: GTE 120 days, LTE 10.0 percent, GTE 80.0 percent, GTE 400
# stems per acre.
AT_THRESHOLD_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 120},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 10.0},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 80.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 400},
]

# One unit the wrong side of two of those thresholds; the other two stay exactly
# on theirs.
ONE_UNIT_BELOW_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 119},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 10.1},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 80.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 400},
]

YEAR1_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 128},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 7.0},
]


def _unfunded_bank_with_pending_milestone():
    """An INSTRUMENT_EXECUTED bank whose easement is recorded but whose
    stewardship endowment holds nothing, carrying one PENDING milestone."""
    set_clock(CLOCK_EPOCH)
    world = setup_sellable_bank(
        stewardship_funded_cents=0,
        record_easement=True,
        release_first_milestone=False,
    )
    milestone = add_milestone(world)
    world["bank"] = bank_state(world)
    return world, milestone


def _sellable_bank_with_outside_permittee():
    """The shared sellable bank plus a permit holder whose obligation is 12.00
    credits and whose authorised impacts sit outside the service area."""
    set_clock(CLOCK_EPOCH)
    return setup_sellable_bank(
        permittee_required_credits=12.00,
        permittee_impact_huc8_code=TEST_DEFAULTS["OUTSIDE_HUC8"],
        permittee_deposit_cents=40_000_000,
    )


def _bank_with_year_one_report():
    """A monitoring-ready bank holding one DRAFT report for year 1 over the
    half-open window [2027-06-01, 2027-09-01)."""
    set_clock(CLOCK_EPOCH)
    world = setup_monitoring_ready_bank()
    set_clock("2027-09-15T00:00:00Z")
    report = open_monitoring_report(
        world,
        monitoring_year=1,
        window_start="2027-06-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        measurements_array=YEAR1_MEASUREMENTS,
    )
    return world, report


def _open_report_response(world, **payload_overrides):
    """Attempt one monitoring-report creation and hand back the raw response."""
    return api_client.create_monitoring_report(
        create_monitoring_report_payload(world["bank"]["id"], **payload_overrides),
        world["sponsor_headers"],
    )


def _accept_scored_report(world, monitoring_year, window_start, window_end, measurements_array):
    """Open, submit and accept one report, returning the review response."""
    report = open_monitoring_report(
        world,
        monitoring_year=monitoring_year,
        window_start=window_start,
        window_end=window_end,
        measurements_array=measurements_array,
    )
    submit_monitoring_report(world, report["id"])
    response = api_client.review_monitoring_report(
        report["id"], review_report_payload("ACCEPT"), world["member_headers"][1]
    )
    return report, response


def _quote_response(world, credits_requested, impact_huc8_code, expected_bank_version):
    """Attempt one quote as the buying permit holder, raw response."""
    return api_client.create_credit_sale(
        create_credit_sale_payload(
            world["bank"]["id"],
            world["permittee"]["id"],
            credits_requested,
            expected_bank_version,
            impact_huc8_code=impact_huc8_code,
        ),
        world["permittee_headers"],
    )


class TestMilestoneStateOutranksStewardshipGate:
    """The 409 milestone-state rejection sits ahead of the 402 stewardship gate."""

    def test_pending_milestone_yields_state_error_not_funding_error(self):
        """A release approval against a never-claimed milestone on an endowment
        holding 0 of the 28420000 interim gate must name the state violation.

        Both rules are broken by the one request, and the pipeline places the
        entity state check well ahead of the fiscal checks, so the 409 wins.

        PRD §2.10: "After identity comes state: first whether the target row is in a state from which the requested transition exists at all, returning the entity-specific code (`ERR_BANK_STATE_INVALID`, `ERR_PROSPECTUS_STATE_INVALID`, `ERR_WORK_PLAN_STATE_INVALID`, `ERR_MILESTONE_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`, `ERR_REMEDIAL_STATE_INVALID` or `ERR_SALE_STATE_INVALID`); then the sales-posture gate of §2.8; then the optimistic-concurrency check (`ERR_STALE_BANK_VERSION`)."
        PRD §2.10: "Fiscal checks are evaluated last, in this order: credit availability (`ERR_INSUFFICIENT_CREDITS`), escrow sufficiency (`ERR_INSUFFICIENT_ESCROW`), stewardship funding (`ERR_STEWARDSHIP_UNDERFUNDED`) and the performance assurance bond (`ERR_PERFORMANCE_BOND_INSUFFICIENT`)."
        PRD §3.6: "The milestone must be in `CLAIMED`; anything else is `ERR_MILESTONE_STATE_INVALID`."
        Design: Difficulty/priority_pair_validation_conflict/milestone_state_error_outranks_stewardship_funding_gate
        """
        world, milestone = _unfunded_bank_with_pending_milestone()
        before = bank_state(world)
        assert_cents(
            before["stewardship_funded_cents"], 0, "endowment must hold nothing"
        )
        assert_cents(
            before["stewardship_required_cents"],
            113680000,
            "required endowment capitalised from 4200000 per year",
        )
        assert milestone_state(milestone["id"], world)["status"] == "PENDING", (
            "the milestone must never have been claimed for the pair to be live"
        )

        response = api_client.approve_milestone_release(
            milestone["id"],
            approve_release_payload(before["version"]),
            world["member_headers"][0],
        )
        validate_error(response, ApiErrorId.ERR_MILESTONE_STATE_INVALID, 409)

        after = bank_state(world)
        assert after["version"] == before["version"], (
            "a rejected approval must not increment the bank version"
        )
        assert_credits(after["credits_released"], 0.00, "credits_released")
        assert ledger_rows(world, entry_type="RELEASED") == [], (
            "no RELEASED entry may be appended by a rejected approval"
        )

    def test_claiming_the_milestone_exposes_the_stewardship_shortfall(self):
        """With the state violation cured by a claim, the same approval falls
        through to the 402 stewardship gate, proving the funding rule is armed.

        The endowment still holds 0 of the 28420000 interim gate that every
        milestone code other than PERF_YEAR_10 must clear.

        PRD §3.6: "And the bank's stewardship endowment must clear the gate for this milestone code: for every code other than `PERF_YEAR_10` the funded amount must be at least the interim gate of 25 percent of the required endowment rounded half up to whole cents, while for `PERF_YEAR_10` the funded amount must be at least the required endowment in full."
        PRD §3.6: "A shortfall is rejected with `ERR_STEWARDSHIP_UNDERFUNDED`."
        Design: Difficulty/priority_pair_validation_conflict/milestone_state_error_outranks_stewardship_funding_gate
        """
        world, milestone = _unfunded_bank_with_pending_milestone()
        claim_milestone(world, milestone["id"])
        before = bank_state(world)

        response = api_client.approve_milestone_release(
            milestone["id"],
            approve_release_payload(before["version"]),
            world["member_headers"][0],
        )
        validate_error(response, ApiErrorId.ERR_STEWARDSHIP_UNDERFUNDED, 402)

        claimed = milestone_state(milestone["id"], world)
        assert claimed["status"] == "CLAIMED", (
            "the rejected approval must leave the milestone in CLAIMED"
        )
        assert claimed["attainment_factor_applied"] is None, (
            "no attainment factor may be stamped by a rejected approval"
        )

        after = bank_state(world)
        assert after["version"] == before["version"], (
            "a rejected approval must not increment the bank version"
        )
        assert_credits(after["credits_released"], 0.00, "credits_released")
        assert_cents(
            after["stewardship_required_cents"], 113680000, "stewardship_required_cents"
        )


class TestServiceAreaOutranksObligationCeiling:
    """Regulatory safety beats referential dependency beats fiscal ceiling."""

    def test_outside_service_area_wins_over_obligation_and_credit_ceilings(self):
        """A 20.00-credit quote for an impact watershed outside the service area
        must be rejected on the service-area rule.

        The same request also exceeds the buyer's 12.00 unmet obligation and the
        bank's 14.82 available credits, but regulatory safety checks are
        evaluated ahead of both the referential and the fiscal groups.

        PRD §2.10: "Regulatory safety checks follow the concurrency check, in this order: the easement precondition (`ERR_EASEMENT_NOT_RECORDED`), the service-area containment rule (`ERR_OUTSIDE_SERVICE_AREA`), the segregation-of-duties rule (`ERR_SEGREGATION_OF_DUTIES`), and the site-watershed membership rule at bank creation (`ERR_SERVICE_AREA_MISSING_SITE_HUC`)."
        PRD §2.10: "Referential dependency checks follow, in this order: the prospectus and work plan prerequisites (`ERR_WORK_PLAN_MISSING` and `ERR_PROSPECTUS_NOT_APPROVED`), review quorum (`ERR_IRT_QUORUM_NOT_MET`), effective standards and their measurements (`ERR_NO_EFFECTIVE_STANDARDS` and `ERR_MEASUREMENT_MISSING`), the monitoring prerequisites of a performance release (`ERR_NO_ACCEPTED_MONITORING_REPORT` and `ERR_COMPLIANCE_FAILED`), and the permit obligation ceiling (`ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT`)."
        PRD §3.8: "The impact watershed must fall inside the bank's service area, or the quote is rejected with `ERR_OUTSIDE_SERVICE_AREA`: this is the service-area limitation that gives mitigation banking its geographic integrity, and it is also what fixes the sale's `service_area_tier`, which is `PRIMARY` when the impact watershed is the bank's own site watershed and `SECONDARY` when it is any other member of the bank's service-area list."
        Design: Difficulty/priority_pair_validation_conflict/outside_service_area_outranks_assignment_requirement_ceiling
        """
        world = _sellable_bank_with_outside_permittee()
        before = bank_state(world)
        assert_credits(before["credits_available"], 14.82, "credits_available")
        assert before["sales_posture"] == "OPEN", (
            "the posture must be OPEN so the posture gate cannot mask the pair"
        )

        response = _quote_response(world, 20.00, "05010007", before["version"])
        validate_error(response, ApiErrorId.ERR_OUTSIDE_SERVICE_AREA, 422)

        after = bank_state(world)
        assert after["open_quote_count"] == 0, (
            "a rejected quote must not raise the open quote count"
        )
        assert_credits(after["credits_available"], 14.82, "credits_available")

    def test_obligation_ceiling_wins_over_credit_availability(self):
        """Inside the service area the same 20.00 credits surface the permit
        obligation ceiling, not the credit-availability shortfall.

        20.00 exceeds both the 12.00 unmet obligation and the 14.82 available
        credits; the obligation rule belongs to the referential group and the
        availability rule to the fiscal group evaluated last.

        PRD §3.8: "The requested quantity must not exceed the bank's available credits — requesting exactly the available quantity is accepted — with a shortfall rejected as `ERR_INSUFFICIENT_CREDITS`; and it must not exceed the buyer's outstanding permit obligation, with an excess rejected as `ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT`."
        PRD §2.10: "Fiscal checks are evaluated last, in this order: credit availability (`ERR_INSUFFICIENT_CREDITS`), escrow sufficiency (`ERR_INSUFFICIENT_ESCROW`), stewardship funding (`ERR_STEWARDSHIP_UNDERFUNDED`) and the performance assurance bond (`ERR_PERFORMANCE_BOND_INSUFFICIENT`)."
        Design: Difficulty/priority_pair_validation_conflict/outside_service_area_outranks_assignment_requirement_ceiling
        """
        world = _sellable_bank_with_outside_permittee()
        before = bank_state(world)

        response = _quote_response(world, 20.00, "03130003", before["version"])
        validate_error(response, ApiErrorId.ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT, 422)

        buyer = permittee_state(world)
        assert_credits(
            buyer["unmet_requirement_credits"], 12.00, "unmet_requirement_credits"
        )
        assert bank_state(world)["open_quote_count"] == 0, (
            "a rejected quote must not raise the open quote count"
        )

    def test_secondary_watershed_quote_within_the_obligation_succeeds(self):
        """A 4.00-credit quote inside the service area but outside the site
        watershed is accepted and priced at the SECONDARY tier.

        The control arm proves the two rejections above were rule-driven rather
        than a blanket refusal of this buyer.

        PRD §3.8: "A quote opens in `QUOTED` status with `hold_start_at`, `hold_expires_at`, `executed_price_cents`, `executed_at`, `assigned_at`, `assignment_reference`, `cancelled_reason` and `cancelled_at` all null, raises the bank's `open_quote_count` by one and increments the bank's `version` by one."
        PRD §3.1: "`assigned_credits` is the total requested-credit quantity across this holder's sales standing in `ASSIGNED` status, starting at 0."
        PRD §3.1: "`unmet_requirement_credits` is the required credits minus the assigned credits, floored at zero so it can never go negative, carried to 2 decimal places, and therefore equal to the required credits at registration."
        Design: Difficulty/priority_pair_validation_conflict/outside_service_area_outranks_assignment_requirement_ceiling
        """
        world = _sellable_bank_with_outside_permittee()
        before = bank_state(world)

        response = _quote_response(world, 4.00, "03130003", before["version"])
        sale = validate_success(response, 201)
        assert sale["status"] == "QUOTED", "an accepted quote opens in QUOTED"
        assert sale["service_area_tier"] == "SECONDARY", (
            "03130003 is a service-area member other than the site watershed"
        )
        assert sale["executed_price_cents"] is None, (
            "a fresh quote carries no settled price"
        )

        after = bank_state(world)
        assert after["open_quote_count"] == 1, "the quote raises open_quote_count to 1"
        assert_credits(after["credits_available"], 14.82, "credits_available")

        buyer = permittee_state(world)
        assert_credits(buyer["assigned_credits"], 0.00, "assigned_credits")
        assert_credits(
            buyer["unmet_requirement_credits"], 12.00, "unmet_requirement_credits"
        )


class TestWindowOverlapOutranksDuplicateYear:
    """The temporal overlap rule is evaluated before the uniqueness rules."""

    def test_overlapping_window_wins_over_the_reused_monitoring_year(self):
        """A second year-1 report whose window overlaps the existing year-1
        window by two months must be rejected on the overlap, not the duplicate.

        Both rules are broken: monitoring_year 1 is already occupied and
        [2027-08-01, 2027-11-01) intersects [2027-06-01, 2027-09-01) over a
        positive length.

        PRD §2.10: "Then come the temporal rules, in this order: monitoring window overlap (`ERR_MONITORING_WINDOW_OVERLAP`), reservation hold conflict (`ERR_RESERVATION_HOLD_CONFLICT`), milestone window buffer (`ERR_MILESTONE_WINDOW_BUFFER`), milestone window not yet open (`ERR_MILESTONE_WINDOW_NOT_OPEN`) and remedial work past due (`ERR_REMEDIAL_PAST_DUE`)."
        PRD §2.10: "Uniqueness and aggregate constraints are evaluated next, in this order: duplicate monitoring year (`ERR_DUPLICATE_MONITORING_YEAR`), duplicate milestone code (`ERR_DUPLICATE_MILESTONE_CODE`), an oversubscribed release schedule (`ERR_RELEASE_SCHEDULE_OVERSUBSCRIBED`), a predecessor milestone not yet released (`ERR_PREDECESSOR_NOT_RELEASED`), a duplicate vote in the round (`ERR_DUPLICATE_VOTE`), a duplicate permit number (`ERR_DUPLICATE_PERMIT_NUMBER`), and the single-approved-work-plan rule together with the standard-weight sum rule (`ERR_WORK_PLAN_ALREADY_APPROVED` and `ERR_STANDARD_WEIGHTS_INVALID`)."
        PRD §3.7: "Those windows are half-open, so a new window whose start equals an existing window's end is perfectly acceptable adjacency; only a positive-length intersection with an occupying window is rejected, with `ERR_MONITORING_WINDOW_OVERLAP`."
        Design: Difficulty/priority_pair_validation_conflict/monitoring_window_overlap_outranks_duplicate_year
        """
        world, existing = _bank_with_year_one_report()
        assert existing["monitoring_year"] == 1, "the occupying report holds year 1"

        response = _open_report_response(
            world,
            monitoring_year=1,
            window_start="2027-08-01T00:00:00Z",
            window_end="2027-11-01T00:00:00Z",
            measurements_array=[
                {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 126},
                {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
            ],
        )
        validate_error(response, ApiErrorId.ERR_MONITORING_WINDOW_OVERLAP, 409)

        rows, meta = validate_paginated(
            api_client.list_monitoring_reports(
                world["sponsor_headers"],
                params={"bank_id": world["bank"]["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 1, "the rejected creation must persist nothing"

    def test_adjacent_window_reusing_year_one_yields_the_duplicate_year_error(self):
        """With the overlap cured by an adjacent window, the reused monitoring
        year surfaces, proving the uniqueness rule is armed.

        [2027-09-01, 2027-12-01) begins exactly where the occupying window ends,
        so the intervals do not intersect and only the year collides.

        PRD §3.7: "The monitoring year must be at least 1 and must be unique within the bank among reports whose review status is `DRAFT`, `SUBMITTED` or `ACCEPTED` — a duplicate is rejected with `ERR_DUPLICATE_MONITORING_YEAR`, while a `RETURNED` report releases its year and its window slot back."
        Design: Difficulty/priority_pair_validation_conflict/monitoring_window_overlap_outranks_duplicate_year
        """
        world, _existing = _bank_with_year_one_report()

        response = _open_report_response(
            world,
            monitoring_year=1,
            window_start="2027-09-01T00:00:00Z",
            window_end="2027-12-01T00:00:00Z",
            measurements_array=[
                {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 126},
                {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
            ],
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_MONITORING_YEAR, 409)

        _rows, meta = validate_paginated(
            api_client.list_monitoring_reports(
                world["sponsor_headers"],
                params={"bank_id": world["bank"]["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 1, "the rejected creation must persist nothing"

    def test_adjacent_window_with_a_fresh_year_is_accepted(self):
        """An adjacent window carrying monitoring year 2 is accepted, because a
        window starting at an existing window's end is legal adjacency.

        PRD §3.7: "Those windows are half-open, so a new window whose start equals an existing window's end is perfectly acceptable adjacency; only a positive-length intersection with an occupying window is rejected, with `ERR_MONITORING_WINDOW_OVERLAP`."
        PRD §3.7: "A new report opens with its review status at `DRAFT`, its compliance status at `UNEVALUATED`, `return_count` at 0, `attainment_score` null, `failed_standard_codes` empty, and `reviewed_by_member_id`, `submitted_at` and `reviewed_at` all null."
        Design: Difficulty/priority_pair_validation_conflict/monitoring_window_overlap_outranks_duplicate_year
        """
        world, _existing = _bank_with_year_one_report()

        response = _open_report_response(
            world,
            monitoring_year=2,
            window_start="2027-09-01T00:00:00Z",
            window_end="2027-12-01T00:00:00Z",
            measurements_array=[
                {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 126},
                {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
            ],
        )
        report = validate_success(response, 201)
        assert report["review_status"] == "DRAFT", "a new report opens in DRAFT"
        assert report["compliance_status"] == "UNEVALUATED", (
            "the ecological track opens at UNEVALUATED"
        )
        assert report["return_count"] == 0, "return_count opens at 0"
        assert report["attainment_score"] is None, "an unscored report has no score"
        assert report["failed_standard_codes"] == [], "failed codes open empty"

        _rows, meta = validate_paginated(
            api_client.list_monitoring_reports(
                world["sponsor_headers"],
                params={"bank_id": world["bank"]["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 2, (
            "the bank must hold exactly the year-1 and year-2 reports"
        )


class TestAttainmentExactlyAtEveryThreshold:
    """The four ecological comparators are inclusive at their boundaries."""

    def test_measurements_on_every_threshold_score_a_full_pass(self):
        """Measurements sitting exactly on 120, 10.0, 80.0 and 400 must all
        count as met, giving an attainment score of 1.0000 and PASS.

        A strict greater-than or less-than reading would fail all four standards
        and score the year FAIL instead.

        PRD §3.7: "For a standard whose comparator is `GTE`, the ratio is the measured value divided by the threshold, capped at 1.0 so over-performance earns no bonus, and the standard is met when the measured value is greater than or equal to the threshold — equality counts as attainment."
        PRD §3.7: "For a standard whose comparator is `LTE`, the ratio is exactly 1.0 when the measured value is less than or equal to the threshold; when the measured value exceeds the threshold, the ratio is 1.0 minus the excess over the threshold divided by the threshold, floored at 0.0 so a catastrophic overshoot scores zero rather than negative, and the standard is met when the measured value is less than or equal to the threshold — again, equality counts."
        PRD §3.7: "The compliance status then follows from those two outputs in order: it is `PASS` when no standard failed, otherwise `PARTIAL` when the attainment score is at least 0.85 — the boundary is inclusive — and otherwise `FAIL`."
        Design: Difficulty/boundary_precision_check/attainment_exactly_at_every_threshold_scores_full_pass
        """
        set_clock(CLOCK_EPOCH)
        world = setup_monitoring_ready_bank()
        set_clock("2029-09-05T00:00:00Z")

        _report, response = _accept_scored_report(
            world,
            monitoring_year=3,
            window_start="2029-06-01T00:00:00Z",
            window_end="2029-09-01T00:00:00Z",
            measurements_array=AT_THRESHOLD_MEASUREMENTS,
        )
        data = validate_success(response, 200)
        assert data["review_status"] == "ACCEPTED", "the paperwork track advances"
        assert_score(data["attainment_score"], 1.0000)
        assert data["compliance_status"] == "PASS", (
            "no standard is missed when every measurement sits on its threshold"
        )
        assert data["failed_standard_codes"] == [], (
            "equality counts as attainment on all four comparators"
        )

    def test_at_threshold_acceptance_opens_no_remedial_action(self):
        """A passing acceptance must not trigger the failure cascade: no remedial
        action exists and the sales posture is left where the ladder had it.

        PRD §3.7: "And if the computed compliance status is `FAIL`, acceptance triggers a four-hop cascade whose order is pinned, because the credit arithmetic at the end depends on it."
        PRD §3.7: "Remedial actions have no creation endpoint; this cascade is the only thing that makes one."
        PRD §3.7: "If the bank has never had an accepted report before, this acceptance additionally carries the bank `INSTRUMENT_EXECUTED → MONITORING`."
        Design: Difficulty/boundary_precision_check/attainment_exactly_at_every_threshold_scores_full_pass
        """
        set_clock(CLOCK_EPOCH)
        world = setup_monitoring_ready_bank()
        set_clock("2029-09-05T00:00:00Z")
        posture_before = bank_state(world)["sales_posture"]

        report, response = _accept_scored_report(
            world,
            monitoring_year=3,
            window_start="2029-06-01T00:00:00Z",
            window_end="2029-09-01T00:00:00Z",
            measurements_array=AT_THRESHOLD_MEASUREMENTS,
        )
        validate_success(response, 200)

        _rows, meta = validate_paginated(
            api_client.list_remedial_actions(
                world["sponsor_headers"],
                params={"monitoring_report_id": report["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 0, (
            "a PASS acceptance must open no remedial action"
        )

        after = bank_state(world)
        assert after["status"] == "MONITORING", (
            "the first accepted report carries the bank into MONITORING"
        )
        assert after["sales_posture"] == posture_before, (
            "a passing acceptance leaves the posture ladder's verdict unchanged"
        )
        assert_credits(after["credits_released"], 0.00, "credits_released")

    def test_one_unit_past_two_thresholds_drops_compliance_to_partial(self):
        """119 days and 10.1 percent barely move the score to 0.9950 yet flip
        compliance to PARTIAL, because PASS depends on the failed-code list.

        The per-standard contributions are 0.2975, 0.2475, 0.3000 and 0.1500,
        each rounded at 4 decimal places before the summation.

        PRD §3.7: "Each standard's contribution is its ratio multiplied by its weight, rounded half up to 4 decimal places; this per-standard rounding is pinned and precedes summation."
        PRD §3.7: "The report's `attainment_score` is the sum of those already-rounded contributions divided by the sum of the effective standards' weights as supplied — the denominator uses the unrounded weights and covers only the standards effective in this year, so a report in an early monitoring year is scored against a denominator smaller than 1.000 — with the quotient rounded half up to 4 decimal places."
        PRD §3.7: "`failed_standard_codes` lists the codes of the standards not met, in ascending code order."
        Design: Difficulty/boundary_precision_check/attainment_exactly_at_every_threshold_scores_full_pass
        """
        set_clock(CLOCK_EPOCH)
        world = setup_monitoring_ready_bank()
        set_clock("2031-09-05T00:00:00Z")

        _report, response = _accept_scored_report(
            world,
            monitoring_year=5,
            window_start="2031-06-01T00:00:00Z",
            window_end="2031-09-01T00:00:00Z",
            measurements_array=ONE_UNIT_BELOW_MEASUREMENTS,
        )
        data = validate_success(response, 200)
        assert_score(data["attainment_score"], 0.9950)
        assert data["compliance_status"] == "PARTIAL", (
            "a single missed standard forbids PASS however high the score"
        )
        assert data["failed_standard_codes"] == [
            "HYDROPERIOD_DAYS",
            "INVASIVE_COVER_PCT",
        ], "failed codes are listed in ascending standard-code order"


class TestQuoteForExactlyAvailableCredits:
    """The credit-availability ceiling reads <=, and exhausting it flips SOLD_OUT."""

    def test_one_hundredth_of_a_credit_over_the_ceiling_is_rejected(self):
        """14.83 credits against 14.82 available must be rejected on the credit
        ceiling, the smallest possible overshoot at 2 decimal places.

        PRD §3.8: "The requested quantity must not exceed the bank's available credits — requesting exactly the available quantity is accepted — with a shortfall rejected as `ERR_INSUFFICIENT_CREDITS`; and it must not exceed the buyer's outstanding permit obligation, with an excess rejected as `ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT`."
        Design: Difficulty/boundary_precision_check/quote_for_exactly_available_credits_accepted_then_sold_out
        """
        set_clock(CLOCK_EPOCH)
        world = setup_sellable_bank(permittee_required_credits=20.00)
        before = bank_state(world)
        assert_credits(before["credits_available"], 14.82, "credits_available")
        assert before["sales_posture"] == "OPEN", "the bank must be quotable"

        response = _quote_response(world, 14.83, "03130002", before["version"])
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_CREDITS, 422)

        after = bank_state(world)
        assert after["open_quote_count"] == 0, (
            "a rejected quote must not raise the open quote count"
        )
        assert_credits(after["credits_available"], 14.82, "credits_available")

    def test_exact_fit_quote_is_accepted_and_priced_from_the_tiered_subtotal(self):
        """A quote for exactly the 14.82 available credits is accepted and priced
        at 58806216 cents.

        The DEPRESSIONAL base price of 3,800,000 cents yields a tiered subtotal
        of 54450200 cents across the first two marginal tiers; the 8 percent
        under-funded stewardship surcharge adds 4356016 cents, and the 62617730
        price cap does not bind. The impact watershed is the site watershed, so
        the PRIMARY tier attracts no service-area premium.

        PRD §3.8: "Pricing starts from the bank's hydrogeomorphic class, which fixes a base price per credit: 4,250,000 cents for `RIVERINE`, 3,800,000 cents for `DEPRESSIONAL`, 3,600,000 cents for `SLOPE`, 3,300,000 cents for `FLATS` and 5,100,000 cents for `ESTUARINE`."
        PRD §3.8: "Each tier carrying a non-zero quantity contributes its quantity multiplied by the base price and by its multiplier, rounded half up to whole cents, and the tiered subtotal is the sum of those already-rounded tier amounts; a tier carrying zero credits contributes nothing and is not rounded at all."
        PRD §3.8: "A bank whose stewardship endowment is funded below its requirement attracts a further 8 percent, and a fully funded bank attracts nothing."
        PRD §3.8: "Finally a ceiling is applied: the price cap is the tiered subtotal multiplied by 1.15, rounded half up to whole cents, and the price charged is whichever of the gross price and the cap is smaller."
        Design: Difficulty/boundary_precision_check/quote_for_exactly_available_credits_accepted_then_sold_out
        """
        set_clock(CLOCK_EPOCH)
        world = setup_sellable_bank(permittee_required_credits=20.00)
        before = bank_state(world)

        response = _quote_response(world, 14.82, "03130002", before["version"])
        sale = validate_success(response, 201)
        assert sale["status"] == "QUOTED", "requesting exactly the ceiling is accepted"
        assert sale["service_area_tier"] == "PRIMARY", (
            "the impact watershed is the bank's own site watershed"
        )
        assert_credits(sale["credits_requested"], 14.82, "credits_requested")
        assert_cents(sale["quoted_price_cents"], 58806216, "quoted_price_cents")

    def test_reserving_the_exact_fit_quote_drives_the_bank_to_sold_out(self):
        """The reservation freezes all 14.82 credits, leaving available credits at
        exactly 0.00 and the posture at SOLD_OUT.

        PRD §3.8: "Reservation stamps `hold_start_at` with the current clock and `hold_expires_at` 30 days later, appends a `HOLD_PLACED` entry carrying the requested credits as a negative delta and attributed through a source entity type of `CREDIT_SALE` and the sale's own identifier, recomputes the bank's credits on hold and available credits and its posture, recomputes the bank's `open_quote_count`, and increments the bank's `version` by one."
        PRD §2.8: "Otherwise, if the bank's available credits are exactly zero, the posture is `SOLD_OUT`."
        PRD §2.11: "The invariant no endpoint may ever break is that released credits equal the sum of sold, on-hold and available credits, and that available credits equal the `balance_after` of the bank's highest-numbered ledger entry."
        Design: Difficulty/boundary_precision_check/quote_for_exactly_available_credits_accepted_then_sold_out
        """
        set_clock(CLOCK_EPOCH)
        world = setup_sellable_bank(permittee_required_credits=20.00)
        quote = validate_success(
            _quote_response(world, 14.82, "03130002", bank_state(world)["version"]), 201
        )

        reserved = validate_success(
            api_client.reserve_credit_sale(quote["id"], world["permittee_headers"]), 200
        )
        assert reserved["status"] == "RESERVED", "the sale advances QUOTED -> RESERVED"
        assert reserved["hold_expires_at"].startswith("2026-08-31T00:00:00"), (
            "the hold expires 30 days after the 2026-08-01 clock, got "
            f"{reserved['hold_expires_at']}"
        )

        after = bank_state(world)
        assert_credits(after["credits_on_hold"], 14.82, "credits_on_hold")
        assert_credits(after["credits_available"], 0.00, "credits_available")
        assert_credits(after["credits_sold"], 0.00, "credits_sold")
        assert_credits(after["credits_released"], 14.82, "credits_released")
        assert after["sales_posture"] == "SOLD_OUT", (
            "exactly zero available credits lands the ladder on SOLD_OUT"
        )
        assert_credits(
            after["credits_released"],
            after["credits_sold"] + after["credits_on_hold"] + after["credits_available"],
            "conservation invariant",
        )

    def test_a_sold_out_bank_rejects_the_next_quote_on_posture_not_credits(self):
        """Once the pool is empty the next quote is turned away on the posture
        gate, which sits ahead of the fiscal credit ceiling.

        PRD §2.8: "The rejection code is keyed to the offending posture value rather than to the operation: a `FROZEN` bank yields `ERR_BANK_SALES_FROZEN`, a `RESTRICTED` bank yields `ERR_BANK_SALES_RESTRICTED`, and a `SOLD_OUT` bank blocking a quote or a reservation yields `ERR_BANK_SOLD_OUT`."
        PRD §2.8: "Quoting and reserving both require a posture of exactly `OPEN`."
        Design: Difficulty/boundary_precision_check/quote_for_exactly_available_credits_accepted_then_sold_out
        """
        set_clock(CLOCK_EPOCH)
        world = setup_sellable_bank(permittee_required_credits=20.00)
        quote = validate_success(
            _quote_response(world, 14.82, "03130002", bank_state(world)["version"]), 201
        )
        validate_success(
            api_client.reserve_credit_sale(quote["id"], world["permittee_headers"]), 200
        )

        sold_out = bank_state(world)
        assert sold_out["sales_posture"] == "SOLD_OUT", "precondition for this arm"

        response = _quote_response(world, 0.01, "03130002", sold_out["version"])
        validate_error(response, ApiErrorId.ERR_BANK_SOLD_OUT, 409)


class TestQuorumOfExactlyThreeVotes:
    """The review quorum reads at least 3, and 2 of 3 concurrences suffices."""

    def test_two_votes_are_one_short_of_quorum(self):
        """Closing the round on two cast votes must be rejected on quorum and
        must leave the prospectus exactly where it stood.

        PRD §3.3: "Quorum first: at least 3 votes must have been cast in the current round, exactly 3 being sufficient; fewer yields `ERR_IRT_QUORUM_NOT_MET`."
        Design: Difficulty/boundary_precision_check/irt_quorum_exactly_three_votes_finalizes_review
        """
        set_clock(CLOCK_EPOCH)
        world = setup_bank_under_review(
            work_plan_state="SUBMITTED", vote_positions=["CONCUR", "ABSTAIN"]
        )
        prospectus_id = world["prospectus"]["id"]

        response = api_client.finalize_prospectus_review(
            prospectus_id, world["chair_headers"]
        )
        validate_error(response, ApiErrorId.ERR_IRT_QUORUM_NOT_MET, 422)

        after = validate_success(
            api_client.get_prospectus(prospectus_id, world["chair_headers"]), 200
        )
        assert after["status"] == "UNDER_REVIEW", (
            "a rejected finalisation leaves the round open"
        )
        assert after["decided_at"] is None, "no decision instant may be stamped"
        assert after["decision_recorded_by"] is None, "no chair identity is recorded"
        assert after["revision_round"] == 1, "the round counter must not advance"

    def test_the_third_vote_completes_the_tally_without_concurring_twice(self):
        """The third vote brings the votes cast to exactly 3 while the concur
        tally reaches only 2, because the ABSTAIN counts elsewhere.

        PRD §3.3: "Each vote raises exactly one of `concur_count`, `object_count` or `abstain_count` by one — the tallies count only votes bearing the prospectus's current revision round — and a veto vote raises the object tally and additionally sets `veto_recorded` to true."
        PRD §3.3: "Its `is_veto` flag is derived: true precisely when the position is `OBJECT` **and** the casting member holds veto authority."
        Design: Difficulty/boundary_precision_check/irt_quorum_exactly_three_votes_finalizes_review
        """
        set_clock(CLOCK_EPOCH)
        world = setup_bank_under_review(
            work_plan_state="SUBMITTED", vote_positions=["CONCUR", "ABSTAIN"]
        )
        prospectus_id = world["prospectus"]["id"]

        third = validate_success(
            api_client.create_prospectus_vote(
                prospectus_id, create_vote_payload("CONCUR"), world["member_headers"][2]
            ),
            201,
        )
        assert third["revision_round"] == 1, "the vote is scoped to the open round"

        tallies = validate_success(
            api_client.get_prospectus(prospectus_id, world["chair_headers"]), 200
        )
        assert tallies["concur_count"] == 2, (
            "only the two CONCUR positions raise the concur tally"
        )
        assert tallies["abstain_count"] == 1, "the ABSTAIN raises the abstain tally"
        assert tallies["object_count"] == 0, "nobody objected"
        assert tallies["veto_recorded"] is False, "no OBJECT vote means no veto"

        votes, meta = validate_paginated(
            api_client.list_prospectus_votes(
                prospectus_id, world["chair_headers"], params={"limit": 100}
            )
        )
        assert meta["total_count"] == 3, "exactly three votes stand in the round"
        abstentions = [v for v in votes if v["position"] == "ABSTAIN"]
        assert len(abstentions) == 1, "one abstention was cast"
        assert abstentions[0]["is_veto"] is False, (
            "only an OBJECT from a veto-holding agency is a veto"
        )

    def test_exactly_three_votes_with_two_concurrences_approves_the_prospectus(self):
        """With votes cast at exactly the quorum minimum and the concur tally at
        exactly the rounded-up two-thirds threshold, the round closes APPROVED.

        Two concurrences out of three votes is precisely sufficient, and the
        approval branch records the chair's opaque identity and the decision
        instant.

        PRD §3.3: "Then the supermajority: the concur tally must be at least two-thirds of the votes cast in the round, with that two-thirds threshold rounded **up** to a whole number of votes, so five votes cast require four concurrences and four votes cast require three."
        PRD §3.3: "When quorum is met, no veto stands, the supermajority is reached, and the bank additionally has a work plan in either `SUBMITTED` or `APPROVED` status, the prospectus goes `UNDER_REVIEW → APPROVED`; if no such work plan exists the finalisation is rejected with `ERR_WORK_PLAN_MISSING`."
        PRD §3.3: "Every one of the three finalisation branches records the chair's opaque caller identity into `decision_recorded_by` and stamps `decided_at` with the clock; those two side effects are common to approval, revision request and rejection alike."
        Design: Difficulty/boundary_precision_check/irt_quorum_exactly_three_votes_finalizes_review
        """
        set_clock(CLOCK_EPOCH)
        world = setup_bank_under_review(
            work_plan_state="SUBMITTED", vote_positions=["CONCUR", "ABSTAIN"]
        )
        prospectus_id = world["prospectus"]["id"]
        validate_success(
            api_client.create_prospectus_vote(
                prospectus_id, create_vote_payload("CONCUR"), world["member_headers"][2]
            ),
            201,
        )

        decided = validate_success(
            api_client.finalize_prospectus_review(prospectus_id, world["chair_headers"]),
            200,
        )
        assert decided["status"] == "APPROVED", (
            "2 concurrences of 3 votes meets the rounded-up two-thirds threshold"
        )
        assert decided["decision_recorded_by"] == world["chair_headers"]["X-User-ID"], (
            "the chair's opaque operator identifier is recorded on the decision"
        )
        assert decided["decided_at"].startswith("2026-08-01T00:00:00"), (
            f"decided_at is stamped from the clock, got {decided['decided_at']}"
        )
        assert decided["revision_round"] == 1, (
            "an approval does not open a further revision round"
        )

    def test_approval_leaves_the_bank_in_prospectus_review_and_frozen(self):
        """Closing the review round approves the prospectus without moving the
        bank, which stays in PROSPECTUS_REVIEW and therefore FROZEN.

        PRD §2.8: "If the bank's `status` is `DRAFT`, `PROSPECTUS_REVIEW`, `SUSPENDED` or `CLOSED`, the posture is `FROZEN`."
        PRD §3.3: "When quorum is met, no veto stands, the supermajority is reached, and the bank additionally has a work plan in either `SUBMITTED` or `APPROVED` status, the prospectus goes `UNDER_REVIEW → APPROVED`; if no such work plan exists the finalisation is rejected with `ERR_WORK_PLAN_MISSING`."
        Design: Difficulty/boundary_precision_check/irt_quorum_exactly_three_votes_finalizes_review
        """
        set_clock(CLOCK_EPOCH)
        world = setup_bank_under_review(
            work_plan_state="SUBMITTED", vote_positions=["CONCUR", "ABSTAIN"]
        )
        prospectus_id = world["prospectus"]["id"]
        validate_success(
            api_client.create_prospectus_vote(
                prospectus_id, create_vote_payload("CONCUR"), world["member_headers"][2]
            ),
            201,
        )
        validate_success(
            api_client.finalize_prospectus_review(prospectus_id, world["chair_headers"]),
            200,
        )

        bank = bank_state(world)
        assert bank["status"] == "PROSPECTUS_REVIEW", (
            "only instrument execution moves the bank out of PROSPECTUS_REVIEW"
        )
        assert bank["sales_posture"] == "FROZEN", (
            "a bank in PROSPECTUS_REVIEW is frozen by the first branch of the ladder"
        )
