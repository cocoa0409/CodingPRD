"""Insurance policies: verification gates, adequacy requirements, the
insurance-lapse cascade; plus manual hour-adjustment floor rules."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_active_handler,
    create_insurance_policy_payload,
    create_request_ok,
    create_verified_policy,
    get_certification,
    get_handler,
    get_team_version,
    get_visit,
    get_visit_request,
    offer_request_ok,
    accept_request_ok,
    post_adjustment,
    schedule_visit_ok,
    setup_active_facility,
    setup_certified_team,
    setup_certified_team_at_facility,
    setup_visit_ready_team,
    make_handler_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestPolicyVerification:
    def test_second_active_policy_rejected(self):
        """PRD §3.5: "Verification by a `ProgramAdmin` requires `PENDING` (otherwise `ERR_POLICY_NOT_PENDING`), requires today to fall within the effective window inclusive (otherwise `ERR_POLICY_WINDOW_INVALID`), and enforces one active policy per handler — verifying a second while another stands `ACTIVE` fails with `ERR_ACTIVE_POLICY_EXISTS`."

        Design: Corner/errors/second_active_policy_rejected
        """
        handler = create_active_handler(full_name="H AP")
        create_verified_policy(handler["id"], coverage_cents=200_000_000)
        second = validate_success(api_client.create_insurance_policy(
            create_insurance_policy_payload(coverage_cents=300_000_000),
            make_handler_headers(handler["id"]),
        ), 201)
        resp = api_client.verify_insurance_policy(second["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_POLICY_EXISTS)

    def test_policy_verify_window_invalid(self):
        """PRD §3.5: "Verification by a `ProgramAdmin` requires `PENDING` (otherwise `ERR_POLICY_NOT_PENDING`), requires today to fall within the effective window inclusive (otherwise `ERR_POLICY_WINDOW_INVALID`), and enforces one active policy per handler — verifying a second while another stands `ACTIVE` fails with `ERR_ACTIVE_POLICY_EXISTS`."
        PRD §2.4: "At startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."

        Design: Corner/errors/policy_verify_window_invalid
        """
        handler = create_active_handler(full_name="H PW")
        policy = validate_success(api_client.create_insurance_policy(
            create_insurance_policy_payload(
                coverage_cents=200_000_000,
                effective_from="2026-01-01", effective_until="2026-06-01",
            ),
            make_handler_headers(handler["id"]),
        ), 201)
        # Default logical clock 2026-08-01 is past effective_until 2026-06-01.
        resp = api_client.verify_insurance_policy(policy["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_INVALID)


class TestHospitalAdequacyMultiplier:
    def test_insurance_hospital_multiplier_boundary(self):
        """PRD §3.5: "Visit-level operations — direct scheduling, offer acceptance, and candidate-team eligibility — apply the facility-specific requirement: the base is the greater of one hundred million cents and the facility's `min_liability_coverage_cents`, and for a `HOSPITAL` that base is multiplied by one and a half, rounded half-up to a whole cent. Coverage is adequate when an `ACTIVE` policy of the team's handler exists whose effective window covers today and whose `coverage_cents` is at least the requirement — equality passes."
        PRD §3.5: "When no `ACTIVE` policy covers today the rejection is `ERR_NO_ACTIVE_INSURANCE`; when one exists but falls short it is `ERR_INSURANCE_COVERAGE_INADEQUATE`."

        Design: Corner/calculations/insurance_hospital_multiplier_boundary
        """
        # HOSPITAL with facility minimum 120000000 -> the required coverage is
        # round_half_up(max(100000000, 120000000) * 1.5) = 180000000 cents.
        fac_ctx = setup_active_facility(
            name="Hospital H", facility_type="HOSPITAL",
            min_liability_coverage_cents=120_000_000,
            insurance_minimum_cents=120_000_000,
        )
        team_a = setup_visit_ready_team(
            setup_certified_team(handler_name="H IA", team_name="TIA",
                                 coverage_cents=179_999_999),
            fac_ctx,
        )
        team_b = setup_visit_ready_team(
            setup_certified_team(handler_name="H IB", team_name="TIB",
                                 coverage_cents=180_000_000,
                                 # Team A's chain already advanced the clock past
                                 # the default evaluation slot; use a later one.
                                 eval_start="2026-08-02T12:00:00Z",
                                 eval_end="2026-08-02T13:00:00Z"),
            fac_ctx,
        )
        # 179999999 < 180000000 -> present but short.
        resp_a = api_client.create_visit(
            {
                "team_id": team_a["team"]["id"],
                "facility_id": fac_ctx["facility"]["id"],
                "scheduled_start": "2026-08-03T10:00:00Z",
                "scheduled_end": "2026-08-03T10:30:00Z",
                "expected_team_version": get_team_version(team_a["team"]["id"]),
            },
            ADMIN,
        )
        validate_error(resp_a, ApiErrorId.ERR_INSURANCE_COVERAGE_INADEQUATE)
        # 180000000 == 180000000 -> adequate at the exact boundary.
        visit_b = schedule_visit_ok(
            team_b["team"]["id"], fac_ctx["facility"]["id"],
            "2026-08-04T10:00:00Z", "2026-08-04T10:30:00Z",
        )
        assert visit_b["lifecycle_status"] == "SCHEDULED"


class TestInsuranceLapseCascade:
    def _setup_lapse_scenario(self):
        """Certified team + ACTIVE facility; one ACCEPTED request-backed visit
        (2026-08-10) and one directly scheduled visit (2026-08-11); a single
        ACTIVE policy."""
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H J", "team_name": "TJ"},
            facility_kwargs={"name": "School I", "visits_per_week_cap": 8},
        )
        request = create_request_ok(ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                                    "2026-08-10T15:00:00Z")
        offer_request_ok(request["id"], ctx["team"]["id"])
        v_req = accept_request_ok(request["id"], ctx["handler"]["id"])
        v_dir = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-11T10:00:00Z", "2026-08-11T10:30:00Z")
        return ctx, request, v_req, v_dir

    def test_policy_cancel_suspends_certification_with_insurance_lapse(self):
        """PRD §3.5: "Cancelling an `ACTIVE` policy runs the insurance-lapse cascade in four hops: first, every certification of the handler's teams standing in `ACTIVE` or `RENEWAL_DUE` is examined, and if no remaining `ACTIVE` policy covers today with at least one hundred million cents of coverage, that certification moves to `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSE`; second, each freshly suspended certification's team drops to `SUSPENDED`; third, every `SCHEDULED` visit of each such team is cancelled with `cancel_reason` `CERT_SUSPENDED` and the animal's `forward_workload_minutes` decremented per visit; fourth, request-backed cancelled visits return their visit requests to `OPEN` with offer fields cleared."

        Design: Difficulty/transitive_cascade/insurance_cancel_depth3_cascade
        """
        ctx, _request, _v_req, _v_dir = self._setup_lapse_scenario()
        cancelled = validate_success(
            api_client.cancel_insurance_policy(
                ctx["policy"]["id"], make_handler_headers(ctx["handler"]["id"])
            )
        )
        assert cancelled["status"] == "CANCELLED"
        cert = get_certification(ctx["certification"]["id"])
        assert cert["status"] == "SUSPENDED", (
            "Hop 1: with no remaining ACTIVE policy the certification suspends"
        )
        assert cert["suspension_reason"] == "INSURANCE_LAPSE"

    def test_policy_cancel_cancels_visits_and_reopens_requests(self):
        """PRD §3.5: "Cancelling an `ACTIVE` policy runs the insurance-lapse cascade in four hops: first, every certification of the handler's teams standing in `ACTIVE` or `RENEWAL_DUE` is examined, and if no remaining `ACTIVE` policy covers today with at least one hundred million cents of coverage, that certification moves to `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSE`; second, each freshly suspended certification's team drops to `SUSPENDED`; third, every `SCHEDULED` visit of each such team is cancelled with `cancel_reason` `CERT_SUSPENDED` and the animal's `forward_workload_minutes` decremented per visit; fourth, request-backed cancelled visits return their visit requests to `OPEN` with offer fields cleared."

        Design: Difficulty/transitive_cascade/insurance_cancel_depth3_cascade
        """
        ctx, request, v_req, v_dir = self._setup_lapse_scenario()
        validate_success(
            api_client.cancel_insurance_policy(
                ctx["policy"]["id"], make_handler_headers(ctx["handler"]["id"])
            )
        )
        backed = get_visit(v_req["id"])
        assert backed["lifecycle_status"] == "CANCELLED"
        assert backed["cancel_reason"] == "CERT_SUSPENDED", (
            "Hop 2: SCHEDULED visits cancel with cancel_reason CERT_SUSPENDED"
        )
        direct = get_visit(v_dir["id"])
        assert direct["lifecycle_status"] == "CANCELLED"
        reopened = get_visit_request(request["id"])
        assert reopened["status"] == "OPEN", (
            "Hop 3: the request-backed visit's request returns to OPEN"
        )
        assert reopened["offered_team_id"] is None, "Offer fields must be cleared"


class TestAdjustmentFloor:
    def test_invalid_adjustment_floor_and_zero(self):
        """PRD §3.8: "A `ComplianceOfficer` posts manual adjustments with the target `handler_id`, a signed `minutes`, and a `reason`; an adjustment of zero minutes, or one that would take the handler's `lifetime_minutes` below zero, is rejected with `ERR_INVALID_ADJUSTMENT`."
        PRD §2.9: "The handler's `lifetime_minutes` is the algebraic sum over all of the handler's ledger rows, floored at zero — a posting that would drive the total below zero is rejected with `ERR_INVALID_ADJUSTMENT`."

        Design: Corner/errors/invalid_adjustment_floor_and_zero
        """
        handler = create_active_handler(full_name="H AD")
        post_adjustment(handler["id"], 30, reason="seed")
        resp_zero = api_client.create_hour_adjustment(
            {"handler_id": handler["id"], "minutes": 0, "reason": "noop"},
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(resp_zero, ApiErrorId.ERR_INVALID_ADJUSTMENT)
        resp_under = api_client.create_hour_adjustment(
            {"handler_id": handler["id"], "minutes": -50, "reason": "overdraw"},
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(resp_under, ApiErrorId.ERR_INVALID_ADJUSTMENT)
        handler_after = get_handler(handler["id"])
        assert handler_after["lifetime_minutes"] == 30, (
            "Both adjustments were rejected; no partial application"
        )
