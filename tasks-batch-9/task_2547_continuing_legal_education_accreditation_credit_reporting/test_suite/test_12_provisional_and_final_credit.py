"""The credit application's two variants, and the risk score's two weightings.

Both behaviours exercised here are single algorithms that run in one of two
variants over identical stored rows, so each test builds one fixed world and
then reads the two answers out of it.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    accreditation_action,
    adjudicate_record,
    api_client,
    audit_action,
    create_accredited_provider,
    create_attorney,
    create_credit_record_payload,
    create_cycle,
    create_probationary_provider,
    create_self_certified_course,
    credit_allocation_entry,
    file_final_affirmation,
    get_success_data,
    list_fee_assessments,
    make_attorney_headers,
    make_provider_admin_headers,
    open_audit,
    read_attorney,
    read_audit,
    read_credit_record,
    read_cycle,
    read_provider,
    review_action,
    submit_application,
    validate_success,
)

BOARD = TEST_USERS["board_admin_headers"]


def _file_affirmation_claim(attorney, course_id, attended_minutes, completion_date):
    """Claims credit on an affirmation-only course, so the record is born
    awaiting verification rather than verified."""
    payload = create_credit_record_payload(
        attorney["id"],
        course_id,
        verification_method="AFFIRMATION",
        attended_minutes=attended_minutes,
        completion_date=completion_date,
    )
    payload.pop("certificate_reference", None)
    return get_success_data(
        api_client.create_credit_record(payload, make_attorney_headers(attorney["id"]))
    )


def _self_study_period_with_one_unverified_claim():
    """Three self-study claims in one open period, consumed in completion order.

    The first verified claim takes 240 of the 360-minute self-study allowance.
    The second claim — 180 ethics minutes — is left awaiting verification, so it
    is inside the provisional input set and outside the final one. The third
    claim is verified and asks for 180 general minutes that only exist once the
    pending claim stops eating the allowance.
    """
    provider = create_accredited_provider(
        name="Statewide Bar CLE Institute", provider_type="BAR_ASSOCIATION"
    )
    course_one = create_self_certified_course(
        provider,
        title="Trust Accounting Basics",
        delivery_format="SELF_STUDY",
        total_minutes=240,
        presented_at="2026-01-05T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[credit_allocation_entry("GENERAL", 240)],
    )
    course_two = create_self_certified_course(
        provider,
        title="Candor Toward the Tribunal",
        delivery_format="SELF_STUDY",
        total_minutes=180,
        presented_at="2026-01-06T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[credit_allocation_entry("ETHICS", 180)],
    )
    course_three = create_self_certified_course(
        provider,
        title="Deposition Practice Review",
        delivery_format="SELF_STUDY",
        total_minutes=180,
        presented_at="2026-01-07T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[credit_allocation_entry("GENERAL", 180)],
    )
    attorney = create_attorney(
        bar_number="BAR-1001",
        full_name="Dana Reyes",
        admission_date="2010-05-01T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    record_one = _file_affirmation_claim(
        attorney, course_one["id"], 240, "2026-02-10T00:00:00Z"
    )
    adjudicate_record(record_one["id"], "VERIFY")
    record_two = _file_affirmation_claim(
        attorney, course_two["id"], 180, "2026-03-10T00:00:00Z"
    )
    record_three = _file_affirmation_claim(
        attorney, course_three["id"], 180, "2026-04-10T00:00:00Z"
    )
    adjudicate_record(record_three["id"], "VERIFY")
    return {
        "provider": provider,
        "attorney": attorney,
        "cycle": read_cycle(cycle["id"]),
        "record_one": record_one,
        "record_two": record_two,
        "record_three": record_three,
    }


def test_pending_self_study_claim_diverts_the_allowance_from_the_later_verified_one(api):
    """Because the caps below are consumed in chronological order, an early pending record can eat the self-study or on-demand allowance that a later verified record would otherwise have taken. Dropping pending records therefore frees cap room for later verified ones, and a specialty total can move from non-zero to zero or from zero to non-zero between the two variants over identical stored data.
    Because the provisional and final pictures can diverge sharply, the cycle summary read runs the algorithm *both* ways over the same stored data and returns the two results side by side without persisting anything.
    Four bucket fields report the **provisional** run's cap consumption: `self_study_used_minutes`, `on_demand_used_minutes`, `nonlive_used_minutes` and `reciprocity_used_minutes`.

    Design: Difficulty/dual_variant_calc/provisional_versus_final_cycle_credit_application_on_compliance_cycle
    """
    world = _self_study_period_with_one_unverified_claim()

    summary = validate_success(
        api.get_cycle_summary(world["cycle"]["id"], BOARD), expected_status=200
    )

    assert summary["provisional_total_minutes"] == 360
    assert summary["provisional_ethics_minutes"] == 120
    assert summary["self_study_used_minutes"] == 360
    assert summary["nonlive_used_minutes"] == 360
    assert summary["on_demand_used_minutes"] == 0
    assert summary["projected_final_total_minutes"] == 360
    assert summary["projected_final_ethics_minutes"] == 0


def test_open_period_persists_the_provisional_answer_and_counts_its_input_set(api):
    """The **provisional** variant includes the cycle's records in `PENDING_VERIFICATION` and `VERIFIED`.
    While a cycle's `credit_status` is `OPEN`, the provisional result is what gets persisted into the cycle's `earned_*` fields and into each record's `countable_minutes`.
    Two counts close the payload: `records_counted` is the size of the provisional input set, and `records_excluded` is the number of the cycle's records in `REJECTED` or `VOIDED`.

    Design: Difficulty/dual_variant_calc/provisional_versus_final_cycle_credit_application_on_compliance_cycle
    """
    world = _self_study_period_with_one_unverified_claim()

    summary = validate_success(
        api.get_cycle_summary(world["cycle"]["id"], BOARD), expected_status=200
    )
    assert summary["records_counted"] == 3
    assert summary["records_excluded"] == 0

    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["credit_status"] == "OPEN"
    assert cycle["earned_countable_minutes"] == 360
    assert cycle["earned_ethics_minutes"] == 120
    assert read_credit_record(world["record_two"]["id"])["countable_minutes"] == 120


def test_projected_late_fee_is_derived_from_the_final_run_and_hits_its_cap(api):
    """The final run supplies `projected_final_total_minutes`, `projected_final_ethics_minutes`, `projected_final_technology_minutes`, `projected_final_bias_minutes`, `projected_final_live_minutes`, `projected_final_deficiency_total_minutes`, `projected_final_deficiency_ethics_minutes`, `projected_final_deficiency_technology_minutes` and `projected_final_deficiency_bias_minutes`.
    Step seven caps the total: `amount_cents` is the smaller of 100000 cents and the base plus surcharge.
    The same derivation is exposed, without persisting anything, as the `projected_late_fee_cents` field of the cycle summary read described in §3.6.

    Design: Difficulty/dual_variant_calc/provisional_versus_final_cycle_credit_application_on_compliance_cycle
    """
    world = _self_study_period_with_one_unverified_claim()

    summary = validate_success(
        api.get_cycle_summary(world["cycle"]["id"], BOARD), expected_status=200
    )

    assert summary["projected_final_deficiency_total_minutes"] == 1440
    assert summary["projected_final_deficiency_ethics_minutes"] == 180
    assert summary["projected_late_fee_cents"] == 100000


def test_certification_freezes_the_final_variant_and_carries_nothing_forward(api):
    """The credit application runs in its final variant over `VERIFIED` records only.
    The four deficiency figures of that final run then decide the outcome, and the fork is exhaustive: if the total deficiency is zero **and** all three specialty deficiencies are zero, `credit_status` moves `OPEN → SATISFIED`; if the total deficiency is above zero **or** any one specialty deficiency is above zero, `credit_status` moves `OPEN → DEFICIENT` and the attorney's `open_deficiency_count` rises by one.
    A deficient certification writes both `carryover_out_general_minutes` and `carryover_out_ethics_minutes` as zero: a period that fell short never carries anything forward, however large its raw total.

    Design: Difficulty/dual_variant_calc/provisional_versus_final_cycle_credit_application_on_compliance_cycle
    """
    world = _self_study_period_with_one_unverified_claim()
    attorney = world["attorney"]
    file_final_affirmation(world["cycle"]["id"], attorney["id"])

    cycle = validate_success(
        api.certify_cycle(
            world["cycle"]["id"], {}, make_attorney_headers(attorney["id"])
        ),
        expected_status=200,
    )

    assert cycle["credit_status"] == "DEFICIENT"
    assert cycle["earned_countable_minutes"] == 360
    assert cycle["earned_ethics_minutes"] == 0
    assert cycle["carryover_out_general_minutes"] == 0
    assert cycle["carryover_out_ethics_minutes"] == 0
    assert read_attorney(attorney["id"])["open_deficiency_count"] == 1


def test_certification_rewrites_every_record_to_its_final_variant_value(api):
    """The resulting `earned_countable_minutes`, `earned_ethics_minutes`, `earned_technology_minutes`, `earned_bias_minutes` and `earned_live_minutes` are frozen into the cycle, every credit record in the cycle has its `countable_minutes` rewritten to its final-variant value, and `certified_at` is stamped with the current logical instant.
    Every credit record of the cycle that was *not* in this variant's input set has its `countable_minutes` rewritten to zero, so the persisted per-record figures always reconcile against the cycle's earned totals for whichever variant last ran.

    Design: Difficulty/dual_variant_calc/provisional_versus_final_cycle_credit_application_on_compliance_cycle
    """
    world = _self_study_period_with_one_unverified_claim()
    attorney = world["attorney"]
    file_final_affirmation(world["cycle"]["id"], attorney["id"])

    validate_success(
        api.certify_cycle(
            world["cycle"]["id"], {}, make_attorney_headers(attorney["id"])
        ),
        expected_status=200,
    )

    assert read_credit_record(world["record_one"]["id"])["countable_minutes"] == 240
    assert read_credit_record(world["record_two"]["id"])["countable_minutes"] == 0
    assert read_credit_record(world["record_three"]["id"])["countable_minutes"] == 120


def _sponsor_with_both_pathways_and_two_findings():
    """A sponsor holding four courses, two individually approved and two
    self-certified, with a second audit sitting at two findings.

    The sponsor starts on probation so its first two courses take the review
    pathway, earns full accreditation through a cleared audit, and only then
    registers the two courses it certifies for itself. A later audit over a
    window holding only those two self-certified courses issues two findings.
    """
    provider = create_probationary_provider(
        name="Meridian CLE Partners", provider_type="GOVERNMENT"
    )
    sponsor_headers = make_provider_admin_headers(provider["id"])
    reviewed_courses = []
    for title, presented_at in (
        ("Pretrial Motions Intensive", "2026-06-05T09:00:00Z"),
        ("Discovery Sanctions Workshop", "2026-06-06T09:00:00Z"),
    ):
        course = create_self_certified_course(
            provider,
            title=title,
            delivery_format="SELF_STUDY",
            total_minutes=120,
            presented_at=presented_at,
            attendance_verification_method="AFFIRMATION_ONLY",
            credit_allocations=[credit_allocation_entry("GENERAL", 120)],
        )
        application = submit_application(course["id"], sponsor_headers)
        review_action(application["id"], "APPROVE")
        reviewed_courses.append(course)

    first_audit = open_audit(
        provider["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "RANDOM"
    )
    first_audit = audit_action(first_audit["id"], "DRAW_SAMPLE", first_audit["version"])
    first_audit = audit_action(
        first_audit["id"], "ISSUE_FINDINGS", first_audit["version"], findings_count=0
    )
    audit_action(first_audit["id"], "CLOSE_CLEARED", first_audit["version"])

    provider = read_provider(provider["id"])
    provider = accreditation_action(provider["id"], "GRANT_FULL", provider["version"])

    self_certified_courses = []
    for title, presented_at, category in (
        ("Client Trust Compliance", "2026-07-10T09:00:00Z", "GENERAL"),
        ("Legal Technology Survey", "2026-07-20T09:00:00Z", "TECHNOLOGY"),
    ):
        self_certified_courses.append(
            create_self_certified_course(
                provider,
                title=title,
                delivery_format="SELF_STUDY",
                total_minutes=180,
                presented_at=presented_at,
                attendance_verification_method="AFFIRMATION_ONLY",
                credit_allocations=[credit_allocation_entry(category, 180)],
            )
        )

    second_audit = open_audit(
        provider["id"], "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", "RANDOM"
    )
    second_audit = audit_action(
        second_audit["id"], "DRAW_SAMPLE", second_audit["version"]
    )
    second_audit = audit_action(
        second_audit["id"], "ISSUE_FINDINGS", second_audit["version"], findings_count=2
    )
    return {
        "provider": read_provider(provider["id"]),
        "reviewed_courses": reviewed_courses,
        "self_certified_courses": self_certified_courses,
        "second_audit": second_audit,
    }


def test_accredited_sponsor_judges_its_findings_against_the_self_certified_subset(api):
    """Under `SELF_CERTIFIED_WEIGHTING`, used when the provider's `accreditation_status` is exactly `ACCREDITED`, the denominator is `courses_self_certified_count` (treated as one when zero): an accredited sponsor certifies its own catalogue, so its findings are judged only against the courses it waved through itself.
    `risk_score` is then the delinquency rate weighted at 0.35, plus the complaint rate weighted at 0.30, plus the finding rate weighted at 0.25, plus the staleness rate weighted at 0.10, and the sum is rounded half-up to two decimal places.
    The count is added to the provider's `audit_findings_count` and the risk score is recomputed.

    Design: Difficulty/dual_variant_calc/self_certified_versus_reviewed_provider_risk_weighting
    """
    world = _sponsor_with_both_pathways_and_two_findings()
    provider = world["provider"]

    assert provider["accreditation_status"] == "ACCREDITED"
    assert provider["courses_total_count"] == 4
    assert provider["courses_self_certified_count"] == 2
    assert provider["audit_findings_count"] == 2
    assert provider["risk_score_variant"] == "SELF_CERTIFIED_WEIGHTING"
    assert provider["risk_score"] == pytest.approx(0.25, abs=0.001)


def test_probation_sanction_rescores_the_sponsor_under_the_reviewed_denominator(api):
    """Under `REVIEWED_WEIGHTING`, used for every other `accreditation_status` — `APPLIED`, `PROBATIONARY`, `SUSPENDED`, `LAPSED` or `DENIED` — the denominator is `courses_total_count` (again treated as one when zero), because every course such a sponsor offers passed board review.
    Since the self-certified subset can only be smaller than or equal to the whole catalogue, identical counters yield a rate that is at least as large, and a score that is strictly higher whenever the two counts differ, under the self-certified weighting.
    On an audit action that cascades a change to the provider's own `accreditation_status`, the recomputation happens **after** that cascade lands, so the variant chosen reflects the provider's post-cascade standing rather than its standing on arrival.

    Design: Difficulty/dual_variant_calc/self_certified_versus_reviewed_provider_risk_weighting
    """
    world = _sponsor_with_both_pathways_and_two_findings()
    audit = world["second_audit"]

    audit_action(
        audit["id"], "CLOSE_SANCTIONED", audit["version"], sanction_type="PROBATION"
    )

    provider = read_provider(world["provider"]["id"])
    assert provider["accreditation_status"] == "PROBATIONARY"
    assert provider["courses_total_count"] == 4
    assert provider["audit_findings_count"] == 2
    assert provider["risk_score_variant"] == "REVIEWED_WEIGHTING"
    assert provider["risk_score"] == pytest.approx(0.13, abs=0.001)


def test_sanctioned_closure_assesses_the_two_hundred_fifty_thousand_cent_fee(api):
    """`CLOSE_SANCTIONED` requires `findings_count` of at least one and a supplied `sanction_type` of `PROBATION` or `SUSPENSION`; it stamps `closed_at`, records the sanction, writes `last_audit_closed_at`, and assesses a `FeeAssessment` of `fee_type` `AUDIT_SANCTION` against the provider for 250000 cents.

    Design: Difficulty/dual_variant_calc/self_certified_versus_reviewed_provider_risk_weighting
    """
    world = _sponsor_with_both_pathways_and_two_findings()
    audit = world["second_audit"]

    closed = audit_action(
        audit["id"], "CLOSE_SANCTIONED", audit["version"], sanction_type="PROBATION"
    )
    assert closed["status"] == "SANCTIONED"
    assert closed["sanction_type"] == "PROBATION"

    sanction_fees = list_fee_assessments(
        provider_id=world["provider"]["id"], fee_type="AUDIT_SANCTION"
    )
    assert len(sanction_fees) == 1
    assert sanction_fees[0]["amount_cents"] == 250000
    assert sanction_fees[0]["status"] == "ASSESSED"


def test_low_tier_frozen_score_draws_two_courses_in_presentation_order(api):
    """The target size comes from the frozen score in three tiers: ten courses when `risk_score_at_open` is 0.60 or above, five when it is 0.30 or above but below 0.60, and two otherwise.
    The pool is ordered by `presented_at` ascending and then `created_at` ascending — never by identifier, and never randomly, so the same engagement over the same data always draws the same courses.
    The eligible pool is the audited provider's courses whose `status` is `APPROVED`, `EXPIRED` or `SUSPENDED_PENDING_REVIEW` and whose `presented_at` falls inside the audit's closed window, both endpoints included.

    Design: Difficulty/dual_variant_calc/self_certified_versus_reviewed_provider_risk_weighting
    """
    world = _sponsor_with_both_pathways_and_two_findings()
    audit = read_audit(world["second_audit"]["id"])

    assert audit["risk_score_at_open"] == pytest.approx(0.0, abs=0.001)
    assert audit["sample_size"] == 2
    assert audit["sampled_course_ids"] == [
        course["id"] for course in world["self_certified_courses"]
    ]
