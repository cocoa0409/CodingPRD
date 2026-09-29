"""Punch-list severity, the verification walk, and the plan's compound readiness edge."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_field_equals,
    assert_item_state,
    assert_plan_dimensions,
    assert_posture,
    complete_item_work,
    executing_plan,
    list_rows,
    performed_completion_inspection,
    punch_verify_payload,
    raise_defect,
    read_budget,
    read_inspection,
    read_item,
    read_plan,
    read_property,
    read_punch_item,
    remediate_defect,
    start_item,
    validate_error,
    verify_defect,
)


@pytest.fixture
def major_defect_on_a_performed_walk(api):
    """A finished guest-facing item knocked back by one major defect at the completion walk."""
    built = performed_completion_inspection(
        api,
        [
            {
                "key": "sconces",
                "category": "GUEST_FACING",
                "standards_reference": "GF-4.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        1182500,
        scheduled_date="2026-08-01",
        perform_at_utc="2026-08-01T00:00:00Z",
        legal_name="Larkspur Hotels LLC",
        contact_email="gm@larkspurhotels.example",
    )
    scenario = built["scenario"]
    built["punch"] = raise_defect(
        api,
        built["inspection"]["id"],
        scenario.item_id("sconces"),
        severity="MAJOR",
        defect_note=(
            "Corridor sconces installed at the wrong mounting height on floors four and five."
        ),
    )
    return built


class TestPunchListVerificationWalk:
    def test_a_major_defect_opens_the_list_and_reopens_the_work(
        self, api, major_defect_on_a_performed_walk
    ):
        """"The defect is created in `OPEN` with `verification_note` null and with
        `cure_deadline_date` set to the clock date advanced by 14 days." "A `MAJOR` or `CRITICAL`
        defect knocks the charged item `WORK_COMPLETE → PUNCH_FAIL`, increments that item's
        `version`, and — because the plan's aggregate readiness condition no longer holds — reverts
        the plan `READY_FOR_COMPLETION_INSPECTION → IN_EXECUTION`, incrementing the plan's
        `version`." "Open `MAJOR` defects cost 5 points each".

        Design: Corner/state_machines/punch_list_defect_walks_open_remediated_verified_closed
        """
        built = major_defect_on_a_performed_walk
        scenario = built["scenario"]

        punch = built["punch"]

        assert_field_equals(punch, "status", "OPEN", "defect")
        assert_field_equals(punch, "cure_deadline_date", "2026-08-15", "defect")
        assert_field_equals(
            read_inspection(api, built["inspection"]["id"]), "punch_open_count", 1, "inspection"
        )
        assert_item_state(read_item(api, scenario.item_id("sconces")), status="PUNCH_FAIL")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")
        assert_posture(read_property(api, scenario.property_id), 95, "COMPLIANT")

    def test_remediation_is_a_claim_and_not_a_closure(
        self, api, major_defect_on_a_performed_walk
    ):
        """"Remediation is a claim, not a closure: the defect still counts toward
        `punch_open_count` and still carries its risk-score penalty until the inspector acts."

        Design: Corner/state_machines/punch_list_defect_walks_open_remediated_verified_closed
        """
        built = major_defect_on_a_performed_walk
        scenario = built["scenario"]

        remediated = remediate_defect(api, scenario, built["punch"]["id"])

        assert_field_equals(remediated, "status", "REMEDIATED", "defect")
        assert_field_equals(
            read_inspection(api, built["inspection"]["id"]), "punch_open_count", 1, "inspection"
        )
        assert_item_state(read_item(api, scenario.item_id("sconces")), status="PUNCH_FAIL")
        assert_posture(read_property(api, scenario.property_id), 95, "COMPLIANT")

    def test_verification_closes_the_defect_and_restores_readiness(
        self, api, major_defect_on_a_performed_walk
    ):
        """"`CLOSE` moves the defect `REMEDIATED → VERIFIED_CLOSED` and decreases the inspection's
        `punch_open_count` by one; if every defect charged to the same item is now
        `VERIFIED_CLOSED` or `WAIVED`, that item returns `PUNCH_FAIL → WORK_COMPLETE` with its
        `version` incremented and the plan re-evaluates its compound readiness condition; the
        property's `compliance_risk_score` and `compliance_posture` are recomputed."

        Design: Corner/state_machines/punch_list_defect_walks_open_remediated_verified_closed
        """
        built = major_defect_on_a_performed_walk
        scenario = built["scenario"]
        remediate_defect(api, scenario, built["punch"]["id"])

        closed = verify_defect(
            api,
            built["punch"]["id"],
            "CLOSE",
            verification_note="Re-measured at the specified height on both floors.",
        )

        assert_field_equals(closed, "status", "VERIFIED_CLOSED", "defect")
        inspection = read_inspection(api, built["inspection"]["id"])
        assert_field_equals(inspection, "punch_open_count", 0, "inspection")
        assert_field_equals(inspection, "status", "PERFORMED", "inspection")
        assert_item_state(read_item(api, scenario.item_id("sconces")), status="WORK_COMPLETE")
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), status="READY_FOR_COMPLETION_INSPECTION"
        )
        assert_posture(read_property(api, scenario.property_id), 100, "COMPLIANT")


@pytest.fixture
def minor_defect_on_a_performed_walk(api):
    """A finished back-of-house item carrying one minor defect and nothing worse."""
    built = performed_completion_inspection(
        api,
        [
            {
                "key": "kitchen_line",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-5.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        1138500,
        scheduled_date="2026-08-01",
        perform_at_utc="2026-08-01T00:00:00Z",
        legal_name="Maplewood Hospitality LLC",
        contact_email="ops@maplewoodhospitality.example",
    )
    scenario = built["scenario"]
    built["minor"] = raise_defect(
        api,
        built["inspection"]["id"],
        scenario.item_id("kitchen_line"),
        severity="MINOR",
        defect_note="Two ceiling tiles in the service corridor are scuffed.",
    )
    return built


class TestSeverityDecidesWhetherWorkReopens:
    def test_a_minor_defect_counts_but_leaves_the_work_complete(
        self, api, minor_defect_on_a_performed_walk
    ):
        """"A `MINOR` defect does neither: it is recorded, it counts toward `punch_open_count`, and
        the charged item stays in `WORK_COMPLETE`." "`MINOR` defects carry no penalty at all."

        Design: Corner/state_machines/minor_defect_does_not_knock_the_item_back_but_major_does
        """
        built = minor_defect_on_a_performed_walk
        scenario = built["scenario"]

        assert_field_equals(built["minor"], "status", "OPEN", "minor defect")
        assert_field_equals(
            read_inspection(api, built["inspection"]["id"]), "punch_open_count", 1, "inspection"
        )
        assert_item_state(read_item(api, scenario.item_id("kitchen_line")), status="WORK_COMPLETE")
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), status="READY_FOR_COMPLETION_INSPECTION"
        )
        assert_posture(read_property(api, scenario.property_id), 100, "COMPLIANT")

    def test_a_major_defect_on_the_same_item_does_knock_it_back(
        self, api, minor_defect_on_a_performed_walk
    ):
        """"Severity decides whether the defect reopens work." "The raising inspection's
        `punch_open_count` increases by one, and the property's `compliance_risk_score` and
        `compliance_posture` are recomputed."

        Design: Corner/state_machines/minor_defect_does_not_knock_the_item_back_but_major_does
        """
        built = minor_defect_on_a_performed_walk
        scenario = built["scenario"]

        raise_defect(
            api,
            built["inspection"]["id"],
            scenario.item_id("kitchen_line"),
            severity="MAJOR",
            defect_note="Walk-in cooler condensate line drains onto the finished floor.",
        )

        assert_item_state(read_item(api, scenario.item_id("kitchen_line")), status="PUNCH_FAIL")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")
        assert_field_equals(
            read_inspection(api, built["inspection"]["id"]), "punch_open_count", 2, "inspection"
        )
        assert_posture(read_property(api, scenario.property_id), 95, "COMPLIANT")

    def test_the_minor_row_is_untouched_by_the_major_filing(
        self, api, minor_defect_on_a_performed_walk
    ):
        """"The defect is created in `OPEN` with `verification_note` null and with
        `cure_deadline_date` set to the clock date advanced by 14 days." "The owner reports a defect
        fixed, moving it `OPEN → REMEDIATED`".

        Design: Corner/state_machines/minor_defect_does_not_knock_the_item_back_but_major_does
        """
        built = minor_defect_on_a_performed_walk
        scenario = built["scenario"]
        raise_defect(
            api,
            built["inspection"]["id"],
            scenario.item_id("kitchen_line"),
            severity="MAJOR",
            defect_note="Walk-in cooler condensate line drains onto the finished floor.",
        )

        minor = read_punch_item(api, built["minor"]["id"])

        assert_field_equals(minor, "status", "OPEN", "minor defect")
        assert_field_equals(minor, "severity", "MINOR", "minor defect")
        assert_field_equals(minor, "cure_deadline_date", "2026-08-15", "minor defect")
        rows, meta = list_rows(
            api, "list_punch_list_items", inspection_id=built["inspection"]["id"]
        )
        assert meta["total_count"] == 2, f"both defects should be listed, got {meta}"
        assert {row["severity"] for row in rows} == {"MINOR", "MAJOR"}, (
            f"the inspection should carry one defect of each severity, got {rows}"
        )


@pytest.fixture
def critical_defect_on_a_performed_walk(api):
    """A critical life-safety wiring defect raised against finished guest-facing work."""
    built = performed_completion_inspection(
        api,
        [
            {
                "key": "guestrooms",
                "category": "GUEST_FACING",
                "standards_reference": "GF-7.4.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        1182500,
        scheduled_date="2026-08-01",
        perform_at_utc="2026-08-01T00:00:00Z",
        legal_name="Silverbirch Lodging LLC",
        contact_email="director@silverbirchlodging.example",
    )
    scenario = built["scenario"]
    built["punch"] = raise_defect(
        api,
        built["inspection"]["id"],
        scenario.item_id("guestrooms"),
        severity="CRITICAL",
        defect_note="Guest room smoke detectors on floor six are wired to a dead circuit.",
    )
    return built


class TestCriticalDefectCannotBeWaived:
    def test_a_waiver_on_a_critical_defect_is_refused(
        self, api, brand_inspector, critical_defect_on_a_performed_walk
    ):
        """"`WAIVE` is admissible from either `OPEN` or `REMEDIATED` — both source states behave
        identically — but never for a `CRITICAL` defect, which may only be remediated and verified
        closed; a waiver attempted on a critical defect is refused with
        `ERR_CRITICAL_DEFECT_NOT_WAIVABLE` (409)."

        Design: Corner/state_machines/critical_defect_cannot_be_waived_and_blocks_signoff
        """
        built = critical_defect_on_a_performed_walk

        response = api.verify_punch_list_item(
            built["punch"]["id"], punch_verify_payload("WAIVE"), brand_inspector
        )

        validate_error(response, ApiErrorId.ERR_CRITICAL_DEFECT_NOT_WAIVABLE, 409)
        refused = read_punch_item(api, built["punch"]["id"])
        assert_field_equals(refused, "status", "OPEN", "critical defect")
        assert refused["verification_note"] is None, (
            "a refused waiver may not record a verification note, got "
            f"{refused['verification_note']!r}"
        )

    def test_the_open_critical_defect_holds_the_plan_out_of_readiness(
        self, api, critical_defect_on_a_performed_walk
    ):
        """"Open `MAJOR` defects cost 5 points each and open `CRITICAL` defects 12 points each".
        "A `MAJOR` or `CRITICAL` defect knocks the charged item `WORK_COMPLETE → PUNCH_FAIL`,
        increments that item's `version`, and — because the plan's aggregate readiness condition no
        longer holds — reverts the plan `READY_FOR_COMPLETION_INSPECTION → IN_EXECUTION`".

        Design: Corner/state_machines/critical_defect_cannot_be_waived_and_blocks_signoff
        """
        built = critical_defect_on_a_performed_walk
        scenario = built["scenario"]

        inspection = read_inspection(api, built["inspection"]["id"])

        assert_field_equals(inspection, "status", "PERFORMED", "inspection")
        assert_field_equals(inspection, "punch_open_count", 1, "inspection")
        assert_item_state(read_item(api, scenario.item_id("guestrooms")), status="PUNCH_FAIL")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")
        assert_posture(read_property(api, scenario.property_id), 88, "COMPLIANT")

    def test_certification_is_refused_while_the_defect_stands(
        self, api, brand_inspector, critical_defect_on_a_performed_walk
    ):
        """"The plan's `status` must be `READY_FOR_COMPLETION_INSPECTION`, or
        `ERR_PLAN_NOT_READY_FOR_SIGNOFF`." "And the inspection's `punch_open_count` must be exactly
        0 — no defect of the inspection still `OPEN` or `REMEDIATED` — or `ERR_PUNCH_LIST_OPEN`."

        Design: Corner/state_machines/critical_defect_cannot_be_waived_and_blocks_signoff
        """
        built = critical_defect_on_a_performed_walk
        scenario = built["scenario"]

        response = api.sign_off_inspection(built["inspection"]["id"], brand_inspector)

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_READY_FOR_SIGNOFF, 409)
        inspection = read_inspection(api, built["inspection"]["id"])
        assert_field_equals(inspection, "status", "PERFORMED", "inspection")
        assert inspection["signed_off_at"] is None, (
            f"a refused sign-off may not stamp signed_off_at, got {inspection['signed_off_at']!r}"
        )
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")


@pytest.fixture
def two_items_in_progress(api):
    """Two guest-facing items started under one locked budget, neither reported finished."""
    built = executing_plan(
        api,
        [
            {
                "key": "first",
                "category": "GUEST_FACING",
                "standards_reference": "GF-3.1.1",
                "brand_estimated_cost_cents": 1000000,
            },
            {
                "key": "second",
                "category": "GUEST_FACING",
                "standards_reference": "GF-3.1.2",
                "brand_estimated_cost_cents": 1000000,
            },
        ],
        2365000,
        financing_source="TERM_LOAN",
        legal_name="Umberfield Hotels LLC",
        contact_email="projects@umberfieldhotels.example",
    )
    scenario = built["scenario"]
    start_item(api, scenario, scenario.item_id("first"))
    start_item(api, scenario, scenario.item_id("second"))
    return built


class TestCompoundReadinessNeedsEveryItem:
    def test_the_first_completion_leaves_the_plan_in_execution(self, api, two_items_in_progress):
        """"A plan rises `IN_EXECUTION → READY_FOR_COMPLETION_INSPECTION` when two things hold: its
        `scope_item_count` is at least 1, and every item of the plan whose `status` is neither
        `REMOVED_BY_DISPUTE` nor `VOIDED` is in `WORK_COMPLETE` or `ACCEPTED`."

        Design: Corner/state_machines/last_item_completion_bubbles_the_plan_to_ready_for_inspection
        """
        scenario = two_items_in_progress["scenario"]

        finished = complete_item_work(api, scenario, scenario.item_id("first"))

        assert_field_equals(finished, "status", "WORK_COMPLETE", "first item")
        assert_item_state(read_item(api, scenario.item_id("second")), status="IN_PROGRESS")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")

    def test_the_last_completion_bubbles_the_plan_up(self, api, two_items_in_progress):
        """"No client request drives it; the condition is re-evaluated after an item's work is
        reported complete and after a punch-list defect is verified, and the plan's `version`
        increments when the transition fires."

        Design: Corner/state_machines/last_item_completion_bubbles_the_plan_to_ready_for_inspection
        """
        scenario = two_items_in_progress["scenario"]
        complete_item_work(api, scenario, scenario.item_id("first"))

        complete_item_work(api, scenario, scenario.item_id("second"))

        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), status="READY_FOR_COMPLETION_INSPECTION"
        )
        assert_item_state(read_item(api, scenario.item_id("second")), status="WORK_COMPLETE")

    def test_readiness_moves_nothing_else_on_the_plan(self, api, two_items_in_progress):
        """"Reporting the work finished moves the item `IN_PROGRESS → WORK_COMPLETE` ... The item's
        `version` increments and its overdue flag is recomputed to false, since a completed item is
        by definition no longer overdue." "a budget in `APPROVED`, `LOCKED` or `UNDERFUNDED` becomes
        `CLOSED` when its plan reaches `COMPLETED` or `TERMINATED`".

        Design: Corner/state_machines/last_item_completion_bubbles_the_plan_to_ready_for_inspection
        """
        built = two_items_in_progress
        scenario = built["scenario"]
        complete_item_work(api, scenario, scenario.item_id("first"))
        complete_item_work(api, scenario, scenario.item_id("second"))

        assert_field_equals(read_budget(api, built["budget"]["id"]), "status", "LOCKED", "budget")
        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "open_plan_count", 1, "property")
        assert_posture(prop, 100, "COMPLIANT")
        assert_item_state(read_item(api, scenario.item_id("first")), is_overdue=False)
