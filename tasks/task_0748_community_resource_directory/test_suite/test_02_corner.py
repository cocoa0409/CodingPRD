"""Breadth-of-behaviour tests (queue B).

Every test here translates one non-stub instance from the corner-design queue.
Excluded stubs (whose `excluded_because.difficulty_instance` names a real Difficulty
instance) are not translated here — the cited Difficulty test owns the assertion.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    api_client,
    TEST_USERS,
    build_user_headers,
    make_client_headers,
    make_provider_staff_headers,
    make_platform_admin_headers,
    make_caseworker_headers,
    setup_baseline,
    setup_baseline_with_referral,
    setup_baseline_with_accepted_referral,
    setup_baseline_with_service_in_progress_referral,
    set_clock,
    create_funder,
    create_provider,
    create_program,
    create_client,
    create_intake,
    screen_intake,
    create_consent_grant,
    create_referral,
    accept_referral,
    start_service,
    create_outcome_report,
    create_funder_payload,
    create_provider_payload,
    create_program_payload,
    create_client_payload,
    create_intake_payload,
    create_consent_grant_payload,
    create_referral_payload,
    create_availability_window_payload,
    create_outcome_report_payload,
    create_funder_report_payload,
    create_transport_plan_payload,
    DEFAULT_CLOCK,
    assert_funder_report_has_no_version_fields,
)


ADMIN = TEST_USERS["platform_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# =============================================================================
# Section: entities
# =============================================================================


class TestEntities:

    def test_funder_creation_returns_201_and_full_body(self, api):
        """PRD §3.1: "On creation, a funder's `grant_cents_remaining` is initialised equal to `grant_cents_total`."
        PRD §2.4: "integer `version` counter that starts at 1 on creation and increments by exactly 1 on every mutation."
        PRD §4: "New resource creations return HTTP 201; state transitions, patches, list endpoints, and the administrative clock-set capability return HTTP 200."

        Design: Corner/entities/funder_creation_happy_path_returns_201_and_full_body
        """
        set_clock(DEFAULT_CLOCK)
        payload = create_funder_payload(name="Rainbow Trust", grant_cents_total=50_000_000)
        resp = api.create_funder(payload, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["name"] == "Rainbow Trust"
        assert data["grant_cents_total"] == 50_000_000
        assert data["grant_cents_remaining"] == 50_000_000
        assert data["version"] == 1

    def test_funder_get_by_missing_id_returns_err_funder_not_found(self, api):
        """PRD §2.5: "the parent entity is looked up first, and if it does not exist the request is rejected with the parent's own not-found error (`ERR_FUNDER_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_INTAKE_NOT_FOUND`, `ERR_CONSENT_GRANT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, or `ERR_OUTCOME_REPORT_NOT_FOUND`, each returning HTTP 404) before any body validation runs."

        Design: Corner/entities/funder_get_by_id_not_found_returns_err_funder_not_found
        """
        set_clock(DEFAULT_CLOCK)
        resp = api.get_funder(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FUNDER_NOT_FOUND, expected_status=404)

    def test_provider_creation_missing_languages_supported_returns_invalid_request(self, api):
        """PRD §3.1: "a `languages_supported` array (a non-empty subset of `EN`, `ES`, `FR`, `ZH`, `VI`, `AR` naming the languages in which the provider can actually deliver service)."
        PRD §5: "`ERR_INVALID_REQUEST` | 400" (the sole 400 error, applied when the request body is malformed).

        Design: Corner/entities/provider_creation_missing_languages_supported_returns_invalid_request
        """
        set_clock(DEFAULT_CLOCK)
        payload = {
            "legal_name": "MissingLang Inc",
            "location_lat": 40.0,
            "location_lng": -74.0,
            "accessibility_features": ["WHEELCHAIR"],
            # languages_supported deliberately omitted.
        }
        resp = api.create_provider(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_program_created_with_computed_defaults_open_and_zero(self, api):
        """PRD §3.1: "At creation, the server initialises `capacity_slots_taken` to 0, `intake_posture` to `OPEN`, and `funder_reporting_posture` to `OPEN`."

        Design: Corner/entities/program_created_with_computed_defaults
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        payload = create_program_payload(p["id"], f["id"])
        data = validate_success(api.create_program(payload, ADMIN), expected_status=201)
        assert data["capacity_slots_taken"] == 0
        assert data["intake_posture"] == "OPEN"
        assert data["funder_reporting_posture"] == "OPEN"

    def test_client_creation_invalid_preferred_language_enum_rejected(self, api):
        """PRD §3.2: "a `preferred_language` from `EN`, `ES`, `FR`, `ZH`, `VI`, or `AR`"
        PRD §5: "`ERR_INVALID_REQUEST` | 400" (a body that fails input-shape validation cannot be honoured; only ERR_INVALID_REQUEST is defined at HTTP 400).

        Design: Corner/entities/client_creation_invalid_preferred_language_enum_rejected
        """
        set_clock(DEFAULT_CLOCK)
        payload = create_client_payload(preferred_language="KLINGON")
        resp = api.create_client(payload, CASEWORKER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_funder_report_response_omits_version_and_updated_at(self, api):
        """PRD §2.4: "`FunderReport` is a computed, immutable aggregate; it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from its representation."

        Design: Corner/entities/funder_report_creation_returns_no_version_field_since_common_fields_false
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        payload = create_funder_report_payload(
            "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", rounding_variant="SUM_THEN_ROUND",
        )
        data = validate_success(api.create_funder_report(f["id"], payload, ADMIN), expected_status=201)
        assert data["total_disbursement_cents"] == 0
        assert data["total_referrals"] == 0
        assert data["total_completions"] == 0
        assert_funder_report_has_no_version_fields(data)


# =============================================================================
# Section: state_machines
# =============================================================================


class TestStateMachines:

    def test_intake_created_starts_in_draft_status_and_version_1(self, api):
        """PRD §3.2: "A new intake enters the system with `status` set to `DRAFT`."
        PRD §2.4: "integer `version` counter that starts at 1 on creation and increments by exactly 1 on every mutation."

        Design: Corner/state_machines/intake_created_starts_in_draft
        """
        set_clock(DEFAULT_CLOCK)
        c = create_client()
        payload = create_intake_payload()
        i = validate_success(api.create_intake(c["id"], payload, CASEWORKER), expected_status=201)
        assert i["status"] == "DRAFT"
        assert i["version"] == 1

    def test_screen_intake_from_screened_returns_err_intake_not_draft(self, api):
        """PRD §3.2: "Screening moves the intake from `DRAFT` to `SCREENED`, requiring the intake to currently be `DRAFT` and its `client_id` to resolve to an existing client; if the intake is not in `DRAFT` the screening call is rejected with `ERR_INTAKE_NOT_DRAFT`."

        Design: Corner/state_machines/intake_screen_from_screened_returns_invalid_state
        """
        set_clock(DEFAULT_CLOCK)
        c = create_client()
        i = create_intake(c["id"])
        screen_intake(i["id"])  # DRAFT -> SCREENED
        resp = api.screen_intake(i["id"], CASEWORKER)
        validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_DRAFT, expected_status=409)

    def test_decline_referral_from_accepted_returns_referral_invalid_state(self, api):
        """PRD §3.5: "Decline is only legal from `PROPOSED` (otherwise `ERR_REFERRAL_INVALID_STATE`)"

        Design: Corner/state_machines/referral_decline_from_accepted_returns_invalid_state
        """
        b, r = setup_baseline_with_accepted_referral()
        resp = api.decline_referral(r["id"], make_provider_staff_headers(b.provider_id))
        validate_error(resp, ApiErrorId.ERR_REFERRAL_INVALID_STATE, expected_status=409)

    def test_revoke_already_revoked_consent_returns_already_terminal(self, api):
        """PRD §3.3: "the grant's `status` must currently be `GRANTED` — a grant already `REVOKED` or `EXPIRED` cannot be revoked again and is rejected with `ERR_CONSENT_ALREADY_TERMINAL`."

        Design: Corner/state_machines/consent_grant_revoke_twice_returns_already_terminal
        """
        set_clock(DEFAULT_CLOCK)
        p = create_provider()
        cl = create_client()
        cg = create_consent_grant(cl["id"], p["id"])
        # First revoke succeeds.
        validate_success(api.revoke_consent_grant(cg["id"], make_client_headers(cl["id"])))
        # Second revoke fails.
        resp = api.revoke_consent_grant(cg["id"], make_client_headers(cl["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSENT_ALREADY_TERMINAL, expected_status=409)

    def test_intake_auto_bubbles_to_closed_when_only_referral_declined(self, api):
        """PRD §3.5: "If this decline leaves every referral on the parent intake terminal and at least one referral exists on the intake, the intake auto-bubbles `SCREENED → CLOSED`, incrementing its `version` by 1."

        Design: Corner/state_machines/intake_bubble_up_close_when_all_referrals_terminal
        """
        b, r = setup_baseline_with_referral()
        validate_success(api.decline_referral(r["id"], make_provider_staff_headers(b.provider_id)))
        # Fetch intake — should be CLOSED via bubble-up.
        i = get_success_data(api.get_intake(b.intake["id"], CASEWORKER))
        assert i["status"] == "CLOSED", (
            f"intake should bubble-up to CLOSED after its only referral became terminal, got {i['status']}"
        )

    def test_consent_expiry_via_clock_advance_leaves_proposed_referral_intact(self, api):
        """PRD §3.3: "when the logical clock advances to a moment at or after a `GRANTED` grant's `expires_at`, the grant is automatically transitioned to `EXPIRED`. This system transition sets `status` to `EXPIRED`, increments `version` by 1, and refreshes `updated_at`; unlike revocation, it deliberately does not cascade to in-flight referrals — expired consent leaves already-accepted and in-progress referrals alone and is instead caught downstream at referral accept and start-service (see §3.5)."

        Design: Corner/state_machines/consent_expiry_via_clock_advance_does_not_cascade_withdraw
        """
        set_clock("2026-06-01T00:00:00Z")
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        cl = create_client()
        i = screen_intake(create_intake(cl["id"])["id"])
        cg = create_consent_grant(cl["id"], p["id"])
        r = create_referral(i["id"], prog["id"], cg["id"])
        # Advance clock past 90-day expires_at.
        set_clock("2026-09-01T00:00:00Z")
        cg_after = get_success_data(api.get_consent_grant(cg["id"], CASEWORKER))
        assert cg_after["status"] == "EXPIRED"
        r_after = get_success_data(api.get_referral(r["id"], CASEWORKER))
        assert r_after["status"] == "PROPOSED", (
            f"consent expiry must NOT cascade to referral, but referral is now {r_after['status']}"
        )


# =============================================================================
# Section: calculations
# =============================================================================


class TestCalculations:

    def test_travel_burden_naive_and_routed_computed_at_referral_creation(self, api):
        """PRD §3.4: "The naive-straight-line variant converts that degree distance to kilometres by multiplying by 111.0, divides by the speed in kilometres per hour associated with the referral's `transport_mode` (25.0 for `PUBLIC_TRANSIT`, 40.0 for `CAR`, 5.0 for `WALKING`, 20.0 for `AGENCY_SHUTTLE`), multiplies by 60.0 to convert to minutes, and rounds half-up to 2 decimal places; the result is written to `travel_burden_naive_min`. The routed variant applies the same steps but multiplies the kilometre distance by an additional winding factor of 1.35 before dividing by speed, so the routed value is always strictly greater than the naive value for the same inputs; the routed value is rounded half-up to 2 decimal places and written to `travel_burden_routed_min`."

        Design: Corner/calculations/travel_burden_naive_less_than_routed_variant_delta
        """
        # Client home (40.10, -74.05); Provider (40.00, -74.00); CAR (40 kph).
        # |dlat|+|dlng| = 0.15 deg -> 16.65 km.
        # naive: 16.65 / 40 * 60 = 24.975 -> 24.98
        # routed: 16.65 * 1.35 / 40 * 60 = 33.7162... -> 33.72
        b = setup_baseline(
            provider_overrides={"location_lat": 40.00, "location_lng": -74.00},
            client_overrides={"home_lat": 40.10, "home_lng": -74.05,
                              "monthly_income_cents": 400000, "accessibility_needs": []},
        )
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"], transport_mode="CAR")
        assert r["travel_burden_naive_min"] == pytest.approx(24.98, abs=0.001)
        assert r["travel_burden_routed_min"] == pytest.approx(33.72, abs=0.001)
        assert r["travel_burden_routed_min"] > r["travel_burden_naive_min"]

    def test_program_utilization_at_80_percent_is_restricted_inclusive_boundary(self, api):
        """PRD §3.4: "utilisation is defined as `capacity_slots_taken` divided by `capacity_slots_total`, and the posture is `CLOSED` when this ratio is at least 1.00, `RESTRICTED` when it is at least 0.80 but strictly less than 1.00, and `OPEN` otherwise."

        Design: Corner/calculations/program_utilization_boundary_at_80_percent_ratio_transitions_to_restricted
        """
        b = setup_baseline(program_overrides={"capacity_slots_total": 5})
        for _ in range(4):
            create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        prog = get_success_data(api.get_program(b.program["id"], ADMIN))
        assert prog["capacity_slots_taken"] == 4
        assert prog["intake_posture"] == "RESTRICTED", (
            f"4/5 = 0.80 is at the RESTRICTED inclusive boundary; got {prog['intake_posture']}"
        )

    def test_eligibility_score_income_ratio_of_exactly_0_50_pins_income_score_to_100(self, api):
        """PRD §3.4: "the ratio of the client's `monthly_income_cents` to the maximum of `eligibility_income_max_cents` and 1 (to avoid division by zero) is bucketed — a ratio of at most 0.50 scores 100.0, a ratio strictly greater than 0.50 but at most 0.80 scores 75.0, a ratio strictly greater than 0.80 but at most 1.00 scores 50.0, and a ratio strictly greater than 1.00 scores 0.0."

        Design: Corner/calculations/eligibility_score_income_ratio_tier_boundaries_pin_income_score
        """
        # All 5 components = 100 (income_ratio 0.50 exactly gets income_score 100;
        # age, category, language, accessibility all match). ROUTINE multiplier.
        # weighted = 100*(0.30+0.20+0.25+0.15+0.10) = 100.00.
        b = setup_baseline(
            program_overrides={"eligibility_income_max_cents": 500_000},
            provider_overrides={"accessibility_features": ["WHEELCHAIR"], "languages_supported": ["EN"]},
            client_overrides={"monthly_income_cents": 250_000, "accessibility_needs": [],
                              "preferred_language": "EN"},
            intake_overrides={"presenting_needs": ["FOOD"], "urgency": "ROUTINE"},
        )
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        assert r["eligibility_score"] == pytest.approx(100.00, abs=0.001), (
            f"income_ratio 0.50 exactly should be inclusive at income_score=100 tier, "
            f"total 100.00, got {r['eligibility_score']}"
        )

    def test_service_cost_final_at_fully_met_10_hours_yields_15000(self, api):
        """PRD §3.7: "if the outcome is `PARTIALLY_MET` or `FULLY_MET` the raw ratio is 0.50 plus the delivered `service_hours` multiplied by 0.10, and no upper cap is applied. The raw ratio is then multiplied by the program's `unit_cost_cents`, and the resulting floating-point cents value is rounded half-up in a single step to whole cents to produce `service_cost_final_cents`."

        Design: Corner/calculations/service_cost_final_variant_at_fully_met_10_hours
        """
        b, r = setup_baseline_with_service_in_progress_referral(
            program_overrides={"unit_cost_cents": 10000, "capacity_slots_total": 5},
        )
        o = create_outcome_report(r["id"], b.provider_id, outcome="FULLY_MET",
                                  service_hours=10.0, follow_up_needed=False)
        # raw_ratio = 0.50 + 10*0.10 = 1.50; raw = 15000; rounded = 15000.
        assert o["service_cost_final_cents"] == 15000


# =============================================================================
# Section: validations
# =============================================================================


class TestValidations:

    def test_create_referral_with_income_over_eligibility_max_returns_income_ineligible(self, api):
        """PRD §3.4: "the client's `monthly_income_cents` must be at most the program's `eligibility_income_max_cents`; equality passes and any strictly greater value yields `ERR_INCOME_INELIGIBLE`."

        Design: Corner/validations/create_referral_with_income_over_max_returns_income_ineligible

        Note: PRD priority order (§3.4) places `ERR_ELIGIBILITY_BELOW_THRESHOLD` before
        `ERR_INCOME_INELIGIBLE`. To isolate the income check the setup MUST first pass the
        eligibility_score gate. With income over max the income component scores 0.0; the
        four remaining components each score 100.0, yielding weighted = 70.0. To lift the
        final score to >= 75.0 the intake urgency is set to `EMERGENCY` (× 1.50 → 105.0).
        """
        b = setup_baseline(
            program_overrides={"eligibility_income_max_cents": 500_000},
            client_overrides={"monthly_income_cents": 600_000},
            intake_overrides={"presenting_needs": ["FOOD"], "urgency": "EMERGENCY"},
        )
        resp = api.create_referral(b.intake["id"],
                                    create_referral_payload(b.program["id"], b.consent["id"]),
                                    CASEWORKER)
        validate_error(resp, ApiErrorId.ERR_INCOME_INELIGIBLE, expected_status=422)

    def test_create_second_window_pushing_sum_of_max_slots_over_capacity_rejects(self, api):
        """PRD §3.1: "In addition, the sum of `max_slots` across every availability window belonging to the program, including the new one, must not exceed the program's `capacity_slots_total`; exceeding it is rejected with `ERR_WINDOW_SLOTS_EXCEED_CAPACITY`."

        Design: Corner/validations/create_window_that_pushes_sum_max_slots_over_capacity_rejects
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        ps = make_provider_staff_headers(p["id"])
        # First window with max_slots=3 succeeds.
        validate_success(
            api.create_availability_window(prog["id"],
                create_availability_window_payload("2026-08-01T09:00:00Z", "2026-08-01T12:00:00Z", 3),
                ps), 201)
        # Second window max_slots=3 -> total 6 > 5 -> reject.
        resp = api.create_availability_window(prog["id"],
            create_availability_window_payload("2026-08-01T13:00:00Z", "2026-08-01T16:00:00Z", 3),
            ps)
        validate_error(resp, ApiErrorId.ERR_WINDOW_SLOTS_EXCEED_CAPACITY, expected_status=422)

    def test_outcome_report_exceeding_grant_cents_remaining_returns_grant_insufficient_402(self, api):
        """PRD §3.7: "Filing an outcome debits the funder's `grant_cents_remaining` by exactly `service_cost_final_cents`. Before the debit is applied, the server checks that the funder has room: if the newly computed `service_cost_final_cents` is strictly greater than `grant_cents_remaining` the file is rejected with `ERR_GRANT_INSUFFICIENT` (HTTP 402), and equality passes."

        Design: Corner/validations/create_outcome_report_exceeding_grant_returns_402
        """
        # Grant 1000, unit_cost 10000, UNMET -> final = 5000 > 1000 -> reject.
        b, r = setup_baseline_with_service_in_progress_referral(
            funder_overrides={"grant_cents_total": 1000},
            program_overrides={"unit_cost_cents": 10000, "capacity_slots_total": 5},
        )
        payload = create_outcome_report_payload("UNMET", 0.0, False)
        resp = api.create_outcome_report(r["id"], payload, make_provider_staff_headers(b.provider_id))
        validate_error(resp, ApiErrorId.ERR_GRANT_INSUFFICIENT, expected_status=402)


# =============================================================================
# Section: endpoints
# =============================================================================


class TestEndpoints:

    def test_list_programs_filtered_by_funder_id_returns_only_matching(self, api):
        """PRD §4: "List programs with optional `provider_id`, `funder_id`, and `category` filters."

        Design: Corner/endpoints/get_programs_filtered_by_funder_id_reverse_reachability
        """
        set_clock(DEFAULT_CLOCK)
        fa = create_funder(name="F_a")
        fb = create_funder(name="F_b")
        p = create_provider()
        prog_a = create_program(p["id"], fa["id"], category="FOOD")
        prog_b = create_program(p["id"], fb["id"], category="HOUSING")
        resp = api.list_programs(ADMIN, params={"funder_id": fa["id"]})
        data, meta = validate_paginated(resp)
        ids = [row["id"] for row in data]
        assert prog_a["id"] in ids, "filtered list should include program under funder F_a"
        assert prog_b["id"] not in ids, "filtered list must NOT include program under funder F_b"

    def test_list_programs_defaults_return_limit_10_offset_0_total_0(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0 and must be at least 0."
        PRD §2.3: "Every list response echoes back the effective `limit` and `offset` in `meta`, along with `total_count` (the total number of records matching the query, before the limit/offset window is applied) and `has_more` (true when additional records remain beyond the current window)."

        Design: Corner/endpoints/pagination_defaults_return_limit_10_offset_0
        """
        set_clock(DEFAULT_CLOCK)
        resp = api.list_programs(ADMIN)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 0
        assert meta["has_more"] is False


# =============================================================================
# Section: errors
# =============================================================================


class TestErrors:

    def test_transport_plan_gap_exactly_30_minutes_passes(self, api):
        """PRD §3.6: "Two plans conflict when the smaller of the two temporal gaps between them — the gap measured in seconds between the closing endpoint of one interval and the opening endpoint of the other — is strictly less than 30 minutes. A conflict is rejected with `ERR_TRANSPORT_OVERLAP`; a gap of exactly 30 minutes is permitted."

        Design: Corner/errors/transport_plan_gap_exactly_30_minutes_passes_boundary
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        cl = create_client()
        i = screen_intake(create_intake(cl["id"])["id"])
        cg = create_consent_grant(cl["id"], p["id"])
        ra = accept_referral(
            create_referral(i["id"], prog["id"], cg["id"], transport_mode="AGENCY_SHUTTLE")["id"], p["id"])
        rb = accept_referral(
            create_referral(i["id"], prog["id"], cg["id"], transport_mode="AGENCY_SHUTTLE")["id"], p["id"])
        # First plan [09:00, 10:00].
        validate_success(
            api.create_transport_plan(ra["id"],
                {"pickup_start_ts": "2026-06-10T09:00:00Z", "pickup_end_ts": "2026-06-10T10:00:00Z",
                 "mode": "AGENCY_SHUTTLE", "cost_cents": 500},
                CASEWORKER), 201)
        # Second plan [10:30, 11:00] — gap = exactly 30 minutes -> passes.
        data = validate_success(
            api.create_transport_plan(rb["id"],
                {"pickup_start_ts": "2026-06-10T10:30:00Z", "pickup_end_ts": "2026-06-10T11:00:00Z",
                 "mode": "AGENCY_SHUTTLE", "cost_cents": 500},
                CASEWORKER), 201)
        assert data["status"] == "SCHEDULED"


# =============================================================================
# Section: rbac
# =============================================================================


class TestRbac:

    def test_client_role_cannot_accept_referral_returns_unauthorized(self, api):
        """PRD §2.1: "If both headers are present but the asserted role is not permitted for the endpoint the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/referrals/{id}/accept` | Provider accepts: `PROPOSED` → `ACCEPTED`. | `ProviderStaff`, `PlatformAdmin` |"

        Design: Corner/rbac/client_cannot_accept_referral_returns_unauthorized
        """
        b, r = setup_baseline_with_referral()
        resp = api.accept_referral(r["id"], make_client_headers(b.client_id))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_provider_staff_accepting_other_providers_referral_returns_ownership_violation(self, api):
        """PRD §2.1: "For any endpoint whose authorised roles list includes an entity-backed role (`ProviderStaff`, `Client`, or `FunderReporter`), a caller whose asserted role passes the role-membership check but whose `X-User-ID` does not match the resource-owner foreign key on the target is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/provider_staff_acting_on_other_provider_program_ownership_violation
        """
        b, r = setup_baseline_with_referral()
        # Create a SECOND provider p_other; call accept with p_other's id -> ownership violation.
        p_other = create_provider(legal_name="Other Provider")
        resp = api.accept_referral(r["id"], make_provider_staff_headers(p_other["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION, expected_status=403)

    def test_missing_x_user_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying which of the five roles the caller is asserting. If either header is missing or unrecognised the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
        """
        # Empty headers dict: neither X-User-Role nor X-User-ID present.
        resp = api.create_funder(create_funder_payload(name="NoAuth"), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# =============================================================================
# Section: cross_cutting_complexity_layers (concurrency / OCC)
# =============================================================================


class TestOptimisticConcurrency:

    def test_patch_program_with_stale_expected_version_returns_stale_program_version(self, api):
        """PRD §2.6: "When a client patches a program, the request body must include a non-optional `expected_program_version` field carrying the value of `version` the client last observed on that program. The server compares `expected_program_version` to the program's current `version`. If another writer has advanced the program's version since the client last read it — whether by an explicit patch or by a cascaded referral state change that bumped `capacity_slots_taken` and therefore `version` — the patch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), preventing the client from overwriting a program state it has not observed."

        Design: Corner/cross_cutting_complexity_layers/patch_program_with_stale_expected_program_version_returns_412
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"])
        v0 = prog["version"]
        # First PATCH advances version from v0 to v0+1.
        first = validate_success(api.patch_program(prog["id"],
            {"expected_program_version": v0, "unit_cost_cents": 15000}, ADMIN))
        assert first["version"] == v0 + 1
        # Second PATCH still uses stale v0.
        resp = api.patch_program(prog["id"],
            {"expected_program_version": v0, "unit_cost_cents": 20000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION, expected_status=412)


# =============================================================================
# Section: consistency_model
# =============================================================================


class TestConsistencyModel:

    def test_create_referral_reflects_incremented_capacity_on_next_get(self, api):
        """PRD §3.4: "As a side effect of creation, the program's `capacity_slots_taken` is incremented by 1"

        Design: Corner/consistency_model/single_request_returns_computed_capacity_immediately
        """
        b = setup_baseline(program_overrides={"capacity_slots_total": 5})
        # capacity_slots_taken == 0 before the referral.
        prog_before = get_success_data(api.get_program(b.program["id"], ADMIN))
        assert prog_before["capacity_slots_taken"] == 0
        # Create one referral.
        create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        # A subsequent GET must reflect the increment immediately.
        prog_after = get_success_data(api.get_program(b.program["id"], ADMIN))
        assert prog_after["capacity_slots_taken"] == 1, (
            f"capacity_slots_taken should show 1 on the very next GET, got {prog_after['capacity_slots_taken']}"
        )
