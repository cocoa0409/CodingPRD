"""Temporal overlap and budget-floor tests (PRD §3.2, §2.7)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    create_active_campaign,
    submit_referral,
    get_campaign,
    create_campaign_payload,
    create_policy_payload,
    api_client,
)


class TestCampaignWindowClosedIntervalTouchConflicts:
    def test_touching_campaign_window_conflicts(self, api):
        """PRD §3.2: "for the same `job_requisition_id`, the new window must not overlap
        the window of any other campaign in `DRAFT`, `ACTIVE`, `PAUSED`, or `EXHAUSTED` —
        and because the intervals are closed, two windows that merely touch at an
        endpoint *do* conflict, unlike policy windows. A violation is rejected with
        `ERR_CAMPAIGN_WINDOW_CONFLICT`."

        A window [2026-08-31, ...] touching an existing [2026-08-01, 2026-08-31] is
        rejected.

        Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_touch_conflicts
        """
        ta = TEST_USERS["talent_admin_headers"]
        req = create_open_requisition(
            req_number="REQ-SR-1", title="Sr Engineer", level="SENIOR", hard_to_fill=True
        )
        get_success_data(
            api.create_campaign(
                create_campaign_payload(
                    name="C1", job_requisition_id=req["id"],
                    window_start="2026-08-01T00:00:00Z", window_end="2026-08-31T00:00:00Z",
                    budget_cents=500000,
                ),
                ta,
            )
        )
        resp = api.create_campaign(
            create_campaign_payload(
                name="C2 touching", job_requisition_id=req["id"],
                window_start="2026-08-31T00:00:00Z", window_end="2026-09-30T00:00:00Z",
                budget_cents=500000,
            ),
            ta,
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT)

    def test_disjoint_campaign_window_accepted(self, api):
        """PRD §3.2: "for the same `job_requisition_id`, the new window must not overlap
        the window of any other campaign in `DRAFT`, `ACTIVE`, `PAUSED`, or `EXHAUSTED` —
        and because the intervals are closed, two windows that merely touch at an
        endpoint *do* conflict".
        PRD §3.2: "A campaign starts in `DRAFT`."

        A strictly later window [2026-09-01, 2026-09-30] shares no instant with
        [2026-08-01, 2026-08-31] and is accepted in DRAFT.

        Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_touch_conflicts
        """
        ta = TEST_USERS["talent_admin_headers"]
        req = create_open_requisition(
            req_number="REQ-SR-1", title="Sr Engineer", level="SENIOR", hard_to_fill=True
        )
        get_success_data(
            api.create_campaign(
                create_campaign_payload(
                    name="C1", job_requisition_id=req["id"],
                    window_start="2026-08-01T00:00:00Z", window_end="2026-08-31T00:00:00Z",
                    budget_cents=500000,
                ),
                ta,
            )
        )
        resp = api.create_campaign(
            create_campaign_payload(
                name="C3 disjoint", job_requisition_id=req["id"],
                window_start="2026-09-01T00:00:00Z", window_end="2026-09-30T00:00:00Z",
                budget_cents=500000,
            ),
            ta,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"


class TestPolicyWindowHalfOpenTouchAllowed:
    def test_touching_policy_windows_allowed(self, api):
        """PRD §3.2: "the candidate window, interpreted as the half-open interval from
        `effective_from` inclusive to `effective_to` exclusive, must not overlap the
        window of any other policy in `DRAFT` or `ACTIVE` — half-open semantics mean two
        windows that merely touch at an endpoint do *not* overlap — with a conflict
        rejected as `ERR_POLICY_WINDOW_CONFLICT` both at creation and at activation".

        A policy starting exactly at the predecessor's effective_to is accepted.

        Design: Difficulty/resource_temporal_overlap/policy_window_halfopen_touch_allowed
        """
        ta = TEST_USERS["talent_admin_headers"]
        get_success_data(
            api.create_policy_version(
                {"effective_from": "2026-01-01T00:00:00Z", "effective_to": "2026-08-01T00:00:00Z"},
                ta,
            )
        )
        resp = api.create_policy_version({"effective_from": "2026-08-01T00:00:00Z"}, ta)
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"

    def test_interior_overlapping_policy_window_rejected(self, api):
        """PRD §3.2: "the candidate window, interpreted as the half-open interval from
        `effective_from` inclusive to `effective_to` exclusive, must not overlap the
        window of any other policy in `DRAFT` or `ACTIVE` — half-open semantics mean two
        windows that merely touch at an endpoint do *not* overlap — with a conflict
        rejected as `ERR_POLICY_WINDOW_CONFLICT` both at creation and at activation".

        A window starting 2026-07-31 overlaps the interior of [2026-01-01, 2026-08-01)
        and is rejected.

        Design: Difficulty/resource_temporal_overlap/policy_window_halfopen_touch_allowed
        """
        ta = TEST_USERS["talent_admin_headers"]
        get_success_data(
            api.create_policy_version(
                {"effective_from": "2026-01-01T00:00:00Z", "effective_to": "2026-08-01T00:00:00Z"},
                ta,
            )
        )
        resp = api.create_policy_version({"effective_from": "2026-07-31T00:00:00Z"}, ta)
        validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_CONFLICT)


class TestCampaignBudgetFloorExactFit:
    def _setup_reserved_campaign(self, api):
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition(
            req_number="REQ-SR-1", title="Sr Engineer", level="SENIOR"
        )
        camp = create_active_campaign(
            req["id"], budget_cents=500000, name="floor test",
        )
        submit_referral(emp["id"], req["id"], candidate_email="ca@x.com",
                        candidate_full_name="C A")
        return emp, req, camp

    def test_budget_exactly_reserved_plus_spent_accepted(self, api):
        """PRD §3.2: "The budget may never be lowered below what is already spoken for:
        the new `budget_cents` must be at least the sum of current `reserved_cents` and
        `spent_cents`, otherwise the edit is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED`."

        New budget 200000 exactly equals reserved (200000) + spent (0): accepted (>=
        boundary inclusive).

        Design: Difficulty/boundary_precision_check/campaign_budget_floor_exact_fit
        """
        _, _, camp = self._setup_reserved_campaign(api)
        ta = TEST_USERS["talent_admin_headers"]
        c = get_campaign(camp["id"])
        assert c["reserved_cents"] == 200000

        data = get_success_data(
            api.patch_campaign(
                camp["id"],
                {"expected_campaign_version": c["version"], "budget_cents": 200000},
                ta,
            )
        )
        assert data["budget_cents"] == 200000

    def test_budget_one_cent_below_floor_rejected(self, api):
        """PRD §3.2: "the new `budget_cents` must be at least the sum of current
        `reserved_cents` and `spent_cents`, otherwise the edit is rejected with
        `ERR_CAMPAIGN_BUDGET_EXCEEDED`."

        New budget 199999 is one cent below the 200000 floor: rejected.

        Design: Difficulty/boundary_precision_check/campaign_budget_floor_exact_fit
        """
        _, _, camp = self._setup_reserved_campaign(api)
        ta = TEST_USERS["talent_admin_headers"]
        c = get_campaign(camp["id"])
        resp = api.patch_campaign(
            camp["id"],
            {"expected_campaign_version": c["version"], "budget_cents": 199999},
            ta,
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED)
        # reservation untouched by the failed edit
        c_now = get_campaign(camp["id"])
        assert c_now["reserved_cents"] == 200000
        assert c_now["budget_cents"] == 500000
