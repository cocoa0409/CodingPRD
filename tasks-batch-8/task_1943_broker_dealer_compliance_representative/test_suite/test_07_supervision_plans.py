"""Heightened supervision plans: half-open window overlap, temporal rules,
validation priority, OCC on the representative version, and activation
gates (PRD §3.7, §2.9, §2.10).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_plan_for_rep,
    create_plan_payload,
    get_rep,
    make_active_plan,
    make_branch_with_rep,
    make_sd_rep,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PRINCIPAL_A = TEST_USERS["principal_a_headers"]
ANY = TEST_USERS["any_headers"]


# ─── window overlap ───────────────────────────────────

class TestPlanWindowOverlap:
    def test_true_overlap_rejected(self, api, any_headers):
        """PRD §3.7: "Two plans of the same representative in `DRAFT` or
        `ACTIVE` must not overlap; because the window is half-open, one
        plan's `end_date` may coincide with another's `start_date` without
        conflict, but any true overlap is rejected with
        `ERR_PLAN_WINDOW_OVERLAP`." [2026-06-15, 2026-12-31) intersects the
        existing [2026-06-01, 2026-12-31).

        Design: Difficulty/resource_temporal_overlap/plan_window_overlap
        """
        _branch, rep = make_branch_with_rep(region="E", crd_number="600001")
        set_clock("2026-01-01T09:00:00Z")
        first = validate_success(
            create_plan_for_rep(rep["id"], start_date="2026-06-01",
                                end_date="2026-12-31", conditions=("A",)),
            201,
        )
        assert first["status"] == "DRAFT"

        res = create_plan_for_rep(rep["id"], start_date="2026-06-15",
                                  end_date="2026-12-31", conditions=("B",))
        validate_error(res, ApiErrorId.ERR_PLAN_WINDOW_OVERLAP)

    def test_rejected_overlap_persists_no_plan(self, api, any_headers):
        """PRD §3.7: "any true overlap is rejected with
        `ERR_PLAN_WINDOW_OVERLAP`" — a rejected create persists nothing, so
        the rep still has exactly the one original plan.

        Design: Difficulty/resource_temporal_overlap/plan_window_overlap
        """
        _branch, rep = make_branch_with_rep(region="E", crd_number="600001")
        set_clock("2026-01-01T09:00:00Z")
        validate_success(
            create_plan_for_rep(rep["id"], start_date="2026-06-01",
                                end_date="2026-12-31", conditions=("A",)),
            201,
        )
        res = create_plan_for_rep(rep["id"], start_date="2026-06-15",
                                  end_date="2026-12-31", conditions=("B",))
        validate_error(res, ApiErrorId.ERR_PLAN_WINDOW_OVERLAP)

        data, _meta = validate_paginated(
            api.list_supervision_plans(ANY, params={"rep_id": rep["id"]})
        )
        assert len(data) == 1
        assert data[0]["start_date"] == "2026-06-01"


# ─── validation priority: temporal before constraint ──

class TestTemporalBeforeConstraint:
    def _setup(self):
        """Rep with an existing DRAFT plan [2026-01-01, 2026-06-30); clock
        then advanced to 2026-02-01 so a 2026-01-15 start is in the past."""
        _branch, rep = make_branch_with_rep(region="S", crd_number="300002")
        set_clock("2026-01-01T09:00:00Z")
        first = validate_success(
            create_plan_for_rep(rep["id"], start_date="2026-01-01",
                                end_date="2026-06-30", conditions=("WEEKLY_REVIEW",)),
            201,
        )
        set_clock("2026-02-01T09:00:00Z")
        return rep, first

    def test_past_start_and_overlapping_window_reports_temporal_error(
        self, api, any_headers
    ):
        """PRD §2.10: "the error that surfaces is determined by a fixed
        evaluation order" — "Date-versus-clock rules surface as 422 errors:
        `ERR_PLAN_START_IN_PAST`, `ERR_MEETING_DATE_NOT_REACHED`,
        `ERR_ATTESTATION_DEADLINE_PASSED`" (temporal) come before
        "Uniqueness, overlap, gap, and threshold rules" (business
        constraints). A plan starting 2026-01-15 (past) that also overlaps
        [2026-01-01, 2026-06-30) reports the temporal error.

        Design: Difficulty/priority_pair_validation_conflict/priority_temporal_before_constraint_plan
        """
        rep, _first = self._setup()
        res = create_plan_for_rep(rep["id"], start_date="2026-01-15",
                                  end_date="2026-07-15",
                                  conditions=("DAILY_REVIEW",))
        validate_error(res, ApiErrorId.ERR_PLAN_START_IN_PAST)

    def test_rejected_temporal_create_does_not_advance_rep_version(
        self, api, any_headers
    ):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource" — a create
        rejected with `ERR_PLAN_START_IN_PAST` mutates nothing, so the
        representative's version is unchanged.

        Design: Difficulty/priority_pair_validation_conflict/priority_temporal_before_constraint_plan
        """
        rep, _first = self._setup()
        before = get_rep(rep["id"])["version"]
        res = create_plan_for_rep(rep["id"], start_date="2026-01-15",
                                  end_date="2026-07-15",
                                  conditions=("DAILY_REVIEW",))
        validate_error(res, ApiErrorId.ERR_PLAN_START_IN_PAST)
        assert get_rep(rep["id"])["version"] == before


# ─── OCC on representative version ────────────────────

class TestPlanCreateOcc:
    def test_stale_representative_version_rejected(self, api, any_headers):
        """PRD §2.9: "Creating a heightened supervision plan requires the
        request to carry `expected_representative_version`, holding the
        `version` of the target RegisteredRepresentative as the client last
        observed it. If the representative's current `version` no longer
        matches — because, for instance, an activity decision or a
        disqualification cascade has advanced it — the create is rejected
        with `ERR_STALE_REPRESENTATIVE_VERSION` (HTTP 412)." The first plan
        creation advanced the rep's version ("Creation places the plan in
        `DRAFT` and increments the representative's `version` by one"), so
        the second create with the pre-creation version is stale.

        Design: Difficulty/cross_cutting/occ_plan_create_stale_representative
        """
        _branch, rep = make_branch_with_rep(region="E", crd_number="800001")
        stale_v = rep["version"]
        set_clock("2026-09-01T09:00:00Z")
        validate_success(
            api.create_supervision_plan(
                create_plan_payload(rep["id"], stale_v,
                                    start_date="2026-10-01",
                                    end_date="2027-03-31", conditions=["A"]),
                PRINCIPAL_A,
            ),
            201,
        )
        res = api.create_supervision_plan(
            create_plan_payload(rep["id"], stale_v,
                                start_date="2026-11-01",
                                end_date="2027-04-30", conditions=["B"]),
            PRINCIPAL_A,
        )
        validate_error(res, ApiErrorId.ERR_STALE_REPRESENTATIVE_VERSION)

    def test_fresh_version_after_stale_rejection_succeeds(self, api,
                                                          any_headers):
        """PRD §2.9: "The OCC check runs after authentication, authorization,
        and existence checks, but before every business rule on the guarded
        endpoint." Re-issuing the create with the rep's current version (and
        a disjoint, future window) passes — proving the stale version was the
        only blocker.

        Design: Difficulty/cross_cutting/occ_plan_create_stale_representative
        """
        _branch, rep = make_branch_with_rep(region="E", crd_number="800001")
        stale_v = rep["version"]
        set_clock("2026-09-01T09:00:00Z")
        validate_success(
            api.create_supervision_plan(
                create_plan_payload(rep["id"], stale_v,
                                    start_date="2026-10-01",
                                    end_date="2027-03-31", conditions=["A"]),
                PRINCIPAL_A,
            ),
            201,
        )
        res = api.create_supervision_plan(
            create_plan_payload(rep["id"], stale_v,
                                start_date="2026-11-01",
                                end_date="2027-04-30", conditions=["B"]),
            PRINCIPAL_A,
        )
        validate_error(res, ApiErrorId.ERR_STALE_REPRESENTATIVE_VERSION)

        fresh = validate_success(
            create_plan_for_rep(rep["id"], start_date="2027-04-01",
                                end_date="2027-09-30", conditions=("B",)),
            201,
        )
        assert fresh["status"] == "DRAFT"


# ─── temporal and overlap single-rule checks ──────────

def test_plan_start_in_past_rejected(api, any_headers):
    """PRD §3.7: "The `start_date` must not lie in the past — a start date
    earlier than the current clock date is rejected with
    `ERR_PLAN_START_IN_PAST` (HTTP 422)." At the default clock 2026-08-01 a
    2026-07-01 start is in the past (no overlap present).

    Design: Corner/validations/plan_start_in_past_rejected
    """
    _branch, rep = make_branch_with_rep(region="E", crd_number="930001")
    res = create_plan_for_rep(rep["id"], start_date="2026-07-01",
                              end_date="2026-12-31", conditions=("X",))
    validate_error(res, ApiErrorId.ERR_PLAN_START_IN_PAST)


def test_adjacent_half_open_windows_allowed(api, any_headers):
    """PRD §3.7: "The plan window is half-open: it covers dates from
    `start_date` inclusive up to but not including `end_date`." and "one
    plan's `end_date` may coincide with another's `start_date` without
    conflict" — [2026-01-01, 2026-06-30) then [2026-06-30, 2026-12-31) is
    accepted.

    Design: Corner/validations/plan_overlap_adjacent_half_open_allowed
    """
    _branch, rep = make_branch_with_rep(region="W", crd_number="930002")
    set_clock("2026-01-01T00:00:00Z")
    validate_success(
        create_plan_for_rep(rep["id"], start_date="2026-01-01",
                            end_date="2026-06-30", conditions=("A",)),
        201,
    )
    second = validate_success(
        create_plan_for_rep(rep["id"], start_date="2026-06-30",
                            end_date="2026-12-31", conditions=("B",)),
        201,
    )
    assert second["status"] == "DRAFT"


# ─── activation gates ─────────────────────────────────

def test_plan_activate_requires_sd_rep(api, any_headers):
    """PRD §3.7: "the representative must carry the
    statutory-disqualification flag, else
    `ERR_REP_NOT_STATUTORILY_DISQUALIFIED`".

    Design: Corner/state_machines/plan_activate_requires_sd_rep
    """
    _branch, rep = make_branch_with_rep(region="N", crd_number="910008")
    assert rep["is_statutorily_disqualified"] is False
    plan = validate_success(
        create_plan_for_rep(rep["id"], start_date="2026-09-01",
                            end_date="2027-08-31"),
        201,
    )
    res = api.activate_supervision_plan(plan["id"], PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_REP_NOT_STATUTORILY_DISQUALIFIED)


def test_plan_terminate_active_plan_manual(api, any_headers):
    """PRD §3.7: "A principal may terminate an `ACTIVE` plan manually, moving
    it to `TERMINATED` with `terminated_reason` set to `MANUAL`."

    Design: Corner/state_machines/plan_terminate_active_plan
    """
    _branch, rep, _event = make_sd_rep(crd_number="910009")
    plan = make_active_plan(rep["id"], start_date="2026-08-02",
                            end_date="2027-08-01", conditions=("DAILY_REVIEW",))
    assert plan["status"] == "ACTIVE"

    terminated = validate_success(
        api.terminate_supervision_plan(plan["id"], PRINCIPAL_A), 200
    )
    assert terminated["status"] == "TERMINATED"
    assert terminated.get("terminated_reason") == "MANUAL"


def test_terminate_draft_plan_rejected(api, any_headers):
    """PRD §3.7: "the plan must be in `DRAFT` — activating or terminating
    from a non-matching state is rejected with `ERR_PLAN_NOT_ACTIVE`" — a
    DRAFT plan cannot be terminated.

    Design: Corner/state_machines/terminate_draft_plan_rejected
    """
    _branch, rep = make_branch_with_rep(region="E", crd_number="910010")
    plan = validate_success(
        create_plan_for_rep(rep["id"], start_date="2026-09-01",
                            end_date="2027-08-31", conditions=("X",)),
        201,
    )
    assert plan["status"] == "DRAFT"
    res = api.terminate_supervision_plan(plan["id"], PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_ACTIVE)


def test_second_activation_rejected_while_plan_active(api, any_headers):
    """PRD §3.7: "no other plan of the same representative may already be
    `ACTIVE`, else `ERR_PLAN_ALREADY_ACTIVE`". Disjoint windows may coexist
    as drafts, but a second activation is rejected.

    Design: Corner/state_machines/plan_already_active_conflict
    """
    _branch, rep, _event = make_sd_rep(crd_number="910011",
                                       event_type="REGULATORY_BAR")
    first = make_active_plan(rep["id"], start_date="2026-08-03",
                             end_date="2026-12-31", conditions=("A",))
    assert first["status"] == "ACTIVE"
    second = validate_success(
        create_plan_for_rep(rep["id"], start_date="2027-01-01",
                            end_date="2027-06-30", conditions=("B",)),
        201,
    )
    res = api.activate_supervision_plan(second["id"], PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_PLAN_ALREADY_ACTIVE)
