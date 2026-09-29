"""Non-linear application/case state machines and the two deep cascade chains.

Covers the bounded UNDER_REVIEW -> DEFICIENT -> UNDER_REVIEW loop of the
licensure application, the two independent status axes of an enforcement case,
the five-link verification-withdrawal chain that ends at a test centre's seat
ledger, and the four-link consent-order chain that ends at a firm's draft plan
sets.
"""

from test_helpers import (
    BOARD_INVESTIGATOR_HEADERS,
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_LICENSING_OFFICER_2_HEADERS,
    BOARD_REVIEWER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    assert_seat_ledger,
    factories,
    fixtures,
    make_applicant_headers,
    make_supervising_engineer_headers,
    validate_error,
    validate_success,
)

INITIAL_CLOCK = "2026-08-01T00:00:00Z"
THIRTY_DAYS_ON = "2026-08-31T00:00:00.000Z"
NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS = 247500


# ---------------------------------------------------------------------------
# Local read helpers: every one re-reads a row through the public API so that
# cascaded side effects are observed rather than inferred.
# ---------------------------------------------------------------------------
def _read_application(api, application_id, engineer_id):
    return validate_success(
        api.get_application(application_id, make_applicant_headers(engineer_id)), 200
    )


def _read_experience_record(api, experience_record_id):
    return validate_success(
        api.get_experience_record(experience_record_id, BOARD_REVIEWER_HEADERS), 200
    )


def _read_reference(api, reference_id):
    return validate_success(api.get_reference(reference_id, BOARD_REVIEWER_HEADERS), 200)


def _read_authorization(api, exam_authorization_id):
    return validate_success(
        api.get_exam_authorization(exam_authorization_id, BOARD_REVIEWER_HEADERS), 200
    )


def _read_appointment(api, exam_appointment_id):
    return validate_success(
        api.get_exam_appointment(exam_appointment_id, BOARD_SECRETARY_HEADERS), 200
    )


def _read_test_center(api, test_center_id):
    return validate_success(
        api.get_test_center(test_center_id, BOARD_SECRETARY_HEADERS), 200
    )


def _read_license(api, license_id):
    return validate_success(
        api.get_license(license_id, BOARD_LICENSING_OFFICER_HEADERS), 200
    )


def _read_engineer(api, engineer_id):
    return validate_success(
        api.get_engineer(engineer_id, BOARD_SECRETARY_HEADERS), 200
    )


def _read_firm(api, firm_registration_id):
    return validate_success(
        api.get_firm_registration(firm_registration_id, BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )


def _read_plan(api, plan_submission_id):
    return validate_success(
        api.get_plan_submission(plan_submission_id, BOARD_LICENSING_OFFICER_HEADERS), 200
    )


def _read_case(api, case_id):
    return validate_success(api.get_case(case_id, BOARD_INVESTIGATOR_HEADERS), 200)


def _read_consent_order(api, consent_order_id):
    return validate_success(
        api.get_consent_order(consent_order_id, BOARD_INVESTIGATOR_HEADERS), 200
    )


# ---------------------------------------------------------------------------
# Local setup helpers built entirely out of the shared fixtures.
# ---------------------------------------------------------------------------
def _file_under_review(api):
    """One examination file taken under review with a submitted reference on it."""
    return fixtures.setup_exam_track(
        api,
        stop_after="under_review",
        submission_overrides={
            "evaluation_score": 5,
            "months_confirmed": 48,
            "responsibility_confirmed": True,
        },
    )


def _exam_approved_with_seat(api, blocks):
    """An examination file approved to sit with one booked seat.

    ``blocks`` is a list of (period_start_month, period_end_month) pairs; each
    pair becomes one RESPONSIBLE_CHARGE post-degree experience block carrying
    its own accepted DIRECT_SUPERVISOR verification.
    """
    applicant = fixtures.create_engineer(api)
    referee, referee_license = fixtures.create_licensed_engineer(api)
    application = fixtures.create_application(api, applicant["id"])
    fixtures.evaluate_education(api, application["id"])

    records = []
    references = []
    for start_month, end_month in blocks:
        record = fixtures.add_experience_record(
            api,
            application["id"],
            applicant["id"],
            period_start_month=start_month,
            period_end_month=end_month,
            responsibility_level="RESPONSIBLE_CHARGE",
            post_degree=True,
        )
        records.append(record)
        references.append(
            fixtures.request_reference(
                api,
                record["id"],
                applicant["id"],
                referee["id"],
                relationship="DIRECT_SUPERVISOR",
            )
        )

    fixtures.pay_assessed_fee(api, application["id"], applicant["id"])
    fixtures.submit_application(api, application["id"], applicant["id"])
    for reference in references:
        fixtures.submit_reference(
            api,
            reference["id"],
            referee["id"],
            evaluation_score=5,
            months_confirmed=48,
            responsibility_confirmed=True,
        )
    fixtures.start_review(api, application["id"])
    for reference in references:
        fixtures.evaluate_reference(api, reference["id"], "ACCEPT")

    fixtures.determine_credit(api, application["id"], BOARD_LICENSING_OFFICER_HEADERS)
    authorization = fixtures.approve_exam(
        api, application["id"], BOARD_LICENSING_OFFICER_2_HEADERS
    )
    center = fixtures.create_test_center(api, seat_labels=["S1", "S2"])
    appointment = fixtures.book_appointment(
        api, authorization["id"], center["id"], applicant["id"], seat_label="S1"
    )
    return {
        "applicant": applicant,
        "referee": referee,
        "referee_license": referee_license,
        "application": application,
        "records": records,
        "references": references,
        "authorization": authorization,
        "test_center": center,
        "appointment": appointment,
    }


def _firm_with_sealed_and_draft_plan(api):
    """A firm behind one ACTIVE licence holding one SEALED and one DRAFT plan set."""
    engineer, license_ = fixtures.create_licensed_engineer(api)
    firm = fixtures.create_firm(api, license_["id"])
    sealed = fixtures.create_plan_submission(
        api, firm["id"], project_name="Water Main Phase 1", sheet_count=4
    )
    sealed = fixtures.seal_plan(api, sealed["id"], license_["id"], engineer["id"])
    draft = fixtures.create_plan_submission(
        api, firm["id"], project_name="Water Main Phase 2", sheet_count=3
    )
    return {
        "engineer": engineer,
        "license": license_,
        "firm": firm,
        "sealed_plan": sealed,
        "draft_plan": draft,
    }


def _case_at_probable_cause_for(api, license_id):
    """A NEGLIGENCE complaint against one licence, investigated to probable cause."""
    case = fixtures.create_case(api, respondent_license_id=license_id)
    fixtures.open_investigation(api, case["id"])
    return fixtures.record_finding(
        api,
        case["id"],
        finding="PROBABLE_CAUSE",
        aggravating_factor_count=1,
        mitigating_factor_count=0,
        violation_count=1,
    )


# ---------------------------------------------------------------------------
# The bounded review loop: UNDER_REVIEW -> DEFICIENT -> UNDER_REVIEW
# ---------------------------------------------------------------------------
def test_review_loop_walks_three_deficiency_cycles_incrementing_the_counter(api):
    """PRD §3.4: "When the reviewer finds the file wanting, they issue a deficiency notice with a `deficiency_reason`, moving the file `UNDER_REVIEW → DEFICIENT`. That increments `deficiency_cycle_count` by 1, stores the reason, and sets `deficiency_due_at` to 30 days after the logical clock's current value."

    Design: Difficulty/non_linear_state_machine/application_deficiency_cycle_capped_at_three_fourth_rejected
    """
    track = _file_under_review(api)
    application_id = track["application"]["id"]
    engineer_id = track["engineer"]["id"]
    assert track["application"]["status"] == "UNDER_REVIEW"
    assert track["application"]["deficiency_cycle_count"] == 0

    reasons = (
        "Transcript legend missing",
        "Reference contact details unreadable",
        "Employer letterhead not verifiable",
    )
    for cycle, reason in enumerate(reasons, start=1):
        noticed = validate_success(
            api.raise_deficiency(
                application_id,
                factories.deficiency_payload(deficiency_reason=reason),
                BOARD_REVIEWER_HEADERS,
            ),
            200,
        )
        assert noticed["status"] == "DEFICIENT"
        assert noticed["deficiency_cycle_count"] == cycle
        assert noticed["deficiency_reason"] == reason
        assert noticed["deficiency_due_at"] == THIRTY_DAYS_ON

        cured = validate_success(
            api.respond_deficiency(
                application_id,
                factories.deficiency_response_payload(
                    response_note=f"Cured cycle {cycle}"
                ),
                make_applicant_headers(engineer_id),
            ),
            200,
        )
        assert cured["status"] == "UNDER_REVIEW"
        assert cured["deficiency_cycle_count"] == cycle
        assert cured["deficiency_reason"] is None
        assert cured["deficiency_due_at"] is None

    final = _read_application(api, application_id, engineer_id)
    assert final["status"] == "UNDER_REVIEW"
    assert final["deficiency_cycle_count"] == 3


def test_fourth_deficiency_notice_is_refused_and_leaves_the_file_under_review(api):
    """PRD §3.4: "The board tolerates three deficiency cycles in total: a notice attempted on a file whose `deficiency_cycle_count` already stands at 3 is refused with `ERR_DEFICIENCY_LIMIT_REACHED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/application_deficiency_cycle_capped_at_three_fourth_rejected
    """
    track = _file_under_review(api)
    application_id = track["application"]["id"]
    engineer_id = track["engineer"]["id"]

    for cycle in range(1, 4):
        fixtures.raise_deficiency(
            api, application_id, deficiency_reason=f"Cycle {cycle} finding"
        )
        fixtures.respond_deficiency(
            api, application_id, engineer_id, response_note=f"Cured cycle {cycle}"
        )

    before = _read_application(api, application_id, engineer_id)
    assert before["deficiency_cycle_count"] == 3
    assert before["status"] == "UNDER_REVIEW"

    validate_error(
        api.raise_deficiency(
            application_id,
            factories.deficiency_payload(
                deficiency_reason="Fourth attempt at a deficiency notice"
            ),
            BOARD_REVIEWER_HEADERS,
        ),
        "ERR_DEFICIENCY_LIMIT_REACHED",
    )

    after = _read_application(api, application_id, engineer_id)
    assert after["status"] == "UNDER_REVIEW"
    assert after["deficiency_cycle_count"] == 3
    assert after["deficiency_reason"] is None
    assert after["deficiency_due_at"] is None
    assert after["version"] == before["version"]


def test_curing_a_deficiency_never_decrements_the_deficiency_cycle_count(api):
    """PRD §3.4: "A successful response clears both `deficiency_reason` and `deficiency_due_at` back to `null`, leaves `deficiency_cycle_count` where it stands, and re-runs the self-reported experience figure so that any blocks added during the deficiency period are reflected."

    Design: Difficulty/non_linear_state_machine/application_deficiency_cycle_capped_at_three_fourth_rejected
    """
    track = _file_under_review(api)
    application_id = track["application"]["id"]
    engineer_id = track["engineer"]["id"]

    fixtures.raise_deficiency(
        api, application_id, deficiency_reason="Employment dates unclear"
    )
    cured = validate_success(
        api.respond_deficiency(
            application_id,
            factories.deficiency_response_payload(response_note="Dates confirmed"),
            make_applicant_headers(engineer_id),
        ),
        200,
    )
    assert cured["status"] == "UNDER_REVIEW"
    assert cured["deficiency_cycle_count"] == 1
    assert cured["deficiency_reason"] is None
    assert cured["deficiency_due_at"] is None
    assert cured["provisional_experience_months"] == 48

    second = validate_success(
        api.raise_deficiency(
            application_id,
            factories.deficiency_payload(deficiency_reason="Second look required"),
            BOARD_REVIEWER_HEADERS,
        ),
        200,
    )
    assert second["status"] == "DEFICIENT"
    assert second["deficiency_cycle_count"] == 2
    assert second["deficiency_due_at"] == THIRTY_DAYS_ON


# ---------------------------------------------------------------------------
# Two independent case axes: the sanction axis moves while the investigation
# axis holds, and the close is a predicate over both.
# ---------------------------------------------------------------------------
def test_hearing_referral_moves_only_the_sanction_axis_then_unlocks_the_close(api):
    """PRD §3.9: "From `NONE` or from `PROPOSED`, and only while `investigation_status` is `PROBABLE_CAUSE`, the sanction axis moves to `HEARING_REFERRED`; when it was standing at `PROPOSED`, the outstanding order is dragged `PROPOSED → SUPERSEDED` on the way."

    Design: Difficulty/non_linear_state_machine/case_parallel_axes_sanction_moves_while_investigation_holds
    """
    setup = fixtures.setup_case_at_probable_cause(api)
    case = setup["case"]
    assert case["investigation_status"] == "PROBABLE_CAUSE"
    assert case["sanction_status"] == "NONE"
    assert round(case["penalty_factor"], 2) == 1.25
    assert case["assessed_penalty_cents"] == NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS

    order = fixtures.propose_consent_order(
        api, case["id"], case["version"], sanction_type="REPRIMAND"
    )
    assert order["status"] == "PROPOSED"
    assert order["penalty_cents"] == NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS
    proposed = _read_case(api, case["id"])
    assert proposed["sanction_status"] == "PROPOSED"
    assert proposed["investigation_status"] == "PROBABLE_CAUSE"
    assert _read_engineer(api, setup["engineer"]["id"])["open_case_count"] == 1

    referred = validate_success(
        api.refer_hearing(case["id"], BOARD_INVESTIGATOR_HEADERS), 200
    )
    assert referred["sanction_status"] == "HEARING_REFERRED"
    assert referred["investigation_status"] == "PROBABLE_CAUSE"

    superseded = _read_consent_order(api, order["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["penalty_cents"] == NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS
    assert superseded["executed_on"] is None
    assert superseded["executed_by_user_id"] is None
    assert superseded["version"] == order["version"] + 1

    closed = validate_success(api.close_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert closed["investigation_status"] == "CLOSED"
    assert closed["sanction_status"] == "HEARING_REFERRED"
    assert closed["assessed_penalty_cents"] == NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS

    assert _read_license(api, setup["license"]["id"])["status"] == "ACTIVE"
    assert _read_engineer(api, setup["engineer"]["id"])["open_case_count"] == 0


def test_close_is_refused_while_a_proposed_consent_order_is_outstanding(api):
    """PRD §3.9: "A close attempted while the sanction axis sits at `NONE` behind a probable-cause finding, or at `PROPOSED`, is refused with `ERR_OPEN_SANCTION_BLOCKS_CLOSE` (HTTP 409) — the board does not close a case with an outstanding proposal on the table."

    Design: Difficulty/non_linear_state_machine/case_parallel_axes_sanction_moves_while_investigation_holds
    """
    setup = fixtures.setup_case_at_probable_cause(api)
    case = setup["case"]
    order = fixtures.propose_consent_order(
        api, case["id"], case["version"], sanction_type="REPRIMAND"
    )
    before = _read_case(api, case["id"])
    assert before["sanction_status"] == "PROPOSED"

    validate_error(
        api.close_case(case["id"], BOARD_INVESTIGATOR_HEADERS),
        "ERR_OPEN_SANCTION_BLOCKS_CLOSE",
    )

    after = _read_case(api, case["id"])
    assert after["investigation_status"] == "PROBABLE_CAUSE"
    assert after["sanction_status"] == "PROPOSED"
    assert after["version"] == before["version"]
    assert _read_consent_order(api, order["id"])["status"] == "PROPOSED"
    assert _read_engineer(api, setup["engineer"]["id"])["open_case_count"] == 1


def test_close_is_refused_when_the_sanction_axis_still_stands_at_none(api):
    """PRD §3.9: "From `PROBABLE_CAUSE` the sanction axis must have resolved to `CONSENT_EXECUTED` or `HEARING_REFERRED`; from `NO_CAUSE` the sanction axis must still be `NONE`."

    Design: Difficulty/non_linear_state_machine/case_parallel_axes_sanction_moves_while_investigation_holds
    """
    setup = fixtures.setup_case_at_probable_cause(api)
    case = setup["case"]
    assert case["sanction_status"] == "NONE"

    validate_error(
        api.close_case(case["id"], BOARD_INVESTIGATOR_HEADERS),
        "ERR_OPEN_SANCTION_BLOCKS_CLOSE",
    )

    after = _read_case(api, case["id"])
    assert after["investigation_status"] == "PROBABLE_CAUSE"
    assert after["sanction_status"] == "NONE"
    assert after["version"] == case["version"]
    assert _read_engineer(api, setup["engineer"]["id"])["open_case_count"] == 1

    referred = validate_success(
        api.refer_hearing(case["id"], BOARD_INVESTIGATOR_HEADERS), 200
    )
    assert referred["sanction_status"] == "HEARING_REFERRED"
    assert referred["investigation_status"] == "PROBABLE_CAUSE"
    reclosed = validate_success(
        api.close_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200
    )
    assert reclosed["investigation_status"] == "CLOSED"


# ---------------------------------------------------------------------------
# The verification-withdrawal chain: reference -> block -> file -> authorization
# -> appointment -> seat ledger
# ---------------------------------------------------------------------------
RECANT_REASON = "Supervision was indirect for the 2021-2022 portion"


def test_recant_cascades_through_five_links_to_the_seat_ledger(api):
    """PRD §3.3: "Third, caused by the second link, the file's `verified_experience_months` is recomputed; and if the file was standing in `EXAM_APPROVED` and the recomputed total has fallen below 48 months, the file moves `EXAM_APPROVED → DEFICIENT`, which increments `deficiency_cycle_count` by 1, sets `deficiency_reason` to the string `EXPERIENCE_CREDIT_WITHDRAWN` and sets `deficiency_due_at` to 30 days after the logical clock's current value."

    Design: Difficulty/transitive_cascade/reference_recant_cascades_five_links_to_seat_release
    """
    setup = _exam_approved_with_seat(api, [("2022-01", "2025-12")])
    applicant_id = setup["applicant"]["id"]
    application_id = setup["application"]["id"]
    record = setup["records"][0]
    reference = setup["references"][0]
    authorization = setup["authorization"]
    appointment = setup["appointment"]

    before_application = _read_application(api, application_id, applicant_id)
    assert before_application["status"] == "EXAM_APPROVED"
    assert before_application["verified_experience_months"] == 48
    assert before_application["deficiency_cycle_count"] == 0
    assert _read_experience_record(api, record["id"])["credited_months"] == 48
    before_authorization = _read_authorization(api, authorization["id"])
    assert before_authorization["status"] == "SCHEDULED"
    before_appointment = _read_appointment(api, appointment["id"])
    assert before_appointment["status"] == "SCHEDULED"
    before_center = _read_test_center(api, setup["test_center"]["id"])
    assert_seat_ledger(before_center, seat_count=2, committed=1, available=1)
    before_reference = _read_reference(api, reference["id"])
    assert before_reference["status"] == "ACCEPTED"

    recanted = validate_success(
        api.recant_reference(
            reference["id"],
            {"recant_reason": RECANT_REASON},
            make_supervising_engineer_headers(setup["referee"]["id"]),
        ),
        200,
    )

    # Link one: the verification request itself.
    assert recanted["status"] == "RECANTED"
    assert recanted["recant_reason"] == RECANT_REASON
    assert recanted["version"] == before_reference["version"] + 1

    # Link two: the experience block it attested.
    recanted_record = _read_experience_record(api, record["id"])
    assert recanted_record["verification_status"] == "RECANTED"
    assert recanted_record["credited_months"] == 0

    # Link three: the file's credit ledger and its fall into a deficiency cycle.
    after_application = _read_application(api, application_id, applicant_id)
    assert after_application["verified_experience_months"] == 0
    assert after_application["status"] == "DEFICIENT"
    assert after_application["deficiency_cycle_count"] == 1
    assert after_application["deficiency_reason"] == "EXPERIENCE_CREDIT_WITHDRAWN"
    assert after_application["deficiency_due_at"] == THIRTY_DAYS_ON
    assert after_application["provisional_experience_months"] == 48

    # Link four: the examination authorization.
    after_authorization = _read_authorization(api, authorization["id"])
    assert after_authorization["status"] == "CANCELLED"
    assert after_authorization["version"] == before_authorization["version"] + 1

    # Link five: the appointment and the owning centre's seat ledger.
    after_appointment = _read_appointment(api, appointment["id"])
    assert after_appointment["status"] == "CANCELLED_BY_BOARD"
    assert after_appointment["version"] == before_appointment["version"] + 1
    after_center = _read_test_center(api, setup["test_center"]["id"])
    assert_seat_ledger(after_center, seat_count=2, committed=0, available=2)
    assert after_center["version"] == before_center["version"] + 1


def test_recant_stops_before_link_four_when_credit_stays_at_the_floor(api):
    """PRD §3.3: "Fourth, caused by the third link and not by the withdrawal itself, the file's exam authorization — if it stands in `APPROVED_TO_SIT` or `SCHEDULED` — moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/reference_recant_cascades_five_links_to_seat_release
    """
    setup = _exam_approved_with_seat(
        api, [("2018-01", "2021-12"), ("2022-01", "2025-12")]
    )
    applicant_id = setup["applicant"]["id"]
    application_id = setup["application"]["id"]
    kept_record, dropped_record = setup["records"][1], setup["records"][0]
    dropped_reference = setup["references"][0]

    before_application = _read_application(api, application_id, applicant_id)
    assert before_application["status"] == "EXAM_APPROVED"
    assert before_application["verified_experience_months"] == 96
    before_authorization = _read_authorization(api, setup["authorization"]["id"])
    before_appointment = _read_appointment(api, setup["appointment"]["id"])
    before_center = _read_test_center(api, setup["test_center"]["id"])

    recanted = validate_success(
        api.recant_reference(
            dropped_reference["id"],
            {"recant_reason": RECANT_REASON},
            make_supervising_engineer_headers(setup["referee"]["id"]),
        ),
        200,
    )
    assert recanted["status"] == "RECANTED"

    assert _read_experience_record(api, dropped_record["id"])["verification_status"] == (
        "RECANTED"
    )
    assert _read_experience_record(api, dropped_record["id"])["credited_months"] == 0
    surviving = _read_experience_record(api, kept_record["id"])
    assert surviving["verification_status"] == "VERIFIED"
    assert surviving["credited_months"] == 48

    after_application = _read_application(api, application_id, applicant_id)
    assert after_application["verified_experience_months"] == 48
    assert after_application["status"] == "EXAM_APPROVED"
    assert after_application["deficiency_cycle_count"] == 0
    assert after_application["deficiency_reason"] is None
    assert after_application["deficiency_due_at"] is None

    after_authorization = _read_authorization(api, setup["authorization"]["id"])
    assert after_authorization["status"] == "SCHEDULED"
    assert after_authorization["version"] == before_authorization["version"]
    after_appointment = _read_appointment(api, setup["appointment"]["id"])
    assert after_appointment["status"] == "SCHEDULED"
    assert after_appointment["version"] == before_appointment["version"]
    after_center = _read_test_center(api, setup["test_center"]["id"])
    assert_seat_ledger(after_center, seat_count=2, committed=1, available=1)
    assert after_center["version"] == before_center["version"]


def test_recanting_a_reference_still_awaiting_board_evaluation_is_refused(api):
    """PRD §3.3: "A `SupervisingEngineer` may withdraw a verification that stands in `ACCEPTED`, supplying `recant_reason`, provided the parent file is in `UNDER_REVIEW`, `DEFICIENT` or `EXAM_APPROVED` — a withdrawal against an already-issued or denied file has no purchase and is refused as a state conflict."

    Design: Difficulty/transitive_cascade/reference_recant_cascades_five_links_to_seat_release
    """
    track = _file_under_review(api)
    reference = track["reference"]
    record = track["experience_record"]
    assert reference["status"] == "SUBMITTED"

    validate_error(
        api.recant_reference(
            reference["id"],
            {"recant_reason": RECANT_REASON},
            make_supervising_engineer_headers(track["referee"]["id"]),
        ),
        "ERR_REFERENCE_STATE_INVALID",
    )

    unchanged_reference = _read_reference(api, reference["id"])
    assert unchanged_reference["status"] == "SUBMITTED"
    assert unchanged_reference["recant_reason"] is None
    assert unchanged_reference["version"] == reference["version"]
    unchanged_record = _read_experience_record(api, record["id"])
    assert unchanged_record["verification_status"] == "PENDING_VERIFICATION"
    assert unchanged_record["credited_months"] == 0
    application = _read_application(
        api, track["application"]["id"], track["engineer"]["id"]
    )
    assert application["status"] == "UNDER_REVIEW"
    assert application["verified_experience_months"] == 0


# ---------------------------------------------------------------------------
# The consent-order chain: order -> licence -> firm -> draft plan sets
# ---------------------------------------------------------------------------
def test_suspension_execution_cascades_four_links_and_voids_only_the_draft_plan(api):
    """PRD §3.9: "Link four, caused by link three, reaches every `DRAFT` plan set beneath those firms and voids it; sets already `SEALED` are untouched."

    Design: Difficulty/transitive_cascade/consent_order_execution_cascades_four_links_to_plan_void
    """
    setup = _firm_with_sealed_and_draft_plan(api)
    case = _case_at_probable_cause_for(api, setup["license"]["id"])
    assert case["assessed_penalty_cents"] == NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS

    order = fixtures.propose_consent_order(
        api,
        case["id"],
        case["version"],
        sanction_type="SUSPENSION",
        suspension_months=12,
        penalty_paid_cents=NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS,
    )
    assert order["status"] == "PROPOSED"
    assert order["penalty_cents"] == NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS

    before_license = _read_license(api, setup["license"]["id"])
    before_firm = _read_firm(api, setup["firm"]["id"])
    before_draft = _read_plan(api, setup["draft_plan"]["id"])
    before_sealed = _read_plan(api, setup["sealed_plan"]["id"])
    assert before_license["status"] == "ACTIVE"
    assert before_firm["status"] == "ACTIVE"
    assert before_draft["status"] == "DRAFT"
    assert before_sealed["status"] == "SEALED"

    # Link one: the order and the case's sanction axis.
    executed = validate_success(
        api.execute_consent_order(
            order["id"],
            factories.execute_payload(executed_on=INITIAL_CLOCK),
            BOARD_LICENSING_OFFICER_HEADERS,
        ),
        200,
    )
    assert executed["status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == "LIC-1"
    assert executed["executed_on"].startswith("2026-08-01T00:00:00")
    assert executed["penalty_cents"] == NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS
    after_case = _read_case(api, case["id"])
    assert after_case["sanction_status"] == "CONSENT_EXECUTED"
    assert after_case["investigation_status"] == "PROBABLE_CAUSE"

    # Link two: the respondent's licence.
    after_license = _read_license(api, setup["license"]["id"])
    assert after_license["status"] == "SUSPENDED"
    assert after_license["suspension_ends_at"] == "2027-08-01T00:00:00.000Z"
    assert after_license["discipline_flag"] is True
    assert after_license["version"] == before_license["version"] + 1
    assert _read_engineer(api, setup["engineer"]["id"])["active_license_number"] is None

    # Link three: the firm the licence held in responsible charge.
    after_firm = _read_firm(api, setup["firm"]["id"])
    assert after_firm["status"] == "LAPSED_NO_RESPONSIBLE_CHARGE"
    assert after_firm["version"] == before_firm["version"] + 1

    # Link four: only the DRAFT plan set beneath that firm.
    after_draft = _read_plan(api, setup["draft_plan"]["id"])
    assert after_draft["status"] == "VOIDED"
    assert after_draft["version"] == before_draft["version"] + 1
    after_sealed = _read_plan(api, setup["sealed_plan"]["id"])
    assert after_sealed["status"] == "SEALED"
    assert after_sealed["version"] == before_sealed["version"]
    assert after_sealed["seal_affixed_at"] == before_sealed["seal_affixed_at"]


def test_revocation_execution_drives_the_firm_to_revoked_and_voids_its_draft_plan(api):
    """PRD §3.9: "Link three, caused by link two, reaches every firm holding that licence in responsible charge, lapsing it into `LAPSED_NO_RESPONSIBLE_CHARGE` on a suspension and moving it to `REVOKED` on a revocation, exactly as the posture rule dictates."

    Design: Difficulty/transitive_cascade/consent_order_execution_cascades_four_links_to_plan_void
    """
    setup = _firm_with_sealed_and_draft_plan(api)
    case = _case_at_probable_cause_for(api, setup["license"]["id"])
    order = fixtures.propose_consent_order(
        api,
        case["id"],
        case["version"],
        sanction_type="REVOCATION",
        penalty_paid_cents=NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS,
    )

    executed = validate_success(
        api.execute_consent_order(
            order["id"],
            factories.execute_payload(executed_on=INITIAL_CLOCK),
            BOARD_LICENSING_OFFICER_HEADERS,
        ),
        200,
    )
    assert executed["status"] == "EXECUTED"
    assert executed["sanction_type"] == "REVOCATION"

    after_license = _read_license(api, setup["license"]["id"])
    assert after_license["status"] == "REVOKED"
    assert after_license["discipline_flag"] is True
    assert _read_engineer(api, setup["engineer"]["id"])["active_license_number"] is None
    assert _read_firm(api, setup["firm"]["id"])["status"] == "REVOKED"
    assert _read_plan(api, setup["draft_plan"]["id"])["status"] == "VOIDED"
    assert _read_plan(api, setup["sealed_plan"]["id"])["status"] == "SEALED"
    assert _read_case(api, case["id"])["sanction_status"] == "CONSENT_EXECUTED"


def test_reprimand_execution_stops_at_link_two_leaving_firm_and_plans_intact(api):
    """PRD §3.9: "A `REPRIMAND` stops the chain at link two, because the licence never leaves `ACTIVE` and therefore no firm posture changes."

    Design: Difficulty/transitive_cascade/consent_order_execution_cascades_four_links_to_plan_void
    """
    setup = _firm_with_sealed_and_draft_plan(api)
    case = _case_at_probable_cause_for(api, setup["license"]["id"])
    order = fixtures.propose_consent_order(
        api,
        case["id"],
        case["version"],
        sanction_type="REPRIMAND",
        penalty_paid_cents=NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS,
    )

    before_firm = _read_firm(api, setup["firm"]["id"])
    before_draft = _read_plan(api, setup["draft_plan"]["id"])

    executed = validate_success(
        api.execute_consent_order(
            order["id"],
            factories.execute_payload(executed_on=INITIAL_CLOCK),
            BOARD_LICENSING_OFFICER_HEADERS,
        ),
        200,
    )
    assert executed["status"] == "EXECUTED"
    assert executed["sanction_type"] == "REPRIMAND"

    after_license = _read_license(api, setup["license"]["id"])
    assert after_license["status"] == "ACTIVE"
    assert after_license["discipline_flag"] is True
    assert after_license["suspension_ends_at"] is None
    engineer = _read_engineer(api, setup["engineer"]["id"])
    assert engineer["active_license_number"] == setup["license"]["license_number"]

    after_firm = _read_firm(api, setup["firm"]["id"])
    assert after_firm["status"] == "ACTIVE"
    assert after_firm["version"] == before_firm["version"]
    after_draft = _read_plan(api, setup["draft_plan"]["id"])
    assert after_draft["status"] == "DRAFT"
    assert after_draft["version"] == before_draft["version"]
    assert _read_plan(api, setup["sealed_plan"]["id"])["status"] == "SEALED"
    assert _read_case(api, case["id"])["sanction_status"] == "CONSENT_EXECUTED"


def test_unpaid_penalty_blocks_execution_and_no_link_of_the_chain_fires(api):
    """PRD §3.9: "The acting `X-User-ID` must differ from the case's `assigned_investigator_user_id`, and `penalty_paid_cents` must be at least `penalty_cents` — an unpaid penalty is refused with `ERR_PENALTY_UNPAID` (HTTP 402), which is the last rung of the ladder and therefore the error a request sees only once everything else about it is in order."

    Design: Difficulty/transitive_cascade/consent_order_execution_cascades_four_links_to_plan_void
    """
    setup = _firm_with_sealed_and_draft_plan(api)
    case = _case_at_probable_cause_for(api, setup["license"]["id"])
    order = fixtures.propose_consent_order(
        api,
        case["id"],
        case["version"],
        sanction_type="SUSPENSION",
        suspension_months=12,
        penalty_paid_cents=0,
    )
    assert order["penalty_cents"] == NEGLIGENCE_ONE_AGGRAVATOR_PENALTY_CENTS

    before_license = _read_license(api, setup["license"]["id"])
    before_firm = _read_firm(api, setup["firm"]["id"])
    before_draft = _read_plan(api, setup["draft_plan"]["id"])
    before_case = _read_case(api, case["id"])

    validate_error(
        api.execute_consent_order(
            order["id"],
            factories.execute_payload(executed_on=INITIAL_CLOCK),
            BOARD_LICENSING_OFFICER_HEADERS,
        ),
        "ERR_PENALTY_UNPAID",
    )

    unchanged_order = _read_consent_order(api, order["id"])
    assert unchanged_order["status"] == "PROPOSED"
    assert unchanged_order["executed_on"] is None
    assert unchanged_order["executed_by_user_id"] is None
    assert unchanged_order["version"] == order["version"]

    after_case = _read_case(api, case["id"])
    assert after_case["sanction_status"] == "PROPOSED"
    assert after_case["investigation_status"] == "PROBABLE_CAUSE"
    assert after_case["version"] == before_case["version"]

    after_license = _read_license(api, setup["license"]["id"])
    assert after_license["status"] == "ACTIVE"
    assert after_license["discipline_flag"] is False
    assert after_license["version"] == before_license["version"]
    engineer = _read_engineer(api, setup["engineer"]["id"])
    assert engineer["active_license_number"] == setup["license"]["license_number"]

    after_firm = _read_firm(api, setup["firm"]["id"])
    assert after_firm["status"] == "ACTIVE"
    assert after_firm["version"] == before_firm["version"]
    after_draft = _read_plan(api, setup["draft_plan"]["id"])
    assert after_draft["status"] == "DRAFT"
    assert after_draft["version"] == before_draft["version"]
    assert _read_plan(api, setup["sealed_plan"]["id"])["status"] == "SEALED"
