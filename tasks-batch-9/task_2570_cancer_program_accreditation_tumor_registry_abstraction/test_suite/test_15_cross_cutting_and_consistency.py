"""Version tokens, threshold counters, and the immediacy of derived reads."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_abstractor,
    assert_created,
    assert_follow_up_contact,
    assert_ok,
    assert_program,
    assert_qa_audit,
    assert_submission,
    assert_submission_item,
    assert_tumor_case,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
    validate_paginated,
)

COORDINATOR = make_accreditation_coordinator_headers("user-coord-1")


def _program(api, coc_program_id, name):
    return get_success_data(
        api.create_program(
            f.program_payload(
                name=name,
                coc_program_id=coc_program_id,
                annual_analytic_caseload=300,
                reference_year=2018,
                timeliness_standard_days=180,
            ),
            PLATFORM_ADMIN,
        )
    )


def _abstractor(api, program_id, name):
    return get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program_id,
                name=name,
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )


def _source(api, program_id):
    return get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program_id, source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )


def _case(api, source_id, patient_mrn):
    entry = get_success_data(
        api.create_casefinding_entry(
            source_id,
            f.casefinding_entry_payload(
                patient_mrn=patient_mrn,
                accession_date="2026-08-03",
                primary_site_code="C50.9",
                histology_code="8500/3",
                behavior_code="MALIGNANT_3",
                diagnosis_date="2026-07-01",
                first_contact_date="2026-07-05",
                diagnosed_at_facility=True,
                first_treatment_at_facility=True,
            ),
            REGISTRY_MANAGER,
        )
    )
    decided = get_success_data(
        api.reportability_decision(
            entry["id"], f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )
    return decided["created_case_id"]


def _abstraction_payload(case_id, abstractor_id, expected_case_version):
    return f.abstraction_payload(
        case_id,
        abstractor_id,
        expected_case_version,
        stage_source="PATHOLOGIC",
        t_category="T2",
        n_category="N0",
        m_category="M0",
        stage_group="STAGE_II",
        first_treatment_date="2026-07-10",
        treatment_modalities=["SURGERY"],
        diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
        outcome_status="ALIVE_NO_EVIDENCE",
        last_contact_date="2026-07-20",
    )


def _submitted_world(api, coc_program_id, name):
    """One case abstracted by registrar A and waiting on reviewer Q."""
    program = _program(api, coc_program_id, name)
    abs_a = _abstractor(api, program["id"], "Dana Reyes")
    abs_q = _abstractor(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    case_id = _case(api, source["id"], "MRN-0001")
    case = get_success_data(
        api.assign_case(case_id, f.assign_payload(abs_a["id"]), REGISTRY_MANAGER)
    )
    abstraction = get_success_data(
        api.create_abstraction(
            _abstraction_payload(case_id, abs_a["id"], case["version"]),
            make_registry_abstractor_headers(abs_a["id"]),
        )
    )
    get_success_data(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(abs_a["id"]),
        )
    )
    return {
        "program": program,
        "abs_a": abs_a,
        "abs_q": abs_q,
        "source": source,
        "case_id": case_id,
        "abstraction": abstraction,
    }


def _approved_world(api, coc_program_id, name):
    world = _submitted_world(api, coc_program_id, name)
    get_success_data(
        api.qa_decision(
            world["abstraction"]["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(world["abs_q"]["id"]),
        )
    )
    return world


# --------------------------------------------------------------------------
# stale_expected_submission_version_outranks_both_duplicate_and_state_refusals
# --------------------------------------------------------------------------
def test_the_stale_batch_version_outranks_both_the_duplicate_and_the_state_refusal(api):
    """One replayed version token buys two 412s for two different real reasons.

    PRD 2.8: "The version check on both endpoints is evaluated after all
    existence checks and before any state precondition. A stale
    `expected_case_version` on a case that is in the wrong state still reports
    the stale-version error, and a stale `expected_submission_version` on a
    batch that is not in `DRAFT` still reports the stale-version error."

    PRD 3.6: "The add creates a `SubmissionItem` with `edit_status` `PENDING`
    and empty `edit_codes`, moves the case `NOT_SUBMITTED → PENDING_SUBMISSION`
    on its second dimension, increments `total_case_count` by one, and
    increments the batch's `version` by one — which is what makes the next add
    require a re-read."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_submission_version_outranks_both_duplicate_and_state_refusals
    """
    world = _approved_world(api, "COC-1456N", "Northside Cancer Center")
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                world["program"]["id"],
                period_start="2026-07-01",
                period_end="2026-07-31",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    sub_v0 = batch["version"]

    item = assert_submission_item(
        assert_created(
            api.add_submission_item(
                batch["id"],
                f.submission_item_payload(world["case_id"], sub_v0),
                REGISTRY_MANAGER,
            )
        )
    )
    assert item["edit_status"] == "PENDING"

    after_add = assert_submission(
        assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    )
    sub_v1 = after_add["version"]
    assert sub_v1 == sub_v0 + 1
    assert after_add["total_case_count"] == 1

    replay = validate_error(
        api.add_submission_item(
            batch["id"],
            f.submission_item_payload(world["case_id"], sub_v0),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_STALE_SUBMISSION_VERSION.value,
        412,
    )
    assert replay["error_id"] != ApiErrorId.ERR_CASE_ALREADY_IN_SUBMISSION.value

    unchanged = assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    assert unchanged["total_case_count"] == 1
    assert unchanged["version"] == sub_v1

    transmitted = assert_ok(
        api.transmit_submission(
            batch["id"], f.transmit_payload(transmit_note="July 2026 batch"), REGISTRY_MANAGER
        )
    )
    assert transmitted["submission_state"] == "TRANSMITTED"
    assert transmitted["version"] == sub_v1 + 1

    stale_on_transmitted = validate_error(
        api.add_submission_item(
            batch["id"],
            f.submission_item_payload(world["case_id"], sub_v1),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_STALE_SUBMISSION_VERSION.value,
        412,
    )
    assert stale_on_transmitted["error_id"] != ApiErrorId.ERR_SUBMISSION_NOT_DRAFT.value

    items, meta = validate_paginated(
        api.list_submission_items(REGISTRY_MANAGER, {"submission_id": batch["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in items] == [item["id"]]
    assert items[0]["edit_status"] == "PENDING"


# --------------------------------------------------------------------------
# entity_version_advances_once_per_successful_write_and_never_on_a_read_or_refusal
# --------------------------------------------------------------------------
def test_the_case_version_moves_one_step_per_write_and_none_per_read_or_refusal(api):
    """Two reads, one refused create and two accepted writes on the same token.

    PRD 2.4: "Most resources additionally carry `updated_at` — an ISO 8601 UTC
    instant refreshed on every mutation — and `version`, an integer that starts
    at 1 on creation and increments by exactly 1 on every mutation of that
    resource."

    PRD 2.8: "If another writer has advanced the case's version since the
    client last read it — a QA verdict, an assignment change, or a prior
    abstraction on the same case all do so — the create is rejected with
    `ERR_STALE_CASE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/entity_version_advances_once_per_successful_write_and_never_on_a_read_or_refusal
    """
    program = _program(api, "COC-1456N", "Northside Cancer Center")
    abs_a = _abstractor(api, program["id"], "Dana Reyes")
    _abstractor(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    case_id = _case(api, source["id"], "MRN-0001")

    first_read = assert_tumor_case(assert_ok(api.get_case(case_id, REGISTRY_MANAGER)))
    v_created = first_read["version"]
    second_read = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert second_read["version"] == v_created

    assigned = assert_ok(
        api.assign_case(case_id, f.assign_payload(abs_a["id"]), REGISTRY_MANAGER)
    )
    v_assigned = assigned["version"]
    assert v_assigned == v_created + 1

    validate_error(
        api.create_abstraction(
            _abstraction_payload(case_id, abs_a["id"], v_created),
            make_registry_abstractor_headers(abs_a["id"]),
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION.value,
        412,
    )
    after_refusal = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert after_refusal["version"] == v_assigned

    abstraction = assert_created(
        api.create_abstraction(
            _abstraction_payload(case_id, abs_a["id"], v_assigned),
            make_registry_abstractor_headers(abs_a["id"]),
        )
    )
    in_abstraction = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert in_abstraction["case_state"] == "IN_ABSTRACTION"
    assert in_abstraction["version"] == v_assigned + 1

    assert_ok(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(abs_a["id"]),
        )
    )
    at_qa = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert at_qa["version"] == v_created + 3
    assert at_qa["case_state"] == "QA_PENDING"


# --------------------------------------------------------------------------
# third_consecutive_failed_audit_trips_the_suspension_threshold_and_releases_the_workload
# --------------------------------------------------------------------------
def test_the_third_failed_audit_suspends_the_author_and_releases_the_worklist(api):
    """Two failures are silent; the third empties the registrar's worklist.

    PRD 3.4: "The `verdict` then follows three ordered rules: any critical
    discrepancy at all forces `CRITICAL_FAIL` regardless of the total;
    otherwise a total of two points or fewer is `PASS`; otherwise it is
    `MINOR_FAIL`."

    PRD 3.4: "Separately, and regardless of which failing verdict was reached,
    an `audit_fail_streak` that reaches three suspends the author: their
    `employment_status` becomes `SUSPENDED_FROM_ABSTRACTING` and their entire
    open worklist is released to `IDENTIFIED` with `assigned_open_case_count`
    set to zero, exactly as in the staffing cascade of §3.2."

    PRD 3.4: "`quality_score_cumulative` is the unweighted variant reported to
    the accreditation file: over every closed audit ever, it divides the total
    count of minor, major, and critical discrepancies — each counted once, with
    no severity weighting — by the total `audited_field_count`, and applies the
    same subtraction, rounding, and clamp, again yielding 100.0 on an empty
    cohort."

    Design: Corner/cross_cutting_complexity_layers/third_consecutive_failed_audit_trips_the_suspension_threshold_and_releases_the_workload
    """
    world = _approved_world(api, "COC-1456N", "Northside Cancer Center")
    abs_a_id = world["abs_a"]["id"]
    abs_q_id = world["abs_q"]["id"]
    auditor = make_qa_reviewer_headers(abs_q_id)
    case_2_id = _case(api, world["source"]["id"], "MRN-0002")
    get_success_data(
        api.assign_case(case_2_id, f.assign_payload(abs_a_id), REGISTRY_MANAGER)
    )

    audit_ids = []
    for window_start, window_end in (
        ("2026-08-01", "2026-08-05"),
        ("2026-08-06", "2026-08-10"),
        ("2026-08-11", "2026-08-15"),
    ):
        audit = get_success_data(
            api.create_qa_audit(
                f.qa_audit_payload(
                    world["abstraction"]["id"],
                    abs_q_id,
                    audit_type="ROUTINE_10PCT",
                    window_start=window_start,
                    window_end=window_end,
                ),
                auditor,
            )
        )
        audit_ids.append(audit["id"])

    score = f.audit_score_payload(
        audited_field_count=40,
        minor_discrepancy_count=0,
        major_discrepancy_count=1,
        critical_discrepancy_count=0,
    )

    first = assert_qa_audit(assert_ok(api.score_qa_audit(audit_ids[0], score, auditor)))
    assert first["weighted_error_score"] == 3
    assert first["verdict"] == "MINOR_FAIL"
    assert first["audit_state"] == "CLOSED_FAIL"

    second = assert_qa_audit(assert_ok(api.score_qa_audit(audit_ids[1], score, auditor)))
    assert second["weighted_error_score"] == 3
    assert second["verdict"] == "MINOR_FAIL"
    assert second["audit_state"] == "CLOSED_FAIL"

    at_two = assert_abstractor(assert_ok(api.get_abstractor(abs_a_id, REGISTRY_MANAGER)))
    assert at_two["audit_fail_streak"] == 2
    assert at_two["employment_status"] == "ACTIVE"
    assert at_two["assigned_open_case_count"] == 1

    third = assert_qa_audit(assert_ok(api.score_qa_audit(audit_ids[2], score, auditor)))
    assert third["weighted_error_score"] == 3
    assert third["verdict"] == "MINOR_FAIL"
    assert third["audit_state"] == "CLOSED_FAIL"

    at_three = assert_abstractor(
        assert_ok(api.get_abstractor(abs_a_id, REGISTRY_MANAGER))
    )
    assert at_three["audit_fail_streak"] == 3
    assert at_three["employment_status"] == "SUSPENDED_FROM_ABSTRACTING"
    assert at_three["assigned_open_case_count"] == 0
    assert at_three["lifetime_discrepancy_points"] == 9
    assert at_three["quality_score_rolling_90d"] == 92.5
    assert at_three["quality_score_cumulative"] == 97.5

    released = assert_ok(api.get_case(case_2_id, REGISTRY_MANAGER))
    assert released["case_state"] == "IDENTIFIED"
    assert released["assigned_abstractor_id"] is None

    kept = assert_ok(api.get_case(world["case_id"], REGISTRY_MANAGER))
    assert kept["case_state"] == "COMPLETED"

    abstraction = assert_ok(
        api.get_abstraction(world["abstraction"]["id"], REGISTRY_MANAGER)
    )
    assert abstraction["abstraction_state"] == "APPROVED"

    for audit_id in audit_ids:
        audit = assert_ok(api.get_qa_audit(audit_id, REGISTRY_MANAGER))
        assert audit["cascade_applied"] is False


# --------------------------------------------------------------------------
# every_derived_field_of_a_four_level_cascade_is_already_settled_in_the_writing_response
# --------------------------------------------------------------------------
def test_the_qa_approval_response_already_carries_the_settled_case_and_registrar(api):
    """The write itself, and the very next read, agree on every derived figure.

    PRD 3.3: "`APPROVED` is the deepest cascade in the system: the abstraction
    moves `SUBMITTED_FOR_QA → APPROVED` with `approved_at` stamped from the
    clock; because the abstraction was approved the case moves `QA_PENDING →
    COMPLETED` with `completed_on` set to the clock date and `timeliness_status`
    finalised; because the case left the open backlog the registrar's
    `assigned_open_case_count` is decremented by one and their
    `completed_cases_30d`, `productivity_rate_per_day`, and
    `productivity_status` are recomputed; because the backlog shrank,
    `open_backlog_count`, `overdue_backlog_count`, and `registry_posture` are
    recomputed; and because the posture was recomputed, a posture that leaves
    `FROZEN` returns every held batch to its `pre_hold_state`."

    PRD 3.1: "Once a case reaches `COMPLETED` the status is finalised against
    the completion date instead of the clock: it is `ON_TIME` when
    `completed_on` is on or before `abstract_due_date` and `LATE` otherwise, and
    `days_to_due` becomes the whole number of days from `completed_on` to
    `abstract_due_date`."

    Design: Corner/consistency_model/every_derived_field_of_a_four_level_cascade_is_already_settled_in_the_writing_response
    """
    world = _submitted_world(api, "COC-1456N", "Northside Cancer Center")

    decision = assert_ok(
        api.qa_decision(
            world["abstraction"]["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(world["abs_q"]["id"]),
        )
    )
    assert decision["abstraction_state"] == "APPROVED"
    assert decision["approved_at"] == "2026-08-01T00:00:00.000Z"
    assert decision["qa_reviewer_user_id"] == world["abs_q"]["id"]

    case = assert_tumor_case(assert_ok(api.get_case(world["case_id"], REGISTRY_MANAGER)))
    assert case["case_state"] == "COMPLETED"
    assert case["completed_on"] == "2026-08-01"
    assert case["abstract_due_date"] == "2027-01-01"
    assert case["timeliness_status"] == "ON_TIME"
    assert case["days_to_due"] == 153

    registrar = assert_abstractor(
        assert_ok(api.get_abstractor(world["abs_a"]["id"], REGISTRY_MANAGER))
    )
    assert registrar["assigned_open_case_count"] == 0
    assert registrar["completed_cases_30d"] == 1
    assert registrar["productivity_rate_per_day"] == 0.05
    assert registrar["productivity_status"] == "BELOW"


def test_repeating_the_program_read_after_that_cascade_changes_nothing(api):
    """The program aggregates settle on the write and hold across two reads.

    PRD 2.7: "The posture is then decided by four clauses evaluated in exactly
    this order, the first matching clause winning: if the program's
    `accreditation_state` is `PROBATION` or `WITHDRAWN`, the posture is
    `FROZEN`; otherwise, if `open_critical_deficiency_count` is at least 1, the
    posture is `FROZEN`; otherwise, if `overdue_backlog_count` is at least 2,
    the posture is `FROZEN`; otherwise, if `open_backlog_count` is at least 4,
    the posture is `RESTRICTED`; otherwise the posture is `OPEN`."

    PRD 3.5: "A contact carries `counts_for_follow_up` true when its `outcome`
    is `CONTACT_MADE` or `DECEASED` and false for `NO_RESPONSE` or
    `MOVED_UNKNOWN` — only qualifying contacts advance the case's
    `last_contact_date`, which is set to the later of its existing value and the
    new `contact_date` so that back-dated entries cannot walk it backwards."

    Design: Corner/consistency_model/every_derived_field_of_a_four_level_cascade_is_already_settled_in_the_writing_response
    """
    world = _approved_world(api, "COC-1456N", "Northside Cancer Center")

    first = assert_program(
        assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    )
    assert first["open_backlog_count"] == 0
    assert first["overdue_backlog_count"] == 0
    assert first["follow_up_rate_coc_pct"] == 0.0
    assert first["registry_posture"] == "OPEN"

    second = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert second["version"] == first["version"]
    assert second == first


# --------------------------------------------------------------------------
# a_computed_read_reflects_the_preceding_mutation_and_stays_stable_until_the_next_one
# --------------------------------------------------------------------------
def test_the_summary_jumps_on_the_first_read_after_the_contact_and_then_holds(api):
    """One contact moves the rate from 0.0 to 100.0 in the very next read.

    PRD 3.5: "The program's compliance summary is a computed read that
    recomputes and returns both rates, the conference compliance flags, the
    backlog counts and the posture without mutating any workflow state."

    PRD 3.5: "The Commission-facing variant, stored as
    `follow_up_rate_coc_pct`, restricts the denominator to cases diagnosed
    within 1826 days of the clock date and drops patients whose `vital_status`
    is `DEAD` entirely; its numerator is those denominator cases with a non-null
    `last_contact_date` no more than 456 days old."

    PRD 3.5: "It accepts a `follow_up_variant` parameter that selects only which
    variant `lost_to_follow_up_pct` is reported from: `coc_five_year`, the
    default when the parameter is absent, reports the Commission complement
    described above, while `state_central_all_years` reports 100.0 minus
    `follow_up_rate_state_pct`."

    Design: Corner/consistency_model/a_computed_read_reflects_the_preceding_mutation_and_stays_stable_until_the_next_one
    """
    world = _approved_world(api, "COC-1456N", "Northside Cancer Center")
    program_id = world["program"]["id"]

    before = assert_ok(api.get_compliance_summary(program_id, COORDINATOR))
    assert before["follow_up_rate_coc_pct"] == 0.0
    assert before["follow_up_rate_state_pct"] == 0.0
    assert before["lost_to_follow_up_pct"] == 100.0

    before_again = assert_ok(api.get_compliance_summary(program_id, COORDINATOR))
    assert before_again["follow_up_rate_coc_pct"] == 0.0
    assert before_again["follow_up_rate_state_pct"] == 0.0
    assert before_again["lost_to_follow_up_pct"] == 100.0

    contact = assert_follow_up_contact(
        assert_created(
            api.create_follow_up_contact(
                world["case_id"],
                f.follow_up_contact_payload(
                    contact_date="2026-08-01",
                    contact_method="CLINIC_VISIT",
                    outcome="CONTACT_MADE",
                    vital_status_at_contact="ALIVE",
                ),
                REGISTRY_MANAGER,
            )
        )
    )
    assert contact["counts_for_follow_up"] is True

    case = assert_ok(api.get_case(world["case_id"], REGISTRY_MANAGER))
    assert case["last_contact_date"] == "2026-08-01"
    assert case["follow_up_status"] == "CURRENT"

    after = assert_ok(api.get_compliance_summary(program_id, COORDINATOR))
    assert after["follow_up_rate_coc_pct"] == 100.0
    assert after["follow_up_rate_state_pct"] == 100.0
    assert after["lost_to_follow_up_pct"] == 0.0

    after_again = assert_ok(api.get_compliance_summary(program_id, COORDINATOR))
    assert after_again["follow_up_rate_coc_pct"] == 100.0
    assert after_again["follow_up_rate_state_pct"] == 100.0
    assert after_again["lost_to_follow_up_pct"] == 0.0

    state_variant = assert_ok(
        api.get_compliance_summary(
            program_id, COORDINATOR, {"follow_up_variant": "state_central_all_years"}
        )
    )
    assert state_variant["follow_up_rate_coc_pct"] == 100.0
    assert state_variant["follow_up_rate_state_pct"] == 100.0
    assert state_variant["lost_to_follow_up_pct"] == 0.0
