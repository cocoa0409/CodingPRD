"""Optimistic concurrency on the examination version line, per-area rate
thresholds, and the immediate consistency the PRD declares for cascades.

Every scenario is built from scratch through the API: the harness relaunches the
server before each test, so each test starts against an empty database.
"""

from test_helpers import (
    DEFAULT_HARM_CENTS,
    EIC,
    SUPERVISOR,
    ApiErrorId,
    assert_consent_order,
    assert_corrective_action_plan,
    assert_criticism,
    assert_examination,
    assert_file_sample,
    assert_insurer,
    assert_restitution_ledgers_balance,
    assert_scope_area,
    build_reviews,
    consent_order_payload,
    corrective_action_plan_payload,
    criticism_finalize_payload,
    disposition_data_call,
    is_iso8601_timestamp,
    issue_criticism,
    issue_data_call,
    make_insurer_respondent_headers,
    order_execution_payload,
    plan_review_payload,
    read_examination,
    respond_to_criticism,
    respond_to_data_call,
    setup_area_in_fieldwork,
    setup_examination_in_criticism,
    setup_examination_in_negotiation,
    setup_locked_examination,
    systematic_file_references,
    validate_error,
    validate_success,
)

# The canonical claims sample: three MATERIAL files quantifying 25000 + 18000 +
# 7333 cents of harm across ten reviewed files drawn from a population of 4000.
# 50333 / 10 = 5033.3, rounded half up to 5033 cents per file, times 4000 files.
EXTRAPOLATED_EXPOSURE_CENTS = 20_132_000
PENALTY_UNITS = 20
PER_VIOLATION_GROSS_CENTS = 500_000
PER_VIOLATION_NET_CENTS = 475_000
PER_VIOLATION_ORDER_TOTAL_CENTS = 20_607_000


def _area_carried_to_tested(scenario, area, population_size, sample_size, due_date, harm_cents):
    """Issue, produce, accept and bulk-review one area's whole population."""
    area_id = scenario["scope_areas"][area]["id"]
    data_call = issue_data_call(
        area_id,
        records_requested=population_size,
        response_due_date=due_date,
    )
    respond_to_data_call(
        data_call["id"], scenario["insurer_id"], records_received=population_size
    )
    disposition_data_call(data_call["id"], "ACCEPTED")
    references = systematic_file_references(area, population_size, sample_size)
    return {
        "area_id": area_id,
        "data_call_id": data_call["id"],
        "file_references": references,
        "reviews": build_reviews(references, harm_cents, "MATERIAL"),
    }


# ─── Optimistic concurrency on the parent examination version ──────────────


class TestExaminationVersionPinning:
    def test_parent_version_guards_the_plan_while_the_plan_keeps_its_own_line(self, api):
        """A stale pin is refused, the refusal writes nothing, and the child versions itself.

        PRD §2.6: "If `expected_examination_version` does not equal the examination's current `version`, the request is rejected with `ERR_STALE_EXAMINATION_VERSION` and HTTP 412."
        PRD §2.4: "Most record types additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that record — including mutations that touch only derived counters."
        PRD §3.8: "A new plan opens in `PROPOSED` and supersedes any earlier plan on the examination whose `status` is `PROPOSED` or `REVISION_REQUESTED`: that earlier plan moves to `SUPERSEDED` and has its `version` incremented by 1, and the new plan takes a `revision_round` one greater than the superseded plan's."
        PRD §3.8: "The very first plan on an examination takes `revision_round` 1."
        PRD §3.8: "Proposal increments the examination's `version` by 1."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_versions_the_parent_examination_and_not_the_child_plan
        """
        scenario = setup_examination_in_negotiation()
        exam_id = scenario["exam_id"]
        respondent = make_insurer_respondent_headers(scenario["insurer_id"])

        before = read_examination(exam_id)
        assert_examination(before)
        assert before["status"] == "NEGOTIATION"
        v0 = before["version"]

        first = validate_success(
            api.propose_corrective_action_plan(
                exam_id,
                corrective_action_plan_payload(
                    v0,
                    milestone_count=4,
                    completion_due_date="2027-03-31",
                    narrative=(
                        "The carrier commits to reunderwriting the affected claim "
                        "inventory and retraining adjusters."
                    ),
                ),
                respondent,
            ),
            201,
        )
        assert_corrective_action_plan(first)
        # The child's own version line starts at 1 independently of the parent's.
        assert first["version"] == 1
        assert first["revision_round"] == 1
        assert first["status"] == "PROPOSED"
        plan1_id = first["id"]

        v1 = read_examination(exam_id)["version"]
        assert v1 == v0 + 1, "creating a child plan advanced the examination's version by 1"

        # Replaying the token captured before the first filing is now stale.
        stale = api.propose_corrective_action_plan(
            exam_id,
            corrective_action_plan_payload(
                v0,
                milestone_count=6,
                completion_due_date="2027-06-30",
                narrative=(
                    "The carrier retries its plan with the version it captured "
                    "before the first filing."
                ),
            ),
            respondent,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_EXAMINATION_VERSION.value)

        v2 = read_examination(exam_id)["version"]
        assert v2 == v1, "the refused write mutated nothing, so the parent version stood still"

        untouched = validate_success(api.get_corrective_action_plan(plan1_id, SUPERVISOR))
        assert untouched["version"] == 1
        assert untouched["status"] == "PROPOSED"

        second = validate_success(
            api.propose_corrective_action_plan(
                exam_id,
                corrective_action_plan_payload(
                    v2,
                    milestone_count=6,
                    completion_due_date="2027-06-30",
                    narrative=(
                        "The carrier commits to reunderwriting the affected claim "
                        "inventory and retraining adjusters."
                    ),
                ),
                respondent,
            ),
            201,
        )
        assert_corrective_action_plan(second)
        assert second["version"] == 1
        assert second["revision_round"] == 2
        assert second["status"] == "PROPOSED"

        superseded = validate_success(api.get_corrective_action_plan(plan1_id, SUPERVISOR))
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["version"] == 2

        v3 = read_examination(exam_id)["version"]
        assert v3 == v2 + 1, (
            "one accepted child write advanced the parent exactly once even though "
            "it also superseded a sibling"
        )

    def test_the_plan_and_the_order_share_one_examination_version_line(self, api):
        """The carrier's filing invalidates the department's pending order token.

        PRD §2.6: "`POST /market-conduct/examinations/{id}/consent-orders` requires the same non-optional `expected_examination_version` field."
        PRD §2.6: "A mismatch against the examination's current `version` is rejected with `ERR_STALE_EXAMINATION_VERSION` and HTTP 412."
        PRD §3.8: "`APPROVE` moves the plan to `APPROVED` and cascades: the examination advances `NEGOTIATION → ORDER_PENDING` and its `version` is incremented by 1."
        PRD §2.6: "Two writes in the enforcement phase are guarded by optimistic concurrency against the parent `Examination`, because in both cases the write is legal on state grounds and would silently overwrite history the client has not seen."

        Design: Corner/cross_cutting_layers/both_guarded_endpoints_share_one_examination_version_line
        """
        scenario = setup_examination_in_negotiation()
        exam_id = scenario["exam_id"]
        respondent = make_insurer_respondent_headers(scenario["insurer_id"])
        order_number = "NV-MC-2026-0042"

        version_a = read_examination(exam_id)["version"]

        plan = validate_success(
            api.propose_corrective_action_plan(
                exam_id,
                corrective_action_plan_payload(
                    version_a,
                    milestone_count=4,
                    completion_due_date="2027-03-31",
                    narrative=(
                        "The carrier commits to reunderwriting the affected claim "
                        "inventory and retraining adjusters."
                    ),
                ),
                respondent,
            ),
            201,
        )
        assert plan["status"] == "PROPOSED"

        # The department still holds version_a.  The plan is only PROPOSED, so the
        # same request would otherwise earn ERR_CAP_NOT_APPROVED; version pinning
        # is the earlier band and therefore the answer.
        stale_before_approval = api.draft_consent_order(
            exam_id,
            consent_order_payload(version_a, order_number, "PER_VIOLATION"),
            SUPERVISOR,
        )
        validate_error(
            stale_before_approval, ApiErrorId.ERR_STALE_EXAMINATION_VERSION.value
        )

        validate_success(
            api.review_corrective_action_plan(
                plan["id"],
                plan_review_payload(
                    "APPROVE",
                    review_note="The department accepts the remediation plan as filed.",
                ),
                SUPERVISOR,
            )
        )

        after_approval = read_examination(exam_id)
        assert after_approval["status"] == "ORDER_PENDING"
        version_b = after_approval["version"]
        assert version_b == version_a + 2, (
            "the carrier's proposal and the supervisor's approval each advanced the "
            "examination's version by exactly 1"
        )

        # A stale token never becomes valid again.
        stale_after_approval = api.draft_consent_order(
            exam_id,
            consent_order_payload(version_a, order_number, "PER_VIOLATION"),
            SUPERVISOR,
        )
        validate_error(
            stale_after_approval, ApiErrorId.ERR_STALE_EXAMINATION_VERSION.value
        )

        order = validate_success(
            api.draft_consent_order(
                exam_id,
                consent_order_payload(version_b, order_number, "PER_VIOLATION"),
                SUPERVISOR,
            ),
            201,
        )
        assert_consent_order(order)
        assert order["status"] == "DRAFT"
        # No earlier order row was ever created, so the identical order_number is free.
        assert order["order_number"] == order_number

        version_c = read_examination(exam_id)["version"]
        assert version_c == version_b + 1


# ─── Per-area tolerance and escalation thresholds ─────────────────────────


class TestPerAreaRateThresholds:
    def test_tolerance_and_escalation_are_read_off_each_area_s_own_rates(self, api):
        """One area breaches and escalates while its sibling reports zero on both.

        PRD §3.5: "An area's counters are recomputed from its own file samples — those reachable through the data calls of that one area, and only that area."
        PRD §3.5: "`tolerance_breached` is true when `error_rate_pct` is greater than or equal to the area's own `error_tolerance_pct`; an error rate exactly equal to the tolerance breaches it."
        PRD §3.5: "`escalation_required` is true when `material_error_rate_pct` is greater than or equal to 10.00 percent; again exact equality escalates."
        PRD §3.3: "An optional `error_tolerance_pct` between 0.00 and 100.00 inclusive overrides the statutory default; when it is omitted the default is read from the per-area statutory table — 7.00 percent for `UNDERWRITING`, 5.00 percent for `RATING`, 3.00 percent for `CLAIMS` and 10.00 percent for `PRODUCER`."
        PRD §2.7: "When a child record changes in a way that feeds a parent counter, the parent's counter is recomputed in the same request, the parent's `updated_at` is refreshed and the parent's `version` is incremented by 1."

        Design: Corner/cross_cutting_layers/rate_thresholds_are_evaluated_per_scope_area_on_the_recomputed_rates
        """
        scenario = setup_locked_examination(
            areas=(("CLAIMS", 4000, 10), ("RATING", 500, 10))
        )
        claims = _area_carried_to_tested(
            scenario, "CLAIMS", 4000, 10, "2026-09-15", (40_000,)
        )
        rating = _area_carried_to_tested(
            scenario, "RATING", 500, 10, "2026-09-18", ()
        )

        claims_batch = validate_success(
            api.bulk_review(claims["data_call_id"], {"reviews": claims["reviews"]}, EIC)
        )
        assert claims_batch["scope_area_status"] == "TESTED"
        assert claims_batch["reviewed_sample_count"] == 10
        assert claims_batch["error_rate_pct"] == 10.00
        assert claims_batch["material_error_rate_pct"] == 10.00
        assert claims_batch["tolerance_breached"] is True
        assert claims_batch["escalation_required"] is True

        # Only one of the two areas is TESTED, so the examination has not bubbled up.
        assert read_examination(scenario["exam_id"])["status"] == "FIELDWORK"

        rating_batch = validate_success(
            api.bulk_review(rating["data_call_id"], {"reviews": rating["reviews"]}, EIC)
        )
        assert rating_batch["scope_area_status"] == "TESTED"
        assert rating_batch["reviewed_sample_count"] == 10
        assert rating_batch["error_rate_pct"] == 0.00
        assert rating_batch["material_error_rate_pct"] == 0.00
        assert rating_batch["tolerance_breached"] is False
        assert rating_batch["escalation_required"] is False

        claims_area = validate_success(api.get_scope_area(claims["area_id"], EIC))
        rating_area = validate_success(api.get_scope_area(rating["area_id"], EIC))
        assert_scope_area(claims_area)
        assert_scope_area(rating_area)

        # The two areas carry different statutory tolerances, so the threshold is
        # per area rather than per examination.
        assert claims_area["error_tolerance_pct"] == 3.00
        assert rating_area["error_tolerance_pct"] == 5.00
        assert claims_area["error_rate_pct"] == 10.00
        assert claims_area["material_error_rate_pct"] == 10.00
        assert claims_area["tolerance_breached"] is True
        assert claims_area["escalation_required"] is True
        assert rating_area["error_rate_pct"] == 0.00
        assert rating_area["material_error_rate_pct"] == 0.00
        assert rating_area["tolerance_breached"] is False
        assert rating_area["escalation_required"] is False

        assert read_examination(scenario["exam_id"])["status"] == "CRITICISM"


# ─── Immediate consistency ────────────────────────────────────────────────


class TestImmediateConsistency:
    def test_the_bulk_review_body_already_carries_its_own_cascade(self, api):
        """The writing request reports the post-cascade area, and the reads agree exactly.

        PRD §2.7: "Upward propagation is immediate and synchronous within the request that triggers it."
        PRD §2.7: "When a child record changes in a way that feeds a parent counter, the parent's counter is recomputed in the same request, the parent's `updated_at` is refreshed and the parent's `version` is incremented by 1."
        PRD §3.5: "It answers with `{ applied_count, skipped_count, skipped_file_references, scope_area_status, reviewed_sample_count, error_count, error_rate_pct, material_error_rate_pct, tolerance_breached, escalation_required }`, where `applied_count` counts the files actually reviewed, `skipped_count` and `skipped_file_references` report the already-reviewed references that were passed over, and the remaining members mirror the owning area's state after the batch."
        PRD §3.5: "When the last `UNREVIEWED` file of an area is reviewed, whether by a single review or as part of a bulk batch, the area advances `FIELDWORK → TESTED` and cascades in two further hops."

        Design: Corner/consistency_model/a_write_response_already_carries_its_own_cascade
        """
        scenario = setup_area_in_fieldwork()
        area_id = scenario["scope_area_id"]
        exam_id = scenario["exam_id"]

        pre_area = validate_success(api.get_scope_area(area_id, EIC))
        assert pre_area["status"] == "FIELDWORK"
        assert pre_area["reviewed_sample_count"] == 0
        assert pre_area["error_rate_pct"] == 0.00
        pre_exam = read_examination(exam_id)
        assert pre_exam["status"] == "FIELDWORK"
        exam_version_before = pre_exam["version"]

        reviews = build_reviews(
            scenario["file_references"], DEFAULT_HARM_CENTS, "MATERIAL"
        )
        batch = validate_success(
            api.bulk_review(scenario["data_call_id"], {"reviews": reviews}, EIC)
        )
        assert batch["applied_count"] == 10
        assert batch["skipped_count"] == 0
        assert batch["skipped_file_references"] == []
        # The cascade is already visible inside the writing request.
        assert batch["scope_area_status"] == "TESTED"
        assert batch["reviewed_sample_count"] == 10
        assert batch["error_count"] == 3
        assert batch["error_rate_pct"] == 30.00
        assert batch["material_error_rate_pct"] == 30.00
        assert batch["tolerance_breached"] is True
        assert batch["escalation_required"] is True

        post_area = validate_success(api.get_scope_area(area_id, EIC))
        assert_scope_area(post_area)
        assert post_area["status"] == batch["scope_area_status"]
        assert post_area["reviewed_sample_count"] == batch["reviewed_sample_count"]
        assert post_area["error_count"] == batch["error_count"]
        assert post_area["error_rate_pct"] == batch["error_rate_pct"]
        assert post_area["material_error_rate_pct"] == batch["material_error_rate_pct"]
        assert post_area["tolerance_breached"] == batch["tolerance_breached"]
        assert post_area["escalation_required"] == batch["escalation_required"]
        assert is_iso8601_timestamp(post_area["tested_at"])

        post_exam = read_examination(exam_id)
        assert_examination(post_exam)
        assert post_exam["status"] == "CRITICISM"
        assert is_iso8601_timestamp(post_exam["criticism_phase_opened_at"])
        assert post_exam["version"] == exam_version_before + 1

        samples = validate_success(api.list_file_samples(scenario["data_call_id"], EIC))
        first_sample = samples[0]
        assert_file_sample(first_sample)
        assert first_sample["review_status"] == "ERROR"
        assert first_sample["error_severity"] == "MATERIAL"
        assert first_sample["underpaid_amount_cents"] == DEFAULT_HARM_CENTS[0]

    def test_sustaining_publishes_every_ledger_to_the_next_reader(self, api):
        """One finalization moves the criticism, the examination and the carrier at once.

        PRD §3.7: "Second, the frozen exposure moves from provisional to accrued on the examination: `open_criticism_count` is lowered by 1 and `pending_restitution_cents` is lowered by the criticism's `restitution_exposure_cents`, while `sustained_criticism_count` is raised by 1, `aggregate_restitution_cents` is raised by that same `restitution_exposure_cents`, and `penalty_units_total` is raised by the criticism's `penalty_units`; the examination's `version` is incremented by 1."
        PRD §3.7: "Third, if that leaves the examination with `open_criticism_count` of 0 and `sustained_criticism_count` of 1 or more, the examination advances `CRITICISM → NEGOTIATION`, incrementing its `version` again and raising the subject carrier's `pending_enforcement_exam_count` by 1."
        PRD §3.6: "Under `POPULATION_EXTRAPOLATED`, the summed underpayment is first divided by the reviewed-sample count and **that per-file average is rounded half up to a whole cent**, and only then is the rounded average multiplied by the area's `population_size` to give `restitution_exposure_cents`."
        PRD §3.8: "Execution stamps `executed_at` from the logical clock, moves the order to `EXECUTED`, increments the order's `version` by 1, and raises the subject carrier's `lifetime_restitution_ordered_cents` by the order's frozen `restitution_cents`."
        PRD §2.7: "Upward propagation is immediate and synchronous within the request that triggers it."

        Design: Corner/consistency_model/finalisation_publishes_its_ledgers_to_every_reader_in_the_same_request
        """
        scenario = setup_examination_in_criticism()
        exam_id = scenario["exam_id"]
        insurer_id = scenario["insurer_id"]
        respondent = make_insurer_respondent_headers(insurer_id)

        criticism = issue_criticism(exam_id, scenario["scope_area_id"], "MATERIAL", 3)
        assert_criticism(criticism)
        assert criticism["restitution_method"] == "POPULATION_EXTRAPOLATED"
        assert criticism["restitution_exposure_cents"] == EXTRAPOLATED_EXPOSURE_CENTS

        held = read_examination(exam_id)
        assert held["open_criticism_count"] == 1
        assert held["pending_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
        assert held["aggregate_restitution_cents"] == 0

        respond_to_criticism(criticism["id"], insurer_id, "DISPUTE")

        pre_insurer = validate_success(api.get_insurer(insurer_id, SUPERVISOR))
        assert_insurer(pre_insurer)
        assert pre_insurer["lifetime_restitution_ordered_cents"] == 0
        assert pre_insurer["pending_enforcement_exam_count"] == 0

        finalized = validate_success(
            api.finalize_criticism(
                criticism["id"],
                criticism_finalize_payload(
                    "SUSTAINED",
                    PENALTY_UNITS,
                    disposition_note=(
                        "Criticism sustained after review of the carrier rebuttal."
                    ),
                ),
                # A criticism may not be sustained by the examiner who issued it.
                SUPERVISOR,
            )
        )
        assert finalized["status"] == "SUSTAINED"

        accrued = read_examination(exam_id)
        assert_examination(accrued)
        assert accrued["open_criticism_count"] == 0
        assert accrued["sustained_criticism_count"] == 1
        assert accrued["pending_restitution_cents"] == 0
        assert accrued["aggregate_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
        assert accrued["penalty_units_total"] == PENALTY_UNITS
        assert accrued["status"] == "NEGOTIATION"
        assert_restitution_ledgers_balance(accrued, EXTRAPOLATED_EXPOSURE_CENTS)

        # The derived read stores nothing yet agrees with the persisted ledgers.
        summary = validate_success(api.get_exposure_summary(exam_id, SUPERVISOR))
        assert summary["aggregate_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
        assert summary["penalty_units_total"] == PENALTY_UNITS
        assert summary["per_violation_penalty_gross_cents"] == PER_VIOLATION_GROSS_CENTS
        assert summary["per_violation_cooperation_credit_pct"] == 0.05
        assert summary["per_violation_penalty_net_cents"] == PER_VIOLATION_NET_CENTS
        assert (
            summary["per_violation_order_total_cents"]
            == PER_VIOLATION_ORDER_TOTAL_CENTS
        )

        mid_insurer = validate_success(api.get_insurer(insurer_id, SUPERVISOR))
        assert mid_insurer["pending_enforcement_exam_count"] == 1
        assert mid_insurer["lifetime_restitution_ordered_cents"] == 0

        plan = validate_success(
            api.propose_corrective_action_plan(
                exam_id,
                corrective_action_plan_payload(
                    accrued["version"],
                    milestone_count=4,
                    completion_due_date="2027-03-31",
                    narrative=(
                        "The carrier commits to reunderwriting the affected claim "
                        "inventory and retraining adjusters."
                    ),
                ),
                respondent,
            ),
            201,
        )
        validate_success(
            api.review_corrective_action_plan(
                plan["id"],
                plan_review_payload(
                    "APPROVE",
                    review_note="The department accepts the remediation plan as filed.",
                ),
                SUPERVISOR,
            )
        )

        approved_exam = read_examination(exam_id)
        assert approved_exam["status"] == "ORDER_PENDING"

        order = validate_success(
            api.draft_consent_order(
                exam_id,
                consent_order_payload(
                    approved_exam["version"], "NV-MC-2026-0042", "PER_VIOLATION"
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert_consent_order(order)
        assert order["restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
        assert order["penalty_gross_cents"] == PER_VIOLATION_GROSS_CENTS
        assert order["cooperation_credit_pct"] == 0.05
        assert order["penalty_net_cents"] == PER_VIOLATION_NET_CENTS
        assert order["order_total_cents"] == PER_VIOLATION_ORDER_TOTAL_CENTS

        # Drafting freezes the figure without crediting the carrier's ledger.
        draft_insurer = validate_success(api.get_insurer(insurer_id, SUPERVISOR))
        assert draft_insurer["lifetime_restitution_ordered_cents"] == 0

        executed = validate_success(
            api.execute_consent_order(
                order["id"],
                order_execution_payload(signed_by="M. Halloran, President and CEO"),
                respondent,
            )
        )
        assert executed["status"] == "EXECUTED"
        assert is_iso8601_timestamp(executed["executed_at"])

        post_insurer = validate_success(api.get_insurer(insurer_id, SUPERVISOR))
        assert (
            post_insurer["lifetime_restitution_ordered_cents"]
            == EXTRAPOLATED_EXPOSURE_CENTS
        ), "the carrier ledger moves only on execution and is readable immediately"
