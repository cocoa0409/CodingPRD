"""The global precedence ladder, read at the rungs where two rules collide.

Every case here breaks more than one rule at once, or breaks the same rule from
two different directions, so the reported code is the discriminating observation.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ABSENT_UUID,
    ADMIN_USER_ID,
    APPRAISER_USER_ID,
    CLOCK_2026_08_20,
    CLOCK_2026_10_05,
    OFFICER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_application_payload,
    create_landowner,
    create_parcel,
    engage_appraisal,
    funding_plan_payload,
    issue_offer,
    issue_offer_payload,
    list_commitments,
    make_appraisal_reviewer_headers,
    make_landowner_headers,
    read_application,
    read_parcel,
    read_source,
    requirement_of_type,
    set_clock,
    setup_accepted_application,
    setup_aggregate_guard_scenario,
    setup_filed_application,
    setup_offered_application,
    setup_program_with_round,
    setup_ranked_application,
    submit_appraisal,
    suspend_source_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]
REVIEWER = TEST_USERS["appraisal_reviewer_headers"]


class TestAuthenticationRungs:
    """Rungs 1 and 2, plus the one endpoint that sits outside them."""

    def test_a_missing_header_or_an_unrecognised_role_is_unauthenticated(self):
        """Neither half of the credential pair may be missing or misspelled.

        PRD §2.1: "Every request except the clock-setting operation described in
        §2.5 must carry two headers: `X-User-ID`, identifying the acting user, and
        `X-User-Role`, declaring the capacity in which that user is acting. If
        either header is absent, or if `X-User-Role` is not one of the six role
        names below spelled exactly, the request is rejected with
        `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/missing_x_user_id_header_or_unknown_role_returns_unauthenticated
        """
        landowner = create_landowner()
        parcel = create_parcel(landowner["id"])

        role_only = api_client.get_parcel(parcel["id"], {"X-User-Role": "ProgramAdmin"})
        validate_error(role_only, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        id_only = api_client.get_parcel(parcel["id"], {"X-User-ID": ADMIN_USER_ID})
        validate_error(id_only, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        # A well-formed identifier under a role name that is not one of the six
        # is still an authentication failure, never an authorisation failure.
        unknown_role = api_client.get_parcel(
            parcel["id"], {"X-User-ID": ADMIN_USER_ID, "X-User-Role": "Auditor"}
        )
        validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        with_both = validate_success(api_client.get_parcel(parcel["id"], ADMIN))
        assert with_both["status"] == "ELIGIBLE"

    def test_the_clock_endpoint_is_the_declared_exemption(self):
        """The clock accepts a request carrying no credential headers at all.

        PRD §2.5: "`POST /_clock/set_current_utc` moves the clock to the supplied
        `current_utc` instant and returns both `current_utc` and `previous_utc`;
        it is the one endpoint exempt from the authentication headers of §2.1, and
        it performs no state transitions of its own."

        Design: Corner/validations/missing_x_user_id_header_or_unknown_role_returns_unauthenticated
        """
        moved = validate_success(api_client.set_clock("2026-08-11T00:00:00Z", None))
        assert moved["current_utc"].startswith("2026-08-11")
        # Before the clock has ever been set it reads exactly 2026-08-01.
        assert moved["previous_utc"].startswith("2026-08-01")


class TestForbiddenRoleOutranksPathResolution:
    """Rung 3 against rung 4 on one nonexistent round."""

    def test_the_forbidden_role_is_reported_before_the_unknown_round_id(self):
        """A Landowner opening a round that does not exist hears about the role.

        PRD §2.11: "3. The role is permitted for the endpoint —
        `ERR_FORBIDDEN_ROLE`. 4. Every path identifier resolves — the
        entity-specific not-found code."

        Design: Corner/validations/priority_three_forbidden_role_is_reported_before_the_unknown_round_id
        """
        landowner = create_landowner()

        forbidden = api_client.open_funding_round(
            ABSENT_UUID, make_landowner_headers(landowner["id"])
        )
        validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        # With a permitted role the very next rung surfaces on the same request.
        missing = api_client.open_funding_round(ABSENT_UUID, ADMIN)
        validate_error(missing, ApiErrorId.ERR_ROUND_NOT_FOUND.value, 404)


class TestPathResolutionOutranksBodyShape:
    """Rung 4 against rung 6 on one malformed counter."""

    def test_the_unknown_application_id_is_reported_before_the_empty_body(self):
        """The same empty body is a 404 on a missing id and a 422 on a real one.

        PRD §2.10: "When a path contains an identifier, that identifier must
        resolve to an existing row of the endpoint's own entity type before any
        body parsing or business rule runs."

        Design: Corner/validations/unknown_path_id_is_reported_before_the_invalid_body_returns_not_found
        """
        scenario = setup_offered_application()
        application_id = scenario["application"]["id"]
        landowner_headers = make_landowner_headers(scenario["landowner"]["id"])

        absent = api_client.file_counter(ABSENT_UUID, {}, landowner_headers)
        validate_error(absent, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, 404)

        malformed = api_client.file_counter(application_id, {}, landowner_headers)
        # `counter_cents` is a required field, so the body fails rung 6.
        validate_error(malformed, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

        after = read_application(application_id)
        assert after["status"] == "OFFER_ISSUED"
        assert after["last_counter_cents"] is None
        assert after["version"] == scenario["application"]["version"]


class TestBodyShapeOutranksOwnership:
    """Rung 6 against rung 7 on one application filing."""

    def test_the_invalid_request_is_reported_before_the_ownership_failure(self):
        """A negative price on someone else's parcel reports the shape failure.

        PRD §2.11: "6. Request shape, types, enum members, string lengths and
        numeric domains — `ERR_INVALID_REQUEST`, or `ERR_WEIGHTS_NOT_NORMALIZED`
        for the program-weight sum. 7. Ownership — `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/invalid_request_is_reported_before_the_not_resource_owner_error
        """
        scenario = setup_program_with_round()
        owner = scenario["landowner"]
        parcel = create_parcel(owner["id"])
        intruder = create_landowner(legal_name="Vireo Ridge LLC", tax_id_last4="8802")
        intruder_headers = make_landowner_headers(intruder["id"])
        round_id = scenario["round"]["id"]

        # Both rules are broken at once: the price is out of domain and the
        # caller owns neither the parcel nor the declared landowner.
        both_broken = api_client.create_application(
            create_application_payload(
                round_id, parcel["id"], owner["id"], requested_price_cents=-1
            ),
            intruder_headers,
        )
        validate_error(both_broken, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

        # A well-formed body still fails on the parcel's landowner foreign key.
        wrong_parcel = api_client.create_application(
            create_application_payload(round_id, parcel["id"], intruder["id"]),
            intruder_headers,
        )
        validate_error(wrong_parcel, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        # Naming the true owner in the body does not help either.
        wrong_header = api_client.create_application(
            create_application_payload(round_id, parcel["id"], owner["id"]),
            intruder_headers,
        )
        validate_error(wrong_header, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        rows, meta = validate_paginated(api_client.list_applications(ADMIN))
        assert meta["total_count"] == 0
        assert rows == []
        assert read_parcel(parcel["id"])["status"] == "ELIGIBLE"


class TestConcurrencyOutranksState:
    """Rung 8 against rung 9 on a replayed offer."""

    def test_the_stale_version_is_reported_before_the_application_state_conflict(self):
        """Replaying the offer that already succeeded reports staleness.

        PRD §2.11: "Note in particular that concurrency sits above the state
        check: an offer carrying a stale `expected_application_version` against an
        application that is also in the wrong state reports the stale-version
        error, not the state error."

        Design: Corner/validations/stale_application_version_is_reported_before_the_application_state_conflict
        """
        scenario = setup_ranked_application()
        application_id = scenario["application"]["id"]
        ranked_version = read_application(application_id)["version"]

        set_clock(CLOCK_2026_10_05)
        offered = issue_offer(application_id, 175_550_000, "FULL_PURCHASE")
        assert offered["status"] == "OFFER_ISSUED"
        assert offered["version"] > ranked_version

        replay = api_client.issue_offer(
            application_id,
            issue_offer_payload(ranked_version, 175_550_000),
            OFFICER,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value, 412)
        assert read_application(application_id)["version"] == offered["version"]

        # Refreshing the version exposes the state rule that was masked.
        refreshed = api_client.issue_offer(
            application_id,
            issue_offer_payload(offered["version"], 175_550_000),
            OFFICER,
        )
        validate_error(refreshed, ApiErrorId.ERR_INVALID_APPLICATION_STATE.value, 409)

        after = read_application(application_id)
        assert after["current_offer_cents"] == 175_550_000
        assert after["version"] == offered["version"]


class TestAppraisalSegregationOfDuties:
    """Rung 10, reached from both identifiers the gate compares against."""

    @staticmethod
    def _submitted_appraisal() -> dict:
        scenario = setup_filed_application()
        appraisal = engage_appraisal(scenario["application"]["id"])
        assert appraisal["engaged_by_user_id"] == OFFICER_USER_ID
        set_clock(CLOCK_2026_08_20)
        submitted = submit_appraisal(appraisal["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["easement_value_cents"] == 175_550_000
        scenario["appraisal"] = submitted
        return scenario

    def test_neither_the_engaging_officer_nor_the_appraiser_may_review(self):
        """Both compared identifiers are barred, and both answers are 403.

        PRD §2.9: "An appraisal review must be performed by a user who is neither
        the officer who engaged the appraisal nor the appraiser who submitted it:
        `X-User-ID` must differ from both `engaged_by_user_id` and
        `appraiser_user_id` on that appraisal, otherwise the review is rejected
        with `ERR_APPRAISAL_REVIEW_SOD`."

        Design: Corner/validations/appraisal_review_by_the_engaging_officer_or_the_appraiser_is_rejected
        """
        scenario = self._submitted_appraisal()
        appraisal_id = scenario["appraisal"]["id"]

        as_engager = api_client.review_appraisal(
            appraisal_id,
            {"decision": "CERTIFY"},
            make_appraisal_reviewer_headers(OFFICER_USER_ID),
        )
        validate_error(as_engager, ApiErrorId.ERR_APPRAISAL_REVIEW_SOD.value, 403)

        as_appraiser = api_client.review_appraisal(
            appraisal_id,
            {"decision": "CERTIFY"},
            make_appraisal_reviewer_headers(APPRAISER_USER_ID),
        )
        validate_error(as_appraiser, ApiErrorId.ERR_APPRAISAL_REVIEW_SOD.value, 403)

        still = validate_success(api_client.get_appraisal(appraisal_id, ADMIN))
        assert still["status"] == "SUBMITTED"
        assert still["certified_by_user_id"] is None

    def test_a_rejection_needs_its_note_and_a_third_party_certifies(self):
        """The note is mandatory only on rejection; a distinct reviewer clears.

        PRD §3.4: "An `AppraisalReviewer` then decides, supplying a `decision` of
        `CERTIFY` or `REJECT` together with an optional `review_note` that becomes
        mandatory on rejection."

        Design: Corner/validations/appraisal_review_by_the_engaging_officer_or_the_appraiser_is_rejected
        """
        scenario = self._submitted_appraisal()
        appraisal_id = scenario["appraisal"]["id"]

        noteless = api_client.review_appraisal(
            appraisal_id, {"decision": "REJECT"}, REVIEWER
        )
        validate_error(noteless, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

        certified = validate_success(
            api_client.review_appraisal(
                appraisal_id,
                {"decision": "CERTIFY", "review_note": "comparable sales verified"},
                REVIEWER,
            )
        )
        assert certified["status"] == "CERTIFIED"
        assert (
            read_application(scenario["application"]["id"])[
                "certified_easement_value_cents"
            ]
            == 175_550_000
        )


class TestLienholderCoupling:
    """Rung 15's polymorphic-payload rule, from both directions."""

    def test_the_subordination_needs_the_recorded_name_and_no_one_else_may_carry_it(
        self,
    ):
        """A wrong name, a missing name and a stray name all report one code.

        PRD §3.7: "A `MORTGAGE_SUBORDINATION` submission must carry a
        `lienholder_name` equal to the parcel's `mortgage_lienholder_name`, and
        any submission of another type that carries `lienholder_name` at all is
        rejected — both failures report `ERR_LIENHOLDER_REQUIRED`."

        Design: Corner/validations/mortgage_subordination_submission_without_the_recorded_lienholder_is_rejected
        """
        scenario = setup_accepted_application()
        application_id = scenario["application"]["id"]
        assert scenario["parcel"]["mortgage_lienholder_name"] == "Midstate Farm Credit"
        subordination = requirement_of_type(application_id, "MORTGAGE_SUBORDINATION")
        title = requirement_of_type(application_id, "TITLE_COMMITMENT")

        omitted = api_client.submit_closing_requirement(
            subordination["id"], {}, OFFICER
        )
        validate_error(omitted, ApiErrorId.ERR_LIENHOLDER_REQUIRED.value, 409)

        wrong_name = api_client.submit_closing_requirement(
            subordination["id"], {"lienholder_name": "Keystone Savings"}, OFFICER
        )
        validate_error(wrong_name, ApiErrorId.ERR_LIENHOLDER_REQUIRED.value, 409)

        stray = api_client.submit_closing_requirement(
            title["id"],
            {"exception_count": 0, "lienholder_name": "Midstate Farm Credit"},
            OFFICER,
        )
        validate_error(stray, ApiErrorId.ERR_LIENHOLDER_REQUIRED.value, 409)
        assert (
            validate_success(api_client.get_closing_requirement(title["id"], ADMIN))[
                "status"
            ]
            == "OUTSTANDING"
        )

        accepted = validate_success(
            api_client.submit_closing_requirement(
                subordination["id"],
                {"lienholder_name": "Midstate Farm Credit"},
                OFFICER,
            )
        )
        assert accepted["status"] == "SUBMITTED"
        assert accepted["submitted_by_user_id"] == OFFICER_USER_ID

        after = read_application(application_id)
        assert after["closing_status"] == "PENDING_REQUIREMENTS"
        # A submission is not yet a satisfaction.
        assert after["requirement_satisfied_count"] == 0


class TestCounterTemporalBound:
    """Rung 13's two independent conditions under one error code."""

    def test_an_equal_counter_and_a_late_counter_report_the_same_code(self):
        """The expiry comparison is inclusive, so the boundary instant is good.

        PRD §3.5: "The counter must be strictly greater than the application's
        `current_offer_cents` and must arrive at or before
        `current_offer_expires_on`; failing either, the answer is
        `ERR_COUNTER_NOT_HIGHER`."

        Design: Corner/validations/counter_filed_after_the_offer_expiry_date_is_rejected
        """
        scenario = setup_offered_application(
            offer_cents=170_000_000, structure="FULL_PURCHASE"
        )
        application_id = scenario["application"]["id"]
        landowner_headers = make_landowner_headers(scenario["landowner"]["id"])
        assert scenario["application"]["current_offer_expires_on"].startswith(
            "2026-11-19"
        )

        equal = api_client.file_counter(
            application_id,
            {"counter_cents": 170_000_000, "rationale": "equal to the standing offer"},
            landowner_headers,
        )
        validate_error(equal, ApiErrorId.ERR_COUNTER_NOT_HIGHER.value, 409)

        # At the expiry instant itself the counter is still admissible.
        set_clock("2026-11-19T00:00:00Z")
        on_time = validate_success(
            api_client.file_counter(
                application_id,
                {
                    "counter_cents": 172_000_000,
                    "rationale": "filed on the expiry date itself",
                },
                landowner_headers,
            )
        )
        assert on_time["status"] == "COUNTERED"
        assert on_time["last_counter_cents"] == 172_000_000

        reoffered = issue_offer(
            application_id,
            173_000_000,
            "FULL_PURCHASE",
            offer_expires_on="2026-11-25T00:00:00Z",
        )
        assert reoffered["status"] == "OFFER_ISSUED"
        assert reoffered["current_offer_cents"] == 173_000_000
        assert reoffered["current_offer_expires_on"].startswith("2026-11-25")

        set_clock("2026-11-26T00:00:00Z")
        late = api_client.file_counter(
            application_id,
            {
                "counter_cents": 175_550_000,
                "rationale": "one day after the second offer expired",
            },
            landowner_headers,
        )
        # 175,550,000 clears both the strict-increase test and the certified
        # ceiling, so only the expiry can be the reason.
        validate_error(late, ApiErrorId.ERR_COUNTER_NOT_HIGHER.value, 409)

        after = read_application(application_id)
        assert after["status"] == "OFFER_ISSUED"
        # `negotiation_round_count` counts OFFER entries only: two were issued.
        assert after["negotiation_round_count"] == 2
        assert after["last_counter_cents"] == 172_000_000


class TestAggregateFundingGuardOrder:
    """Rung 20's four share tests, isolated one suspension at a time."""

    def test_each_suspension_moves_the_failure_down_the_declared_order(self):
        """One cost, four sweeps, four different aggregate verdicts.

        PRD §2.11: "20. Waterfall coverage and its share tests:
        `ERR_FUNDING_SHORTFALL`, then `ERR_FEDERAL_SHARE_EXCEEDED`, then
        `ERR_LOCAL_MATCH_SHORTFALL`, then `ERR_MATCH_RATIO_UNSATISFIED`."

        Design: Corner/validations/aggregate_funding_guards_fire_in_their_declared_order_as_sources_are_suspended
        """
        scenario = setup_aggregate_guard_scenario()
        application = scenario["application"]
        application_id = application["id"]
        sources = scenario["sources"]
        assert application["composite_score"] == 65.00
        assert application["certified_easement_value_cents"] == 25_000_000
        assert application["total_program_cost_cents"] == 25_500_000
        version = application["version"]
        payload = funding_plan_payload(version)

        def suspend(key: str, reason: str) -> None:
            suspended = validate_success(
                api_client.suspend_funding_source(
                    sources[key]["id"], suspend_source_payload(reason=reason), ADMIN
                )
            )
            assert suspended["status"] == "SUSPENDED"

        # Both federal tranches take floor(25,500,000 x 0.45) == 11,475,000, so
        # the federal total of 22,950,000 passes floor(25,500,000 x 0.50).
        federal = api_client.assemble_funding_plan(application_id, payload, ADMIN)
        validate_error(federal, ApiErrorId.ERR_FEDERAL_SHARE_EXCEEDED.value, 409)

        suspend("fed_b", "tranche B rescinded by the federal partner")
        # Now FED_A 11,475,000 + LOC_A 8,925,000 + STATE_A 5,100,000 covers the
        # cost, clears the federal cap and clears the 6,375,000 local minimum,
        # leaving only FED_A's two-to-one match unsatisfied at 14,025,000.
        match_ratio = api_client.assemble_funding_plan(application_id, payload, ADMIN)
        validate_error(match_ratio, ApiErrorId.ERR_MATCH_RATIO_UNSATISFIED.value, 409)

        suspend("loc_a", "county match withdrawn")
        # The only local participation left is the thin 1,275,000 sliver, which
        # is below the local minimum. The match ratio is still unsatisfied, but
        # the local-match test sits ahead of it in the declared order.
        local_match = api_client.assemble_funding_plan(application_id, payload, ADMIN)
        validate_error(local_match, ApiErrorId.ERR_LOCAL_MATCH_SHORTFALL.value, 409)

        suspend("state_b", "series B bond authorization lapsed")
        # FED_A 11,475,000 + STATE_A 10,200,000 + LOC_B 1,275,000 leaves a
        # 2,550,000 remainder, and the last non-zero take can absorb only the
        # 725,000 of headroom its 2,000,000 authority still has.
        shortfall = api_client.assemble_funding_plan(application_id, payload, ADMIN)
        validate_error(shortfall, ApiErrorId.ERR_FUNDING_SHORTFALL.value, 409)

        after = read_application(application_id)
        assert after["funding_plan_status"] == "UNFUNDED"
        assert after["funded_cost_cents"] is None
        assert after["version"] == version
        assert list_commitments({"application_id": application_id}) == []
        # Nothing was written against the sources that stayed ACTIVE either.
        for key in ("fed_a", "state_a", "loc_b"):
            source = read_source(sources[key]["id"])
            assert source["status"] == "ACTIVE"
            assert source["reserved_cents"] == 0
            assert source["committed_cents"] == 0
