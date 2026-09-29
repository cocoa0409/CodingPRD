"""Derived figures: affinity tiers, rubric means, credited-minute truncation,
attendance penalties, unrounded readiness components, stipend accrual and pricing.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.assertions import (
    assert_four_decimals,
    assert_instant_equals,
    assert_money_cents,
    assert_two_decimals,
)
from test_helpers.constants import CLOCK_INITIAL_UTC
from test_helpers.fixtures import (
    activate_match,
    build_program,
    create_certified_mentor,
    create_cohort,
    create_mentor,
    create_novice,
    create_site,
    define_milestone,
    attainment_for,
    attest_attainment,
    open_observation_cycle,
    post_certify_training,
    propose_match,
    read_match,
    read_mentor,
    read_novice,
    read_readiness,
    read_session,
    schedule_seminar_session,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import (
    ADMIN,
    PAYROLL_PREP,
    PAYROLL_PREP_1,
    make_mentor_headers,
    make_site_lead_headers,
)


class TestSubjectAffinityTier:
    """The adjacency map decides both the tier and the money."""

    def test_subject_match_tier_resolves_adjacent_from_adjacency_map(
        self, api: InductionApiClient
    ):
        """A SCIENCE mentor on a MATH novice is ADJACENT, so activation pins 3600.

        The PRD fixes the map and the three-way resolution: "When the novice's
        `subject_area` is one of the mentor's `subject_endorsements`, the tier is
        `EXACT`. Otherwise, if the novice's subject appears in the adjacency set of
        any endorsement the mentor holds, the tier is `ADJACENT`. Failing both, the
        tier is `CROSS`. The adjacency sets are fixed district policy: `MATH` is
        adjacent to `SCIENCE` and `CTE`; `SCIENCE` to `MATH` and `CTE`; `ELA` to
        `SOCIAL_STUDIES` and `WORLD_LANGUAGE`; `SOCIAL_STUDIES` to `ELA` and
        `WORLD_LANGUAGE`; `SPED` to `ELA` and `MATH`; `WORLD_LANGUAGE` to `ELA` and
        `SOCIAL_STUDIES`; and `CTE` to `MATH` and `SCIENCE`."

        Design: Corner/calculations/subject_match_tier_resolves_adjacent_from_adjacency_map
        """
        site = create_site(api)
        cohort = create_cohort(api)
        mentor = create_certified_mentor(api, site["id"], subject_endorsements=["SCIENCE"])
        novice = create_novice(api, site["id"], cohort["id"], subject_area="MATH")
        match = propose_match(api, novice["id"], mentor["version"], mentor["id"])

        activated = validate_success(
            api.dispose_match(match["id"], f.disposition_payload("ACTIVATE"), ADMIN)
        )
        assert activated["match_status"] == "ACTIVE"
        assert activated["subject_match_tier"] == "ADJACENT", (
            "MATH sits in the adjacency set of SCIENCE, so the tier is neither exact "
            f"nor cross, got {activated['subject_match_tier']}"
        )
        assert activated["site_match"] is True
        assert activated["pinned_stipend_rate_cents_per_hour"] == 3600, (
            "the adjacent rate is pinned, not the exact 4200, got "
            f"{activated['pinned_stipend_rate_cents_per_hour']}"
        )
        assert_instant_equals(activated["activated_at"], CLOCK_INITIAL_UTC, "activated_at")


class TestCompositeRubricScore:
    """The composite is the arithmetic mean of the four dimensions."""

    def test_composite_rubric_score_is_mean_of_four_dimensions(
        self, api: InductionApiClient
    ):
        """Scores of 4, 4, 3 and 2 average to 3.25, which is none of the four values.

        The PRD pins the mean and its precision: "Every write of the feedback
        package recomputes `composite_rubric_score` as the sum of those four rubric
        values divided by four, rounded half up to 2 decimal places, yielding a
        figure between 1.00 and 4.00."

        Design: Corner/calculations/composite_rubric_score_is_mean_of_four_dimensions
        """
        program = build_program(api)
        mentor_headers = make_mentor_headers(program["mentor_id"])
        set_clock(api, "2026-08-04T12:00:00Z")
        cycle = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-03T14:00:00Z",
            "2026-08-03T15:00:00Z",
        )
        get_success_data(
            api.advance_cycle(cycle["id"], f.advance_payload("OBSERVED"), mentor_headers)
        )
        get_success_data(
            api.advance_cycle(
                cycle["id"], f.advance_payload("POST_CONFERENCE"), mentor_headers
            )
        )

        submitted = validate_success(
            api.write_feedback(
                cycle["id"],
                f.feedback_payload(
                    submit=True,
                    growth_area_codes=["INSTRUCTION", "ASSESSMENT"],
                    rubric_scores={
                        "planning": 4,
                        "instruction": 4,
                        "environment": 3,
                        "assessment": 2,
                    },
                ),
                mentor_headers,
            )
        )
        assert_two_decimals(
            submitted["composite_rubric_score"], 3.25, "composite_rubric_score"
        )
        assert submitted["feedback_review_status"] == "SUBMITTED", (
            f"submitting moves the review dimension, got "
            f"{submitted['feedback_review_status']}"
        )
        assert submitted["phase"] == "POST_CONFERENCE", (
            f"but leaves the phase dimension alone, got {submitted['phase']}"
        )
        assert submitted["growth_area_codes"] == ["INSTRUCTION", "ASSESSMENT"], (
            f"the growth areas are stored as supplied, got {submitted['growth_area_codes']}"
        )
        assert submitted["return_count"] == 0, (
            f"nothing has been returned yet, got {submitted['return_count']}"
        )

        assert read_novice(api, program["novice_id"])["documented_observation_cycles"] == 0, (
            "submitting feedback does not document the cycle"
        )


class TestStipendGrossInputSet:
    """The final draft counts verified logs only."""

    def test_stipend_gross_counts_only_verified_logs_in_period(
        self, api: InductionApiClient
    ):
        """A disputed log inside the period contributes nothing to the gross.

        The PRD narrows the draft's input set to verification, not contact date:
        "Only contact logs whose `verification_status` is `VERIFIED` count, on any
        match of that mentor, and only those whose `verified_at` falls inside the
        **closed** interval from `period_start` to `period_end` — a log verified at
        exactly either bound is inside."

        Design: Corner/calculations/stipend_gross_counts_only_verified_logs_in_period
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-04T12:00:00Z")
        verified = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-02T09:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Planning conference on proportional reasoning",
        )
        verify_contact_log(api, verified["id"], lead)
        disputed = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-03T09:00:00Z",
            minutes=45,
            contact_type="CO_PLANNING",
            mentor_id=program["mentor_id"],
            description="Co-planning the unit assessment",
        )
        validate_success(
            api.review_contact_log(
                disputed["id"],
                f.review_payload("DISPUTE", note="Minutes do not match the sign-in sheet"),
                lead,
            )
        )
        set_clock(api, "2026-08-05T00:00:00Z")

        draft = validate_success(
            api.create_disbursement(
                f.disbursement_payload(
                    program["mentor_id"],
                    read_mentor(api, program["mentor_id"])["version"],
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-08-04T23:59:59Z",
                ),
                PAYROLL_PREP,
            ),
            201,
        )
        assert draft["status"] == "DRAFT", (
            f"a new disbursement opens as a draft, got {draft['status']}"
        )
        assert draft["eligible_log_count"] == 1, (
            "only the verified log enters the input set, got "
            f"{draft['eligible_log_count']}"
        )
        assert_money_cents(draft["gross_cents"], 4200, "gross_cents")
        assert_money_cents(draft["adjustment_cents"], 0, "adjustment_cents")
        assert_money_cents(draft["net_cents"], 4200, "net_cents")
        assert draft["prepared_by_user_id"] == PAYROLL_PREP_1, (
            f"the preparer is stamped from the caller, got {draft['prepared_by_user_id']}"
        )
        assert draft["approved_by_user_id"] is None, (
            f"nobody has approved a fresh draft, got {draft['approved_by_user_id']}"
        )


class TestSeminarAttendancePenalty:
    """A flat ten minutes comes off a late arrival before the ratio is formed."""

    def test_late_attendance_applies_ten_minute_penalty(self, api: InductionApiClient):
        """80 late minutes clear the gate and 75 do not, purely because of the penalty.

        The PRD applies the penalty before the division: "A late arrival forfeits a
        flat 10 minutes: the effective minutes are the raw `minutes_attended` less
        that penalty for a `LATE` row and the raw minutes themselves otherwise,
        floored at zero so a novice who arrived 5 minutes into a session and is
        marked late does not go negative. The `credit_ratio` is then the effective
        minutes divided by the session's `scheduled_minutes`, rounded half up to 4
        decimal places."

        Design: Corner/calculations/late_attendance_applies_ten_minute_penalty
        """
        site = create_site(api)
        cohort = create_cohort(api, seminar_sessions_required=2)
        lead = make_site_lead_headers(site["id"])
        novice = create_novice(api, site["id"], cohort["id"])
        first = schedule_seminar_session(
            api,
            cohort["id"],
            1,
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:30:00Z",
            topic="Classroom routines",
        )
        second = schedule_seminar_session(
            api,
            cohort["id"],
            2,
            "2026-08-06T09:00:00Z",
            "2026-08-06T10:30:00Z",
            topic="Formative assessment",
        )

        credited_row = validate_success(
            api.create_attendance(
                f.attendance_payload(first["id"], novice["id"], "LATE", 80), lead
            ),
            201,
        )
        assert_four_decimals(credited_row["credit_ratio"], 0.7778, "credit_ratio")
        assert credited_row["credited"] is True, (
            f"70 effective minutes over 90 clears three-quarters, got "
            f"credited {credited_row['credited']}"
        )

        uncredited_row = validate_success(
            api.create_attendance(
                f.attendance_payload(second["id"], novice["id"], "LATE", 75), lead
            ),
            201,
        )
        assert_four_decimals(uncredited_row["credit_ratio"], 0.7222, "credit_ratio")
        assert uncredited_row["credited"] is False, (
            f"65 effective minutes over 90 falls short, got "
            f"credited {uncredited_row['credited']}"
        )

        stored = validate_success(api.get_attendance(credited_row["id"], ADMIN))
        assert stored["minutes_attended"] == 80, (
            f"the raw minutes are stored unmodified, got {stored['minutes_attended']}"
        )
        assert stored["recorded_by_user_id"] == site["id"], (
            f"the acting lead is recorded, got {stored['recorded_by_user_id']}"
        )

        assert read_session(api, first["id"])["credited_attendance_count"] == 1, (
            "the credited row counts against its session immediately"
        )
        assert read_session(api, second["id"])["credited_attendance_count"] == 0, (
            "the uncredited row counts against nothing"
        )
        assert read_novice(api, novice["id"])["credited_seminar_sessions"] == 0, (
            "neither session has been held, so the novice's counter has not moved yet"
        )


class TestReadinessComponentPrecision:
    """The three components enter the weighted sum unrounded."""

    def test_readiness_components_unrounded_before_weighted_sum(
        self, api: InductionApiClient
    ):
        """100 verified minutes give 7.50, not the 7.65 a pre-rounded component gives.

        The PRD forbids rounding the components: "Seventh, the index is 100
        multiplied by the sum of the contact component weighted by 0.45, the
        observation component weighted by 0.30 and the seminar component weighted
        by 0.25, the total rounded half up to 2 decimal places. The three
        components are *not* rounded before the weighted sum; only the final index
        is rounded."

        Design: Corner/calculations/readiness_components_unrounded_before_weighted_sum
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-04T12:00:00Z")
        log = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-02T09:00:00Z",
            minutes=100,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Extended planning conference on unit design",
        )

        verified = validate_success(
            api.review_contact_log(
                log["id"], f.review_payload("VERIFY", note="Confirmed by the site lead"), lead
            )
        )
        assert verified["verification_status"] == "VERIFIED"
        assert verified["credited_minutes"] == 100, (
            f"a one-on-one counts at full value, got {verified['credited_minutes']}"
        )
        assert_money_cents(verified["stipend_cents"], 7000, "stipend_cents")

        novice = read_novice(api, program["novice_id"])
        assert novice["verified_contact_minutes"] == 100
        assert_two_decimals(novice["readiness_index_live"], 7.50, "readiness_index_live")
        assert novice["readiness_index_live"] != pytest.approx(7.65, abs=0.005), (
            "7.65 is what rounding the contact component to two places first would "
            f"give, got {novice['readiness_index_live']}"
        )

        readiness = read_readiness(api, program["novice_id"])
        assert readiness["contact_component"] == pytest.approx(100 / 600, abs=0.0001), (
            "the contact component is one sixth, got "
            f"{readiness['contact_component']}"
        )
        assert readiness["observation_component"] == pytest.approx(0.0, abs=0.0001)
        assert readiness["seminar_component"] == pytest.approx(0.0, abs=0.0001)
        assert readiness["meets_readiness_gate"] is False, (
            f"7.50 is far below the 85.00 gate, got {readiness['meets_readiness_gate']}"
        )


class TestCreditedMinuteTruncation:
    """The weighted product is truncated before the day ceiling is consulted."""

    def test_credited_minutes_floors_weighted_product_before_day_room(
        self, api: InductionApiClient
    ):
        """A 45-minute debrief weights to 33.75 and credits 33, paying 2310 cents.

        The PRD pins the order and the direction of the truncation: "Second, the
        weighted product is truncated toward zero to a whole number of minutes — a
        50-minute debrief weighted to 37.5 becomes 37, not 38. Third, and only
        then, a per-day ceiling is applied."

        Design: Corner/calculations/credited_minutes_floors_weighted_product_before_day_room
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-04T12:00:00Z")
        log = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-02T09:00:00Z",
            minutes=45,
            contact_type="DEBRIEF",
            mentor_id=program["mentor_id"],
            description="Post-observation debrief on questioning technique",
        )

        verified = validate_success(
            api.review_contact_log(
                log["id"], f.review_payload("VERIFY", note="Confirmed by the site lead"), lead
            )
        )
        assert verified["credited_minutes"] == 33, (
            f"floor(45 * 0.75) is 33 and not 34, got {verified['credited_minutes']}"
        )
        assert_money_cents(verified["stipend_cents"], 2310, "stipend_cents")
        assert verified["rate_tier_at_verification"] == "EXACT", (
            f"the tier is pinned from the match, got {verified['rate_tier_at_verification']}"
        )
        assert_two_decimals(
            verified["cert_multiplier_at_verification"],
            1.00,
            "cert_multiplier_at_verification",
        )
        assert verified["verified_by_user_id"] == program["site_id"], (
            f"the acting lead is stamped as verifier, got {verified['verified_by_user_id']}"
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["verified_contact_minutes"] == 33
        assert_two_decimals(novice["readiness_index_live"], 2.48, "readiness_index_live")
        assert read_mentor(api, program["mentor_id"])["verified_minutes_lifetime"] == 33


class TestCompletionBonusTier:
    """The bonus table is keyed on the rounded base score and the retention outcome."""

    def test_completion_bonus_zero_below_mid_tier(self, api: InductionApiClient):
        """A base of 40.00 with the best retention outcome still earns no bonus.

        The PRD makes the outcome necessary but not sufficient: "Step three looks up
        `retention_bonus` from a tier table keyed on the score *and* the retention
        outcome: a base score at or above 90.00 with a `retention_outcome` of
        `RETAINED_SAME_SITE` earns 5.00; otherwise a base score at or above 75.00
        with a `retention_outcome` of either `RETAINED_SAME_SITE` or
        `RETAINED_DISTRICT` earns 2.50; every other combination earns 0.00."

        Design: Corner/calculations/completion_bonus_zero_below_mid_tier
        """
        program = build_program(api)
        for index, code in enumerate(("IND_ENTRY", "IND_MIDYEAR", "IND_EXIT"), start=1):
            milestone = define_milestone(api, code, index)
            attainment = attainment_for(api, program["novice_id"], milestone["id"])
            attest_attainment(api, attainment["id"])
        validate_success(
            api.record_retention_outcome(
                program["novice_id"], f.retention_outcome_payload("RETAINED_SAME_SITE"), ADMIN
            )
        )

        packet = validate_success(
            api.create_packet(
                f.packet_payload(
                    program["novice_id"], read_novice(api, program["novice_id"])["version"]
                ),
                ADMIN,
            ),
            201,
        )
        assert packet["packet_status"] == "ASSEMBLING", (
            f"a fresh packet opens in ASSEMBLING, got {packet['packet_status']}"
        )
        assert packet["evidence_milestone_count"] == 3, (
            f"all three attained rows count as evidence, got "
            f"{packet['evidence_milestone_count']}"
        )
        assert_two_decimals(packet["base_score"], 40.00, "base_score")
        assert_two_decimals(packet["retention_bonus"], 0.00, "retention_bonus")
        assert_two_decimals(packet["completion_score"], 40.00, "completion_score")
        assert packet["state_file_number"] is None, (
            f"the state has not seen this packet yet, got {packet['state_file_number']}"
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["program_status"] == "COMPLETION_PENDING", (
            f"assembling moves the novice, got {novice['program_status']}"
        )
        assert novice["license_advancement_status"] == "NOT_ELIGIBLE", (
            "milestone evidence does not by itself clear the readiness gate, got "
            f"{novice['license_advancement_status']}"
        )


class TestTrainingHourLedger:
    """Hours accumulate on every posting; the module list does not."""

    def test_training_hour_ledger_dedupes_module_codes(self, api: InductionApiClient):
        """A second FOUNDATIONS credit adds 2.00 hours and no fourth module code.

        The PRD separates the two ledgers explicitly: "Each posted credit is rounded
        half up to 2 decimal places before it is added to the running
        `training_hours_current_cycle`, and the module code is added to
        `training_modules_current_cycle` without duplication, so posting the same
        module twice adds hours but leaves the module list unchanged."

        Design: Corner/calculations/training_hour_ledger_dedupes_module_codes
        """
        site = create_site(api)
        mentor = create_mentor(api, site["id"])
        post_certify_training(api, mentor["id"])
        before = read_mentor(api, mentor["id"])
        assert_two_decimals(
            before["training_hours_current_cycle"], 18.00, "training_hours_current_cycle"
        )
        assert sorted(before["training_modules_current_cycle"]) == [
            "EQUITY",
            "FOUNDATIONS",
            "OBSERVATION_PROTOCOL",
        ], f"three distinct modules so far, got {before['training_modules_current_cycle']}"

        after = get_success_data(
            api.post_training_credit(
                mentor["id"],
                f.training_credit_payload("FOUNDATIONS", 2.00, completed_on="2026-07-20"),
                ADMIN,
            )
        )
        assert_two_decimals(
            after["training_hours_current_cycle"], 20.00, "training_hours_current_cycle"
        )
        assert len(after["training_modules_current_cycle"]) == 3, (
            "the repeated module code is not appended a second time, got "
            f"{after['training_modules_current_cycle']}"
        )
        assert after["training_modules_current_cycle"].count("FOUNDATIONS") == 1, (
            f"FOUNDATIONS appears once, got {after['training_modules_current_cycle']}"
        )
        assert after["certification_status"] == "UNCERTIFIED", (
            "accumulating hours does not certify anybody on its own, got "
            f"{after['certification_status']}"
        )
        assert after["certification_expires_on"] is None, (
            f"and mints no expiry, got {after['certification_expires_on']}"
        )


class TestProvisionalAccrualRunningTotal:
    """Submitted logs move the mentor's accrual and nothing else."""

    def test_provisional_accrual_running_total_across_two_submitted_logs(
        self, api: InductionApiClient
    ):
        """4200 then 7350 accrue while both logs still read zero credited minutes.

        The PRD prices an unverified log from live values: "For a log that is merely
        `SUBMITTED` nothing has been pinned yet, so the tier is read live from the
        match's current `subject_match_tier`, the multiplier is read live from the
        mentor's current `certification_status`, and the credited minutes are
        replaced by the projected figure — the raw minutes scaled by the contact
        type's weight and floored, then capped by whatever room is left in that
        day's ceiling."

        Design: Corner/calculations/provisional_accrual_running_total_across_two_submitted_logs
        """
        program = build_program(api)
        set_clock(api, "2026-08-04T12:00:00Z")
        first = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-02T09:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Planning conference on proportional reasoning",
        )
        assert first["credited_minutes"] == 0, (
            f"a submitted log credits nothing yet, got {first['credited_minutes']}"
        )
        assert_money_cents(first["stipend_cents"], 0, "stipend_cents")
        assert_money_cents(
            read_mentor(api, program["mentor_id"])["stipend_accrued_cents"],
            4200,
            "stipend_accrued_cents after one submitted log",
        )

        second = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-03T09:00:00Z",
            minutes=45,
            contact_type="CO_PLANNING",
            mentor_id=program["mentor_id"],
            description="Co-planning the unit assessment",
        )
        assert second["credited_minutes"] == 0, (
            f"nor does the second, got {second['credited_minutes']}"
        )
        assert_money_cents(second["stipend_cents"], 0, "stipend_cents")
        assert_money_cents(
            read_mentor(api, program["mentor_id"])["stipend_accrued_cents"],
            7350,
            "stipend_accrued_cents after two submitted logs",
        )

        match = read_match(api, program["match_id"])
        assert match["verified_minutes_total"] == 0, (
            "the match's verified ledger only moves on verification, got "
            f"{match['verified_minutes_total']}"
        )
        assert_money_cents(match["accrued_stipend_cents"], 0, "accrued_stipend_cents")
        assert read_novice(api, program["novice_id"])["verified_contact_minutes"] == 0


class TestAutomaticMentorSelection:
    """Subject affinity outranks every later key, including creation order."""

    def test_auto_selection_ranks_exact_tier_above_earlier_created_mentor(
        self, api: InductionApiClient
    ):
        """The last-created MATH mentor beats an earlier ELA and an earlier SCIENCE one.

        The PRD orders the keys and puts affinity first: "Otherwise the candidates
        are ranked, and the single best one wins, by four keys applied in order:
        first, subject affinity, best first — a mentor whose endorsements include
        the novice's `subject_area` outranks one merely holding an adjacent
        endorsement, which in turn outranks one holding neither; second, the lighter
        `active_caseload_count` first; third, the later `certification_expires_on`
        first, so freshly certified mentors are preferred; and fourth, as the final
        tie-break, the earlier `created_at` first."

        Design: Corner/calculations/auto_selection_ranks_exact_tier_above_earlier_created_mentor
        """
        site = create_site(api)
        cohort = create_cohort(api)
        cross = create_certified_mentor(
            api, site["id"], full_name="Ken Osei", subject_endorsements=["ELA"]
        )
        adjacent = create_certified_mentor(
            api, site["id"], full_name="Mira Vance", subject_endorsements=["SCIENCE"]
        )
        exact = create_certified_mentor(
            api, site["id"], full_name="Rosa Alvarez", subject_endorsements=["MATH"]
        )
        novice = create_novice(api, site["id"], cohort["id"], subject_area="MATH")

        match = validate_success(
            api.create_match(
                f.match_payload(
                    novice["id"], read_mentor(api, exact["id"])["version"]
                ),
                ADMIN,
            ),
            201,
        )
        assert match["selection_mode"] == "AUTO_SELECTED", (
            f"omitting mentor_id hands the choice to the policy, got "
            f"{match['selection_mode']}"
        )
        assert match["mentor_id"] == exact["id"], (
            "the exact-affinity mentor wins even though the other two were created "
            f"first, got {match['mentor_id']}"
        )
        assert match["mentor_id"] not in (cross["id"], adjacent["id"])
        assert match["subject_match_tier"] == "EXACT", (
            f"and the recorded tier agrees, got {match['subject_match_tier']}"
        )
        assert match["site_match"] is True
        assert match["match_status"] == "PROPOSED"
        assert read_novice(api, novice["id"])["program_status"] == "MATCHED"


class TestRateTierPinnedPerMatch:
    """One mentor can hold two matches priced at two different tiers."""

    def test_stipend_rate_tier_pinned_per_match_for_one_mentor(
        self, api: InductionApiClient
    ):
        """Identical 60-minute logs pay 4200 on the exact match and 2800 on the cross one.

        The price follows the log's own tier, not the mentor: "The hourly rate comes
        from the log's tier — 4200 cents for `EXACT`, 3600 cents for `ADJACENT`,
        2800 cents for `CROSS` — and is multiplied by the certification multiplier,
        1.00 for a certified mentor and 0.50 otherwise."

        Design: Corner/calculations/stipend_rate_tier_pinned_per_match_for_one_mentor
        """
        site = create_site(api)
        cohort = create_cohort(api)
        lead = make_site_lead_headers(site["id"])
        mentor = create_certified_mentor(api, site["id"], subject_endorsements=["MATH"])
        exact_novice = create_novice(
            api, site["id"], cohort["id"], full_name="Dana Whitfield", subject_area="MATH"
        )
        cross_novice = create_novice(
            api, site["id"], cohort["id"], full_name="Ivo Marek", subject_area="ELA"
        )

        exact_match = propose_match(
            api,
            exact_novice["id"],
            read_mentor(api, mentor["id"])["version"],
            mentor["id"],
        )
        activated_exact = activate_match(api, exact_match["id"])
        assert activated_exact["subject_match_tier"] == "EXACT"
        assert activated_exact["pinned_stipend_rate_cents_per_hour"] == 4200

        cross_match = propose_match(
            api,
            cross_novice["id"],
            read_mentor(api, mentor["id"])["version"],
            mentor["id"],
        )
        activated_cross = activate_match(api, cross_match["id"])
        assert activated_cross["subject_match_tier"] == "CROSS", (
            "ELA is neither a MATH endorsement nor adjacent to one, got "
            f"{activated_cross['subject_match_tier']}"
        )
        assert activated_cross["pinned_stipend_rate_cents_per_hour"] == 2800

        set_clock(api, "2026-08-04T12:00:00Z")
        exact_log = submit_contact_log(
            api,
            exact_match["id"],
            "2026-08-03T09:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            mentor_id=mentor["id"],
        )
        cross_log = submit_contact_log(
            api,
            cross_match["id"],
            "2026-08-03T13:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            mentor_id=mentor["id"],
        )
        exact_verified = verify_contact_log(api, exact_log["id"], lead)
        cross_verified = verify_contact_log(api, cross_log["id"], lead)

        assert exact_verified["credited_minutes"] == 60
        assert cross_verified["credited_minutes"] == 60, (
            "the two logs are identical in every input but their match"
        )
        assert_money_cents(exact_verified["stipend_cents"], 4200, "stipend_cents")
        assert_money_cents(cross_verified["stipend_cents"], 2800, "stipend_cents")
        assert exact_verified["rate_tier_at_verification"] == "EXACT"
        assert cross_verified["rate_tier_at_verification"] == "CROSS"

        assert_money_cents(
            read_match(api, exact_match["id"])["accrued_stipend_cents"],
            4200,
            "accrued_stipend_cents on the exact match",
        )
        assert_money_cents(
            read_match(api, cross_match["id"])["accrued_stipend_cents"],
            2800,
            "accrued_stipend_cents on the cross match",
        )
        final_mentor = read_mentor(api, mentor["id"])
        assert final_mentor["verified_minutes_lifetime"] == 120
        assert_money_cents(
            final_mentor["stipend_accrued_cents"], 7000, "stipend_accrued_cents"
        )
