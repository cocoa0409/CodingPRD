"""Declared initial states, audit stamps, terminal lockdown and stage routing."""

import pytest

from test_helpers import (
    ApiErrorId,
    STAGE_PLAN,
    all_elements_passing,
    api_client,
    asset_with_obsolete_predecessor,
    brand,
    brief_decision_payload,
    coord,
    create_printer_proof_payload,
    decide_brief,
    decide_task,
    current_route,
    element_check_by_code,
    element_checks_for,
    in_review_version,
    legal,
    make_headers,
    new_asset,
    new_brief,
    new_claim,
    new_printer,
    new_runout,
    new_version,
    printer_as,
    proofs_for_version,
    read_asset,
    read_brief,
    read_route,
    read_task,
    read_version,
    regulatory,
    routes_for,
    set_clock,
    submit,
    tasks_by_discipline,
    validate_error,
    validate_success,
    verified_version,
    verify,
    waiver_payload,
)


class TestDeclaredInitialStates:
    """Five entities, five different postures on the very first write."""

    def test_a_new_vendor_starts_in_the_good_state_and_not_a_neutral_one(self):
        """Four rows start pending or draft; the vendor starts fully certified.

        PRD §3.9: "A new vendor is created `CERTIFIED`, with a `performance_score`
        of 100.0 that is constrained to remain between 0.0 and 100.0 inclusive, a
        `recovery_balance_cents` of 0, an `escape_count` of 0 and a `version` of 1."

        Design: Corner/state_machines/fresh_rows_start_in_their_declared_initial_states
        """
        brief = new_brief()
        claim = new_claim()
        asset = new_asset(brief["id"])
        version = new_version(asset)
        printer = new_printer()

        assert brief["status"] == "DRAFT"
        assert brief["approved_at"] is None

        assert claim["legal_status"] == "DRAFT"
        assert claim["cleared_from_utc"] is None
        assert claim["cleared_until_utc"] is None
        assert claim["usage_count"] == 0

        assert asset["obsolescence_state"] == "ACTIVE"
        assert asset["version_counter"] == 0
        assert asset["current_approved_version_id"] is None

        assert version["state"] == "DRAFT"
        assert version["check_run_no"] == 0
        assert version["revision_cycle_count"] == 0

        assert printer["certification_status"] == "CERTIFIED"
        assert printer["performance_score"] == pytest.approx(100.0, abs=0.01)
        assert printer["recovery_balance_cents"] == 0
        assert printer["escape_count"] == 0
        assert printer["version"] == 1


class TestBriefDecisionAuditTrail:
    """One endpoint, two outcomes, one audit trio that both must record."""

    def test_the_rejecting_reviewer_is_recorded_as_carefully_as_the_approving_one(self):
        """Both decisions stamp the decider, the clock and the note.

        PRD §3.1: "Either outcome records `approved_by_user_id` as the deciding
        `X-User-ID` and `approved_at` as the current logical-clock instant, stores the
        `review_note`, refreshes `updated_at` and increments the brief's `version` by
        1."

        Design: Corner/state_machines/brief_decision_records_the_reviewer_and_the_clock_on_both_outcomes
        """
        brief_ok = new_brief()
        brief_no = new_brief(
            sku_code="SKU-1002", product_name="Northgate Cocoa Carton 500g"
        )
        set_clock("2026-08-04T10:30:00Z")

        approved = decide_brief(
            brief_ok["id"], "APPROVED", review_note="Scheme and net contents confirmed."
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u_reg"
        assert approved["approved_at"].startswith("2026-08-04T10:30:00")
        assert approved["review_note"] == "Scheme and net contents confirmed."

        rejected = decide_brief(
            brief_no["id"],
            "REJECTED",
            review_note="Structural spec contradicts the filed dieline.",
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["approved_by_user_id"] == "u_reg"
        assert rejected["approved_at"].startswith("2026-08-04T10:30:00")
        assert rejected["review_note"] == "Structural spec contradicts the filed dieline."

        assert approved["created_at"].startswith("2026-08-01T00:00:00")
        assert approved["updated_at"].startswith("2026-08-04T10:30:00")
        assert approved["version"] == 2
        assert rejected["version"] == 2


class TestRejectedBriefIsTerminal:
    """The endpoint that produced the terminal state must also close behind it."""

    def test_neither_an_edit_nor_a_second_decision_can_reopen_a_rejected_brief(self):
        """Re-firing the decision handler must not resurrect the brief into approved.

        PRD §3.1: "Once the brief has left `DRAFT` no edit is possible and the
        attempt is refused with `ERR_BRIEF_STATE_INVALID`."

        Design: Corner/state_machines/rejected_brief_is_terminal_for_both_edits_and_further_decisions
        """
        brief = new_brief()
        rejected = decide_brief(
            brief["id"], "REJECTED", review_note="Dieline mismatch."
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["version"] == 2

        edit = api_client.patch_brief(
            brief["id"], {"product_name": "Renamed After Rejection"}, coord()
        )
        validate_error(edit, ApiErrorId.ERR_BRIEF_STATE_INVALID.value, 409)

        second = api_client.decide_brief(
            brief["id"],
            brief_decision_payload(
                "APPROVED", review_note="Reversing the earlier rejection."
            ),
            regulatory(),
        )
        validate_error(second, ApiErrorId.ERR_BRIEF_STATE_INVALID.value, 409)

        after = read_brief(brief["id"])
        assert after["status"] == "REJECTED"
        assert after["product_name"] == "Northgate Cocoa Carton 340g"
        assert after["review_note"] == "Dieline mismatch."
        assert after["version"] == 2


class TestWaiverPrecondition:
    """A waiver halves a deduction; it never clears one, and never touches a pass."""

    def _one_failing_major_element(self):
        _brief, _asset, version = verified_version(
            mandatory_elements=all_elements_passing(
                date_code_zone={"zone_mm2": 120, "position": "BACK_PANEL_LOWER_RIGHT"}
            )
        )
        assert version["check_run_no"] == 1
        assert version["failed_element_count"] == 1
        assert version["waived_element_count"] == 0
        assert version["compliance_score"] == pytest.approx(90.0, abs=0.01)
        return version

    def test_the_waiver_is_refused_on_a_passing_row_and_halves_the_failing_one(self):
        """10.0 deduction points become 5.0, so the score reads 95.0 and not 100.0.

        PRD §3.4: "A successful waiver moves the row's `result` from `FAIL` to
        `WAIVED`, records `waived_by_user_id` as the waiving `X-User-ID` and stores the
        `waiver_justification`, halves the row's `deduction_points` to half the severity
        weight, and then recomputes the owning version's `compliance_score`,
        `failed_element_count` and `waived_element_count` through the same four-input
        arithmetic described above."

        Design: Corner/state_machines/waiver_requires_a_failed_verdict_and_only_halves_its_deduction
        """
        version = self._one_failing_major_element()
        passing = element_check_by_code(version["id"], "NET_CONTENTS")
        failing = element_check_by_code(version["id"], "DATE_CODE_ZONE")
        assert passing["result"] == "PASS"
        assert failing["result"] == "FAIL"
        assert failing["severity"] == "MAJOR"
        assert failing["deduction_points"] == pytest.approx(10.0, abs=0.01)

        refused = api_client.waive_element_check(
            passing["id"],
            waiver_payload(waiver_justification="Waiving a verdict that never failed."),
            regulatory(),
        )
        validate_error(refused, ApiErrorId.ERR_ELEMENT_CHECK_NOT_FAILED.value, 409)
        assert element_check_by_code(version["id"], "NET_CONTENTS")["result"] == "PASS"
        assert element_check_by_code(version["id"], "NET_CONTENTS")[
            "deduction_points"
        ] == pytest.approx(0.0, abs=0.01)

        row = validate_success(
            api_client.waive_element_check(
                failing["id"],
                waiver_payload(
                    waiver_justification=(
                        "Date code prints inside the varnish-free window on this"
                        " dieline."
                    )
                ),
                regulatory(),
            ),
            200,
        )
        assert row["result"] == "WAIVED"
        assert row["deduction_points"] == pytest.approx(5.0, abs=0.01)
        assert row["waived_by_user_id"] == "u_reg"
        assert row["waiver_justification"]

        after = read_version(version["id"])
        assert after["failed_element_count"] == 0
        assert after["waived_element_count"] == 1
        assert after["compliance_score"] == pytest.approx(95.0, abs=0.01)
        assert after["check_run_no"] == 1

        rows = element_checks_for(version["id"])
        passing_rows = [row for row in rows if row["result"] == "PASS"]
        assert len(passing_rows) == 6
        for row in passing_rows:
            assert row["deduction_points"] == pytest.approx(0.0, abs=0.01)


class TestSubmitMaterialisesTheFrozenRoute:
    """One call has to produce a pass, its plan and four tasks."""

    def test_only_the_two_stage_one_tasks_are_activated(self):
        """The plan is frozen at creation and all four tasks exist immediately.

        PRD §3.5: "Four review tasks are created from that plan — one per discipline
        — each stamped with its `discipline`, its `mode` and its `stage_no`, each
        starting with `decision` `PENDING`, and each with `is_active` false except the
        two stage-1 tasks, which are activated as the pass immediately moves `PENDING →
        IN_PROGRESS` inside the very same request."

        Design: Corner/state_machines/submit_materialises_the_frozen_three_stage_route_and_opens_stage_one
        """
        _brief, _asset, version = verified_version()

        submitted = submit(
            version["id"],
            submit_note="Route through brand, regulatory, legal and quality.",
        )
        assert submitted["state"] == "IN_REVIEW"
        assert submitted["route_count"] == 1

        routes = routes_for(version["id"])
        assert len(routes) == 1
        route = routes[0]
        assert route["status"] == "IN_PROGRESS"
        assert route["route_no"] == 1
        assert route["current_stage_no"] == 1
        assert route["conditional_count"] == 0
        assert route["completed_at"] is None

        plan = route["stage_plan"]
        assert len(plan) == 3
        for index, stage in enumerate(plan):
            assert stage["stage_no"] == index + 1
            assert stage["mode"] == STAGE_PLAN[index]["mode"]
            assert stage["disciplines"] == STAGE_PLAN[index]["disciplines"]

        tasks = tasks_by_discipline(route["id"])
        assert len(tasks) == 4
        assert all(task["decision"] == "PENDING" for task in tasks.values())

        assert tasks["BRAND"]["stage_no"] == 1
        assert tasks["BRAND"]["mode"] == "PARALLEL"
        assert tasks["BRAND"]["is_active"] is True
        assert tasks["REGULATORY"]["stage_no"] == 1
        assert tasks["REGULATORY"]["mode"] == "PARALLEL"
        assert tasks["REGULATORY"]["is_active"] is True
        assert tasks["LEGAL"]["stage_no"] == 2
        assert tasks["LEGAL"]["mode"] == "SEQUENTIAL"
        assert tasks["LEGAL"]["is_active"] is False
        assert tasks["QUALITY"]["stage_no"] == 3
        assert tasks["QUALITY"]["mode"] == "SEQUENTIAL"
        assert tasks["QUALITY"]["is_active"] is False

        after = read_version(version["id"])
        assert after["check_run_no"] == 1
        assert after["compliance_score"] == pytest.approx(100.0, abs=0.01)


class TestAdmissibleTriggersAreKeyedOnOperationAndState:
    """A walk that fires, at each stop, the triggers that stop does not list."""

    def test_six_out_of_state_triggers_are_refused_while_the_two_advances_succeed(self):
        """Revise and release are wrong in DRAFT; a proof is wrong once verified.

        PRD §5: "`ERR_VERSION_STATE_INVALID` | 409"

        Design: Corner/state_machines/every_trigger_absent_from_the_current_state_row_is_refused_along_the_draft_to_in_review_walk
        """
        brief = read_brief(new_brief()["id"])
        decide_brief(brief["id"], "APPROVED")
        asset = new_asset(brief["id"])
        printer = new_printer()
        version = new_version(asset)
        assert version["state"] == "DRAFT"
        assert version["check_run_no"] == 0

        validate_error(
            api_client.revise_artwork_version(
                version["id"], {"revise_note": "Re-open for edit."}, coord()
            ),
            ApiErrorId.ERR_VERSION_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.release_to_print(
                version["id"], {"release_note": "Released against the proof."}, coord()
            ),
            ApiErrorId.ERR_VERSION_STATE_INVALID.value,
            409,
        )

        verified = verify(version["id"])
        assert verified["state"] == "ELEMENTS_VERIFIED"
        assert verified["check_run_no"] == 1

        validate_error(
            api_client.revise_artwork_version(
                version["id"], {"revise_note": "Re-open for edit."}, coord()
            ),
            ApiErrorId.ERR_VERSION_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.create_printer_proof(
                create_printer_proof_payload(version["id"], printer["id"]),
                printer_as(printer),
            ),
            ApiErrorId.ERR_VERSION_STATE_INVALID.value,
            409,
        )
        assert proofs_for_version(version["id"]) == []

        submitted = submit(version["id"])
        assert submitted["state"] == "IN_REVIEW"
        assert submitted["route_count"] == 1

        validate_error(
            api_client.patch_artwork_version(
                version["id"],
                {
                    "change_description": "Editing while the route is open.",
                    "mandatory_elements": all_elements_passing(),
                },
                coord(),
            ),
            ApiErrorId.ERR_VERSION_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.submit_artwork_version(
                version["id"], {"submit_note": "Second attempt."}, coord()
            ),
            ApiErrorId.ERR_VERSION_STATE_INVALID.value,
            409,
        )

        final = read_version(version["id"])
        assert final["state"] == "IN_REVIEW"
        assert final["route_count"] == 1
        assert final["revision_cycle_count"] == 0
        assert final["change_description"] == (
            "First production artwork for the Northgate cocoa carton."
        )
        assert len(routes_for(version["id"])) == 1


class TestRepeatedTaskDecision:
    """The same repeat call yields two different refusals depending on who fires it."""

    def _decided_brand_task(self):
        _brief, _asset, version = in_review_version()
        route = current_route(version["id"])
        tasks = tasks_by_discipline(route["id"])
        first = decide_task(tasks["BRAND"], "APPROVED")
        assert first["decision"] == "APPROVED"
        assert first["decided_by_user_id"] == "u_brand"
        assert first["decided_at"].startswith("2026-08-01T00:00:00")
        return version, route, tasks

    def test_the_original_decider_trips_segregation_before_already_decided(self):
        """A second brand reviewer clears segregation and lands on the later rule.

        PRD §3.5: "Finally, segregation of duties: the deciding `X-User-ID` may be
        neither the routed version's `author_user_id` nor an identifier already recorded
        as `decided_by_user_id` on any other task of the same pass, and either violation
        is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/second_decision_on_a_decided_task_is_refused_and_priority_16_outranks_priority_28
        """
        version, route, tasks = self._decided_brand_task()

        # PRD §3.5 scopes the segregation check to "an identifier already recorded as
        # `decided_by_user_id` on **any other task** of the same pass", so the original
        # decider re-firing the very same task is not a segregation violation and the
        # already-decided precondition is the operative refusal for both callers.
        other_user = api_client.decide_review_task(
            tasks["BRAND"]["id"],
            {"decision": "APPROVED"},
            make_headers("u_brand2", "BrandReviewer"),
        )
        validate_error(other_user, ApiErrorId.ERR_TASK_ALREADY_DECIDED.value, 409)

        same_user = api_client.decide_review_task(
            tasks["BRAND"]["id"], {"decision": "APPROVED"}, brand()
        )
        validate_error(same_user, ApiErrorId.ERR_TASK_ALREADY_DECIDED.value, 409)

        after = read_task(tasks["BRAND"]["id"])
        assert after["decision"] == "APPROVED"
        assert after["decided_by_user_id"] == "u_brand"
        assert after["version"] == 2

        still_open = read_route(route["id"])
        assert still_open["status"] == "IN_PROGRESS"
        assert still_open["current_stage_no"] == 1
        assert read_version(version["id"])["state"] == "IN_REVIEW"


class TestParallelStageMustFullyLand:
    """A parallel stage resolves only when every sibling has a verdict."""

    def test_one_of_two_parallel_siblings_does_not_open_stage_two(self):
        """The middle probe is the discriminator: half a stage is not a stage.

        PRD §3.5: "Otherwise, if every task in the stage carries either `APPROVED` or
        `CONDITIONAL` — a conditional decision counts as approving for this purpose,
        which is precisely why a stage can resolve approved while conditions remain open
        — the stage verdict is `APPROVED`."

        Design: Corner/state_machines/stage_two_task_is_undecidable_until_both_parallel_stage_one_tasks_land
        """
        _brief, _asset, version = in_review_version()
        route = current_route(version["id"])
        tasks = tasks_by_discipline(route["id"])
        legal_decision = {"decision": "APPROVED"}

        too_early = api_client.decide_review_task(
            tasks["LEGAL"]["id"], legal_decision, legal()
        )
        validate_error(too_early, ApiErrorId.ERR_ROUTE_STAGE_NOT_ACTIVE.value, 409)

        assert decide_task(tasks["BRAND"], "APPROVED")["decision"] == "APPROVED"

        still_early = api_client.decide_review_task(
            tasks["LEGAL"]["id"], legal_decision, legal()
        )
        validate_error(still_early, ApiErrorId.ERR_ROUTE_STAGE_NOT_ACTIVE.value, 409)

        assert decide_task(tasks["REGULATORY"], "APPROVED")["decision"] == "APPROVED"
        advanced = read_route(route["id"])
        assert advanced["status"] == "IN_PROGRESS"
        assert advanced["current_stage_no"] == 2

        assert read_task(tasks["LEGAL"]["id"])["is_active"] is True
        assert read_task(tasks["QUALITY"]["id"])["is_active"] is False
        assert read_task(tasks["QUALITY"]["id"])["decision"] == "PENDING"

        legal_row = decide_task(tasks["LEGAL"], "APPROVED")
        assert legal_row["decision"] == "APPROVED"
        assert read_route(route["id"])["current_stage_no"] == 3
        assert read_task(tasks["QUALITY"]["id"])["is_active"] is True

        after = read_version(version["id"])
        assert after["state"] == "IN_REVIEW"
        assert after["approved_at"] is None


class TestRejectionSkipsEverySibling:
    """One rejection has to reach the never-activated later stages too."""

    def test_the_inactive_stage_two_and_stage_three_tasks_are_skipped_as_well(self):
        """Skipped rows stay unattributed, and the version drops one revision cycle.

        PRD §3.5: "A stage verdict of `REJECTED` — at any stage — moves the pass
        `IN_PROGRESS → COMPLETE_REJECTED`, stamps `completed_at`, and moves every
        still-`PENDING` task of the pass, in all three stages including the inactive
        later ones, `PENDING → SKIPPED` with `is_active` set false and
        `decided_by_user_id` left null."

        Design: Corner/state_machines/one_rejection_skips_every_pending_sibling_in_all_three_stages
        """
        _brief, asset, version = in_review_version()
        route = current_route(version["id"])
        tasks = tasks_by_discipline(route["id"])
        set_clock("2026-08-05T09:00:00Z")

        rejected = decide_task(
            tasks["REGULATORY"],
            "REJECTED",
            comment="Allergen statement omits the tree-nut cross-contact advisory.",
        )
        assert rejected["decision"] == "REJECTED"
        assert rejected["decided_at"].startswith("2026-08-05T09:00:00")

        closed = read_route(route["id"])
        assert closed["status"] == "COMPLETE_REJECTED"
        assert closed["completed_at"].startswith("2026-08-05T09:00:00")
        assert closed["current_stage_no"] == 1
        assert closed["conditional_count"] == 0

        sibling = read_task(tasks["BRAND"]["id"])
        assert sibling["decision"] == "SKIPPED"
        assert sibling["decided_by_user_id"] is None
        assert sibling["decided_at"] is None

        for discipline in ("LEGAL", "QUALITY"):
            later = read_task(tasks[discipline]["id"])
            assert later["decision"] == "SKIPPED"
            assert later["is_active"] is False

        after = read_version(version["id"])
        assert after["state"] == "REVISION_REQUESTED"
        assert after["revision_cycle_count"] == 1
        assert after["route_count"] == 1
        assert after["approved_at"] is None
        assert after["pinned_claim_snapshot"] == []

        untouched = read_asset(asset["id"])
        assert untouched["current_approved_version_id"] is None
        assert untouched["obsolescence_state"] == "ACTIVE"


class TestZeroStockRunoutSettlesOnCreate:
    """Two pending states resolve on the way up from a single POST."""

    def test_the_create_call_completes_the_runout_and_the_whole_cascade(self):
        """Nothing to deplete, so both projections collapse onto the start date.

        PRD §3.8: "There is nothing to deplete, so the runout goes `PLANNED →
        RUNOUT_COMPLETE` inside that same request, with `actual_runout_date` set equal
        to `projected_runout_date`, `remaining_qty` 0, `units_scrapped` and
        `units_reworked` 0, `disposition` `RUNOUT` and all changeover money fields 0 —
        and the obsolescence cascade completes at once: the obsolete version moves
        `OBSOLETE_PENDING → OBSOLETE` and the owning asset moves `SUPERSEDE_PENDING →
        SUPERSEDED`."

        Design: Corner/state_machines/zero_stock_runout_completes_inside_its_create_call_and_settles_the_obsolescence_chain
        """
        _brief, asset, v1, v2 = asset_with_obsolete_predecessor()
        assert asset["obsolescence_state"] == "SUPERSEDE_PENDING"
        assert asset["current_approved_version_id"] == v2["id"]
        assert asset["version_counter"] == 2
        assert asset["obsolete_units_total"] == 0
        assert asset["changeover_cost_committed_cents"] == 0
        assert v1["state"] == "OBSOLETE_PENDING"
        assert v1["obsoleted_at"] is None

        set_clock("2026-08-10T00:00:00Z")
        runout = new_runout(
            asset,
            v1,
            on_hand_qty=0,
            weekly_usage_qty=2500,
            runout_start_utc="2026-08-10T00:00:00Z",
        )

        assert runout["state"] == "RUNOUT_COMPLETE"
        assert runout["disposition"] == "RUNOUT"
        assert runout["remaining_qty"] == 0
        assert runout["projected_runout_date"] == "2026-08-10"
        assert runout["actual_runout_date"] == "2026-08-10"
        assert runout["trailing_avg_usage_qty"] is None
        assert runout["depletion_records"] == []
        assert runout["units_scrapped"] == 0
        assert runout["units_reworked"] == 0
        assert runout["material_writeoff_cents"] == 0
        assert runout["relabel_cost_cents"] == 0
        assert runout["changeover_base_cents"] == 0
        assert runout["changeover_expedite_cents"] == 0
        assert runout["total_changeover_cost_cents"] == 0
        assert runout["reversal_count"] == 0

        obsolete = read_version(v1["id"])
        assert obsolete["state"] == "OBSOLETE"
        assert obsolete["obsoleted_at"].startswith("2026-08-10T00:00:00")

        settled = read_asset(asset["id"])
        assert settled["obsolescence_state"] == "SUPERSEDED"
        assert settled["current_approved_version_id"] == v2["id"]
        assert settled["obsolete_units_total"] == 0
        assert settled["changeover_cost_committed_cents"] == 0
        assert read_version(v2["id"])["state"] == "APPROVED"
