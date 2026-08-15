"""Opportunity lifecycle, fill accounting, and the matching selector."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_opportunity,
    check_in_volunteer,
    confirm_placement,
    create_active_volunteer,
    create_lincoln_campus,
    create_open_opportunity,
    create_opportunity_payload,
    create_orient_module,
    create_volunteer_applied,
    get_opportunity,
    get_placement,
    get_success_data,
    log_and_verify_hours,
    make_volunteer_headers,
    record_training,
    request_placement,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


class TestInitialStates:
    def test_creation_initial_states(self, api):
        """PRD: "A new opportunity starts in `DRAFT` with both
        `committed_count` and `projected_count` at zero."
        PRD: "The new check starts in `PENDING` with null `findings`, null
        `decided_at`, and null `expires_at`."
        PRD: "The new placement starts in `REQUESTED` with null `confirmed_at`
        and null `cancel_reason`, and the opportunity's `projected_count` is
        recomputed."
        PRD: "At creation the entry's `volunteer_id` is copied from the
        placement, its status starts at `PENDING`, and its `points` are
        computed immediately: the `hours` multiplied by the category multiplier
        — one for `STANDARD`, one and a half for `TUTORING`, two for
        `MENTORING` — rounded half up to one decimal place."
        PRD: "A fresh visit starts in `OPEN` status with null `checked_out_at`
        and null `close_reason`."

        Design: Corner/state_machines/creation_initial_states
        """
        module = create_orient_module()
        volunteer = create_volunteer_applied("Initial Ina", "ina@x.com",
                                             "SUPERVISED")

        check = get_success_data(api.create_background_check(
            {"volunteer_id": volunteer["id"], "level": "BASIC",
             "expected_volunteer_version": volunteer["version"]}, DC))
        assert check["status"] == "PENDING"
        assert check["findings"] is None
        assert check["decided_at"] is None
        assert check["expires_at"] is None

        record_training(volunteer["id"], module["id"])
        validate_success(api.adjudicate_background_check(
            check["id"], {"findings": "NONE"}, DC), 200)

        campus = create_lincoln_campus()
        draft = get_success_data(api.create_opportunity(
            create_opportunity_payload(campus["id"], title="Library Help",
                                       capacity=2), CA))
        assert_opportunity(draft)
        assert draft["status"] == "DRAFT"
        assert draft["committed_count"] == 0
        assert draft["projected_count"] == 0
        validate_success(api.publish_opportunity(draft["id"], CA), 200)

        placement = request_placement(draft["id"], volunteer["id"])
        assert placement["status"] == "REQUESTED"
        assert placement["confirmed_at"] is None
        assert placement["cancel_reason"] is None

        confirm_placement(placement["id"])

        entry = get_success_data(api.create_hour_entry(
            {"placement_id": placement["id"], "worked_date": "2026-08-10",
             "hours": 1.5, "activity_category": "TUTORING"},
            make_volunteer_headers(volunteer["id"])))
        assert entry["status"] == "PENDING"
        # 1.5 hours x 1.5 multiplier = 2.25, rounded half up to one decimal.
        assert entry["points"] == pytest.approx(2.3, abs=1e-6)
        assert entry["volunteer_id"] == volunteer["id"]

        set_clock("2026-08-10T13:30:00Z")
        visit = check_in_volunteer(campus["id"], volunteer["id"],
                                   placement_id=placement["id"])
        assert visit["status"] == "OPEN"
        assert visit["badge_code"] == "LNC-0001"
        assert visit["checked_out_at"] is None
        assert visit["close_reason"] is None


class TestOpportunityLifecycle:
    def test_publish_cancelled_opportunity_rejected(self, api):
        """PRD: "Publishing requires the opportunity to still be in `DRAFT`
        (otherwise `ERR_OPPORTUNITY_INVALID_STATE`)"
        PRD: "Cancelling is permitted from either `DRAFT` or `OPEN` and moves
        the opportunity to the terminal `CANCELLED` status"

        Design: Corner/state_machines/publish_cancelled_opportunity_rejected
        """
        campus = create_lincoln_campus()
        opp = get_success_data(api.create_opportunity(
            create_opportunity_payload(campus["id"], title="Doomed"), CA))
        validate_success(api.cancel_opportunity(opp["id"], CA), 200)

        publish = api.publish_opportunity(opp["id"], CA)
        validate_error(publish, ApiErrorId.ERR_OPPORTUNITY_INVALID_STATE)
        assert get_opportunity(opp["id"])["status"] == "CANCELLED"

    def test_opportunity_auto_completed_by_clock_sweep(self, api):
        """PRD: "Once the window closes, the clock sweep of §2.5 moves an
        `OPEN` opportunity whose `ends_at` has been reached to the terminal
        `COMPLETED` status."
        PRD: "Third, every opportunity in `OPEN` whose `ends_at` is at or
        before the new current time transitions to `COMPLETED`."

        Design: Corner/state_machines/opportunity_auto_completed_by_clock_sweep
        """
        campus = create_lincoln_campus()
        opp = create_open_opportunity(
            campus["id"], title="Morning Shift", capacity=2,
            starts_at="2026-08-03T08:00:00Z", ends_at="2026-08-03T12:00:00Z")
        assert opp["status"] == "OPEN"

        sweep = set_clock("2026-08-04T00:00:00Z")
        assert sweep["opportunities_completed_count"] == 1
        assert get_opportunity(opp["id"])["status"] == "COMPLETED"


class TestFillAccounting:
    def _three_active_volunteers(self, module):
        out = []
        for name, email in [("Vol A", "vol.a@x.com"), ("Vol B", "vol.b@x.com"),
                            ("Vol C", "vol.c@x.com")]:
            recruited = create_active_volunteer(name, email, "SUPERVISED",
                                                module=module)
            out.append(recruited["volunteer"])
        return out

    def test_opportunity_fill_committed_and_projected_variants(self, api):
        """PRD: "A successful confirmation stamps `confirmed_at` from the
        logical clock, moves the placement to `CONFIRMED`, recomputes the
        opportunity's `committed_count` and `projected_count`, and increments
        the placement's `version` by one."
        PRD: "The new placement starts in `REQUESTED` with null `confirmed_at`
        and null `cancel_reason`, and the opportunity's `projected_count` is
        recomputed."

        Design: Difficulty/dual_variant_calc/opportunity_fill_committed_vs_projected
        """
        module = create_orient_module()
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], title="Field Day",
                                      capacity=5)
        va, vb, vc = self._three_active_volunteers(module)

        p1 = request_placement(opp["id"], va["id"])
        confirm_placement(p1["id"])
        request_placement(opp["id"], vb["id"])
        request_placement(opp["id"], vc["id"])

        after = get_opportunity(opp["id"])
        assert after["committed_count"] == 1, (
            "Only CONFIRMED placements occupy seats")
        assert after["projected_count"] == 3, (
            "Projected demand counts the REQUESTED placements too")

    def test_projected_count_includes_requested_before_confirmation(self, api):
        """PRD: "A new opportunity starts in `DRAFT` with both
        `committed_count` and `projected_count` at zero."
        PRD: "The new placement starts in `REQUESTED` with null `confirmed_at`
        and null `cancel_reason`, and the opportunity's `projected_count` is
        recomputed."
        PRD: "A successful confirmation stamps `confirmed_at` from the logical
        clock, moves the placement to `CONFIRMED`, recomputes the opportunity's
        `committed_count` and `projected_count`, and increments the placement's
        `version` by one."

        Design: Difficulty/dual_variant_calc/opportunity_fill_committed_vs_projected
        """
        module = create_orient_module()
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], capacity=2)
        recruited = create_active_volunteer("Proj Pam", "proj.pam@x.com",
                                            "SUPERVISED", module=module)

        placement = request_placement(opp["id"], recruited["volunteer"]["id"])
        mid = get_opportunity(opp["id"])
        assert mid["committed_count"] == 0
        assert mid["projected_count"] == 1, (
            "A bare REQUESTED placement already feeds projected demand")

        confirm_placement(placement["id"])
        after = get_opportunity(opp["id"])
        assert after["committed_count"] == 1
        assert after["projected_count"] == 1


class TestCapacityBoundary:
    def _active_pair(self, module, names=(("First Fay", "fay@x.com"),
                                          ("Second Sam", "sam@x.com"))):
        return [create_active_volunteer(n, e, "SUPERVISED", module=module)["volunteer"]
                for n, e in names]

    def test_confirm_at_exactly_full_capacity_rejected(self, api):
        """PRD: "finally capacity: confirmation while `committed_count` has
        already reached `capacity` fails with `ERR_OPPORTUNITY_FULL`."

        Design: Difficulty/boundary_precision_check/capacity_boundary_confirm_at_exactly_full
        """
        module = create_orient_module()
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], title="Single Seat",
                                      capacity=1)
        v1, v2 = self._active_pair(module)
        p1 = request_placement(opp["id"], v1["id"])
        p2 = request_placement(opp["id"], v2["id"])

        first = validate_success(api.confirm_placement(p1["id"], CA), 200)
        assert first["status"] == "CONFIRMED"

        # committed_count has reached capacity (1): the next confirm fails.
        second = api.confirm_placement(p2["id"], CA)
        validate_error(second, ApiErrorId.ERR_OPPORTUNITY_FULL)

        after = get_opportunity(opp["id"])
        assert after["committed_count"] == 1
        assert after["projected_count"] == 2

    def test_capacity_two_third_confirm_rejected(self, api):
        """PRD: "finally capacity: confirmation while `committed_count` has
        already reached `capacity` fails with `ERR_OPPORTUNITY_FULL`."
        PRD: "Placement confirmation and the opportunity matching selector
        apply three gates in this exact order"

        Design: Difficulty/boundary_precision_check/capacity_boundary_confirm_at_exactly_full
        """
        module = create_orient_module()
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], title="Two Seats",
                                      capacity=2)
        v1, v2, v3 = self._active_pair(module, names=(
            ("Cap One", "cap.one@x.com"), ("Cap Two", "cap.two@x.com"),
            ("Cap Three", "cap.three@x.com")))
        p1 = request_placement(opp["id"], v1["id"])
        p2 = request_placement(opp["id"], v2["id"])
        p3 = request_placement(opp["id"], v3["id"])

        validate_success(api.confirm_placement(p1["id"], CA), 200)
        validate_success(api.confirm_placement(p2["id"], CA), 200)

        third = api.confirm_placement(p3["id"], CA)
        validate_error(third, ApiErrorId.ERR_OPPORTUNITY_FULL)
        assert get_placement(p3["id"])["status"] == "REQUESTED"

        after = get_opportunity(opp["id"])
        assert after["committed_count"] == 2
        assert after["projected_count"] == 3


class TestMatchingSelector:
    def test_match_selector_ranking_tiebreak_and_capacity(self, api):
        """PRD: "Eligible volunteers are ranked by `total_verified_hours`
        ascending, ties broken by the volunteer's `created_at` ascending, and
        placements are created directly in `CONFIRMED` — `confirmed_at` stamped
        — in ranking order until the remaining capacity is exhausted or, when
        the caller supplies `max_placements`, that cap is reached."
        PRD: "The response reports `matched_count`, the
        `created_placement_ids`, the resulting `committed_count`, and the
        `remaining_capacity`; the opportunity's fill counts are recomputed
        accordingly."

        Design: Corner/cross_cutting_complexity_layers/match_selector_ranking_tiebreak_and_capacity
        """
        module = create_orient_module()
        campus = create_lincoln_campus()
        helper = create_open_opportunity(
            campus["id"], title="Helper", capacity=5,
            starts_at="2026-08-03T08:00:00Z", ends_at="2026-08-03T12:00:00Z")
        target = create_open_opportunity(campus["id"], title="Target",
                                         capacity=2)

        v1 = create_active_volunteer("First Vic", "v1@x.com", "SUPERVISED",
                                     module=module)["volunteer"]
        v2 = create_active_volunteer("Second Vic", "v2@x.com", "SUPERVISED",
                                     module=module)["volunteer"]
        v3 = create_active_volunteer("Third Vic", "v3@x.com", "SUPERVISED",
                                     module=module)["volunteer"]

        # v3 accumulates 5.0 verified hours on the non-overlapping helper
        # opportunity, ranking behind the two 0-hour volunteers.
        p3h = request_placement(helper["id"], v3["id"])
        confirm_placement(p3h["id"])
        log_and_verify_hours(p3h["id"], v3["id"], worked_date="2026-08-03",
                             hours=5.0)

        result = validate_success(
            api.match_opportunity(target["id"], {}, DC), 200)
        assert result["matched_count"] == 2
        assert result["remaining_capacity"] == 0
        assert result["committed_count"] == 2

        placements, meta = validate_paginated(api.list_placements(
            DC, params={"opportunity_id": target["id"], "status": "CONFIRMED"}))
        assert meta["total_count"] == 2
        placed_ids = {p["volunteer_id"] for p in placements}
        assert placed_ids == {v1["id"], v2["id"]}, (
            "The two zero-hour volunteers rank ahead of the 5.0-hour volunteer")
        for p in placements:
            assert p["confirmed_at"] is not None

        assert get_opportunity(target["id"])["committed_count"] == 2

    def test_match_empty_pool_returns_zero(self, api):
        """PRD: "The opportunity must be `OPEN` (else
        `ERR_OPPORTUNITY_INVALID_STATE`), and an empty pool simply yields a
        `matched_count` of zero."

        Design: Corner/cross_cutting_complexity_layers/match_empty_pool_returns_zero
        """
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], title="Lonely Shift",
                                      capacity=3)

        result = validate_success(api.match_opportunity(opp["id"], {}, DC), 200)
        assert result["matched_count"] == 0
        assert result["remaining_capacity"] == 3

        _, meta = validate_paginated(api.list_placements(
            DC, params={"opportunity_id": opp["id"]}))
        assert meta["total_count"] == 0
