"""Patient assessment instruments, transmission timeliness and QRP scoring."""

from test_helpers import (
    OFFICER_HEADERS,
    ApiErrorId,
    api_client,
    assert_assessment,
    assert_qrp_assessment,
    complete_assessment,
    complete_assessment_payload,
    create_assessment_payload,
    finalize_qrp_assessment,
    open_assessment,
    open_qrp_assessment,
    read_assessment,
    read_facility,
    set_clock,
    setup_discharged_stay,
    setup_facility_with_staff,
    setup_stay,
    validate_error,
    validate_success,
)

CODING_STAFF = ("nurse", "physician", "coder", "coder2")


def test_completing_an_instrument_with_an_unfinished_item_set_is_rejected():
    """The coder attests that the item set is not complete, so completion fails.

    PRD §3.9: "Completing the item set requires `item_set_complete` to be supplied
    as true; supplying false is `ERR_PAI_ITEM_SET_INCOMPLETE`."

    Design: Corner/state_machines/assessment_complete_with_incomplete_item_set_rejected
    """
    env = setup_facility_with_staff(staff=CODING_STAFF)
    stay = setup_stay(env)
    assessment = open_assessment(env, stay["admission"]["id"])
    assert_assessment(assessment)
    assert assessment["assessment_reference_date"] == "2026-08-07"
    assert assessment["completion_deadline_at"].startswith("2026-08-11T00:00:00")

    response = api_client.complete_assessment(
        assessment["id"], complete_assessment_payload(item_set_complete=False),
        env["coder_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PAI_ITEM_SET_INCOMPLETE)
    unchanged = read_assessment(assessment["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["completed_at"] is None


def test_transmitting_an_instrument_that_was_never_completed_is_rejected():
    """The item set is still in draft, so there is nothing to transmit.

    PRD §3.9: "When the clock is strictly earlier than `transmission_deadline_at`,
    the instrument moves from `COMPLETED` to `TRANSMITTED`, `transmitted_at` is
    stamped from the clock, `late_days` is 0, and `transmitted_by_clinician_id`
    records the acting coder."

    PRD §2.5: "the target resource must currently be in a state from which the
    requested transition is declared, else `ERR_INVALID_STATE` (409), on every
    transition endpoint"

    Design: Corner/endpoints/assessment_transmit_from_draft_rejected
    """
    env = setup_facility_with_staff(staff=CODING_STAFF)
    stay = setup_discharged_stay(env, "2026-08-11T12:00:00Z")
    assessment = open_assessment(env, stay["admission"]["id"],
                                 assessment_type="DISCHARGE")

    response = api_client.transmit_assessment(assessment["id"],
                                              env["coder2_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    unchanged = read_assessment(assessment["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["transmitted_at"] is None


def test_second_discharge_instrument_for_the_same_stay_is_rejected():
    """One live instrument per admission per type, and the type is already taken.

    PRD §3.9: "At most one instrument per admission per type may exist in any
    status other than `MISSED`; a duplicate is `ERR_ASSESSMENT_TYPE_DUPLICATE`."

    Design: Corner/validations/duplicate_discharge_assessment_rejected
    """
    env = setup_facility_with_staff(staff=CODING_STAFF)
    stay = setup_discharged_stay(env, "2026-08-11T12:00:00Z")
    first = open_assessment(env, stay["admission"]["id"],
                            assessment_type="DISCHARGE")

    response = api_client.create_assessment(
        create_assessment_payload(stay["admission"]["id"], env["coder"]["id"],
                                  "DISCHARGE"),
        env["coder_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ASSESSMENT_TYPE_DUPLICATE)
    assert read_assessment(first["id"])["status"] == "DRAFT"


def test_coder_named_on_the_instrument_may_not_transmit_it():
    """Transmission needs a second pair of eyes from another coder.

    PRD §2.9: "The coder transmitting an assessment instrument must not be the
    clinician named as `coder_clinician_id` on it."

    Design: Corner/rbac/assessment_transmitted_by_its_own_coder_rejected
    """
    env = setup_facility_with_staff(staff=CODING_STAFF)
    stay = setup_discharged_stay(env, "2026-08-11T12:00:00Z")
    assessment = open_assessment(env, stay["admission"]["id"],
                                 assessment_type="DISCHARGE")
    complete_assessment(env, assessment["id"])

    response = api_client.transmit_assessment(assessment["id"],
                                              env["coder_headers"])

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    unchanged = read_assessment(assessment["id"])
    assert unchanged["status"] == "COMPLETED"
    assert unchanged["transmitted_by_clinician_id"] is None


def test_finalising_a_quality_report_twice_is_rejected():
    """FINALIZED is terminal, so the penalty cannot be put into force again.

    PRD §3.9: "Finalisation recomputes all four metrics, stamps `finalized_at`
    from the logical clock, and moves the record from `DRAFT` to the terminal
    `FINALIZED`."

    Design: Corner/state_machines/qrp_assessment_finalize_twice_rejected
    """
    env = setup_facility_with_staff(staff=CODING_STAFF)
    setup_discharged_stay(env, "2026-08-11T12:00:00Z")
    qrp = open_qrp_assessment(env)
    finalized = finalize_qrp_assessment(qrp["id"])
    assert finalized["status"] == "FINALIZED"

    response = api_client.finalize_qrp_assessment(qrp["id"], OFFICER_HEADERS)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_late_transmitted_discharge_instrument_never_counts_as_timely():
    """The single discharge is one day late, so completeness is 0.00 percent.

    PRD §3.9: "`timely_count` is the number of cohort members holding a
    `DISCHARGE` assessment instrument whose `status` is `TRANSMITTED`; instruments
    in `LATE_TRANSMITTED`, `MISSED`, `COMPLETED` or `DRAFT` do not count."

    PRD §3.9: "`penalty_pct` is 0.00 when `data_completeness_pct` is greater than
    or equal to 95.00, and 2.00 otherwise; the pass test is inclusive, so exactly
    95.00 percent completeness avoids the penalty."

    Design: Corner/calculations/qrp_completeness_excludes_late_transmitted_discharge_assessment
    """
    env = setup_facility_with_staff(staff=CODING_STAFF)
    stay = setup_discharged_stay(env, "2026-08-11T12:00:00Z")
    assessment = open_assessment(env, stay["admission"]["id"],
                                 assessment_type="DISCHARGE")
    assert assessment["transmission_deadline_at"].startswith("2026-09-02T00:00:00")
    complete_assessment(env, assessment["id"])
    set_clock("2026-09-03T00:00:00Z")
    transmitted = validate_success(
        api_client.transmit_assessment(assessment["id"], env["coder2_headers"])
    )
    assert transmitted["status"] == "LATE_TRANSMITTED"
    assert transmitted["late_days"] == 1

    qrp = open_qrp_assessment(env)

    assert_qrp_assessment(qrp)
    assert qrp["cohort_count"] == 1
    assert qrp["timely_count"] == 0
    assert float(qrp["data_completeness_pct"]) == 0.00
    assert float(qrp["penalty_pct"]) == 2.00
    finalize_qrp_assessment(qrp["id"])
    assert float(read_facility(env["facility_id"])["active_qrp_penalty_pct"]) == 2.00


def test_timely_transmission_scores_full_completeness_and_no_penalty():
    """The only discharge was transmitted inside its window, so nothing is withheld.

    PRD §3.9: "`data_completeness_pct` is the timely count multiplied by 100,
    divided by `cohort_count`, rounded half up to two decimals — or exactly 0.00
    when the cohort is empty."

    Design: Corner/calculations/qrp_completeness_at_hundred_percent_yields_no_penalty
    """
    env = setup_facility_with_staff(staff=CODING_STAFF)
    stay = setup_discharged_stay(env, "2026-08-11T12:00:00Z")
    assessment = open_assessment(env, stay["admission"]["id"],
                                 assessment_type="DISCHARGE")
    complete_assessment(env, assessment["id"])
    set_clock("2026-08-12T09:00:00Z")
    transmitted = validate_success(
        api_client.transmit_assessment(assessment["id"], env["coder2_headers"])
    )
    assert transmitted["status"] == "TRANSMITTED"
    assert transmitted["late_days"] == 0

    qrp = open_qrp_assessment(env)

    assert qrp["cohort_count"] == 1
    assert qrp["timely_count"] == 1
    assert float(qrp["data_completeness_pct"]) == 100.00
    assert float(qrp["penalty_pct"]) == 0.00
    finalize_qrp_assessment(qrp["id"])
    assert float(read_facility(env["facility_id"])["active_qrp_penalty_pct"]) == 0.00
