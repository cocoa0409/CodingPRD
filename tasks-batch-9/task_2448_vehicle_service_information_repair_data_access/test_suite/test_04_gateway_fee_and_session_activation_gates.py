"""Secure-gateway session pricing and the ordered gates on activation.

Covers the discount waterfall keyed on the base subtotal, the precedence of the
identity gate over the tool-occupancy gate, and the half-open arithmetic that
decides whether two sessions contend for the same scan tool.
"""

from test_helpers import (
    VIN_SECONDARY,
    VIN_TERTIARY,
    ApiErrorId,
    AuditEventType,
    JobType,
    SessionStatus,
    ToolStatus,
    assert_credential_token_derived_from_session,
    assert_data_credit_conservation,
    assert_diagnostic_tool,
    assert_gateway_fee_breakdown,
    assert_gateway_session,
    assert_no_audit_event,
    fixtures,
    make_compliance_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _tool_row(api, ctx, tool_id):
    rows, _meta = validate_paginated(
        api.list_shop_diagnostic_tools(
            ctx["shop"]["id"], ctx["manager_headers"], {"limit": 100}
        )
    )
    return next(row for row in rows if row["id"] == tool_id)


class TestGatewayFeeWaterfall:
    """The discount tier is chosen from the base subtotal, before any surcharge."""

    def test_discount_tier_is_keyed_on_the_base_subtotal_not_the_total(self, api):
        """A 9,800 subtotal earns five percent, giving 10,486 and not 9,996.

        PRD 3.7: "a session with one `IMMOBILIZER_KEY` job and one `MODULE_FLASH`
        job, both billable, has a base subtotal of 2,500 plus 300 plus 4,000 plus
        3,000, which is 9,800", the discount is five percent because "a base
        subtotal from 5,000 cents up to but not including 10,000 cents earns five
        percent", the surcharge is twelve percent because an immobilizer job is
        present, "and `total_access_fee_cents` is 9,800 minus 490 plus 1,176,
        which is 10,486."

        Design: Difficulty/combinatorial_formula/gateway_fee_discount_tier_keyed_on_base_subtotal_not_total
        """
        ctx = fixtures.build_session_with_completed_jobs(
            api,
            job_types=(JobType.IMMOBILIZER_KEY, JobType.MODULE_FLASH),
            covered_area_codes=("POWERTRAIN",),
        )

        completed = validate_success(
            api.complete_gateway_session(
                ctx["sessions"]["main"]["id"], ctx["tech_headers"]["main"]
            )
        )

        assert_gateway_session(completed)
        assert completed["status"] == SessionStatus.COMPLETED
        assert_gateway_fee_breakdown(completed, 9800, 490, 1176, 10486)
        assert completed["total_access_fee_cents"] != 9996

    def test_the_access_fee_accrues_outside_the_data_credit_ledger(self, api):
        """The fee lands on the shop's running total and releases the tool.

        PRD 3.7: both closing branches "add the resulting
        `total_access_fee_cents` to the owning shop's `gateway_fee_accrued_cents`,
        release the diagnostic tool back to `IDLE` with `occupied_by_session_id`
        cleared". PRD 3.3 keeps that total out of the credit identity, because
        "secure-gateway access fees accrue as a separate running total and are
        never netted against the data-credit balance".

        Design: Difficulty/combinatorial_formula/gateway_fee_discount_tier_keyed_on_base_subtotal_not_total
        """
        ctx = fixtures.build_session_with_completed_jobs(
            api,
            job_types=(JobType.IMMOBILIZER_KEY, JobType.MODULE_FLASH),
            covered_area_codes=("POWERTRAIN",),
        )
        validate_success(
            api.complete_gateway_session(
                ctx["sessions"]["main"]["id"], ctx["tech_headers"]["main"]
            )
        )

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["gateway_fee_accrued_cents"] == 10486
        assert_data_credit_conservation(shop, ctx["entitlement"])

        tool = _tool_row(api, ctx, ctx["tools"]["main"]["id"])
        assert_diagnostic_tool(tool)
        assert tool["status"] == ToolStatus.IDLE
        assert tool["occupied_by_session_id"] is None


class TestActivationGateOrder:
    """An unverified identity is reported before any tool contention."""

    def test_identity_gate_outranks_the_tool_window_gate(self, api):
        """Both gates would fail; the earlier gate in the list is the one reported.

        PRD 3.7 checks the six conditions "in this order", with "the seated
        technician's `identity_status` must read `VERIFIED`, failing which
        `ERR_TECHNICIAN_NOT_VERIFIED`" ahead of the rule that "no sibling session
        on the same tool that is currently `ACTIVE` may overlap this session's
        window under the half-open arithmetic of §2.9".

        Design: Difficulty/priority_pair_validation_conflict/activate_session_unverified_identity_beats_tool_window_conflict
        """
        ctx = fixtures.build_seated_technician(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_technician(api, ctx, key="uri", full_name="Uri Unchecked", verify=False)
        fixtures.add_seat(api, ctx, key="uri")
        fixtures.add_session(
            api,
            ctx,
            key="tina",
            technician_key="main",
            activate=True,
            window_start="2026-08-03T09:00:00Z",
            window_end="2026-08-03T12:00:00Z",
        )
        fixtures.add_session(
            api,
            ctx,
            key="uri",
            technician_key="uri",
            activate=False,
            vin=VIN_SECONDARY,
            window_start="2026-08-03T10:00:00Z",
            window_end="2026-08-03T11:00:00Z",
        )

        response = api.activate_gateway_session(
            ctx["sessions"]["uri"]["id"], ctx["tech_headers"]["uri"]
        )

        error = validate_error(response, ApiErrorId.TECHNICIAN_NOT_VERIFIED, 409)
        assert error["error_id"] != ApiErrorId.TOOL_WINDOW_CONFLICT

    def test_a_refused_activation_mints_no_credential_and_leaves_the_tool_held(
        self, api
    ):
        """The refused session stays REQUESTED with no token and no trail row.

        PRD 3.7: "A successful request opens the session in `REQUESTED` with
        `credential_token` null", and only on activation is the token minted and a
        `SESSION_CREDENTIAL_ISSUED` row appended; the tool's
        `occupied_by_session_id` continues to name the incumbent active session.

        Design: Difficulty/priority_pair_validation_conflict/activate_session_unverified_identity_beats_tool_window_conflict
        """
        ctx = fixtures.build_seated_technician(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_technician(api, ctx, key="uri", full_name="Uri Unchecked", verify=False)
        fixtures.add_seat(api, ctx, key="uri")
        fixtures.add_session(
            api,
            ctx,
            key="tina",
            technician_key="main",
            activate=True,
            window_start="2026-08-03T09:00:00Z",
            window_end="2026-08-03T12:00:00Z",
        )
        fixtures.add_session(
            api,
            ctx,
            key="uri",
            technician_key="uri",
            activate=False,
            vin=VIN_SECONDARY,
            window_start="2026-08-03T10:00:00Z",
            window_end="2026-08-03T11:00:00Z",
        )
        validate_error(
            api.activate_gateway_session(
                ctx["sessions"]["uri"]["id"], ctx["tech_headers"]["uri"]
            ),
            ApiErrorId.TECHNICIAN_NOT_VERIFIED,
            409,
        )

        refused = fixtures.refresh_session(api, ctx, key="uri", technician_key="uri")
        assert refused["status"] == SessionStatus.REQUESTED
        assert refused["credential_token"] is None

        tool = _tool_row(api, ctx, ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.OCCUPIED
        assert tool["occupied_by_session_id"] == ctx["sessions"]["tina"]["id"]

        events, _meta = validate_paginated(
            api.list_audit_events(
                make_compliance_officer_headers(),
                {"subject_id": refused["id"], "limit": 100},
            )
        )
        assert_no_audit_event(
            events, AuditEventType.SESSION_CREDENTIAL_ISSUED, subject_id=refused["id"]
        )


class TestToolWindowHalfOpenArithmetic:
    """Adjacent windows share the tool; overlapping windows do not."""

    def test_a_session_starting_at_the_incumbents_end_instant_activates(self, api):
        """Back-to-back windows touch without conflicting.

        PRD 3.7: "no sibling session on the same tool that is currently `ACTIVE`
        may overlap this session's window under the half-open arithmetic of §2.9",
        and PRD 2.9 spells the consequence out: "Back-to-back windows, where one
        starts at the exact instant another ends, are accepted; there is no
        buffer."

        Design: Difficulty/resource_temporal_overlap/tool_session_half_open_adjacency_allowed_overlap_rejected
        """
        ctx = fixtures.build_seated_technician(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_session(
            api,
            ctx,
            key="session_a",
            activate=True,
            window_start="2026-08-03T09:00:00Z",
            window_end="2026-08-03T12:00:00Z",
        )
        fixtures.add_session(
            api,
            ctx,
            key="session_b",
            activate=False,
            vin=VIN_SECONDARY,
            window_start="2026-08-03T12:00:00Z",
            window_end="2026-08-03T14:00:00Z",
        )

        activated = validate_success(
            api.activate_gateway_session(
                ctx["sessions"]["session_b"]["id"], ctx["tech_headers"]["main"]
            )
        )

        assert_gateway_session(activated)
        assert activated["status"] == SessionStatus.ACTIVE
        assert_credential_token_derived_from_session(activated)

        tool = _tool_row(api, ctx, ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.OCCUPIED
        assert tool["occupied_by_session_id"] == activated["id"]

    def test_an_overlapping_session_is_refused_on_the_tool_window(self, api):
        """A window straddling the incumbent's end instant genuinely overlaps.

        PRD 3.7: "no sibling session on the same tool that is currently `ACTIVE`
        may overlap this session's window under the half-open arithmetic of §2.9 —
        that is, no sibling whose start is strictly before this window's end while
        this window's start is strictly before that sibling's end — failing which
        `ERR_TOOL_WINDOW_CONFLICT`." PRD 2.9: "Diagnostic tool occupation windows
        are compared as **half-open intervals with no buffer**, so a session
        starting at the exact instant a prior session ends is accepted."

        Design: Difficulty/resource_temporal_overlap/tool_session_half_open_adjacency_allowed_overlap_rejected
        """
        ctx = fixtures.build_seated_technician(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_session(
            api,
            ctx,
            key="session_a",
            activate=True,
            window_start="2026-08-03T09:00:00Z",
            window_end="2026-08-03T12:00:00Z",
        )
        fixtures.add_session(
            api,
            ctx,
            key="session_c",
            activate=False,
            vin=VIN_TERTIARY,
            window_start="2026-08-03T11:00:00Z",
            window_end="2026-08-03T13:00:00Z",
        )

        validate_error(
            api.activate_gateway_session(
                ctx["sessions"]["session_c"]["id"], ctx["tech_headers"]["main"]
            ),
            ApiErrorId.TOOL_WINDOW_CONFLICT,
            409,
        )

        refused = fixtures.refresh_session(api, ctx, key="session_c")
        assert refused["status"] == SessionStatus.REQUESTED
        assert refused["credential_token"] is None

        incumbent = fixtures.refresh_session(api, ctx, key="session_a")
        assert incumbent["status"] == SessionStatus.ACTIVE
