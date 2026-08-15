"""Clearance-request intake validation, state-machine boundaries, fair-use reroute."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_request,
    create_asset,
    create_clearance_request,
    create_clearance_request_payload,
    create_rights_holder,
    get_success_data,
    make_certifier_headers,
    make_curator_headers,
    make_officer_headers,
    make_requester_headers,
    setup_approved_request,
    setup_holder_asset,
    setup_request_in_negotiating,
    validate_error,
    validate_success,
)


class TestClearanceRequestSchema:
    def test_missing_requested_units_rejected(self, api):
        """PRD §2.8 step 3: "Request-body schema — required fields present, enum
        values in range, datetimes well-formed, integer fields at or above their
        minimums; failure is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/clearance_request_missing_required_field_rejected
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        requester = make_requester_headers("req_c_1")
        resp = api.create_clearance_request(
            asset["id"],
            {
                "media": "STREAMING",
                "territory": "NA",
                "use_start_at": "2026-09-01T00:00:00Z",
                "use_end_at": "2026-10-01T00:00:00Z",
            },
            requester,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_media_enum_rejected(self, api):
        """PRD §2.8 step 3: "Request-body schema — required fields present, enum
        values in range, datetimes well-formed, integer fields at or above their
        minimums; failure is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/clearance_request_invalid_enum_rejected
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        requester = make_requester_headers("req_c_2")
        resp = api.create_clearance_request(
            asset["id"],
            {
                "media": "CABLE_TV",
                "territory": "NA",
                "use_start_at": "2026-09-01T00:00:00Z",
                "use_end_at": "2026-10-01T00:00:00Z",
                "requested_units": 1,
            },
            requester,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_zero_length_window_rejected(self, api):
        """PRD §3.2: "The window is half-open: the start is inclusive, the end
        exclusive, and `use_end_at` must fall strictly after `use_start_at` —
        a zero-length or inverted window is rejected with `ERR_INVALID_WINDOW`."

        Design: Corner/validations/invalid_window_zero_length_rejected
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        requester = make_requester_headers("req_c_24")
        resp = api.create_clearance_request(
            asset["id"],
            {
                "media": "STREAMING",
                "territory": "NA",
                "use_start_at": "2026-09-01T00:00:00Z",
                "use_end_at": "2026-09-01T00:00:00Z",
                "requested_units": 1,
            },
            requester,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestClearanceAdvanceStateMachine:
    def test_advance_from_negotiating_returns_invalid_state(self, api):
        """PRD §3.2: "a `ClearanceOfficer` advances the request along `SUBMITTED`
        → `HOLDER_REVIEW` → `NEGOTIATING`, one step per call"
        PRD §2.8 step 6: "Transition legality — the target resource is in a state
        from which the requested transition exists; failure is `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/clearance_advance_from_negotiating_returns_invalid_state
        """
        holder, asset, req, _rid = setup_request_in_negotiating()
        officer = make_officer_headers("off_c_4")
        resp = api.advance_clearance_request(req["id"], req["version"], officer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdraw_on_terminal_request_returns_invalid_state(self, api):
        """PRD §3.2: "Withdrawal is the requester's own exit: the calling header
        must equal the recorded `requester_id` — another user's attempt is
        `ERR_FORBIDDEN_OWNER_ONLY` — and withdrawal is permitted from `SUBMITTED`,
        `HOLDER_REVIEW`, or `NEGOTIATING`, rejecting any `OPEN` rounds when
        leaving the last. Both `DENIED` and `WITHDRAWN` are terminal."

        Design: Corner/state_machines/withdraw_terminal_request_returns_invalid_state
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        req, rid = create_clearance_request(
            asset["id"],
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=2,
        )
        # Officer denies from SUBMITTED.
        officer = make_officer_headers("off_c_5")
        deny_resp = api.deny_clearance_request(req["id"], officer)
        validate_success(deny_resp)
        # Owner tries to withdraw the DENIED request.
        requester = make_requester_headers(rid)
        resp = api.withdraw_clearance_request(req["id"], requester)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestClearanceAutoExpiry:
    def test_submitted_request_expires_when_clock_passes_use_end(self, api):
        """PRD §3.2: "the clock closes stale work: a request still in `SUBMITTED`
        when the clock reaches its `use_end_at` expires to `EXPIRED`, and an
        `APPROVED` request whose grant was never executed expires the same way
        when its window runs out."

        Design: Corner/state_machines/request_auto_expires_when_window_passes_ungranted
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        req, _rid = create_clearance_request(
            asset["id"],
            media="STREAMING",
            use_start_at="2026-08-02T00:00:00Z",
            use_end_at="2026-08-10T00:00:00Z",
            requested_units=1,
        )
        curator = make_curator_headers("cur_c_11")
        api.set_clock("2026-08-11T00:00:00Z", curator)
        officer = make_officer_headers("off_c_11")
        req_after = get_success_data(api.get_clearance_request(req["id"], officer))
        assert req_after["status"] == "EXPIRED"


class TestFairUseRoute:
    def test_fair_use_route_requires_social_or_print(self, api):
        """PRD §3.8: "The route is narrow: only `SOCIAL` or `PRINT` media are
        eligible, and any other medium is rejected with
        `ERR_FAIR_USE_MEDIA_INELIGIBLE`."

        Design: Corner/state_machines/fair_use_route_requires_social_or_print
        """
        holder, asset = setup_holder_asset(
            work_kind="LITERARY_EXCERPT", permitted_media=["STREAMING", "PRINT"]
        )
        requester = make_requester_headers("req_c_14")
        r_stream = get_success_data(
            api.create_clearance_request(
                asset["id"],
                {
                    "media": "STREAMING",
                    "territory": "NA",
                    "use_start_at": "2026-09-01T00:00:00Z",
                    "use_end_at": "2026-11-01T00:00:00Z",
                    "requested_units": 1,
                },
                requester,
            )
        )
        r_print = get_success_data(
            api.create_clearance_request(
                asset["id"],
                {
                    "media": "PRINT",
                    "territory": "NA",
                    "use_start_at": "2026-09-01T00:00:00Z",
                    "use_end_at": "2026-11-01T00:00:00Z",
                    "requested_units": 1,
                },
                requester,
            )
        )
        err_resp = api.create_fair_use_assessment(
            asset["id"],
            {
                "clearance_request_id": r_stream["id"],
                "factor_scores": {"purpose": 3, "nature": 2, "amount": 2, "market": 3},
            },
            requester,
        )
        validate_error(err_resp, ApiErrorId.ERR_FAIR_USE_MEDIA_INELIGIBLE)

        ok_resp = api.create_fair_use_assessment(
            asset["id"],
            {
                "clearance_request_id": r_print["id"],
                "factor_scores": {"purpose": 3, "nature": 2, "amount": 2, "market": 3},
            },
            requester,
        )
        fu = get_success_data(ok_resp)
        # 3 + 2 + 2 + 2*3 = 13
        assert fu["composite_score"] == 13
        officer = make_officer_headers("off_c_14")
        req_after = get_success_data(api.get_clearance_request(r_print["id"], officer))
        assert req_after["status"] == "FAIR_USE_ROUTE"
        assert req_after["fair_use_assessment_id"] == fu["id"]


class TestFairUseCertify:
    def test_composite_at_threshold_certifies_below_threshold_rejected(self, api):
        """PRD §3.8: "The composite must meet the bar — a `composite_score` of at
        least 13, with anything lower rejected as `ERR_FAIR_USE_SCORE_LOW`."

        Design: Corner/state_machines/fair_use_certify_boundary_and_low_score
        """
        holder, asset = setup_holder_asset(
            work_kind="LITERARY_EXCERPT", permitted_media=["PRINT"]
        )
        requester = make_requester_headers("req_c_15")
        r1 = get_success_data(
            api.create_clearance_request(
                asset["id"],
                {
                    "media": "PRINT",
                    "territory": "NA",
                    "use_start_at": "2026-09-01T00:00:00Z",
                    "use_end_at": "2026-11-01T00:00:00Z",
                    "requested_units": 1,
                },
                requester,
            )
        )
        fu1 = get_success_data(
            api.create_fair_use_assessment(
                asset["id"],
                {
                    "clearance_request_id": r1["id"],
                    "factor_scores": {"purpose": 3, "nature": 2, "amount": 2, "market": 3},
                },
                requester,
            )
        )
        r2 = get_success_data(
            api.create_clearance_request(
                asset["id"],
                {
                    "media": "PRINT",
                    "territory": "NA",
                    "use_start_at": "2026-09-01T00:00:00Z",
                    "use_end_at": "2026-11-01T00:00:00Z",
                    "requested_units": 1,
                },
                requester,
            )
        )
        fu2 = get_success_data(
            api.create_fair_use_assessment(
                asset["id"],
                {
                    "clearance_request_id": r2["id"],
                    "factor_scores": {"purpose": 2, "nature": 2, "amount": 2, "market": 2},
                },
                requester,
            )
        )
        certifier = make_certifier_headers("leg_c_15")
        err_resp = api.certify_fair_use_assessment(fu2["id"], certifier)
        validate_error(err_resp, ApiErrorId.ERR_FAIR_USE_SCORE_LOW)

        ok_resp = api.certify_fair_use_assessment(fu1["id"], certifier)
        fu1_after = get_success_data(ok_resp)
        assert fu1_after["status"] == "CERTIFIED"
        assert fu1_after["certified"] is True
