"""What the first read after a write already shows, and what a read never changes."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assert_bay_ledger,
    assert_money,
    assert_project_state,
    assert_skid_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
    make_fabrication_manager_headers,
    make_platform_admin_headers,
)

PAST_THE_TERM = "2032-01-01T00:00:00.000Z"


class TestCascadesAreVisibleImmediately:
    """A multi-hop cascade lands inside the request that triggered it."""

    def test_the_first_read_after_a_failed_test_already_shows_every_link(self, api):
        """No second read is needed to see the skid, the package and the posture move.

        The PRD says derived values "are recomputed and stamped by the server as a side
        effect of the operation that could have changed them", and pins the chain: "a
        recorded `FAIL` moves the run `SCHEDULED → FAILED` and starts the three-link rework
        cascade. **Link one:** the skid's mechanical axis reverts `MECH_COMPLETE → REWORK`,
        `rework_count` increments by 1, `fat_readiness` recomputes to `BLOCKED` ...
        **Link two:** the parent package transitions `RELEASED_FOR_FAB → REWORK_HOLD` and
        its `version` advances by 1. **Link three:** the project's `delivery_posture`
        becomes `HELD`." Every exit from `SCHEDULED` also "subtracts exactly the same
        footprint-minutes that the booking added."

        Design: Corner/consistency_model/the_fat_failure_cascade_is_already_visible_to_the_very_next_read
        """
        state = fixtures.scheduled_fat_run_project(api)
        fixtures.witness_run(api, state["fat_run"]["id"], "FAIL", 7)

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_application_engineer_headers()
            )
        )

        assert_project_state(
            project, status="IN_FABRICATION", delivery_posture="HELD"
        )

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "REWORK_HOLD"

        skid = fixtures.current_skid(api, state["skid"]["id"])
        assert_skid_state(
            skid,
            mechanical_status="REWORK",
            fat_readiness="BLOCKED",
            rework_count=1,
        )

        run = validate_success(
            api.get_fat_run(
                state["fat_run"]["id"], make_fabrication_manager_headers()
            )
        )
        assert run["status"] == "FAILED"
        assert run["punchlist_item_count"] == 7

        bay = validate_success(
            api.get_test_bay(
                state["test_bay"]["id"], make_fabrication_manager_headers()
            )
        )
        assert_bay_ledger(bay, 0)


class TestReadsNeverMutate:
    """The one deferred transition in the domain is materialised on the write path only."""

    def test_reading_an_agreement_years_past_its_term_leaves_it_active(self, api):
        """The clock jump to 2032 does not itself flip the agreement or bump its version.

        The PRD says "advancing the clock never retroactively re-evaluates stored rows —
        expiry and escalation are evaluated when an operation next touches the affected
        record, as described in the relevant workflow." The workflow that materialises
        expiry is the draw: "before any of that, the **lazy expiry sweep** runs. When the
        logical clock is at or after the agreement's `expires_at`, the agreement is written
        to `EXPIRED`".

        Design: Corner/consistency_model/reading_an_agreement_past_its_term_does_not_itself_expire_it
        """
        state = fixtures.service_active_project(api)
        before = fixtures.current_agreement(api, state["agreement"]["id"])
        validate_success(
            api.set_clock(PAST_THE_TERM, make_platform_admin_headers())
        )

        after = validate_success(
            api.get_service_agreement(
                before["id"], make_contracts_administrator_headers()
            )
        )

        assert after["status"] == "ACTIVE"
        assert after["version"] == before["version"]
        assert_money(
            after["reserve_available_cents"], 12200000, "reserve_available_cents"
        )
        assert_money(
            after["reserve_committed_accrual_cents"],
            0,
            "reserve_committed_accrual_cents",
        )

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="SERVICE_ACTIVE")


class TestParentAggregatesFoldWithTheChild:
    """The aggregate on the parent is rewritten in the request that appends the child."""

    def test_posting_one_draw_rewrites_the_reserve_totals_before_it_answers(self, api):
        """The 1,830,000 accrual and 1,533,600 settled line are both folded into the parent.

        The PRD says "the agreement then adds the accrual line to
        `reserve_committed_accrual_cents`, adds the settled line to
        `reserve_committed_settled_cents`, decreases `reserve_available_cents` by the accrual
        line, recomputes `settlement_variance_cents` as the settled total minus the accrual
        total, and advances its `version` by 1." The two lines are independent:
        `accrual_amount_cents` is "`quantity` multiplied by `catalog_unit_cost_cents`, marked
        up by 22 percent, rounded half up to whole cents", while `settled_amount_cents`
        "starts from `quantity` multiplied by `invoiced_unit_cost_cents`, uplifted by 6.5
        percent freight, rounded half up to whole cents, and then has the warranty credit
        subtracted", and "for a `CONSUMABLE` draw `warranty_credit_cents` is 0."

        Design: Corner/consistency_model/the_parent_reserve_totals_move_in_the_same_request_as_the_child_draw
        """
        state = fixtures.service_active_project(api)
        before = fixtures.current_agreement(api, state["agreement"]["id"])

        draw = validate_success(
            api.create_consumable_draw(
                before["id"],
                factories.consumable_draw_payload(
                    before["version"],
                    draw_type="CONSUMABLE",
                    item_code="MF-ELEM-8",
                    quantity=3,
                    catalog_unit_cost_cents=500000,
                    invoiced_unit_cost_cents=480000,
                ),
                make_contracts_administrator_headers(),
            ),
            201,
        )

        assert draw["draw_type"] == "CONSUMABLE"
        assert_money(draw["accrual_amount_cents"], 1830000, "accrual_amount_cents")
        assert_money(draw["settled_amount_cents"], 1533600, "settled_amount_cents")
        assert_money(draw["warranty_credit_cents"], 0, "warranty_credit_cents")

        after = fixtures.current_agreement(api, before["id"])
        assert_money(
            after["reserve_committed_accrual_cents"],
            1830000,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            after["reserve_committed_settled_cents"],
            1533600,
            "reserve_committed_settled_cents",
        )
        assert_money(
            after["reserve_available_cents"], 10370000, "reserve_available_cents"
        )
        assert_money(
            after["settlement_variance_cents"], -296400, "settlement_variance_cents"
        )
        assert after["version"] != before["version"]
        assert after["status"] == "ACTIVE"
