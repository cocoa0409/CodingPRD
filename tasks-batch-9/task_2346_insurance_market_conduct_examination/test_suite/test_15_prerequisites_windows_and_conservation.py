"""Cross-entity prerequisites, temporal occupancy windows and conserved ledgers.

Three families of rule are exercised here, all of them stated in the PRD:

* a gate that reads the *state* of a neighbouring aggregate — the carrier's
  licence position when scope is locked, the corrective action plan's status
  when a consent order is drafted, the consent order's status when multistate
  restitution is allocated;
* the two temporal occupancy rules — the carrier's half-open fieldwork calendar
  and the three-day separation between live data calls of one scope area;
* the two conserved ledgers — the cycle's examiner slots and the multistate
  restitution allocation — plus the compensating withdrawal branch of criticism
  finalization.
"""

from test_helpers import (
    COORDINATOR,
    EIC,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    abort_examination,
    abort_payload,
    allocate_restitution,
    assert_allocation_conserved,
    assert_collaboration,
    assert_consent_order,
    assert_data_call,
    assert_slot_ledger_conserved,
    consent_order_payload,
    data_call_payload,
    examination_payload,
    execute_consent_order,
    finalize_criticism,
    is_iso8601_timestamp,
    issue_criticism,
    issue_data_call,
    open_examination,
    plan_review_payload,
    propose_plan,
    read_collaboration,
    read_criticism,
    read_cycle,
    read_cycle_scores,
    read_examination,
    read_exposure_summary,
    read_insurer,
    read_scope_area,
    refresh_market_data,
    register_insurer,
    respond_to_criticism,
    review_plan,
    setup_cycle_with_selected_targets,
    setup_examination_in_criticism,
    setup_examination_in_negotiation,
    setup_examination_with_drafted_order,
    setup_examination_with_executed_order,
    setup_locked_examination,
    validate_error,
    validate_paginated,
    validate_success,
)

# Three participants of identical weight: the lead election therefore turns on
# the state_code tie-break, and the allocation cannot be split evenly.
EQUAL_WEIGHT_STATES = [
    {"state_code": "NV", "policy_count_in_state": 1, "has_examiner_resources": True},
    {"state_code": "AZ", "policy_count_in_state": 1, "has_examiner_resources": True},
    {"state_code": "UT", "policy_count_in_state": 1, "has_examiner_resources": False},
]

BOREAL = {
    "name": "Boreal Indemnity Company",
    "naic_code": "10002",
    "annual_premium_written_cents": 6_000_000_000,
    "policy_count_in_force": 50_000,
    "confirmed_complaints_12mo": 300,
    "financial_stress_score": 80,
    "consumer_trend_score": 90,
}
DELTA = {
    "name": "Delta Shield Insurance Company",
    "naic_code": "10004",
    "annual_premium_written_cents": 2_000_000_000,
    "policy_count_in_force": 20_000,
    "confirmed_complaints_12mo": 100,
    "financial_stress_score": 50,
    "consumer_trend_score": 60,
}


# ══════════════════════════════════════════════════════════════════════════
# Locking scope reads the carrier's licence position, late
# ══════════════════════════════════════════════════════════════════════════


class TestLockScopeBlockedByWithdrawnInsurerLicense:
    """The lock-scope gate is re-evaluated against the subject carrier's licence."""

    @staticmethod
    def _examination_in_scoping():
        insurer = register_insurer()
        examination = open_examination(
            insurer["id"],
            fieldwork_start_date="2026-09-01",
            fieldwork_end_date="2026-11-30",
        )
        scope_area = validate_success(
            api_client.create_scope_area(
                examination["id"],
                {"area": "CLAIMS", "population_size": 4000, "sample_size": 10},
                EIC,
            ),
            201,
        )
        return insurer, examination, scope_area

    def test_lock_scope_is_refused_once_the_carrier_licence_is_withdrawn(self):
        """A carrier that withdrew after the examination opened blocks the lock.

        PRD §3.3: "Locking is possible only from `SCOPING` (otherwise `ERR_EXAM_NOT_IN_SCOPING`), requires at least one scope area to exist (an examination with `scope_area_count` of 0 is a malformed request, `ERR_INVALID_REQUEST`), and requires the subject carrier's `license_status` still to be `LICENSED` or `SUSPENDED` — a carrier that has become `WITHDRAWN` since the examination opened blocks the lock with `ERR_INSURER_NOT_EXAMINABLE`."

        Design: Difficulty/cross_entity_state_dependency/lock_scope_blocked_by_withdrawn_insurer_license
        """
        insurer, examination, _ = self._examination_in_scoping()

        withdrawn = refresh_market_data(insurer["id"], license_status="WITHDRAWN")
        assert withdrawn["license_status"] == "WITHDRAWN"

        before = read_examination(examination["id"])
        assert before["status"] == "SCOPING"

        resp = api_client.lock_scope(examination["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INSURER_NOT_EXAMINABLE.value, 409)

        after = read_examination(examination["id"])
        assert after["status"] == "SCOPING"
        assert after["scope_locked"] is False
        assert after["scope_area_count"] == 1
        assert after["version"] == before["version"]

    def test_opening_a_new_examination_on_a_withdrawn_carrier_is_refused(self):
        """The same licence gate guards the opening of a fresh examination.

        PRD §3.3: "A carrier whose `license_status` is `WITHDRAWN` cannot be examined at all and the attempt is rejected with `ERR_INSURER_NOT_EXAMINABLE`."
        PRD §3.1: "The three enforcement counters are never client-writable: `open_exam_count` tracks the carrier's examinations whose `status` is neither `PUBLISHED` nor `ABORTED`; `pending_enforcement_exam_count` tracks those whose `status` is `NEGOTIATION` or `ORDER_PENDING`; and `lifetime_restitution_ordered_cents` accumulates the `restitution_cents` of every consent order on the carrier's examinations that has reached `EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/lock_scope_blocked_by_withdrawn_insurer_license
        """
        insurer, _examination, _ = self._examination_in_scoping()
        refresh_market_data(insurer["id"], license_status="WITHDRAWN")

        resp = api_client.open_examination(
            examination_payload(
                insurer["id"],
                exam_type="TARGETED_EXAM",
                mode="DESK",
                fieldwork_start_date="2027-06-01",
                fieldwork_end_date="2027-07-31",
            ),
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSURER_NOT_EXAMINABLE.value, 409)

        # No examination was created, so the carrier still carries exactly the one.
        assert read_insurer(insurer["id"])["open_exam_count"] == 1
        listed, meta = validate_paginated(
            api_client.list_examinations(SUPERVISOR, {"insurer_id": insurer["id"]})
        )
        assert meta["total_count"] == 1
        assert len(listed) == 1

    def test_moving_the_licence_to_suspended_unblocks_the_same_lock(self):
        """SUSPENDED is still examinable, so the replayed lock succeeds.

        PRD §3.3: "Locking is possible only from `SCOPING` (otherwise `ERR_EXAM_NOT_IN_SCOPING`), requires at least one scope area to exist (an examination with `scope_area_count` of 0 is a malformed request, `ERR_INVALID_REQUEST`), and requires the subject carrier's `license_status` still to be `LICENSED` or `SUSPENDED` — a carrier that has become `WITHDRAWN` since the examination opened blocks the lock with `ERR_INSURER_NOT_EXAMINABLE`."
        PRD §3.3: "Locking sets `scope_locked` to true and increments the examination's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/lock_scope_blocked_by_withdrawn_insurer_license
        """
        insurer, examination, _ = self._examination_in_scoping()
        refresh_market_data(insurer["id"], license_status="WITHDRAWN")
        validate_error(
            api_client.lock_scope(examination["id"], SUPERVISOR),
            ApiErrorId.ERR_INSURER_NOT_EXAMINABLE.value,
            409,
        )

        suspended = refresh_market_data(insurer["id"], license_status="SUSPENDED")
        assert suspended["license_status"] == "SUSPENDED"

        before = read_examination(examination["id"])
        locked = validate_success(api_client.lock_scope(examination["id"], SUPERVISOR))
        assert locked["status"] == "DATA_CALL"
        assert locked["scope_locked"] is True
        assert locked["scope_area_count"] == 1
        assert locked["version"] == before["version"] + 1


# ══════════════════════════════════════════════════════════════════════════
# Drafting a consent order reads the plan's state, not its existence
# ══════════════════════════════════════════════════════════════════════════


class TestConsentOrderGateReadsPlanState:
    """A plan exists throughout: only an APPROVED one opens the order phase."""

    @staticmethod
    def _negotiation_with_plan_awaiting_revision():
        scenario = setup_examination_in_negotiation(
            harm_cents=(30_000, 20_000, 10_000), penalty_units=20
        )
        plan_one = propose_plan(
            scenario["exam_id"],
            scenario["insurer_id"],
            milestone_count=3,
            completion_due_date="2027-03-31",
            narrative="First filing: the carrier proposes adjuster retraining only.",
        )
        plan_one = review_plan(
            plan_one["id"],
            "REQUEST_REVISION",
            review_note="The plan omits file remediation and a completion audit.",
        )
        scenario["plan_one"] = plan_one
        return scenario

    @staticmethod
    def _draft_order(exam_id):
        version = read_examination(exam_id)["version"]
        return api_client.draft_consent_order(
            exam_id,
            consent_order_payload(version, "MC-2026-0003", "TIERED_AGGREGATE"),
            SUPERVISOR,
        )

    def test_order_is_refused_while_the_only_plan_awaits_revision(self):
        """A REVISION_REQUESTED plan is not an approved plan.

        PRD §3.8: "The examination's `status` must be `NEGOTIATION` or `ORDER_PENDING`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`, and the examination must already hold a corrective action plan in `APPROVED`, otherwise `ERR_CAP_NOT_APPROVED`."
        PRD §3.8: "`REQUEST_REVISION` moves the plan to `REVISION_REQUESTED` and leaves the examination in `NEGOTIATION`."

        Design: Difficulty/cross_entity_state_dependency/consent_order_gate_reads_plan_state_not_plan_existence
        """
        scenario = self._negotiation_with_plan_awaiting_revision()
        assert scenario["plan_one"]["status"] == "REVISION_REQUESTED"
        assert read_examination(scenario["exam_id"])["status"] == "NEGOTIATION"

        validate_error(
            self._draft_order(scenario["exam_id"]),
            ApiErrorId.ERR_CAP_NOT_APPROVED.value,
            409,
        )

        orders, meta = validate_paginated(
            api_client.list_consent_orders(scenario["exam_id"], SUPERVISOR)
        )
        assert meta["total_count"] == 0
        assert orders == []

    def test_a_superseding_plan_is_preserved_and_existence_is_not_approval(self):
        """Filing a replacement supersedes the first plan without deleting it.

        PRD §3.8: "A new plan opens in `PROPOSED` and supersedes any earlier plan on the examination whose `status` is `PROPOSED` or `REVISION_REQUESTED`: that earlier plan moves to `SUPERSEDED` and has its `version` incremented by 1, and the new plan takes a `revision_round` one greater than the superseded plan's."
        PRD §3.8: "The examination's `status` must be `NEGOTIATION` or `ORDER_PENDING`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`, and the examination must already hold a corrective action plan in `APPROVED`, otherwise `ERR_CAP_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/consent_order_gate_reads_plan_state_not_plan_existence
        """
        scenario = self._negotiation_with_plan_awaiting_revision()
        plan_one = scenario["plan_one"]

        plan_two = propose_plan(
            scenario["exam_id"],
            scenario["insurer_id"],
            milestone_count=5,
            completion_due_date="2027-06-30",
            narrative=(
                "Second filing: retraining, file remediation and an independent "
                "completion audit."
            ),
        )
        assert plan_two["status"] == "PROPOSED"
        assert plan_two["revision_round"] == 2

        superseded = validate_success(
            api_client.get_corrective_action_plan(plan_one["id"], SUPERVISOR)
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["version"] == plan_one["version"] + 1

        plans, meta = validate_paginated(
            api_client.list_corrective_action_plans(scenario["exam_id"], SUPERVISOR)
        )
        assert meta["total_count"] == 2
        assert {p["id"] for p in plans} == {plan_one["id"], plan_two["id"]}

        # The replacement exists but is only PROPOSED: existence is not approval.
        validate_error(
            self._draft_order(scenario["exam_id"]),
            ApiErrorId.ERR_CAP_NOT_APPROVED.value,
            409,
        )

    def test_approving_the_plan_opens_the_consent_order_gate(self):
        """APPROVE advances the examination and lets the order be drafted.

        PRD §3.8: "`APPROVE` moves the plan to `APPROVED` and cascades: the examination advances `NEGOTIATION → ORDER_PENDING` and its `version` is incremented by 1."
        PRD §3.8: "Each tier's amount is multiplied by its own rate — one tenth for the first tier, six hundredths for the second, three hundredths for the third — and **each of those three products is rounded half up to a whole cent individually before the three are added together**."
        PRD §3.8: "Step three: `cooperation_credit_pct` is fifteen hundredths when the subtotal is 25,000,000 cents or more, and five hundredths otherwise."

        Design: Difficulty/cross_entity_state_dependency/consent_order_gate_reads_plan_state_not_plan_existence
        """
        scenario = self._negotiation_with_plan_awaiting_revision()
        plan_two = propose_plan(
            scenario["exam_id"],
            scenario["insurer_id"],
            milestone_count=5,
            completion_due_date="2027-06-30",
            narrative=(
                "Second filing: retraining, file remediation and an independent "
                "completion audit."
            ),
        )
        approved = review_plan(
            plan_two["id"], "APPROVE", review_note="The revised plan is acceptable."
        )
        assert approved["status"] == "APPROVED"

        examination = read_examination(scenario["exam_id"])
        assert examination["status"] == "ORDER_PENDING"
        assert examination["aggregate_restitution_cents"] == 24_000_000
        assert examination["penalty_units_total"] == 20

        order = validate_success(self._draft_order(scenario["exam_id"]), 201)
        assert_consent_order(order)
        assert order["status"] == "DRAFT"
        assert order["restitution_cents"] == 24_000_000
        assert order["penalty_gross_cents"] == 1_740_000
        assert order["cooperation_credit_pct"] == 0.15
        assert order["penalty_net_cents"] == 1_479_000
        assert order["order_total_cents"] == 25_479_000

    def test_reviewing_the_superseded_plan_is_refused(self):
        """A SUPERSEDED plan is terminal and can no longer be dispositioned.

        PRD §3.8: "Reviewing a plan whose `status` is not `PROPOSED` is rejected with `ERR_ENFORCEMENT_RECORD_STATE_INVALID`."
        PRD §3.8: "`APPROVED`, `REJECTED` and `SUPERSEDED` are all terminal for a plan."

        Design: Difficulty/cross_entity_state_dependency/consent_order_gate_reads_plan_state_not_plan_existence
        """
        scenario = self._negotiation_with_plan_awaiting_revision()
        plan_one = scenario["plan_one"]
        propose_plan(
            scenario["exam_id"],
            scenario["insurer_id"],
            milestone_count=5,
            completion_due_date="2027-06-30",
            narrative=(
                "Second filing: retraining, file remediation and an independent "
                "completion audit."
            ),
        )

        resp = api_client.review_corrective_action_plan(
            plan_one["id"], plan_review_payload("APPROVE"), SUPERVISOR
        )
        validate_error(resp, ApiErrorId.ERR_ENFORCEMENT_RECORD_STATE_INVALID.value, 409)

        still_superseded = validate_success(
            api_client.get_corrective_action_plan(plan_one["id"], SUPERVISOR)
        )
        assert still_superseded["status"] == "SUPERSEDED"


# ══════════════════════════════════════════════════════════════════════════
# Multistate allocation waits on a sibling aggregate: the executed order
# ══════════════════════════════════════════════════════════════════════════


class TestMultistateAllocationRequiresExecutedOrder:
    """The collaboration is ACTIVE, yet allocation waits on the consent order."""

    @staticmethod
    def _scenario():
        return setup_examination_with_drafted_order(
            penalty_variant="PER_VIOLATION",
            order_number="MC-2026-0004",
            criticism_severity="MATERIAL",
            affected_file_count=3,
            penalty_units=12,
            with_collaboration=True,
        )

    def test_allocation_is_refused_while_the_order_is_only_drafted(self):
        """A DRAFT order does not satisfy the allocation prerequisite.

        PRD §3.9: "A collaboration whose `status` is not `ACTIVE` is rejected with `ERR_ENFORCEMENT_RECORD_STATE_INVALID`; the examination must already hold a consent order in `EXECUTED`, otherwise `ERR_ORDER_NOT_EXECUTED`; and an examination whose `aggregate_restitution_cents` is 0 has nothing to allocate, so the attempt is rejected with `ERR_RESTITUTION_NOT_CONSERVED`."

        Design: Difficulty/cross_entity_state_dependency/multistate_allocation_requires_an_executed_consent_order
        """
        scenario = self._scenario()
        collaboration = read_collaboration(scenario["collaboration_id"])
        assert collaboration["status"] == "ACTIVE"
        assert collaboration["lead_state_code"] == "NV"
        assert collaboration["allocated_total_cents"] == 0
        assert scenario["consent_order"]["status"] == "DRAFT"
        assert scenario["consent_order"]["penalty_gross_cents"] == 300_000
        assert scenario["consent_order"]["cooperation_credit_pct"] == 0.05
        assert scenario["consent_order"]["penalty_net_cents"] == 285_000
        assert scenario["consent_order"]["order_total_cents"] == 20_417_000

        resp = api_client.allocate_restitution(scenario["collaboration_id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_EXECUTED.value, 409)

        untouched = read_collaboration(scenario["collaboration_id"])
        assert untouched["status"] == "ACTIVE"
        assert untouched["allocated_total_cents"] == 0
        assert all(s["allocated_cents"] == 0 for s in untouched["participating_states"])

    def test_executing_the_order_unblocks_the_identical_allocation_call(self):
        """Once the carrier executes, the same allocation call settles.

        PRD §3.8: "Execution stamps `executed_at` from the logical clock, moves the order to `EXECUTED`, increments the order's `version` by 1, and raises the subject carrier's `lifetime_restitution_ordered_cents` by the order's frozen `restitution_cents`."
        PRD §3.9: "Each participant's provisional share is the total multiplied by that participant's `policy_count_in_state`, divided by the denominator, with any fractional cent discarded."
        PRD §3.9: "Each participant's final figure is written to its `allocated_cents`, their sum is written to `allocated_total_cents`, `allocation_completed_at` is stamped from the logical clock and the collaboration's `version` is incremented by 1."

        Design: Difficulty/cross_entity_state_dependency/multistate_allocation_requires_an_executed_consent_order
        """
        scenario = self._scenario()
        validate_error(
            api_client.allocate_restitution(scenario["collaboration_id"], COORDINATOR),
            ApiErrorId.ERR_ORDER_NOT_EXECUTED.value,
            409,
        )

        executed = execute_consent_order(
            scenario["consent_order_id"],
            scenario["insurer_id"],
            signed_by="M. Calloway, President and CEO",
        )
        assert executed["status"] == "EXECUTED"
        assert is_iso8601_timestamp(executed["executed_at"])
        assert executed["signed_by"] == "M. Calloway, President and CEO"
        assert (
            read_insurer(scenario["insurer_id"])["lifetime_restitution_ordered_cents"]
            == 20_132_000
        )

        settled = validate_success(
            api_client.allocate_restitution(scenario["collaboration_id"], COORDINATOR)
        )
        assert_collaboration(settled)
        assert settled["status"] == "SETTLED"
        assert is_iso8601_timestamp(settled["allocation_completed_at"])
        allocations = {
            s["state_code"]: s["allocated_cents"] for s in settled["participating_states"]
        }
        assert allocations == {"NV": 10_882_163, "AZ": 6_801_351, "UT": 2_448_486}
        assert settled["allocated_total_cents"] == 20_132_000
        assert_allocation_conserved(
            settled, read_examination(scenario["exam_id"])["aggregate_restitution_cents"]
        )

    def test_a_state_without_examiner_resources_still_receives_its_share(self):
        """Resource eligibility governs the lead election, not the allocation.

        PRD §3.9: "Only participants whose `has_examiner_resources` is true are eligible."
        PRD §3.9: "The denominator is the sum of `policy_count_in_state` across the whole roster, which is at least 1 by the input constraint."

        Design: Difficulty/cross_entity_state_dependency/multistate_allocation_requires_an_executed_consent_order
        """
        scenario = self._scenario()
        execute_consent_order(scenario["consent_order_id"], scenario["insurer_id"])
        settled = allocate_restitution(scenario["collaboration_id"])

        assert settled["lead_state_code"] == "NV"
        utah = next(
            s for s in settled["participating_states"] if s["state_code"] == "UT"
        )
        assert utah["has_examiner_resources"] is False
        assert utah["allocated_cents"] == 2_448_486


# ══════════════════════════════════════════════════════════════════════════
# The carrier's fieldwork calendar is a half-open interval, per carrier
# ══════════════════════════════════════════════════════════════════════════


class TestExaminationFieldworkWindowsHalfOpen:
    """Fieldwork occupancy is exclusive per carrier and half-open in geometry."""

    @staticmethod
    def _incumbent():
        insurer = register_insurer()
        examination = open_examination(
            insurer["id"],
            fieldwork_start_date="2026-09-01",
            fieldwork_end_date="2026-11-30",
        )
        return insurer, examination

    @staticmethod
    def _attempt(insurer_id, start, end):
        return api_client.open_examination(
            examination_payload(
                insurer_id,
                exam_type="TARGETED_EXAM",
                mode="DESK",
                fieldwork_start_date=start,
                fieldwork_end_date=end,
            ),
            SUPERVISOR,
        )

    def test_a_window_starting_on_the_incumbents_end_date_is_accepted(self):
        """Exact adjacency does not intersect a half-open interval.

        PRD §3.3: "Because the geometry is half-open, exact adjacency is permitted: one examination ending on the very day another begins does not overlap and is accepted."

        Design: Difficulty/resource_temporal_overlap/examination_fieldwork_windows_are_half_open_per_insurer
        """
        insurer, incumbent = self._incumbent()

        adjacent = validate_success(
            self._attempt(insurer["id"], "2026-11-30", "2027-01-31"), 201
        )
        assert adjacent["fieldwork_start_date"] == "2026-11-30"
        assert adjacent["fieldwork_end_date"] == "2027-01-31"
        assert adjacent["status"] == "SCOPING"
        assert adjacent["id"] != incumbent["id"]
        assert read_insurer(insurer["id"])["open_exam_count"] == 2

    def test_a_window_overlapping_the_incumbent_by_one_day_is_refused(self):
        """One day of intersection is an overlap.

        PRD §3.3: "The requested window, read as half-open from `fieldwork_start_date` inclusive to `fieldwork_end_date` exclusive, must not overlap the window of any existing examination of the same carrier whose `status` is neither `PUBLISHED` nor `ABORTED`; an overlap is `ERR_EXAM_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/examination_fieldwork_windows_are_half_open_per_insurer
        """
        insurer, _incumbent = self._incumbent()
        validate_success(self._attempt(insurer["id"], "2026-11-30", "2027-01-31"), 201)

        resp = self._attempt(insurer["id"], "2026-11-29", "2027-02-28")
        validate_error(resp, ApiErrorId.ERR_EXAM_WINDOW_CONFLICT.value, 409)

        listed, meta = validate_paginated(
            api_client.list_examinations(SUPERVISOR, {"insurer_id": insurer["id"]})
        )
        assert meta["total_count"] == 2
        assert len(listed) == 2
        assert read_insurer(insurer["id"])["open_exam_count"] == 2

    def test_a_window_strictly_contained_in_the_incumbent_is_refused(self):
        """Containment is intersection.

        PRD §3.3: "Fieldwork occupancy on a carrier is exclusive. The requested window, read as half-open from `fieldwork_start_date` inclusive to `fieldwork_end_date` exclusive, must not overlap the window of any existing examination of the same carrier whose `status` is neither `PUBLISHED` nor `ABORTED`; an overlap is `ERR_EXAM_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/examination_fieldwork_windows_are_half_open_per_insurer
        """
        insurer, _incumbent = self._incumbent()

        resp = self._attempt(insurer["id"], "2026-10-01", "2026-10-31")
        validate_error(resp, ApiErrorId.ERR_EXAM_WINDOW_CONFLICT.value, 409)

        _listed, meta = validate_paginated(
            api_client.list_examinations(SUPERVISOR, {"insurer_id": insurer["id"]})
        )
        assert meta["total_count"] == 1
        assert read_insurer(insurer["id"])["open_exam_count"] == 1

    def test_the_identical_window_is_accepted_for_a_different_carrier(self):
        """The occupancy constraint is scoped to one carrier's calendar.

        PRD §3.3: "The requested window, read as half-open from `fieldwork_start_date` inclusive to `fieldwork_end_date` exclusive, must not overlap the window of any existing examination of the same carrier whose `status` is neither `PUBLISHED` nor `ABORTED`; an overlap is `ERR_EXAM_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/examination_fieldwork_windows_are_half_open_per_insurer
        """
        aurora, _incumbent = self._incumbent()
        cedar = register_insurer(
            name="Cedar Ridge Mutual Insurance Company",
            naic_code="10003",
            annual_premium_written_cents=800_000_000,
            policy_count_in_force=30_000,
            confirmed_complaints_12mo=60,
            financial_stress_score=40,
            consumer_trend_score=30,
        )

        twin = validate_success(
            api_client.open_examination(
                examination_payload(
                    cedar["id"],
                    fieldwork_start_date="2026-09-01",
                    fieldwork_end_date="2026-11-30",
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert twin["insurer_id"] == cedar["id"]
        assert twin["fieldwork_start_date"] == "2026-09-01"
        assert twin["fieldwork_end_date"] == "2026-11-30"
        assert read_insurer(cedar["id"])["open_exam_count"] == 1
        assert read_insurer(aurora["id"])["open_exam_count"] == 1

    def test_aborting_the_incumbent_releases_the_fieldwork_calendar(self):
        """A terminal examination no longer holds its window.

        PRD §3.3: "The requested window, read as half-open from `fieldwork_start_date` inclusive to `fieldwork_end_date` exclusive, must not overlap the window of any existing examination of the same carrier whose `status` is neither `PUBLISHED` nor `ABORTED`; an overlap is `ERR_EXAM_WINDOW_CONFLICT`."
        PRD §3.10: "The first hop records `abort_reason` and moves the examination to `ABORTED`."

        Design: Difficulty/resource_temporal_overlap/examination_fieldwork_windows_are_half_open_per_insurer
        """
        insurer, incumbent = self._incumbent()
        validate_success(self._attempt(insurer["id"], "2026-11-30", "2027-01-31"), 201)
        assert read_insurer(insurer["id"])["open_exam_count"] == 2

        aborted = validate_success(
            api_client.abort_examination(
                incumbent["id"],
                abort_payload(
                    abort_reason=(
                        "Withdrawn in favour of a rescheduled examination of the "
                        "same carrier."
                    )
                ),
                SUPERVISOR,
            )
        )
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == (
            "Withdrawn in favour of a rescheduled examination of the same carrier."
        )
        assert read_insurer(insurer["id"])["open_exam_count"] == 1

        reused = validate_success(
            api_client.open_examination(
                examination_payload(
                    insurer["id"],
                    fieldwork_start_date="2026-09-01",
                    fieldwork_end_date="2026-10-01",
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert reused["fieldwork_start_date"] == "2026-09-01"
        assert reused["fieldwork_end_date"] == "2026-10-01"
        assert read_insurer(insurer["id"])["open_exam_count"] == 2


# ══════════════════════════════════════════════════════════════════════════
# Live data calls of one scope area must be three whole days apart
# ══════════════════════════════════════════════════════════════════════════


class TestDataCallDueDateSeparation:
    """A minimum-separation rule, scoped to one scope area and strict."""

    @staticmethod
    def _two_areas_with_one_live_call():
        scenario = setup_locked_examination(
            areas=(("CLAIMS", 4000, 10), ("RATING", 500, 10))
        )
        first = issue_data_call(
            scenario["scope_areas"]["CLAIMS"]["id"],
            records_requested=4000,
            response_due_date="2026-09-15",
        )
        scenario["first_call"] = first
        return scenario

    def test_a_gap_of_two_days_is_refused(self):
        """Two whole days of separation is below the statutory buffer.

        PRD §3.4: "If the area already holds a data call whose `status` is neither `REJECTED` nor `CANCELLED`, and the whole-day distance between that call's `response_due_date` and the requested one is fewer than three days in either direction, the new call is rejected with `ERR_DATA_CALL_WINDOW_CONFLICT`."
        PRD §3.4: "The comparison is strict: a gap of exactly three days is accepted, a gap of two is not."

        Design: Difficulty/resource_temporal_overlap/data_call_due_dates_need_a_three_day_gap_within_one_scope_area
        """
        scenario = self._two_areas_with_one_live_call()
        assert scenario["first_call"]["status"] == "ISSUED"
        assert scenario["first_call"]["response_due_date"] == "2026-09-15"

        resp = api_client.create_data_call(
            scenario["scope_areas"]["CLAIMS"]["id"],
            data_call_payload(records_requested=500, response_due_date="2026-09-17"),
            EIC,
        )
        validate_error(resp, ApiErrorId.ERR_DATA_CALL_WINDOW_CONFLICT.value, 409)

        _calls, meta = validate_paginated(
            api_client.list_scope_area_data_calls(
                scenario["scope_areas"]["CLAIMS"]["id"], EIC
            )
        )
        assert meta["total_count"] == 1

    def test_a_gap_of_exactly_three_days_is_accepted(self):
        """Exactly three days clears the strict comparison.

        PRD §3.4: "The comparison is strict: a gap of exactly three days is accepted, a gap of two is not."
        PRD §3.4: "The server stamps `issued_date` from the date part of the logical clock and opens the call in `ISSUED` with `records_received` 0, `is_late` false, `days_late` 0, `completeness_pct` 0.00, `effective_completeness_pct` 0.00, `sample_draw_interval` 0 and `samples_drawn_count` 0."

        Design: Difficulty/resource_temporal_overlap/data_call_due_dates_need_a_three_day_gap_within_one_scope_area
        """
        scenario = self._two_areas_with_one_live_call()

        second = validate_success(
            api_client.create_data_call(
                scenario["scope_areas"]["CLAIMS"]["id"],
                data_call_payload(records_requested=500, response_due_date="2026-09-18"),
                EIC,
            ),
            201,
        )
        assert_data_call(second)
        assert second["status"] == "ISSUED"
        assert second["response_due_date"] == "2026-09-18"
        assert second["issued_date"] == "2026-08-01"
        assert second["records_received"] == 0
        assert second["is_late"] is False
        assert second["days_late"] == 0
        assert second["completeness_pct"] == 0.00
        assert second["effective_completeness_pct"] == 0.00
        assert second["sample_draw_interval"] == 0
        assert second["samples_drawn_count"] == 0

        _calls, meta = validate_paginated(
            api_client.list_scope_area_data_calls(
                scenario["scope_areas"]["CLAIMS"]["id"], EIC
            )
        )
        assert meta["total_count"] == 2

    def test_a_sibling_scope_area_may_reuse_the_same_due_date(self):
        """The separation rule is scoped to one scope area.

        PRD §3.4: "If the area already holds a data call whose `status` is neither `REJECTED` nor `CANCELLED`, and the whole-day distance between that call's `response_due_date` and the requested one is fewer than three days in either direction, the new call is rejected with `ERR_DATA_CALL_WINDOW_CONFLICT`."
        PRD §3.4: "A data call occupies a closed interval on its scope area, running from `issued_date` to `response_due_date` inclusive, and two temporal rules police it."

        Design: Difficulty/resource_temporal_overlap/data_call_due_dates_need_a_three_day_gap_within_one_scope_area
        """
        scenario = self._two_areas_with_one_live_call()

        sibling = validate_success(
            api_client.create_data_call(
                scenario["scope_areas"]["RATING"]["id"],
                data_call_payload(records_requested=500, response_due_date="2026-09-15"),
                EIC,
            ),
            201,
        )
        assert sibling["status"] == "ISSUED"
        assert sibling["response_due_date"] == "2026-09-15"
        assert sibling["scope_area_id"] == scenario["scope_areas"]["RATING"]["id"]

        _claims, claims_meta = validate_paginated(
            api_client.list_scope_area_data_calls(
                scenario["scope_areas"]["CLAIMS"]["id"], EIC
            )
        )
        _rating, rating_meta = validate_paginated(
            api_client.list_scope_area_data_calls(
                scenario["scope_areas"]["RATING"]["id"], EIC
            )
        )
        assert claims_meta["total_count"] == 1
        assert rating_meta["total_count"] == 1

        examination = read_examination(scenario["exam_id"])
        assert examination["status"] == "DATA_CALL"
        assert examination["rejected_data_call_count"] == 0

    def test_a_due_date_past_the_fieldwork_end_date_is_refused(self):
        """The examination's fieldwork window bounds the whole family of calls.

        PRD §3.4: "First, the due date must lie inside the examination's fieldwork window in the practical sense: a `response_due_date` earlier than the current logical-clock date, or later than the owning examination's `fieldwork_end_date`, is rejected with `ERR_DUE_DATE_OUT_OF_WINDOW` at HTTP 422."

        Design: Difficulty/resource_temporal_overlap/data_call_due_dates_need_a_three_day_gap_within_one_scope_area
        """
        scenario = self._two_areas_with_one_live_call()
        assert read_examination(scenario["exam_id"])["fieldwork_end_date"] == "2026-11-30"

        resp = api_client.create_data_call(
            scenario["scope_areas"]["RATING"]["id"],
            data_call_payload(records_requested=500, response_due_date="2026-12-15"),
            EIC,
        )
        validate_error(resp, ApiErrorId.ERR_DUE_DATE_OUT_OF_WINDOW.value, 422)

        _calls, meta = validate_paginated(
            api_client.list_scope_area_data_calls(
                scenario["scope_areas"]["RATING"]["id"], EIC
            )
        )
        assert meta["total_count"] == 0


# ══════════════════════════════════════════════════════════════════════════
# Abandonment gives the examiner slot back exactly
# ══════════════════════════════════════════════════════════════════════════


class TestAbortRestoresSlotLedger:
    """slots_committed plus slots_available equals capacity at every observation."""

    @staticmethod
    def _cycle_with_two_selected_targets():
        scenario = setup_cycle_with_selected_targets(
            carriers=[BOREAL, DELTA],
            cycle_label="FY2026 Two Slot Cycle",
            target_slot_capacity=2,
            default_fieldwork_start="2026-09-01",
            default_fieldwork_end="2026-11-30",
        )
        by_insurer = {e["insurer_id"]: e for e in scenario["examinations"]}
        scenario["boreal"] = scenario["insurers"][0]
        scenario["delta"] = scenario["insurers"][1]
        scenario["boreal_exam"] = by_insurer[scenario["insurers"][0]["id"]]
        scenario["delta_exam"] = by_insurer[scenario["insurers"][1]["id"]]
        return scenario

    def test_selection_commits_both_examiner_slots(self):
        """Each examination selection consumes exactly one slot.

        PRD §3.2: "Each creation raises the carrier's `open_exam_count` by 1 and the cycle's `slots_committed` by 1, thereby lowering `slots_available` by 1."
        PRD §3.2: "Each taken row has `selected` set to true and `selection_reason` set to `SELECTED`, and produces one examination."

        Design: Difficulty/compensating_invariant/abort_restores_the_cycle_examiner_slot_ledger
        """
        scenario = self._cycle_with_two_selected_targets()
        cycle = read_cycle(scenario["cycle_id"])
        assert cycle["status"] == "TARGETS_SELECTED"
        assert cycle["selected_target_count"] == 2
        assert cycle["slots_committed"] == 2
        assert cycle["slots_available"] == 0
        assert_slot_ledger_conserved(cycle)

        scores = read_cycle_scores(scenario["cycle_id"])
        assert [s["rank_position"] for s in scores] == [1, 2]
        assert scores[0]["insurer_id"] == scenario["boreal"]["id"]
        assert scores[0]["composite_score"] == 90.20
        assert scores[1]["insurer_id"] == scenario["delta"]["id"]
        assert scores[1]["composite_score"] == 67.00
        assert all(s["selected"] is True for s in scores)
        assert all(s["selection_reason"] == "SELECTED" for s in scores)

    def test_the_first_abort_returns_one_slot_and_leaves_the_cycle_open(self):
        """One release restores one slot without closing the cycle.

        PRD §2.10: "Every event that adds a non-terminal examination to a cycle raises `slots_committed` by 1 and therefore lowers `slots_available` by 1; every event that drives such an examination terminal lowers `slots_committed` by 1 and restores `slots_available` by 1."
        PRD §3.10: "Because the examination has become terminal, the carrier's `open_exam_count` is lowered by 1; the carrier's `pending_enforcement_exam_count` is lowered by 1 as well, but only when the examination's status immediately before the abort was `NEGOTIATION` or `ORDER_PENDING`; and when the examination carries a `cycle_id`, that cycle's `slots_committed` is lowered by 1, restoring `slots_available` exactly."

        Design: Difficulty/compensating_invariant/abort_restores_the_cycle_examiner_slot_ledger
        """
        scenario = self._cycle_with_two_selected_targets()

        aborted = abort_examination(
            scenario["boreal_exam"]["id"],
            abort_reason=(
                "The carrier is in voluntary run-off; the department suspends this "
                "examination."
            ),
        )
        assert aborted["status"] == "ABORTED"

        cycle = read_cycle(scenario["cycle_id"])
        assert cycle["slots_committed"] == 1
        assert cycle["slots_available"] == 1
        assert cycle["status"] == "TARGETS_SELECTED"
        assert cycle["selected_target_count"] == 2
        assert_slot_ledger_conserved(cycle)

        assert read_insurer(scenario["boreal"]["id"])["open_exam_count"] == 0
        assert read_insurer(scenario["delta"]["id"])["open_exam_count"] == 1

    def test_the_second_abort_closes_the_cycle_and_restores_full_capacity(self):
        """The last release drives the cycle to CLOSED without rewriting history.

        PRD §3.2: "When the last examination attributed to the cycle reaches `PUBLISHED` or `ABORTED` — that is, when `slots_committed` falls to 0 while `selected_target_count` is 1 or more — the cycle advances `TARGETS_SELECTED → CLOSED`, stamps `closed_at` from the logical clock and increments its `version` by 1."
        PRD §2.10: "An abandoned examination gives its slot back exactly, leaving the ledger where it stood before the examination was opened."

        Design: Difficulty/compensating_invariant/abort_restores_the_cycle_examiner_slot_ledger
        """
        scenario = self._cycle_with_two_selected_targets()
        abort_examination(
            scenario["boreal_exam"]["id"],
            abort_reason=(
                "The carrier is in voluntary run-off; the department suspends this "
                "examination."
            ),
        )
        midpoint = read_cycle(scenario["cycle_id"])
        assert_slot_ledger_conserved(midpoint)

        abort_examination(
            scenario["delta_exam"]["id"],
            abort_reason=(
                "Resource reallocation: the department defers this examination to "
                "the next cycle."
            ),
        )

        cycle = read_cycle(scenario["cycle_id"])
        assert cycle["slots_committed"] == 0
        assert cycle["slots_available"] == 2
        assert cycle["status"] == "CLOSED"
        assert is_iso8601_timestamp(cycle["closed_at"])
        assert cycle["selected_target_count"] == 2
        assert_slot_ledger_conserved(cycle)

        for exam_key, reason_fragment in (
            ("boreal_exam", "voluntary run-off"),
            ("delta_exam", "Resource reallocation"),
        ):
            examination = read_examination(scenario[exam_key]["id"])
            assert examination["status"] == "ABORTED"
            assert reason_fragment in examination["abort_reason"]

        assert read_insurer(scenario["boreal"]["id"])["open_exam_count"] == 0
        assert read_insurer(scenario["delta"]["id"])["open_exam_count"] == 0

        scores = read_cycle_scores(scenario["cycle_id"])
        assert all(s["selected"] is True for s in scores)
        assert all(s["selection_reason"] == "SELECTED" for s in scores)

    def test_a_third_abort_is_refused_and_the_ledger_does_not_move(self):
        """A second abandonment of the same examination is terminal-guarded.

        PRD §3.10: "An examination already in `PUBLISHED` or `ABORTED` is rejected with `ERR_EXAM_ALREADY_TERMINAL`, which also covers a second abort attempt."

        Design: Difficulty/compensating_invariant/abort_restores_the_cycle_examiner_slot_ledger
        """
        scenario = self._cycle_with_two_selected_targets()
        abort_examination(
            scenario["boreal_exam"]["id"], abort_reason="First abandonment of this examination."
        )
        abort_examination(
            scenario["delta_exam"]["id"], abort_reason="Second abandonment of this examination."
        )

        resp = api_client.abort_examination(
            scenario["boreal_exam"]["id"],
            abort_payload(abort_reason="A third attempt on an already terminal record."),
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_EXAM_ALREADY_TERMINAL.value, 409)

        cycle = read_cycle(scenario["cycle_id"])
        assert cycle["slots_committed"] == 0
        assert cycle["slots_available"] == 2
        assert cycle["status"] == "CLOSED"
        assert_slot_ledger_conserved(cycle)


# ══════════════════════════════════════════════════════════════════════════
# The multistate allocation conserves every cent through the sweep
# ══════════════════════════════════════════════════════════════════════════


class TestAllocationConservesEveryCent:
    """50333 cents over three equal-weight states leaves a two-cent remainder."""

    @staticmethod
    def _scenario():
        return setup_examination_with_executed_order(
            penalty_variant="PER_VIOLATION",
            order_number="MC-2026-0005",
            criticism_severity="MINOR",
            affected_file_count=1,
            penalty_units=3,
            with_collaboration=True,
            participating_states=EQUAL_WEIGHT_STATES,
        )

    def test_a_minor_criticism_on_a_breached_area_stays_sample_actual(self):
        """The exposure to be allocated is the observed sample harm exactly.

        PRD §3.6: "Both operands carry weight: a `MATERIAL` criticism on a within-tolerance area remains `SAMPLE_ACTUAL`, and a `MINOR` criticism on a breached area also remains `SAMPLE_ACTUAL`."
        PRD §3.6: "Under `SAMPLE_ACTUAL`, `restitution_exposure_cents` equals the observed sample harm exactly — the summed underpayment across the area's error files — and the unexamined remainder of the population is not charged."

        Design: Difficulty/compensating_invariant/allocation_conserves_every_cent_through_the_remainder_sweep
        """
        scenario = self._scenario()
        criticism = read_criticism(scenario["criticism_id"])
        assert criticism["severity"] == "MINOR"
        assert criticism["restitution_method"] == "SAMPLE_ACTUAL"
        assert criticism["restitution_exposure_cents"] == 50_333

        area = read_scope_area(scenario["scope_area_id"])
        assert area["tolerance_breached"] is True
        assert read_examination(scenario["exam_id"])["aggregate_restitution_cents"] == 50_333

    def test_the_lead_state_election_breaks_the_tie_on_state_code(self):
        """Equal policy counts push the election onto the lexicographic tie-break.

        PRD §3.9: "Eligible participants are ranked by `policy_count_in_state` descending, and ties are broken by `state_code` ascending in plain lexicographic order on the two-letter code."
        PRD §3.9: "The first participant after that ordering becomes the collaboration's `lead_state_code`."

        Design: Difficulty/compensating_invariant/allocation_conserves_every_cent_through_the_remainder_sweep
        """
        scenario = self._scenario()
        collaboration = read_collaboration(scenario["collaboration_id"])
        assert_collaboration(collaboration)
        assert collaboration["lead_state_code"] == "AZ"
        assert collaboration["participant_count"] == 3
        assert collaboration["status"] == "ACTIVE"

    def test_the_per_violation_order_prices_the_three_penalty_units(self):
        """The order the carrier executed carries the frozen restitution figure.

        PRD §3.8: "The **per-violation** algorithm ignores restitution size entirely: the gross penalty is the examination's `penalty_units_total` multiplied by 25,000 cents (250 dollars per statutory violation unit)."
        PRD §3.8: "Step four: `penalty_net_cents` is the gross penalty multiplied by one minus the credit rate, rounded half up to a whole cent."
        PRD §3.8: "Step five: `order_total_cents` is the restitution aggregate plus the net penalty."

        Design: Difficulty/compensating_invariant/allocation_conserves_every_cent_through_the_remainder_sweep
        """
        scenario = self._scenario()
        order = scenario["consent_order"]
        assert_consent_order(order)
        assert order["status"] == "EXECUTED"
        assert order["restitution_cents"] == 50_333
        assert order["penalty_gross_cents"] == 75_000
        assert order["cooperation_credit_pct"] == 0.05
        assert order["penalty_net_cents"] == 71_250
        assert order["order_total_cents"] == 121_583
        assert (
            read_insurer(scenario["insurer_id"])["lifetime_restitution_ordered_cents"]
            == 50_333
        )

    def test_the_two_cent_remainder_is_swept_one_cent_at_a_time_in_order(self):
        """The sweep walks policy count descending then state code ascending.

        PRD §3.9: "That remainder is distributed one cent at a time, walking the roster ordered by `policy_count_in_state` descending and then `state_code` ascending; since the remainder is always strictly smaller than `participant_count`, exactly the first several participants in that order — as many as there are remainder cents — receive one extra cent each, and no participant receives two."
        PRD §2.10: "Once allocation runs, the sum of every participant's `allocated_cents` — surfaced as `allocated_total_cents` — must equal the examination's sustained restitution aggregate to the cent, with no rounding drift in either direction."

        Design: Difficulty/compensating_invariant/allocation_conserves_every_cent_through_the_remainder_sweep
        """
        scenario = self._scenario()

        settled = validate_success(
            api_client.allocate_restitution(scenario["collaboration_id"], COORDINATOR)
        )
        assert settled["status"] == "SETTLED"
        assert is_iso8601_timestamp(settled["allocation_completed_at"])

        allocations = {
            s["state_code"]: s["allocated_cents"] for s in settled["participating_states"]
        }
        assert allocations == {"AZ": 16_778, "NV": 16_778, "UT": 16_777}
        assert settled["allocated_total_cents"] == 50_333
        assert_allocation_conserved(settled, 50_333)
        assert (
            read_examination(scenario["exam_id"])["aggregate_restitution_cents"] == 50_333
        )

    def test_a_second_allocation_is_refused_so_the_sweep_cannot_double_apply(self):
        """SETTLED is terminal, so the conserved ledger is written exactly once.

        PRD §3.9: "A collaboration whose `status` is not `ACTIVE` is rejected with `ERR_ENFORCEMENT_RECORD_STATE_INVALID`; the examination must already hold a consent order in `EXECUTED`, otherwise `ERR_ORDER_NOT_EXECUTED`; and an examination whose `aggregate_restitution_cents` is 0 has nothing to allocate, so the attempt is rejected with `ERR_RESTITUTION_NOT_CONSERVED`."
        PRD §3.9: "A collaboration's `status` runs `LEAD_ASSIGNED → ACTIVE → SETTLED`, with `DISSOLVED` reachable when the examination is abandoned; `SETTLED` and `DISSOLVED` are both terminal."

        Design: Difficulty/compensating_invariant/allocation_conserves_every_cent_through_the_remainder_sweep
        """
        scenario = self._scenario()
        first = allocate_restitution(scenario["collaboration_id"])
        assert first["status"] == "SETTLED"

        resp = api_client.allocate_restitution(scenario["collaboration_id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_ENFORCEMENT_RECORD_STATE_INVALID.value, 409)

        after = read_collaboration(scenario["collaboration_id"])
        assert after["status"] == "SETTLED"
        assert after["allocated_total_cents"] == 50_333
        assert {
            s["state_code"]: s["allocated_cents"] for s in after["participating_states"]
        } == {
            s["state_code"]: s["allocated_cents"] for s in first["participating_states"]
        }
        assert_allocation_conserved(after, 50_333)


# ══════════════════════════════════════════════════════════════════════════
# Withdrawal releases the pending pool; only sustaining accrues
# ══════════════════════════════════════════════════════════════════════════


class TestCriticismWithdrawalReleasesPendingPool:
    """Both dispositions drain the pending pool; only SUSTAINED credits the aggregate."""

    @staticmethod
    def _two_responded_criticisms():
        scenario = setup_examination_in_criticism()
        first = issue_criticism(
            scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
        )
        respond_to_criticism(
            first["id"],
            scenario["insurer_id"],
            "DISPUTE",
            narrative="The carrier disputes the three cited claim files.",
        )
        second = issue_criticism(
            scenario["exam_id"],
            scenario["scope_area_id"],
            "MINOR",
            1,
            statute_citation="NRS 686A.310(1)(n)",
        )
        respond_to_criticism(
            second["id"],
            scenario["insurer_id"],
            "CONCUR",
            narrative="The carrier concurs with the documentation finding.",
        )
        scenario["first_criticism"] = first
        scenario["second_criticism"] = second
        return scenario

    def test_withdrawal_drains_pending_without_crediting_the_aggregate(self):
        """The withdrawn exposure is released, never transferred.

        PRD §3.7: "Withdrawal is the compensating branch. It lowers `open_criticism_count` by 1 and lowers `pending_restitution_cents` by the criticism's `restitution_exposure_cents`, and it leaves `sustained_criticism_count`, `aggregate_restitution_cents` and `penalty_units_total` completely untouched — no fiscal accrual of any kind."
        PRD §3.7: "Second, the frozen exposure moves from provisional to accrued on the examination: `open_criticism_count` is lowered by 1 and `pending_restitution_cents` is lowered by the criticism's `restitution_exposure_cents`, while `sustained_criticism_count` is raised by 1, `aggregate_restitution_cents` is raised by that same `restitution_exposure_cents`, and `penalty_units_total` is raised by the criticism's `penalty_units`; the examination's `version` is incremented by 1."

        Design: Difficulty/compensating_invariant/criticism_withdrawal_releases_the_pending_pool_without_touching_the_aggregate
        """
        scenario = self._two_responded_criticisms()
        assert scenario["first_criticism"]["restitution_exposure_cents"] == 20_132_000
        assert scenario["second_criticism"]["restitution_exposure_cents"] == 50_333

        before = read_examination(scenario["exam_id"])
        assert before["pending_restitution_cents"] == 20_182_333
        assert before["aggregate_restitution_cents"] == 0
        assert before["open_criticism_count"] == 2
        assert before["sustained_criticism_count"] == 0

        finalize_criticism(
            scenario["first_criticism"]["id"],
            "SUSTAINED",
            12,
            disposition_note="Sustained: the extrapolation stands.",
        )
        finalize_criticism(
            scenario["second_criticism"]["id"],
            "WITHDRAWN",
            4,
            disposition_note=(
                "Withdrawn: the documentation defect was a department indexing error."
            ),
        )

        after = read_examination(scenario["exam_id"])
        assert after["pending_restitution_cents"] == 0
        assert after["aggregate_restitution_cents"] == 20_132_000
        assert after["sustained_criticism_count"] == 1
        assert after["open_criticism_count"] == 0

    def test_penalty_units_of_a_withdrawn_criticism_never_reach_the_ledger(self):
        """Only the sustained criticism's units raise penalty_units_total.

        PRD §3.7: "Withdrawal is the compensating branch. It lowers `open_criticism_count` by 1 and lowers `pending_restitution_cents` by the criticism's `restitution_exposure_cents`, and it leaves `sustained_criticism_count`, `aggregate_restitution_cents` and `penalty_units_total` completely untouched — no fiscal accrual of any kind."
        PRD §3.7: "Either disposition records `finalized_by_user_id` from `X-User-ID`, stamps `finalized_at` from the logical clock, and increments the criticism's `version` by 1; both `SUSTAINED` and `WITHDRAWN` are terminal for the criticism."

        Design: Difficulty/compensating_invariant/criticism_withdrawal_releases_the_pending_pool_without_touching_the_aggregate
        """
        scenario = self._two_responded_criticisms()

        sustained = finalize_criticism(
            scenario["first_criticism"]["id"],
            "SUSTAINED",
            12,
            disposition_note="Sustained: the extrapolation stands.",
        )
        withdrawn = finalize_criticism(
            scenario["second_criticism"]["id"],
            "WITHDRAWN",
            4,
            disposition_note=(
                "Withdrawn: the documentation defect was a department indexing error."
            ),
        )

        assert sustained["status"] == "SUSTAINED"
        assert withdrawn["status"] == "WITHDRAWN"
        assert sustained["penalty_units"] == 12
        for criticism in (sustained, withdrawn):
            assert criticism["finalized_by_user_id"] == "22222222-2222-2222-2222-222222222222"
            assert is_iso8601_timestamp(criticism["finalized_at"])

        examination = read_examination(scenario["exam_id"])
        assert examination["penalty_units_total"] == 12

    def test_exposure_summary_prices_only_the_sustained_criticism(self):
        """Both penalty variants read an aggregate that excludes the withdrawal.

        PRD §3.8: "`restitution_cents` is a snapshot of the examination's `aggregate_restitution_cents`, which by construction reflects `SUSTAINED` criticisms only — criticisms still in `ISSUED` or `RESPONDED`, and criticisms that were `WITHDRAWN`, contribute nothing to it, nor to `penalty_units_total`, nor to `sustained_criticism_count`."
        PRD §3.8: "That computed read reports `{ examination_id, sustained_criticism_count, aggregate_restitution_cents, penalty_units_total, per_violation_penalty_gross_cents, per_violation_cooperation_credit_pct, per_violation_penalty_net_cents, per_violation_order_total_cents, tiered_penalty_gross_cents, tiered_cooperation_credit_pct, tiered_penalty_net_cents, tiered_order_total_cents }`, applying the same five-step chain independently to each variant."

        Design: Difficulty/compensating_invariant/criticism_withdrawal_releases_the_pending_pool_without_touching_the_aggregate
        """
        scenario = self._two_responded_criticisms()
        finalize_criticism(
            scenario["first_criticism"]["id"],
            "SUSTAINED",
            12,
            disposition_note="Sustained: the extrapolation stands.",
        )
        finalize_criticism(
            scenario["second_criticism"]["id"],
            "WITHDRAWN",
            4,
            disposition_note=(
                "Withdrawn: the documentation defect was a department indexing error."
            ),
        )

        summary = read_exposure_summary(scenario["exam_id"])
        assert summary["sustained_criticism_count"] == 1
        assert summary["aggregate_restitution_cents"] == 20_132_000
        assert summary["penalty_units_total"] == 12
        assert summary["tiered_penalty_gross_cents"] == 1_507_920
        assert summary["tiered_cooperation_credit_pct"] == 0.05
        assert summary["tiered_penalty_net_cents"] == 1_432_524
        assert summary["tiered_order_total_cents"] == 21_564_524
        assert summary["per_violation_penalty_gross_cents"] == 300_000
        assert summary["per_violation_cooperation_credit_pct"] == 0.05
        assert summary["per_violation_penalty_net_cents"] == 285_000
        assert summary["per_violation_order_total_cents"] == 20_417_000
