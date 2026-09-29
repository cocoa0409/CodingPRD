"""State machine edges: valid transitions, guards, birth states, cycles, forks and cascades."""

from test_helpers import (
    AUDITOR_ADJUDICATOR_ID,
    AUDITOR_DRAWER_ID,
    NATIONAL_VERIFIER,
    PROGRAM_ADMIN,
    PROGRAM_ADMIN_ID,
    ApiErrorId,
    assert_audit_sample,
    assert_date_component,
    assert_device,
    assert_device_counters,
    assert_eligibility_check,
    assert_enrollment,
    assert_household_address,
    assert_instant,
    assert_instant_null,
    assert_reimbursement_claim,
    assert_service_transfer,
    assert_subscriber_case,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
CHECK_EXPIRY = "2026-10-30T00:00:00Z"
PORT_FREEZE_UNTIL = "2026-09-30T00:00:00Z"
RECERT_DUE = "2027-08-01"

FIRST_DE_ENROLL = "2026-08-10T00:00:00Z"
APPEAL_DEADLINE = "2026-09-09T23:59:59.999Z"
REPLAY_INSTANT = "2026-08-20T00:00:00Z"

FIRST_FLAG = "2026-08-31T00:00:00Z"
FIRST_EXPIRY = "2026-09-16T00:00:00Z"
SECOND_START = "2026-09-17T00:00:00Z"
SECOND_FLAG = "2026-10-17T00:00:00Z"
SECOND_EXPIRY = "2026-11-02T00:00:00Z"

JUNE_START = "2026-06-01T00:00:00Z"
JULY_FILING = "2026-07-02T00:00:00Z"

DAMAGED_RETURN = "2026-08-02T00:00:00Z"
SECOND_ISSUE = "2026-08-03T00:00:00Z"


def test_the_bounced_check_returns_to_pending_and_can_still_be_confirmed(api):
    """DOCUMENTATION_REQUIRED is a parking state, not a terminal one: both edges fire in order.

    PRD: "A successful resubmission returns the check `DOCUMENTATION_REQUIRED →
    PENDING_VERIFIER`, increments `resubmission_count` by one, and clears `verifier_outcome`
    and `verifier_reason_code` back to null so the verifier faces a clean slate."

    Design: Corner/state_machines/eligibility_check_documentation_loop_returns_to_pending_verifier
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.create_subscriber(api, address["id"])
    check = fx.open_eligibility_check(
        api, applicant["id"], claimed_basis="INCOME", proof_document_ref="DOC-M1"
    )

    bounced = validate_success(
        api.submit_verifier_result(
            check["id"],
            f.verifier_result_payload(
                verifier_outcome="DOCUMENTATION_REQUIRED",
                verifier_reason_code="INCOME_PROOF_ILLEGIBLE",
            ),
            NATIONAL_VERIFIER,
        )
    )
    assert bounced["status"] == "DOCUMENTATION_REQUIRED"
    assert bounced["subscriber_id"] == applicant["id"], "the check keeps its parent"
    assert bounced["verifier_reason_code"] == "INCOME_PROOF_ILLEGIBLE"
    assert fx.refresh_subscriber(api, applicant["id"])["status"] == "ELIGIBILITY_PENDING", (
        "a bounced check leaves the applicant mid-screening, not back at PROSPECT"
    )

    rearmed = validate_success(
        api.resubmit_documentation(
            check["id"],
            f.resubmit_documentation_payload(proof_document_ref="DOC-M1-REV2"),
            fx.provider_headers(provider),
        )
    )
    assert rearmed["status"] == "PENDING_VERIFIER", (
        f"the resubmission re-arms the check, got {rearmed['status']}"
    )
    assert rearmed["resubmission_count"] == 1
    assert rearmed["proof_document_ref"] == "DOC-M1-REV2", "the replacement reference overwrites"
    assert rearmed["verifier_outcome"] is None, "the verifier faces a clean slate"
    assert rearmed["verifier_reason_code"] is None

    confirmed = validate_success(
        api.submit_verifier_result(
            check["id"], f.verifier_result_payload(verifier_outcome="MATCH"), NATIONAL_VERIFIER
        )
    )
    assert_eligibility_check(confirmed)
    assert confirmed["status"] == "ELIGIBLE_CONFIRMED"
    assert_instant(confirmed["confirmed_at"], CLOCK, "confirmed_at")
    assert_instant(confirmed["expires_at"], CHECK_EXPIRY, "expires_at")

    settled = fx.refresh_subscriber(api, applicant["id"])
    assert settled["status"] == "VERIFIED_ELIGIBLE"
    assert settled["eligibility_basis"] == "INCOME"


def test_a_second_verifier_determination_on_a_confirmed_check_is_refused(api):
    """The PENDING_VERIFIER guard is enforced, and the later clock rewrites nothing.

    PRD: "Only the `NationalVerifier` role may post a determination, and only onto a check
    that is still `PENDING_VERIFIER` — a second determination on the same check is refused
    with `ERR_ELIGIBILITY_CHECK_NOT_PENDING`."

    Design: Corner/state_machines/verifier_result_on_confirmed_check_returns_check_not_pending
    """
    fx.set_clock(api, CLOCK)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.create_subscriber(api, address["id"])
    check = fx.open_eligibility_check(api, applicant["id"])
    confirmed = fx.confirm_eligibility_check(api, check["id"])
    assert confirmed["status"] == "ELIGIBLE_CONFIRMED"
    assert_instant(confirmed["expires_at"], CHECK_EXPIRY, "expires_at")

    fx.set_clock(api, "2026-08-15T00:00:00Z")
    response = api.submit_verifier_result(
        check["id"],
        f.verifier_result_payload(
            verifier_outcome="NO_MATCH", verifier_reason_code="LATE_REVERSAL"
        ),
        NATIONAL_VERIFIER,
    )
    validate_error(response, ApiErrorId.ELIGIBILITY_CHECK_NOT_PENDING.value, 409)

    untouched = fx.refresh_eligibility_check(api, check["id"])
    assert untouched["status"] == "ELIGIBLE_CONFIRMED"
    assert untouched["verifier_outcome"] == "MATCH", "the first determination stands"
    assert_instant(untouched["confirmed_at"], CLOCK, "confirmed_at")
    assert_instant(untouched["expires_at"], CHECK_EXPIRY, "expires_at")
    assert untouched["verifier_reason_code"] is None, (
        "the refused determination wrote no reason code"
    )
    assert fx.refresh_subscriber(api, applicant["id"])["status"] == "VERIFIED_ELIGIBLE"


def test_creating_the_benefit_writes_both_anchors_and_settles_three_neighbours(api):
    """One create writes the two derived windows, three zeroed counters and three neighbours.

    PRD: "`port_freeze_until` is the date component of `benefit_start_date` plus 60 days,
    stamped at `00:00:00.000Z`; it governs §3.7. `recert_due_date` is the date component of
    `benefit_start_date` plus 365 days; it governs §3.5."

    Design: Corner/state_machines/enrollment_creation_side_effects_write_all_three_windows_and_counters
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api, licensed_state_codes=["TX"], enrollment_cap=50)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])

    benefit = validate_success(
        api.create_enrollment(
            f.enrollment_payload(
                subscriber_id=applicant["subscriber"]["id"],
                provider_id=provider["id"],
                eligibility_check_id=applicant["check"]["id"],
                certified_address_id=address["id"],
                service_type="BUNDLED",
            ),
            fx.provider_headers(provider),
        ),
        201,
    )
    assert_enrollment(benefit)
    assert benefit["service_type"] == "BUNDLED"
    assert_instant(benefit["benefit_start_date"], CLOCK, "benefit_start_date")
    assert_instant(benefit["port_freeze_until"], PORT_FREEZE_UNTIL, "port_freeze_until")
    assert_date_component(benefit["recert_due_date"], RECERT_DUE, "recert_due_date")
    assert benefit["benefit_status"] == "ACTIVE"
    assert_instant_null(benefit["benefit_end_date"], "benefit_end_date")
    assert_instant_null(benefit["appeal_deadline_at"], "appeal_deadline_at")
    assert benefit["transfer_count"] == 0
    assert benefit["device_issuance_count"] == 0
    assert benefit["reinstatement_count"] == 0
    assert benefit["audit_risk_score"] == 0, (
        f"a brand-new benefit has earned no risk weighting, got {benefit['audit_risk_score']}"
    )

    assert (
        fx.refresh_subscriber(api, applicant["subscriber"]["id"])["status"] == "ENROLLED"
    ), "the applicant is promoted in the same request"
    dwelling = fx.refresh_address(api, address["id"])
    assert_household_address(dwelling)
    assert dwelling["occupied_benefit_slots"] == 1
    assert dwelling["max_permitted_benefit_slots"] == 1
    assert fx.refresh_provider(api, provider["id"])["active_enrollment_count"] == 1


def test_answering_before_any_notice_exists_writes_no_recertification_field(api):
    """recertify is not an edge out of NOT_DUE; only the sweep's notice arm is.

    PRD: "A notice must actually be outstanding: a benefit whose `recert_status` is
    `NOT_DUE`, `NON_RESPONSIVE` or `RESPONDED_INELIGIBLE` is refused with
    `ERR_RECERT_NOT_NOTICED`, because a subscriber cannot recertify before the sweep has
    issued the notice."

    Design: Corner/state_machines/recertify_on_not_due_enrollment_is_rejected_as_recert_not_noticed
    """
    fx.set_clock(api, CLOCK)
    context = fx.active_benefit(api)
    benefit = context["enrollment"]
    assert benefit["recert_status"] == "NOT_DUE", "no sweep has run yet"
    assert_date_component(benefit["recert_due_date"], RECERT_DUE, "recert_due_date")

    response = api.recertify(
        benefit["id"],
        f.recertify_payload(
            household_size=4,
            annual_income_cents=3000000,
            last_3mo_income_cents=750000,
            attested_qualifying_benefit="NONE",
            attestation_ref="ATT-1",
        ),
        context["holder"],
    )
    validate_error(response, ApiErrorId.RECERT_NOT_NOTICED.value, 409)

    unmoved = fx.refresh_enrollment(api, benefit["id"])
    assert unmoved["recert_status"] == "NOT_DUE"
    assert_date_component(unmoved["recert_due_date"], RECERT_DUE, "recert_due_date")
    assert_instant_null(unmoved["recert_notice_sent_at"], "recert_notice_sent_at")
    assert_instant_null(
        unmoved["recert_response_deadline_at"], "recert_response_deadline_at"
    )
    assert_instant_null(unmoved["recert_last_responded_at"], "recert_last_responded_at")
    assert unmoved["recert_evaluated_income_cents"] is None, (
        "the refused attestation was never evaluated"
    )
    assert unmoved["benefit_status"] == "ACTIVE"


def test_replaying_the_de_enrollment_cannot_extend_the_appeal_window(api):
    """The second identical call is refused, and the first call's instants are not rewritten.

    PRD: "A benefit that is already `DE_ENROLLED` cannot be de-enrolled again — the second
    attempt is refused with `ERR_ENROLLMENT_ALREADY_DE_ENROLLED` rather than silently
    rewriting `benefit_end_date`."

    Design: Corner/state_machines/second_de_enroll_of_same_enrollment_rejected_as_already_de_enrolled
    """
    fx.set_clock(api, CLOCK)
    context = fx.active_benefit(api)
    benefit_id = context["enrollment"]["id"]

    fx.set_clock(api, FIRST_DE_ENROLL)
    stopped = fx.de_enroll(
        api,
        benefit_id,
        reason="SUBSCRIBER_REQUEST",
        headers=context["agent"],
        note="moving in with family",
    )
    assert_instant(stopped["de_enrolled_at"], FIRST_DE_ENROLL, "de_enrolled_at")
    assert_instant(stopped["appeal_deadline_at"], APPEAL_DEADLINE, "appeal_deadline_at")

    fx.set_clock(api, REPLAY_INSTANT)
    response = api.de_enroll(
        benefit_id,
        f.de_enroll_payload(
            de_enrollment_reason="SUBSCRIBER_REQUEST", note="replayed request"
        ),
        context["agent"],
    )
    validate_error(response, ApiErrorId.ENROLLMENT_ALREADY_DE_ENROLLED.value, 409)

    replayed = fx.refresh_enrollment(api, benefit_id)
    assert replayed["benefit_status"] == "DE_ENROLLED"
    assert_instant(replayed["de_enrolled_at"], FIRST_DE_ENROLL, "de_enrolled_at")
    assert_instant(replayed["benefit_end_date"], FIRST_DE_ENROLL, "benefit_end_date")
    # replaying the request cannot buy another thirty days of appeal right
    assert_instant(replayed["appeal_deadline_at"], APPEAL_DEADLINE, "appeal_deadline_at")
    assert replayed["de_enrollment_reason"] == "SUBSCRIBER_REQUEST"

    applicant = fx.refresh_subscriber(api, context["subscriber"]["id"])
    assert applicant["status"] == "DE_ENROLLED"
    assert applicant["de_enrollment_count"] == 0, (
        "a voluntary exit is not one of the four fault reasons the counter counts, got "
        f"{applicant['de_enrollment_count']}"
    )
    assert fx.refresh_address(api, context["address"]["id"])["occupied_benefit_slots"] == 0
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 0


def test_two_non_usage_de_enrollments_bar_the_applicant_from_screening(api):
    """BARRED is reached by arithmetic across two sweep-driven cure expiries, then locks.

    PRD: "An applicant in `BARRED` cannot be screened at all: the attempt is refused with
    `ERR_SUBSCRIBER_BARRED`."

    Design: Corner/state_machines/barred_subscriber_cannot_open_a_third_eligibility_check
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    subscriber_id = applicant["subscriber"]["id"]
    first = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        benefit_start_date=CLOCK,
    )

    fx.set_clock(api, FIRST_FLAG)
    assert fx.sweep(api, provider["id"])["non_usage_flagged_enrollment_ids"] == [first["id"]]
    fx.set_clock(api, FIRST_EXPIRY)
    assert fx.sweep(api, provider["id"])["cure_expired_de_enrolled_enrollment_ids"] == [
        first["id"]
    ]

    once = fx.refresh_subscriber(api, subscriber_id)
    assert once["de_enrollment_count"] == 1, (
        f"a non-usage stop is a fault reason, got {once['de_enrollment_count']}"
    )
    assert once["status"] == "DE_ENROLLED", "one fault is below the bar threshold of two"

    reapplication = fx.open_eligibility_check(
        api, subscriber_id, proof_document_ref="DOC-M8-R2"
    )
    assert fx.refresh_subscriber(api, subscriber_id)["status"] == "ELIGIBILITY_PENDING", (
        "the re-application fires DE_ENROLLED to PROSPECT to ELIGIBILITY_PENDING at once"
    )
    fx.confirm_eligibility_check(api, reapplication["id"])

    fx.set_clock(api, SECOND_START)
    second = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        reapplication,
        address,
        benefit_start_date=SECOND_START,
    )
    fx.set_clock(api, SECOND_FLAG)
    assert fx.sweep(api, provider["id"])["non_usage_flagged_enrollment_ids"] == [second["id"]]
    fx.set_clock(api, SECOND_EXPIRY)
    assert fx.sweep(api, provider["id"])["cure_expired_de_enrolled_enrollment_ids"] == [
        second["id"]
    ]

    barred = fx.refresh_subscriber(api, subscriber_id)
    assert barred["de_enrollment_count"] == 2
    assert barred["status"] == "BARRED", (
        f"the second fault reaches the threshold of two, got {barred['status']}"
    )

    response = api.create_eligibility_check(
        subscriber_id,
        f.eligibility_check_payload(claimed_basis="INCOME", proof_document_ref="DOC-M8"),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.SUBSCRIBER_BARRED.value, 409)

    assert_instant(
        fx.refresh_enrollment(api, first["id"])["benefit_end_date"],
        FIRST_EXPIRY,
        "benefit_end_date",
    )
    closed = fx.refresh_enrollment(api, second["id"])
    assert_instant(closed["benefit_start_date"], SECOND_START, "benefit_start_date")
    assert_instant(closed["benefit_end_date"], SECOND_EXPIRY, "benefit_end_date")

    _rows, meta = validate_paginated(
        api.list_subscriber_eligibility_checks(subscriber_id, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 2, (
        f"the barred third attempt created no check row, got {meta['total_count']}"
    )
    assert fx.refresh_provider(api, provider["id"])["active_enrollment_count"] == 0
    assert fx.refresh_address(api, address["id"])["occupied_benefit_slots"] == 0


def test_both_action_endpoints_are_closed_on_a_granted_case_with_different_codes(api):
    """GRANTED is terminal, and each closed endpoint reports its own precondition code.

    PRD: "The case must be `SUBMITTED` or `REMANDED`, or the request is refused with
    `ERR_CASE_NOT_ASSIGNABLE`."

    Design: Corner/state_machines/granted_case_cannot_be_reassigned_or_decided_again
    """
    fx.set_clock(api, CLOCK)
    context = fx.active_benefit(api)
    benefit_id = context["enrollment"]["id"]

    fx.set_clock(api, FIRST_DE_ENROLL)
    fx.de_enroll(
        api,
        benefit_id,
        reason="SUBSCRIBER_REQUEST",
        headers=context["agent"],
        note="stopped at the carrier's counter",
    )
    case = fx.file_case(
        api,
        context["subscriber"]["id"],
        benefit_id,
        case_type="DE_ENROLLMENT_APPEAL",
        narrative="the benefit was stopped without my consent",
    )
    fx.assign_review(api, case["id"], reviewer_ref="REV-1")
    granted = fx.decide_case(
        api, case["id"], "GRANT_REINSTATE", rationale="the record supports reinstatement"
    )
    assert granted["status"] == "GRANTED"
    assert granted["reinstated_enrollment_flag"] is True

    reassign = api.assign_case_review(
        case["id"], f.assign_review_payload(reviewer_ref="REV-2"), PROGRAM_ADMIN
    )
    validate_error(reassign, ApiErrorId.CASE_NOT_ASSIGNABLE.value, 409)

    redecide = api.decide_case(
        case["id"],
        f.decide_case_payload(decision="DENY", decision_rationale="second thoughts"),
        PROGRAM_ADMIN,
    )
    validate_error(redecide, ApiErrorId.CASE_NOT_UNDER_REVIEW.value, 409)

    locked = fx.refresh_case(api, case["id"])
    assert_subscriber_case(locked)
    assert locked["status"] == "GRANTED"
    assert locked["decision"] == "GRANT_REINSTATE", "the refused decision overwrote nothing"
    assert locked["reviewer_ref"] == "REV-1", "the refused reassignment kept the reviewer"
    assert locked["review_round"] == 1
    assert_instant(locked["decided_at"], FIRST_DE_ENROLL, "decided_at")
    assert locked["decided_by_ref"] == PROGRAM_ADMIN_ID

    benefit = fx.refresh_enrollment(api, benefit_id)
    assert benefit["benefit_status"] == "ACTIVE"
    assert benefit["reinstatement_count"] == 1, (
        f"the benefit was not reinstated a second time, got {benefit['reinstatement_count']}"
    )
    assert_instant(benefit["benefit_start_date"], CLOCK, "benefit_start_date")
    assert_date_component(benefit["recert_due_date"], RECERT_DUE, "recert_due_date")


def test_five_machines_are_observed_in_their_declared_birth_states(api):
    """One chain of creates reads the initial state of five different machines.

    PRD: "A fresh check is born `PENDING_VERIFIER` with `resubmission_count` at 0 and
    `verifier_outcome`, `verifier_reason_code`, `matched_benefit`, `confirmed_at` and
    `expires_at` all null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api, licensed_state_codes=["TX"], enrollment_cap=50)
    agent = fx.provider_headers(provider)

    dwelling = validate_success(
        api.create_address(f.distinct_address_payload(1), PROGRAM_ADMIN), 201
    )
    assert dwelling["status"] == "UNVERIFIED", "a dwelling alone in its cohort is unflagged"

    applicant = validate_success(
        api.create_subscriber(f.subscriber_payload(dwelling["id"]), PROGRAM_ADMIN), 201
    )
    assert applicant["status"] == "PROSPECT"

    check = validate_success(
        api.create_eligibility_check(
            applicant["id"],
            f.eligibility_check_payload(claimed_basis="INCOME", proof_document_ref="DOC-N1"),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert check["status"] == "PENDING_VERIFIER"
    assert check["resubmission_count"] == 0
    assert check["verifier_outcome"] is None
    assert check["verifier_reason_code"] is None
    assert check["matched_benefit"] is None
    assert_instant_null(check["confirmed_at"], "confirmed_at")
    assert_instant_null(check["expires_at"], "expires_at")

    handset = validate_success(
        api.stock_device(
            provider["id"],
            f.device_payload(imei="350000000000030", model_tier="BASIC", unit_cost_cents=2100),
            agent,
        ),
        201,
    )
    assert_device(handset)
    assert handset["status"] == "IN_STOCK"
    assert handset["issued_enrollment_id"] is None
    assert_instant_null(handset["issued_at"], "issued_at")
    assert handset["return_condition"] is None

    fx.confirm_eligibility_check(api, check["id"])
    benefit = validate_success(
        api.create_enrollment(
            f.enrollment_payload(
                subscriber_id=applicant["id"],
                provider_id=provider["id"],
                eligibility_check_id=check["id"],
                certified_address_id=dwelling["id"],
                service_type="VOICE",
            ),
            agent,
        ),
        201,
    )
    assert benefit["benefit_status"] == "ACTIVE"
    assert benefit["usage_status"] == "PENDING_FIRST_USE"
    assert benefit["recert_status"] == "NOT_DUE"
    assert benefit["device_status"] == "AWAITING_DEVICE", (
        "stocking a handset does not put one in the subscriber's hands"
    )

    case = validate_success(
        api.create_subscriber_case(
            f.subscriber_case_payload(
                subscriber_id=applicant["id"],
                enrollment_id=benefit["id"],
                case_type="SERVICE_COMPLAINT",
                narrative="dropped calls in my building",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_subscriber_case(case)
    assert case["status"] == "SUBMITTED"
    assert case["review_round"] == 0
    assert case["decision"] is None
    assert case["reviewer_ref"] is None
    assert case["reinstated_enrollment_flag"] is False


def test_the_documentation_loop_is_bounded_at_two_round_trips(api):
    """Two resubmissions are accepted, the third is refused and the check stays parked.

    PRD: "The check must be sitting in `DOCUMENTATION_REQUIRED`, otherwise the attempt is
    refused with `ERR_DOCUMENTATION_NOT_REQUESTED`; and `resubmission_count` must be below 2,
    otherwise it is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/documentation_resubmission_cycle_is_bounded_at_two_rounds
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    agent = fx.provider_headers(provider)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.create_subscriber(api, address["id"])
    check = fx.open_eligibility_check(api, applicant["id"], proof_document_ref="DOC-N2")

    def bounce(reason_code):
        return validate_success(
            api.submit_verifier_result(
                check["id"],
                f.verifier_result_payload(
                    verifier_outcome="DOCUMENTATION_REQUIRED",
                    verifier_reason_code=reason_code,
                ),
                NATIONAL_VERIFIER,
            )
        )

    bounce("ROUND_1")
    first = validate_success(
        api.resubmit_documentation(
            check["id"],
            f.resubmit_documentation_payload(proof_document_ref="DOC-N2-R1"),
            agent,
        )
    )
    assert first["resubmission_count"] == 1

    bounce("ROUND_2")
    second = validate_success(
        api.resubmit_documentation(
            check["id"],
            f.resubmit_documentation_payload(proof_document_ref="DOC-N2-R2"),
            agent,
        )
    )
    assert second["resubmission_count"] == 2

    bounce("ROUND_3")
    third = api.resubmit_documentation(
        check["id"], f.resubmit_documentation_payload(proof_document_ref="DOC-N2-R3"), agent
    )
    validate_error(third, ApiErrorId.RESUBMISSION_LIMIT_EXCEEDED.value, 409)

    parked = fx.refresh_eligibility_check(api, check["id"])
    assert parked["status"] == "DOCUMENTATION_REQUIRED", (
        f"the refused resubmission leaves the check parked, got {parked['status']}"
    )
    assert parked["resubmission_count"] == 2, "the counter is not advanced by a refusal"
    assert parked["proof_document_ref"] == "DOC-N2-R2", (
        "the third reference was never stored"
    )
    assert parked["verifier_reason_code"] == "ROUND_3"
    assert fx.refresh_subscriber(api, applicant["id"])["status"] == "ELIGIBILITY_PENDING"


def test_the_declined_port_is_terminal_and_changes_nothing_on_the_benefit(api):
    """The REJECTED arm of the fork stores its reason and is a no-op on the benefit.

    PRD: "The request moves `REQUESTED → REJECTED`, the reason is stored, and `completed_at`
    is stamped with the current instant."

    Design: Corner/state_machines/transfer_reject_arm_records_reason_and_leaves_enrollment_untouched
    """
    fx.set_clock(api, CLOCK)
    losing = fx.register_provider(api, name="SafeLink Wireless", licensed_state_codes=["TX"])
    gaining = fx.register_provider(api, name="TruConnect", licensed_state_codes=["TX"])
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        losing,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=CLOCK,
    )
    assert_instant(benefit["port_freeze_until"], PORT_FREEZE_UNTIL, "port_freeze_until")

    fx.set_clock(api, PORT_FREEZE_UNTIL)
    request = fx.request_transfer(api, losing, benefit["id"], gaining["id"])
    assert request["status"] == "REQUESTED"

    declined = validate_success(
        api.reject_service_transfer(
            request["id"],
            f.transfer_reject_payload(
                rejection_reason="CONSENT_INVALID",
                rejection_note="consent ref does not match our record",
            ),
            fx.provider_headers(gaining),
        )
    )
    assert_service_transfer(declined)
    assert declined["status"] == "REJECTED", (
        f"the decline is the terminal arm of the fork, got {declined['status']}"
    )
    assert declined["rejection_reason"] == "CONSENT_INVALID"
    assert_instant(declined["completed_at"], PORT_FREEZE_UNTIL, "completed_at")

    unmoved = fx.refresh_enrollment(api, benefit["id"])
    assert unmoved["provider_id"] == losing["id"], "the benefit never left its carrier"
    assert unmoved["transfer_count"] == 0, (
        f"a declined port is not a transfer, got {unmoved['transfer_count']}"
    )
    assert_instant(unmoved["port_freeze_until"], PORT_FREEZE_UNTIL, "port_freeze_until")
    assert unmoved["usage_status"] == "PENDING_FIRST_USE"
    assert unmoved["audit_risk_score"] == 0, (
        f"the declined port earns no risk weighting, got {unmoved['audit_risk_score']}"
    )
    assert fx.refresh_provider(api, losing["id"])["active_enrollment_count"] == 1
    assert fx.refresh_provider(api, gaining["id"])["active_enrollment_count"] == 0


def test_resolving_the_cohort_as_one_household_keeps_only_the_earliest_benefit(api):
    """The SINGLE_HOUSEHOLD arm cascades down to the excess benefit and leaves the first alone.

    PRD: "First, every active benefit certified at that dwelling is ordered by
    `benefit_start_date` ascending with `created_at` ascending as the tie-break; the earliest
    is retained and every subsequent one is de-enrolled with `de_enrollment_reason` set to
    `DUPLICATE_HOUSEHOLD`, `benefit_end_date` and `de_enrolled_at` set to the current instant,
    and `de_enrolled_by_ref` set to the resolving operator's `X-User-ID`."

    Design: Corner/state_machines/single_household_resolution_cascades_down_to_excess_enrollments
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    first_dwelling, _twin = fx.duplicate_cohort(api, 2)

    first_applicant = fx.create_subscriber(api, first_dwelling["id"])
    first_check = fx.confirm_eligibility_check(
        api, fx.open_eligibility_check(api, first_applicant["id"])["id"]
    )
    second_applicant = fx.create_subscriber(api, first_dwelling["id"])
    second_check = fx.confirm_eligibility_check(
        api, fx.open_eligibility_check(api, second_applicant["id"])["id"]
    )

    opened = fx.resolve_multi_household(
        api, first_dwelling["id"], declared_household_count=2, worksheet_ref="WS-1"
    )
    assert opened["max_permitted_benefit_slots"] == 2
    assert fx.refresh_subscriber(api, first_applicant["id"])["status"] == "VERIFIED_ELIGIBLE"
    assert fx.refresh_subscriber(api, second_applicant["id"])["status"] == "VERIFIED_ELIGIBLE"

    retained = fx.enroll(
        api, provider, first_applicant, first_check, first_dwelling, benefit_start_date=CLOCK
    )
    excess = fx.enroll(
        api, provider, second_applicant, second_check, first_dwelling, benefit_start_date=CLOCK
    )
    assert fx.refresh_address(api, first_dwelling["id"])["occupied_benefit_slots"] == 2

    validate_success(
        api.create_address(
            f.address_payload(
                address_line1="1200-N-MAIN-ST",
                unit_designator="APT4B",
                city="el paso",
                state_code="TX",
                postal_code="79901",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    reflagged = fx.refresh_address(api, first_dwelling["id"])
    assert reflagged["status"] == "DUPLICATE_FLAGGED", (
        "a later arrival pulls an adjudicated dwelling back into the cohort"
    )
    assert reflagged["cohort_address_count"] == 3

    resolved = fx.resolve_single_household(api, first_dwelling["id"])
    assert_household_address(resolved)
    assert resolved["status"] == "RESOLVED_SINGLE_HOUSEHOLD"
    assert resolved["max_permitted_benefit_slots"] == 1
    assert resolved["occupied_benefit_slots"] == 1, (
        f"only the retained benefit still occupies a slot, got {resolved['occupied_benefit_slots']}"
    )
    assert resolved["declared_household_count"] is None
    assert resolved["independent_household_worksheet_ref"] is None

    kept = fx.refresh_enrollment(api, retained["id"])
    assert kept["benefit_status"] == "ACTIVE", "the earliest benefit is untouched"
    assert_instant_null(kept["benefit_end_date"], "benefit_end_date")
    assert kept["de_enrollment_reason"] is None

    reclaimed = fx.refresh_enrollment(api, excess["id"])
    assert reclaimed["benefit_status"] == "DE_ENROLLED"
    assert reclaimed["de_enrollment_reason"] == "DUPLICATE_HOUSEHOLD"
    assert_instant(reclaimed["de_enrolled_at"], CLOCK, "de_enrolled_at")
    assert_instant(reclaimed["benefit_end_date"], CLOCK, "benefit_end_date")
    assert_instant(reclaimed["appeal_deadline_at"], "2026-08-31T23:59:59.999Z", "appeal_deadline_at")
    assert reclaimed["de_enrolled_by_ref"] == PROGRAM_ADMIN_ID

    assert fx.refresh_subscriber(api, first_applicant["id"])["status"] == "ENROLLED"
    displaced = fx.refresh_subscriber(api, second_applicant["id"])
    assert displaced["status"] == "DE_ENROLLED"
    assert displaced["de_enrollment_count"] == 0, (
        "a duplicate-household clean-up is not one of the four fault reasons, got "
        f"{displaced['de_enrollment_count']}"
    )
    assert fx.refresh_provider(api, provider["id"])["active_enrollment_count"] == 1


def test_the_only_compliant_sample_carries_the_claim_up_to_audit_passed(api):
    """The join arm bubbles up from the child sample to the parent claim and its carrier.

    PRD: "The claim advances to `AUDIT_PASSED` only when this adjudication leaves no sample
    of the claim in `DRAWN` **and** `failed_sample_count` is 0 — it is a join, waiting for
    every sample."

    Design: Corner/state_machines/all_samples_compliant_bubbles_claim_up_to_audit_passed
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )

    fx.set_clock(api, JULY_FILING)
    claim = fx.file_claim(api, fx.draft_claim(api, provider, "2026-06")["id"], provider)
    assert claim["final_amount_cents"] == 925, (
        f"30 of 30 days on one non-tribal voice line, got {claim['final_amount_cents']}"
    )
    assert claim["covered_enrollment_count"] == 1

    sample = fx.draw_samples(api, claim["id"], sample_size=1)[0]
    assert_audit_sample(sample)
    assert sample["selection_rank"] == 1
    assert sample["claimed_line_cents"] == 925
    assert sample["drawn_by_ref"] == AUDITOR_DRAWER_ID
    assert fx.refresh_claim(api, claim["id"])["status"] == "UNDER_AUDIT"

    passed = fx.adjudicate(
        api, sample["id"], finding="COMPLIANT", finding_note="documentation complete"
    )
    assert passed["status"] == "ADJUDICATED_PASS"
    assert passed["disallowed_support_cents"] == 0
    assert passed["finding"] == "COMPLIANT"
    assert passed["adjudicated_by_ref"] == AUDITOR_ADJUDICATOR_ID

    settled = fx.refresh_claim(api, claim["id"])
    assert_reimbursement_claim(settled)
    assert settled["status"] == "AUDIT_PASSED", (
        f"no DRAWN sample is left and none failed, got {settled['status']}"
    )
    assert settled["audit_sample_count"] == 1
    assert settled["failed_sample_count"] == 0
    assert settled["recoupment_amount_cents"] == 0
    assert settled["penalty_cents"] == 0
    assert settled["net_payable_cents"] == 925

    carrier = fx.refresh_provider(api, provider["id"])
    assert carrier["claim_gross_cents"] == 925
    assert carrier["recouped_cents"] == 0
    assert carrier["net_reimbursed_cents"] == 925
    assert carrier["audit_hold_flag"] is False
    assert fx.refresh_enrollment(api, benefit["id"])["benefit_status"] == "ACTIVE", (
        "a compliant finding does not stop the benefit"
    )


def test_the_ledger_moves_only_on_the_filing_never_on_the_draft(api):
    """The carrier's derived figures are read at three points around the draft-then-file pair.

    PRD: "`open_claim_count` counts that carrier's claims that are draft, filed, held or
    under audit."

    Design: Corner/state_machines/claim_filing_syncs_provider_ledger_and_open_claim_counter
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    agent = fx.provider_headers(provider)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )

    fx.set_clock(api, JULY_FILING)
    before = fx.refresh_provider(api, provider["id"])
    assert before["open_claim_count"] == 0
    assert before["claim_gross_cents"] == 0
    assert before["net_reimbursed_cents"] == 0

    draft = validate_success(
        api.create_claim(
            f.claim_payload(
                provider_id=provider["id"],
                service_month="2026-06",
                expected_provider_version=before["version"],
            ),
            agent,
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    assert draft["provisional_amount_cents"] == 925

    mid = fx.refresh_provider(api, provider["id"])
    assert mid["open_claim_count"] == 1, (
        f"a DRAFT claim is an open claim, got {mid['open_claim_count']}"
    )
    assert mid["claim_gross_cents"] == 0, "a draft is worth nothing in the ledger"
    assert mid["net_reimbursed_cents"] == 0

    filed = validate_success(
        api.file_claim(
            draft["id"], f.claim_file_payload(certifying_officer_ref="OFFICER-8"), agent
        )
    )
    assert filed["status"] == "FILED"
    assert filed["final_amount_cents"] == 925
    assert filed["variance_cents"] == 0, (
        f"the two pricings agree for a month already closed, got {filed['variance_cents']}"
    )
    assert_instant(filed["filed_at"], JULY_FILING, "filed_at")
    assert filed["certifying_officer_ref"] == "OFFICER-8"
    assert filed["covered_enrollment_count"] == 1

    after = fx.refresh_provider(api, provider["id"])
    assert after["open_claim_count"] == 1, (
        f"a FILED claim is still an open claim, got {after['open_claim_count']}"
    )
    assert after["claim_gross_cents"] == 925, "the money lands on the filing"
    assert after["net_reimbursed_cents"] == 925
    assert after["recouped_cents"] == 0
    assert after["audit_hold_flag"] is False


def test_only_the_issued_handset_is_reclaimed_when_the_benefit_stops(api):
    """Of three handsets, the reclaim cascade touches only the one actually in ISSUED.

    PRD: "If the benefit was holding a handset — `device_status` is `DEVICE_ISSUED` — then
    `device_status` moves to `RECLAIM_PENDING`, the handset itself moves `ISSUED →
    RECLAIM_PENDING`, the carrier's `devices_issued_count` and `devices_reclaim_pending_count`
    are recomputed and its `version` incremented by one."

    Design: Corner/state_machines/de_enrollment_reclaims_only_the_issued_handset
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    agent = fx.provider_headers(provider)
    first, spare, retired = fx.stock_devices(
        api, provider, [("BASIC", 2100), ("BASIC", 2100), ("STANDARD", 1200)]
    )
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=CLOCK,
    )

    fx.issue_device(api, benefit["id"], provider, device_id=retired["id"])
    fx.set_clock(api, DAMAGED_RETURN)
    fx.return_device(api, retired["id"], return_condition="DAMAGED")
    assert fx.refresh_device(api, retired["id"])["status"] == "RETIRED", (
        "a DAMAGED return retires the handset and waives the re-issue freeze"
    )

    fx.set_clock(api, SECOND_ISSUE)
    fx.issue_device(api, benefit["id"], provider, device_id=first["id"])
    assert_device_counters(fx.refresh_provider(api, provider["id"]), 3, 1, 1, 0, 1)

    stopped = fx.de_enroll(
        api,
        benefit["id"],
        reason="SUBSCRIBER_REQUEST",
        headers=agent,
        note="handset recall",
    )
    assert stopped["benefit_status"] == "DE_ENROLLED"
    assert stopped["device_status"] == "RECLAIM_PENDING"

    held = fx.refresh_device(api, first["id"])
    assert_device(held)
    assert held["status"] == "RECLAIM_PENDING", (
        f"the issued handset is the only one recalled, got {held['status']}"
    )
    assert held["issued_enrollment_id"] == benefit["id"]
    assert_instant(held["issued_at"], SECOND_ISSUE, "issued_at")
    assert_instant_null(held["returned_at"], "returned_at")

    untouched = fx.refresh_device(api, spare["id"])
    assert untouched["status"] == "IN_STOCK", "the spare was never issued"
    assert untouched["issued_enrollment_id"] is None

    terminal = fx.refresh_device(api, retired["id"])
    assert terminal["status"] == "RETIRED", "a terminal handset is not recalled again"
    assert terminal["return_condition"] == "DAMAGED"
    assert_instant(terminal["returned_at"], DAMAGED_RETURN, "returned_at")

    assert_device_counters(fx.refresh_provider(api, provider["id"]), 3, 1, 0, 1, 1)
    assert fx.refresh_enrollment(api, benefit["id"])["device_issuance_count"] == 2, (
        "two handsets were issued to this benefit across its life"
    )
