"""The top of the validation ladder: auth, request shape, resolution, version.

Each test puts a request in front of the server that breaks more than one rule at
once wherever the ladder makes the ordering observable, and reads back the rows
the refusal was supposed to leave untouched.
"""
from test_helpers import (
    BASE_SCENARIO,
    BILLING,
    CONSULTANT,
    NON_EXISTENT_UUID,
    PRINCIPAL,
    RECORDER,
    api_client,
    build_user_headers,
    create_accommodation_term_payload,
    create_fee_schedule_payload,
    create_placement_payload,
    create_trial_engagement_payload,
    invoice_and_pay,
    ledger_adjustment_payload,
    propose_accommodation_term,
    provide_claim_info_payload,
    read_claim,
    read_client,
    read_milestone,
    read_requisition,
    record_payment_payload,
    register_candidate,
    setup_active_placement,
    setup_claim_under_review,
    setup_passed_trial,
    setup_scenario,
    setup_sourcing_requisition,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_HEADERS = {}
UNRECOGNISED_ROLE_HEADERS = build_user_headers("u_ops_1", "HouseManager")


class TestAuthenticationAndAuthorizationRungs:
    def test_01_missing_headers_outrank_an_unresolvable_path_id(self):
        """No headers on an id that resolves to nothing is 401, never 404.

        PRD §2.1: "If either header is absent or present but empty, the request is
        refused with `ERR_MISSING_AUTH_HEADER` (HTTP 401). This check runs before
        anything else at all — before path parameters are parsed, before the body
        is inspected — so an unauthenticated request naming a non-existent
        identifier still returns 401 rather than 404."

        Design: Corner/validations/missing_auth_headers_on_an_unknown_id_returns_unauthenticated
        """
        setup_scenario(stage="clock")

        validate_error(
            api_client.get_client(NON_EXISTENT_UUID, NO_HEADERS),
            "ERR_MISSING_AUTH_HEADER",
            401,
        )

    def test_02_a_role_outside_the_seven_is_refused_as_invalid(self):
        """Both headers are present, so the failure isolates the role spelling.

        PRD §2.1: "Seven roles are recognised, and the spellings are exact:
        `AgencyPrincipal`, `PlacementConsultant`, `VettingSpecialist`,
        `BillingAdministrator`, `ComplianceOfficer`, `Client`, and `Candidate`. A
        value of `X-User-Role` outside that set of seven is refused with
        `ERR_INVALID_ROLE` (HTTP 401)."

        Design: Corner/validations/an_unrecognised_role_header_is_invalid_role
        """
        scenario = setup_scenario(stage="household")

        validate_error(
            api_client.get_client(
                scenario["client"]["id"], UNRECOGNISED_ROLE_HEADERS
            ),
            "ERR_INVALID_ROLE",
            401,
        )

    def test_03_a_forbidden_role_never_learns_the_body_was_malformed(self):
        """The RBAC rung answers before the request-shape rung.

        PRD §2.1: "A recognised role that is not granted the requested operation
        by the permission matrix in §4 is refused with `ERR_UNAUTHORIZED` (HTTP
        403), and this refusal precedes request-shape validation — a forbidden
        role that also sends a malformed body receives 403, not 400."

        Design: Corner/validations/a_forbidden_role_sending_a_malformed_body_returns_forbidden
        """
        setup_scenario(stage="clock")

        payload = create_fee_schedule_payload()
        payload.pop("fee_percent_bps")

        validate_error(
            api_client.create_fee_schedule(payload, RECORDER),
            "ERR_UNAUTHORIZED",
            403,
        )

        _, meta = validate_paginated(api_client.list_fee_schedules(PRINCIPAL))
        assert meta["total_count"] == 0


class TestRequestShapeRungs:
    def test_04_an_absent_required_field_is_an_invalid_request(self):
        """The caller is permitted and every other field is well formed.

        PRD §2.11: "A field declared required by the endpoint that is absent or
        null yields `ERR_INVALID_REQUEST`; this same error also covers a string
        outside its declared length bounds and an email-shaped field that does not
        contain an `@` character."

        Design: Corner/validations/a_fee_band_missing_required_fee_percent_bps_is_rejected
        """
        setup_scenario(stage="clock")

        payload = create_fee_schedule_payload()
        payload.pop("fee_percent_bps")

        validate_error(
            api_client.create_fee_schedule(payload, PRINCIPAL),
            "ERR_INVALID_REQUEST",
            400,
        )

        _, meta = validate_paginated(api_client.list_fee_schedules(PRINCIPAL))
        assert meta["total_count"] == 0

    def test_05_a_role_type_outside_the_four_is_an_invalid_enum(self):
        """Nothing is missing, so the enum rung is the one that speaks.

        PRD §3.1: "Opening a search is done by a `PlacementConsultant` or by the
        household acting as `Client`. The request names the household through
        `client_id`, the `role_type` being searched (one of `ESTATE_MANAGER`,
        `HOUSEKEEPER`, `CHEF` or `CHAUFFEUR`), the `first_year_compensation_cents`
        being scoped (which must be at least 100,000 cents), and the
        `schedule_pattern` from `FIVE_TWO`, `SIX_ONE`, `ROTA_TWO_TWO` and
        `ON_CALL`; it may also carry `live_in_required`, which defaults to false,
        and an opening `scope_note`."

        PRD §2.11: "Then an enum-typed value outside its declared set yields
        `ERR_INVALID_ENUM`."

        Design: Corner/validations/an_unrecognised_role_type_enum_on_a_fee_band_is_rejected
        """
        setup_scenario(stage="clock")

        validate_error(
            api_client.create_fee_schedule(
                create_fee_schedule_payload(role_type="BUTLER"), PRINCIPAL
            ),
            "ERR_INVALID_ENUM",
            400,
        )

    def test_06_a_zero_basis_point_rate_is_out_of_range(self):
        """Zero sits one below the inclusive floor of the rate band.

        PRD §2.11: "Then a numeric field outside its accepted band yields
        `ERR_INVALID_RANGE`; the accepted bands are: no `_cents` field may be
        negative, `years_experience` must be 0 through 60, `weekly_hours` must be
        1 through 80, `days_off_per_week` must be 0 through 7, `fee_percent_bps`
        must be 1 through 10000, `guarantee_window_days` must be 1 through 365,
        `scope_items` must be non-empty, `limit` must be 1 through 200 and
        `offset` must not be negative."

        Design: Corner/validations/a_fee_percent_of_zero_basis_points_is_rejected
        """
        setup_scenario(stage="clock")

        validate_error(
            api_client.create_fee_schedule(
                create_fee_schedule_payload(fee_percent_bps=0), PRINCIPAL
            ),
            "ERR_INVALID_RANGE",
            400,
        )

        accepted = validate_success(
            api_client.create_fee_schedule(
                create_fee_schedule_payload(fee_percent_bps=1), PRINCIPAL
            ),
            201,
        )
        assert accepted["fee_percent_bps"] == 1

    def test_07_a_date_in_the_wrong_notation_is_a_format_failure(self):
        """A real date written the wrong way round fails the format rung.

        PRD §2.11: "Then a date that is not `YYYY-MM-DD`, a timestamp that is not
        RFC 3339 UTC with a trailing `Z`, or a month key that is not `YYYY-MM`
        yields `ERR_INVALID_DATE_FORMAT`."

        Design: Corner/validations/a_non_iso_effective_from_date_is_rejected
        """
        setup_scenario(stage="clock")

        validate_error(
            api_client.create_fee_schedule(
                create_fee_schedule_payload(effective_from="01/06/2026"), PRINCIPAL
            ),
            "ERR_INVALID_DATE_FORMAT",
            400,
        )

        _, meta = validate_paginated(api_client.list_fee_schedules(PRINCIPAL))
        assert meta["total_count"] == 0

    def test_08_a_ceiling_equal_to_the_floor_is_a_misordered_interval(self):
        """The rule treats a ceiling at or below the floor as the violation.

        PRD §2.11: "Then a mis-ordered interval yields `ERR_INVALID_INTERVAL`: an
        `end_at` at or before `start_at` when booking a trial, an
        `employment_end_month` earlier than `employment_start_month` when
        recording a reference, or a non-null `comp_band_ceiling_cents` at or below
        `comp_band_floor_cents` when publishing a fee band."

        Design: Corner/validations/a_fee_band_whose_ceiling_equals_its_floor_is_rejected
        """
        setup_scenario(stage="clock")

        validate_error(
            api_client.create_fee_schedule(
                create_fee_schedule_payload(
                    comp_band_floor_cents=5_000_000,
                    comp_band_ceiling_cents=5_000_000,
                ),
                PRINCIPAL,
            ),
            "ERR_INVALID_INTERVAL",
            400,
        )

        validate_success(
            api_client.create_fee_schedule(
                create_fee_schedule_payload(
                    comp_band_floor_cents=5_000_000,
                    comp_band_ceiling_cents=5_000_001,
                ),
                PRINCIPAL,
            ),
            201,
        )

    def test_09_a_zero_ledger_movement_has_its_own_error(self):
        """Zero is neither negative nor absent, so it is caught on its own rung.

        PRD §3.7: "`signed_amount_cents` may be positive or negative but must not
        be zero, and a zero amount is refused with `ERR_INVALID_LEDGER_AMOUNT`
        (HTTP 400)."

        Design: Corner/validations/a_zero_amount_ledger_adjustment_is_rejected
        """
        scenario = setup_scenario(stage="onboarded")
        client_id = scenario["client"]["id"]

        validate_error(
            api_client.create_ledger_adjustment(
                client_id, ledger_adjustment_payload(0), BILLING
            ),
            "ERR_INVALID_LEDGER_AMOUNT",
            400,
        )

        _, meta = validate_paginated(
            api_client.list_ledger_entries(client_id, BILLING)
        )
        assert meta["total_count"] == 0

        validate_success(
            api_client.create_ledger_adjustment(
                client_id, ledger_adjustment_payload(-100), BILLING
            ),
            201,
        )


class TestReferentialResolutionRungs:
    def test_10_an_unknown_path_id_reports_the_addressed_entity(self):
        """The segment being addressed picks the not-found error id.

        PRD §2.11: "**Referential resolution, in three steps.** An unresolvable
        path identifier yields that entity's not-found error; then an unresolvable
        body identifier yields the same per-entity catalogue; then rows that
        resolve but do not belong together yield
        `ERR_ENTITY_RELATIONSHIP_MISMATCH`."

        Design: Corner/validations/an_unknown_placement_in_the_path_returns_placement_not_found
        """
        setup_scenario(stage="clock")

        validate_error(
            api_client.get_placement(NON_EXISTENT_UUID, CONSULTANT),
            "ERR_PLACEMENT_NOT_FOUND",
            404,
        )

    def test_11_an_unknown_body_id_is_resolved_as_strictly_as_a_path_id(self):
        """The path requisition resolves; the 404 comes from the payload.

        PRD §2.11: "**Referential resolution, in three steps.** An unresolvable
        path identifier yields that entity's not-found error; then an unresolvable
        body identifier yields the same per-entity catalogue; then rows that
        resolve but do not belong together yield
        `ERR_ENTITY_RELATIONSHIP_MISMATCH`."

        Design: Corner/validations/an_unknown_candidate_in_a_trial_payload_returns_candidate_not_found
        """
        scenario = setup_sourcing_requisition()

        validate_error(
            api_client.create_trial_engagement(
                scenario["requisition"]["id"],
                create_trial_engagement_payload(NON_EXISTENT_UUID),
                CONSULTANT,
            ),
            "ERR_CANDIDATE_NOT_FOUND",
            404,
        )

        stored = read_requisition(scenario["requisition"])
        assert stored["status"] == "SOURCING"
        assert stored["active_trial_count"] == 0

    def test_12_an_offer_to_a_candidate_with_no_engagement_is_a_mismatch(self):
        """Both ids resolve, so the refusal is purely relational.

        PRD §3.6: "After the requisition and candidate have been resolved, the
        candidate must have at least one `TrialEngagement` on the named
        requisition at all, or the request is refused with
        `ERR_ENTITY_RELATIONSHIP_MISMATCH` (HTTP 409)."

        Design: Corner/validations/offering_a_candidate_who_never_tried_at_this_household_is_a_relationship_mismatch
        """
        scenario = setup_passed_trial()
        stranger = register_candidate(
            full_name="T. Vance",
            contact_email="tvance@mail.example",
            years_experience=6,
        )

        requisition = read_requisition(scenario["requisition"])
        validate_error(
            api_client.create_placement(
                create_placement_payload(
                    requisition["id"], stranger["id"], requisition["version"]
                ),
                CONSULTANT,
            ),
            "ERR_ENTITY_RELATIONSHIP_MISMATCH",
            409,
        )

        _, meta = validate_paginated(api_client.list_placements(CONSULTANT))
        assert meta["total_count"] == 0


class TestConcurrencyAndStateRungs:
    def test_13_a_stale_version_answers_before_the_live_in_rule(self):
        """The doubly-wrong proposal is told to re-read, not told about the
        candidate.

        PRD §2.11: "**Optimistic concurrency.** A supplied
        `expected_requisition_version`, `expected_candidate_version` or
        `expected_placement_version` that differs from the stored parent
        `version` yields the matching stale-version error. This runs after the
        parent has been resolved but before any state or business rule, so a
        stale version on a request that is also invalid for business reasons
        still returns 412."

        Design: Corner/validations/a_stale_requisition_version_outranks_a_live_in_incompatibility
        """
        scenario = setup_sourcing_requisition()
        candidate = register_candidate(live_in_willing=False)

        stale_version = read_requisition(scenario["requisition"])["version"]
        propose_accommodation_term(scenario["requisition"], candidate)

        validate_error(
            api_client.create_accommodation_term(
                scenario["requisition"]["id"],
                create_accommodation_term_payload(
                    candidate["id"],
                    stale_version,
                    live_in=True,
                    private_quarters=True,
                    imputed_accommodation_cents=300_000,
                ),
                CONSULTANT,
            ),
            "ERR_STALE_REQUISITION_VERSION",
            412,
        )

        terms, meta = validate_paginated(
            api_client.list_accommodation_terms(
                CONSULTANT, {"requisition_id": scenario["requisition"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert terms[0]["status"] == "PROPOSED"

    def test_14_provide_info_leaves_only_the_information_requested_state(self):
        """A claim under review has no provide-info edge to take.

        PRD §3.8: "The household answers by supplying an `info_note`, which is
        exclusive to the `Client` role and moves the claim `INFO_REQUESTED →
        UNDER_REVIEW`, appending the supplied note to `decision_note`; a claim in
        any other state is refused with `ERR_INVALID_STATE_TRANSITION`, and a
        terminal claim with `ERR_ENTITY_TERMINAL`."

        Design: Corner/validations/providing_information_on_a_claim_already_under_review_is_refused
        """
        scenario = setup_claim_under_review("REPLACEMENT")

        validate_error(
            api_client.provide_claim_info(
                scenario["claim"]["id"],
                provide_claim_info_payload(),
                scenario["client_headers"],
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        stored = read_claim(scenario["claim"])
        assert stored["status"] == "UNDER_REVIEW"
        assert stored["info_request_round"] == 0

    def test_15_a_paid_milestone_is_locked_even_against_the_exact_amount(self):
        """The repeat payment is fiscally correct, so terminality is the only
        reason left to refuse it.

        PRD §3.7: "The row must be `INVOICED` or `OVERDUE`, and any other
        non-terminal state is refused with `ERR_MILESTONE_NOT_INVOICED` (HTTP
        409) while a terminal row is refused with `ERR_ENTITY_TERMINAL`."

        Design: Corner/validations/a_paid_milestone_refuses_a_second_payment
        """
        scenario = setup_active_placement()
        paid = invoice_and_pay(scenario["milestones"][0])

        validate_error(
            api_client.record_milestone_payment(
                paid["id"],
                record_payment_payload(
                    paid["amount_cents"], payment_reference="WIRE-2411-02"
                ),
                BILLING,
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        stored = read_milestone(paid)
        assert stored["payment_reference"] == BASE_SCENARIO["PAYMENT_REFERENCE"]

        entries, meta = validate_paginated(
            api_client.list_ledger_entries(scenario["client"]["id"], BILLING)
        )
        assert meta["total_count"] == 2
        assert len(entries) == 2
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 0
