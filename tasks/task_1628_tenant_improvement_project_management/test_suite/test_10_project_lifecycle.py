"""Project-level reads and the cancellation compensation cascade."""
from test_helpers import (
    create_approved_draw,
    create_milestone_record,
    create_submitted_draw,
    get_success_data,
    set_logical_clock,
    setup_project_in_construction,
    setup_project_negotiated,
    validate_success,
)


class TestProjectComputedRead:
    def test_project_read_exposes_computed_monetary_fields(self, api, landlord_pm_headers):
        """PRD 3.2: "the new record carries the `lease_id` of its parent lease,
        starts in `INITIATED`, and all of its monetary accumulators —
        `allowance_total_cents`, `total_cost_cents`, `allowance_consumed_cents`,
        `provisional_allowance_consumed_cents`, `allowance_remaining_cents`,
        `overage_cents`, `retainage_held_cents`, `retainage_released_cents` —
        start at 0, with `posture` at `OPEN`." PRD 3.2: "Execution is the
        moment the allowance pool is born: the project's
        `allowance_total_cents` is set from the letter's
        `allowance_offer_cents`, `allowance_remaining_cents` is recomputed".
        PRD 3.5: "recomputes the project's `total_cost_cents` as
        `base_contract_cents` plus the `total_with_markup_cents` of every
        `APPROVED` change order, its `overage_cents` as the amount by which
        `total_cost_cents` exceeds `allowance_total_cents` (never below zero)".

        Design: Corner/endpoints/project_read_exposes_computed_monetary_fields
        """
        sc = setup_project_negotiated(
            allowance_offer_cents=50_000_000, base_contract_cents=40_000_000
        )
        project = validate_success(api.get_project(sc["project"]["id"], landlord_pm_headers), 200)
        assert project["total_cost_cents"] == 0, (
            "PRD 3.2 lists total_cost_cents among the accumulators that start at 0, "
            "and the 3.5 recompute to base_contract + approved-CO totals runs only "
            "on change-order approval — none has occurred here"
        )
        assert project["allowance_total_cents"] == 50_000_000
        assert project["allowance_remaining_cents"] == 50_000_000
        assert project["allowance_consumed_cents"] == 0
        assert project["overage_cents"] == 0
        assert project["posture"] == "OPEN"
        assert project["status"] == "WORK_LETTER_NEGOTIATION"


class TestCancellationCascade:
    def test_project_cancel_cascades_children_to_terminal(self, api, landlord_pm_headers):
        """PRD 3.8: "From `CONSTRUCTION` the full cascade runs: letters and
        submissions as above; every engagement in `PROPOSED`, `APPROVED`,
        `ACTIVE`, or `SUSPENDED` is `TERMINATED`; every milestone in `PLANNED`
        or `CONFIRMED` is `CANCELLED`; change orders are rejected or voided
        with compensation as above; every draw in `DRAFT`, `SUBMITTED`, or
        `ON_HOLD` is `VOIDED`, and any `APPROVED` draw is `VOIDED` with its
        consumption and retainage backed out of the project exactly as in
        §3.6; every invoice in `DRAFT`, `ISSUED`, or `DISPUTED` is moved to
        `VOID`; and the suite, if it stands `UNDER_CONSTRUCTION` for this
        project, returns to `LEASED`."

        Design: Corner/state_machines/project_cancel_cascades_children_to_terminal
        """
        sc = setup_project_in_construction()
        ctr = sc["contractor"]["id"]

        milestone = create_milestone_record(
            sc["engagement"]["id"], ctr,
            milestone_name="Noisy work",
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            work_type="NOISY",
        )
        milestone = get_success_data(api.confirm_milestone(milestone["id"], landlord_pm_headers))
        assert milestone["status"] == "CONFIRMED"

        set_logical_clock("2026-08-15T00:00:00Z")
        d1 = create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        assert d1["status"] == "APPROVED"
        d2 = create_submitted_draw(sc["project"]["id"], ctr, 2_000_000, waiver_action="none")["draw"]
        assert d2["status"] == "SUBMITTED"

        cancelled = validate_success(api.cancel_project(sc["project"]["id"], landlord_pm_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["allowance_consumed_cents"] == 0, (
            "the approved draw's consumption is backed out of the project"
        )
        assert cancelled["retainage_held_cents"] == 0, (
            "the approved draw's withholding is backed out of the project"
        )

        d1_after = get_success_data(api.get_draw(d1["id"], landlord_pm_headers))
        assert d1_after["status"] == "VOIDED", "an APPROVED draw is voided with compensation"
        d2_after = get_success_data(api.get_draw(d2["id"], landlord_pm_headers))
        assert d2_after["status"] == "VOIDED", "a non-terminal draw is voided"

        milestone_after = get_success_data(api.get_milestone(milestone["id"], landlord_pm_headers))
        assert milestone_after["status"] == "CANCELLED"
        engagement_after = get_success_data(
            api.get_engagement(sc["engagement"]["id"], landlord_pm_headers)
        )
        assert engagement_after["status"] == "TERMINATED"
