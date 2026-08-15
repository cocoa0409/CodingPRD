"""Blueprints, forms, slots, controlled assembly, and exposure cascades."""
from test_helpers import (
    ApiErrorId,
    assert_form_item_slot,
    get_success_data,
    validate_error,
)
from test_helpers.factories import create_equating_link_payload, create_slot_payload
from test_helpers.fixtures import (
    ASSEMBLER_H,
    PSYCH_H,
    add_slot,
    assemble_form,
    build_assembled_form,
    create_draft_item,
    create_form,
    create_locked_blueprint,
    create_program,
    create_standard,
    list_slots,
    make_operational_items,
    mark_compromised,
    read_item,
    submit_item,
)


def _one_operational_item(program, standard, cap=3, ones=30):
    return make_operational_items(program["id"], standard["id"], [ones],
                                  exposure_cap=cap)[0]


class TestAssemblyOccAndOrdering:
    def test_occ_stale_form_version_returns_412(self, api):
        """PRD: "it is version-guarded under §2.7: the request must carry
        `expected_form_version` equal to the form's current `version`, failing
        with `ERR_STALE_VERSION` on a mismatch."

        Design: Corner/cross_cutting_layers/occ_stale_form_version_returns_412
        """
        program = create_program()
        bp = create_locked_blueprint(program["id"], 1)
        form = create_form(program["id"], bp["id"])
        resp = api.assemble_test_form(form["id"], form["version"] + 99,
                                      ASSEMBLER_H)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_version_wins_over_blueprint_mismatch(self, api):
        """PRD: "it is version-guarded under §2.7: the request must carry
        `expected_form_version` equal to the form's current `version`, failing
        with `ERR_STALE_VERSION` on a mismatch. Assembly then validates, in
        order, that the form is `ASSEMBLING` (`ERR_FORM_NOT_ASSEMBLING`), that
        its blueprint is `LOCKED` (`ERR_BLUEPRINT_NOT_LOCKED`), that each
        section holds exactly its blueprinted number of slots
        (`ERR_BLUEPRINT_MISMATCH`, HTTP 422)"
        (The form has zero slots against a blueprint requiring one, so the
        mismatch also holds; the version guard is evaluated first.)

        Design: Difficulty/priority_pair_validation_conflict/stale_version_vs_blueprint_mismatch_priority
        """
        program = create_program()
        bp = create_locked_blueprint(program["id"], 1)
        form = create_form(program["id"], bp["id"])
        resp = api.assemble_test_form(form["id"], form["version"] + 7,
                                      ASSEMBLER_H)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_fresh_version_exposes_blueprint_mismatch(self, api):
        """PRD: "Assembly then validates, in order, that the form is
        `ASSEMBLING` (`ERR_FORM_NOT_ASSEMBLING`), that its blueprint is
        `LOCKED` (`ERR_BLUEPRINT_NOT_LOCKED`), that each section holds exactly
        its blueprinted number of slots (`ERR_BLUEPRINT_MISMATCH`, HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/stale_version_vs_blueprint_mismatch_priority
        """
        program = create_program()
        bp = create_locked_blueprint(program["id"], 2)
        form = create_form(program["id"], bp["id"])
        # One slot against a blueprint requiring two.
        standard = create_standard(program["id"])
        item = make_operational_items(program["id"], standard["id"], [30])[0]
        add_slot(program["id"], form["id"], item["id"])
        fresh = get_success_data(api.get_test_form(form["id"], ASSEMBLER_H))
        resp = api.assemble_test_form(form["id"], fresh["version"], ASSEMBLER_H)
        validate_error(resp, ApiErrorId.ERR_BLUEPRINT_MISMATCH)


class TestParallelStateDimensions:
    def test_assemble_advances_posture_but_not_lifecycle(self, api):
        """PRD: "A successful assembly stamps `assembled_at` from the program
        clock, moves the form `ASSEMBLING → ASSEMBLED`, increments the form's
        `version`, adds one to every slotted item's
        `operational_exposure_count`, and flips every slotted item whose
        posture was `SECURED` to `EXPOSED`"
        PRD: "A transition on one dimension never changes the other unless the
        transition's stated effects say so."

        Design: Difficulty/non_linear_state_machine/item_parallel_dimensions_status_x_security_posture
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _one_operational_item(program, standard)
        assert item["status"] == "OPERATIONAL"
        assert item["security_posture"] == "SECURED"
        assert item["operational_exposure_count"] == 0
        form = build_assembled_form(program["id"], [item])
        assert form["status"] == "ASSEMBLED"
        after = read_item(program["id"], item["id"])
        assert after["status"] == "OPERATIONAL", "lifecycle status unchanged"
        assert after["security_posture"] == "EXPOSED", (
            "posture advances SECURED -> EXPOSED on first assembly"
        )
        assert after["operational_exposure_count"] == 1

    def test_review_transitions_leave_posture_untouched(self, api):
        """PRD: "A transition on one dimension never changes the other unless
        the transition's stated effects say so."
        PRD: "Submitting an item moves it from `DRAFT` to `SUBMITTED`, from
        which the system immediately and automatically promotes it to
        `CONTENT_REVIEW`."

        Design: Difficulty/non_linear_state_machine/item_parallel_dimensions_status_x_security_posture
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-PD")
        submitted = submit_item(item)
        assert submitted["status"] == "CONTENT_REVIEW"
        assert submitted["security_posture"] == "UNSECURED", (
            "the lifecycle advanced while the posture dimension stayed put"
        )


class TestDokSectionBalance:
    def _setup_dok_form(self, api, dok, dok_min, dok_max):
        """One OPERATIONAL item whose standard carries `dok`; blueprint with
        one section of item_count 1 bounded by [dok_min, dok_max]."""
        program = create_program()
        standard = create_standard(program["id"], depth_of_knowledge=dok)
        item = _one_operational_item(program, standard)
        bp = create_locked_blueprint(program["id"], 1, dok_min=dok_min,
                                     dok_max=dok_max)
        form = create_form(program["id"], bp["id"])
        add_slot(program["id"], form["id"], item["id"])
        return program, form

    def test_dok_section_boundary_inclusive(self, api):
        """PRD: "the sum of the slotted items' `depth_of_knowledge` ratings —
        each looked up through the item's `primary_standard_id` to its
        standard — must lie between the section's `dok_min` and `dok_max`
        inclusive on both ends"
        (dok_sum == dok_min == dok_max == 2 satisfies the constraint.)

        Design: Corner/calculations/dok_section_boundary_inclusive
        """
        _program, form = self._setup_dok_form(api, dok=2, dok_min=2, dok_max=2)
        assembled = assemble_form(form["id"])
        assert assembled["status"] == "ASSEMBLED", (
            "sum exactly equal to both bounds passes (inclusive)"
        )

    def test_dok_section_outside_range_rejected(self, api):
        """PRD: "must lie between the section's `dok_min` and `dok_max`
        inclusive on both ends, failing with `ERR_DOK_OUT_OF_RANGE` (HTTP 422)
        when even one section falls outside."

        Design: Corner/calculations/dok_section_boundary_inclusive
        """
        _program, form = self._setup_dok_form(api, dok=3, dok_min=1, dok_max=2)
        fresh = get_success_data(api.get_test_form(form["id"], ASSEMBLER_H))
        resp = api.assemble_test_form(form["id"], fresh["version"], ASSEMBLER_H)
        validate_error(resp, ApiErrorId.ERR_DOK_OUT_OF_RANGE)


class TestSlots:
    def test_form_slots_delete_returns_204(self, api):
        """PRD: "Slot removal is the sole deletion and returns `204 No
        Content` with no resource payload."
        PRD: "Every slot addition and every slot removal increments the parent
        form's `version`; removal returns no resource payload."

        Design: Corner/endpoints/form_slots_delete_returns_204
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _one_operational_item(program, standard)
        bp = create_locked_blueprint(program["id"], 1)
        form = create_form(program["id"], bp["id"])
        slot = add_slot(program["id"], form["id"], item["id"])
        assert_form_item_slot(slot)
        assert slot["points_possible"] == item["max_score_points"], (
            "points_possible is copied from the item at slot creation"
        )
        before = get_success_data(api.get_test_form(form["id"], ASSEMBLER_H))
        resp = api.delete_form_item_slot(slot["id"], ASSEMBLER_H)
        assert resp.status_code == 204, f"expected 204, got {resp.status_code}"
        validate_error(api.get_form_item_slot(slot["id"], ASSEMBLER_H),
                       ApiErrorId.ERR_NOT_FOUND)
        after = get_success_data(api.get_test_form(form["id"], ASSEMBLER_H))
        assert after["version"] == before["version"] + 1, (
            "removal increments the parent form's version"
        )


class TestExposureCapBoundary:
    def _setup_item_at_count(self, api, cap, assemblies):
        """OPERATIONAL item already assembled onto `assemblies` forms."""
        program = create_program()
        standard = create_standard(program["id"])
        item = _one_operational_item(program, standard, cap=cap)
        bp = create_locked_blueprint(program["id"], 1)
        for _ in range(assemblies):
            form = create_form(program["id"], bp["id"])
            add_slot(program["id"], form["id"], item["id"])
            assemble_form(form["id"])
        return program, bp, read_item(program["id"], item["id"])

    def test_exposure_cap_exactly_at_limit_succeeds_then_retires(self, api):
        """PRD: "the exposure guard runs: assembly increments each slotted
        item's `operational_exposure_count` by one, and if any item's
        resulting count would exceed its `exposure_cap`, the entire assembly
        rolls back"
        PRD: "the moment an item's `operational_exposure_count` reaches its
        `exposure_cap` through slot creation, the system retires it
        automatically with `retirement_reason` `OVER_EXPOSED`, the same
        timestamp and posture effects"
        (count 2 + 1 == cap 3: the assembly succeeds and the item retires.)

        Design: Difficulty/boundary_precision_check/exposure_cap_exactly_at_limit_succeeds_then_blocks
        """
        program, bp, item = self._setup_item_at_count(api, cap=3, assemblies=2)
        assert item["operational_exposure_count"] == 2
        form = create_form(program["id"], bp["id"])
        add_slot(program["id"], form["id"], item["id"])
        assembled = assemble_form(form["id"])
        assert assembled["status"] == "ASSEMBLED", "count+1 == cap passes"
        after = read_item(program["id"], item["id"])
        assert after["status"] == "RETIRED"
        assert after["retirement_reason"] == "OVER_EXPOSED"
        assert after["security_posture"] == "UNSECURED"
        clock = get_success_data(api.get_assessment_program(program["id"],
                                                            ASSEMBLER_H))
        assert after["retired_at"] == clock["current_period_utc"], (
            "retired_at is stamped from the program clock"
        )

    def test_retired_item_cannot_be_slotted_again(self, api):
        """PRD: "is rejected with `ERR_SLOT_ITEM_INVALID` (HTTP 409) unless the
        item is `OPERATIONAL` with a `security_posture` of `SECURED` or
        `EXPOSED` and does not already appear on the same form"
        (Once the cap-triggered retirement fires, the item is no longer
        OPERATIONAL, so any further slot addition is rejected.)

        Design: Difficulty/boundary_precision_check/exposure_cap_exactly_at_limit_succeeds_then_blocks
        """
        program, bp, item = self._setup_item_at_count(api, cap=3, assemblies=2)
        form = create_form(program["id"], bp["id"])
        add_slot(program["id"], form["id"], item["id"])
        assemble_form(form["id"])  # reaches cap -> item auto-retires
        form2 = create_form(program["id"], bp["id"])
        resp = api.add_form_item_slot(
            form2["id"], create_slot_payload(item["id"], 0, 1), ASSEMBLER_H)
        validate_error(resp, ApiErrorId.ERR_SLOT_ITEM_INVALID)


class TestForcedReworkCycle:
    def _setup_assembled_with_item(self, api):
        program = create_program()
        standard = create_standard(program["id"])
        item = _one_operational_item(program, standard)
        form = build_assembled_form(program["id"], [item])
        return program, standard, item, form

    def test_mark_compromised_forces_rework_and_deletes_slot(self, api):
        """PRD: "every slot referencing the item on a non-archived form is
        deleted; each affected form in `ASSEMBLED` or `EQUATED` is forced back
        into `ASSEMBLING` for rework"
        PRD: "the compromised item's own `operational_exposure_count` is reset
        to zero."

        Design: Difficulty/non_linear_state_machine/testform_forced_rework_cycle
        """
        program, _standard, item, form = self._setup_assembled_with_item(api)
        marked = get_success_data(mark_compromised(program["id"], item["id"]))
        assert marked["security_posture"] == "COMPROMISED"
        form_after = get_success_data(api.get_test_form(form["id"], ASSEMBLER_H))
        assert form_after["status"] == "ASSEMBLING", (
            "ASSEMBLED -> ASSEMBLING forced rework"
        )
        slots = list_slots(form["id"])
        assert [s["item_id"] for s in slots] == [], "the slot is deleted"

    def test_form_can_be_reassembled_after_rework(self, api):
        """PRD: "each affected form in `ASSEMBLED` or `EQUATED` is forced back
        into `ASSEMBLING` for rework"
        PRD: "Assembly then validates, in order, that the form is
        `ASSEMBLING` (`ERR_FORM_NOT_ASSEMBLING`)"
        (A replacement slot restores blueprint satisfaction, so the reworked
        form assembles again — closing the ASSEMBLING -> ASSEMBLED ->
        ASSEMBLING -> ASSEMBLED cycle.)

        Design: Difficulty/non_linear_state_machine/testform_forced_rework_cycle
        """
        program, standard, item, form = self._setup_assembled_with_item(api)
        get_success_data(mark_compromised(program["id"], item["id"]))
        replacement = _one_operational_item(program, standard)
        add_slot(program["id"], form["id"], replacement["id"])
        reassembled = assemble_form(form["id"])
        assert reassembled["status"] == "ASSEMBLED", (
            "the reworked form assembles again with a replacement slot"
        )


class TestMarkCompromisedCascade:
    def _setup_cascade(self, api):
        """F1 (ASSEMBLED) carries I-C + I-D; target form (EQUATED) carries
        I-C + 3 anchors; a link from the source form targets the EQUATED
        form. All five items share one field-test window."""
        program = create_program()
        standard = create_standard(program["id"])
        items = make_operational_items(
            program["id"], standard["id"], [30, 30, 25, 30, 35],
            exposure_cap=10)
        item_c, item_d = items[0], items[1]
        anchors = items[2:]
        anchor_ids = [a["id"] for a in anchors]
        f1 = build_assembled_form(program["id"], [item_c, item_d])
        src = build_assembled_form(program["id"], anchors, anchor_ids=anchor_ids)
        f2 = build_assembled_form(program["id"], anchors + [item_c],
                                  anchor_ids=anchor_ids)
        link = get_success_data(api.create_equating_link(
            create_equating_link_payload(program["id"], src["id"], f2["id"],
                                         anchor_ids),
            PSYCH_H,
        ))
        f2 = get_success_data(api.get_test_form(f2["id"], ASSEMBLER_H))
        assert f2["status"] == "EQUATED", "setup: link equates the target form"
        return program, item_c, item_d, f1, f2, link, anchors

    def test_mark_compromised_full_cascade(self, api):
        """PRD: "The compromise cascade is severe: every slot referencing the
        item on a non-archived form is deleted; each affected form in
        `ASSEMBLED` or `EQUATED` is forced back into `ASSEMBLING` for rework,
        and a forced-back `EQUATED` form additionally loses every equating
        link that targeted it; the remaining slotted items on each reworked
        form have their `operational_exposure_count` decremented as
        compensation; and the compromised item's own
        `operational_exposure_count` is reset to zero."

        Design: Difficulty/transitive_cascade/mark_compromised_full_cascade
        """
        program, item_c, _d, f1, f2, link, _anchors = self._setup_cascade(api)
        assert read_item(program["id"], item_c["id"])[
            "operational_exposure_count"] == 2
        get_success_data(mark_compromised(program["id"], item_c["id"]))
        after_c = read_item(program["id"], item_c["id"])
        assert after_c["security_posture"] == "COMPROMISED"
        assert after_c["operational_exposure_count"] == 0
        f1_after = get_success_data(api.get_test_form(f1["id"], ASSEMBLER_H))
        f2_after = get_success_data(api.get_test_form(f2["id"], ASSEMBLER_H))
        assert f1_after["status"] == "ASSEMBLING", "ASSEMBLED -> ASSEMBLING"
        assert f2_after["status"] == "ASSEMBLING", "EQUATED -> ASSEMBLING"
        validate_error(api.get_equating_link(link["id"], PSYCH_H),
                       ApiErrorId.ERR_NOT_FOUND)

    def test_cascade_decrements_co_slotted_items(self, api):
        """PRD: "the remaining slotted items on each reworked form have their
        `operational_exposure_count` decremented as compensation"

        Design: Difficulty/transitive_cascade/mark_compromised_full_cascade
        """
        program, item_c, item_d, f1, _f2, _link, anchors = self._setup_cascade(api)
        get_success_data(mark_compromised(program["id"], item_c["id"]))
        d_after = read_item(program["id"], item_d["id"])
        assert d_after["operational_exposure_count"] == 0, (
            "co-slotted item on the reworked form is decremented 1 -> 0"
        )
        anchor_after = read_item(program["id"], anchors[0]["id"])
        assert anchor_after["operational_exposure_count"] == 1, (
            "anchor on both forms loses only the reworked form's count"
        )
        remaining = {s["item_id"] for s in list_slots(f1["id"])}
        assert remaining == {item_d["id"]}, (
            "only the compromised item's slot is deleted"
        )


class TestExposureCompensatingInvariant:
    def _setup_counts_5_3_2(self, api):
        """Item A on 5 assembled forms, B on 3, C on 2; one shared form F
        carries all three. Mirrors the conserved-quantity scenario."""
        program = create_program()
        standard = create_standard(program["id"])
        item_a, item_b, item_c = make_operational_items(
            program["id"], standard["id"], [30, 30, 30], exposure_cap=10)
        bp1 = create_locked_blueprint(program["id"], 1)
        bp3 = create_locked_blueprint(program["id"], 3)
        for _ in range(4):
            f = create_form(program["id"], bp1["id"])
            add_slot(program["id"], f["id"], item_a["id"])
            assemble_form(f["id"])
        for _ in range(2):
            f = create_form(program["id"], bp1["id"])
            add_slot(program["id"], f["id"], item_b["id"])
            assemble_form(f["id"])
        f = create_form(program["id"], bp1["id"])
        add_slot(program["id"], f["id"], item_c["id"])
        assemble_form(f["id"])
        shared = create_form(program["id"], bp3["id"])
        for pos, it in enumerate((item_a, item_b, item_c), start=1):
            add_slot(program["id"], shared["id"], it["id"],
                     position_in_section=pos)
        shared = assemble_form(shared["id"])
        return program, item_a, item_b, item_c, shared

    def test_exposure_count_invariant_on_forced_rework(self, api):
        """PRD: "the remaining slotted items on each reworked form have their
        `operational_exposure_count` decremented as compensation; and the
        compromised item's own `operational_exposure_count` is reset to zero."
        PRD: "Exposure accounting is a strict invariant:
        `operational_exposure_count` equals the number of slots referencing
        the item across forms in `ASSEMBLED`, `EQUATED`, or `PUBLISHED`
        status, it is never decremented below zero, and every forced-rework
        compensation subtracts exactly the count of deleted slots so the
        metric stays consistent."

        Design: Difficulty/compensating_invariant/exposure_count_invariant_on_forced_rework
        """
        program, item_a, item_b, item_c, _shared = self._setup_counts_5_3_2(api)
        assert read_item(program["id"], item_a["id"])["operational_exposure_count"] == 5
        assert read_item(program["id"], item_b["id"])["operational_exposure_count"] == 3
        assert read_item(program["id"], item_c["id"])["operational_exposure_count"] == 2
        get_success_data(mark_compromised(program["id"], item_b["id"]))
        a_after = read_item(program["id"], item_a["id"])["operational_exposure_count"]
        b_after = read_item(program["id"], item_b["id"])["operational_exposure_count"]
        c_after = read_item(program["id"], item_c["id"])["operational_exposure_count"]
        assert a_after == 4, "A shares exactly one reworked form with B"
        assert b_after == 0, "the compromised item resets to zero"
        assert c_after == 1, "C shares exactly one reworked form with B"

    def test_exposure_total_conserved_across_compensation(self, api):
        """PRD: "Exposure accounting is a strict invariant:
        `operational_exposure_count` equals the number of slots referencing
        the item across forms in `ASSEMBLED`, `EQUATED`, or `PUBLISHED`
        status, it is never decremented below zero, and every forced-rework
        compensation subtracts exactly the count of deleted slots so the
        metric stays consistent."

        Design: Difficulty/compensating_invariant/exposure_count_invariant_on_forced_rework
        """
        program, item_a, item_b, item_c, _shared = self._setup_counts_5_3_2(api)
        before = sum(read_item(program["id"], it["id"])[
            "operational_exposure_count"] for it in (item_a, item_b, item_c))
        assert before == 10
        get_success_data(mark_compromised(program["id"], item_b["id"]))
        after = sum(read_item(program["id"], it["id"])[
            "operational_exposure_count"] for it in (item_a, item_b, item_c))
        # 10 - 5 == 3 (B's reset) + 1 (A's compensation) + 1 (C's compensation)
        assert after == 5
        assert before - after == 3 + 1 + 1
