"""Dangling references on filters, and branch-conditional fields that write nothing."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    admin,
    api_client,
    append_depletion,
    asset_with_obsolete_predecessor,
    assign_root_cause,
    brand,
    coord,
    current_route,
    decide_task,
    depletion,
    disposition_runout,
    in_review_version,
    new_escape,
    new_printer,
    new_runout,
    raise_recovery_claim,
    read_asset,
    read_escape,
    read_route,
    read_runout,
    read_task,
    read_version,
    task_decision_payload,
    tasks_by_discipline,
    tasks_for_route,
    validate_error,
    validate_paginated,
)


class TestDanglingRouteAndTaskIdsAreNotFounds:
    """The route filter on the task list is an existence check, not a where clause."""

    def test_the_filtered_task_list_refuses_an_unknown_route(self):
        """An unknown route id is a 404 on the list as well as on the single read.

        PRD §2.5: "Nested and referenced resources are resolved strictly from left to
        right along the URL, and only afterwards from the request body."

        PRD §2.5: "a review route id, in the path or as a `review_route_id` filter,
        yields `ERR_REVIEW_ROUTE_NOT_FOUND`; a review task id yields
        `ERR_REVIEW_TASK_NOT_FOUND`"

        Design: Corner/errors/dangling_route_and_task_ids_are_404s_even_on_the_list_endpoints
        """
        _brief, _asset, version = in_review_version()
        route = current_route(version["id"])
        assert len(tasks_for_route(route["id"])) == 4

        validate_error(
            api_client.get_review_route(NON_EXISTENT_UUID, coord()),
            ApiErrorId.ERR_REVIEW_ROUTE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.list_review_tasks(
                coord(), params={"review_route_id": NON_EXISTENT_UUID}
            ),
            ApiErrorId.ERR_REVIEW_ROUTE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.get_review_task(NON_EXISTENT_UUID, coord()),
            ApiErrorId.ERR_REVIEW_TASK_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.decide_review_task(
                NON_EXISTENT_UUID,
                task_decision_payload("APPROVED", comment="Brand identity approved."),
                brand(),
            ),
            ApiErrorId.ERR_REVIEW_TASK_NOT_FOUND.value,
            404,
        )

        live = read_route(route["id"])
        assert live["artwork_version_id"] == version["id"]
        assert live["route_no"] == 1
        assert live["status"] == "IN_PROGRESS"
        assert live["current_stage_no"] == 1
        assert live["conditional_count"] == 0
        assert len(live["stage_plan"]) == 3

        rows, meta = validate_paginated(
            api_client.list_review_tasks(
                coord(), params={"review_route_id": route["id"], "limit": 100}
            )
        )
        assert len(rows) == 4
        assert meta["total_count"] == 4
        assert [row["stage_no"] for row in rows] == [1, 1, 2, 3]
        assert {row["discipline"] for row in rows[:2]} == {"BRAND", "REGULATORY"}
        assert rows[2]["discipline"] == "LEGAL"
        assert rows[3]["discipline"] == "QUALITY"
        assert all(row["review_route_id"] == route["id"] for row in rows)


class TestDecisionPayloadsMissingTheirConditionalField:
    """Two conditionally required fields and one bad enum, all on the same task."""

    def test_three_bad_payloads_leave_the_task_completely_undecided(self):
        """A comment-less rejection, a bare conditional and a bad enum all write nothing.

        PRD §3.5: "A `REJECTED` decision requires a non-empty `comment` and a
        `CONDITIONAL` decision requires a non-empty `condition_code`; either omission is
        `ERR_INVALID_REQUEST`."

        PRD §2.8: "Before any business rule is consulted, every write request is checked
        against the shape its endpoint declares, and a single code covers every way that
        shape can be violated."

        Design: Corner/errors/decision_payloads_missing_their_conditional_field_are_400s_that_write_nothing
        """
        _brief, _asset, version = in_review_version()
        route = current_route(version["id"])
        task = tasks_by_discipline(route["id"])["BRAND"]

        before = read_task(task["id"])
        assert before["decision"] == "PENDING"
        assert before["comment"] is None
        assert before["condition_code"] is None
        assert before["decided_by_user_id"] is None
        assert before["decided_at"] is None
        assert before["is_active"] is True
        assert before["stage_no"] == 1
        assert before["mode"] == "PARALLEL"
        baseline = before["version"]

        validate_error(
            api_client.decide_review_task(
                task["id"], {"decision": "REJECTED"}, brand()
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api_client.decide_review_task(
                task["id"], {"decision": "CONDITIONAL"}, brand()
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api_client.decide_review_task(
                task["id"], {"decision": "MAYBE", "comment": "Undecided."}, brand()
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        untouched = read_task(task["id"])
        assert untouched["decision"] == "PENDING"
        assert untouched["comment"] is None
        assert untouched["condition_code"] is None
        assert untouched["decided_by_user_id"] is None
        assert untouched["decided_at"] is None
        assert untouched["is_active"] is True
        assert untouched["version"] == baseline
        assert read_route(route["id"])["status"] == "IN_PROGRESS"
        assert read_version(version["id"])["state"] == "IN_REVIEW"

        decided = decide_task(
            task,
            "REJECTED",
            comment="Logo lock-up clears the allergen panel; revise.",
        )
        assert decided["decision"] == "REJECTED"
        assert decided["comment"] == (
            "Logo lock-up clears the allergen panel; revise."
        )
        assert decided["decided_by_user_id"] == "u_brand"
        assert decided["decided_at"].startswith("2026-08-01T00:00:00")
        assert decided["version"] == baseline + 1
        assert read_route(route["id"])["status"] == "COMPLETE_REJECTED"
        assert read_version(version["id"])["state"] == "REVISION_REQUESTED"


class TestBranchConditionalFieldsAreRequiredOnlyOnTheirBranch:
    """A settlement needs three actuals; a scrap needs two unit counts; RUNOUT needs none."""

    def test_the_missing_branch_fields_are_four_hundreds_that_change_no_state(self):
        """Two short settlements and a bare scrap are refused; the RUNOUT branch succeeds.

        PRD §3.9: "A `SETTLED` resolution is admissible from `RECOVERY_CLAIMED` and
        requires all three actual invoice amounts — `actual_reprint_cost_cents`,
        `actual_scrap_cost_cents` and `actual_expedite_freight_cents` — to be present and
        zero or greater, any of them missing or negative being `ERR_INVALID_REQUEST`."

        PRD §3.8: "A `SCRAP` disposition writes off what is left and therefore requires
        both `units_scrapped` and `units_reworked` in the payload — omitting either is
        `ERR_INVALID_REQUEST` — and requires their sum to equal `remaining_qty`
        **exactly**, neither more nor less; any other sum is
        `ERR_UNIT_CONSERVATION_VIOLATION`."

        Design: Corner/errors/settlement_and_scrap_payloads_missing_their_branch_fields_are_400s_not_state_changes
        """
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        assert v1["state"] == "OBSOLETE_PENDING"
        printer = new_printer()

        escape = new_escape(
            v1["id"], printer, discovered_stage="DISTRIBUTION", units_affected=4000
        )
        assert escape["investigation_fee_cents"] == 150000
        assign_root_cause(escape["id"], "PRINTER", 1.00)
        claimed = raise_recovery_claim(escape["id"])
        # 168000 reprint + 28000 scrap + 0 freight + 150000 investigation at share 1.00.
        assert claimed["state"] == "RECOVERY_CLAIMED"
        assert claimed["provisional_recovery_cents"] == 346000

        runout = new_runout(asset, v1, on_hand_qty=5000, weekly_usage_qty=1000)
        assert runout["state"] == "PLANNED"
        assert runout["projected_runout_date"] == "2026-09-07"
        monitoring = append_depletion(
            runout["id"], [depletion("2026-08-03T00:00:00Z", 5000)]
        )
        assert monitoring["state"] == "MONITORING"
        assert monitoring["remaining_qty"] == 0
        assert monitoring["trailing_avg_usage_qty"] == 5000
        assert monitoring["actual_runout_date"] == "2026-08-10"

        validate_error(
            api_client.settle_escape(
                escape["id"], {"resolution": "SETTLED"}, admin()
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api_client.settle_escape(
                escape["id"],
                {
                    "resolution": "SETTLED",
                    "actual_reprint_cost_cents": 190000,
                    "actual_scrap_cost_cents": 30000,
                },
                admin(),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api_client.disposition_runout(
                runout["id"], {"disposition": "SCRAP"}, coord()
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        still_claimed = read_escape(escape["id"])
        assert still_claimed["state"] == "RECOVERY_CLAIMED"
        assert still_claimed["provisional_recovery_cents"] == 346000
        assert still_claimed["final_recovery_cents"] is None
        assert still_claimed["recovery_variance_cents"] is None
        assert still_claimed["resolution"] is None
        assert still_claimed["settled_at"] is None

        still_open = read_runout(runout["id"])
        assert still_open["state"] == "MONITORING"
        assert still_open["disposition"] is None
        assert still_open["units_scrapped"] == 0
        assert still_open["units_reworked"] == 0
        assert still_open["remaining_qty"] == 0
        assert still_open["total_changeover_cost_cents"] == 0

        completed = disposition_runout(runout["id"], "RUNOUT")
        assert completed["state"] == "RUNOUT_COMPLETE"
        assert completed["disposition"] == "RUNOUT"
        assert completed["units_scrapped"] == 0
        assert completed["units_reworked"] == 0
        assert completed["material_writeoff_cents"] == 0
        assert completed["relabel_cost_cents"] == 0
        assert completed["total_changeover_cost_cents"] == 0

        rows, meta = validate_paginated(
            api_client.list_inventory_runouts(
                coord(),
                params={"artwork_asset_id": asset["id"], "disposition": "RUNOUT"},
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["id"] == runout["id"]
        assert rows[0]["units_scrapped"] == 0
        assert rows[0]["units_reworked"] == 0

        assert read_version(v1["id"])["state"] == "OBSOLETE"
        closing_asset = read_asset(asset["id"])
        assert closing_asset["obsolescence_state"] == "SUPERSEDED"
        assert closing_asset["obsolete_units_total"] == 0
        assert closing_asset["changeover_cost_committed_cents"] == 0
