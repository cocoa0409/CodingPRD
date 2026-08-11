"""Modification requests: NCE calendar regeneration, reallocation conservation,
OCC stale-version, and type-specific submit rules (PRD §3.7, §2.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_modification_request,
    create_posted_expense,
    allocate,
    create_submitted_modification,
    make_funder_headers,
    post_activity_in_period,
    set_clock,
    setup_active_grant,
    submit_modification_request,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _grant_version(api, grant_id):
    return validate_success(api.get_grant(grant_id, OFFICER))["version"]


class TestNceApprovalCalendarExtension:
    def test_nce_approval_extends_end_date_and_regenerates_calendar(self, api):
        """PRD §3.7: "For a `NO_COST_EXTENSION`, the grant's `end_date` is set
        to the `requested_end_date` and the reporting calendar is regenerated
        around the new end: an existing `FINAL` report that is still `SCHEDULED`
        is demoted to `INTERIM`, new `Report` rows are appended to tile the
        range from the day after the old `end_date` through the
        `requested_end_date`, with the last appended period marked `FINAL`, and
        future `SCHEDULED` reports are otherwise unchanged."
        PRD §3.7: "An approval applies its side effects atomically and
        increments the grant's `version` by exactly one."

        Design: Difficulty/transitive_cascade/nce_approval_calendar_extension
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        funder_id = ctx["funder"]["id"]
        gv = _grant_version(api, gid)

        mr = create_modification_request(
            gid, request_type="NO_COST_EXTENSION",
            requested_end_date="2027-08-31",
        )
        submit_modification_request(mr["id"])

        resp = api.approve_modification_request(
            mr["id"], {"expected_grant_version": gv}, make_funder_headers(funder_id)
        )
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"

        grant = validate_success(api.get_grant(gid, OFFICER))
        assert grant["end_date"][:10] == "2027-08-31"
        assert grant["version"] == gv + 1

        reports, _ = validate_paginated(api.list_reports(gid, OFFICER))
        assert len(reports) == 5, (
            f"extension to 2027-08-31 must append one more quarter, got "
            f"{len(reports)} reports"
        )
        assert reports[3]["period_type"] == "INTERIM", (
            "the previously-FINAL still-SCHEDULED report must be demoted to "
            "INTERIM"
        )
        assert reports[4]["period_type"] == "FINAL"
        assert reports[4]["period_start"][:10] == "2027-06-01"
        assert reports[4]["period_end"][:10] == "2027-08-31"
        assert reports[4]["due_date"][:10] == "2027-11-29"  # period_end + 90d

    def test_nce_approval_bumps_grant_version_by_exactly_one(self, api):
        """PRD §3.7: "An approval applies its side effects atomically and
        increments the grant's `version` by exactly one."
        PRD §2.8: "Such a request must carry `expected_grant_version` as a
        non-optional input field, holding the `version` of the parent `Grant`
        as the approving client last observed it."

        Design: Difficulty/transitive_cascade/nce_approval_calendar_extension
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        funder_id = ctx["funder"]["id"]
        gv_before = _grant_version(api, gid)
        mr = create_submitted_modification(
            gid, request_type="NO_COST_EXTENSION",
            requested_end_date="2027-08-31",
        )
        validate_success(api.approve_modification_request(
            mr["id"], {"expected_grant_version": gv_before},
            make_funder_headers(funder_id),
        ))
        gv_after = _grant_version(api, gid)
        assert gv_after == gv_before + 1, (
            f"approval must increment grant.version by exactly one: "
            f"{gv_before} -> {gv_after}"
        )


class TestReallocationConservation:
    def test_reallocation_conserves_total_budget_authority(self, api):
        """PRD §3.7: "For a `BUDGET_REALLOCATION`, each affected budget line's
        `adjusted_cents` is increased by its `delta_cents` and the
        `period_budgets_cents` vector of every affected line is recomputed by
        the waterfall proration of §3.2."
        PRD §3.7: "For a `BUDGET_REALLOCATION`, the `delta_cents` values across
        `line_deltas` must sum to exactly zero — money moves between lines, it
        is not created — otherwise `ERR_REALLOCATION_NOT_BALANCED` (HTTP 422)."

        Design: Difficulty/compensating_invariant/reallocation_conserves_total_budget_authority
        """
        ctx = setup_active_grant(lines=[
            {"category": "PERSONNEL", "budgeted_cents": 50_000_000},
            {"category": "TRAVEL", "budgeted_cents": 20_000_000},
            {"category": "SUPPLIES", "budgeted_cents": 30_000_000},
        ])
        gid = ctx["grant"]["id"]
        l1, l2, l3 = ctx["lines"]
        funder_id = ctx["funder"]["id"]
        gv = _grant_version(api, gid)

        mr = create_modification_request(
            gid,
            request_type="BUDGET_REALLOCATION",
            requested_end_date=None,
            line_deltas=[
                {"budget_line_id": l2["id"], "delta_cents": 5_000_000},
                {"budget_line_id": l3["id"], "delta_cents": -5_000_000},
            ],
        )
        submit_modification_request(mr["id"])
        approved = validate_success(api.approve_modification_request(
            mr["id"], {"expected_grant_version": gv},
            make_funder_headers(funder_id),
        ))
        assert approved["status"] == "APPROVED"

        lines, _ = validate_paginated(api.list_budget_lines(gid, OFFICER))
        by_id = {row["id"]: row for row in lines}
        assert by_id[l1["id"]]["adjusted_cents"] == 50_000_000
        assert by_id[l2["id"]]["adjusted_cents"] == 25_000_000
        assert by_id[l3["id"]]["adjusted_cents"] == 25_000_000
        total_after = sum(row["adjusted_cents"] for row in lines)
        assert total_after == 100_000_000, (
            f"total budget authority must be conserved: 50000000 + 25000000 + "
            f"25000000 == 100000000, got {total_after}"
        )
        assert by_id[l3["id"]]["period_budgets_cents"] == [6_250_000] * 4, (
            f"affected line must be re-prorated to [6250000 x 4], got "
            f"{by_id[l3['id']]['period_budgets_cents']}"
        )

    def test_reallocation_recomputed_period_budgets_conserve_line_total(self, api):
        """PRD §3.2: "The remainder — `adjusted_cents` minus the base times n —
        is assigned in full to the final period."
        PRD §3.7: "the `period_budgets_cents` vector of every affected line is
        recomputed by the waterfall proration of §3.2."

        Design: Difficulty/compensating_invariant/reallocation_conserves_total_budget_authority
        """
        ctx = setup_active_grant(lines=[
            {"category": "PERSONNEL", "budgeted_cents": 50_000_000},
            {"category": "TRAVEL", "budgeted_cents": 20_000_000},
        ])
        gid = ctx["grant"]["id"]
        l1, l2 = ctx["lines"]
        funder_id = ctx["funder"]["id"]
        gv = _grant_version(api, gid)

        mr = create_modification_request(
            gid,
            request_type="BUDGET_REALLOCATION",
            requested_end_date=None,
            line_deltas=[
                {"budget_line_id": l1["id"], "delta_cents": -10_000_000},
                {"budget_line_id": l2["id"], "delta_cents": 10_000_000},
            ],
        )
        submit_modification_request(mr["id"])
        validate_success(api.approve_modification_request(
            mr["id"], {"expected_grant_version": gv},
            make_funder_headers(funder_id),
        ))

        lines, _ = validate_paginated(api.list_budget_lines(gid, OFFICER))
        by_id = {row["id"]: row for row in lines}
        for line_id, expected in ((l1["id"], 40_000_000), (l2["id"], 30_000_000)):
            proration = by_id[line_id]["period_budgets_cents"]
            assert sum(proration) == expected, (
                f"re-prorated line must conserve its adjusted total "
                f"{expected}, got {proration}"
            )
            assert by_id[line_id]["adjusted_cents"] == expected


class TestModificationRules:
    def test_modification_withdraw_then_approve_rejected(self, api):
        """PRD §3.7: "Approving or denying a request that is not in `SUBMITTED`
        is rejected with `ERR_MODIFICATION_NOT_PENDING` (HTTP 409); withdrawal
        is possible from `DRAFT` or `SUBMITTED` and is rejected with the same
        error once the request is terminal."
        PRD §3.7: "`APPROVED`, `DENIED`, and `WITHDRAWN` are all terminal."

        Design: Corner/state_machines/modification_withdraw_then_approve_rejected
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        funder_id = ctx["funder"]["id"]
        gv = _grant_version(api, gid)
        mr = create_submitted_modification(
            gid, request_type="NO_COST_EXTENSION",
            requested_end_date="2027-08-31",
        )
        validate_success(api.withdraw_modification_request(mr["id"], OFFICER))

        resp = api.approve_modification_request(
            mr["id"], {"expected_grant_version": gv},
            make_funder_headers(funder_id),
        )
        validate_error(resp, ApiErrorId.ERR_MODIFICATION_NOT_PENDING)

    def test_modification_approve_stale_version_rejected(self, api):
        """PRD §2.8: "If the value presented does not equal the grant's current
        `version` — because, for instance, another modification approval has
        already mutated the grant's `end_date` or a budget line's
        `adjusted_cents` and advanced the version — the approval is rejected
        with `ERR_STALE_VERSION` (HTTP 412), preventing the approver from
        deciding against an award baseline it has not observed."

        Design: Corner/validations/modification_approve_stale_version_rejected
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        funder_id = ctx["funder"]["id"]
        gv = _grant_version(api, gid)

        mr1 = create_submitted_modification(
            gid, request_type="NO_COST_EXTENSION", requested_end_date="2027-08-31",
            justification="j1",
        )
        mr2 = create_submitted_modification(
            gid, request_type="NO_COST_EXTENSION", requested_end_date="2027-11-30",
            justification="j2",
        )

        first = validate_success(api.approve_modification_request(
            mr1["id"], {"expected_grant_version": gv},
            make_funder_headers(funder_id),
        ))
        assert first["status"] == "APPROVED"

        resp = api.approve_modification_request(
            mr2["id"], {"expected_grant_version": gv},
            make_funder_headers(funder_id),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_reallocation_below_expended_rejected(self, api):
        """PRD §3.7: "for every delta, the target line's `adjusted_cents` plus
        the delta must remain at least the line's `expended_cents`, so authority
        can never be pulled below money already spent, otherwise
        `ERR_REALLOCATION_BELOW_EXPENDED` (HTTP 422)."

        Design: Corner/validations/reallocation_below_expended_rejected
        """
        ctx = setup_active_grant(lines=[
            {"category": "PERSONNEL", "budgeted_cents": 50_000_000},
            {"category": "TRAVEL", "budgeted_cents": 20_000_000},
        ])
        gid = ctx["grant"]["id"]
        l1, l2 = ctx["lines"]
        fund = ctx["fund"]
        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 13_000_000, "2026-06-20")

        mr = create_modification_request(
            gid,
            request_type="BUDGET_REALLOCATION",
            requested_end_date=None,
            line_deltas=[
                {"budget_line_id": l1["id"], "delta_cents": -40_000_000},
                {"budget_line_id": l2["id"], "delta_cents": 40_000_000},
            ],
        )
        resp = api.submit_modification_request(mr["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_REALLOCATION_BELOW_EXPENDED)

    def test_extension_not_forward_rejected(self, api):
        """PRD §3.7: "For a `NO_COST_EXTENSION`, the `requested_end_date` must
        be strictly after the grant's current `end_date`; a request that does
        not move the end date forward is rejected with
        `ERR_EXTENSION_NOT_FORWARD` (HTTP 422)."

        Design: Corner/validations/extension_not_forward_rejected
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        mr = create_modification_request(
            gid, request_type="NO_COST_EXTENSION",
            requested_end_date="2027-05-31",  # equal to current end_date
        )
        resp = api.submit_modification_request(mr["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_NOT_FORWARD)
