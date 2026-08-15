"""Event completion cascades: fulfillment, line crediting, run auto-finalize, release."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_agency,
    get_event_issuances,
    get_inventory,
    get_run,
    get_run_lines,
    setup_completed_event,
    setup_event_with_issuance,
    size_entry,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]


class TestEventCompletionCascade:
    def test_completion_fulfills_issuances_and_debits_inventory(self, api):
        """PRD §3.5: "In the first hop, every `RECORDED` issuance of the event transitions to `FULFILLED` with `fulfilled_at` stamped from the logical clock. In the second hop, each fulfilled issuance line debits the inventory twice — `on_hand_units` decreases by the quantity and `reserved_units` decreases by the same quantity, because the reservation is being consumed rather than released, leaving `available_units` unchanged by fulfillment itself — and the allocation line selected by the clock's current calendar month, the run's `PUBLISHED` status, the event's host agency, and the line's size is credited, its `fulfilled_units` increasing by the quantity and its status recomputed per §3.4."

        Design: Difficulty/transitive_cascade/event_complete_cascade_to_run_auto_finalize
        """
        scenario = setup_event_with_issuance(
            size_code="SIZE_1", stock_units=300, issue_quantity=300, record=True,
        )
        event = scenario["event"]
        validate_success(api.lock_distribution_event(event["id"], ADMIN), 200)
        completed = validate_success(api.complete_distribution_event(event["id"], ADMIN), 200)
        assert completed["status"] == "COMPLETED"

        issuances = get_event_issuances(event["id"])
        assert len(issuances) == 1
        assert issuances[0]["status"] == "FULFILLED", "Hop 1 fulfills the issuance"
        assert issuances[0]["fulfilled_at"] is not None

        lines = get_run_lines(scenario["run"]["id"])
        assert lines[0]["fulfilled_units"] == 300, "Hop 2 credits the line"
        assert lines[0]["status"] == "FULFILLED", (
            "A line reaching fulfilled == allocated flips to FULFILLED"
        )

        entry = size_entry(get_inventory(), "SIZE_1")
        assert entry["on_hand_units"] == 0
        assert entry["reserved_units"] == 0, (
            "The reservation is consumed by fulfillment, not released"
        )

    def test_last_line_fulfilled_auto_finalizes_run(self, api):
        """PRD §3.4: "When the last open line of a `PUBLISHED` run reaches `FULFILLED`, the run automatically transitions to `FINALIZED` with no reservation release — every reserved unit was consumed by fulfillment — and only the run's `version` increments."
        PRD §3.5: "The event stamps `completed_at`, recomputes `issued_total_units` as the sum of `total_units` over its `FULFILLED` issuances, and the versions of the event, the inventory, and every touched allocation line increment."

        Design: Difficulty/transitive_cascade/event_complete_cascade_to_run_auto_finalize
        """
        scenario = setup_completed_event(
            size_code="SIZE_1", stock_units=300, issue_quantity=300,
        )
        run_after = get_run(scenario["run"]["id"])
        assert run_after["status"] == "FINALIZED", (
            "Hop 3: every line FULFILLED auto-finalizes the run"
        )

        event = scenario["event"]
        assert event["status"] == "COMPLETED"
        assert event["completed_at"] is not None
        assert event["issued_total_units"] == 300


class TestAgencySuspensionCascade:
    def test_suspend_releases_unfulfilled_remainder(self, api):
        """PRD §3.1: "When a `BankAdmin` suspends an agency, it transitions `ACTIVE` → `SUSPENDED`, and the suspension cascades through everything the agency was promised: every allocation line belonging to that agency whose status is `ALLOCATED` or `PARTIALLY_FULFILLED` transitions to `RELEASED`, with `released_units` set to the line's `allocated_units` minus its `fulfilled_units`. For each released line, the inventory's `reserved_units` for that line's `size_code` is decremented by the released amount, returning the stock to the available pool."

        Design: Difficulty/transitive_cascade/agency_suspend_release_cascade
        """
        scenario = setup_completed_event(
            size_code="SIZE_3", stock_units=500, issue_quantity=200,
        )
        line = get_run_lines(scenario["run"]["id"])[0]
        assert line["status"] == "PARTIALLY_FULFILLED"
        assert line["fulfilled_units"] == 200

        suspended = validate_success(
            api.suspend_agency(scenario["agency"]["id"], ADMIN), 200)
        assert suspended["status"] == "SUSPENDED"

        line_after = get_run_lines(scenario["run"]["id"])[0]
        assert line_after["status"] == "RELEASED"
        assert line_after["released_units"] == 300, "500 allocated - 200 fulfilled"

        entry = size_entry(get_inventory(), "SIZE_3")
        assert entry["reserved_units"] == 0, (
            "The 300-unit remainder returns from reserved to the available pool"
        )
        assert entry["on_hand_units"] == 300, (
            "Only the fulfillment debit touched physical stock"
        )

    def test_suspend_zeroes_active_allocation(self, api):
        """PRD §3.1: "The agency's `active_allocated_units` is recomputed — it becomes zero — and the agency's `version` increments."
        PRD §2.9: "Each agency's `active_allocated_units` mirrors this from the recipient side: it is the sum of allocated-but-unfulfilled units over that agency's allocation lines whose status is `ALLOCATED` or `PARTIALLY_FULFILLED`, and it is recomputed whenever those lines move."

        Design: Difficulty/transitive_cascade/agency_suspend_release_cascade
        """
        scenario = setup_completed_event(
            size_code="SIZE_3", stock_units=500, issue_quantity=200,
        )
        agency_before = get_agency(scenario["agency"]["id"])
        assert agency_before["active_allocated_units"] == 300, (
            "500 allocated minus 200 fulfilled over the PARTIALLY_FULFILLED line"
        )

        validate_success(api.suspend_agency(scenario["agency"]["id"], ADMIN), 200)

        agency_after = get_agency(scenario["agency"]["id"])
        assert agency_after["status"] == "SUSPENDED"
        assert agency_after["active_allocated_units"] == 0, (
            "The released line no longer counts toward active allocation"
        )


class TestRunExitGuards:
    def test_run_retract_with_consumption_rejected(self, api):
        """PRD §3.4: "Retraction — `PUBLISHED` → `DRAFT` — is permitted only while no line has consumed anything: a single line with `fulfilled_units` above zero makes the run unretractable, likewise `ERR_RUN_NOT_PUBLISHED`."

        Design: Corner/state_machines/run_retract_with_consumption_rejected
        """
        scenario = setup_completed_event(
            size_code="SIZE_1", stock_units=500, issue_quantity=200,
        )
        resp = api.retract_allocation_run(scenario["run"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_PUBLISHED)

        run_after = get_run(scenario["run"]["id"])
        assert run_after["status"] == "PUBLISHED", (
            "Consumption closes the revert branch; the run stays PUBLISHED"
        )
        line = get_run_lines(scenario["run"]["id"])[0]
        assert line["fulfilled_units"] == 200

    def test_finalize_checkpoint_releases_remainder(self, api):
        """PRD §3.4: "Finalization — `PUBLISHED` → `FINALIZED`, the terminal state — releases the leftovers: every line in `ALLOCATED` or `PARTIALLY_FULFILLED` transitions to `RELEASED` with `released_units` set to `allocated_units` minus `fulfilled_units`, the inventory's `reserved_units` is decremented by each released amount, and lines already `FULFILLED` are left unchanged."

        Design: Corner/cross_cutting_layers/finalize_checkpoint_releases_remainder
        """
        scenario = setup_completed_event(
            size_code="SIZE_6", stock_units=500, issue_quantity=200,
        )
        finalized = validate_success(
            api.finalize_allocation_run(scenario["run"]["id"], ADMIN), 200)
        assert finalized["status"] == "FINALIZED"

        line = get_run_lines(scenario["run"]["id"])[0]
        assert line["status"] == "RELEASED"
        assert line["released_units"] == 300, "500 allocated - 200 fulfilled"
        assert line["fulfilled_units"] == 200

        entry = size_entry(get_inventory(), "SIZE_6")
        assert entry["reserved_units"] == 0
        assert entry["on_hand_units"] == 300
        assert entry["available_units"] == 300, (
            "The released remainder is available again"
        )


class TestDerivedFieldReconciliation:
    def test_derived_fields_reconcile_after_completion(self, api):
        """PRD §3.5: "The event stamps `completed_at`, recomputes `issued_total_units` as the sum of `total_units` over its `FULFILLED` issuances, and the versions of the event, the inventory, and every touched allocation line increment."
        PRD §2.9: "Each agency's `active_allocated_units` mirrors this from the recipient side: it is the sum of allocated-but-unfulfilled units over that agency's allocation lines whose status is `ALLOCATED` or `PARTIALLY_FULFILLED`, and it is recomputed whenever those lines move."
        PRD §1: "every derived counter described in this document is reconciled in the same request that invalidates it."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_completion
        """
        scenario = setup_completed_event(
            size_code="SIZE_1", stock_units=100, issue_quantity=45,
        )
        event = scenario["event"]
        assert event["issued_total_units"] == 45, (
            "Sum of total_units over the event's FULFILLED issuances"
        )

        agency = get_agency(scenario["agency"]["id"])
        assert agency["active_allocated_units"] == 55, (
            "100 allocated minus 45 fulfilled, recomputed in the same request's aftermath"
        )

        entry = size_entry(get_inventory(), "SIZE_1")
        assert entry["on_hand_units"] == 55
        assert entry["reserved_units"] == 55
