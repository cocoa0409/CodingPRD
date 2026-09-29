"""Credit arithmetic and the money that follows it: the fifteen-minute floor
under the minimum-credit gate, the attendance clamp, the cap truncation
waterfall, roster lateness, carryover forfeiture, out-of-state conversion, the
audit sample pool and the late-fee ladder.

Each test builds every record it needs through the declared endpoints, because
the board's data is empty when the test begins.
"""
from datetime import datetime, timezone

from test_helpers import (
    affirm_and_certify,
    audit_action,
    create_accredited_provider,
    create_attorney,
    create_code_verified_course,
    create_credit_record_payload,
    create_cycle,
    create_self_certified_course,
    credit_allocation_entry,
    determine_claim,
    file_credit_record,
    file_reciprocity_claim,
    file_roster,
    make_attorney_headers,
    open_audit,
    read_attorney,
    read_course,
    read_credit_record,
    read_cycle,
    read_cycle_summary,
    read_provider,
    roster_entry,
    run_sweep,
    set_clock,
    setup_earned_minutes,
    validate_error,
    validate_paginated,
    validate_success,
)

FULL_PERIOD_START = "2026-01-01T00:00:00Z"
FULL_PERIOD_END = "2028-01-01T00:00:00Z"


def as_instant(value):
    """Reads an ISO 8601 UTC timestamp, so a pinned literal and the rendered
    value compare as the same instant however many fractional digits it
    carries."""
    assert isinstance(value, str), f"expected an ISO 8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_same_instant(actual, expected, label):
    assert as_instant(actual) == as_instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


def attorney_on_a_full_period(**overrides):
    """One attorney on the register with one full 24-month period."""
    attorney = create_attorney(**overrides)
    cycle = create_cycle(attorney["id"], FULL_PERIOD_START, FULL_PERIOD_END)
    return attorney, cycle


def count_credit_records(api, headers, attorney_id):
    """The number of credit records the register holds for one attorney."""
    response = api.list_credit_records(headers, params={"attorney_id": attorney_id})
    _, meta = validate_paginated(response)
    return meta["total_count"]


def test_thirty_credited_minutes_clear_the_minimum_credit_gate(api, board_headers):
    """PRD §3.5: "First, the attended figure is clamped: it is the smaller of the claim's `attended_minutes` and the course's `total_minutes`, so a claim for more time than the course contains earns no bonus."
    PRD §3.5: "Then, working through the four categories in the pinned order `ETHICS`, `TECHNOLOGY`, `BIAS_ELIMINATION`, `GENERAL`, each category's raw entitlement is that category's allocated minutes multiplied by the clamped attended figure and divided by the course's `total_minutes` — kept as an exact rational value, never rounded at this step, and taken as zero when the course has no allocation in that category."
    PRD §3.5: "Each raw entitlement is then rounded **down** to the nearest whole multiple of 15 minutes, and the four results are written to `credited_ethics_minutes`, `credited_technology_minutes`, `credited_bias_minutes` and `credited_general_minutes`."
    PRD §3.5: "Only after all four have been individually rounded down are they added together to give `credited_minutes`."
    PRD §3.5: "Once the sum is known, a floor applies: a claim whose `credited_minutes` comes to less than 30 minutes is not worth recording, and the request is rejected with `ERR_BELOW_MINIMUM_CREDIT`."
    PRD §3.5: "A `LIVE_IN_PERSON` course always yields `LIVE`."

    Design: Corner/calculations/the_minimum_credit_gate_is_measured_after_the_fifteen_minute_floor
    """
    provider = create_accredited_provider(provider_type="LAW_SCHOOL")
    course = create_code_verified_course(
        provider,
        600,
        "2026-03-02T09:00:00Z",
        credit_allocations=[credit_allocation_entry("GENERAL", 600)],
    )
    attorney, cycle = attorney_on_a_full_period()

    payload = create_credit_record_payload(
        attorney["id"],
        course["id"],
        verification_method="ATTENDANCE_CODE",
        attendance_code=course["attendance_code"],
        attended_minutes=30,
        completion_date="2026-03-02T09:00:00Z",
        certificate_reference=None,
    )
    response = api.create_credit_record(payload, make_attorney_headers(attorney["id"]))
    record = validate_success(response, expected_status=201)

    assert record["credited_general_minutes"] == 30, (
        "30 minutes of a 600-minute all-general course entitles 30 general minutes, "
        f"which is already a whole quarter hour, got {record['credited_general_minutes']}"
    )
    assert record["credited_minutes"] == 30, (
        "the four floored figures sum to 30 credited minutes, which meets the floor, "
        f"got {record['credited_minutes']}"
    )
    assert record["status"] == "VERIFIED", (
        f"a matching attendance code verifies the record on filing, got {record['status']}"
    )
    assert record["effective_format"] == "LIVE", (
        f"a LIVE_IN_PERSON course always yields LIVE, got {record['effective_format']}"
    )

    reread = read_cycle(cycle["id"])
    assert reread["earned_countable_minutes"] == 30, (
        f"the period counts the 30 credited minutes, got {reread['earned_countable_minutes']}"
    )
    assert reread["earned_live_minutes"] == 30, (
        f"the 30 minutes travel as live minutes, got {reread['earned_live_minutes']}"
    )


def test_twenty_nine_attended_minutes_fall_below_the_minimum_credit_gate(api, board_headers):
    """PRD §3.5: "Each raw entitlement is then rounded **down** to the nearest whole multiple of 15 minutes, and the four results are written to `credited_ethics_minutes`, `credited_technology_minutes`, `credited_bias_minutes` and `credited_general_minutes`."
    PRD §3.5: "Only after all four have been individually rounded down are they added together to give `credited_minutes`."
    PRD §3.5: "Once the sum is known, a floor applies: a claim whose `credited_minutes` comes to less than 30 minutes is not worth recording, and the request is rejected with `ERR_BELOW_MINIMUM_CREDIT`."

    Design: Corner/calculations/the_minimum_credit_gate_is_measured_after_the_fifteen_minute_floor
    """
    provider = create_accredited_provider(provider_type="LAW_SCHOOL")
    course = create_code_verified_course(
        provider,
        600,
        "2026-03-02T09:00:00Z",
        credit_allocations=[credit_allocation_entry("GENERAL", 600)],
    )
    attorney, cycle = attorney_on_a_full_period()

    payload = create_credit_record_payload(
        attorney["id"],
        course["id"],
        verification_method="ATTENDANCE_CODE",
        attendance_code=course["attendance_code"],
        attended_minutes=29,
        completion_date="2026-03-02T09:00:00Z",
        certificate_reference=None,
    )
    response = api.create_credit_record(payload, make_attorney_headers(attorney["id"]))
    validate_error(response, "ERR_BELOW_MINIMUM_CREDIT")

    assert count_credit_records(api, board_headers, attorney["id"]) == 0, (
        "a claim rejected by the minimum-credit floor leaves no credit record behind"
    )
    reread = read_cycle(cycle["id"])
    assert reread["earned_countable_minutes"] == 0, (
        "29 attended minutes floor to 15 credited minutes, below the 30-minute floor, "
        f"so the period earns nothing, got {reread['earned_countable_minutes']}"
    )


def test_attended_minutes_above_the_course_length_are_clamped_before_proration(
    api, board_headers
):
    """PRD §3.5: "First, the attended figure is clamped: it is the smaller of the claim's `attended_minutes` and the course's `total_minutes`, so a claim for more time than the course contains earns no bonus."
    PRD §3.5: "Then, working through the four categories in the pinned order `ETHICS`, `TECHNOLOGY`, `BIAS_ELIMINATION`, `GENERAL`, each category's raw entitlement is that category's allocated minutes multiplied by the clamped attended figure and divided by the course's `total_minutes` — kept as an exact rational value, never rounded at this step, and taken as zero when the course has no allocation in that category."
    PRD §3.5: "Only after all four have been individually rounded down are they added together to give `credited_minutes`."

    Design: Corner/calculations/attended_minutes_above_the_course_length_are_clamped_before_proration
    """
    provider = create_accredited_provider()
    course = create_code_verified_course(
        provider,
        600,
        "2026-04-01T09:00:00Z",
        credit_allocations=[
            credit_allocation_entry("ETHICS", 180),
            credit_allocation_entry("GENERAL", 420),
        ],
    )
    attorney, cycle = attorney_on_a_full_period()

    payload = create_credit_record_payload(
        attorney["id"],
        course["id"],
        verification_method="ATTENDANCE_CODE",
        attendance_code=course["attendance_code"],
        attended_minutes=900,
        completion_date="2026-04-01T09:00:00Z",
        certificate_reference=None,
    )
    response = api.create_credit_record(payload, make_attorney_headers(attorney["id"]))
    record = validate_success(response, expected_status=201)

    assert record["credited_ethics_minutes"] == 180, (
        "the clamped attended figure is the course's own 600 minutes, so the ethics "
        f"allocation is credited in full at 180 minutes, got {record['credited_ethics_minutes']}"
    )
    assert record["credited_general_minutes"] == 420, (
        "the general allocation is credited in full at 420 minutes, got "
        f"{record['credited_general_minutes']}"
    )
    assert record["credited_minutes"] == 600, (
        "a claim for more time than the course contains earns no bonus, so the credit "
        f"stops at the course's 600 minutes, got {record['credited_minutes']}"
    )

    reread = read_cycle(cycle["id"])
    assert reread["earned_countable_minutes"] == 600, (
        f"the period counts 600 minutes, not 900, got {reread['earned_countable_minutes']}"
    )
    assert reread["earned_ethics_minutes"] == 180, (
        f"the period counts 180 ethics minutes, got {reread['earned_ethics_minutes']}"
    )


def setup_truncated_self_study_period():
    """One period holding a 720-minute on-demand session and a later
    360-minute self-study session, so the second session runs out of non-live
    room and has to be truncated."""
    return setup_earned_minutes(
        [
            {
                "total_minutes": 720,
                "presented_at": "2026-01-02T09:00:00Z",
                "delivery_format": "ON_DEMAND",
                "credit_allocations": [credit_allocation_entry("GENERAL", 720)],
                "completion_date": "2026-02-01T00:00:00Z",
            },
            {
                "total_minutes": 360,
                "presented_at": "2026-01-03T09:00:00Z",
                "delivery_format": "SELF_STUDY",
                "credit_allocations": [
                    credit_allocation_entry("ETHICS", 90),
                    credit_allocation_entry("TECHNOLOGY", 60),
                    credit_allocation_entry("BIAS_ELIMINATION", 60),
                    credit_allocation_entry("GENERAL", 150),
                ],
                "completion_date": "2026-03-01T00:00:00Z",
            },
        ],
        period_start=FULL_PERIOD_START,
        period_end=FULL_PERIOD_END,
    )


def test_a_capped_record_loses_general_minutes_first_and_ethics_minutes_last(
    api, board_headers
):
    """PRD §3.6: "The records in the variant's input set are processed in ascending order of `completion_date`, breaking ties by ascending `created_at`."
    PRD §3.5: "An `ON_DEMAND` course always yields `ON_DEMAND`, and a `SELF_STUDY` course always yields `SELF_STUDY`."
    PRD §3.6: "A record whose `effective_format` is `ON_DEMAND` has its room reduced to the smallest of its own credited minutes, the 720-minute on-demand allowance (12 credit hours per cycle) less on-demand minutes already used, and the same 900-minute non-live allowance less non-live minutes already used."
    PRD §3.6: "A record whose `effective_format` is `SELF_STUDY` has its room reduced to the smallest of three quantities: its own credited minutes, the 360-minute self-study allowance (6 credit hours per cycle) less self-study minutes already used, and the 900-minute non-live allowance (15 credit hours per cycle) less non-live minutes already used."
    PRD §3.6: "That shortfall is absorbed in the pinned bucket order `GENERAL`, then `BIAS_ELIMINATION`, then `TECHNOLOGY`, then `ETHICS`: for each bucket in that order, the amount taken is the smaller of the shortfall still outstanding and that record's credited minutes in that bucket; the bucket contributes its credited minutes *less* the amount taken to the cycle's running total for that category; and the outstanding shortfall drops by the amount taken."
    PRD §3.6: "After the record is accounted for, the run adds its countable minutes to the overall countable total; adds them to the self-study and non-live allowances used when its `effective_format` is `SELF_STUDY`; adds them to the on-demand and non-live allowances used when its `effective_format` is `ON_DEMAND`; adds them to the running live total when its `effective_format` is `LIVE`; and adds them to the reciprocity allowance used when its `source` is `RECIPROCITY`."

    Design: Corner/calculations/a_capped_record_loses_general_minutes_first_and_ethics_minutes_last
    """
    _, _, cycle, _, records = setup_truncated_self_study_period()
    on_demand_record = read_credit_record(records[0]["id"])
    self_study_record = read_credit_record(records[1]["id"])

    assert on_demand_record["effective_format"] == "ON_DEMAND", (
        f"an ON_DEMAND course yields ON_DEMAND, got {on_demand_record['effective_format']}"
    )
    assert on_demand_record["countable_minutes"] == 720, (
        "the earlier on-demand session fits inside both the 720-minute on-demand "
        "allowance and the 900-minute non-live allowance, got "
        f"{on_demand_record['countable_minutes']}"
    )

    assert self_study_record["effective_format"] == "SELF_STUDY", (
        f"a SELF_STUDY course yields SELF_STUDY, got {self_study_record['effective_format']}"
    )
    assert self_study_record["credited_minutes"] == 360, (
        f"the self-study session credits its whole 360 minutes, got "
        f"{self_study_record['credited_minutes']}"
    )
    assert self_study_record["countable_minutes"] == 180, (
        "only 180 minutes of non-live allowance are left when the self-study session "
        f"is reached, got {self_study_record['countable_minutes']}"
    )

    reread = read_cycle(cycle["id"])
    assert reread["earned_countable_minutes"] == 900, (
        "720 on-demand minutes plus 180 self-study minutes exhaust the non-live "
        f"allowance at 900 minutes, got {reread['earned_countable_minutes']}"
    )
    assert reread["earned_ethics_minutes"] == 90, (
        "the 180-minute shortfall is absorbed from general and then "
        "elimination-of-bias, so all 90 ethics minutes survive, got "
        f"{reread['earned_ethics_minutes']}"
    )
    assert reread["earned_technology_minutes"] == 60, (
        "the shortfall is exhausted before it reaches technology, so all 60 technology "
        f"minutes survive, got {reread['earned_technology_minutes']}"
    )
    assert reread["earned_bias_minutes"] == 30, (
        "the shortfall takes all 150 general minutes and then 30 of the 60 "
        "elimination-of-bias minutes, leaving 30, got "
        f"{reread['earned_bias_minutes']}"
    )
    assert reread["earned_live_minutes"] == 0, (
        "neither an on-demand nor a self-study session yields live minutes, got "
        f"{reread['earned_live_minutes']}"
    )


def test_a_truncated_period_reports_its_bucket_consumption_and_final_shortfalls(
    api, board_headers
):
    """PRD §3.6: "Four bucket fields report the **provisional** run's cap consumption: `self_study_used_minutes`, `on_demand_used_minutes`, `nonlive_used_minutes` and `reciprocity_used_minutes`."
    PRD §3.6: "The final run supplies `projected_final_total_minutes`, `projected_final_ethics_minutes`, `projected_final_technology_minutes`, `projected_final_bias_minutes`, `projected_final_live_minutes`, `projected_final_deficiency_total_minutes`, `projected_final_deficiency_ethics_minutes`, `projected_final_deficiency_technology_minutes` and `projected_final_deficiency_bias_minutes`."
    PRD §3.6: "Two counts close the payload: `records_counted` is the size of the provisional input set, and `records_excluded` is the number of the cycle's records in `REJECTED` or `VOIDED`."
    PRD §3.6: "The four shortfalls are then: the total shortfall, being `required_total_minutes` less the effective total, floored at zero; the ethics shortfall, being `required_ethics_minutes` less the effective ethics figure, floored at zero; the technology shortfall, being `required_technology_minutes` less `earned_technology_minutes`, floored at zero; and the bias shortfall, being `required_bias_minutes` less `earned_bias_minutes`, floored at zero."
    PRD §3.6: "A record whose `effective_format` is `SELF_STUDY` has its room reduced to the smallest of three quantities: its own credited minutes, the 360-minute self-study allowance (6 credit hours per cycle) less self-study minutes already used, and the 900-minute non-live allowance (15 credit hours per cycle) less non-live minutes already used."

    Design: Corner/calculations/a_capped_record_loses_general_minutes_first_and_ethics_minutes_last
    """
    _, _, cycle, _, _ = setup_truncated_self_study_period()
    summary = read_cycle_summary(cycle["id"])

    assert summary["self_study_used_minutes"] == 180, (
        "only the 180 truncated self-study minutes consume the self-study allowance, "
        f"got {summary['self_study_used_minutes']}"
    )
    assert summary["on_demand_used_minutes"] == 720, (
        f"the on-demand session consumes 720 minutes, got {summary['on_demand_used_minutes']}"
    )
    assert summary["nonlive_used_minutes"] == 900, (
        "the two sessions together exhaust the 900-minute non-live allowance, got "
        f"{summary['nonlive_used_minutes']}"
    )
    assert summary["projected_final_total_minutes"] == 900, (
        "both records are verified, so the final picture also counts 900 minutes, got "
        f"{summary['projected_final_total_minutes']}"
    )
    assert summary["projected_final_deficiency_total_minutes"] == 900, (
        "1800 required minutes less 900 counted minutes leaves a 900-minute shortfall, "
        f"got {summary['projected_final_deficiency_total_minutes']}"
    )
    assert summary["projected_final_deficiency_ethics_minutes"] == 90, (
        "180 required ethics minutes less the 90 that survived leaves 90, got "
        f"{summary['projected_final_deficiency_ethics_minutes']}"
    )
    assert summary["projected_final_deficiency_technology_minutes"] == 0, (
        "60 required technology minutes are met in full, got "
        f"{summary['projected_final_deficiency_technology_minutes']}"
    )
    assert summary["projected_final_deficiency_bias_minutes"] == 90, (
        "120 required elimination-of-bias minutes less the 30 that survived leaves 90, "
        f"got {summary['projected_final_deficiency_bias_minutes']}"
    )
    assert summary["records_counted"] == 2, (
        f"both records sit in the provisional input set, got {summary['records_counted']}"
    )
    assert summary["records_excluded"] == 0, (
        f"no record is rejected or voided, got {summary['records_excluded']}"
    )


def setup_three_late_filers():
    """Three attorneys whose 2024-2026 periods all missed their filing
    deadline, holding respectively no shortfall, a five-hour shortfall and a
    six-hour shortfall."""
    provider = create_accredited_provider()
    ladder = [
        {
            "total_minutes": 1800,
            "presented_at": "2025-03-03T09:00:00Z",
            "credit_allocations": [
                credit_allocation_entry("ETHICS", 180),
                credit_allocation_entry("TECHNOLOGY", 60),
                credit_allocation_entry("BIAS_ELIMINATION", 120),
                credit_allocation_entry("GENERAL", 1440),
            ],
        },
        {
            "total_minutes": 1500,
            "presented_at": "2025-04-01T09:00:00Z",
            "credit_allocations": [
                credit_allocation_entry("ETHICS", 180),
                credit_allocation_entry("TECHNOLOGY", 60),
                credit_allocation_entry("BIAS_ELIMINATION", 120),
                credit_allocation_entry("GENERAL", 1140),
            ],
        },
        {
            "total_minutes": 1500,
            "presented_at": "2025-05-01T09:00:00Z",
            "credit_allocations": [
                credit_allocation_entry("ETHICS", 180),
                credit_allocation_entry("TECHNOLOGY", 60),
                credit_allocation_entry("BIAS_ELIMINATION", 60),
                credit_allocation_entry("GENERAL", 1200),
            ],
        },
    ]
    filers = []
    for session in ladder:
        _, attorney, cycle, _, _ = setup_earned_minutes(
            [session],
            provider=provider,
            period_start="2024-01-01T00:00:00Z",
            period_end="2026-01-01T00:00:00Z",
            attorney_overrides={
                "admission_date": "2004-01-01T00:00:00Z",
                "compliance_group": "GROUP_1",
            },
        )
        filers.append((attorney, cycle))
    return provider, filers


def test_the_late_fee_tier_ladder_steps_at_zero_five_and_six_deficient_hours(
    api, board_headers
):
    """PRD §3.9: "Step three totals the shortfall across all four requirements: the total deficiency plus the ethics, technology and elimination-of-bias deficiencies, added together as one number of minutes."
    PRD §3.9: "Step four converts that to whole hours, rounding **up** — one minute short is one deficient hour."
    PRD §3.9: "Step five picks a base amount from the rounded hour count: zero hours gives 15000 cents, one to five hours gives 25000, six to fifteen gives 40000, and sixteen or more gives 60000."
    PRD §3.9: "Step six adds a surcharge of 2500 cents for each deficient hour, counting at most twenty hours."
    PRD §3.9: "Observe that a perfectly compliant but late filer still pays: zero deficient hours yields the 15000-cent base plus a zero surcharge, because the fee is for filing late, not for being short."
    PRD §3.9: "That assessment raises the attorney's `outstanding_fee_cents` by its `amount_cents`, and the run's `delinquencies_issued` and `late_fees_assessed_cents` tallies rise by one and by that amount respectively."

    Design: Corner/calculations/the_late_fee_tier_ladder_steps_at_zero_five_and_six_deficient_hours
    """
    _, filers = setup_three_late_filers()
    sweep = run_sweep()

    assert sweep["delinquencies_issued"] == 3, (
        "all three periods missed their 2026-02-01 filing deadline, got "
        f"{sweep['delinquencies_issued']}"
    )
    assert sweep["late_fees_assessed_cents"] == 107500, (
        "15000 plus 37500 plus 55000 cents of late fees, got "
        f"{sweep['late_fees_assessed_cents']}"
    )

    balances = [read_attorney(attorney["id"])["outstanding_fee_cents"]
                for attorney, _ in filers]

    assert balances[0] == 15000, (
        "a period with no shortfall at all still pays the 15000-cent base with a zero "
        f"surcharge, got {balances[0]}"
    )
    assert balances[1] == 37500, (
        "a 300-minute total shortfall is five deficient hours: the 25000-cent base "
        f"plus five surcharges of 2500 cents, got {balances[1]}"
    )
    assert balances[2] == 55000, (
        "a 300-minute total shortfall plus a 60-minute elimination-of-bias shortfall is "
        "360 minutes, six deficient hours: the 40000-cent base plus six surcharges of "
        f"2500 cents, got {balances[2]}"
    )


def test_each_late_fee_is_stamped_by_the_run_that_assessed_it(api, board_headers):
    """PRD §3.9: "The first: a cycle whose `administrative_status` is `GOOD_STANDING`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `filing_deadline` is at or before the run's `as_of`, moves `administrative_status` from `GOOD_STANDING` to `DELINQUENT`."
    PRD §3.9: "Its `delinquent_since` is set to the run's `as_of` — not to the deadline it missed — and a `FeeAssessment` is created with `fee_type` `LATE_COMPLIANCE`, the cycle's `attorney_id` and `cycle_id`, an `assessed_by_sweep_id` naming this run, `status` of `ASSESSED` and an `amount_cents` derived as described below."
    PRD §3.9: "`cycles_examined` counts the cycles the run considered."
    PRD §3.9: "Every course in `APPROVED` whose `expires_at` is at or before `as_of` moves to `EXPIRED`, and `courses_expired` counts them."
    PRD §3.9: "The second enforcement step: a cycle whose `administrative_status` is `DELINQUENT`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `delinquent_since` is at least 60 days before the run's `as_of`, moves `administrative_status` from `DELINQUENT` to `ADMIN_SUSPENDED`."
    PRD §2.4: "Before the clock is ever set it reads exactly `2026-08-01T00:00:00Z`."

    Design: Corner/calculations/the_late_fee_tier_ladder_steps_at_zero_five_and_six_deficient_hours
    """
    _, filers = setup_three_late_filers()
    sweep = run_sweep()

    assert sweep["cycles_examined"] == 3, (
        f"the run considered all three periods, got {sweep['cycles_examined']}"
    )
    assert sweep["courses_expired"] == 3, (
        "all three live sessions ended in 2025, so each course expires in this run, got "
        f"{sweep['courses_expired']}"
    )
    assert sweep["suspensions_issued"] == 0, (
        "each period only became delinquent in this very run, so none has been "
        f"delinquent for 60 days, got {sweep['suspensions_issued']}"
    )

    expected_amounts = [15000, 37500, 55000]
    for (attorney, cycle), expected in zip(filers, expected_amounts):
        reread = read_cycle(cycle["id"])
        assert reread["administrative_status"] == "DELINQUENT", (
            "a period past its filing deadline moves to DELINQUENT, got "
            f"{reread['administrative_status']}"
        )
        assert_same_instant(
            reread["delinquent_since"],
            "2026-08-01T00:00:00Z",
            "delinquent_since, which is the run's evaluation instant",
        )
        assert reread["credit_status"] == "OPEN", (
            "delinquency touches only the filing dimension, so the credit dimension "
            f"stays OPEN, got {reread['credit_status']}"
        )

        response = api.list_fee_assessments(
            board_headers,
            params={"attorney_id": attorney["id"], "fee_type": "LATE_COMPLIANCE"},
        )
        assessments, meta = validate_paginated(response)
        assert meta["total_count"] == 1, (
            "one late-compliance assessment per delinquent period, got "
            f"{meta['total_count']}"
        )
        assessment = assessments[0]
        assert assessment["amount_cents"] == expected, (
            f"the assessment must carry {expected} cents, got {assessment['amount_cents']}"
        )
        assert assessment["status"] == "ASSESSED", (
            f"a new assessment lands on ASSESSED, got {assessment['status']}"
        )
        assert assessment["cycle_id"] == cycle["id"], (
            "the assessment names the period it was raised against, got "
            f"{assessment['cycle_id']}"
        )
        assert assessment["assessed_by_sweep_id"] == sweep["id"], (
            "the assessment names the run that created it, got "
            f"{assessment['assessed_by_sweep_id']}"
        )


def setup_period_with_one_pending_record():
    """One 2024-2026 period holding 1200 verified minutes and a further 600
    minutes still waiting for board adjudication."""
    provider, attorney, cycle, _, _ = setup_earned_minutes(
        [
            {
                "total_minutes": 1200,
                "presented_at": "2025-06-02T09:00:00Z",
                "credit_allocations": [
                    credit_allocation_entry("ETHICS", 180),
                    credit_allocation_entry("TECHNOLOGY", 60),
                    credit_allocation_entry("BIAS_ELIMINATION", 120),
                    credit_allocation_entry("GENERAL", 840),
                ],
            }
        ],
        period_start="2024-01-01T00:00:00Z",
        period_end="2026-01-01T00:00:00Z",
        attorney_overrides={
            "admission_date": "2004-01-01T00:00:00Z",
            "compliance_group": "GROUP_1",
        },
    )
    certificate_course = create_self_certified_course(
        provider,
        title="Certificate Session",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=600,
        presented_at="2025-07-02T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[credit_allocation_entry("GENERAL", 600)],
    )
    pending = file_credit_record(
        attorney,
        certificate_course["id"],
        attended_minutes=600,
        completion_date="2025-07-02T09:00:00Z",
    )
    return attorney, cycle, pending


def test_pending_minutes_lower_the_provisional_picture_but_not_the_final_one(
    api, board_headers
):
    """PRD §3.5: "With `CERTIFICATE` or `AFFIRMATION`, the record is created in `PENDING_VERIFICATION` and waits: a certificate claim waits for board adjudication, an affirmation claim waits for the attorney's own sworn affirmation."
    PRD §3.6: "The **provisional** variant includes the cycle's records in `PENDING_VERIFICATION` and `VERIFIED`."
    PRD §3.6: "The **final** variant includes only those in `VERIFIED`."
    PRD §3.6: "Because the provisional and final pictures can diverge sharply, the cycle summary read runs the algorithm *both* ways over the same stored data and returns the two results side by side without persisting anything."
    PRD §3.6: "The provisional run supplies `provisional_total_minutes`, `provisional_ethics_minutes`, `provisional_technology_minutes`, `provisional_bias_minutes`, `provisional_live_minutes`, `provisional_deficiency_total_minutes` and `provisional_deficiency_ethics_minutes`."
    PRD §3.6: "The final run supplies `projected_final_total_minutes`, `projected_final_ethics_minutes`, `projected_final_technology_minutes`, `projected_final_bias_minutes`, `projected_final_live_minutes`, `projected_final_deficiency_total_minutes`, `projected_final_deficiency_ethics_minutes`, `projected_final_deficiency_technology_minutes` and `projected_final_deficiency_bias_minutes`."
    PRD §3.6: "Two counts close the payload: `records_counted` is the size of the provisional input set, and `records_excluded` is the number of the cycle's records in `REJECTED` or `VOIDED`."

    Design: Corner/calculations/pending_verification_minutes_lower_the_provisional_picture_but_never_the_late_fee
    """
    _, cycle, pending = setup_period_with_one_pending_record()

    assert pending["status"] == "PENDING_VERIFICATION", (
        f"a certificate claim waits for adjudication, got {pending['status']}"
    )

    summary = read_cycle_summary(cycle["id"])
    assert summary["provisional_total_minutes"] == 1800, (
        "the provisional picture counts the pending 600 minutes alongside the verified "
        f"1200, got {summary['provisional_total_minutes']}"
    )
    assert summary["provisional_deficiency_total_minutes"] == 0, (
        "1800 provisional minutes meet the 1800-minute requirement, got "
        f"{summary['provisional_deficiency_total_minutes']}"
    )
    assert summary["provisional_deficiency_ethics_minutes"] == 0, (
        "the verified session already carries the 180 required ethics minutes, got "
        f"{summary['provisional_deficiency_ethics_minutes']}"
    )
    assert summary["projected_final_total_minutes"] == 1200, (
        "the final picture drops the pending record, leaving 1200 minutes, got "
        f"{summary['projected_final_total_minutes']}"
    )
    assert summary["projected_final_deficiency_total_minutes"] == 600, (
        "1800 required minutes less 1200 verified minutes leaves 600, got "
        f"{summary['projected_final_deficiency_total_minutes']}"
    )
    assert summary["projected_final_deficiency_ethics_minutes"] == 0, (
        "the ethics floor is met even in the final picture, got "
        f"{summary['projected_final_deficiency_ethics_minutes']}"
    )
    assert summary["records_counted"] == 2, (
        "both the verified and the pending record sit in the provisional input set, got "
        f"{summary['records_counted']}"
    )
    assert summary["records_excluded"] == 0, (
        f"no record is rejected or voided, got {summary['records_excluded']}"
    )


def test_a_pending_record_never_reduces_the_late_fee(api, board_headers):
    """PRD §3.9: "Step two runs the credit application in its final variant — `VERIFIED` records only — substituting that effective figure for `carryover_in_general_minutes`."
    PRD §3.9: "Records still in `PENDING_VERIFICATION` never reduce a late fee."
    PRD §3.9: "Step three totals the shortfall across all four requirements: the total deficiency plus the ethics, technology and elimination-of-bias deficiencies, added together as one number of minutes."
    PRD §3.9: "Step four converts that to whole hours, rounding **up** — one minute short is one deficient hour."
    PRD §3.9: "Step five picks a base amount from the rounded hour count: zero hours gives 15000 cents, one to five hours gives 25000, six to fifteen gives 40000, and sixteen or more gives 60000."
    PRD §3.9: "Step six adds a surcharge of 2500 cents for each deficient hour, counting at most twenty hours."
    PRD §3.9: "The same derivation is exposed, without persisting anything, as the `projected_late_fee_cents` field of the cycle summary read described in §3.6."
    PRD §3.9: "That assessment raises the attorney's `outstanding_fee_cents` by its `amount_cents`, and the run's `delinquencies_issued` and `late_fees_assessed_cents` tallies rise by one and by that amount respectively."

    Design: Corner/calculations/pending_verification_minutes_lower_the_provisional_picture_but_never_the_late_fee
    """
    attorney, cycle, _ = setup_period_with_one_pending_record()

    summary = read_cycle_summary(cycle["id"])
    assert summary["projected_late_fee_cents"] == 65000, (
        "the fee is priced on the 600-minute final shortfall: ten deficient hours give "
        "the 40000-cent base plus ten surcharges of 2500 cents, got "
        f"{summary['projected_late_fee_cents']}"
    )

    sweep = run_sweep()
    assert sweep["delinquencies_issued"] == 1, (
        f"the one period past its deadline is billed, got {sweep['delinquencies_issued']}"
    )
    assert sweep["late_fees_assessed_cents"] == 65000, (
        "the pending 600 minutes do not soften the fee, got "
        f"{sweep['late_fees_assessed_cents']}"
    )
    assert read_attorney(attorney["id"])["outstanding_fee_cents"] == 65000, (
        "the assessment raises the attorney's balance by its own amount"
    )
    assert read_cycle(cycle["id"])["administrative_status"] == "DELINQUENT", (
        "the period moves to DELINQUENT"
    )


AUDIT_WINDOW_START = "2025-03-05T09:00:00Z"
AUDIT_WINDOW_END = "2025-06-05T09:00:00Z"


def register_on_demand_course(provider, title, presented_at):
    """One on-demand course of the sponsor's own catalogue, approved on filing,
    so it sits in the sampling pool."""
    return create_self_certified_course(
        provider,
        title=title,
        delivery_format="ON_DEMAND",
        total_minutes=180,
        presented_at=presented_at,
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[credit_allocation_entry("GENERAL", 180)],
    )


def setup_audit_pool_on_the_window_boundaries():
    """A sponsor whose catalogue straddles both ends of an audit window: one
    course on each endpoint and one course a second outside each endpoint."""
    provider = create_accredited_provider()
    on_start = register_on_demand_course(provider, "Window Start", AUDIT_WINDOW_START)
    on_end = register_on_demand_course(provider, "Window End", AUDIT_WINDOW_END)
    before_start = register_on_demand_course(
        provider, "One Second Early", "2025-03-05T08:59:59Z"
    )
    after_end = register_on_demand_course(
        provider, "One Second Late", "2025-06-05T09:00:01Z"
    )
    audit = open_audit(
        provider["id"],
        audit_period_start=AUDIT_WINDOW_START,
        audit_period_end=AUDIT_WINDOW_END,
    )
    return provider, audit, on_start, on_end, before_start, after_end


def test_the_audit_pool_includes_both_ends_of_its_closed_window(api, board_headers):
    """PRD §3.9: "It also captures `risk_score_at_open`: the provider's risk score computed at that moment and **frozen** onto the audit row, never refreshed afterwards even as the provider's live `risk_score` moves."
    PRD §3.9: "The delinquency rate is `attendance_reports_late_count` divided by `attendance_reports_total_count`, where the denominator is treated as one whenever the stored count is zero, so a provider that has filed nothing has a delinquency rate of zero rather than an undefined one."
    PRD §3.9: "The complaint rate is `substantiated_complaint_count` divided by three, capped at 1.0 — three substantiated complaints saturate the term."
    PRD §3.9: "The finding rate is `audit_findings_count` divided by a denominator that depends on the variant below, again capped at 1.0."
    PRD §3.9: "The staleness rate measures how long it has been since anyone looked: the anchor is `last_audit_closed_at` when that field is set, and otherwise `accreditation_term_start`; if the anchor is still null the staleness rate is 1.0 outright, and otherwise it is the number of months between the anchor and the current logical instant divided by 24, capped at 1.0."
    PRD §3.9: "`risk_score` is then the delinquency rate weighted at 0.35, plus the complaint rate weighted at 0.30, plus the finding rate weighted at 0.25, plus the staleness rate weighted at 0.10, and the sum is rounded half-up to two decimal places."
    PRD §3.9: "The eligible pool is the audited provider's courses whose `status` is `APPROVED`, `EXPIRED` or `SUSPENDED_PENDING_REVIEW` and whose `presented_at` falls inside the audit's closed window, both endpoints included."
    PRD §3.9: "The pool is ordered by `presented_at` ascending and then `created_at` ascending — never by identifier, and never randomly, so the same engagement over the same data always draws the same courses."
    PRD §3.9: "The target size comes from the frozen score in three tiers: ten courses when `risk_score_at_open` is 0.60 or above, five when it is 0.30 or above but below 0.60, and two otherwise."
    PRD §3.9: "`sample_size` is then the smaller of the target and the pool size — a pool smaller than the target simply yields a short sample and is not an error — and `sampled_course_ids` is the identifiers of the first `sample_size` entries of the sorted pool, in that order."
    PRD §3.9: "`DRAW_SAMPLE` moves the audit `OPENED → SAMPLED`, and is also legitimately repeatable as a `SAMPLED → SAMPLED` redraw, which is exactly why the version guard exists."

    Design: Corner/calculations/the_audit_pool_is_a_closed_interval_and_a_redraw_recomputes_it_from_scratch
    """
    _, audit, on_start, on_end, before_start, after_end = (
        setup_audit_pool_on_the_window_boundaries()
    )

    assert audit["risk_score_at_open"] == 0.0, (
        "a sponsor with no rosters, no substantiated complaints, no findings and an "
        "accreditation term that started at this very instant scores zero on every "
        f"term, got {audit['risk_score_at_open']}"
    )

    sampled = audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])

    assert sampled["status"] == "SAMPLED", (
        f"DRAW_SAMPLE moves the audit to SAMPLED, got {sampled['status']}"
    )
    assert sampled["sample_size"] == 2, (
        "a frozen score below 0.30 targets two courses, and the pool holds exactly the "
        f"two boundary courses, got {sampled['sample_size']}"
    )
    assert sampled["sampled_course_ids"] == [on_start["id"], on_end["id"]], (
        "both endpoints of the closed window are in the pool, ordered by presented_at "
        f"ascending, got {sampled['sampled_course_ids']}"
    )
    assert before_start["id"] not in sampled["sampled_course_ids"], (
        "a course presented one second before the window start is outside the pool"
    )
    assert after_end["id"] not in sampled["sampled_course_ids"], (
        "a course presented one second after the window end is outside the pool"
    )


def test_an_audit_redraw_recomputes_the_pool_from_scratch(api, board_headers):
    """PRD §3.9: "The pool is ordered by `presented_at` ascending and then `created_at` ascending — never by identifier, and never randomly, so the same engagement over the same data always draws the same courses."
    PRD §3.9: "`sample_size` is then the smaller of the target and the pool size — a pool smaller than the target simply yields a short sample and is not an error — and `sampled_course_ids` is the identifiers of the first `sample_size` entries of the sorted pool, in that order."
    PRD §3.9: "A redraw recomputes the whole list from scratch rather than appending to it, and the provider's `courses_sampled_lifetime` is adjusted by the difference between the new and prior `sample_size` — on a first draw that difference is simply the new sample size."
    PRD §3.9: "`DRAW_SAMPLE` moves the audit `OPENED → SAMPLED`, and is also legitimately repeatable as a `SAMPLED → SAMPLED` redraw, which is exactly why the version guard exists."
    PRD §2.5: "Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity."

    Design: Corner/calculations/the_audit_pool_is_a_closed_interval_and_a_redraw_recomputes_it_from_scratch
    """
    provider, audit, on_start, on_end, _, _ = (
        setup_audit_pool_on_the_window_boundaries()
    )
    first_draw = audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    assert first_draw["sampled_course_ids"] == [on_start["id"], on_end["id"]], (
        f"the first draw takes the two boundary courses, got {first_draw['sampled_course_ids']}"
    )

    set_clock("2026-08-02T00:00:00Z")
    latecomer = register_on_demand_course(
        provider, "Registered Afterwards", AUDIT_WINDOW_START
    )

    redraw = audit_action(first_draw["id"], "DRAW_SAMPLE", first_draw["version"])

    assert redraw["status"] == "SAMPLED", (
        f"a redraw is a SAMPLED to SAMPLED transition, got {redraw['status']}"
    )
    assert redraw["sample_size"] == 2, (
        f"the target is still two courses, got {redraw['sample_size']}"
    )
    assert redraw["sampled_course_ids"] == [on_start["id"], latecomer["id"]], (
        "the new course shares the window's opening instant and was inserted later, so "
        "it sorts second and displaces the course presented three months later, got "
        f"{redraw['sampled_course_ids']}"
    )
    assert on_end["id"] not in redraw["sampled_course_ids"], (
        "the redraw is computed from scratch, so the previously sampled course is no "
        "longer in the sample"
    )
    assert read_provider(provider["id"])["courses_sampled_lifetime"] == 2, (
        "the lifetime tally moves by the difference between the new and the prior "
        "sample size, which is zero here"
    )
    assert redraw["version"] == 3, (
        "the audit was created at version 1 and each of the two draws mutated it once, "
        f"got {redraw['version']}"
    )


def test_a_non_live_surplus_forfeits_the_general_carryover(api, board_headers):
    """PRD §3.8: "The credit application runs in its final variant over `VERIFIED` records only."
    PRD §3.8: "The four deficiency figures of that final run then decide the outcome, and the fork is exhaustive: if the total deficiency is zero **and** all three specialty deficiencies are zero, `credit_status` moves `OPEN → SATISFIED`; if the total deficiency is above zero **or** any one specialty deficiency is above zero, `credit_status` moves `OPEN → DEFICIENT` and the attorney's `open_deficiency_count` rises by one."
    PRD §3.8: "The resulting `earned_countable_minutes`, `earned_ethics_minutes`, `earned_technology_minutes`, `earned_bias_minutes` and `earned_live_minutes` are frozen into the cycle, every credit record in the cycle has its `countable_minutes` rewritten to its final-variant value, and `certified_at` is stamped with the current logical instant."
    PRD §3.8: "Otherwise the general surplus is computed as `earned_countable_minutes` plus `carryover_in_general_minutes` plus `carryover_in_ethics_minutes`, less `required_total_minutes`."
    PRD §3.8: "`carryover_out_general_minutes` is then the smallest of three quantities: the general carryover ceiling of 600 minutes, that surplus floored at zero, and the cycle's `earned_live_minutes`."
    PRD §3.8: "That third term is the substantive constraint — **only live minutes travel forward**."
    PRD §3.8: "The ethics surplus is `earned_ethics_minutes` less `required_ethics_minutes`, and `carryover_out_ethics_minutes` is the smaller of the ethics carryover ceiling of 120 minutes and that surplus floored at zero."
    PRD §2.4: "Before the clock is ever set it reads exactly `2026-08-01T00:00:00Z`."

    Design: Corner/calculations/a_waived_election_and_a_non_live_excess_both_forfeit_the_carryover
    """
    _, attorney, cycle, _, _ = setup_earned_minutes(
        [
            {
                "total_minutes": 720,
                "presented_at": "2025-05-01T09:00:00Z",
                "delivery_format": "ON_DEMAND",
                "credit_allocations": [
                    credit_allocation_entry("ETHICS", 90),
                    credit_allocation_entry("TECHNOLOGY", 60),
                    credit_allocation_entry("BIAS_ELIMINATION", 60),
                    credit_allocation_entry("GENERAL", 510),
                ],
                "completion_date": "2025-06-01T00:00:00Z",
            },
            {
                "total_minutes": 180,
                "presented_at": "2025-06-01T09:00:00Z",
                "delivery_format": "SELF_STUDY",
                "credit_allocations": [credit_allocation_entry("GENERAL", 180)],
                "completion_date": "2025-07-01T00:00:00Z",
            },
        ],
        period_start="2024-01-01T00:00:00Z",
        period_end="2026-01-01T00:00:00Z",
        attorney_overrides={
            "admission_date": "2025-03-15T00:00:00Z",
            "compliance_group": "GROUP_1",
        },
    )

    assert cycle["required_total_minutes"] == 720, (
        "the period is prorated from the month after a 2025-03-15 admission, got "
        f"{cycle['required_total_minutes']}"
    )

    certified = affirm_and_certify(
        cycle["id"], attorney["id"], carryover_election="CARRY_FORWARD"
    )

    assert certified["credit_status"] == "SATISFIED", (
        "900 counted minutes clear a 720-minute requirement and every specialty floor, "
        f"got {certified['credit_status']}"
    )
    assert certified["earned_countable_minutes"] == 900, (
        f"the final run counts 900 minutes, got {certified['earned_countable_minutes']}"
    )
    assert certified["earned_live_minutes"] == 0, (
        "an on-demand session and a self-study session earn no live minutes at all, got "
        f"{certified['earned_live_minutes']}"
    )
    assert_same_instant(
        certified["certified_at"],
        "2026-08-01T00:00:00Z",
        "certified_at, stamped from the logical clock",
    )
    assert certified["carryover_out_general_minutes"] == 0, (
        "the 180-minute surplus is capped by the zero live minutes, so nothing travels "
        f"forward, got {certified['carryover_out_general_minutes']}"
    )
    assert certified["carryover_out_ethics_minutes"] == 0, (
        "90 earned ethics minutes exactly meet the 90-minute prorated ethics floor, so "
        f"the ethics surplus is zero, got {certified['carryover_out_ethics_minutes']}"
    )
    assert certified["administrative_status"] == "GOOD_STANDING", (
        "certification does not touch the filing dimension, got "
        f"{certified['administrative_status']}"
    )


def test_a_waived_election_forfeits_even_a_wholly_live_surplus(api, board_headers):
    """PRD §3.8: "First, two circumstances suppress carryover outright, setting both `carryover_out_general_minutes` and `carryover_out_ethics_minutes` to zero: an election of `WAIVE_CARRYOVER`, or any of the four deficiency figures being above zero."
    PRD §3.8: "When supplied it overwrites whatever the cycle was carrying, so an attorney may change its mind about carryover right up to the moment of filing; when omitted the stored election stands."
    PRD §3.8: "The four deficiency figures of that final run then decide the outcome, and the fork is exhaustive: if the total deficiency is zero **and** all three specialty deficiencies are zero, `credit_status` moves `OPEN → SATISFIED`; if the total deficiency is above zero **or** any one specialty deficiency is above zero, `credit_status` moves `OPEN → DEFICIENT` and the attorney's `open_deficiency_count` rises by one."
    PRD §3.8: "The resulting `earned_countable_minutes`, `earned_ethics_minutes`, `earned_technology_minutes`, `earned_bias_minutes` and `earned_live_minutes` are frozen into the cycle, every credit record in the cycle has its `countable_minutes` rewritten to its final-variant value, and `certified_at` is stamped with the current logical instant."

    Design: Corner/calculations/a_waived_election_and_a_non_live_excess_both_forfeit_the_carryover
    """
    _, attorney, cycle, _, _ = setup_earned_minutes(
        [
            {
                "total_minutes": 1800,
                "presented_at": "2025-02-03T09:00:00Z",
                "credit_allocations": [
                    credit_allocation_entry("ETHICS", 300),
                    credit_allocation_entry("TECHNOLOGY", 60),
                    credit_allocation_entry("BIAS_ELIMINATION", 120),
                    credit_allocation_entry("GENERAL", 1320),
                ],
            },
            {
                "total_minutes": 720,
                "presented_at": "2025-04-07T09:00:00Z",
                "credit_allocations": [credit_allocation_entry("GENERAL", 720)],
            },
        ],
        period_start="2024-01-01T00:00:00Z",
        period_end="2026-01-01T00:00:00Z",
        attorney_overrides={
            "admission_date": "2004-01-01T00:00:00Z",
            "compliance_group": "GROUP_1",
        },
    )

    certified = affirm_and_certify(
        cycle["id"], attorney["id"], carryover_election="WAIVE_CARRYOVER"
    )

    assert certified["carryover_election"] == "WAIVE_CARRYOVER", (
        "the election supplied at certification overwrites the stored one, got "
        f"{certified['carryover_election']}"
    )
    assert certified["credit_status"] == "SATISFIED", (
        "2520 live minutes clear the 1800-minute requirement and every specialty floor, "
        f"got {certified['credit_status']}"
    )
    assert certified["earned_countable_minutes"] == 2520, (
        f"both live sessions count in full, got {certified['earned_countable_minutes']}"
    )
    assert certified["earned_live_minutes"] == 2520, (
        f"every counted minute is a live minute, got {certified['earned_live_minutes']}"
    )
    assert certified["earned_ethics_minutes"] == 300, (
        f"the period earns 300 ethics minutes, got {certified['earned_ethics_minutes']}"
    )
    assert certified["carryover_out_general_minutes"] == 0, (
        "a waived election forfeits the 720-minute live surplus outright, got "
        f"{certified['carryover_out_general_minutes']}"
    )
    assert certified["carryover_out_ethics_minutes"] == 0, (
        "a waived election forfeits the 120-minute ethics surplus too, got "
        f"{certified['carryover_out_ethics_minutes']}"
    )
    assert certified["administrative_status"] == "GOOD_STANDING", (
        "certification does not touch the filing dimension, got "
        f"{certified['administrative_status']}"
    )


ORIGIN_CLAIMS = [
    {
        "origin_jurisdiction": "NY",
        "origin_course_title": "New York Professionalism Update",
        "origin_credit_hours": 2.0,
        "origin_category": "PROFESSIONALISM",
        "completion_date": "2026-02-01T00:00:00Z",
    },
    {
        "origin_jurisdiction": "FL",
        "origin_course_title": "Florida Inclusion In Practice",
        "origin_credit_hours": 1.5,
        "origin_category": "DIVERSITY_INCLUSION",
        "completion_date": "2026-03-01T00:00:00Z",
    },
    {
        "origin_jurisdiction": "TX",
        "origin_course_title": "Texas Civil Practice Survey",
        "origin_credit_hours": 2.0,
        "origin_category": "GENERAL",
        "completion_date": "2026-04-01T00:00:00Z",
    },
]


def setup_three_approved_out_of_state_claims():
    """One attorney with one open period and three approved reciprocity claims,
    one from each of three origin jurisdictions."""
    attorney, cycle = attorney_on_a_full_period(
        admission_date="2004-01-01T00:00:00Z", compliance_group="GROUP_1"
    )
    approved, version_trail = [], []
    for filing in ORIGIN_CLAIMS:
        before = read_attorney(attorney["id"])["version"]
        claim = file_reciprocity_claim(attorney["id"], basis="RECIPROCITY", **filing)
        after = read_attorney(attorney["id"])["version"]
        version_trail.append((before, after))
        approved.append(determine_claim(claim["id"], "APPROVE"))
    return attorney, cycle, approved, version_trail


def test_each_origin_jurisdiction_converts_through_its_own_hour_length(api, board_headers):
    """PRD §3.7: "Approval on the `RECIPROCITY` basis first checks that the `origin_jurisdiction` is one the board has a reciprocal arrangement with — `NY`, `CA`, `TX`, `IL` or `FL`."
    PRD §3.7: "Conversion then accounts for the fact that an "hour" is not the same length everywhere: `NY` and `FL` award credit in 50-minute hours, while `CA`, `TX` and `IL` use 60-minute hours."
    PRD §3.7: "The origin minutes are `origin_credit_hours` multiplied by the origin jurisdiction's hour length, and `converted_minutes` is that product rounded **down** to a whole multiple of 15 minutes."
    PRD §3.7: "Two New York credit hours therefore convert as follows: two hours at 50 minutes each is 100 minutes, and 100 minutes floored to a 15-minute multiple is 90 minutes."
    PRD §3.7: "`converted_category` is the home category the origin label maps onto: `GENERAL` stays `GENERAL`, both `PROFESSIONALISM` and `ETHICS` map to `ETHICS`, `TECHNOLOGY` stays `TECHNOLOGY`, and `DIVERSITY_INCLUSION` maps to `BIAS_ELIMINATION`."
    PRD §3.7: "A new claim is created in `SUBMITTED` with `converted_minutes` at zero, `converted_category` at `GENERAL` and `determination_reason` null, and the act of filing raises the attorney's own `version` by one."

    Design: Corner/calculations/each_origin_jurisdiction_converts_through_its_own_hour_length_and_category_map
    """
    _, _, approved, version_trail = setup_three_approved_out_of_state_claims()
    from_new_york, from_florida, from_texas = approved

    for claim in approved:
        assert claim["status"] == "APPROVED", (
            f"each determined claim moves to APPROVED, got {claim['status']}"
        )

    assert from_new_york["converted_minutes"] == 90, (
        "two New York hours are 100 minutes at 50 minutes each, floored to 90, got "
        f"{from_new_york['converted_minutes']}"
    )
    assert from_new_york["converted_category"] == "ETHICS", (
        "a PROFESSIONALISM label maps onto ETHICS, got "
        f"{from_new_york['converted_category']}"
    )
    assert from_florida["converted_minutes"] == 75, (
        "one and a half Florida hours are 75 minutes at 50 minutes each, already a "
        f"quarter-hour multiple, got {from_florida['converted_minutes']}"
    )
    assert from_florida["converted_category"] == "BIAS_ELIMINATION", (
        "a DIVERSITY_INCLUSION label maps onto BIAS_ELIMINATION, got "
        f"{from_florida['converted_category']}"
    )
    assert from_texas["converted_minutes"] == 120, (
        "two Texas hours are 120 minutes at 60 minutes each, got "
        f"{from_texas['converted_minutes']}"
    )
    assert from_texas["converted_category"] == "GENERAL", (
        f"a GENERAL label stays GENERAL, got {from_texas['converted_category']}"
    )

    for before, after in version_trail:
        assert after == before + 1, (
            f"filing a claim raises the attorney's own version by one, got {before} -> {after}"
        )


def test_an_approved_reciprocity_claim_cascades_a_verified_live_record(api, board_headers):
    """PRD §3.7: "That record is created already `VERIFIED`, naming the claiming attorney and the covering cycle and carrying no `course_id`, with `source` set to `RECIPROCITY`, `reciprocity_claim_id` pointing back at the claim, `verification_method` recorded as `CERTIFICATE`, and `effective_format` of `LIVE`."
    PRD §3.7: "Its credited minutes for the mapped category equal `converted_minutes`, and its `credited_minutes` equals `converted_minutes` as well, the other three category figures being zero."
    PRD §3.6: "A record whose `source` is `RECIPROCITY` has its room further reduced to the smaller of the room reached so far and the 900-minute reciprocity allowance (15 credit hours per cycle) less reciprocity minutes already used — and note that this narrowing composes with the format narrowing rather than replacing it."
    PRD §3.6: "Four bucket fields report the **provisional** run's cap consumption: `self_study_used_minutes`, `on_demand_used_minutes`, `nonlive_used_minutes` and `reciprocity_used_minutes`."
    PRD §3.6: "The four shortfalls are then: the total shortfall, being `required_total_minutes` less the effective total, floored at zero; the ethics shortfall, being `required_ethics_minutes` less the effective ethics figure, floored at zero; the technology shortfall, being `required_technology_minutes` less `earned_technology_minutes`, floored at zero; and the bias shortfall, being `required_bias_minutes` less `earned_bias_minutes`, floored at zero."
    PRD §3.6: "After the record is accounted for, the run adds its countable minutes to the overall countable total; adds them to the self-study and non-live allowances used when its `effective_format` is `SELF_STUDY`; adds them to the on-demand and non-live allowances used when its `effective_format` is `ON_DEMAND`; adds them to the running live total when its `effective_format` is `LIVE`; and adds them to the reciprocity allowance used when its `source` is `RECIPROCITY`."

    Design: Corner/calculations/each_origin_jurisdiction_converts_through_its_own_hour_length_and_category_map
    """
    attorney, cycle, approved, _ = setup_three_approved_out_of_state_claims()

    response = api.list_credit_records(
        board_headers, params={"attorney_id": attorney["id"]}
    )
    records, meta = validate_paginated(response)
    assert meta["total_count"] == 3, (
        f"each approved claim cascades one credit record, got {meta['total_count']}"
    )
    claim_ids = {claim["id"] for claim in approved}
    for record in records:
        assert record["status"] == "VERIFIED", (
            f"a cascaded record is born VERIFIED, got {record['status']}"
        )
        assert record["source"] == "RECIPROCITY", (
            f"its source is RECIPROCITY, got {record['source']}"
        )
        assert record["verification_method"] == "CERTIFICATE", (
            f"its verification_method is CERTIFICATE, got {record['verification_method']}"
        )
        assert record["effective_format"] == "LIVE", (
            f"its effective_format is LIVE, got {record['effective_format']}"
        )
        assert record["reciprocity_claim_id"] in claim_ids, (
            "the record points back at the claim that created it, got "
            f"{record['reciprocity_claim_id']}"
        )

    reread = read_cycle(cycle["id"])
    assert reread["earned_ethics_minutes"] == 90, (
        f"the New York conversion lands in ethics, got {reread['earned_ethics_minutes']}"
    )
    assert reread["earned_bias_minutes"] == 75, (
        "the Florida conversion lands in elimination-of-bias, got "
        f"{reread['earned_bias_minutes']}"
    )
    assert reread["earned_technology_minutes"] == 0, (
        "no claim converts into technology, got "
        f"{reread['earned_technology_minutes']}"
    )
    assert reread["earned_countable_minutes"] == 285, (
        "90 plus 75 plus 120 converted minutes all sit well inside the 900-minute "
        f"reciprocity allowance, got {reread['earned_countable_minutes']}"
    )
    assert reread["earned_live_minutes"] == 285, (
        "every cascaded record is live, got "
        f"{reread['earned_live_minutes']}"
    )

    summary = read_cycle_summary(cycle["id"])
    assert summary["reciprocity_used_minutes"] == 285, (
        "all 285 counted minutes consume the reciprocity allowance, got "
        f"{summary['reciprocity_used_minutes']}"
    )
    assert summary["projected_final_deficiency_technology_minutes"] == 60, (
        "the 60-minute technology floor is untouched by these conversions, got "
        f"{summary['projected_final_deficiency_technology_minutes']}"
    )


ROSTER_SESSION_DATE = "2026-08-01T09:00:00Z"
ROSTER_DUE_AT = "2026-08-31T09:00:00Z"


def setup_two_roster_sessions():
    """A sponsor with two 360-minute roster-verified sessions on the same day —
    one in person, one webcast — and one attorney enrolled in a period that
    covers them."""
    provider = create_accredited_provider()
    in_person = create_self_certified_course(
        provider,
        title="In Person Session",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=360,
        presented_at=ROSTER_SESSION_DATE,
        attendance_verification_method="ROSTER",
        credit_allocations=[credit_allocation_entry("GENERAL", 360)],
    )
    webcast = create_self_certified_course(
        provider,
        title="Webcast Session",
        delivery_format="LIVE_WEBCAST",
        total_minutes=360,
        presented_at=ROSTER_SESSION_DATE,
        attendance_verification_method="ROSTER",
        credit_allocations=[credit_allocation_entry("GENERAL", 360)],
    )
    attorney, cycle = attorney_on_a_full_period(
        admission_date="2004-01-01T00:00:00Z", compliance_group="GROUP_1"
    )
    return provider, in_person, webcast, attorney, cycle


def test_a_roster_filed_on_its_due_instant_is_accepted_on_time(api, board_headers):
    """PRD §3.5: "On acceptance the roster stores `entry_count` (the number of rows supplied), `submitted_at` (the logical instant of acceptance) and `session_end`, which is `session_date` plus the course's `total_minutes` and marks the closed interval the session occupies on the course as a resource."
    PRD §3.5: "The roster's `due_at` is `session_date` plus 30 days, and its hard close is `session_date` plus 90 days."
    PRD §3.5: "A roster arriving at or before `due_at` has `days_late` of 0 and a `status` of `ACCEPTED`."
    PRD §3.5: "`accepted_entry_count` counts the entries that produced a record and `rejected_entry_count` counts the rest, and the two always sum to `entry_count`."
    PRD §2.4: "Day arithmetic — the roster due date, the appeal window, the suspension interval, the grace window, the filing-deadline offsets — is UTC calendar-day arithmetic against the logical clock."

    Design: Corner/calculations/a_roster_filed_one_second_past_its_due_date_costs_a_whole_late_day
    """
    provider, in_person, _, attorney, _ = setup_two_roster_sessions()

    set_clock(ROSTER_DUE_AT)
    roster = file_roster(
        provider["id"],
        in_person["id"],
        ROSTER_SESSION_DATE,
        [roster_entry(attorney["bar_number"], 360)],
    )

    assert_same_instant(
        roster["due_at"], ROSTER_DUE_AT, "due_at, which is the session date plus 30 days"
    )
    assert_same_instant(
        roster["submitted_at"], ROSTER_DUE_AT, "submitted_at, the instant of acceptance"
    )
    assert roster["days_late"] == 0, (
        "a roster arriving exactly on its due instant is not late at all, got "
        f"{roster['days_late']}"
    )
    assert roster["status"] == "ACCEPTED", (
        f"a roster arriving at or before due_at is ACCEPTED, got {roster['status']}"
    )
    assert roster["entry_count"] == 1, (
        f"one row was supplied, got {roster['entry_count']}"
    )
    assert roster["accepted_entry_count"] == 1, (
        "the single entry names a registered attorney with a covering period, so it "
        f"produced a record, got {roster['accepted_entry_count']}"
    )
    assert roster["rejected_entry_count"] == 0, (
        f"no entry was skipped, got {roster['rejected_entry_count']}"
    )
    assert_same_instant(
        roster["session_end"],
        "2026-08-01T15:00:00Z",
        "session_end, which is the session date plus the course's 360 minutes",
    )


def test_a_roster_one_second_past_its_due_instant_costs_a_whole_late_day(
    api, board_headers
):
    """PRD §3.5: "The roster's `due_at` is `session_date` plus 30 days, and its hard close is `session_date` plus 90 days."
    PRD §3.5: "A roster arriving after `due_at` but at or before the hard close has `days_late` set to the number of days from `due_at` to now, rounded **up** so that any part of a day counts as a whole day, and a `status` of `ACCEPTED_LATE`; a late acceptance also raises the sponsor's `attendance_reports_late_count` by one, which feeds directly into its risk score."
    PRD §3.5: "Every accepted roster, late or not, raises the sponsor's `attendance_reports_total_count` by one, and the sponsor's `risk_score` is recomputed afterwards."
    PRD §3.9: "The delinquency rate is `attendance_reports_late_count` divided by `attendance_reports_total_count`, where the denominator is treated as one whenever the stored count is zero, so a provider that has filed nothing has a delinquency rate of zero rather than an undefined one."
    PRD §3.9: "`risk_score` is then the delinquency rate weighted at 0.35, plus the complaint rate weighted at 0.30, plus the finding rate weighted at 0.25, plus the staleness rate weighted at 0.10, and the sum is rounded half-up to two decimal places."
    PRD §3.9: "The rounding is applied once, to the weighted sum, and never to the individual terms."
    PRD §3.1: "`risk_score_variant` follows the same fact from the other side, reading `SELF_CERTIFIED_WEIGHTING` exactly when the sponsor is `ACCREDITED` and `REVIEWED_WEIGHTING` in every other state including `APPLIED` and `DENIED`."

    Design: Corner/calculations/a_roster_filed_one_second_past_its_due_date_costs_a_whole_late_day
    """
    provider, in_person, webcast, attorney, _ = setup_two_roster_sessions()

    set_clock(ROSTER_DUE_AT)
    on_time = file_roster(
        provider["id"],
        in_person["id"],
        ROSTER_SESSION_DATE,
        [roster_entry(attorney["bar_number"], 360)],
    )
    assert on_time["status"] == "ACCEPTED", (
        f"the first roster arrives on its due instant, got {on_time['status']}"
    )

    set_clock("2026-08-31T09:00:01Z")
    late = file_roster(
        provider["id"],
        webcast["id"],
        ROSTER_SESSION_DATE,
        [roster_entry(attorney["bar_number"], 360)],
    )

    assert late["days_late"] == 1, (
        "one second past the due instant is part of a day, and part of a day counts as "
        f"a whole day, got {late['days_late']}"
    )
    assert late["status"] == "ACCEPTED_LATE", (
        f"a roster past due_at but inside the hard close is ACCEPTED_LATE, got {late['status']}"
    )

    sponsor = read_provider(provider["id"])
    assert sponsor["attendance_reports_total_count"] == 2, (
        "both acceptances count, late or not, got "
        f"{sponsor['attendance_reports_total_count']}"
    )
    assert sponsor["attendance_reports_late_count"] == 1, (
        f"only the second acceptance was late, got {sponsor['attendance_reports_late_count']}"
    )
    assert round(float(sponsor["risk_score"]), 2) == 0.18, (
        "one late roster out of two weighs 0.35 times one half, which is 0.175, and "
        f"rounds half up to 0.18, got {sponsor['risk_score']}"
    )
    assert sponsor["risk_score_variant"] == "SELF_CERTIFIED_WEIGHTING", (
        "an ACCREDITED sponsor is scored under the self-certified weighting, got "
        f"{sponsor['risk_score_variant']}"
    )


def test_every_accepted_roster_entry_cascades_a_live_verified_record(api, board_headers):
    """PRD §3.5: "Each accepted entry cascades a credit record that is born `VERIFIED`, with `verification_method` set to `ROSTER` and `attendance_report_id` pointing at the roster, which raises the course's `verified_credit_record_count` and triggers a credit-application re-run for that record's owning cycle."
    PRD §3.5: "A `LIVE_IN_PERSON` course always yields `LIVE`."
    PRD §3.5: "A `LIVE_WEBCAST` course yields `LIVE` only when attendance was verified by `ATTENDANCE_CODE` or by `ROSTER` — the two methods that prove someone was actually watching in real time — and otherwise yields `ON_DEMAND`."
    PRD §3.6: "When every record in the input set has been processed, the overall countable total becomes `earned_countable_minutes`, the three specialty running totals become `earned_ethics_minutes`, `earned_technology_minutes` and `earned_bias_minutes`, and the running live total becomes `earned_live_minutes`."

    Design: Corner/calculations/a_roster_filed_one_second_past_its_due_date_costs_a_whole_late_day
    """
    provider, in_person, webcast, attorney, cycle = setup_two_roster_sessions()

    set_clock(ROSTER_DUE_AT)
    file_roster(
        provider["id"],
        in_person["id"],
        ROSTER_SESSION_DATE,
        [roster_entry(attorney["bar_number"], 360)],
    )
    set_clock("2026-08-31T09:00:01Z")
    late = file_roster(
        provider["id"],
        webcast["id"],
        ROSTER_SESSION_DATE,
        [roster_entry(attorney["bar_number"], 360)],
    )

    response = api.list_credit_records(
        board_headers, params={"attorney_id": attorney["id"]}
    )
    records, meta = validate_paginated(response)
    assert meta["total_count"] == 2, (
        f"one record per accepted roster entry, got {meta['total_count']}"
    )
    for record in records:
        assert record["status"] == "VERIFIED", (
            f"a roster-borne record is born VERIFIED, got {record['status']}"
        )
        assert record["verification_method"] == "ROSTER", (
            f"its verification_method is ROSTER, got {record['verification_method']}"
        )
        assert record["effective_format"] == "LIVE", (
            "an in-person session is live, and a webcast verified by roster is live too, "
            f"got {record['effective_format']}"
        )

    assert read_course(webcast["id"])["verified_credit_record_count"] == 1, (
        "the cascade raises the course's verified record count"
    )
    assert late["accepted_entry_count"] == 1, (
        f"the late roster's single entry still produced a record, got {late['accepted_entry_count']}"
    )

    reread = read_cycle(cycle["id"])
    assert reread["earned_countable_minutes"] == 720, (
        f"two 360-minute sessions count in full, got {reread['earned_countable_minutes']}"
    )
    assert reread["earned_live_minutes"] == 720, (
        f"both sessions travel as live minutes, got {reread['earned_live_minutes']}"
    )
