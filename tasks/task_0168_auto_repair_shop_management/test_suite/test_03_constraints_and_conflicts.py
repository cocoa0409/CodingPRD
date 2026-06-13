"""Cross-entity state dependencies, resource-temporal conflicts (bay overlap,
technician cleanup buffer), and the state-vs-business validation precedence that
the PRD pins explicitly.

Covers difficulty queue rules: cross_entity_state_dependency,
resource_temporal_overlap, and the close_invalid_state precedence instance of
priority_pair_validation_conflict (the red-vs-labor instance is skipped — PRD
prose states no precedence among those two completion business rules).
"""
from test_helpers import (
    validate_success,
    validate_error,
    fixtures as fx,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_customer_headers, make_technician_headers
from test_helpers import factories as f

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]
PM = TEST_USERS["parts_manager_headers"]


# ===========================================================================
# cross_entity_state_dependency — approve RJ requires owning RO not terminal
# ===========================================================================
class TestApproveRecommendedJobRequiresRoNotTerminal:
    def test_approve_on_cancelled_ro_rejected(self, api):
        """PRD §3.11: "Approving moves a `PENDING` or `DEFERRED` job to `APPROVED`
        and requires the owning order to be in `ESTIMATE`, `APPROVED`,
        `IN_PROGRESS`, or `ON_HOLD` status (else `ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/approve_recommended_job_requires_ro_not_terminal
        """
        s = fx.setup_inspection_with_pending_job(api, item_severity="YELLOW")
        ro_id = s["ro"]["id"]
        fx.transition_ro(api, ro_id, "CANCEL")
        resp = api.decide_recommended_job(
            s["recommended_job"]["id"], {"decision": "APPROVE"},
            make_customer_headers(s["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_recommended_job_unchanged_after_rejected_approve(self, api):
        """PRD §3.11: "Approving moves a `PENDING` or `DEFERRED` job to `APPROVED`
        and requires the owning order to be in `ESTIMATE`, `APPROVED`,
        `IN_PROGRESS`, or `ON_HOLD` status (else `ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/approve_recommended_job_requires_ro_not_terminal
        """
        s = fx.setup_inspection_with_pending_job(api, item_severity="YELLOW")
        ro_id = s["ro"]["id"]
        fx.transition_ro(api, ro_id, "CANCEL")
        api.decide_recommended_job(
            s["recommended_job"]["id"], {"decision": "APPROVE"},
            make_customer_headers(s["customer"]["id"]),
        )
        rj = validate_success(api.get_recommended_job(s["recommended_job"]["id"], SM), 200)
        assert rj["status"] == "PENDING", "rejected approve must leave the job PENDING"


# ===========================================================================
# cross_entity_state_dependency — complete RO requires inspection SUBMITTED
# ===========================================================================
class TestCompleteRequiresInspectionSubmitted:
    def test_complete_with_draft_inspection_rejected(self, api):
        """PRD §3.3: "If the order has an inspection, that inspection must be
        `SUBMITTED` or `REVIEWED`, or completion is refused with
        `ERR_INSPECTION_NOT_SUBMITTED`."

        Design: Difficulty/cross_entity_state_dependency/complete_ro_requires_inspection_submitted
        """
        ro_id, tech_id = _ro_started_with_completed_line_and_draft_inspection(api)
        resp = api.complete_repair_order(ro_id, make_technician_headers(tech_id))
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_SUBMITTED.value)

    def test_ro_remains_in_progress_after_rejected_complete(self, api):
        """PRD §3.3: "If the order has an inspection, that inspection must be
        `SUBMITTED` or `REVIEWED`, or completion is refused with
        `ERR_INSPECTION_NOT_SUBMITTED`."

        Design: Difficulty/cross_entity_state_dependency/complete_ro_requires_inspection_submitted
        """
        ro_id, tech_id = _ro_started_with_completed_line_and_draft_inspection(api)
        api.complete_repair_order(ro_id, make_technician_headers(tech_id))
        ro = validate_success(api.get_repair_order(ro_id, SM), 200)
        assert ro["status"] == "IN_PROGRESS"


def _ro_started_with_completed_line_and_draft_inspection(api):
    """RO IN_PROGRESS with its single labor line COMPLETED, and a DRAFT inspection
    (one item, never submitted). Returns (ro_id, technician_id)."""
    operation = fx.create_labor_operation(api)
    technician = fx.create_technician(api)
    customer, vehicle = fx.create_customer_and_vehicle(api)
    bay = fx.create_service_bay(api)
    ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
    ll = validate_success(
        api.create_labor_line(
            ro["id"],
            f.create_labor_line_payload(
                operation["id"], technician_id=technician["id"], billing_method="FLAT_RATE"
            ),
            SM,
        ),
        201,
    )
    insp = fx.create_inspection(api, ro["id"], technician["id"])
    fx.add_item(api, insp["id"], technician["id"], "Oil level", "GREEN")
    fx.authorize_ro(api, ro["id"], customer["id"])
    fx.schedule_ro(api, ro["id"], bay["id"], "2026-06-06T08:00:00Z", "2026-06-06T12:00:00Z")
    fx.transition_ro(api, ro["id"], "START")
    fx.clock_session_and_complete(api, ll["id"], technician["id"],
                                  "2026-06-06T09:00:00Z", "2026-06-06T10:00:00Z")
    return ro["id"], technician["id"]


# ===========================================================================
# resource_temporal_overlap — bay half-open window overlap
# ===========================================================================
class TestBayWindowOverlap:
    def test_overlapping_window_on_same_bay_rejected(self, api):
        """PRD §3.2: "It may not overlap any other repair order's window on the same
        bay; two windows that merely touch at an endpoint do not overlap and are
        allowed, but any genuine overlap is rejected with `ERR_BAY_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/bay_window_half_open_overlap_rejected
        """
        bay = fx.create_service_bay(api)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro_a = fx.create_repair_order(api, customer["id"], vehicle["id"])
        ro_b = fx.create_repair_order(api, customer["id"], vehicle["id"])
        fx.schedule_ro(api, ro_a["id"], bay["id"],
                       "2026-06-07T09:00:00Z", "2026-06-07T11:00:00Z")
        resp = api.schedule_repair_order(
            ro_b["id"],
            f.schedule_payload(bay["id"], "2026-06-07T10:00:00Z", "2026-06-07T12:00:00Z"),
            SM,
        )
        validate_error(resp, ApiErrorId.ERR_BAY_DOUBLE_BOOKED.value)

    def test_touching_window_on_same_bay_allowed(self, api):
        """PRD §3.2: "The requested window is treated as a half-open interval that
        begins at `scheduled_start` and runs up to but not including
        `scheduled_end`. It may not overlap any other repair order's window on the
        same bay; two windows that merely touch at an endpoint do not overlap and
        are allowed".

        Design: Difficulty/resource_temporal_overlap/bay_window_half_open_overlap_rejected
        """
        bay = fx.create_service_bay(api)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro_a = fx.create_repair_order(api, customer["id"], vehicle["id"])
        ro_b = fx.create_repair_order(api, customer["id"], vehicle["id"])
        fx.schedule_ro(api, ro_a["id"], bay["id"],
                       "2026-06-07T09:00:00Z", "2026-06-07T11:00:00Z")
        # [11:00,12:00) touches [09:00,11:00) at 11:00 — allowed.
        scheduled = validate_success(
            api.schedule_repair_order(
                ro_b["id"],
                f.schedule_payload(bay["id"], "2026-06-07T11:00:00Z", "2026-06-07T12:00:00Z"),
                SM,
            ),
            200,
        )
        assert scheduled["bay_id"] == bay["id"]


# ===========================================================================
# resource_temporal_overlap — technician cleanup buffer
# ===========================================================================
class TestTechnicianCleanupBuffer:
    def test_clock_in_within_cleanup_buffer_rejected(self, api):
        """PRD §3.9: "the supplied `clock_in` instant must fall at least a
        ten-minute cleanup buffer after the technician's `last_clock_out_at`; a
        clock-in earlier than ten minutes after their most recent clock-out is
        likewise rejected with `ERR_TECH_DOUBLE_CLOCKED`."

        Design: Difficulty/resource_temporal_overlap/technician_clock_in_within_cleanup_buffer_rejected
        """
        ll2_id, tech_id = _two_lines_one_clocked_out(api)
        # Clock-out was at 10:00; clock-in at 10:05 is within the 10-min buffer.
        resp = api.clock_in_labor_line(
            ll2_id, {"technician_id": tech_id, "clock_in": "2026-06-08T10:05:00Z"},
            make_technician_headers(tech_id),
        )
        validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_CLOCKED.value)

    def test_line_remains_not_started_after_rejected_clock_in(self, api):
        """PRD §3.9: "a clock-in earlier than ten minutes after their most recent
        clock-out is likewise rejected with `ERR_TECH_DOUBLE_CLOCKED`."

        Design: Difficulty/resource_temporal_overlap/technician_clock_in_within_cleanup_buffer_rejected
        """
        ll2_id, tech_id = _two_lines_one_clocked_out(api)
        api.clock_in_labor_line(
            ll2_id, {"technician_id": tech_id, "clock_in": "2026-06-08T10:05:00Z"},
            make_technician_headers(tech_id),
        )
        ll2 = validate_success(api.get_labor_line(ll2_id, SM), 200)
        assert ll2["status"] == "NOT_STARTED", "rejected clock-in must leave the line NOT_STARTED"


def _two_lines_one_clocked_out(api):
    """Two started ROs (separate bays) sharing one technician. Line L1 is clocked
    [09:00,10:00] and clocked out; line L2 is fresh. Returns (l2_id, tech_id)."""
    operation = fx.create_labor_operation(api)
    technician = fx.create_technician(api)
    customer, vehicle = fx.create_customer_and_vehicle(api)
    bay1 = fx.create_service_bay(api)
    bay2 = fx.create_service_bay(api)

    ro1 = fx.create_repair_order(api, customer["id"], vehicle["id"])
    l1 = validate_success(
        api.create_labor_line(
            ro1["id"],
            f.create_labor_line_payload(operation["id"], technician_id=technician["id"]),
            SM,
        ),
        201,
    )
    fx.authorize_ro(api, ro1["id"], customer["id"])
    fx.schedule_ro(api, ro1["id"], bay1["id"], "2026-06-08T08:00:00Z", "2026-06-08T12:00:00Z")
    fx.transition_ro(api, ro1["id"], "START")

    ro2 = fx.create_repair_order(api, customer["id"], vehicle["id"])
    l2 = validate_success(
        api.create_labor_line(
            ro2["id"],
            f.create_labor_line_payload(operation["id"], technician_id=technician["id"]),
            SM,
        ),
        201,
    )
    fx.authorize_ro(api, ro2["id"], customer["id"])
    fx.schedule_ro(api, ro2["id"], bay2["id"], "2026-06-08T08:00:00Z", "2026-06-08T12:00:00Z")
    fx.transition_ro(api, ro2["id"], "START")

    fx.clock_in(api, l1["id"], technician["id"], "2026-06-08T09:00:00Z")
    fx.clock_out(api, l1["id"], technician["id"], "2026-06-08T10:00:00Z")
    return l2["id"], technician["id"]


# ===========================================================================
# priority_pair_validation_conflict — state check precedes business check
# (PRD §2.6 pins ERR_INVALID_STATE before the domain business rules)
# ===========================================================================
class TestCloseInvalidStateBeatsCoreOutstanding:
    def test_close_on_completed_ro_with_charged_core_returns_invalid_state(self, api):
        """PRD §2.6: "the target resource must be in a state where the requested
        transition is permitted (`ERR_INVALID_STATE`); and ... Only after these
        gates pass are the domain-specific business rules of Section 3 evaluated."
        PRD §3.3: "Closing advances an `INVOICED` order to `CLOSED` (else
        `ERR_INVALID_STATE`); it is refused while any core charge on the order is
        still in `CHARGED` status (`ERR_CORE_OUTSTANDING`)".

        Design: Difficulty/priority_pair_validation_conflict/close_invalid_state_beats_core_outstanding
        """
        ro_id = _completed_ro_with_charged_core(api)
        # RO is COMPLETED (not INVOICED), so CLOSE fails the state gate first.
        resp = api.transition_repair_order(ro_id, {"action": "CLOSE"}, SA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_completed_ro_unchanged_after_invalid_close(self, api):
        """PRD §2.6: "the target resource must be in a state where the requested
        transition is permitted (`ERR_INVALID_STATE`); and ... Only after these
        gates pass are the domain-specific business rules of Section 3 evaluated."

        Design: Difficulty/priority_pair_validation_conflict/close_invalid_state_beats_core_outstanding
        """
        ro_id = _completed_ro_with_charged_core(api)
        api.transition_repair_order(ro_id, {"action": "CLOSE"}, SA)
        ro = validate_success(api.get_repair_order(ro_id, SM), 200)
        assert ro["status"] == "COMPLETED"


def _completed_ro_with_charged_core(api):
    """RO driven to COMPLETED while still holding a CHARGED core charge.
    Returns ro_id."""
    fx.setup_markup_matrix(api, [(0, 0, 20000, 0.40)])
    operation = fx.create_labor_operation(api)
    technician = fx.create_technician(api)
    customer, vehicle = fx.create_customer_and_vehicle(api)
    bay = fx.create_service_bay(api)
    ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
    ll = validate_success(
        api.create_labor_line(
            ro["id"],
            f.create_labor_line_payload(
                operation["id"], technician_id=technician["id"], billing_method="FLAT_RATE"
            ),
            SM,
        ),
        201,
    )
    validate_success(
        api.create_part_line(
            ro["id"],
            f.create_part_line_payload(
                "WP-1", 1, 8000, markup_mode="FLAT_BRACKET", has_core=True, core_deposit_cents=4000
            ),
            PM,
        ),
        201,
    )
    fx.authorize_ro(api, ro["id"], customer["id"])
    fx.schedule_ro(api, ro["id"], bay["id"], "2026-06-05T08:00:00Z", "2026-06-05T12:00:00Z")
    fx.transition_ro(api, ro["id"], "START")
    fx.clock_session_and_complete(api, ll["id"], technician["id"],
                                  "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z")
    validate_success(
        api.complete_repair_order(ro["id"], make_technician_headers(technician["id"])), 200
    )
    return ro["id"]
