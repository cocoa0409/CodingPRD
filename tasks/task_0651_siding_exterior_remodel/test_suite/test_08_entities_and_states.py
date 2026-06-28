"""Entity creation defaults, validation, computed fields, and state-machine corners."""
from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    bootstrap_actors, create_draft_project, create_measured_project,
    create_draft_estimate, create_baselined_project, add_line_item,
    current_project_version, create_dual_signed_change_order, approve_change_order,
)
from test_helpers.factories import (
    create_staff_payload, create_client_payload, create_measurement_payload,
)
from test_helpers.assertions import assert_project, assert_measurement


class TestProjectCreation:
    def test_create_project_returns_201_with_status_defaults(self, api):
        """PRD §3.1: "A new project starts with `workflow_status` of `DRAFT` and
        `compliance_status` of `PENDING_CLEARANCE`, and with its computed cash fields
        `contract_total_cents`, `retainage_held_cents`, and `amount_released_cents`
        all at zero."
        PRD §3.1: "`hoa_required` defaults to false when omitted."

        Design: Corner/entities/create_project_returns_201_with_defaults
        """
        actors = bootstrap_actors()
        resp = _ac.create_project(
            {"client_id": actors["client_id"], "project_manager_id": actors["pm_id"],
             "property_address": "100 Cedar"}, actors["pm_h"])
        data = validate_success(resp, expected_status=201)
        assert_project(data)
        assert data["workflow_status"] == "DRAFT"
        assert data["compliance_status"] == "PENDING_CLEARANCE"
        assert data["hoa_required"] is False
        assert data["contract_total_cents"] == 0
        assert data["retainage_held_cents"] == 0
        assert data["amount_released_cents"] == 0

    def test_create_project_missing_property_address_returns_invalid_request(self, api):
        """PRD §3.12: "Request well-formedness follows: a missing required field, a
        bad type, an enum value outside its set, or a numeric range violation yields
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_project_missing_required_field_returns_invalid_request
        """
        actors = bootstrap_actors()
        resp = _ac.create_project(
            {"client_id": actors["client_id"], "project_manager_id": actors["pm_id"]}, actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_nonexistent_project_returns_not_found(self, api):
        """PRD §2.7: "the first one that does not resolve to an existing resource
        causes the request to fail with `ERR_NOT_FOUND` (HTTP 404) before any later
        identifier is examined."

        Design: Corner/entities/get_project_nonexistent_returns_not_found
        """
        actors = bootstrap_actors()
        resp = _ac.get_project(NON_EXISTENT_UUID, actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_project_listing_returns_paginated_array_envelope(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object of the envelope."

        Design: Corner/entities/project_listing_pagination_envelope
        """
        proj, actors = create_draft_project()
        data, meta = validate_paginated(_ac.list_projects(actors["pm_h"], params={"limit": 1, "offset": 0}))
        assert isinstance(data, list)
        assert meta["total_count"] >= 1, f"expected >=1 project, got {meta['total_count']}"


class TestLineItemValidation:
    def test_invalid_scope_kind_returns_invalid_request(self, api):
        """PRD §3.3: "Each `EstimateLineItem` belongs to its estimate (recorded as
        `estimate_id`) and prices a single `scope_kind`, which is one of `SIDING`,
        `TRIM`, or `WRAP`."
        PRD §3.12: "Request well-formedness follows: a missing required field, a bad
        type, an enum value outside its set, or a numeric range violation yields
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_line_item_invalid_enum_scope_kind_returns_invalid_request
        """
        _proj, _meas, est, actors = create_draft_estimate()
        resp = _ac.create_line_item(
            est["id"], {"scope_kind": "GUTTER", "quantity": 100, "unit_price_cents": 500}, actors["est_h"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestMeasurementComputed:
    def test_net_siding_sqft_is_gross_minus_opening(self, api):
        """PRD §3.2: "Upon recording, the system computes `net_siding_sqft` as the
        gross wall area minus the opening area, with the result held at no less than
        zero — that is, if openings would exceed the gross wall area the net is zero
        rather than a negative number."

        Design: Corner/entities/measurement_net_siding_sqft_computed_input_ignored
        """
        proj, actors = create_draft_project()
        meas = validate_success(_ac.create_measurement(
            proj["id"],
            create_measurement_payload(actors["est_id"], gross_wall_sqft=1500,
                                       opening_sqft=300, linear_trim_ft=200),
            actors["est_h"]), expected_status=201)
        assert_measurement(meas)
        assert meas["net_siding_sqft"] == 1200.0, \
            f"net = 1500 - 300 = 1200.0, got {meas['net_siding_sqft']}"


class TestBaselineSideEffects:
    def test_baseline_creates_two_pending_warranties_and_advances_workflow(self, api):
        """PRD §3.3: "On success the estimate's `status` becomes `BASELINE`, the
        project's `workflow_status` becomes `ESTIMATED`, the project's
        `contract_total_cents` is set equal to this estimate's `estimate_total_cents`,
        and the system creates two `PENDING` warranty rows for the project — one per
        `warranty_kind`, namely `LIFETIME_MATERIAL` and `WORKMANSHIP`."

        Design: Corner/state_machines/baseline_initial_state_warranties_created_pending
        """
        _proj, _meas, est, actors = create_draft_estimate()
        proj_id = est["project_id"]
        add_line_item(est["id"], actors, scope_kind="SIDING", quantity=1000, unit_price_cents=1000)
        get_success_data(_ac.baseline_estimate(est["id"], actors["pm_h"]))
        refetched = validate_success(_ac.get_project(proj_id, actors["pm_h"]))
        assert refetched["workflow_status"] == "ESTIMATED"
        data, meta = validate_paginated(_ac.list_warranties(actors["pm_h"], params={"project_id": proj_id}))
        assert meta["total_count"] == 2, f"expected 2 warranties, got {meta['total_count']}"
        kinds = sorted(w["warranty_kind"] for w in data)
        assert kinds == ["LIFETIME_MATERIAL", "WORKMANSHIP"], f"got kinds {kinds}"
        assert all(w["status"] == "PENDING" for w in data), \
            f"warranties must be PENDING, got {[w['status'] for w in data]}"

    def test_baseline_empty_estimate_returns_empty_estimate(self, api):
        """PRD §3.3: "the estimate to hold at least one `EstimateLineItem` (an
        estimate with zero line items cannot become baseline and is rejected with
        `ERR_EMPTY_ESTIMATE`, HTTP 422)"

        Design: Corner/validations/baseline_empty_estimate_returns_empty_estimate
        """
        _proj, _meas, est, actors = create_draft_estimate()
        resp = _ac.baseline_estimate(est["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_EMPTY_ESTIMATE.value)

    def test_second_baseline_returns_baseline_exists(self, api):
        """PRD §3.3: "no other `BASELINE` estimate to already exist for the project —
        a second baseline attempt is rejected with `ERR_BASELINE_EXISTS` (HTTP 409)
        rather than superseding the first."

        Design: Corner/validations/second_baseline_returns_baseline_exists
        """
        proj, _meas, actors = create_measured_project()
        est1 = get_success_data(_ac.create_estimate(
            {"project_id": proj["id"], "measurement_id": _meas["id"], "waste_factor_pct": 0.10}, actors["est_h"]))
        add_line_item(est1["id"], actors, scope_kind="SIDING", quantity=1000, unit_price_cents=1000)
        get_success_data(_ac.baseline_estimate(est1["id"], actors["pm_h"]))
        est2 = get_success_data(_ac.create_estimate(
            {"project_id": proj["id"], "measurement_id": _meas["id"], "waste_factor_pct": 0.10}, actors["est_h"]))
        add_line_item(est2["id"], actors, scope_kind="SIDING", quantity=1000, unit_price_cents=1000)
        resp = _ac.baseline_estimate(est2["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_BASELINE_EXISTS.value)


class TestChangeOrderTerminalLockdown:
    def test_reject_approved_changeorder_returns_invalid_state(self, api):
        """PRD §3.7: "A `ProjectManager` may reject a `SUBMITTED` change order, setting
        its `status` to `REJECTED`."
        PRD §3.12: "State-machine admissibility comes next: a target resource not in a
        state from which the requested transition is allowed yields `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/terminal_state_lockdown_approved_changeorder_cannot_reject
        """
        proj, est, line_map, actors = create_baselined_project()
        line_id = line_map["SIDING"]["id"]
        co = create_dual_signed_change_order(proj["id"], line_id, actors, delta_cents=20000)
        approve_change_order(proj["id"], co["id"], actors)
        resp = _ac.reject_change_order(co["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestImmediateConsistency:
    def test_contract_total_visible_immediately_after_baseline(self, api):
        """PRD §3.3: "On success the estimate's `status` becomes `BASELINE`, the
        project's `workflow_status` becomes `ESTIMATED`, the project's
        `contract_total_cents` is set equal to this estimate's `estimate_total_cents`"

        Design: Corner/consistency_model/immediate_consistency_contract_total_visible_same_response
        """
        # Single SIDING line 1000@1000c with 0.10 waste -> extended 1100000;
        # subtotal 1100000, tax 90750, total 1190750.
        proj, est, line_map, actors = create_baselined_project()
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["contract_total_cents"] == 1190750, \
            f"contract_total must be visible immediately as 1190750, got {refetched['contract_total_cents']}"
