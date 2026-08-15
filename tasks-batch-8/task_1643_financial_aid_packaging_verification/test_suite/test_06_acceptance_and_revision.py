"""Award package acceptance, decline, notification, and revision: per-line
acceptance semantics, pool release cascades, terminal lockdown, notification
snapshots, the single-pending-revision guard, and the package uniqueness
window (PRD §2.7, §2.10, §3.6)."""
from test_helpers import (
    SSN_NOT_SELECTED_A,
    SSN_NOT_SELECTED_B,
    SSN_SELECTED_B,
    TEST_USERS,
    ApiErrorId,
    accept_lines,
    assert_award_notification,
    build_package,
    create_aid_year,
    create_package,
    get_package,
    get_package_lines,
    get_package_notifications,
    import_isir,
    lines_by_fund,
    make_student_headers,
    notify_package,
    register_student,
    setup_notified_package,
    setup_open_aid_year,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["aid_officer_headers"]
DIRECTOR = TEST_USERS["aid_director_headers"]

SEOG_ONLY = [
    {"fund_code": "SEOG", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 200000, "pool_budget_cents": 350000,
     "packaging_rank": 1, "requires_verification_complete": False},
]

PELL_PLUS_INST = [
    {"fund_code": "PELL", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 739500, "pool_budget_cents": 0, "packaging_rank": 1,
     "requires_verification_complete": False},
    {"fund_code": "INST_GRANT", "category": "INSTITUTIONAL", "need_based": True,
     "annual_cap_cents": 500000, "pool_budget_cents": 800000,
     "packaging_rank": 2, "requires_verification_complete": False},
]


class TestRevisionFork:
    def _setup_revision_pending(self, api):
        env = setup_notified_package(ssn=SSN_NOT_SELECTED_A)
        resp = api.create_revision_request(
            env["package"]["id"], "APPEAL_AMOUNT",
            make_student_headers(env["student"]["id"]))
        request = validate_success(resp, 201)
        assert request["status"] == "SUBMITTED"
        assert request["requested_by_role"] == "Student"
        return env, request

    def test_revision_denied_returns_package_unchanged(self, api):
        """PRD §3.6: "Denial returns the package to `NOTIFIED` unchanged."
        PRD §3.6: "Either terminal decision — `APPROVED` after its repack or `DENIED` — returns the package from `REVISION_REQUESTED` to `NOTIFIED`."

        Design: Difficulty/non_linear_state_machine/revision_request_branching_fork_on_package
        """
        env, request = self._setup_revision_pending(api)
        validate_success(api.begin_review_revision_request(request["id"], OFFICER))
        denied = validate_success(api.deny_revision_request(
            request["id"], "No new circumstances documented", DIRECTOR))
        assert denied["status"] == "DENIED"

        package = get_package(env["package"]["id"])
        assert package["status"] == "NOTIFIED"
        # No repack on the DENIED branch: the single PELL line is untouched.
        assert package["total_offered_cents"] == 739500

    def test_revision_approved_repacks_and_renotifies(self, api):
        """PRD §3.6: "Approval re-runs the packaging waterfall against current inputs — enrollment, official EFC, professional judgment deltas — adjusting existing lines, creating new ones, or moving ineligible lines `OFFERED` → `CANCELLED` (releasing their reserved pool and recomputing package totals); recomputes every fund's reserved pool with the exhaustion auto-transitions firing in both directions; refuses the whole decision with `ERR_FUND_POOL_EXHAUSTED` if the repack would push any non-PELL fund's reserved pool above its budget; and finally returns the package to `NOTIFIED` through the system transition, creating a fresh AwardNotification with the next `notification_seq`."

        Design: Difficulty/non_linear_state_machine/revision_request_branching_fork_on_package
        """
        env, request = self._setup_revision_pending(api)
        validate_success(api.begin_review_revision_request(request["id"], OFFICER))
        approved = validate_success(api.approve_revision_request(
            request["id"], "Circumstances reviewed; package rebuilt", DIRECTOR))
        assert approved["status"] == "APPROVED"

        package = get_package(env["package"]["id"])
        assert package["status"] == "NOTIFIED"
        assert package["total_offered_cents"] == 739500

        notifications = get_package_notifications(env["package"]["id"])
        seqs = sorted(n["notification_seq"] for n in notifications)
        assert seqs == [1, 2], (
            f"repack must re-notify with the next notification_seq, got {seqs}")


class TestDeclinePoolReleaseCascade:
    def _setup_two_notified_packages(self, api):
        """SEOG pool 350_000: student A's build reserves 200_000, student B's
        build is pool-capped at 150_000 and tips the fund to exactly EXHAUSTED."""
        env = setup_open_aid_year(fund_specs=SEOG_ONLY)
        students = {}
        packages = {}
        for ssn, name in ((SSN_NOT_SELECTED_A, "Decliner A"),
                          (SSN_NOT_SELECTED_B, "Holder B")):
            student = register_student(ssn, full_name=name,
                                       email=f"{ssn}@example.edu")
            import_isir(student["id"], env["aid_year"]["id"], agi_cents=2000000)
            package = create_package(student["id"], env["aid_year"]["id"])
            build_package(package["id"])
            packages[ssn] = notify_package(package["id"])
            students[ssn] = student
        return env, students, packages

    def test_decline_revives_exhausted_fund(self, api):
        """PRD §3.6: "A student may instead decline the entire package, moving it `NOTIFIED` → `DECLINED`: every `OFFERED` line becomes `DECLINED`, each fund's reserved pool is released (again possibly reviving `EXHAUSTED` funds), and the aid year's packaged total is recomputed."
        PRD §2.10: "should a later mutation reduce `pool_reserved_cents` below `pool_budget_cents`, the fund automatically returns from `EXHAUSTED` to `ACTIVE`."

        Design: Difficulty/transitive_cascade/package_decline_pool_release_exhaustion_reversal_cascade
        """
        env, students, packages = self._setup_two_notified_packages(api)
        fund_id = env["funds"]["SEOG"]["id"]
        pre = validate_success(api.get_fund_type(fund_id, OFFICER))
        assert pre["status"] == "EXHAUSTED"
        assert pre["pool_reserved_cents"] == 350000

        declined = validate_success(api.decline_award_package(
            packages[SSN_NOT_SELECTED_A]["id"],
            make_student_headers(students[SSN_NOT_SELECTED_A]["id"])))
        assert declined["status"] == "DECLINED"

        fund = validate_success(api.get_fund_type(fund_id, OFFICER))
        assert fund["status"] == "ACTIVE"

    def test_decline_reconciles_pool_reserved_to_the_cent(self, api):
        """PRD §2.10: "A FundType's `pool_reserved_cents` is the sum of `offered_cents` over its award lines whose status is `OFFERED`, `ACCEPTED`, `PARTIALLY_ACCEPTED`, `DISBURSING`, or `DISBURSED`, recomputed on every line transition into or out of that set and on any change to `offered_cents`; lines that are `DECLINED`, `CANCELLED`, or `RETURNED` no longer reserve pool."
        PRD §3.6: "A student may instead decline the entire package, moving it `NOTIFIED` → `DECLINED`: every `OFFERED` line becomes `DECLINED`, each fund's reserved pool is released (again possibly reviving `EXHAUSTED` funds), and the aid year's packaged total is recomputed."

        Design: Difficulty/transitive_cascade/package_decline_pool_release_exhaustion_reversal_cascade
        """
        env, students, packages = self._setup_two_notified_packages(api)
        fund_id = env["funds"]["SEOG"]["id"]

        validate_success(api.decline_award_package(
            packages[SSN_NOT_SELECTED_A]["id"],
            make_student_headers(students[SSN_NOT_SELECTED_A]["id"])))

        fund = validate_success(api.get_fund_type(fund_id, OFFICER))
        # 350_000 reserved - 200_000 released = 150_000 (student B's line).
        assert fund["pool_reserved_cents"] == 150000

        # Student B's package is untouched by the cascade.
        other = get_package(packages[SSN_NOT_SELECTED_B]["id"])
        assert other["status"] == "NOTIFIED"
        other_lines = get_package_lines(other["id"])
        assert len(other_lines) == 1
        assert other_lines[0]["status"] == "OFFERED"
        assert other_lines[0]["offered_cents"] == 150000


class TestPackageUniquenessWindow:
    def _setup_two_year_window(self, api):
        env = setup_open_aid_year()
        other_year = create_aid_year(
            year_code="2027-2028", coa_in_state_cents=2500000,
            coa_out_of_state_cents=3700000,
            priority_deadline="2027-03-01T00:00:00Z")
        student = register_student(SSN_NOT_SELECTED_A, full_name="Windowed",
                                   email="win@example.edu")
        import_isir(student["id"], env["aid_year"]["id"], agi_cents=2000000)
        package = create_package(student["id"], env["aid_year"]["id"])
        return env, other_year, student, package

    def test_second_package_same_student_same_year_rejected(self, api):
        """PRD §3.6: "Packaging begins with a shell: an `AidOfficer` creates an AwardPackage for a `student_id` and `aid_year_id`, at most one per student per aid year (a second attempt fails with `ERR_DUPLICATE`), born in `DRAFT`."
        PRD §2.7 (rung 11): "`ssn` unique across students, `email` unique across students, `fund_code` unique within an aid year, the (`student_id`, `aid_year_id`, `transaction_number`) triple unique across ISIR records, and at most one AwardPackage per (`student_id`, `aid_year_id`) — otherwise `ERR_DUPLICATE` (409)."

        Design: Difficulty/resource_temporal_overlap/duplicate_package_same_aid_year_window_conflict
        """
        env, other_year, student, package = self._setup_two_year_window(api)
        resp = api.create_award_package(
            {"student_id": student["id"], "aid_year_id": env["aid_year"]["id"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_package_same_student_other_aid_year_allowed(self, api):
        """PRD §3.6: "Packaging begins with a shell: an `AidOfficer` creates an AwardPackage for a `student_id` and `aid_year_id`, at most one per student per aid year (a second attempt fails with `ERR_DUPLICATE`), born in `DRAFT`."

        Design: Difficulty/resource_temporal_overlap/duplicate_package_same_aid_year_window_conflict
        """
        env, other_year, student, package = self._setup_two_year_window(api)
        resp = api.create_award_package(
            {"student_id": student["id"], "aid_year_id": other_year["id"]},
            OFFICER)
        second = validate_success(resp, 201)
        assert second["status"] == "DRAFT"
        assert second["aid_year_id"] == other_year["id"]


class TestNotificationAndTerminalStates:
    def test_notify_from_draft_rejected(self, api):
        """PRD §3.6: "Notification moves the package `PACKAGED` → `NOTIFIED` and is permitted only when at least one child line is still `OFFERED`."
        PRD §2.7 (rung 5): "the target entity's state machine permits the requested transition from its current state — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/invalid_transition_notify_from_draft
        """
        env = setup_open_aid_year()
        student = register_student(SSN_SELECTED_B, full_name="Draft Notify",
                                   email="dn@example.edu")
        import_isir(student["id"], env["aid_year"]["id"], agi_cents=2000000)
        package = create_package(student["id"], env["aid_year"]["id"])

        resp = api.notify_award_package(package["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        notifications = get_package_notifications(package["id"])
        assert notifications == []

    def test_declined_package_rejects_revision_request(self, api):
        """PRD §3.6: "A student who wants changes files a revision request with a `reason` of `CHANGE_ENROLLMENT`, `CHANGE_CIRCUMSTANCE`, `APPEAL_AMOUNT`, or `DECLINE_LOAN_ONLY`. Filing moves the package `NOTIFIED` → `REVISION_REQUESTED` and creates the RevisionRequest in `SUBMITTED` with `requested_by_role` captured from the caller (`Student` when the student filed it; the value may also be `AidOfficer`)."
        PRD §2.7 (rung 5): "the target entity's state machine permits the requested transition from its current state — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/terminal_lockdown_declined_package_rejects_accept
        """
        env = setup_notified_package(ssn=SSN_SELECTED_B)
        validate_success(api.decline_award_package(
            env["package"]["id"], make_student_headers(env["student"]["id"])))

        resp = api.create_revision_request(
            env["package"]["id"], "APPEAL_AMOUNT",
            make_student_headers(env["student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_package(env["package"]["id"])["status"] == "DECLINED"

    def test_notification_snapshot_and_acknowledge(self, api):
        """PRD §3.6: "Notifying creates an AwardNotification in `DRAFT` and immediately fires it to `SENT`, stamping `sent_at` from the logical clock, assigning `notification_seq` (1 for the package's first notification, incrementing on each re-notification after a revision), and freezing `snapshot_total_offered_cents` to the package's `total_offered_cents` at send time so later drift is detectable."
        PRD §3.6: "The student acknowledges a `SENT` notification, moving it to the terminal `ACKNOWLEDGED`; acknowledgment is an ownership-checked action (rung 8), so a student acknowledging someone else's notification is refused with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/endpoints/notification_acknowledge_and_snapshot
        """
        env = setup_notified_package(ssn=SSN_SELECTED_B)
        notifications = get_package_notifications(env["package"]["id"])
        assert len(notifications) == 1
        note = notifications[0]
        assert_award_notification(note)
        assert note["notification_seq"] == 1
        assert note["status"] == "SENT"
        assert note["snapshot_total_offered_cents"] == 739500

        acked = validate_success(api.acknowledge_notification(
            note["id"], make_student_headers(env["student"]["id"])))
        assert acked["status"] == "ACKNOWLEDGED"

    def test_second_revision_request_while_pending_rejected(self, api):
        """PRD §3.6: "Only one revision may be in flight: if a request for the package already sits in `SUBMITTED` or `UNDER_REVIEW`, a new filing fails with `ERR_REVISION_ALREADY_PENDING` (409)."

        Design: Corner/validations/revision_second_pending_rejected
        """
        env = setup_notified_package(ssn=SSN_SELECTED_B)
        first = api.create_revision_request(
            env["package"]["id"], "APPEAL_AMOUNT",
            make_student_headers(env["student"]["id"]))
        validate_success(first, 201)

        resp = api.create_revision_request(
            env["package"]["id"], "CHANGE_ENROLLMENT",
            make_student_headers(env["student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REVISION_ALREADY_PENDING)


class TestPartialAcceptanceTotals:
    def _setup_two_fund_notified(self, api):
        env = setup_notified_package(ssn=SSN_SELECTED_B,
                                     fund_specs=PELL_PLUS_INST)
        by_code = lines_by_fund(env["lines"], env["funds"])
        return env, by_code

    def test_declined_line_drops_out_of_offered_totals(self, api):
        """PRD §3.6: "The rules per line are exact: an amount equal to `offered_cents` moves the line `OFFERED` → `ACCEPTED` with `accepted_cents` set to `offered_cents`; an amount strictly between zero and the offer moves it to `PARTIALLY_ACCEPTED` with `accepted_cents` set to that amount, releasing the difference from the fund's `pool_reserved_cents`; an amount of zero declines the line, moving it to `DECLINED` and releasing the full `offered_cents` from the pool, which may fire the fund's `EXHAUSTED` → `ACTIVE` return. When every non-declined line is accepted at its full offer, the package lands in `ACCEPTED`; when at least one line is partial or declined, it lands in `PARTIALLY_ACCEPTED`."
        PRD §3.6: "The package also exposes `total_offered_cents` — the sum of `offered_cents` over lines in `OFFERED`, `ACCEPTED`, `PARTIALLY_ACCEPTED`, `DISBURSING`, or `DISBURSED` — and `total_accepted_cents`, the sum of `accepted_cents` over lines in `ACCEPTED`, `PARTIALLY_ACCEPTED`, `DISBURSING`, or `DISBURSED`."

        Design: Corner/endpoints/computed_read_package_totals_after_partial_accept
        """
        env, by_code = self._setup_two_fund_notified(api)
        resp = accept_lines(env["package"]["id"], env["student"]["id"],
                            [(by_code["PELL"]["id"], 739500),
                             (by_code["INST_GRANT"]["id"], 0)])
        package = validate_success(resp)
        assert package["status"] == "PARTIALLY_ACCEPTED"
        assert package["total_accepted_cents"] == 739500
        # The DECLINED institutional line leaves the offered status set.
        assert package["total_offered_cents"] == 739500

        fund = validate_success(api.get_fund_type(
            env["funds"]["INST_GRANT"]["id"], OFFICER))
        assert fund["pool_reserved_cents"] == 0

    def test_partial_accept_releases_difference_from_pool(self, api):
        """PRD §3.6: "an amount strictly between zero and the offer moves it to `PARTIALLY_ACCEPTED` with `accepted_cents` set to that amount, releasing the difference from the fund's `pool_reserved_cents`".
        PRD §2.10: "An AidYear's `total_packaged_cents` is the same reserved-style sum taken across every award line of every package belonging to the aid year, recomputed on every AwardLine mutation; its `total_disbursed_cents` is the sum of `disbursed_cents` over `POSTED` disbursements of the aid year, recomputed on every disbursement transition into `POSTED` or `RETURNED`."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_pool_reserved_after_partial_accept
        """
        env, by_code = self._setup_two_fund_notified(api)
        resp = accept_lines(env["package"]["id"], env["student"]["id"],
                            [(by_code["PELL"]["id"], 739500),
                             (by_code["INST_GRANT"]["id"], 200000)])
        package = validate_success(resp)
        assert package["status"] == "PARTIALLY_ACCEPTED"

        line = validate_success(api.get_award_line(by_code["INST_GRANT"]["id"],
                                                   OFFICER))
        assert line["status"] == "PARTIALLY_ACCEPTED"
        assert line["accepted_cents"] == 200000

        # 500_000 offered - 300_000 released = 200_000 still reserved.
        fund = validate_success(api.get_fund_type(
            env["funds"]["INST_GRANT"]["id"], OFFICER))
        assert fund["pool_reserved_cents"] == 200000

        # Reserved-style year total: 739_500 (PELL) + 200_000 (INST_GRANT).
        aid_year = validate_success(api.get_aid_year(env["aid_year"]["id"],
                                                     OFFICER))
        assert aid_year["total_packaged_cents"] == 939500
