"""Read-only projections, the immutable audit row, resolution order across a nested path, and
the guarantee that a derived value is visible in the very response that produced it.
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_same_instant,
    create_employer_account,
    create_jurisdiction,
    employer_location_payload,
    enroll_server,
    get_account,
    get_enrollment_row,
    get_location,
    get_session,
    is_valid_uuid,
    lock_roster,
    make_alcohol_server_headers,
    make_employer_admin_headers,
    register_alcohol_server,
    server_assignment_payload,
    set_clock,
    setup_certified_server_at_location,
    setup_training_base,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_payload,
)

CLOCK = "2026-08-03T09:00:00Z"
COMPLETION_CLOCK = "2026-08-10T18:30:00Z"
MISSING_LOCATION_ID = "00000000-0000-4000-8000-000000000fff"
ONE_LOCATION = [{"location_name": "Alamo Taproom", "annual_premium_cents": 4821734}]
DASHBOARD_KEYS = (
    "training_requirement",
    "assigned_server_count",
    "compliant_server_count",
    "grace_server_count",
    "restricted_server_count",
    "compliance_rate_strict_pct",
    "compliance_rate_grace_inclusive_pct",
    "compliance_posture",
)


class TestProjectionsOverStoredState:
    def test_the_dashboard_mirrors_the_location_row_it_reads_from(self, api):
        """PRD §3.8: "Locations can be read individually, listed with filters on
        `employer_account_id`, `state_jurisdiction_id` and `compliance_posture`, and each exposes a
        dashboard returning its `employer_location_id`, `training_requirement`,
        `assigned_server_count`, `compliant_server_count`, `grace_server_count`,
        `restricted_server_count`, `compliance_rate_strict_pct`,
        `compliance_rate_grace_inclusive_pct` and `compliance_posture` exactly as stored."
        PRD §2.6: "Read endpoints never recompute time-based state. A location's compliance
        dashboard returns the stored derived values exactly as the last mutation or compliance run
        left them."
        PRD §3.8: "An accepted assignment lands in `ACTIVE` with `restriction_reason` at `NONE`,
        `assigned_at` stamped from the logical clock, and `restricted_at`, `ended_at` and
        `end_reason` unset."
        PRD §2.8: "**Stage four — account roll-up.** The owning `EmployerAccount` has its
        `location_count` and `account_compliance_rate_pct` recomputed. If
        `dram_shop_discount_status` is `NOT_DOCUMENTED` and the recomputed
        `account_compliance_rate_pct` is at least 80.00, the status advances to `ELIGIBLE`."

        Design: Corner/endpoints/compliance_dashboard_projects_the_stored_counters_for_one_compliant_server
        """
        scenario = setup_certified_server_at_location(
            location_specs=ONE_LOCATION, seat_quantity=0, sponsor_enrollment=False,
            clock=CLOCK)
        location_id = scenario["locations"][0]["id"]

        dashboard = validate_success(api.get_location_compliance_dashboard(
            location_id, scenario["employer_headers"]), 200)
        assert dashboard["employer_location_id"] == location_id
        assert dashboard["training_requirement"] == "MANDATED"
        assert dashboard["assigned_server_count"] == 1
        assert dashboard["compliant_server_count"] == 1
        assert dashboard["grace_server_count"] == 0
        assert dashboard["restricted_server_count"] == 0
        assert dashboard["compliance_rate_strict_pct"] == 100.00
        assert dashboard["compliance_rate_grace_inclusive_pct"] == 100.00
        assert dashboard["compliance_posture"] == "COMPLIANT"

        stored = get_location(location_id)
        for key in DASHBOARD_KEYS:
            assert dashboard[key] == stored[key], (
                f"the dashboard projects the stored {key} rather than recomputing it: "
                f"{dashboard[key]} against {stored[key]}")

        account = get_account(scenario["account"]["id"])
        assert account["account_compliance_rate_pct"] == 100.00
        assert account["dram_shop_discount_status"] == "ELIGIBLE", (
            "a rate at or above 80.00 promotes NOT_DOCUMENTED to ELIGIBLE, got "
            f"{account['dram_shop_discount_status']}")

        assert scenario["assignment"]["assignment_state"] == "ACTIVE"
        assert_same_instant(scenario["assignment"]["assigned_at"], COMPLETION_CLOCK,
                            "assigned_at")

    def test_two_runs_with_nothing_due_each_record_their_own_all_zero_row(self, api):
        """PRD §2.4: "One resource family is deliberately leaner. A compliance run is an immutable
        audit record: it carries only `id` and `created_at`. It has no `updated_at` and no
        `version` at all, and those keys must not appear on it."
        PRD §3.9: "A compliance run is the platform's only clock-driven mutation, started by a
        `ProgramAdmin` with no input. It stamps `run_at` from the logical clock and evaluates every
        time comparison against that single instant, working through eight ordered phases and
        recording a counter for each on the returned record."
        PRD §2.6: "Moving the clock forward does **not**, by itself, lapse a credential, expire an
        approval, grace or lapse a certificate, emit a reminder, or restrict a server."

        Design: Corner/endpoints/a_compliance_run_with_nothing_due_records_an_all_zero_immutable_row
        """
        set_clock(CLOCK)
        create_jurisdiction()

        first = validate_success(api.create_compliance_run(ADMIN), 201)
        second = validate_success(api.create_compliance_run(ADMIN), 201)
        assert is_valid_uuid(first["id"]) and is_valid_uuid(second["id"])
        assert first["id"] != second["id"], "each run is its own audit row"

        assert_same_instant(first["run_at"], CLOCK, "run_at")
        for counter in ("trainers_lapsed_count", "approvals_expired_count",
                        "certificates_graced_count", "certificates_lapsed_count",
                        "reminders_sent_count", "assignments_restricted_count",
                        "assignments_restored_count", "locations_recomputed_count",
                        "documents_voided_count"):
            assert first[counter] == 0, (
                f"nothing was due, so {counter} stays at zero, got {first[counter]}")

        assert "version" not in first
        assert "updated_at" not in first

    def test_the_dashboard_and_the_account_show_the_write_that_just_happened(self, api):
        """PRD §2.6: "Everything else — roster counts, the seat-credit ledger, server eligibility
        recomputation, location compliance metrics, account roll-ups, account rate and dram-shop
        document standing — is recomputed synchronously inside whichever request caused the
        change."
        PRD §3.8: "Creation recomputes the location's counts and both rates, re-thresholds the
        posture, and then runs stages four and five of the recompute chain."
        PRD §3.8: "Otherwise it is `COMPLIANT` at 95.00 or above, `AT_RISK` at 80.00 or above but
        below 95.00, and `NON_COMPLIANT` below 80.00."
        PRD §3.8: "The total live headcount is the sum of `assigned_server_count` over the
        account's locations; `account_compliance_rate_pct` is the sum of `compliant_server_count`
        divided by that total, multiplied by 100, rounded half up to two decimals — except that
        when the total live headcount is zero the account rate reads **0.00**, not 100.00."

        Design: Corner/consistency model/derived_compliance_fields_are_visible_in_the_same_response_that_caused_them
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()
        server = register_alcohol_server(jurisdiction["id"], full_name="Bo Nakamura",
                                         email="bo@example.com")
        account = create_employer_account()
        employer_headers = make_employer_admin_headers(account["id"])
        location = validate_success(api.create_employer_location(
            account["id"],
            employer_location_payload(jurisdiction["id"], location_name="Alamo Taproom",
                                      annual_premium_cents=4821734),
            employer_headers), 201)

        assignment = validate_success(api.create_server_assignment(
            location["id"],
            server_assignment_payload(server["id"], role_title="Barback"),
            employer_headers), 201)
        assert assignment["assignment_state"] == "ACTIVE"
        assert_same_instant(assignment["assigned_at"], CLOCK, "assigned_at")

        dashboard = validate_success(api.get_location_compliance_dashboard(
            location["id"], employer_headers), 200)
        assert dashboard["assigned_server_count"] == 1
        assert dashboard["compliant_server_count"] == 0, (
            "an uncertified hire is on the payroll but not compliant")
        assert dashboard["grace_server_count"] == 0
        assert dashboard["restricted_server_count"] == 0
        assert dashboard["compliance_rate_strict_pct"] == 0.00
        assert dashboard["compliance_rate_grace_inclusive_pct"] == 0.00
        assert dashboard["compliance_posture"] == "NON_COMPLIANT"

        rolled_up = validate_success(api.get_employer_account(
            account["id"], employer_headers), 200)
        assert rolled_up["location_count"] == 1
        assert rolled_up["account_compliance_rate_pct"] == 0.00
        assert rolled_up["dram_shop_discount_status"] == "NOT_DOCUMENTED"

        again = validate_success(api.get_location_compliance_dashboard(
            location["id"], employer_headers), 200)
        assert {key: again[key] for key in DASHBOARD_KEYS} == {
            key: dashboard[key] for key in DASHBOARD_KEYS}, (
            "a second read with no intervening write converges on nothing new")
        assert get_account(account["id"])["account_compliance_rate_pct"] == 0.00


class TestResolutionOrderAndRepeatedTransitions:
    def test_the_unresolved_path_identifier_answers_before_the_body_one(self, api):
        """PRD §2.9: "Path identifiers are resolved left to right. A request targeting a nested
        resource fails on the **first** identifier in the path that does not resolve, before any
        deeper identifier is examined, and before any business rule runs."
        PRD §2.9: "`ERR_CREDENTIAL_NOT_FOUND` — an unresolved `Trainer`, `AlcoholServer`,
        `Certificate` or `RegistrySubmission` identifier."
        PRD §2.9: "`ERR_EMPLOYER_NOT_FOUND` — an unresolved `EmployerAccount`,
        `EmployerLocation`, `ServerAssignment` or `DramShopDocument` identifier."
        PRD §2.9: "The body-borne identifiers subject to the same resolution rule are `course_id`,
        `state_jurisdiction_id`, `trainer_id`, `proctor_trainer_id`, `class_session_id`,
        `alcohol_server_id`, `sponsoring_employer_account_id` and `supersedes_course_id`, wherever
        any of them appears in a request payload."

        Design: Corner/endpoints/assignment_link_resolves_the_path_id_before_the_body_id
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()
        account = create_employer_account()
        employer_headers = make_employer_admin_headers(account["id"])
        location = validate_success(api.create_employer_location(
            account["id"],
            employer_location_payload(jurisdiction["id"], location_name="Alamo Taproom",
                                      annual_premium_cents=4821734),
            employer_headers), 201)

        validate_error(api.create_server_assignment(
            location["id"], server_assignment_payload(NON_EXISTENT_UUID),
            employer_headers), ApiErrorId.ERR_CREDENTIAL_NOT_FOUND, 404)
        validate_error(api.create_server_assignment(
            MISSING_LOCATION_ID, server_assignment_payload(NON_EXISTENT_UUID),
            employer_headers), ApiErrorId.ERR_EMPLOYER_NOT_FOUND, 404)

        assert get_location(location["id"])["assigned_server_count"] == 0
        _, meta = validate_paginated(api.list_location_server_assignments(
            location["id"], employer_headers))
        assert meta["total_count"] == 0, (
            f"neither refused request created an assignment, got {meta['total_count']}")

    def test_a_second_withdrawal_is_judged_on_the_seat_not_on_the_class(self, api):
        """PRD §3.5: "Withdrawal releases a seat before the exam window opens, recording the
        supplied `withdrawal_reason`. It is available to the sponsoring `EmployerAdmin` or to the
        `AlcoholServer` who holds the seat, and requires the enrollment to be in `REGISTERED`,
        `ATTENDED` or `NO_SHOW` and the session to be in `SCHEDULED` or `ROSTER_LOCKED`."
        PRD §3.5: "On success the seat moves to `WITHDRAWN`, the session's `enrolled_count` falls
        by one and the session's `version` rises by one; and when `seat_credit_charged` was true,
        the sponsor's `seat_credits_refunded_total` rises by one, `seat_credit_balance` rises by
        one, and `seat_credit_charged` becomes false."
        PRD §2.9: "`ERR_ENROLLMENT_INVALID_STATE` is raised whenever an enrollment is not in the
        from-state its transition needs: `REGISTERED` for marking attendance, either
        `EXAM_SCHEDULED` or `EXAM_FAILED` for opening a new attempt, and one of `REGISTERED`,
        `ATTENDED` or `NO_SHOW` for withdrawal; the same code covers submitting an attempt whose
        `outcome` is no longer `IN_PROGRESS`."

        Design: Corner/endpoints/withdrawing_an_already_withdrawn_seat_is_refused_on_the_enrollment_dimension
        """
        base = setup_training_base(clock=CLOCK)
        server = register_alcohol_server(base["jurisdiction"]["id"])
        server_headers = make_alcohol_server_headers(server["id"])
        seat = enroll_server(base["session"]["id"], server["id"], headers=server_headers)
        lock_roster(base["session"]["id"], base["trainer_headers"])

        released = validate_success(api.withdraw_enrollment(
            seat["id"], withdraw_payload(withdrawal_reason="schedule conflict"),
            server_headers), 200)
        assert released["enrollment_state"] == "WITHDRAWN"
        assert released["withdrawal_reason"] == "schedule conflict"

        emptied = get_session(base["session"]["id"])
        assert emptied["enrolled_count"] == 0
        assert emptied["session_status"] == "ROSTER_LOCKED", (
            "the roster stays locked, which is a legal from-state for withdrawal")

        validate_error(api.withdraw_enrollment(
            seat["id"], withdraw_payload(withdrawal_reason="schedule conflict"),
            server_headers), ApiErrorId.ERR_ENROLLMENT_INVALID_STATE, 409)

        assert get_session(base["session"]["id"])["enrolled_count"] == 0, (
            "the refused repeat did not decrement a second time")
        assert get_enrollment_row(seat["id"])["enrollment_state"] == "WITHDRAWN"
