"""Work order pipeline, habitability scoring variants, and hold cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_building,
    create_site,
    create_unit,
    create_work_order,
    get_summary,
    get_unit,
    make_maintenance_lead_headers,
    make_site_manager_headers,
    setup_certified_site,
    validate_error,
    validate_paginated,
    validate_success,
    verify_work_order,
    walk_work_order_to_completed,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
MANAGER = TEST_USERS["site_manager_headers"]
LEAD = TEST_USERS["maintenance_lead_headers"]


def _seed_open_set(api, unit_id):
    """2 MAJOR + 6 MINOR work orders: cumulative 38, below the hold
    threshold. Returns the list of created work orders."""
    wos = []
    wos.append(create_work_order(unit_id, "PLUMBING", "MAJOR", "w1"))
    wos.append(create_work_order(unit_id, "ELECTRICAL", "MAJOR", "w2"))
    for i in range(3, 9):
        wos.append(create_work_order(unit_id, "APPLIANCE", "MINOR", f"w{i}"))
    return wos


class TestHabitabilityVariantDivergence:
    """Difficulty instance: the same open set (2 MAJOR + 7 MINOR) scores
    cumulative 41 (hold) vs worst_case 17.75 (preview below threshold)."""

    def _setup_at_41(self, api):
        ctx = setup_certified_site(site_name="Site H", state_code="WA")
        unit_id = ctx["unit"]["id"]
        wos = _seed_open_set(api, unit_id)
        unit = get_unit(unit_id)
        assert unit["habitability_score_cumulative"] == 38, (
            f"Setup failed: expected cumulative 38, got "
            f"{unit['habitability_score_cumulative']}")
        assert unit["status"] == "CERTIFIED", "Setup failed: no hold yet at 38"
        # The ninth order (a seventh MINOR) tips the cumulative score over.
        wos.append(create_work_order(unit_id, "OTHER", "MINOR",
                                     "w9 tips the cumulative score"))
        return ctx, unit_id, wos

    def test_cumulative_variant_drives_enforcement(self, api,
                                                   operator_admin_headers):
        """PRD §3.6: "Enforcement follows the cumulative variant exclusively:
        from `REGISTERED`, from `CERTIFIED`, or from `OCCUPIED`, a unit moves
        to `HABITABILITY_HOLD` whenever the cumulative score reaches 40 or any
        `CRITICAL` order is open, with the site posture recomputed on each
        transition."
        PRD §3.6: "weighted 25 for `CRITICAL`, 10 for `MAJOR`, and 3 for
        `MINOR`"

        Design: Difficulty/dual_variant_calc/habitability_cumulative_vs_worst_case_divergence
        """
        _, unit_id, _ = self._setup_at_41(api)
        unit = get_unit(unit_id)
        assert unit["habitability_score_cumulative"] == 41, "2*10 + 7*3"
        assert unit["status"] == "HABITABILITY_HOLD", (
            "Enforcement follows the cumulative variant (41 >= 40)")

    def test_worst_case_variant_is_preview_only(self, api,
                                                operator_admin_headers):
        """PRD §3.6: "The triage preview, `habitability_score_worst_case`, is
        the largest single weight in the open set plus one quarter of the sum
        of the remaining weights — heavily discounting long tails of minor
        items — is zero when the open set is empty, keeps two decimal places,
        and surfaces on reads only."
        PRD §2.9: "Failing that, a site is `WATCH` when exactly one of its
        units stands in `HABITABILITY_HOLD`"

        Design: Difficulty/dual_variant_calc/habitability_cumulative_vs_worst_case_divergence
        """
        ctx, unit_id, _ = self._setup_at_41(api)
        unit = get_unit(unit_id)
        # max weight 10 + 0.25 * (41 - 10) = 17.75 — below the threshold, yet
        # the unit is on hold: the preview never drives enforcement.
        assert unit["habitability_score_worst_case"] == pytest.approx(17.75)
        assert unit["status"] == "HABITABILITY_HOLD"

        summary = get_summary(ctx["site"]["id"])
        assert summary["compliance_posture"] == "WATCH", (
            "Exactly one unit on hold")


class TestCriticalHoldClause:
    def test_critical_work_order_holds_unit_below_score_threshold(
            self, api, site_manager_headers, operator_admin_headers):
        """PRD §3.6: "creating a `CRITICAL` work order immediately moves its
        unit to `HABITABILITY_HOLD` (unless the unit is `CONDEMNED` or
        `DECOMMISSIONED`), recomputes the habitability scores, and recomputes
        the site posture."
        PRD §2.9: "Failing that, a site is `WATCH` when exactly one of its
        units stands in `HABITABILITY_HOLD`, when any non-terminal work order
        of `CRITICAL` severity exists on the site"

        Design: Corner/calculations/critical_work_order_holds_unit_below_score_threshold
        """
        ctx = setup_certified_site(site_name="S")
        resp = api.create_work_order(
            {"unit_id": ctx["unit"]["id"], "category": "STRUCTURAL",
             "severity": "CRITICAL", "description": "stair collapse risk"},
            site_manager_headers)
        assert resp.status_code == 201, "Setup failed"

        unit = get_unit(ctx["unit"]["id"])
        assert unit["habitability_score_cumulative"] == 25, (
            "A single CRITICAL is below the 40 threshold")
        assert unit["status"] == "HABITABILITY_HOLD", (
            "The any-open-CRITICAL clause fires independently of the score")

        summary = get_summary(ctx["site"]["id"])
        assert summary["compliance_posture"] == "WATCH"
        assert summary["open_critical_work_orders"] == 1


class TestWorkOrderPipeline:
    def test_work_order_skip_pipeline_invalid(self, api,
                                              maintenance_lead_headers):
        """PRD §3.6: "A `MaintenanceLead` moves an order `REPORTED → TRIAGED`,
        then `TRIAGED → ASSIGNED` by naming an `assignee_name` — omitting it
        is `ERR_INVALID_REQUEST` — and `ASSIGNED → IN_PROGRESS` as work
        begins."
        PRD §2.8: "Seventh, state-machine validity: the requested target
        status must be a declared transition from the entity's current
        status"

        Design: Corner/state_machines/work_order_skip_pipeline_invalid
        """
        site = create_site()
        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        wo = create_work_order(unit["id"], "OTHER", "MINOR", "d")

        resp = api.update_work_order(wo["id"], {"status": "COMPLETED"},
                                     maintenance_lead_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = validate_success(api.get_work_order(wo["id"],
                                                      maintenance_lead_headers))
        assert current["status"] == "REPORTED"

    def test_filtered_list_isolation_work_orders_by_unit(
            self, api, operator_admin_headers):
        """PRD §4: "The supported list filters are `site_id`, `building_id`,
        `unit_id`, `household_id`, `tenancy_id`, `complaint_id`, `status`,
        `eligibility_status`, `compliance_posture`, `entry_type`,
        `source_work_order_id`, `severity`, `referral_type`, and
        `superseded_by_id`, alongside the pagination parameters `limit` and
        `offset`."

        Design: Corner/endpoints/filtered_list_isolation_work_orders_by_unit
        """
        site = create_site()
        building = create_building(site["id"])
        u1 = create_unit(site["id"], building["id"], unit_code="U1")
        u2 = create_unit(site["id"], building["id"], unit_code="U2")
        w1 = create_work_order(u1["id"], "PLUMBING", "MINOR", "on u1")
        create_work_order(u2["id"], "ELECTRICAL", "MAJOR", "on u2")

        data, _ = validate_paginated(api.list_work_orders(
            operator_admin_headers, params={"unit_id": u1["id"]}))
        assert len(data) == 1
        assert data[0]["id"] == w1["id"]
        assert all(row["unit_id"] == u1["id"] for row in data), (
            "The filtered list must not leak another unit's work orders")


class TestWorkOrderReopenCycle:
    """Difficulty instance: the COMPLETED -> REOPENED -> ASSIGNED rework loop
    is legal and terminates in CLOSED."""

    def _setup_completed(self, api):
        ctx = setup_certified_site(site_name="Site W")
        wo = create_work_order(ctx["unit"]["id"], "PLUMBING", "MINOR",
                               "leaky faucet")
        assert wo["status"] == "REPORTED"
        return ctx, wo

    def test_reopen_cycle_traversal(self, api):
        """PRD §3.6: "When verification instead reveals deficient work, a
        `SiteManager` returns the order `COMPLETED → REOPENED`, which counts
        the order as open again and recomputes both the scores and the
        posture; a `MaintenanceLead` then re-assigns it, `REOPENED →
        ASSIGNED`, again requiring `assignee_name`."
        PRD §3.6: "A verified order is closed by a `SiteManager` — `VERIFIED →
        CLOSED` — with a posture recompute. ... `CLOSED` and `CANCELLED` are
        terminal."

        Design: Difficulty/non_linear_state_machine/work_order_reopen_cycle
        """
        _, wo = self._setup_completed(api)
        walk_work_order_to_completed(wo["id"], completed_by="ml-1")

        reopened = validate_success(api.update_work_order(
            wo["id"], {"status": "REOPENED"}, make_site_manager_headers("sm-1")))
        assert reopened["status"] == "REOPENED", (
            "The cycle COMPLETED -> REOPENED -> ASSIGNED is legal")

        reassigned = validate_success(api.update_work_order(
            wo["id"], {"status": "ASSIGNED", "assignee_name": "tech-2"},
            LEAD))
        assert reassigned["status"] == "ASSIGNED"
        validate_success(api.update_work_order(
            wo["id"], {"status": "IN_PROGRESS"}, LEAD))
        validate_success(api.update_work_order(
            wo["id"], {"status": "COMPLETED"},
            make_maintenance_lead_headers("ml-1")))
        verified = verify_work_order(wo["id"], verified_by="sm-1")
        assert verified["status"] == "VERIFIED"
        closed = validate_success(api.update_work_order(
            wo["id"], {"status": "CLOSED"}, MANAGER))
        assert closed["status"] == "CLOSED", (
            "The second pass through ASSIGNED/IN_PROGRESS/COMPLETED/VERIFIED "
            "ends at CLOSED")

    def test_reopen_cycle_records_distinct_actors(self, api):
        """PRD §3.6: "Completion, `IN_PROGRESS → COMPLETED`, records the
        finisher as `completed_by`."
        PRD §3.6: "a `SiteManager` moves `COMPLETED → VERIFIED` only when the
        caller's `X-User-ID` differs from `completed_by`
        (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`), records `verified_by`"

        Design: Difficulty/non_linear_state_machine/work_order_reopen_cycle
        """
        _, wo = self._setup_completed(api)
        walk_work_order_to_completed(wo["id"], completed_by="ml-1")
        api.update_work_order(wo["id"], {"status": "REOPENED"},
                              make_site_manager_headers("sm-1"))
        api.update_work_order(wo["id"],
                              {"status": "ASSIGNED", "assignee_name": "t2"},
                              LEAD)
        api.update_work_order(wo["id"], {"status": "IN_PROGRESS"}, LEAD)
        api.update_work_order(wo["id"], {"status": "COMPLETED"},
                              make_maintenance_lead_headers("ml-1"))
        verify_work_order(wo["id"], verified_by="sm-1")

        current = validate_success(api.get_work_order(wo["id"], MANAGER))
        assert current["completed_by"] == "ml-1"
        assert current["verified_by"] == "sm-1", (
            "Segregation satisfied: verifier differs from completer")


class TestVerifyHoldClearCascade:
    """Difficulty instance: VERIFIED recomputes the score, clears the hold,
    and recomputes the posture."""

    def _setup_on_hold(self, api):
        ctx = setup_certified_site(site_name="Site V", state_code="WA")
        unit_id = ctx["unit"]["id"]
        _seed_open_set(api, unit_id)
        target = create_work_order(unit_id, "OTHER", "MINOR", "n7 target")
        assert get_unit(unit_id)["status"] == "HABITABILITY_HOLD", (
            "Setup failed: cumulative 41 should hold the unit")
        walk_work_order_to_completed(target["id"], completed_by="ml-1")
        return ctx, unit_id, target

    def test_verify_drops_score_and_clears_hold(self, api,
                                                site_manager_headers):
        """PRD §3.6: "The hold clears on matching terms: whenever a work order
        is verified, closed, or cancelled and the recomputed cumulative score
        is below 40 with zero non-terminal `CRITICAL` orders, the unit leaves
        `HABITABILITY_HOLD` — to `CERTIFIED` when it holds a valid `PASSED`
        certification"

        Design: Difficulty/transitive_cascade/work_order_verify_hold_clear_cascade
        """
        _, unit_id, target = self._setup_on_hold(api)
        verified = verify_work_order(target["id"], verified_by="sm-1")
        assert verified["status"] == "VERIFIED"

        unit = get_unit(unit_id)
        assert unit["habitability_score_cumulative"] == 38, (
            "41 - 3: the VERIFIED minor leaves the open set")
        assert unit["status"] == "CERTIFIED", (
            "Score 38 < 40 with zero open CRITICAL clears the hold")

    def test_verify_cascade_restores_normal_posture(self, api):
        """PRD §2.9: "Otherwise the posture is `NORMAL`."
        PRD §3.6: "with the site posture recomputed on each transition."

        Design: Difficulty/transitive_cascade/work_order_verify_hold_clear_cascade
        """
        ctx, unit_id, target = self._setup_on_hold(api)
        verify_work_order(target["id"], verified_by="sm-1")

        summary = get_summary(ctx["site"]["id"])
        assert summary["compliance_posture"] == "NORMAL", (
            "Last hold cleared; no open CRITICAL work orders; no breached "
            "complaints")
