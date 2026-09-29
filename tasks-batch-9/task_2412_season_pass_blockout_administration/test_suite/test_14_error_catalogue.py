"""Reaching the error catalogue: each code from its own trigger, in its own band."""

from test_helpers import (
    BRONZE,
    GOLD,
    UNKNOWN_UUID,
    ApiErrorId,
    CaseStatus,
    CreditMode,
    PassStatus,
    PaymentMode,
    ProgramStatus,
    TierStatus,
    UpgradeOrderStatus,
    apply_upgrade_payload,
    assert_day_counters,
    assert_day_posture,
    assert_pass_dimensions,
    advance_program,
    appeal_case,
    appeal_payload,
    blockout_payload,
    book_reservation,
    build_active_pass,
    build_pending_pass,
    build_program,
    cancel_reservation,
    clerk_headers,
    close_visit,
    close_visit_payload,
    compliance_officer_headers,
    create_blockout,
    create_park_day,
    create_passholder,
    create_program,
    create_tier,
    decide_case,
    decide_payload,
    gate_agent_headers,
    get_park_day,
    get_pass,
    headers_with_empty_user_id,
    headers_with_undeclared_role,
    lift_blockout,
    lift_payload,
    make_compliance_officer_headers,
    make_passholder_headers,
    open_case,
    pass_program_payload,
    payment_plan_payload,
    plan_installments,
    program_admin_headers,
    quote_upgrade,
    record_visit,
    reinstate_payload,
    renew_payload,
    reservation_payload,
    reverse_upgrade_payload,
    review_case,
    season_pass_payload,
    sell_pass,
    sharing_case_payload,
    tier_status_payload,
    upgrade_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
    visit_payload,
)


def _passes(api, **params):
    return validate_paginated(api.list_season_passes(headers=clerk_headers(), params=params))


class TestEveryExistenceRuleHasItsOwnCode:
    """Eight unknown identifiers, eight different codes."""

    def test_each_unknown_identifier_answers_with_its_own_not_found_code(self, api):
        """The existence band is per-resource, never a single generic 404.

        PRD: "Within the existence band, identifiers resolve in this order: pass programme
        (`ERR_PROGRAM_NOT_FOUND`), pass tier (`ERR_TIER_NOT_FOUND`), park day
        (`ERR_PARK_DAY_NOT_FOUND`), passholder (`ERR_PASSHOLDER_NOT_FOUND`), season pass
        (`ERR_PASS_NOT_FOUND`), payment plan (`ERR_PLAN_NOT_FOUND`), installment
        (`ERR_INSTALLMENT_NOT_FOUND`), reservation (`ERR_RESERVATION_NOT_FOUND`), visit
        (`ERR_VISIT_NOT_FOUND`), sharing case (`ERR_CASE_NOT_FOUND`), upgrade order
        (`ERR_UPGRADE_ORDER_NOT_FOUND`), blockout assignment
        (`ERR_ASSIGNMENT_NOT_FOUND`)."

        Design: Corner/errors/every_existence_rule_returns_its_own_not_found_code
        """
        reads = [
            (api.get_passholder, clerk_headers(), ApiErrorId.ERR_PASSHOLDER_NOT_FOUND),
            (api.get_payment_plan, clerk_headers(), ApiErrorId.ERR_PLAN_NOT_FOUND),
            (api.get_installment, clerk_headers(), ApiErrorId.ERR_INSTALLMENT_NOT_FOUND),
            (api.get_reservation, clerk_headers(), ApiErrorId.ERR_RESERVATION_NOT_FOUND),
            (api.get_visit, gate_agent_headers(), ApiErrorId.ERR_VISIT_NOT_FOUND),
            (api.get_sharing_case, compliance_officer_headers(), ApiErrorId.ERR_CASE_NOT_FOUND),
            (api.get_upgrade_order, clerk_headers(), ApiErrorId.ERR_UPGRADE_ORDER_NOT_FOUND),
            (
                api.get_blockout_assignment,
                program_admin_headers(),
                ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
            ),
        ]

        for read, headers, expected in reads:
            response = read(UNKNOWN_UUID, headers=headers)
            validate_error(response, expected.value, 404)

    def test_the_error_envelope_carries_only_the_code_and_the_message(self, api):
        """Every refusal answers in the standard error envelope.

        PRD: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/every_existence_rule_returns_its_own_not_found_code
        """
        response = api.get_payment_plan(UNKNOWN_UUID, headers=clerk_headers())

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404)
        body = response.json()
        assert body["response_type"] == "error", (
            f"a refusal should declare response_type error, got {body['response_type']!r}"
        )
        assert set(body["data"]) == {"error_id", "message"}, (
            f"the error data object holds only error_id and message, got {sorted(body['data'])}"
        )
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "the message should be a human-readable string"
        )
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
            f"the error meta holds only the two request fields, got {sorted(body['meta'])}"
        )


class TestUnauthenticatedIsNotUnauthorised:
    """Bands 1 and 2 answer 401; only band 3 answers 403."""

    def test_an_empty_user_id_header_is_an_authentication_failure(self, api):
        """The identifier is checked before anything else in the system.

        PRD: "If `X-User-ID` is absent or empty the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/calls_missing_x_user_id_or_carrying_an_undeclared_role_are_unauthenticated
        """
        response = api.create_pass_program(
            pass_program_payload(), headers=headers_with_empty_user_id()
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        _, meta = validate_paginated(api.list_pass_programs(headers=program_admin_headers()))
        assert meta["total_count"] == 0, (
            f"the unauthenticated write must create nothing, got {meta['total_count']!r}"
        )

    def test_a_role_outside_the_five_declared_names_is_also_a_401(self, api):
        """An unknown role name never reaches the permitted-role comparison.

        PRD: "If `X-User-Role` is absent, empty, or is not one of the five role names
        declared below, the request is likewise rejected with `ERR_UNAUTHENTICATED` (HTTP
        401); the missing-identifier check is evaluated before the role-name check."

        Design: Corner/errors/calls_missing_x_user_id_or_carrying_an_undeclared_role_are_unauthenticated
        """
        response = api.list_pass_programs(headers=headers_with_undeclared_role())

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


class TestOwnershipAppliesOnlyToTheGuest:
    """A guest may act on their own pass and on nothing else."""

    def _two_holders_one_pass(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-09-01")
        owner_pass = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "owner@example.com"}
        )
        stranger = create_passholder(
            api, full_name="Ben Holder", email="stranger@example.com", date_of_birth="1988-06-11"
        )
        return program, day, owner_pass, stranger

    def test_a_stranger_can_neither_read_nor_book_the_pass(self, api, default_clock):
        """The ownership rule guards the single read and the booking alike.

        PRD: "First, **ownership**: a caller acting as `Passholder` who touches a season
        pass whose `passholder_id` differs from `X-User-ID` is refused with
        `ERR_NOT_PASS_OWNER` (HTTP 403)."

        Design: Corner/errors/passholder_cannot_touch_another_holders_pass
        """
        _, day, owner_pass, stranger = self._two_holders_one_pass(api)
        stranger_headers = make_passholder_headers(stranger["id"])

        read = api.get_season_pass(owner_pass.id, headers=stranger_headers)
        booking = api.create_reservation(
            reservation_payload(owner_pass.id, day["id"], "09:00", "12:00"),
            headers=stranger_headers,
        )

        validate_error(read, ApiErrorId.ERR_NOT_PASS_OWNER.value, 403)
        validate_error(booking, ApiErrorId.ERR_NOT_PASS_OWNER.value, 403)
        assert_day_counters(get_park_day(api, day["id"]), reserved=0, grant=0)

    def test_the_owner_and_the_clerk_are_both_admitted(self, api, default_clock):
        """The rule is scoped to the Passholder role, so staff are unaffected.

        PRD: "This applies to reservation creation, reservation cancellation, appealing a
        sharing case, and reading a single season pass."

        Design: Corner/errors/passholder_cannot_touch_another_holders_pass
        """
        _, _, owner_pass, _ = self._two_holders_one_pass(api)

        by_owner = validate_success(
            api.get_season_pass(owner_pass.id, headers=owner_pass.headers)
        )
        by_clerk = validate_success(api.get_season_pass(owner_pass.id, headers=clerk_headers()))

        assert by_owner["id"] == owner_pass.id, "the owner should read their own pass"
        assert by_clerk["id"] == owner_pass.id, "the clerk should read any pass"


class TestTierNotPublishedCoversThreeCauses:
    """One code answers a bad transition, a blocked retirement and a draft sale."""

    def _published_silver_and_draft_bronze(self, api):
        program = create_program(api)
        bronze = create_tier(api, program["id"], publish=False, name="BRONZE", tier_rank=1)
        silver = create_tier(
            api,
            program["id"],
            name="SILVER",
            tier_rank=2,
            base_price_cents=18000,
            in_park_discount_pct=0.10,
            peak_reservation_quota=3,
            parking_benefit="DISCOUNT",
        )
        advance_program(api, program["id"], ProgramStatus.SALES_OPEN.value)
        holder = create_passholder(api, email="live@example.com")
        sell_pass(api, program["id"], silver["id"], holder["id"])
        return program, bronze, silver

    def test_republishing_a_published_tier_and_retiring_one_with_a_live_pass_both_fail(
        self, api, default_clock
    ):
        """`PUBLISHED` is not reachable from `PUBLISHED`, and a live pass pins the tier.

        PRD: "A `target_status` unreachable from the tier's current `status`, or a
        retirement attempt that still has live passes on the tier, is rejected with
        `ERR_TIER_NOT_PUBLISHED` (HTTP 409); the same code answers a publish attempt made
        while the programme has already moved past `SALES_OPEN`."

        Design: Corner/errors/tier_not_published_code_covers_both_the_transition_and_the_reference_rule
        """
        _, _, silver = self._published_silver_and_draft_bronze(api)

        republish = api.set_tier_status(
            silver["id"],
            tier_status_payload(TierStatus.PUBLISHED.value),
            headers=program_admin_headers(),
        )
        retire = api.set_tier_status(
            silver["id"],
            tier_status_payload(TierStatus.RETIRED.value),
            headers=program_admin_headers(),
        )

        validate_error(republish, ApiErrorId.ERR_TIER_NOT_PUBLISHED.value, 409)
        validate_error(retire, ApiErrorId.ERR_TIER_NOT_PUBLISHED.value, 409)
        still = validate_success(api.get_pass_tier(silver["id"], headers=program_admin_headers()))
        assert still["status"] == TierStatus.PUBLISHED.value, (
            f"both refusals must leave the tier PUBLISHED, got {still['status']!r}"
        )

    def test_selling_on_a_draft_tier_is_answered_by_the_same_code(self, api, default_clock):
        """The reference rule reuses the code the transition rule owns.

        PRD: "Selling a pass, renewing into a tier, or quoting an upgrade whose referenced
        tier is not in `PUBLISHED` is also refused with `ERR_TIER_NOT_PUBLISHED`."

        Design: Corner/errors/tier_not_published_code_covers_both_the_transition_and_the_reference_rule
        """
        program, bronze, _ = self._published_silver_and_draft_bronze(api)
        buyer = create_passholder(
            api, full_name="Ben Holder", email="draft-buyer@example.com", date_of_birth="1988-06-11"
        )

        response = api.create_season_pass(
            season_pass_payload(program["id"], bronze["id"], buyer["id"]), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_TIER_NOT_PUBLISHED.value, 409)
        _, meta = _passes(api, passholder_id=buyer["id"])
        assert meta["total_count"] == 0, (
            f"the refused sale must not mint a pass, got {meta['total_count']!r}"
        )


class TestTheTierMustBelongToTheProgrammeBeingSoldUnder:
    """A published tier from the wrong programme is still refused."""

    def test_a_sale_priced_off_another_programmes_tier_is_refused(self, api, default_clock):
        """Only the referential rule can catch this: the tier exists and is published.

        PRD: "Four guards apply beyond the programme-status and tier-published checks
        already stated: the tier's programme must match the programme being sold under, else
        `ERR_TIER_PROGRAM_MISMATCH`; and the holder must not already own a pass in this
        programme whose `pass_status` is `PENDING_PROCESSING`, `ACTIVE` or `SUSPENDED`, else
        `ERR_DUPLICATE_ACTIVE_PASS` (HTTP 422)."

        Design: Corner/errors/tier_from_another_program_cannot_be_sold
        """
        first = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        second = build_program(
            api,
            tiers=(BRONZE,),
            status=ProgramStatus.SALES_OPEN.value,
            season_year=2027,
            park_name="Harbor Bay",
        )
        holder = create_passholder(api, email="cross@example.com")

        response = api.create_season_pass(
            season_pass_payload(first.id, second.tier_id("BRONZE"), holder["id"]),
            headers=clerk_headers(),
        )

        validate_error(response, ApiErrorId.ERR_TIER_PROGRAM_MISMATCH.value, 422)
        sold = sell_pass(api, first.id, first.tier_id("BRONZE"), holder["id"])
        assert sold["contract_value_cents"] == 12000, (
            "the accepted sale should be priced off its own programme's tier, got "
            f"{sold['contract_value_cents']!r}"
        )
        _, meta = _passes(api, program_id=first.id)
        assert meta["total_count"] == 1, (
            f"exactly one pass should exist in the programme, got {meta['total_count']!r}"
        )


class TestRenewalAndReinstateStateCodes:
    """Three state codes on the renewal path, each from its own precondition."""

    def _two_programmes_and_two_passes(self, api):
        first = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        create_park_day(api, first.id, "2026-09-01")
        active = build_active_pass(
            api, first, tier_name="BRONZE", holder_overrides={"email": "renew-active@example.com"}
        )
        pending = build_pending_pass(
            api, first, tier_name="BRONZE", holder_overrides={"email": "renew-pending@example.com"}
        )
        advance_program(api, first.id, ProgramStatus.SEASON_ACTIVE.value)
        second = build_program(
            api,
            tiers=(BRONZE,),
            status=ProgramStatus.SEASON_ACTIVE.value,
            season_year=2027,
            park_name="Summit Ridge",
        )
        return first, second, active, pending

    def test_an_active_pass_cannot_be_reinstated_and_a_season_active_target_cannot_be_renewed_into(
        self, api, default_clock
    ):
        """Reinstatement needs a suspension; renewal needs a target in `RENEWAL_OPEN`.

        PRD: "Reinstatement requires the pass's `pass_status` to be `SUSPENDED`; a pass in
        any other access state is refused with `ERR_PASS_NOT_SUSPENDED` (HTTP 409), and this
        check precedes the cure-amount arithmetic."

        Design: Corner/errors/renewal_and_reinstate_state_rules_are_each_triggerable
        """
        _, second, active, _ = self._two_programmes_and_two_passes(api)

        cure = api.reinstate_season_pass(
            active.id, reinstate_payload(0), headers=clerk_headers()
        )
        renewal = api.renew_season_pass(
            active.id,
            renew_payload(second.id, second.tier_id("BRONZE")),
            headers=clerk_headers(),
        )

        validate_error(cure, ApiErrorId.ERR_PASS_NOT_SUSPENDED.value, 409)
        validate_error(renewal, ApiErrorId.ERR_PROGRAM_NOT_IN_RENEWAL.value, 409)
        assert_pass_dimensions(get_pass(api, active.id), pass_status=PassStatus.ACTIVE.value)

    def test_a_pass_still_awaiting_processing_is_not_renewable(self, api, default_clock):
        """With the target legally open, the pass's own state is the blocking rung.

        PRD: "The target programme's `status` must be exactly `RENEWAL_OPEN`; any other
        status is refused with `ERR_PROGRAM_NOT_IN_RENEWAL` (HTTP 409), and that check
        precedes the `ERR_TIER_NOT_PUBLISHED` check on the target tier, which in turn
        precedes the `ERR_PASS_NOT_RENEWABLE` check and then the
        `ERR_TIER_PROGRAM_MISMATCH` check requiring the target tier to belong to the target
        programme."

        Design: Corner/errors/renewal_and_reinstate_state_rules_are_each_triggerable
        """
        _, second, _, pending = self._two_programmes_and_two_passes(api)
        advance_program(api, second.id, ProgramStatus.RENEWAL_OPEN.value)

        response = api.renew_season_pass(
            pending.id,
            renew_payload(second.id, second.tier_id("BRONZE")),
            headers=clerk_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PASS_NOT_RENEWABLE.value, 409)
        _, meta = _passes(api, program_id=second.id)
        assert meta["total_count"] == 0, (
            f"no renewal pass should have been minted, got {meta['total_count']!r}"
        )


class TestRepeatActionsOnTerminalRows:
    """A second attempt on a finished row gets the state code, not a silent success."""

    def _finished_rows(self, api):
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
        first_day = create_park_day(api, program.id, "2026-09-01")
        second_day = create_park_day(api, program.id, "2026-09-02")
        assignment = create_blockout(api, program.tier_id("BRONZE"), second_day["id"])
        lift_blockout(api, assignment["id"], reason="Promo weekend opened up")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            CreditMode.PAID_TO_DATE.value,
        )
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        visit = record_visit(api, pass_ctx.id, first_day["id"], "2026-09-01T10:00:00Z")
        close_visit(api, visit["id"], 2500)
        return program, pass_ctx, assignment, order, visit

    def test_a_closed_visit_and_a_lifted_blockout_each_refuse_the_second_call(
        self, api, default_clock
    ):
        """The first result stands and the second call is answered with its own code.

        PRD: "A visit whose `status` is not `OPEN` is refused with
        `ERR_VISIT_ALREADY_CLOSED` (HTTP 409)."

        Design: Corner/errors/repeat_actions_on_terminal_rows_return_their_state_codes
        """
        _, _, assignment, _, visit = self._finished_rows(api)

        second_close = api.close_visit(
            visit["id"], close_visit_payload(3000), headers=gate_agent_headers()
        )
        second_lift = api.lift_blockout_assignment(
            assignment["id"], lift_payload("Second attempt"), headers=program_admin_headers()
        )

        validate_error(second_close, ApiErrorId.ERR_VISIT_ALREADY_CLOSED.value, 409)
        validate_error(second_lift, ApiErrorId.ERR_ASSIGNMENT_ALREADY_LIFTED.value, 409)
        stored = validate_success(api.get_visit(visit["id"], headers=gate_agent_headers()))
        assert stored["spend_cents"] == 2500, (
            f"the first close should stand, got {stored['spend_cents']!r}"
        )
        blocked = validate_success(
            api.get_blockout_assignment(assignment["id"], headers=program_admin_headers())
        )
        assert blocked["lift_reason"] == "Promo weekend opened up", (
            f"the original lift reason should survive, got {blocked['lift_reason']!r}"
        )

    def test_an_order_that_was_never_applied_cannot_be_reversed(self, api, default_clock):
        """Reversal is defined on `APPLIED`, so a quote is not reversible.

        PRD: "The order must be in `APPLIED` and the pass must still sit on the order's
        `target_tier_id`; otherwise the request is refused with
        `ERR_UPGRADE_ORDER_NOT_ACTIONABLE`."

        Design: Corner/errors/repeat_actions_on_terminal_rows_return_their_state_codes
        """
        program, pass_ctx, _, order, _ = self._finished_rows(api)

        response = api.reverse_upgrade_order(
            order["id"],
            reverse_upgrade_payload("Nothing to reverse yet"),
            headers=compliance_officer_headers(),
        )

        validate_error(response, ApiErrorId.ERR_UPGRADE_ORDER_NOT_ACTIONABLE.value, 409)
        still = validate_success(api.get_upgrade_order(order["id"], headers=clerk_headers()))
        assert still["status"] == UpgradeOrderStatus.QUOTED.value, (
            f"the refused reversal leaves the order QUOTED, got {still['status']!r}"
        )
        assert get_pass(api, pass_ctx.id)["tier_id"] == program.tier_id("BRONZE"), (
            "the pass should still sit on its original tier"
        )


class TestSharingCaseStateAndAppealLimit:
    """Deciding needs a review; appealing needs an unspent round."""

    def _open_case(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        day = create_park_day(api, program.id, "2026-09-01")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        visit = record_visit(
            api, pass_ctx.id, day["id"], "2026-09-01T10:00:00Z", photo_match="MISMATCH"
        )
        case = open_case(api, pass_ctx.id, [visit["id"]], agent_user_id="gate-user-g1")
        return program, pass_ctx, case

    def test_an_open_case_cannot_be_decided(self, api, default_clock):
        """Adjudication is defined on `UNDER_REVIEW` only.

        PRD: "It requires the case to be in `UNDER_REVIEW`, and again
        `ERR_INVALID_CASE_STATE` answers any other state."

        Design: Corner/errors/sharing_case_actions_enforce_the_required_state_and_the_single_appeal
        """
        _, _, case = self._open_case(api)

        response = api.decide_sharing_case(
            case["id"],
            decide_payload("SUBSTANTIATED", "Too early"),
            headers=make_compliance_officer_headers("officer-o1"),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value, 409)
        still = validate_success(
            api.get_sharing_case(case["id"], headers=compliance_officer_headers())
        )
        assert still["case_status"] == CaseStatus.OPEN.value, (
            f"the refused decision leaves the case OPEN, got {still['case_status']!r}"
        )
        assert still["review_round"] == 0, (
            f"no review has happened yet, got review_round {still['review_round']!r}"
        )

    def test_the_second_appeal_is_refused_by_the_round_limit(self, api, default_clock):
        """After the one permitted appeal the limit rule answers, not the state rule.

        PRD: "Exactly one appeal is permitted per case, enforced by the requirement that
        `review_round` be less than 2 at the time of the appeal; a case whose `review_round`
        has already reached 2 is refused with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409), and
        that check follows the `ERR_INVALID_CASE_STATE` check that requires the case to be
        in `SUBSTANTIATED`."

        Design: Corner/errors/sharing_case_actions_enforce_the_required_state_and_the_single_appeal
        """
        _, pass_ctx, case = self._open_case(api)
        review_case(api, case["id"], officer_user_id="officer-o1")
        decide_case(
            api,
            case["id"],
            "SUBSTANTIATED",
            rationale="Two holders on one pass",
            officer_user_id="officer-o1",
        )
        appeal_case(api, case["id"], pass_ctx.holder_id, statement="It was my own entry")
        second_round = review_case(api, case["id"], officer_user_id="officer-o1")
        assert second_round["review_round"] == 2, (
            f"the appeal review is the second round, got {second_round['review_round']!r}"
        )
        decide_case(
            api,
            case["id"],
            "SUBSTANTIATED",
            rationale="Appeal denied",
            officer_user_id="officer-o1",
        )

        response = api.appeal_sharing_case(
            case["id"],
            appeal_payload("Second appeal"),
            headers=make_passholder_headers(pass_ctx.holder_id),
        )

        validate_error(response, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, 409)
        assert_pass_dimensions(get_pass(api, pass_ctx.id), pass_status=PassStatus.REVOKED.value)


class TestSharingCaseEvidenceMustBeReal:
    """An empty list and foreign evidence are both invalid; a bad id is a 404."""

    def _two_passes_with_visits(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        day = create_park_day(api, program.id, "2026-09-01")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        first = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "evidence-a@example.com"}
        )
        second = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "evidence-b@example.com"}
        )
        first_visit = record_visit(api, first.id, day["id"], "2026-09-01T10:00:00Z")
        second_visit = record_visit(
            api, second.id, day["id"], "2026-09-01T10:05:00Z", gate_code="SOUTH"
        )
        return first, second, first_visit, second_visit

    def test_an_empty_list_foreign_evidence_and_an_unknown_visit_are_distinguished(
        self, api, default_clock
    ):
        """Existence answers before the evidence rule, and both evidence faults share a code.

        PRD: "The evidence must be real: an empty `evidence_visit_ids` array, or any cited
        visit whose `season_pass_id` differs from the case's `season_pass_id`, is refused
        with `ERR_INVALID_EVIDENCE` (HTTP 422); a cited visit that does not exist at all is
        refused earlier with `ERR_VISIT_NOT_FOUND`."

        Design: Corner/errors/sharing_case_evidence_must_belong_to_the_named_pass
        """
        first, _, first_visit, second_visit = self._two_passes_with_visits(api)

        empty = api.create_sharing_case(
            sharing_case_payload(first.id, [], "No evidence attached"),
            headers=gate_agent_headers(),
        )
        foreign = api.create_sharing_case(
            sharing_case_payload(first.id, [second_visit["id"]], "Evidence from the wrong pass"),
            headers=gate_agent_headers(),
        )
        unknown = api.create_sharing_case(
            sharing_case_payload(first.id, [UNKNOWN_UUID], "Evidence that does not exist"),
            headers=gate_agent_headers(),
        )

        validate_error(empty, ApiErrorId.ERR_INVALID_EVIDENCE.value, 422)
        validate_error(foreign, ApiErrorId.ERR_INVALID_EVIDENCE.value, 422)
        validate_error(unknown, ApiErrorId.ERR_VISIT_NOT_FOUND.value, 404)
        opened = open_case(
            api, first.id, [first_visit["id"]], note="Valid evidence", agent_user_id="gate-user-g1"
        )
        assert opened["case_status"] == CaseStatus.OPEN.value, (
            f"valid evidence should open the case, got {opened['case_status']!r}"
        )
        assert opened["opened_by_user_id"] == "gate-user-g1", (
            f"the opening agent should be recorded, got {opened['opened_by_user_id']!r}"
        )
        assert opened["opened_by_role"] == "GATE_AGENT", (
            f"the opening role should be recorded, got {opened['opened_by_role']!r}"
        )
        _, meta = validate_paginated(
            api.list_sharing_cases(
                headers=compliance_officer_headers(), params={"season_pass_id": first.id}
            )
        )
        assert meta["total_count"] == 1, (
            f"the three refused calls created nothing, got {meta['total_count']!r}"
        )


class TestThreeGateRefusalsWithThreeCodes:
    """Readiness, the date match and the transfer hold each have their own code."""

    def _gate_world(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        first_day = create_park_day(api, program.id, "2026-09-01")
        second_day = create_park_day(api, program.id, "2026-09-02")
        held = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "held@example.com"}
        )
        clean = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "clean@example.com"}
        )
        unprocessed = build_pending_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "unprocessed@example.com"}
        )
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        evidence = record_visit(
            api, held.id, first_day["id"], "2026-09-01T10:00:00Z", photo_match="MISMATCH"
        )
        open_case(api, held.id, [evidence["id"]], agent_user_id="gate-user-g1")
        return program, first_day, second_day, held, clean, unprocessed

    def test_an_unprocessed_pass_is_refused_for_its_missing_photograph(self, api, default_clock):
        """Readiness sits above the general access-state check on purpose.

        PRD: "A pass whose `photo_captured` is false or whose `identity_bound` is false is
        refused with `ERR_PHOTO_NOT_CAPTURED` (HTTP 422)."

        Design: Corner/errors/gate_guards_reject_an_unprocessed_pass_a_wrong_date_and_a_held_pass
        """
        _, first_day, _, _, _, unprocessed = self._gate_world(api)

        response = api.create_visit(
            visit_payload(
                unprocessed.id, first_day["id"], "2026-09-01T11:00:00Z", photo_match="NOT_CHECKED"
            ),
            headers=gate_agent_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PHOTO_NOT_CAPTURED.value, 422)
        row = get_pass(api, unprocessed.id)
        assert row["photo_captured"] is False and row["identity_bound"] is False, (
            f"the pass should still be unprocessed, got {row['photo_captured']!r} "
            f"and {row['identity_bound']!r}"
        )

    def test_a_wrong_dated_entry_and_a_held_pass_are_each_refused_by_their_own_rule(
        self, api, default_clock
    ):
        """The date match and the transfer hold are separate rules with separate codes.

        PRD: "An `entry_at` whose calendar date differs from the park day's
        `calendar_date` is refused with `ERR_ENTRY_DATE_MISMATCH` (HTTP 422)."

        Design: Corner/errors/gate_guards_reject_an_unprocessed_pass_a_wrong_date_and_a_held_pass
        """
        _, _, second_day, held, clean, _ = self._gate_world(api)

        wrong_date = api.create_visit(
            visit_payload(clean.id, second_day["id"], "2026-09-01T11:05:00Z"),
            headers=gate_agent_headers(),
        )
        on_hold = api.create_visit(
            visit_payload(held.id, second_day["id"], "2026-09-02T10:00:00Z"),
            headers=gate_agent_headers(),
        )

        validate_error(wrong_date, ApiErrorId.ERR_ENTRY_DATE_MISMATCH.value, 422)
        validate_error(on_hold, ApiErrorId.ERR_PASS_TRANSFER_PROHIBITED.value, 422)
        _, meta = validate_paginated(
            api.list_visits(headers=gate_agent_headers(), params={"park_day_id": second_day["id"]})
        )
        assert meta["total_count"] == 0, (
            f"neither refused scan should have recorded a visit, got {meta['total_count']!r}"
        )


class TestTwoUniquenessScopesOnOneDay:
    """(tier, day) for a blockout and (pass, day) for a booking."""

    def _blocked_day_with_one_booking(self, api):
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
        day = create_park_day(api, program.id, "2026-09-01")
        create_blockout(api, program.tier_id("GOLD"), day["id"])
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        booking = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")
        return program, day, pass_ctx, booking

    def test_a_second_active_blockout_on_the_same_pair_is_refused(self, api, default_clock):
        """The pair is unique while the first assignment is still active.

        PRD: "Two guards protect the pairing: a tier whose programme differs from the park
        day's programme is rejected with `ERR_PARK_DAY_PROGRAM_MISMATCH` (HTTP 422), and a
        second active blockout for the same `tier_id` and `park_day_id` pair is rejected
        with `ERR_DUPLICATE_BLOCKOUT_ASSIGNMENT` (HTTP 422)."

        Design: Corner/errors/duplicate_blockout_and_duplicate_reservation_are_rejected
        """
        program, day, _, _ = self._blocked_day_with_one_booking(api)
        fresh = get_park_day(api, day["id"])

        response = api.create_blockout_assignment(
            blockout_payload(program.tier_id("GOLD"), day["id"], fresh["version"]),
            headers=program_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_BLOCKOUT_ASSIGNMENT.value, 422)
        _, meta = validate_paginated(
            api.list_blockout_assignments(
                headers=program_admin_headers(), params={"park_day_id": day["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the day should still carry one assignment, got {meta['total_count']!r}"
        )

    def test_a_second_booking_on_the_same_day_is_refused_even_at_a_free_hour(
        self, api, default_clock
    ):
        """The scope is one booking per pass per day, whatever the window.

        PRD: "A pass that already holds a reservation on that day whose `status` is
        `CONFIRMED` or `REDEEMED` is refused with `ERR_DUPLICATE_RESERVATION` (HTTP 422) —
        one booking per pass per day; a previously cancelled or no-showed reservation does
        not block a rebooking."

        Design: Corner/errors/duplicate_blockout_and_duplicate_reservation_are_rejected
        """
        _, day, pass_ctx, booking = self._blocked_day_with_one_booking(api)

        response = api.create_reservation(
            reservation_payload(pass_ctx.id, day["id"], "15:00", "18:00"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_RESERVATION.value, 422)
        assert_day_counters(get_park_day(api, day["id"]), reserved=1)
        cancel_reservation(api, booking["id"])
        rebooked = book_reservation(api, pass_ctx.id, day["id"], "15:00", "18:00")
        assert rebooked["arrival_window_start"].startswith("15:00"), (
            "a cancelled booking should not block the same window, got "
            f"{rebooked['arrival_window_start']!r}"
        )


class TestPaymentPlanEnrolmentBounds:
    """The count range and the down-payment floor are both boundary rules."""

    def _plan_ready_pass(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        return program, pass_ctx

    def test_a_count_outside_three_through_ten_is_refused_at_both_ends(self, api, default_clock):
        """2 and 11 are both outside the inclusive range.

        PRD: "First, an `installment_count` outside the inclusive range 3 through 10 is
        rejected with `ERR_INSTALLMENT_COUNT_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/errors/payment_plan_enrollment_bounds_are_rejected
        """
        _, pass_ctx = self._plan_ready_pass(api)
        version = get_pass(api, pass_ctx.id)["version"]

        for count in (2, 11):
            response = api.create_payment_plan(
                pass_ctx.id,
                payment_plan_payload(4000, count, "2026-09-01", version),
                headers=clerk_headers(),
            )
            validate_error(response, ApiErrorId.ERR_INSTALLMENT_COUNT_OUT_OF_RANGE.value, 422)

    def test_the_down_payment_floor_is_inclusive_at_a_fifth_of_the_contract(
        self, api, default_clock
    ):
        """2399 is below the 2400 floor; 2400 itself enrols and amortises.

        PRD: "Second, the park requires a fifth of the contract as a down payment: the
        minimum acceptable down payment is the pass's `contract_value_cents` multiplied by
        twenty hundredths, rounded half up to a whole number of cents, and a
        `down_payment_cents` strictly below that figure is rejected with
        `ERR_DOWN_PAYMENT_TOO_LOW` (HTTP 422)."

        Design: Corner/errors/payment_plan_enrollment_bounds_are_rejected
        """
        _, pass_ctx = self._plan_ready_pass(api)
        version = get_pass(api, pass_ctx.id)["version"]

        refused = api.create_payment_plan(
            pass_ctx.id,
            payment_plan_payload(2399, 4, "2026-09-01", version),
            headers=clerk_headers(),
        )
        validate_error(refused, ApiErrorId.ERR_DOWN_PAYMENT_TOO_LOW.value, 422)

        plan = validate_success(
            api.create_payment_plan(
                pass_ctx.id,
                payment_plan_payload(2400, 4, "2026-09-01", version),
                headers=clerk_headers(),
            ),
            201,
        )

        assert plan["installment_count"] == 4, (
            f"the accepted plan should carry four instalments, got {plan['installment_count']!r}"
        )
        assert plan["financed_amount_cents"] == 11100, (
            "the financed amount is the contract less the down payment plus the setup fee, got "
            f"{plan['financed_amount_cents']!r}"
        )
        assert plan["monthly_amount_cents"] == 2775, (
            f"11100 over four rows is 2775 each, got {plan['monthly_amount_cents']!r}"
        )
        rows = plan_installments(api, plan["id"])
        assert [row["amount_cents"] for row in rows] == [2775, 2775, 2775, 2775], (
            f"every row should be 2775, got {[row['amount_cents'] for row in rows]}"
        )


class TestUpgradeQuoteAndPaymentRules:
    """A downgrade is not an upgrade, and the apply step wants the exact total."""

    def _two_passes_and_a_quote(self, api):
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
        gold_pass = build_active_pass(
            api, program, tier_name="GOLD", holder_overrides={"email": "gil@example.com"}
        )
        bronze_pass = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "ben@example.com"}
        )
        order = quote_upgrade(
            api,
            bronze_pass.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            CreditMode.PAID_TO_DATE.value,
        )
        return program, gold_pass, bronze_pass, order

    def test_both_branches_of_the_not_an_upgrade_rule_are_reachable(self, api, default_clock):
        """A cheaper target and a source that is not the pass's tier share one code.

        PRD: "and finally, if the target tier's `base_price_cents` is less than or equal to
        the source tier's `base_price_cents`, or if the supplied `source_tier_id` is not in
        fact the pass's current `tier_id`, the request is refused with `ERR_NOT_AN_UPGRADE`
        (HTTP 422)."

        Design: Corner/errors/upgrade_order_rules_reject_a_downgrade_and_a_wrong_payment
        """
        program, gold_pass, _, _ = self._two_passes_and_a_quote(api)

        downgrade = api.create_upgrade_order(
            upgrade_order_payload(
                gold_pass.id, program.tier_id("GOLD"), program.tier_id("BRONZE")
            ),
            headers=clerk_headers(),
        )
        wrong_source = api.create_upgrade_order(
            upgrade_order_payload(
                gold_pass.id, program.tier_id("BRONZE"), program.tier_id("GOLD")
            ),
            headers=clerk_headers(),
        )

        validate_error(downgrade, ApiErrorId.ERR_NOT_AN_UPGRADE.value, 422)
        validate_error(wrong_source, ApiErrorId.ERR_NOT_AN_UPGRADE.value, 422)
        _, meta = validate_paginated(
            api.list_upgrade_orders(
                headers=clerk_headers(), params={"season_pass_id": gold_pass.id}
            )
        )
        assert meta["total_count"] == 0, (
            f"neither refused quote should exist, got {meta['total_count']!r}"
        )

    def test_the_payment_must_equal_the_total_due_including_the_admin_fee(
        self, api, default_clock
    ):
        """6000 is the net delta; the order is due 7000 with the fee.

        PRD: "and a `payment_amount_cents` that does not exactly equal the order's
        `total_due_cents` is refused with `ERR_UPGRADE_PAYMENT_INSUFFICIENT` (HTTP 422), in
        that order."

        Design: Corner/errors/upgrade_order_rules_reject_a_downgrade_and_a_wrong_payment
        """
        program, _, bronze_pass, order = self._two_passes_and_a_quote(api)
        assert order["total_due_cents"] == 7000, (
            f"the quote should total the 6000 net plus the 1000 fee, got {order['total_due_cents']!r}"
        )

        short = api.apply_upgrade_order(
            order["id"], apply_upgrade_payload(6000), headers=clerk_headers()
        )
        validate_error(short, ApiErrorId.ERR_UPGRADE_PAYMENT_INSUFFICIENT.value, 422)
        quoted = validate_success(api.get_upgrade_order(order["id"], headers=clerk_headers()))
        assert quoted["status"] == UpgradeOrderStatus.QUOTED.value, (
            f"the refused payment leaves the order QUOTED, got {quoted['status']!r}"
        )

        applied = validate_success(
            api.apply_upgrade_order(
                order["id"], apply_upgrade_payload(7000), headers=clerk_headers()
            )
        )

        assert applied["status"] == UpgradeOrderStatus.APPLIED.value, (
            f"the exact payment should apply the order, got {applied['status']!r}"
        )
        moved = get_pass(api, bronze_pass.id)
        assert moved["tier_id"] == program.tier_id("GOLD"), "the pass should move onto GOLD"
        assert moved["paid_to_date_cents"] == 19000, (
            f"12000 already paid plus the 7000 tendered is 19000, got {moved['paid_to_date_cents']!r}"
        )


class TestDayCapacityIsCheckedBeforeTheWindow:
    """A day with a single slot refuses the second booking on the day rule."""

    def test_a_one_slot_day_refuses_the_second_booking_although_its_window_is_free(
        self, api, default_clock
    ):
        """The day-level rule fires first, so the window rule never speaks.

        PRD: "A day whose `reserved_count` has reached or passed its
        `reservation_slot_capacity` is refused with `ERR_PARK_DAY_CAPACITY_FULL` (HTTP 422)
        — the day as a whole is sold out."

        Design: Corner/errors/day_level_capacity_is_exhausted_before_the_window_rule_applies
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        tiny = create_park_day(
            api, program.id, "2026-09-01", capacity_total=10, forecast_attendance=9
        )
        first = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "tiny-a@example.com"}
        )
        second = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "tiny-b@example.com"}
        )
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        assert_day_posture(tiny, utilization=0.9000, slot_capacity=1, window_capacity=1)
        holding = book_reservation(api, first.id, tiny["id"], "09:00", "10:00")

        response = api.create_reservation(
            reservation_payload(second.id, tiny["id"], "15:00", "16:00"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_PARK_DAY_CAPACITY_FULL.value, 422)
        assert_day_counters(get_park_day(api, tiny["id"]), reserved=1, remaining=0)
        cancel_reservation(api, holding["id"])
        book_reservation(api, second.id, tiny["id"], "15:00", "16:00")
        assert_day_counters(get_park_day(api, tiny["id"]), reserved=1, released=1)
