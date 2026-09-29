"""Depth tests for the two multi-stage money formulas.

Both formulas pin the ORDER of their stages: interpretation billing rounds per
session and only then sums, and grant reimbursement selects the surcharge tier
from the base alone before the allocation runs on the post-surcharge total.
Re-ordering either pipeline produces a different integer, which is what these
tests read.
"""

from test_helpers import factories
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    created,
    ok,
)
from test_helpers.fixtures import accept_intake, minimal_world, new_client, set_clock

# ---------------------------------------------------------------------------
# interpretation_rollup_per_session_round_then_sum_off_by_one
# ---------------------------------------------------------------------------


def _setup_interpretation_rollup(api):
    """Four sessions on one U_VISA matter, then the clock moved past their windows.

    Three sessions will be completed and one marked no-show. The sessions are
    scheduled on 2026-09-02 while the clock reads 2026-09-01, and the clock is
    then advanced to 2026-09-03 so both closure guards (clock at or after
    ``scheduled_start_utc`` for COMPLETE, at or after ``scheduled_end_utc`` for
    MARK_NO_SHOW) are satisfied.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=12,
        reserved_detained_slots=2,
        languages=["en", "ht"],
        decider_max_case_load=25,
    )

    # Marie Toussaint speaks Haitian Creole: 'ht' is outside the five common
    # languages, so every 'ht' session carries the 15 percent surcharge.
    client_id = new_client(
        env,
        full_name="Marie Toussaint",
        preferred_language_code="ht",
        country_of_birth_code="HT",
        date_of_birth="1993-07-19",
        household_size=2,
        annual_household_income_cents=1800000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    matter = accept_intake(
        env,
        client_id,
        case_type="U_VISA",
        detained=False,
        statutory_deadline_date="2026-12-01",
    )
    env.set(client_id=client_id, matter_id=matter["id"])

    windows = (
        ("s1_id", "ht", "CONTRACT", "09:00", "10:00"),
        ("s2_id", "ht", "CONTRACT", "11:00", "12:00"),
        ("s3_id", "es", "TELEPHONIC", "13:00", "14:00"),
        ("s4_id", "ht", "CONTRACT", "15:00", "16:00"),
    )
    for key, language, source, start, end in windows:
        session = created(
            api.create_session(
                factories.session_payload(
                    matter["id"],
                    language_code=language,
                    interpreter_source=source,
                    purpose="HEARING_PREP",
                    scheduled_start_utc="2026-09-02T{0}:00.000Z".format(start),
                    scheduled_end_utc="2026-09-02T{0}:00.000Z".format(end),
                ),
                headers=env.director,
            )
        )
        env[key] = session["id"]

    set_clock(api, "2026-09-03T00:00:00.000Z")
    return env


def test_each_completed_session_rounds_its_own_amount_before_any_summing(api):
    """22 actual minutes bills 30, and 9500 x 0.5 x 1.15 == 5462.5 rounds up to 5463.

    The 30-minute floor, the 15-minute block ceiling and the rare-language
    surcharge all act inside a single session, and the half-up rounding happens
    once, on the surcharged product -- not on the rate and the surcharge apart.

    Design: Difficulty/combinatorial_formula/interpretation_rollup_per_session_round_then_sum_off_by_one
    """
    env = _setup_interpretation_rollup(api)

    first = ok(
        api.transition_session(
            env["s1_id"],
            {"action": "COMPLETE", "actual_minutes": 22},
            headers=env.director,
        )
    )
    second = ok(
        api.transition_session(
            env["s2_id"],
            {"action": "COMPLETE", "actual_minutes": 22},
            headers=env.director,
        )
    )
    third = ok(
        api.transition_session(
            env["s3_id"],
            {"action": "COMPLETE", "actual_minutes": 46},
            headers=env.director,
        )
    )

    for row in (first, second):
        assert_fields(row, status="COMPLETED", billed_minutes=30, billable_cents=5463)
    # ceil(46/15) * 15 == 60, and 'es' is a common language so no surcharge.
    assert_fields(third, status="COMPLETED", billed_minutes=60, billable_cents=6200)


def test_matter_rollup_is_the_sum_of_rounded_amounts_and_skips_the_no_show(api):
    """17126, not the 17125 an implementation that sums before rounding reports.

    The two 5462.5 sessions are the whole point: summing them unrounded gives
    10925.0, which lands one cent below the sum of the two rounded amounts. The
    no-show session contributes nothing at all.

    Design: Difficulty/combinatorial_formula/interpretation_rollup_per_session_round_then_sum_off_by_one
    """
    env = _setup_interpretation_rollup(api)

    for key, minutes in (("s1_id", 22), ("s2_id", 22), ("s3_id", 46)):
        ok(
            api.transition_session(
                env[key],
                {"action": "COMPLETE", "actual_minutes": minutes},
                headers=env.director,
            )
        )
    no_show = ok(
        api.transition_session(
            env["s4_id"],
            {"action": "MARK_NO_SHOW", "closure_reason_code": "CLIENT_UNAVAILABLE"},
            headers=env.director,
        )
    )
    assert_fields(no_show, status="NO_SHOW", billed_minutes=0, billable_cents=0)

    matter = env.matter()
    assert matter["interpretation_cost_cents"] == 17126, (
        "expected 5463 + 5463 + 6200 == 17126; got {0} (17125 means the "
        "per-session amounts were summed before rounding)".format(
            matter["interpretation_cost_cents"]
        )
    )


# ---------------------------------------------------------------------------
# grant_reimbursement_tier_from_base_then_largest_remainder_allocation
# ---------------------------------------------------------------------------

_HOUR_ENTRIES = {
    "m1": (12.0, 12.0, 12.0, 12.0, 12.0, 0.01),
    "m2": (12.0, 12.0, 12.0, 12.0, 4.0),
    "m3": (12.0, 12.0, 12.0, 4.01),
}


def _setup_grant_allocation(api):
    """Three matters carrying 60.01 / 52.00 / 40.01 DIRECT hours, created in order.

    One attorney holds the ACTIVE LEAD on all three, so every hour is DIRECT and
    lands on a LEAD assignment. The matters are created M1, M2, M3 so that
    ``created_at`` ascending is the declared tie-break order for the leftover
    cent. Hours arrive in entries of at most 12.00 because larger entries are
    rejected outright.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=12,
        reserved_detained_slots=2,
        decider_max_case_load=10,
    )

    profiles = (
        ("m1", "Client One", "MX", "1985-01-05"),
        ("m2", "Client Two", "HN", "1986-02-06"),
        ("m3", "Client Three", "SV", "1987-03-07"),
    )
    for key, name, country, dob in profiles:
        client_id = new_client(
            env,
            full_name=name,
            preferred_language_code="en",
            country_of_birth_code=country,
            date_of_birth=dob,
            household_size=1,
            annual_household_income_cents=2000000,
            confidentiality_consent_scope="PROGRAM_ONLY",
        )
        matter = accept_intake(
            env, client_id, case_type="ADJUSTMENT_OF_STATUS", detained=False
        )
        assignment = created(
            api.create_assignment(
                factories.assignment_payload(
                    matter["id"],
                    env["atty_a_id"],
                    matter["version"],
                    role_on_case="LEAD",
                ),
                headers=env.director,
            )
        )
        ok(
            api.transition_assignment(
                assignment["id"], {"action": "ACTIVATE"}, headers=env.director
            )
        )
        env[key + "_id"] = matter["id"]
        env["asg_" + key] = assignment["id"]

    for key, entries in (("m1", _HOUR_ENTRIES["m1"]), ("m2", _HOUR_ENTRIES["m2"]),
                         ("m3", _HOUR_ENTRIES["m3"])):
        for hours in entries:
            ok(
                api.log_hours(
                    env["asg_" + key],
                    {
                        "hours": hours,
                        "hours_kind": "DIRECT",
                        "service_date": "2026-09-01",
                    },
                    headers=env.director,
                )
            )

    report = created(
        api.create_grant_report(
            factories.grant_report_payload(
                env["cycle_id"],
                disclosure_level="AGGREGATE_ONLY",
                period_start_date="2026-08-01",
                period_end_date="2026-09-30",
                grant_code="EOIRLOP2027",
            ),
            headers=env.analyst,
        )
    )
    env["report_id"] = report["id"]
    return env


def test_surcharge_tier_is_read_from_the_base_alone_not_from_the_grossed_up_total(api):
    """Base 1900250 sits below the 2,000,000 tier boundary; the total does not.

    Selecting the rate from the base gives 0.06 and a surcharge of 114015. An
    implementation that grosses up first and then re-reads the tier from
    2014265 would charge 0.09 and report 171023.

    Design: Difficulty/combinatorial_formula/grant_reimbursement_tier_from_base_then_largest_remainder_allocation
    """
    env = _setup_grant_allocation(api)

    assert_decimal_equals(env.matter(env["m1_id"])["direct_hours_logged"], "60.01", 2)
    assert_decimal_equals(env.matter(env["m2_id"])["direct_hours_logged"], "52.00", 2)
    assert_decimal_equals(env.matter(env["m3_id"])["direct_hours_logged"], "40.01", 2)

    generated = ok(
        api.transition_grant_report(
            env["report_id"], {"action": "GENERATE"}, headers=env.analyst
        )
    )

    assert_fields(
        generated,
        status="GENERATED",
        generated_at_utc="2026-09-01T00:00:00.000Z",
        cases_served_count=3,
        consent_verified_count=3,
        suppressed_case_count=0,
    )
    # Per matter: round_half_up(12500 * hours) == 750125 + 650000 + 500125.
    assert generated["base_reimbursable_cents"] == 1900250
    assert generated["supervision_surcharge_cents"] == 114015, (
        "expected the 0.06 tier read from base 1900250; got {0} (171023 means "
        "the tier was re-read from the total)".format(
            generated["supervision_surcharge_cents"]
        )
    )
    assert generated["total_reimbursable_cents"] == 2014265
    assert generated["outcomes_summary"]["NOT_YET_DECIDED"] == 3


def test_largest_remainder_hands_the_single_leftover_cent_to_the_earliest_matter(api):
    """Floors sum to 2014264, so exactly one cent must be distributed.

    The ideals are 795132.5 / 689000.0 / 530132.5: two lines tie at remainder
    0.5 and the earlier ``created_at`` takes the cent, so the allocation closes
    on the total and the remainder counter reads 1.

    Design: Difficulty/combinatorial_formula/grant_reimbursement_tier_from_base_then_largest_remainder_allocation
    """
    env = _setup_grant_allocation(api)

    generated = ok(
        api.transition_grant_report(
            env["report_id"], {"action": "GENERATE"}, headers=env.analyst
        )
    )

    assert generated["allocated_line_total_cents"] == 2014265
    assert (
        generated["allocated_line_total_cents"]
        == generated["total_reimbursable_cents"]
    ), "the allocation must close exactly on total_reimbursable_cents"
    assert generated["rounding_remainder_cents"] == 1
    # The conservation identity the allocation sits on top of.
    assert (
        generated["base_reimbursable_cents"]
        + generated["supervision_surcharge_cents"]
        == generated["total_reimbursable_cents"]
    )
