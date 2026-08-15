"""Bed bug exposure cascade, case state machine, clearance evaluation, and the
property posture boundary."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    MANAGER,
    complete_follow_up,
    complete_positive_inspection,
    complete_treatment,
    create_technician,
    create_unit,
    schedule_inspection,
    set_clock,
    setup_case_monitoring,
    setup_community,
    setup_prep_verified_treatment,
)


def _find_auto_initial(api, unit_id, case_id):
    inspections = get_success_data(api.list_unit_inspections(unit_id, MANAGER))
    matches = [i for i in inspections if i.get("bed_bug_case_id") == case_id]
    return inspections, matches


def _parse_ts(ts):
    """Parse an ISO 8601 UTC timestamp into a datetime for format-agnostic
    instant comparison (PRD pins instants, not per-field string formats)."""
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestExposureCascade:
    def test_positive_completion_creates_case_and_flags_unit(self, api):
        """PRD §3.3: "Link one: if the unit has no bed bug case in `OPEN`,
        `TREATING`, `MONITORING`, or `REOPENED`, the server creates a new case
        in `OPEN`; if the unit's existing case sits in `MONITORING`, that case
        reopens to `REOPENED`, resetting its `consecutive_negative_count` to
        zero; the unit's `pest_flag` becomes `INFESTED`."

        Design: Difficulty/transitive_cascade/cascade_positive_inspection_to_property_posture
        """
        ctx = setup_community(num_units=3, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]},
                              unit_overrides={"bedrooms": 2})
        u101, u102, u201 = ctx["units"]
        tech = ctx["technician"]
        # default numbering 101/102/103 on floors 1; make 201 floor 2 stack 1
        # via explicit rebuild: use fresh property to control the grid.
        completed, case = complete_positive_inspection(u101["id"], tech)
        assert case["status"] == "OPEN"
        unit = validate_success(api.get_unit(u101["id"], MANAGER))
        assert unit["pest_flag"] == "INFESTED"

    def test_cascade_creates_initial_inspections_and_updates_posture(self, api):
        """PRD §3.3: "For each exposed unit the server creates an inspection of
        `kind` `INITIAL`, `pest_type` `BED_BUGS`, status `SCHEDULED`,
        `bed_bug_case_id` pointing at the new case, `scheduled_for` set 24
        hours after the current logical time, and assigned to the technician
        who completed the originating inspection."
        PRD §3.3: "Link three: each such auto-created initial inspection moves
        its target unit's `pest_flag` from `CLEAR` to `MONITORING`."
        PRD §2.4: "At startup, before any clock call, the logical clock reads
        exactly 2026-08-01T00:00:00Z."
        PRD §3.1: "`posture`, which is `RESTRICTED` when that count reaches at
        least 3, `ELEVATED` when it is at least 1, and `STANDARD` otherwise."

        Design: Difficulty/transitive_cascade/cascade_positive_inspection_to_property_posture
        """
        ctx = setup_community(num_units=3, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]},
                              unit_overrides={"bedrooms": 2})
        # Rebuild the grid deterministically: units created by setup_community
        # are numbered 101/102/103 on floors 1 with stacks 1/2/3; create a
        # dedicated property instead for exact 101/102/201 geometry.
        from test_helpers.fixtures import create_active_contract, create_property
        prop = create_property(name="Ash Court", address="7 Ash St")
        create_active_contract(prop["id"], scope_pest_types=["BED_BUGS"])
        u101 = create_unit(prop["id"], unit_number="101", floor=1, stack_index=1, bedrooms=2)
        u102 = create_unit(prop["id"], unit_number="102", floor=1, stack_index=2, bedrooms=2)
        u201 = create_unit(prop["id"], unit_number="201", floor=2, stack_index=1, bedrooms=2)
        tech = create_technician()

        completed, case = complete_positive_inspection(u101["id"], tech)

        all_102, matches_102 = _find_auto_initial(api, u102["id"], case["id"])
        assert len(all_102) == 1 and len(matches_102) == 1
        i102 = matches_102[0]
        assert i102["kind"] == "INITIAL"
        assert i102["pest_type"] == "BED_BUGS"
        assert i102["status"] == "SCHEDULED"
        # PRD pins the instant ("scheduled_for set 24 hours after the current
        # logical time", default clock 2026-08-01T00:00:00Z) but not this
        # field's serialization format, so compare parsed instants.
        assert _parse_ts(i102["scheduled_for"]) == _parse_ts("2026-08-02T00:00:00Z"), (
            "default clock 2026-08-01T00:00:00Z + 24h"
        )
        assert i102["technician_id"] == tech["id"]

        all_201, matches_201 = _find_auto_initial(api, u201["id"], case["id"])
        assert len(all_201) == 1 and len(matches_201) == 1
        assert matches_201[0]["kind"] == "INITIAL"

        u102_after = validate_success(api.get_unit(u102["id"], MANAGER))
        u201_after = validate_success(api.get_unit(u201["id"], MANAGER))
        u101_after = validate_success(api.get_unit(u101["id"], MANAGER))
        assert u102_after["pest_flag"] == "MONITORING"
        assert u201_after["pest_flag"] == "MONITORING"
        assert u101_after["pest_flag"] == "INFESTED"

        summary = validate_success(api.get_property_summary(prop["id"], MANAGER))
        assert summary["open_bed_bug_case_count"] == 1
        assert summary["posture"] == "ELEVATED"


class TestClearanceGate:
    def test_evaluate_clearance_from_open_returns_case_not_monitoring(self, api):
        """PRD §3.6: "A `PropertyManager` evaluates clearance on a case in
        `MONITORING` — any other status returns `ERR_CASE_NOT_MONITORING`
        (HTTP 409)."

        Design: Corner/state_machines/evaluate_clearance_from_open_returns_case_not_monitoring
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        _, case = complete_positive_inspection(ctx["unit"]["id"], ctx["technician"])
        resp = api.evaluate_clearance(case["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_MONITORING)


class TestCaseReopenCycle:
    def test_reopen_resets_counter(self, api):
        """PRD §3.6: "A case in `MONITORING` that suffers a positive follow-up
        reopens to `REOPENED`, resets its negative counter, recomputes the
        property indicators, and may return to `TREATING` when a fresh linked
        treatment is created."
        PRD §3.3: "Completion also drives the clearance counters: when a
        completed `FOLLOW_UP` inspection carries a `bed_bug_case_id`, the
        server replays that case's clearance evaluation, and a positive finding
        resets the case's `consecutive_negative_count` to zero."

        Design: Difficulty/non_linear_state_machine/bed_bug_case_reopen_cycle
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        unit, resident, tech = ctx["unit"], ctx["resident"], ctx["technician"]
        _, case = complete_positive_inspection(unit["id"], tech)
        setup_case_monitoring(resident, tech, unit["id"], case["id"])
        case_now = validate_success(api.get_bed_bug_case(case["id"], MANAGER))
        assert case_now["status"] == "MONITORING"

        complete_follow_up(unit["id"], case["id"], tech, "2026-08-15T09:00:00Z",
                           positive=False)
        fu2 = complete_follow_up(unit["id"], case["id"], tech, "2026-08-16T09:00:00Z",
                                 positive=True, live_sightings=1)
        case_after = validate_success(api.get_bed_bug_case(case["id"], MANAGER))
        assert case_after["status"] == "REOPENED"
        assert case_after["consecutive_negative_count"] == 0

    def test_full_reopen_cycle_ends_cleared_and_restores_property(self, api):
        """PRD §3.6: "Clearance passes only when the running count is at least
        2, the two most recent consecutive negatives were completed at least 14
        days apart inclusive, and every disposal of the case is `VERIFIED` or
        none exist."
        PRD §3.6: "A passing evaluation moves the case to `CLEARED`, stamps
        `cleared_at`, recomputes the unit's `pest_flag` — an `INFESTED` unit
        returns to `CLEAR` when no other non-terminal case and no scheduled
        auto-created initial inspection remain — and recomputes the property's
        case count and posture."

        Design: Difficulty/non_linear_state_machine/bed_bug_case_reopen_cycle
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        prop, unit, resident, tech = (ctx["property"], ctx["unit"],
                                      ctx["resident"], ctx["technician"])
        _, case = complete_positive_inspection(unit["id"], tech)

        # First loop: OPEN -> TREATING -> MONITORING
        setup_case_monitoring(resident, tech, unit["id"], case["id"],
                              window_start="2026-08-10T09:00:00Z",
                              window_end="2026-08-10T10:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-08-15T09:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-08-16T09:00:00Z",
                           positive=True, live_sightings=1)
        case_now = validate_success(api.get_bed_bug_case(case["id"], MANAGER))
        assert case_now["status"] == "REOPENED" and case_now["consecutive_negative_count"] == 0

        # Second loop: REOPENED -> TREATING -> MONITORING
        setup_case_monitoring(resident, tech, unit["id"], case["id"],
                              window_start="2026-08-20T09:00:00Z",
                              window_end="2026-08-20T10:00:00Z")
        case_now = validate_success(api.get_bed_bug_case(case["id"], MANAGER))
        assert case_now["status"] == "MONITORING"

        set_clock("2026-08-21T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-08-21T09:00:00Z")
        set_clock("2026-09-04T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-09-04T09:00:00Z")

        cleared = validate_success(api.evaluate_clearance(case["id"], MANAGER))
        assert cleared["status"] == "CLEARED"
        assert cleared["consecutive_negative_count"] == 2
        # PRD pins the stamped instant ("stamps `cleared_at`" at the current
        # logical time, 2026-09-04T00:00:00Z) but not its string format.
        assert _parse_ts(cleared["cleared_at"]) == _parse_ts("2026-09-04T00:00:00Z")

        unit_after = validate_success(api.get_unit(unit["id"], MANAGER))
        assert unit_after["pest_flag"] == "CLEAR"
        summary = validate_success(api.get_property_summary(prop["id"], MANAGER))
        assert summary["posture"] == "STANDARD"
        assert summary["open_bed_bug_case_count"] == 0


class TestClearanceSpacingBoundary:
    def test_clearance_spacing_exact_fourteen_days(self, api):
        """PRD §3.6: "Clearance passes only when the running count is at least
        2, the two most recent consecutive negatives were completed at least 14
        days apart inclusive, and every disposal of the case is `VERIFIED` or
        none exist. A shortfall in the count or spacing returns
        `ERR_CLEARANCE_CRITERIA_UNMET` (HTTP 422); a disposal still `PENDING`
        or `REJECTED` returns `ERR_DISPOSAL_UNVERIFIED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/clearance_spacing_exact_fourteen_days
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        unit, resident, tech = ctx["unit"], ctx["resident"], ctx["technician"]
        _, case = complete_positive_inspection(unit["id"], tech)
        setup_case_monitoring(resident, tech, unit["id"], case["id"])

        set_clock("2026-08-10T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-08-10T09:00:00Z")
        set_clock("2026-08-23T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-08-23T09:00:00Z")

        resp = api.evaluate_clearance(case["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_CRITERIA_UNMET)

        set_clock("2026-09-06T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-09-06T09:00:00Z")
        cleared = validate_success(api.evaluate_clearance(case["id"], MANAGER))
        assert cleared["status"] == "CLEARED"
        assert cleared["consecutive_negative_count"] == 3

    def test_thirteen_day_spacing_fails_then_fourteen_day_extension_passes(self, api):
        """PRD §3.6: "Clearance passes only when the running count is at least
        2, the two most recent consecutive negatives were completed at least 14
        days apart inclusive, and every disposal of the case is `VERIFIED` or
        none exist. A shortfall in the count or spacing returns
        `ERR_CLEARANCE_CRITERIA_UNMET` (HTTP 422); a disposal still `PENDING`
        or `REJECTED` returns `ERR_DISPOSAL_UNVERIFIED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/clearance_spacing_exact_fourteen_days
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        unit, resident, tech = ctx["unit"], ctx["resident"], ctx["technician"]
        _, case = complete_positive_inspection(unit["id"], tech)
        setup_case_monitoring(resident, tech, unit["id"], case["id"])

        set_clock("2026-08-10T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-08-10T09:00:00Z")
        set_clock("2026-08-23T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-08-23T09:00:00Z")
        validate_error(api.evaluate_clearance(case["id"], MANAGER),
                       ApiErrorId.ERR_CLEARANCE_CRITERIA_UNMET)

        # Extend: a third negative 14 days after the second makes the last
        # pair exactly 14 days apart.
        set_clock("2026-09-06T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-09-06T09:00:00Z")
        cleared = validate_success(api.evaluate_clearance(case["id"], MANAGER))
        assert cleared["status"] == "CLEARED"


class TestDisposalBlocksClearance:
    def test_disposal_pending_blocks_clearance(self, api):
        """PRD §3.6: "Clearance passes only when the running count is at least
        2, the two most recent consecutive negatives were completed at least 14
        days apart inclusive, and every disposal of the case is `VERIFIED` or
        none exist. A shortfall in the count or spacing returns
        `ERR_CLEARANCE_CRITERIA_UNMET` (HTTP 422); a disposal still `PENDING`
        or `REJECTED` returns `ERR_DISPOSAL_UNVERIFIED` (HTTP 422)."

        Design: Corner/validations/disposal_pending_blocks_clearance
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        unit, resident, tech = ctx["unit"], ctx["resident"], ctx["technician"]
        _, case = complete_positive_inspection(unit["id"], tech)
        setup_case_monitoring(resident, tech, unit["id"], case["id"])

        set_clock("2026-08-21T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-08-21T09:00:00Z")
        set_clock("2026-09-04T00:00:00Z")
        complete_follow_up(unit["id"], case["id"], tech, "2026-09-04T09:00:00Z")

        get_success_data(
            api.create_furniture_disposal(case["id"],
                                          {"item_description": "mattress", "quantity": 1},
                                          MANAGER)
        )
        resp = api.evaluate_clearance(case["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_DISPOSAL_UNVERIFIED)


class TestPostureBoundary:
    def test_posture_elevated_at_exactly_two_cases(self, api):
        """PRD §3.1: "`posture`, which is `RESTRICTED` when that count reaches
        at least 3, `ELEVATED` when it is at least 1, and `STANDARD` otherwise.
        The count thresholds are inclusive, and both indicators recompute on
        every case creation, reopen, and clearance."

        Design: Corner/calculations/posture_elevated_at_exactly_two_cases
        """
        ctx = setup_community(num_units=2, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        prop = ctx["property"]
        tech = ctx["technician"]
        # Non-adjacent: stacks 1 and 3 on floor 1 (delta 2) so no INITIAL
        # cross-creation complicates the case count.
        u1 = create_unit(prop["id"], unit_number="201", floor=1, stack_index=1, bedrooms=1)
        u3 = create_unit(prop["id"], unit_number="203", floor=1, stack_index=3, bedrooms=1)
        complete_positive_inspection(u1["id"], tech, scheduled_for="2026-08-05T09:00:00Z")
        complete_positive_inspection(u3["id"], tech, scheduled_for="2026-08-05T10:00:00Z")

        summary = validate_success(api.get_property_summary(prop["id"], MANAGER))
        assert summary["open_bed_bug_case_count"] == 2
        assert summary["posture"] == "ELEVATED"
