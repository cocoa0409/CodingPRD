"""Who may act: role-exclusive writes, shared operations and segregation of duties."""

from test_helpers import (
    BRONZE,
    GOLD,
    ApiErrorId,
    CaseStatus,
    DayClass,
    PassStatus,
    PassholderStatus,
    ProgramStatus,
    ReservationStatus,
    UpgradeOrderStatus,
    advance_program,
    apply_upgrade,
    assert_day_counters,
    assert_ledger,
    assert_ledger_identity,
    assert_pass_dimensions,
    assert_version_unchanged,
    book_reservation,
    build_active_pass,
    build_program,
    cancel_reservation,
    clerk_headers,
    compliance_officer_headers,
    create_park_day,
    create_passholder,
    create_program,
    decide_payload,
    forecast_payload,
    gate_agent_headers,
    get_park_day,
    get_pass,
    make_compliance_officer_headers,
    make_passholder_headers,
    open_case,
    park_day_payload,
    passholder_payload,
    program_admin_headers,
    quote_upgrade,
    record_visit,
    reservation_payload,
    review_case,
    reverse_upgrade_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheCalendarIsTheAdministratorsAlone:
    """Only a ProgramAdmin writes to the operating calendar."""

    def test_three_other_roles_are_refused_the_identical_park_day_body(self, api, default_clock):
        """The role set is matched before the body is even considered.

        PRD: "Once both headers are present and well-formed, the role is matched against the
        set of roles the target endpoint permits, and a role outside that set is rejected
        with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/program_admin_exclusive_calendar_writes_are_refused_to_other_roles
        """
        program = create_program(api)
        holder = create_passholder(api, email="calendar-guest@example.com")
        body = park_day_payload(program["id"], "2026-09-01")

        for headers in (
            clerk_headers(),
            gate_agent_headers(),
            make_passholder_headers(holder["id"]),
        ):
            response = api.create_park_day(body, headers=headers)
            validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        accepted = validate_success(
            api.create_park_day(body, headers=program_admin_headers()), 201
        )

        assert accepted["day_class"] == DayClass.STANDARD.value, (
            f"a 1000/100 day opens STANDARD, got {accepted['day_class']!r}"
        )
        _, meta = validate_paginated(
            api.list_park_days(headers=program_admin_headers(), params={"program_id": program["id"]})
        )
        assert meta["total_count"] == 1, (
            f"only the administrator's day should exist, got {meta['total_count']!r}"
        )

    def test_re_forecasting_is_reserved_to_the_same_role(self, api, default_clock):
        """Re-forecasting an operating day is part of the administrator's remit.

        PRD: "A `ProgramAdmin` is the season programme office. It designs programmes, tiers
        and the operating calendar, re-forecasts operating days, assigns and lifts blockout
        dates, runs monthly billing and sets the logical clock."

        Design: Corner/rbac/program_admin_exclusive_calendar_writes_are_refused_to_other_roles
        """
        program = create_program(api)
        day = create_park_day(api, program["id"], "2026-09-01")

        refused = api.forecast_park_day(
            day["id"], forecast_payload(900), headers=clerk_headers()
        )

        validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        assert_version_unchanged(day, get_park_day(api, day["id"]), "the park day")

        updated = validate_success(
            api.forecast_park_day(day["id"], forecast_payload(900), headers=program_admin_headers())
        )
        assert updated["forecast_attendance"] == 900, (
            f"the administrator's re-forecast should land, got {updated['forecast_attendance']!r}"
        )
        assert updated["version"] == day["version"] + 1, (
            f"only the accepted write should bump the version, got {updated['version']!r}"
        )


class TestTheGateOpensCasesButDoesNotJudgeThem:
    """Review and decide belong to the compliance officer."""

    def _open_case(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        day = create_park_day(api, program.id, "2026-09-01")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        visit = record_visit(
            api, pass_ctx.id, day["id"], "2026-09-01T10:00:00Z", photo_match="MISMATCH"
        )
        case = open_case(api, pass_ctx.id, [visit["id"]], agent_user_id="gate-user-g1")
        return program, pass_ctx, case

    def test_the_opening_agent_may_neither_review_nor_decide_the_case(self, api, default_clock):
        """The gate's authority stops at opening the investigation.

        PRD: "A `GateAgent` operates the turnstiles: it records gate entries, closes visits
        with the in-park spend, and opens pass-sharing cases from gate evidence."

        Design: Corner/rbac/gate_agent_cannot_review_or_decide_a_sharing_case
        """
        _, _, case = self._open_case(api)

        review = api.review_sharing_case(case["id"], headers=gate_agent_headers())
        decide = api.decide_sharing_case(
            case["id"],
            decide_payload("DISMISSED", "Self-service dismissal"),
            headers=gate_agent_headers(),
        )

        validate_error(review, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        validate_error(decide, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        untouched = validate_success(
            api.get_sharing_case(case["id"], headers=gate_agent_headers())
        )
        assert untouched["case_status"] == CaseStatus.OPEN.value, (
            f"the refused actions leave the case OPEN, got {untouched['case_status']!r}"
        )
        assert untouched["review_round"] == 0, (
            f"no review round should have been consumed, got {untouched['review_round']!r}"
        )

    def test_the_compliance_officer_performs_the_same_review(self, api, default_clock):
        """Adjudication is the officer's remit, and reading a case is shared.

        PRD: "A `ComplianceOfficer` handles adjudication: it takes sharing cases under
        review, decides them, reverses applied upgrades, and reads the revenue analysis."

        Design: Corner/rbac/gate_agent_cannot_review_or_decide_a_sharing_case
        """
        _, _, case = self._open_case(api)

        reviewed = review_case(api, case["id"], officer_user_id="officer-o1")

        assert reviewed["case_status"] == CaseStatus.UNDER_REVIEW.value, (
            f"the officer's review should move the case, got {reviewed['case_status']!r}"
        )
        by_agent = validate_success(api.get_sharing_case(case["id"], headers=gate_agent_headers()))
        assert by_agent["case_status"] == CaseStatus.UNDER_REVIEW.value, (
            "the gate should still be able to read the case it opened, got "
            f"{by_agent['case_status']!r}"
        )


class TestApplyingAnUpgradeAndUndoingItAreDifferentDesks:
    """The clerk applies; only the officer reverses."""

    def _applied_upgrade(self, api):
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        order = quote_upgrade(
            api, pass_ctx.id, program.tier_id("BRONZE"), program.tier_id("GOLD")
        )
        applied = apply_upgrade(api, order["id"], order["total_due_cents"])
        return program, pass_ctx, applied

    def test_the_clerk_who_applied_the_upgrade_cannot_reverse_it(self, api, default_clock):
        """Reversal is withheld from the desk that took the money.

        PRD: "**Reversing** an applied upgrade is reserved for a `ComplianceOfficer`, never
        the clerk who applied it."

        Design: Corner/rbac/pass_office_clerk_cannot_reverse_an_applied_upgrade
        """
        program, pass_ctx, applied = self._applied_upgrade(api)

        response = api.reverse_upgrade_order(
            applied["id"], reverse_upgrade_payload("Clerk change of mind"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        still = validate_success(api.get_upgrade_order(applied["id"], headers=clerk_headers()))
        assert still["status"] == UpgradeOrderStatus.APPLIED.value, (
            f"the refused reversal leaves the order APPLIED, got {still['status']!r}"
        )
        assert get_pass(api, pass_ctx.id)["tier_id"] == program.tier_id("GOLD"), (
            "the pass should still sit on the upgraded tier"
        )

    def test_the_officers_reversal_compensates_the_whole_ledger(self, api, default_clock):
        """The permitted caller undoes every money effect with no residue.

        PRD: "On success the order moves `APPLIED → REVERSED`, its terminal state, and every
        ledger effect is compensated exactly: the pass's `tier_id` returns to
        `source_tier_id` and `contract_value_cents` returns to the source tier's
        `base_price_cents`; `billed_total_cents` falls by `gross_delta_cents` plus
        `admin_fee_cents`; `credited_amount_cents` falls by `credit_cents`;
        `paid_to_date_cents` falls by `payment_amount_cents`; `outstanding_balance_cents` is
        recomputed so that the §2.10 ledger identity still holds with no residue; and both
        the pass's and the order's `version` increment by 1."

        Design: Corner/rbac/pass_office_clerk_cannot_reverse_an_applied_upgrade
        """
        program, pass_ctx, applied = self._applied_upgrade(api)

        reversed_order = validate_success(
            api.reverse_upgrade_order(
                applied["id"],
                reverse_upgrade_payload("Charged in error"),
                headers=make_compliance_officer_headers("officer-o1"),
            )
        )

        assert reversed_order["status"] == UpgradeOrderStatus.REVERSED.value, (
            f"the officer's reversal should reach REVERSED, got {reversed_order['status']!r}"
        )
        row = get_pass(api, pass_ctx.id)
        assert row["tier_id"] == program.tier_id("BRONZE"), (
            "the pass should return to the source tier"
        )
        assert_ledger(row, contract=12000, billed=12000, paid=12000, credited=0, outstanding=0)
        assert_ledger_identity(row)


class TestTheHolderDirectoryIsStaffOnly:
    """The exclusion is on the collection, not on the single row."""

    def _two_holders(self, api):
        first = create_passholder(api, email="ada@example.com")
        second = create_passholder(
            api, full_name="Ben Holder", email="ben@example.com", date_of_birth="1988-06-11"
        )
        return first, second

    def test_a_guest_is_refused_the_directory_that_every_staff_role_reads(self, api):
        """The listing is readable by the four operator roles and by no guest.

        PRD: "The holder directory may be filtered by `email` or `status`, and is readable
        by every role except `Passholder`."

        Design: Corner/rbac/passholder_cannot_read_the_holder_directory
        """
        first, _ = self._two_holders(api)

        response = api.list_passholders(headers=make_passholder_headers(first["id"]))

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        _, meta = validate_paginated(api.list_passholders(headers=gate_agent_headers()))
        assert meta["total_count"] == 2, (
            f"the staff roles keep the whole directory, got {meta['total_count']!r}"
        )

    def test_the_same_guest_may_still_read_a_single_holder_row(self, api):
        """The guest's exclusion covers the directory listing and writes, not this read.

        PRD: "A `Passholder` also has no access whatsoever to the passholder directory
        listing, nor to any write reserved for `ProgramAdmin`, `PassOfficeClerk`,
        `GateAgent` or `ComplianceOfficer`."

        Design: Corner/rbac/passholder_cannot_read_the_holder_directory
        """
        first, _ = self._two_holders(api)

        row = validate_success(
            api.get_passholder(first["id"], headers=make_passholder_headers(first["id"]))
        )

        assert row["full_name"] == "Ada Holder", (
            f"the single read should return the holder, got {row['full_name']!r}"
        )
        assert row["status"] == PassholderStatus.ACTIVE.value, (
            f"a fresh holder is ACTIVE, got {row['status']!r}"
        )

        refused = api.create_passholder(
            passholder_payload(
                full_name="Cara Holder", email="cara@example.com", date_of_birth="1991-02-03"
            ),
            headers=make_passholder_headers(first["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)


class TestBookingAndCancellingAreSharedWork:
    """A clerk books for the guest and the guest cancels the clerk's row."""

    def _bookable_day(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        day = create_park_day(api, program.id, "2026-09-01")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        return program, day, pass_ctx

    def test_the_guest_may_cancel_a_booking_the_clerk_made(self, api, default_clock):
        """Voluntary cancellation is open to either caller on the same row.

        PRD: "Voluntary cancellation is available to a `PassOfficeClerk` or to the owning
        `Passholder` and takes no request body."

        Design: Corner/rbac/reservation_operations_are_shared_by_clerk_and_holder
        """
        _, day, pass_ctx = self._bookable_day(api)

        booked = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")
        cancelled = cancel_reservation(api, booked["id"], headers=pass_ctx.headers)

        assert booked["status"] == ReservationStatus.CONFIRMED.value, (
            f"the clerk's booking should open CONFIRMED, got {booked['status']!r}"
        )
        assert cancelled["status"] == ReservationStatus.CANCELLED_BY_HOLDER.value, (
            f"the guest's cancellation is voluntary, got {cancelled['status']!r}"
        )

    def test_the_two_callers_counters_reconcile_on_one_day(self, api, default_clock):
        """Whoever books, the day's counters move the same way.

        PRD: "A new reservation opens in `status` `CONFIRMED`, leaves `redeemed_visit_id`
        null, raises the day's `reserved_count` by one, raises the day's monotonic
        `grant_count` by one, and recomputes `remaining_slot_count`."

        Design: Corner/rbac/reservation_operations_are_shared_by_clerk_and_holder
        """
        _, day, pass_ctx = self._bookable_day(api)

        booked = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")
        cancel_reservation(api, booked["id"], headers=pass_ctx.headers)
        by_holder = validate_success(
            api.create_reservation(
                reservation_payload(pass_ctx.id, day["id"], "13:00", "16:00"),
                headers=pass_ctx.headers,
            ),
            201,
        )

        assert by_holder["status"] == ReservationStatus.CONFIRMED.value, (
            f"the guest's own booking should open CONFIRMED, got {by_holder['status']!r}"
        )
        assert by_holder["redeemed_visit_id"] is None, (
            f"a fresh booking has no visit, got {by_holder['redeemed_visit_id']!r}"
        )
        assert_day_counters(get_park_day(api, day["id"]), reserved=1, released=1, grant=2)


class TestTheOpenerOfACaseMayNotDecideIt:
    """The bar is on the user identifier, not on the role."""

    def _case_under_review_opened_by_u1(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        day = create_park_day(api, program.id, "2026-09-01")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        visit = record_visit(
            api, pass_ctx.id, day["id"], "2026-09-01T10:00:00Z", photo_match="MISMATCH"
        )
        case = open_case(
            api,
            pass_ctx.id,
            [visit["id"]],
            note="Two different faces on one pass",
            agent_user_id="user-u1",
        )
        reviewed = review_case(api, case["id"], officer_user_id="user-u1")
        return program, pass_ctx, reviewed

    def test_the_same_user_wearing_the_officer_hat_is_still_refused(self, api, default_clock):
        """Reviewing was allowed to U1; deciding is not.

        PRD: "A decide request whose `X-User-ID` equals the case's `opened_by_user_id` is
        refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/the_gate_user_who_opened_a_case_cannot_also_decide_it
        """
        _, pass_ctx, reviewed = self._case_under_review_opened_by_u1(api)
        assert reviewed["opened_by_user_id"] == "user-u1", (
            f"the case should remember its opener, got {reviewed['opened_by_user_id']!r}"
        )
        assert reviewed["case_status"] == CaseStatus.UNDER_REVIEW.value, (
            f"the same user's review is permitted, got {reviewed['case_status']!r}"
        )

        response = api.decide_sharing_case(
            reviewed["id"],
            decide_payload("SUBSTANTIATED", "My own case"),
            headers=make_compliance_officer_headers("user-u1"),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        still = validate_success(
            api.get_sharing_case(reviewed["id"], headers=compliance_officer_headers())
        )
        assert still["case_status"] == CaseStatus.UNDER_REVIEW.value, (
            f"the refused decision leaves the case UNDER_REVIEW, got {still['case_status']!r}"
        )
        assert_pass_dimensions(get_pass(api, pass_ctx.id), pass_status=PassStatus.ACTIVE.value)

    def test_a_second_officer_decides_the_identical_case(self, api, default_clock):
        """Only the header identity differs, and that is enough.

        PRD: "A decision of `SUBSTANTIATED` drives `UNDER_REVIEW → SUBSTANTIATED` and
        snapshots `revocation_forfeit_cents` from the pass's `paid_to_date_cents` at that
        instant — the figure the park is about to keep."

        PRD: "Both outcomes record `decided_by_user_id` and `decision_rationale`, and both
        increment the case's `version` by 1."

        Design: Corner/rbac/the_gate_user_who_opened_a_case_cannot_also_decide_it
        """
        _, pass_ctx, reviewed = self._case_under_review_opened_by_u1(api)

        decided = validate_success(
            api.decide_sharing_case(
                reviewed["id"],
                decide_payload("SUBSTANTIATED", "Independent review upholds the finding"),
                headers=make_compliance_officer_headers("user-u2"),
            )
        )

        assert decided["case_status"] == CaseStatus.SUBSTANTIATED.value, (
            f"the independent officer's decision should land, got {decided['case_status']!r}"
        )
        assert decided["decided_by_user_id"] == "user-u2", (
            f"the deciding user should be recorded, got {decided['decided_by_user_id']!r}"
        )
        assert decided["review_round"] == 1, (
            f"the first round decided the case, got {decided['review_round']!r}"
        )
        assert decided["revocation_forfeit_cents"] == 12000, (
            "the forfeit snapshots everything paid so far, got "
            f"{decided['revocation_forfeit_cents']!r}"
        )
        assert_pass_dimensions(get_pass(api, pass_ctx.id), pass_status=PassStatus.REVOKED.value)
