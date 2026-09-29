"""Counters and rates that are recomputed on write, including the two places where an empty
denominator is answered with a different constant on purpose.
"""
from test_helpers import (
    ADMIN,
    assert_employer_location,
    assert_same_instant,
    certificates_for_server,
    create_employer_account,
    create_jurisdiction,
    employer_location_payload,
    end_assignment,
    get_account,
    get_location,
    get_server,
    get_trainer_row,
    make_employer_admin_headers,
    register_alcohol_server,
    run_class_to_completion,
    set_clock,
    setup_certified_server_at_location,
    setup_training_base,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"
END_CLOCK = "2026-09-01T12:00:00Z"
ONE_LOCATION = [{"location_name": "Alamo Taproom", "annual_premium_cents": 4821734}]


class TestTrainerTeachingMetrics:
    def test_the_pass_rate_ignores_the_ungraded_seat_and_rounds_to_two_decimals(self, api):
        """PRD §3.4: "Over the enrollments on exactly those completed sessions,
        `graded_enrollments_count` is the number sitting in either `PASSED` or `EXAM_FAILED`, and
        `pass_rate_pct` is the count of `PASSED` divided by `graded_enrollments_count`, multiplied
        by 100 and rounded half up to two decimals."
        PRD §3.4: "Cancelled sessions are excluded entirely, and seats sitting in `NO_SHOW`,
        `INCOMPLETE` or `WITHDRAWN` count toward neither the numerator nor the denominator."
        PRD §3.7: "The issuing jurisdiction's `certificates_issued_count` is incremented, and
        `certificate_number` is minted as the jurisdiction's `state_code`, a hyphen, the four-digit
        year of `issued_at`, a hyphen, and the post-increment counter value rendered as five digits
        with leading zeros — so the first certificate ever issued in Texas in 2026 reads
        `TX-2026-00001`."

        Design: Corner/calculations/trainer_pass_rate_counts_only_graded_enrollments_and_rounds_to_two_decimals
        """
        base = setup_training_base(clock=CLOCK)
        ari = register_alcohol_server(base["jurisdiction"]["id"])
        bo = register_alcohol_server(base["jurisdiction"]["id"],
                                     full_name="Bo Nakamura", email="bo@example.com")
        cy = register_alcohol_server(base["jurisdiction"]["id"],
                                     full_name="Cy Alvarez", email="cy@example.com")
        dee = register_alcohol_server(base["jurisdiction"]["id"],
                                      full_name="Dee Whitfield", email="dee@example.com")

        outcome = run_class_to_completion(base, [
            {"server": ari, "raw_correct_count": 34},
            {"server": bo, "raw_correct_count": 28},
            {"server": cy, "raw_correct_count": 27},
            {"server": dee, "raw_correct_count": None},
        ])

        states = [seat["enrollment_state"] for seat in outcome["enrollments"]]
        assert states == ["PASSED", "PASSED", "EXAM_FAILED", "INCOMPLETE"], (
            f"34 and 28 of 40 clear a 70.00 floor while 27 does not, got {states}")
        assert outcome["enrollments"][2]["best_score_pct"] == 67.50
        assert outcome["enrollments"][3]["attempt_count"] == 0
        assert outcome["session"]["passed_count"] == 2
        assert outcome["session"]["session_status"] == "COMPLETED"

        trainer = get_trainer_row(base["trainer"]["id"])
        assert trainer["sessions_taught_count"] == 1
        assert trainer["graded_enrollments_count"] == 3, (
            "the unexamined seat is neither passed nor failed, got "
            f"{trainer['graded_enrollments_count']}")
        assert trainer["pass_rate_pct"] == 66.67, (
            f"two of three is 66.666... rounded half up to 66.67, got {trainer['pass_rate_pct']}")

        assert [row["certificate_number"] for row in certificates_for_server(ari["id"])] == [
            "TX-2026-00001"], "the first enrolled seat is numbered first"
        assert [row["certificate_number"] for row in certificates_for_server(bo["id"])] == [
            "TX-2026-00002"]
        assert certificates_for_server(dee["id"]) == [], (
            "the unexamined seat holds no certificate")


class TestLocationAndAccountRates:
    def test_an_ended_assignment_leaves_the_location_reading_the_empty_constant(self, api):
        """PRD §3.8: "Ending an assignment is the one direct staffing action, available to the
        owning `EmployerAdmin` with an optional `end_reason`, and reachable from either
        `ACTIVE → ENDED` or `WORK_RESTRICTED → ENDED`. Both behave identically:
        `assignment_state` becomes `ENDED` — a terminal state — `ended_at` is stamped from the
        logical clock, the location's `assigned_server_count` falls by one, counts and both rates
        are recomputed and the posture re-thresholded, and stages four and five of the recompute
        chain then run."
        PRD §3.8: "Those metrics are computed from the location's **live** assignments — those
        whose `assignment_state` is `ACTIVE` or `WORK_RESTRICTED`. Assignments in `ENDED` are
        excluded from both numerator and denominator."
        PRD §3.8: "When `assigned_server_count` is zero — an empty location has nothing out of
        compliance — both rates read 100.00."
        PRD §3.8: "The total live headcount is the sum of `assigned_server_count` over the
        account's locations; `account_compliance_rate_pct` is the sum of `compliant_server_count`
        divided by that total, multiplied by 100, rounded half up to two decimals — except that
        when the total live headcount is zero the account rate reads **0.00**, not 100.00."

        Design: Corner/calculations/ended_assignments_leave_both_location_rates_and_the_numerator_untouched
        """
        scenario = setup_certified_server_at_location(
            location_specs=ONE_LOCATION, seat_quantity=0, sponsor_enrollment=False,
            clock=CLOCK)

        set_clock(END_CLOCK)
        ended = end_assignment(scenario["assignment"]["id"],
                               scenario["employer_headers"], end_reason="resigned")
        assert ended["assignment_state"] == "ENDED"
        assert_same_instant(ended["ended_at"], END_CLOCK, "ended_at")
        assert ended["end_reason"] == "resigned"

        location = get_location(scenario["locations"][0]["id"])
        assert location["assigned_server_count"] == 0
        assert location["compliant_server_count"] == 0
        assert location["grace_server_count"] == 0
        assert location["restricted_server_count"] == 0
        assert location["compliance_rate_strict_pct"] == 100.00
        assert location["compliance_rate_grace_inclusive_pct"] == 100.00
        assert location["compliance_posture"] == "COMPLIANT"

        account = get_account(scenario["account"]["id"])
        assert account["account_compliance_rate_pct"] == 0.00, (
            "the account convention for an empty denominator is the opposite of the location "
            f"one, got {account['account_compliance_rate_pct']}")

        assert get_server(scenario["server"]["id"])["work_eligibility"] == "ELIGIBLE", (
            "ending an assignment does not touch the certificate")

        _, live_meta = validate_paginated(api.list_location_server_assignments(
            location["id"], scenario["employer_headers"], {"assignment_state": "ACTIVE"}))
        assert live_meta["total_count"] == 0
        _, all_meta = validate_paginated(api.list_location_server_assignments(
            location["id"], scenario["employer_headers"]))
        assert all_meta["total_count"] == 1, (
            f"the ended row is retained, not deleted, got {all_meta['total_count']}")

    def test_a_brand_new_location_reads_a_hundred_while_its_account_reads_zero(self, api):
        """PRD §3.8: "The jurisdiction's mandate mapping decides the location's
        `training_requirement`: `MANDATED` when the location's `premise_type` appears in the
        jurisdiction's `mandated_tracks`, and `VOLUNTARY` otherwise. A fresh location starts with
        `assigned_server_count`, `compliant_server_count`, `grace_server_count` and
        `restricted_server_count` at zero and both `compliance_rate_strict_pct` and
        `compliance_rate_grace_inclusive_pct` at 100.00. Creation raises the owning account's
        `location_count` by one and then runs stages four and five of the recompute chain."
        PRD §3.8: "The total live headcount is the sum of `assigned_server_count` over the
        account's locations; `account_compliance_rate_pct` is the sum of `compliant_server_count`
        divided by that total, multiplied by 100, rounded half up to two decimals — except that
        when the total live headcount is zero the account rate reads **0.00**, not 100.00."
        PRD §2.8: "**Stage four — account roll-up.** The owning `EmployerAccount` has its
        `location_count` and `account_compliance_rate_pct` recomputed. If
        `dram_shop_discount_status` is `NOT_DOCUMENTED` and the recomputed
        `account_compliance_rate_pct` is at least 80.00, the status advances to `ELIGIBLE`."

        Design: Corner/calculations/empty_rate_constants_diverge_between_a_location_and_its_account
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()
        account = create_employer_account()

        location = validate_success(api.create_employer_location(
            account["id"],
            employer_location_payload(jurisdiction["id"], location_name="Alamo Taproom",
                                      premise_type="ON_PREMISE",
                                      annual_premium_cents=4821734),
            make_employer_admin_headers(account["id"])), 201)
        assert_employer_location(location)
        assert location["training_requirement"] == "MANDATED"
        assert location["assigned_server_count"] == 0
        assert location["compliance_rate_strict_pct"] == 100.00
        assert location["compliance_rate_grace_inclusive_pct"] == 100.00
        assert location["compliance_posture"] == "COMPLIANT"

        rolled_up = get_account(account["id"])
        assert rolled_up["location_count"] == 1
        assert rolled_up["account_compliance_rate_pct"] == 0.00, (
            "the same empty roster reads 100.00 at the location and 0.00 at the account, got "
            f"{rolled_up['account_compliance_rate_pct']}")
        assert rolled_up["dram_shop_discount_status"] == "NOT_DOCUMENTED", (
            "0.00 is below the 80.00 promotion floor, so nothing advances to ELIGIBLE, got "
            f"{rolled_up['dram_shop_discount_status']}")

    def test_a_voluntary_location_publishes_rates_but_no_posture_verdict(self, api):
        """PRD §3.8: "The jurisdiction's mandate mapping decides the location's
        `training_requirement`: `MANDATED` when the location's `premise_type` appears in the
        jurisdiction's `mandated_tracks`, and `VOLUNTARY` otherwise."
        PRD §3.8: "`compliance_posture` is thresholded off the grace-inclusive rate, and only
        where training is legally required. When `training_requirement` is `VOLUNTARY` the posture
        is `NOT_APPLICABLE`."
        PRD §3.8: "Locations can be read individually, listed with filters on
        `employer_account_id`, `state_jurisdiction_id` and `compliance_posture`, and each exposes
        a dashboard returning its `employer_location_id`, `training_requirement`,
        `assigned_server_count`, `compliant_server_count`, `grace_server_count`,
        `restricted_server_count`, `compliance_rate_strict_pct`,
        `compliance_rate_grace_inclusive_pct` and `compliance_posture` exactly as stored."

        Design: Corner/calculations/voluntary_premise_type_makes_the_posture_not_applicable
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction(state_code="NV", mandate_type="CONDITIONAL",
                                           mandated_tracks=["ON_PREMISE"])
        account = create_employer_account(legal_name="Silver State Bottle Shops LLC",
                                          billing_state_code="NV")

        location = validate_success(api.create_employer_location(
            account["id"],
            employer_location_payload(jurisdiction["id"],
                                      location_name="Fremont Bottle Shop",
                                      premise_type="OFF_PREMISE",
                                      annual_premium_cents=250000),
            make_employer_admin_headers(account["id"])), 201)
        assert location["training_requirement"] == "VOLUNTARY", (
            "OFF_PREMISE is absent from the state's mandated tracks, got "
            f"{location['training_requirement']}")
        assert location["compliance_posture"] == "NOT_APPLICABLE", (
            "an unmandated premise gets no verdict at all, got "
            f"{location['compliance_posture']}")
        assert location["compliance_rate_strict_pct"] == 100.00, (
            "the rates are still published, only the posture is withheld")
        assert location["compliance_rate_grace_inclusive_pct"] == 100.00

        rows, meta = validate_paginated(api.list_employer_locations(
            ADMIN, {"compliance_posture": "NOT_APPLICABLE"}))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [location["id"]]
