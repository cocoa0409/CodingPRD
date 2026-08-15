"""Permit fees, the reject/amend/refile cycle, expiry sweeps, and schedule gating."""
from test_helpers import (
    ApiErrorId,
    ONE_ASPHALT_CROSSING,
    confirm_booking,
    create_booking,
    create_crew,
    create_permit_payload,
    get_success_data,
    refresh_application,
    refresh_permit,
    set_clock,
    setup_draft_app,
    setup_paid_ciac_app,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPermitFeeRounding:
    def test_per_segment_rounding_pinned(self, api, coordinator_headers):
        """PRD §3.4: "The fee's rounding order is pinned: for each crossing segment, multiply the segment's length by its width to get square footage, multiply by the surface rate — 350 cents per square foot for `ASPHALT`, 525 for `CONCRETE`, 150 for `LANDSCAPE` — and round that segment fee half up to whole cents before anything is summed; then total the individually rounded segment fees and add the flat filing fee of 7,500 cents ($75.00)."

        Design: Difficulty/combinatorial_formula/permit_fee_segment_rounding_pinned
        """
        ctx = setup_draft_app()
        resp = api.create_permit(
            create_permit_payload(
                ctx["app"]["id"],
                crossings=[
                    {"surface_type": "CONCRETE", "length_ft": 1.5, "width_ft": 1.0},
                    {"surface_type": "CONCRETE", "length_ft": 1.5, "width_ft": 1.0},
                    {"surface_type": "CONCRETE", "length_ft": 1.5, "width_ft": 1.0},
                ],
            ),
            coordinator_headers,
        )
        permit = validate_success(resp, expected_status=201)
        # Each segment: 1.5 sqft x 525 = 787.5 -> round half up 788; 3 x 788 + 7500.
        assert permit["permit_fee_cents"] == 9864, (
            f"3 x round_half_up(787.5) + 7500 = 9864, got {permit['permit_fee_cents']}"
        )
        assert permit["status"] == "DRAFT"

    def test_per_segment_rounding_is_not_sum_then_round(self, api, coordinator_headers):
        """PRD §3.4: "Summing raw segment fees and rounding once at the end is a different number and is not the contract."

        Design: Difficulty/combinatorial_formula/permit_fee_segment_rounding_pinned
        """
        ctx = setup_draft_app()
        resp = api.create_permit(
            create_permit_payload(
                ctx["app"]["id"],
                crossings=[
                    {"surface_type": "CONCRETE", "length_ft": 1.5, "width_ft": 1.0},
                    {"surface_type": "CONCRETE", "length_ft": 1.5, "width_ft": 1.0},
                    {"surface_type": "CONCRETE", "length_ft": 1.5, "width_ft": 1.0},
                ],
            ),
            coordinator_headers,
        )
        permit = validate_success(resp, expected_status=201)
        assert permit["permit_fee_cents"] != 9863, (
            "sum-then-round (3 x 787.5 = 2362.5 -> 2363 + 7500 = 9863) is not the contract"
        )
        persisted = refresh_permit(permit["id"])
        assert persisted["permit_fee_cents"] == 9864


class TestPermitRejectAmendRefileCycle:
    def test_reject_then_amend_recomputes_fee(self, api, coordinator_headers):
        """PRD §3.4: "A rejected permit, or an approved one that the clock sweep has since moved from `APPROVED` to `EXPIRED`, can be amended back to `DRAFT` with optional updates to `jurisdiction` or `crossings`, and the fee is recomputed whenever the crossings change."
        PRD §3.4: "while `REJECTED` captures the authority's `decision_note`; either way `decided_at` is stamped."

        Design: Difficulty/non_linear_state_machine/permit_reject_amend_refile_cycle
        """
        ctx = setup_draft_app()
        resp = api.create_permit(
            create_permit_payload(
                ctx["app"]["id"],
                crossings=[{"surface_type": "CONCRETE", "length_ft": 4.0, "width_ft": 3.0}],
            ),
            coordinator_headers,
        )
        permit = validate_success(resp, expected_status=201)
        assert permit["permit_fee_cents"] == 13800, "12 sqft x 525 + 7500 = 13800"
        get_success_data(api.file_permit(permit["id"], coordinator_headers))

        resp = api.record_permit_decision(
            permit["id"],
            {"decision": "REJECTED", "decision_note": "traffic plan missing"},
            coordinator_headers,
        )
        rejected = validate_success(resp)
        assert rejected["status"] == "REJECTED"

        resp = api.amend_permit(
            permit["id"],
            {"crossings": [{"surface_type": "ASPHALT", "length_ft": 12.0, "width_ft": 3.0}]},
            coordinator_headers,
        )
        amended = validate_success(resp)
        assert amended["status"] == "DRAFT", "the amend hop loops back to DRAFT"
        assert amended["permit_fee_cents"] == 20100, (
            f"36 sqft x 350 + 7500 = 20100, got {amended['permit_fee_cents']}"
        )

    def test_refiling_after_amend_reaches_approved(self, api, coordinator_headers):
        """PRD §3.4: "Filing moves a permit from `DRAFT` to `FILED`, stamps `filed_at`"
        PRD §3.4: "`APPROVED` requires an `expires_at` date on or after the current date — a lapse date in the past is rejected with `ERR_DATE_IN_PAST` (HTTP 422)"

        Design: Difficulty/non_linear_state_machine/permit_reject_amend_refile_cycle
        """
        ctx = setup_draft_app()
        resp = api.create_permit(
            create_permit_payload(
                ctx["app"]["id"],
                crossings=[{"surface_type": "CONCRETE", "length_ft": 4.0, "width_ft": 3.0}],
            ),
            coordinator_headers,
        )
        permit = validate_success(resp, expected_status=201)
        get_success_data(api.file_permit(permit["id"], coordinator_headers))
        get_success_data(
            api.record_permit_decision(
                permit["id"],
                {"decision": "REJECTED", "decision_note": "traffic plan missing"},
                coordinator_headers,
            )
        )
        get_success_data(
            api.amend_permit(
                permit["id"],
                {"crossings": [{"surface_type": "ASPHALT", "length_ft": 12.0, "width_ft": 3.0}]},
                coordinator_headers,
            )
        )

        refiled = get_success_data(api.file_permit(permit["id"], coordinator_headers))
        assert refiled["status"] == "FILED", "the cycle re-enters FILED from DRAFT"

        resp = api.record_permit_decision(
            permit["id"],
            {"decision": "APPROVED", "expires_at": "2026-12-31"},
            coordinator_headers,
        )
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"
        assert approved["expires_at"] == "2026-12-31"


class TestScheduleConstructionPermitGate:
    def test_filed_permit_blocks_schedule_construction(self, api, coordinator_headers,
                                                       supervisor_headers):
        """PRD §3.5: "Moving an application from `APPROVED_FOR_CONSTRUCTION` or `PERMITTING` to `CONSTRUCTION_SCHEDULED` enforces five checks: the application must be unheld (`ERR_APPLICATION_ON_HOLD`); every permit of the application must be in `APPROVED` or `CLOSED` (`ERR_PERMIT_NOT_APPROVED`, HTTP 422); when the design's `crossings_count` is greater than zero, at least one `ROAD_CUT` permit specifically must be in `APPROVED` or `CLOSED` (same error); at least one of the application's bookings must be `CONFIRMED` (`ERR_NO_CONFIRMED_BOOKING`, HTTP 422); and the CIAC invoice must be `PAID` (`ERR_CIAC_UNPAID`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/schedule_construction_needs_approved_road_cut_permit
        """
        ctx = setup_paid_ciac_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False,
            payment_amount=446203,
        )
        permit = get_success_data(
            api.create_permit(create_permit_payload(ctx["app"]["id"]), coordinator_headers)
        )
        get_success_data(api.file_permit(permit["id"], coordinator_headers))
        app = refresh_application(ctx["app"]["id"])
        assert app["status"] == "PERMITTING", "filing nudges the spine to PERMITTING"

        crew = create_crew(specialty="MAIN_EXTENSION")
        booking = create_booking(ctx["app"]["id"], crew["id"], scope="MAIN_CONSTRUCTION")
        confirm_booking(booking["id"])

        resp = api.schedule_construction(ctx["app"]["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED, expected_status=422)
        app = refresh_application(ctx["app"]["id"])
        assert app["status"] == "PERMITTING", "the rejected gate must not move the spine"

    def test_approved_road_cut_unblocks_schedule_construction(self, api, coordinator_headers,
                                                              supervisor_headers):
        """PRD §3.5: "Moving an application from `APPROVED_FOR_CONSTRUCTION` or `PERMITTING` to `CONSTRUCTION_SCHEDULED` enforces five checks: the application must be unheld (`ERR_APPLICATION_ON_HOLD`); every permit of the application must be in `APPROVED` or `CLOSED` (`ERR_PERMIT_NOT_APPROVED`, HTTP 422); when the design's `crossings_count` is greater than zero, at least one `ROAD_CUT` permit specifically must be in `APPROVED` or `CLOSED` (same error); at least one of the application's bookings must be `CONFIRMED` (`ERR_NO_CONFIRMED_BOOKING`, HTTP 422); and the CIAC invoice must be `PAID` (`ERR_CIAC_UNPAID`, HTTP 422)."
        PRD §3.4: "Filing moves a permit from `DRAFT` to `FILED`, stamps `filed_at`, and — when the application is sitting in `APPROVED_FOR_CONSTRUCTION` — nudges the spine into `PERMITTING`."

        Design: Difficulty/cross_entity_state_dependency/schedule_construction_needs_approved_road_cut_permit
        """
        ctx = setup_paid_ciac_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False,
            payment_amount=446203,
        )
        permit = get_success_data(
            api.create_permit(create_permit_payload(ctx["app"]["id"]), coordinator_headers)
        )
        get_success_data(api.file_permit(permit["id"], coordinator_headers))
        crew = create_crew(specialty="MAIN_EXTENSION")
        booking = create_booking(ctx["app"]["id"], crew["id"], scope="MAIN_CONSTRUCTION")
        confirm_booking(booking["id"])

        resp = api.schedule_construction(ctx["app"]["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED, expected_status=422)

        get_success_data(
            api.record_permit_decision(
                permit["id"],
                {"decision": "APPROVED", "expires_at": "2026-12-31"},
                coordinator_headers,
            )
        )
        resp = api.schedule_construction(ctx["app"]["id"], supervisor_headers)
        scheduled = validate_success(resp)
        assert scheduled["status"] == "CONSTRUCTION_SCHEDULED", (
            "the permit's own FILED->APPROVED transition unblocks the gate"
        )


class TestPermitCreationRules:
    def test_road_cut_permit_without_crossings_rejected(self, api, coordinator_headers):
        """PRD §2.6: "Separately from this ordered stack, malformed request bodies — a missing required field, a value of the wrong type, an enum member outside the declared set, a non-positive quantity, footage, or money amount, a time window whose end does not fall strictly after its start, or a road-cut permit with an empty crossing list — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/road_cut_permit_without_crossings_rejected
        """
        ctx = setup_draft_app()
        resp = api.create_permit(
            create_permit_payload(ctx["app"]["id"], permit_type="ROAD_CUT", crossings=[]),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        resp = api.list_permits(
            coordinator_headers, params={"service_application_id": ctx["app"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 0


class TestPermitExpirySweep:
    def test_approved_permit_expires_and_amends_back(self, api, coordinator_headers):
        """PRD §2.9: "a permit in `APPROVED` whose `expires_at` date has passed moves to `EXPIRED`."
        PRD §3.4: "A rejected permit, or an approved one that the clock sweep has since moved from `APPROVED` to `EXPIRED`, can be amended back to `DRAFT` with optional updates to `jurisdiction` or `crossings`, and the fee is recomputed whenever the crossings change."

        Design: Corner/complexity_layers/permit_expiry_sweep
        """
        ctx = setup_draft_app()
        permit = get_success_data(
            api.create_permit(create_permit_payload(ctx["app"]["id"]), coordinator_headers)
        )
        get_success_data(api.file_permit(permit["id"], coordinator_headers))
        get_success_data(
            api.record_permit_decision(
                permit["id"],
                {"decision": "APPROVED", "expires_at": "2026-08-20"},
                coordinator_headers,
            )
        )

        set_clock("2026-08-21T09:00:00Z")
        expired = refresh_permit(permit["id"])
        assert expired["status"] == "EXPIRED", (
            f"2026-08-21 is past expires_at 2026-08-20, got {expired['status']}"
        )

        resp = api.amend_permit(permit["id"], {}, coordinator_headers)
        amended = validate_success(resp)
        assert amended["status"] == "DRAFT", "the EXPIRED->DRAFT loop closes"
