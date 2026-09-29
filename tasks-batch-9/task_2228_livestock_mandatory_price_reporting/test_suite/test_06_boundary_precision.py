"""Values sitting exactly on a limit, and one unit either side of it.

Four metrics are pinned here: the species head threshold and the flooring that
feeds it, the three confidentiality guidelines at once, the audit materiality
rate as a rounded field, and filing lateness in whole minutes and ceilinged days.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.assertions import (
    assert_clock_stamp,
    assert_determination,
    assert_discrepancy_rates,
    assert_lateness,
    assert_price_statistics,
    assert_registration_number_format,
    assert_report_dimensions,
    assert_report_masked,
    assert_window_ledger,
)
from test_helpers.types import (
    AggregationState,
    AuditCaseStatus,
    AuditFinding,
    BasisVariant,
    DeterminationOutcome,
    DisclosureState,
    RegistrationStatus,
    SubmissionStatus,
    SuppressionReason,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}


def _flat_history(head):
    return {year: head for year in ("2021", "2022", "2023", "2024", "2025")}


def _determined_firm(api, legal_name, plant_code, annual_head_history):
    """One firm, one plant with the given history, determined on the averaged basis."""
    entity = fx.create_entity(api, legal_name=legal_name)
    fx.create_plant(
        api,
        entity["id"],
        plant_code=plant_code,
        annual_head_history=annual_head_history,
    )
    registration = fx.draft_registration(api, entity["id"])
    determined = get_success_data(
        api.determine_registration(registration["id"], u.PROGRAM_ADMIN)
    )
    return registration, determined


def test_01_the_cattle_threshold_comparison_includes_the_floor_value_itself(api):
    """One head below is exempt; exactly at the threshold is mandatory.

    A firm averaging 124,999 head falls outside the program while a firm
    averaging exactly 125,000 falls inside it, and only the obligated one is
    issued a registration number when it is activated.

    PRD §3.2: "The `determination_outcome` is `MANDATORY` when `measured_head` is
    greater than or equal to `threshold_head`, and `EXEMPT` otherwise".

    Design: Difficulty/boundary_precision_check/threshold_head_exactly_at_species_floor
    """
    _below_reg, below = _determined_firm(
        api, "Below Floor Packing", "EST-901", _flat_history(124999)
    )
    at_reg, at_threshold = _determined_firm(
        api, "At Floor Packing", "EST-902", _flat_history(125000)
    )

    assert_determination(below, 124999, 125000, DeterminationOutcome.EXEMPT.value)
    assert below["registration_number"] is None, below

    assert_determination(
        at_threshold, 125000, 125000, DeterminationOutcome.MANDATORY.value
    )

    activated = validate_success(
        api.activate_registration(at_reg["id"], u.PROGRAM_ADMIN)
    )
    assert_registration_number_format(activated["registration_number"], 2026, 1)


def test_02_the_pooled_total_is_floored_once_and_never_rounded_up(api):
    """A pooled quotient of 125,000.4 measures 125,000, not 125,001.

    One head above the threshold measures above it as expected, and a history
    whose five years pool to 625,002 measures the floored 125,000 -- the fraction
    is discarded rather than carried upward.

    PRD §3.2: "The division and the flooring happen once, after pooling; never
    once per plant and never once per year."

    Design: Difficulty/boundary_precision_check/threshold_head_exactly_at_species_floor
    """
    _above_reg, above = _determined_firm(
        api, "Above Floor Packing", "EST-903", _flat_history(125001)
    )
    _floor_reg, floored = _determined_firm(
        api,
        "Fractional Floor Packing",
        "EST-904",
        {
            "2021": 125000,
            "2022": 125000,
            "2023": 125000,
            "2024": 125000,
            "2025": 125002,
        },
    )

    assert_determination(above, 125001, 125000, DeterminationOutcome.MANDATORY.value)

    assert_determination(floored, 125000, 125000, DeterminationOutcome.MANDATORY.value)
    assert floored["measured_head"] != 125001, (
        "625002 pooled over five years floors to 125000"
    )

    for registration in (above, floored):
        assert registration["status"] == RegistrationStatus.DETERMINED.value
        assert registration["basis_variant"] == BasisVariant.FIVE_YEAR_AVERAGE.value


def _report_on_all_three_guideline_limits(api):
    """A computed report sitting exactly on all three confidentiality limits."""
    alpha = fx.alpha_firm(api)
    bravo = fx.bravo_firm(api)
    coop = fx.coop_firm(api)
    window = fx.create_standard_window(api)

    filings = {}
    for key, firm, head, price in (
        ("alpha", alpha, 700, 280.00),
        ("bravo", bravo, 200, 285.00),
        ("coop", coop, 100, 290.00),
    ):
        filings[key] = fx.accepted_filing(
            api,
            firm["entity"]["id"],
            firm["plant"]["id"],
            window["id"],
            lines=[
                f.transaction_payload(
                    head_count=head,
                    avg_net_price_per_cwt=price,
                    avg_carcass_weight_cwt=8.00,
                )
            ],
        )

    report = fx.computed_report(api, window["id"])
    return {"window": window, "filings": filings, "report": report}


def test_03_three_reporters_a_seventy_percent_share_and_a_thousand_head_clear(api):
    """Every guideline comparison is strict, so sitting on the limit passes.

    The count equals the minimum, the largest share equals the ceiling and the
    volume equals the floor, and the review clears the report with every price
    and volume figure intact.

    PRD §3.6: "When no guideline fails, `suppression_reason` stays null,
    `disclosure_state` becomes `CLEARED`, and every price and volume figure
    survives intact."

    Design: Difficulty/boundary_precision_check/reporter_count_exactly_at_confidentiality_minimum
    """
    scene = _report_on_all_three_guideline_limits(api)
    computed = scene["report"]

    assert computed["reporter_count"] == 3, computed
    assert computed["max_reporter_share_pct"] == 70.00, computed
    assert computed["total_head"] == 1000, computed
    assert_price_statistics(computed, 282.00, 280.00, 290.00)

    cleared = validate_success(
        api.disclosure_review_market_report(computed["id"], u.MARKET_ANALYST)
    )
    assert cleared["disclosure_state"] == DisclosureState.CLEARED.value, cleared
    assert cleared["suppression_reason"] is None, cleared
    assert cleared["total_head"] == 1000, cleared
    assert cleared["weighted_average_price_per_cwt"] == 282.00, cleared


def test_04_dropping_one_reporter_below_the_minimum_withholds_the_report(api):
    """At the minimum minus one the count check fires first, and masks selectively.

    Reopening the cooperative's filing stales the aggregate, the recompute reads
    two reporters over 900 head at a 77.78 percent share, and the second review
    withholds for the reporter count even though the share and volume checks are
    failing too -- keeping both counters visible.

    PRD §3.6: "`weighted_average_price_per_cwt`, `price_low_per_cwt`,
    `price_high_per_cwt`, `total_head` and `total_pounds` are all set to null,
    while `reporter_count` and `max_reporter_share_pct` are deliberately
    **retained** so the suppression decision remains auditable."

    Design: Difficulty/boundary_precision_check/reporter_count_exactly_at_confidentiality_minimum
    """
    scene = _report_on_all_three_guideline_limits(api)
    report_id = scene["report"]["id"]
    validate_success(api.disclosure_review_market_report(report_id, u.MARKET_ANALYST))

    fx.reopen_filing(
        api, scene["filings"]["coop"]["id"], "coop withdraws its filing for rework"
    )

    staled = fx.read_report(api, report_id)
    assert_report_dimensions(
        staled, AggregationState.STALE.value, DisclosureState.UNREVIEWED.value
    )

    recomputed = validate_success(
        api.compute_market_report(report_id, u.MARKET_ANALYST)
    )
    assert recomputed["reporter_count"] == 2, recomputed
    assert recomputed["total_head"] == 900, recomputed
    assert recomputed["max_reporter_share_pct"] == 77.78, recomputed
    assert recomputed["weighted_average_price_per_cwt"] == 281.11, recomputed

    withheld = validate_success(
        api.disclosure_review_market_report(report_id, u.MARKET_ANALYST)
    )
    assert_report_masked(
        withheld,
        SuppressionReason.INSUFFICIENT_REPORTERS.value,
        reporter_count=2,
        max_reporter_share_pct=77.78,
    )


def _three_filings_under_audit(api):
    """Three identical 255-head filings, each with a case at a chosen materiality."""
    window = fx.create_standard_window(api)
    filings = {}
    cases = {}
    for key, firm, materiality in (
        ("eq", fx.alpha_firm(api), 2.00),
        ("hi", fx.bravo_firm(api), 2.00),
        ("rnd", fx.coop_firm(api), 2.41),
    ):
        filings[key] = fx.accepted_filing(
            api,
            firm["entity"]["id"],
            firm["plant"]["id"],
            window["id"],
            lines=[
                f.transaction_payload(
                    head_count=255,
                    avg_net_price_per_cwt=280.00,
                    avg_carcass_weight_cwt=8.00,
                )
            ],
        )
        cases[key] = fx.fieldwork_case(
            api, filings[key]["id"], materiality_pct=materiality
        )
    return {"window": window, "filings": filings, "cases": cases}


def test_05_a_rate_equal_to_the_materiality_threshold_is_immaterial(api):
    """Five head short of 250 verified is 2.00 percent, and 2.00 is not material.

    The strict comparison lets the equal case reconcile, while one head further
    out gives 2.41 percent against the same 2.00 threshold and is material --
    and the verified figure, not the reported one, is the denominator.

    PRD §3.7: "Each rate is material only when it is **strictly greater** than the
    case's `materiality_pct`; a rate exactly equal to the threshold is immaterial."

    Design: Difficulty/boundary_precision_check/materiality_rate_exactly_at_case_threshold
    """
    scene = _three_filings_under_audit(api)

    at_threshold = fx.finalize_case(api, scene["cases"]["eq"]["id"], 250, 571200.00)
    assert_discrepancy_rates(at_threshold, 2.00, 0.00, AuditFinding.IMMATERIAL.value)
    assert at_threshold["status"] == AuditCaseStatus.RECONCILED.value, at_threshold

    above = fx.finalize_case(api, scene["cases"]["hi"]["id"], 249, 571200.00)
    assert_discrepancy_rates(above, 2.41, 0.00, AuditFinding.MATERIAL_HEAD.value)
    assert above["status"] == AuditCaseStatus.DISCREPANCY.value, above
    assert above["head_discrepancy_rate_pct"] != 2.35, (
        "the denominator is verified_head, not reported_head"
    )


def test_06_the_comparison_happens_on_the_rounded_rate_field(api):
    """A rate of 2.40963 percent rounds to 2.41 and ties with a 2.41 threshold.

    Because the stored rate is the rounded figure, the same six-head deviation
    that is material against 2.00 is immaterial against 2.41 -- and only the
    material case moves its filing out of the window ledger.

    PRD §2.5: "percentage rates (`materiality_pct`, `head_discrepancy_rate_pct`,
    `value_discrepancy_rate_pct`, `max_reporter_share_pct`,
    `max_single_reporter_share_pct`) carry 2 decimals rounded half up".

    Design: Difficulty/boundary_precision_check/materiality_rate_exactly_at_case_threshold
    """
    scene = _three_filings_under_audit(api)

    fx.finalize_case(api, scene["cases"]["eq"]["id"], 250, 571200.00)
    fx.finalize_case(api, scene["cases"]["hi"]["id"], 249, 571200.00)
    rounded = fx.finalize_case(api, scene["cases"]["rnd"]["id"], 249, 571200.00)

    assert rounded["materiality_pct"] == 2.41, rounded
    assert_discrepancy_rates(rounded, 2.41, 0.00, AuditFinding.IMMATERIAL.value)
    assert rounded["status"] == AuditCaseStatus.RECONCILED.value, rounded

    for key, status in (
        ("eq", SubmissionStatus.ACCEPTED.value),
        ("hi", SubmissionStatus.UNDER_CORRECTION.value),
        ("rnd", SubmissionStatus.ACCEPTED.value),
    ):
        filing = fx.read_submission(api, scene["filings"][key]["id"])
        assert filing["status"] == status, filing

    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=510,
        accepted_submission_count=2,
    )


def _four_drafts_awaiting_the_deadline(api):
    """One firm, four plants, four draft filings each carrying 100 head."""
    firm = fx.firm_with_plants(
        api,
        [{"plant_code": "EST-101"}]
        + [
            {
                "plant_code": code,
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
                "boxed_beef_volume_lbs_prior_year": 0,
                "forward_commitment_cap_head": 500,
            }
            for code in ("EST-101B", "EST-101C", "EST-101D")
        ],
        legal_name="Alpha Packing",
    )
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)

    filings = []
    for plant in firm["plants"]:
        filing = fx.draft_filing(api, entity_id, plant["id"], window["id"])
        fx.add_transaction(
            api,
            entity_id,
            filing["id"],
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            ),
        )
        filings.append(filing)

    return {"entity_id": entity_id, "window": window, "filings": filings}


def _file_at(api, entity_id, submission_id, instant):
    fx.set_clock(api, instant)
    return validate_success(
        api.submit_submission(submission_id, u.reporter_agent(entity_id))
    )


def test_07_filing_at_the_deadline_instant_is_on_time_and_one_minute_is_a_day(api):
    """Zero minutes late is not late; one minute late is already one day late.

    Filing exactly at the deadline records no lateness at all, while filing one
    minute past it records a single minute -- which the day count rounds up to a
    whole day rather than down to none.

    PRD §3.5: "`is_late` is true only when `lateness_minutes` is greater than 0,
    and `days_late` is `lateness_minutes` divided by 1440 — the number of minutes
    in a 24-hour day — rounded **up** to the next whole number".

    Design: Difficulty/boundary_precision_check/lateness_minute_and_day_ceiling_boundaries
    """
    scene = _four_drafts_awaiting_the_deadline(api)

    on_time = _file_at(
        api,
        scene["entity_id"],
        scene["filings"][0]["id"],
        k.WINDOW_SUBMISSION_DEADLINE,
    )
    assert_lateness(on_time, lateness_minutes=0, is_late=False, days_late=0)
    assert_clock_stamp(
        on_time["submitted_at"], k.WINDOW_SUBMISSION_DEADLINE, "submitted_at"
    )

    one_minute = _file_at(
        api,
        scene["entity_id"],
        scene["filings"][1]["id"],
        k.DEADLINE_PLUS_ONE_MINUTE,
    )
    assert_lateness(one_minute, lateness_minutes=1, is_late=True, days_late=1)


def test_08_a_full_day_late_is_one_day_and_a_minute_more_is_two(api):
    """Exactly 1440 minutes does not tip the ceiling; 1441 minutes does.

    A filing a full day past the deadline still counts as one day late, the very
    next minute counts as two, and none of these filings puts a single head into
    the window ledger.

    PRD §3.5: "so anything from one minute to a full day late counts as one day
    late and 1441 minutes counts as two"

    Design: Difficulty/boundary_precision_check/lateness_minute_and_day_ceiling_boundaries
    """
    scene = _four_drafts_awaiting_the_deadline(api)

    one_day = _file_at(
        api, scene["entity_id"], scene["filings"][2]["id"], k.DEADLINE_PLUS_ONE_DAY
    )
    assert_lateness(one_day, lateness_minutes=1440, is_late=True, days_late=1)

    over_a_day = _file_at(
        api,
        scene["entity_id"],
        scene["filings"][3]["id"],
        k.DEADLINE_PLUS_ONE_DAY_ONE_MINUTE,
    )
    assert_lateness(over_a_day, lateness_minutes=1441, is_late=True, days_late=2)

    for filing in scene["filings"][2:]:
        assert (
            fx.read_submission(api, filing["id"])["status"]
            == SubmissionStatus.SUBMITTED.value
        )

    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=0,
        accepted_submission_count=0,
    )
