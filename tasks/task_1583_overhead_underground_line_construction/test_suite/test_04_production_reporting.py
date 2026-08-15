"""Daily production reporting: the quantity ceiling, the outage gate, OCC on the
assignment version, and acceptance accounting input filters."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_entry,
    create_production_entry_payload,
    fail_entry,
    fresh_assignment_version,
    get_success_data,
    report_production,
    setup_approved_outage,
    setup_field_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
DISPATCHER = TEST_USERS["utility_dispatcher_headers"]


def _cap_scenario(api, contract_number="C-701"):
    """ACTIVE contract (est=100, default 125% ceiling) with an IN_PROGRESS work
    package and an ACTIVE assignment; 100 units already reported (SUBMITTED)."""
    scenario = setup_field_scenario(
        contract_overrides={"contract_number": contract_number},
        bid_item_overrides={"item_code": "OH-WIRE-4/0", "description": "4/0 ACSR",
                            "unit": "LF", "unit_price": 8.00,
                            "estimated_quantity": 100},
        wp_overrides={"name": "Reconductor R-2", "location": "Feeder F-7"},
        crew_overrides={"crew_code": "CR-C1"},
        equipment_overrides={"equipment_code": "EQ-C1", "kind": "REEL_TRAILER",
                             "daily_rate": 90.00})
    report_production(scenario["assignment"]["id"],
                      scenario["bid_item"]["id"], "2026-08-03", 100)
    return scenario


class TestQuantityCeiling:
    def test_quantity_cap_allows_exact_ceiling(self, api):
        """PRD §3.3: "The cumulative `quantity_reported` across the bid item's
        entries standing in `SUBMITTED` or `ACCEPTED`, plus the quantity now
        being reported, must not exceed the bid item's `estimated_quantity`
        multiplied by the contract's `quantity_cap_pct` — one hundred
        twenty-five percent of the schedule by default. Equality is permitted:
        the check rejects only a strict excess, with `ERR_QUANTITY_CAP_EXCEEDED`
        (HTTP 422)."
        100 already reported + 25 more = 125 == 100 x 1.25 exactly: allowed.

        Design: Difficulty/boundary_precision_check/quantity_cap_equality_boundary
        """
        scenario = _cap_scenario(api)
        version = fresh_assignment_version(scenario["assignment"]["id"])
        resp = api.create_production_entry(
            scenario["assignment"]["id"],
            create_production_entry_payload(scenario["bid_item"]["id"],
                                            "2026-08-04", 25, version),
            FOREMAN)
        entry = validate_success(resp, 201)
        assert entry["status"] == "SUBMITTED", (
            "Cumulative 125 == estimated 100 x 1.25 exactly; equality allowed")

    def test_quantity_cap_rejects_one_over_ceiling(self, api):
        """PRD §3.3: "The cumulative `quantity_reported` across the bid item's
        entries standing in `SUBMITTED` or `ACCEPTED`, plus the quantity now
        being reported, must not exceed the bid item's `estimated_quantity`
        multiplied by the contract's `quantity_cap_pct` — one hundred
        twenty-five percent of the schedule by default. Equality is permitted:
        the check rejects only a strict excess, with `ERR_QUANTITY_CAP_EXCEEDED`
        (HTTP 422)."
        100 + 25 = 125 at the ceiling, then 1 more = 126 > 125: strict excess.

        Design: Difficulty/boundary_precision_check/quantity_cap_equality_boundary
        """
        scenario = _cap_scenario(api)
        report_production(scenario["assignment"]["id"],
                          scenario["bid_item"]["id"], "2026-08-04", 25)
        version = fresh_assignment_version(scenario["assignment"]["id"])
        resp = api.create_production_entry(
            scenario["assignment"]["id"],
            create_production_entry_payload(scenario["bid_item"]["id"],
                                            "2026-08-05", 1, version),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_CAP_EXCEEDED)


class TestAcceptanceAccounting:
    def test_accepted_quantity_counts_only_accepted_entries(self, api):
        """PRD §3.1: "Every bid item also exposes two running totals that both
        start at zero: `accepted_quantity`, the sum of `quantity_reported` over
        the item's production entries standing in `ACCEPTED`, and
        `billed_quantity`, the frozen units already placed on submitted-or-later
        invoices as defined in §2.8."
        PRD §3.2: "Two counters ride on the package and appear on every read of
        it: `rework_open_count`, the number of production entries reported under
        its assignments that currently stand in `REWORK_REQUIRED`, and
        `open_material_issue_count`, the number of its material issues still
        `OPEN`."
        With 10 ACCEPTED + 7 SUBMITTED + 5 VOID + 3 REWORK_REQUIRED, only the
        ACCEPTED 10 count.

        Design: Corner/calculations/accepted_quantity_counts_only_accepted_entries
        """
        scenario = setup_field_scenario(
            contract_overrides={"contract_number": "CC-1"},
            bid_item_overrides={"estimated_quantity": 200},
            wp_overrides={"name": "WP filt", "location": "L7"},
            crew_overrides={"crew_code": "CR-FL"},
            equipment_overrides={"equipment_code": "EQ-FL"})
        asg_id = scenario["assignment"]["id"]
        bid_id = scenario["bid_item"]["id"]
        wp_id = scenario["work_package"]["id"]

        e1 = report_production(asg_id, bid_id, "2026-08-03", 10)
        accept_entry(wp_id, e1["id"])
        report_production(asg_id, bid_id, "2026-08-04", 7)  # stays SUBMITTED
        e3 = report_production(asg_id, bid_id, "2026-08-05", 5)
        get_success_data(api.void_production_entry(e3["id"], FOREMAN))
        e4 = report_production(asg_id, bid_id, "2026-08-06", 3)
        fail_entry(wp_id, e4["id"])

        bid_item = validate_success(api.get_bid_item(bid_id, PM))
        assert bid_item["accepted_quantity"] == 10, (
            "SUBMITTED, VOID, and REWORK_REQUIRED entries are all excluded")
        wp = validate_success(api.get_work_package(wp_id, PM))
        assert wp["rework_open_count"] == 1, (
            "Only the REWORK_REQUIRED entry counts toward open rework")


def _outage_scenario(api, contract_number="C-800"):
    """IN_PROGRESS outage-dependent work package with an ACTIVE assignment and
    the logical clock parked at 2026-08-03T12:00:00Z."""
    return setup_field_scenario(
        requires_outage=True,
        contract_overrides={"contract_number": contract_number},
        bid_item_overrides={"item_code": "UG-SPLICE", "description": "Cable splice",
                            "unit_price": 75.00, "estimated_quantity": 60},
        wp_overrides={"name": "Splice pit S-4", "location": "River crossing"},
        crew_overrides={"crew_code": "CR-O", "crew_type": "UNDERGROUND",
                        "base_rate_per_hour": 58.00},
        equipment_overrides={"equipment_code": "EQ-O", "kind": "TRENCHER",
                             "daily_rate": 180.00})


class TestOutageGate:
    def test_production_without_in_effect_outage_rejected(self, api):
        """PRD §3.3: "And the outage gate, for any work package whose
        `requires_outage` flag is true, demands that an outage request belonging
        to that same work package stand `IN_EFFECT` with a window covering the
        entry's `work_date`; without such coverage the report is rejected with
        `ERR_OUTAGE_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/production_requires_in_effect_outage
        """
        scenario = _outage_scenario(api)
        version = scenario["assignment"]["version"]
        resp = api.create_production_entry(
            scenario["assignment"]["id"],
            create_production_entry_payload(scenario["bid_item"]["id"],
                                            "2026-08-03", 5, version),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_REQUIRED)

    def test_production_allowed_once_outage_in_effect(self, api):
        """PRD §3.6: "Whenever the logical clock enters an approved window — the
        current time falling on or after `window_start` and on or before
        `window_end` — the request moves from `APPROVED` to `IN_EFFECT`. The
        evaluation is lazy: it runs whenever the clock is set and whenever the
        request is read or referenced by another operation, including list
        reads."
        PRD §3.3: "And the outage gate, for any work package whose
        `requires_outage` flag is true, demands that an outage request belonging
        to that same work package stand `IN_EFFECT` with a window covering the
        entry's `work_date`; without such coverage the report is rejected with
        `ERR_OUTAGE_REQUIRED`."
        The approved window 08:00-17:00 contains the logical clock's 12:00, so
        the read flips the request to IN_EFFECT and the gate passes.

        Design: Difficulty/cross_entity_state_dependency/production_requires_in_effect_outage
        """
        scenario = _outage_scenario(api)
        wp_id = scenario["work_package"]["id"]
        outage = setup_approved_outage(wp_id, "CKT-4",
                                       "2026-08-03T08:00:00Z",
                                       "2026-08-03T17:00:00Z")
        read = validate_success(api.get_outage_request(outage["id"], PM))
        assert read["status"] == "IN_EFFECT", (
            "The logical clock 2026-08-03T12:00:00Z is inside the approved window")

        version = fresh_assignment_version(scenario["assignment"]["id"])
        resp = api.create_production_entry(
            scenario["assignment"]["id"],
            create_production_entry_payload(scenario["bid_item"]["id"],
                                            "2026-08-03", 5, version),
            FOREMAN)
        entry = validate_success(resp, 201)
        assert entry["status"] == "SUBMITTED"


def _dual_violation_scenario(api):
    """Outage-dependent package: 100 units reported while an outage was in
    effect, then the outage is RELEASED so no IN_EFFECT coverage remains.
    The next report of 30 would break both the outage gate and the 125% ceiling
    (100 + 30 = 130 > 125)."""
    scenario = setup_field_scenario(
        requires_outage=True,
        contract_overrides={"contract_number": "C-601"},
        bid_item_overrides={"item_code": "UG-CABLE-750",
                            "description": "750MCM cable", "unit": "LF",
                            "unit_price": 40.00, "estimated_quantity": 100},
        wp_overrides={"name": "UG feeder U-11", "location": "Harbor line"},
        crew_overrides={"crew_code": "CR-Q", "crew_type": "UNDERGROUND",
                        "base_rate_per_hour": 58.00},
        equipment_overrides={"equipment_code": "EQ-Q", "kind": "REEL_TRAILER",
                             "daily_rate": 90.00})
    wp_id = scenario["work_package"]["id"]
    outage = setup_approved_outage(wp_id, "CKT-1",
                                   "2026-08-03T08:00:00Z",
                                   "2026-08-03T17:00:00Z")
    # Reported while the approved window covers the logical clock (IN_EFFECT).
    report_production(scenario["assignment"]["id"],
                      scenario["bid_item"]["id"], "2026-08-03", 100)
    released = get_success_data(api.release_outage_request(outage["id"], DISPATCHER))
    assert released["status"] == "RELEASED"
    return scenario


class TestGatePrecedence:
    def test_outage_gate_beats_quantity_cap(self, api):
        """PRD §2.9: "Every request is evaluated against a fixed precedence
        ladder, so that when several rules would fail at once the error surfaced
        to the caller is deterministic."
        PRD §2.9: "8. Work-safety gates — outage coverage for outage-dependent
        production (`ERR_OUTAGE_REQUIRED`) and equipment availability
        (`ERR_EQUIPMENT_DOWN`)."
        PRD §2.9: "9. Business constraints — crew and equipment scheduling
        conflicts, outage-window clearance, storm-duty exclusivity,
        open-inspection uniqueness, the quantity ceiling, date-range
        well-formedness, return bounds, variance authorization, and the
        completion, resume, and close gates, each carrying its own error
        identifier."
        The safety gate (rung 8) precedes the quantity ceiling (rung 9), so the
        dual violation surfaces ERR_OUTAGE_REQUIRED.

        Design: Difficulty/priority_pair_validation_conflict/outage_safety_beats_quantity_cap
        """
        scenario = _dual_violation_scenario(api)
        version = fresh_assignment_version(scenario["assignment"]["id"])
        resp = api.create_production_entry(
            scenario["assignment"]["id"],
            create_production_entry_payload(scenario["bid_item"]["id"],
                                            "2026-08-03", 30, version),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_REQUIRED)

    def test_outage_cap_dual_violation_creates_no_entry(self, api):
        """PRD §2.9: "Every request is evaluated against a fixed precedence
        ladder, so that when several rules would fail at once the error surfaced
        to the caller is deterministic."
        PRD §3.3: "And the outage gate, for any work package whose
        `requires_outage` flag is true, demands that an outage request belonging
        to that same work package stand `IN_EFFECT` with a window covering the
        entry's `work_date`; without such coverage the report is rejected with
        `ERR_OUTAGE_REQUIRED`."
        The rejected report persists nothing: only the pre-existing entry
        remains listed for the assignment.

        Design: Difficulty/priority_pair_validation_conflict/outage_safety_beats_quantity_cap
        """
        scenario = _dual_violation_scenario(api)
        asg_id = scenario["assignment"]["id"]
        version = fresh_assignment_version(asg_id)
        resp = api.create_production_entry(
            asg_id,
            create_production_entry_payload(scenario["bid_item"]["id"],
                                            "2026-08-03", 30, version),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_REQUIRED)

        entries, meta = validate_paginated(
            api.list_production_entries(PM, params={"assignment_id": asg_id}))
        assert meta["total_count"] == 1, "The rejected report created no entry"
        assert entries[0]["quantity_reported"] == 100
        assert entries[0]["status"] == "SUBMITTED"


class TestAssignmentOcc:
    def test_stale_assignment_version_rejected(self, api):
        """PRD §2.6: "A request to report daily production against an assignment
        must carry `expected_assignment_version`, set to the assignment's
        `version` as the client last read it. If the assignment's current
        `version` has advanced since that read — for instance because another
        writer has posted a production entry against the same assignment, which
        legitimately advances the assignment's daily tally — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
        recording production against a tally it has not observed."

        Design: Corner/cross_cutting_layers/occ_stale_assignment_version_rejected
        """
        scenario = setup_field_scenario(
            contract_overrides={"contract_number": "CL-1"},
            wp_overrides={"name": "WP occ", "location": "L26"},
            crew_overrides={"crew_code": "CR-OC"},
            equipment_overrides={"equipment_code": "EQ-OC"})
        asg_id = scenario["assignment"]["id"]
        stale_version = scenario["assignment"]["version"]

        # First report succeeds and advances the assignment's version by one.
        first = report_production(asg_id, scenario["bid_item"]["id"],
                                  "2026-08-03", 5)
        assert first["status"] == "SUBMITTED"
        after_first = validate_success(api.get_assignment(asg_id, FOREMAN))
        assert after_first["version"] == stale_version + 1, (
            "Posting a production entry increments the assignment's version by one")

        # Replaying the stale version is rejected.
        resp = api.create_production_entry(
            asg_id,
            create_production_entry_payload(scenario["bid_item"]["id"],
                                            "2026-08-04", 5, stale_version),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after_reject = validate_success(api.get_assignment(asg_id, FOREMAN))
        assert after_reject["version"] == after_first["version"], (
            "The rejected call does not advance the assignment's version")

        # Retrying with the freshly read version succeeds.
        retry = api.create_production_entry(
            asg_id,
            create_production_entry_payload(scenario["bid_item"]["id"],
                                            "2026-08-04", 5,
                                            after_reject["version"]),
            FOREMAN)
        entry = validate_success(retry, 201)
        assert entry["status"] == "SUBMITTED"
