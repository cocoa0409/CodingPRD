"""Accommodation plans, the check-in safety gate, and the allergen gate
(PRD §2.5, §3.5, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    approve_plan,
    create_item,
    create_plan,
    open_day_with_clock,
    set_clock,
    setup_in_session_program,
    setup_open_program_with_classroom,
    setup_family_with_children,
    register_child,
    create_day,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

_DIRECTOR = TEST_USERS["program_director_headers"]
_DESK = TEST_USERS["check_in_staff_headers"]


class TestPlanApprovalOcc:
    def test_stale_child_version_rejected(self, api, safety_officer_headers):
        """PRD §2.5: "Approving an accommodation plan (`POST
        /vbs/accommodation-plans/{plan_id}/approve`) requires the non-optional
        field `expected_child_version`, matching the current `version` of the
        plan's child" — mismatch reports `ERR_STALE_VERSION` (HTTP 412); §3.5:
        "the child's `version` increments by one because the supersede mutates
        the child's plan set", so the first approval is exactly what makes the
        second approval's view stale.

        Design: Corner/cross_cutting_layers/occ_plan_approve_stale_child_version_rejected
        """
        family, children = setup_family_with_children(count=1, special_needs=True)
        child = children[0]
        plan_a = create_plan(child["id"], family["id"],
                             instructions="Plan A instructions")
        submit_plan(plan_a["id"], family["id"])
        plan_b = create_plan(child["id"], family["id"],
                             allergens=["PEANUT", "TREE_NUT"],
                             instructions="Plan B instructions")
        submit_plan(plan_b["id"], family["id"])

        resp_a = api.approve_accommodation_plan(
            plan_a["id"], {"expected_child_version": child["version"]},
            safety_officer_headers,
        )
        assert validate_success(resp_a)["status"] == "APPROVED", (
            "first approve at the observed version succeeds"
        )

        resp_b = api.approve_accommodation_plan(
            plan_b["id"], {"expected_child_version": child["version"]},
            safety_officer_headers,
        )
        validate_error(resp_b, ApiErrorId.ERR_STALE_VERSION, 412)

        plan_b_after = validate_success(
            api.get_accommodation_plan(plan_b["id"], safety_officer_headers)
        )
        assert plan_b_after["status"] == "SUBMITTED", "no partial supersede"
        plan_a_after = validate_success(
            api.get_accommodation_plan(plan_a["id"], safety_officer_headers)
        )
        assert plan_a_after["status"] == "APPROVED"


class TestCheckInAccommodationGate:
    def _setup_open_day_with_submitted_plan(self):
        """IN_SESSION program, ADEQUATE staffing, one special-needs child
        ENROLLED, his FOOD_ALLERGY plan SUBMITTED but never approved, and the
        program day OPEN on its own date."""
        ctx = setup_in_session_program(child_count=1, special_needs=True)
        child = ctx["children"][0]
        family = ctx["families"][0]
        plan = create_plan(child["id"], family["id"], requires_epinephrine=True)
        submit_plan(plan["id"], family["id"])
        day = ctx["days"][0]
        open_day_with_clock(day)
        return ctx, child, plan, day

    def test_checkin_rejected_with_plan_only_submitted(self, api):
        """PRD §3.7: "Its gates fire in pipeline order: the safety gate first —
        a child with `has_special_needs` true must hold an `APPROVED`
        accommodation plan, failing with `ERR_ACCOMMODATION_NOT_APPROVED`" —
        SUBMITTED is not APPROVED.

        Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_accommodation_plan
        """
        _ctx, child, _plan, day = self._setup_open_day_with_submitted_plan()
        resp = api.check_in(
            {"child_id": child["id"], "program_day_id": day["id"]}, _DESK
        )
        validate_error(resp, ApiErrorId.ERR_ACCOMMODATION_NOT_APPROVED, 409)

    def test_checkin_succeeds_after_approval(self, api):
        """PRD §3.7: "the safety gate first — a child with `has_special_needs`
        true must hold an `APPROVED` accommodation plan"; §3.5: "A successful
        approval moves `SUBMITTED` → `APPROVED`". With the gate flipped, the
        same check-in succeeds and "mints a security tag: an `ISSUED` tag for
        the child and day whose `tag_code` the record copies" (§3.7).

        Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_accommodation_plan
        """
        ctx, child, plan, day = self._setup_open_day_with_submitted_plan()
        approved = approve_plan(plan["id"], expected_child_version=child["version"])
        assert approved["status"] == "APPROVED"

        resp = api.check_in(
            {"child_id": child["id"], "program_day_id": day["id"]}, _DESK
        )
        record = validate_success(resp, 201)
        assert record["status"] == "CHECKED_IN"
        assert record["tag_code"] is not None


class TestSafetyBeatsState:
    def _setup_scheduled_day_with_submitted_plan(self):
        """IN_SESSION program with the day still SCHEDULED (never opened) and
        the special-needs child's plan SUBMITTED: both the safety gate and the
        state gate would fail. Clock sits on the day's date so no temporal
        check interferes."""
        ctx = setup_in_session_program(child_count=1, special_needs=True)
        child = ctx["children"][0]
        family = ctx["families"][0]
        plan = create_plan(child["id"], family["id"], requires_epinephrine=True)
        submit_plan(plan["id"], family["id"])
        day = ctx["days"][0]
        set_clock(f"{day['date']}T08:30:00Z")
        return ctx, child, day

    def test_safety_outranks_day_state(self, api):
        """PRD §3.7: "Its gates fire in pipeline order: the safety gate first —
        a child with `has_special_needs` true must hold an `APPROVED`
        accommodation plan, failing with `ERR_ACCOMMODATION_NOT_APPROVED`; then
        state — the day must be `OPEN` and the record `NOT_ARRIVED`, failing
        with `ERR_INVALID_STATE`". With both failing, the safety error
        surfaces.

        Design: Difficulty/priority_pair_validation_conflict/checkin_safety_beats_state
        """
        _ctx, child, day = self._setup_scheduled_day_with_submitted_plan()
        resp = api.check_in(
            {"child_id": child["id"], "program_day_id": day["id"]}, _DESK
        )
        validate_error(resp, ApiErrorId.ERR_ACCOMMODATION_NOT_APPROVED, 409)

    def test_rejected_checkin_creates_no_attendance(self, api):
        """PRD §3.7: "A successful check-in moves the record `NOT_ARRIVED` →
        `CHECKED_IN`" — and with the day never opened, §3.7's open step
        ("pre-creates an attendance record in `NOT_ARRIVED` for every
        `ENROLLED` registration of the program") never ran, so the rejected
        check-in leaves no attendance record for the child on that day.

        Design: Difficulty/priority_pair_validation_conflict/checkin_safety_beats_state
        """
        _ctx, child, day = self._setup_scheduled_day_with_submitted_plan()
        api.check_in({"child_id": child["id"], "program_day_id": day["id"]}, _DESK)
        data, meta = validate_paginated(
            api.list_attendance(
                _DIRECTOR,
                params={"child_id": child["id"], "program_day_id": day["id"]},
            )
        )
        assert meta["total_count"] == 0
        assert data == []


class TestAllergenGate:
    def _setup(self):
        """Child with an APPROVED PEANUT plan ENROLLED in the classroom; a
        SCHEDULED day; one PEANUT-tagged and one GLUTEN-tagged snack item."""
        program, classroom = setup_open_program_with_classroom(capacity=10)
        family, children = setup_family_with_children(count=1, special_needs=True)
        child = children[0]
        register_child(child["id"], classroom["id"], family["id"])
        plan = create_plan(child["id"], family["id"], allergens=["PEANUT"])
        submit_plan(plan["id"], family["id"])
        approve_plan(plan["id"], expected_child_version=child["version"])
        day = create_day(program["id"], program["start_date"])
        peanut_item = create_item(
            program["id"], name="Peanut Crackers", category="SNACK", unit="box",
            quantity_on_hand=5, allergen_tags=["PEANUT"],
        )
        gluten_item = create_item(
            program["id"], name="Rice Cakes", category="SNACK", unit="box",
            quantity_on_hand=5, allergen_tags=["GLUTEN"],
        )
        return classroom, day, peanut_item, gluten_item

    def test_allergen_conflict_rejected_and_clean_item_passes(self, api):
        """PRD §3.5: "the blocked-allergen set is the union of `allergens`
        across plans that are `APPROVED`, carry severity `FOOD_ALLERGY`, and
        belong to a child holding an `ENROLLED` registration in that
        classroom"; §3.6: "when the item is a snack, any overlap between the
        item's `allergen_tags` and the target classroom's blocked-allergen set
        of §3.5 rejects the plan with `ERR_ALLERGEN_CONFLICT`".

        Design: Corner/validations/allergen_conflict_rejected_and_clean_item_passes
        """
        classroom, day, peanut_item, gluten_item = self._setup()
        resp = api.create_supply_distribution(
            {"supply_item_id": peanut_item["id"], "classroom_id": classroom["id"],
             "program_day_id": day["id"], "quantity": 1},
            _DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT, 409)

        resp_ok = api.create_supply_distribution(
            {"supply_item_id": gluten_item["id"], "classroom_id": classroom["id"],
             "program_day_id": day["id"], "quantity": 1},
            _DIRECTOR,
        )
        assert validate_success(resp_ok, 201)["status"] == "PLANNED", (
            "disjoint allergen sets pass the safety check"
        )
