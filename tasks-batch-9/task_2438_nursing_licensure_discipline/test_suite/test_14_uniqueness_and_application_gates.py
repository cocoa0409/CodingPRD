"""Uniqueness, pagination, ownership, and the licence-application eligibility gates."""
from test_helpers import (
    ADMIN,
    ANALYST,
    CLOCK_DEFAULT_STAMP,
    INVESTIGATOR,
    ApiClient,
    ApiErrorId,
    assert_pagination_meta,
    board_config_payload,
    complaint_version,
    dispose_complaint,
    education_program_payload,
    endorsement_application_payload,
    make_applicant_headers,
    make_board_member_headers,
    reports_for_source,
    reread_complaint,
    seed_active_license,
    seed_application,
    seed_board_program_nurse,
    seed_complaint,
    seed_compact_board,
    seed_evidence_complete_complaint,
    seed_nurse,
    seed_program,
    seed_referred_context,
    seed_second_board,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_second_board_for_the_same_state_code_is_refused(api: ApiClient):
    """PRD §3.1: "A second registration reusing an existing `state_code` is
    refused with `ERR_STATE_CODE_EXISTS`."

    PRD §2.11: "Uniqueness holds: a board's `state_code` is unused, and a
    program's `program_code` is unused within its board. Otherwise
    `ERR_STATE_CODE_EXISTS` or `ERR_PROGRAM_CODE_EXISTS`."

    Design: Corner/validations/reusing_a_state_code_returns_state_code_exists
    """
    board = seed_compact_board(api)

    refused = api.create_board_config(
        board_config_payload(state_code="OH",
                             board_name="Ohio Board of Nursing (Duplicate)",
                             compact_member=False),
        ADMIN,
    )

    validate_error(refused, ApiErrorId.ERR_STATE_CODE_EXISTS.value)
    stored = validate_success(api.get_board_config(board["id"], ADMIN))
    assert stored["board_name"] == "Ohio Board of Nursing", (
        f"The first registration is untouched, got {stored['board_name']}"
    )
    assert stored["compact_member"] is True, (
        "The refused duplicate must not have overwritten compact_member"
    )
    assert stored["version"] == 1, (
        f"A refused create is not a mutation, got version {stored['version']}"
    )


def test_a_program_code_is_unique_per_board_not_globally(api: ApiClient):
    """PRD §2.11: "Uniqueness holds: a board's `state_code` is unused, and a
    program's `program_code` is unused within its board. Otherwise
    `ERR_STATE_CODE_EXISTS` or `ERR_PROGRAM_CODE_EXISTS`."

    PRD §3.1: "Programs may be listed for a board and narrowed by
    `approval_status` or by `degree_level`."

    Design: Corner/validations/reusing_a_program_code_under_the_same_board_returns_program_code_exists
    """
    board_oh = seed_compact_board(api)
    board_mi = seed_second_board(api, compact_member=True)
    program = seed_program(api, board_oh["id"])

    collision = api.create_education_program(
        education_program_payload(board_oh["id"], program_code="OH-BSN-01",
                                  program_name="Buckeye BSN Evening",
                                  nclex_first_time_pass_rate_bp=9100),
        ADMIN,
    )

    validate_error(collision, ApiErrorId.ERR_PROGRAM_CODE_EXISTS.value)
    accepted = validate_success(
        api.create_education_program(
            education_program_payload(board_mi["id"], program_code="OH-BSN-01",
                                      program_name="Buckeye BSN Evening",
                                      nclex_first_time_pass_rate_bp=9100),
            ADMIN,
        ),
        201,
    )
    assert accepted["program_code"] == "OH-BSN-01", (
        "The very same code is free under a different board"
    )
    programs, meta = validate_paginated(
        api.list_board_education_programs(board_oh["id"], ADMIN)
    )
    assert meta["total_count"] == 1, (
        f"The refused collision left one program under the board, got "
        f"{meta['total_count']}"
    )
    assert [row["id"] for row in programs] == [program["id"]]


def test_pagination_bounds_are_rejected_before_any_credential_is_listed(api: ApiClient):
    """PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum
    accepted value is 1, and its maximum accepted value is 100."

    PRD §2.3: "`offset` controls the starting position: it defaults to 0 and its
    minimum accepted value is 0, with no upper bound."

    PRD §2.3: "If `limit` is not an integer within 1 through 100, or `offset` is
    not an integer greater than or equal to 0, the request is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filters before pagination is
    applied), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/validations/negative_limit_on_the_license_list_returns_invalid_pagination
    """
    seed_compact_board(api)

    below_minimum = api.list_licenses(ANALYST, params={"limit": -5, "offset": 0})

    validate_error(below_minimum, ApiErrorId.ERR_INVALID_PAGINATION.value)
    validate_error(
        api.list_licenses(ANALYST, params={"limit": 101, "offset": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
    )
    validate_error(
        api.list_licenses(ANALYST, params={"limit": 10, "offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
    )
    credentials, meta = validate_paginated(api.list_licenses(ANALYST))
    assert credentials == [], "No credential was ever minted in this scenario"
    assert_pagination_meta(meta, 10, 0, 0, False)


def test_an_applicant_may_not_read_a_credential_belonging_to_another_nurse(
    api: ApiClient,
):
    """PRD §2.1: "The comparison walks whatever chain reaches a nurse: the `Nurse`
    record's own `id` when the nurse resource is addressed directly; `nurse_id`
    for a licence application, a credential, or a monitoring agreement; the
    credential's `nurse_id` reached through a renewal's `license_id`; and the
    credential's `nurse_id` reached through a continuing-education record's
    `renewal_application_id` and then that renewal's `license_id`."

    PRD §2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD §2.11: "When the caller is an `Applicant`, the ownership chain of §2.1
    resolves to the caller — otherwise `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/applicant_reading_another_nurses_license_returns_not_resource_owner
    """
    ctx = seed_active_license(api)
    stranger = seed_nurse(api, ctx["board_id"], full_name="Kai Moreno",
                          birth_year=1990, ssn_last4="7712")

    refused = api.get_license(ctx["license_id"], make_applicant_headers(stranger["id"]))

    error = validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value, (
        "Applicant is an authorised role for this read, so the role gate passes"
    )
    assert error["error_id"] != ApiErrorId.ERR_LICENSE_NOT_FOUND.value, (
        "The credential exists; a not-found answer would leak nothing but is wrong"
    )
    owned = validate_success(
        api.get_license(ctx["license_id"], make_applicant_headers(ctx["nurse_id"]))
    )
    assert owned["id"] == ctx["license_id"], (
        "The owning nurse reads their own credential"
    )


def test_a_failed_examination_result_blocks_qualification_verification(api: ApiClient):
    """PRD §3.2: "The application's `nclex_result` must be `PASS`; anything else
    yields `ERR_NCLEX_NOT_PASSED`."

    PRD §2.11: "An examination-pathway application names an education program
    whose approval posture and expiry are acceptable — otherwise
    `ERR_PROGRAM_NOT_APPROVED`."

    PRD §2.11: "An examination-pathway application reports a passing examination
    result — otherwise `ERR_NCLEX_NOT_PASSED`."

    PRD §3.2: "A new application begins at `DRAFT` with `screening_status`
    `NOT_ORDERED`, `deficiency_cycle_count` 0, `board_decision` `NONE`,
    `prior_license_verified` false, an empty `screening_offense_records` array,
    and both `submitted_at` and `decided_at` null."

    Design: Corner/validations/examination_verification_with_a_failed_nclex_returns_nclex_not_passed
    """
    ctx = seed_board_program_nurse(api)
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"], nclex_result="FAIL")
    submitted = submit_application(api, application["id"])
    assert submitted["status"] == "SUBMITTED", (
        "A failed examination does not block submission, only verification"
    )

    refused = api.verify_license_application_qualification(application["id"], ANALYST)

    error = validate_error(refused, ApiErrorId.ERR_NCLEX_NOT_PASSED.value)
    assert error["error_id"] != ApiErrorId.ERR_PROGRAM_NOT_APPROVED.value, (
        "The program is APPROVED and unexpired, so the failing conjunct is the "
        "examination result alone"
    )
    stored = validate_success(api.get_license_application(application["id"], ANALYST))
    assert stored["status"] == "SUBMITTED", (
        f"The refused verification left the filing at SUBMITTED, got "
        f"{stored['status']}"
    )
    assert stored["screening_status"] == "NOT_ORDERED", (
        f"Screening is only ordered by a successful verification, got "
        f"{stored['screening_status']}"
    )


def test_an_endorsement_needs_its_prior_credential_confirmed_before_verification(
    api: ApiClient,
):
    """PRD §3.2: "On the endorsement route, `prior_license_verified` must be true
    and `prior_license_state` must be a non-null two-letter code, failing which
    the verification is refused with `ERR_PRIOR_LICENSE_UNVERIFIED`."

    PRD §3.2: "A new application begins at `DRAFT` with `screening_status`
    `NOT_ORDERED`, `deficiency_cycle_count` 0, `board_decision` `NONE`,
    `prior_license_verified` false, an empty `screening_offense_records` array,
    and both `submitted_at` and `decided_at` null."

    PRD §3.2: "A successful verification passes the application through
    `QUALIFICATION_VERIFIED` and out the other side to `SCREENING_IN_PROGRESS`
    within the same request, setting `screening_status` to `REQUESTED` on the way."

    PRD §3.2: "The two routes differ in exactly one respect, and it is a side
    effect rather than a state: an endorsement verification additionally queues an
    interstate verification notice — a notification report on the
    `INTERSTATE_COMPACT` channel, with `source_entity_type` `LICENSE_APPLICATION`,
    `basis_code` `ENDORSEMENT_VERIFICATION`, and `status` `QUEUED`."

    Design: Corner/validations/endorsement_verification_without_prior_license_proof_returns_prior_license_unverified
    """
    board = seed_compact_board(api)
    nurse = seed_nurse(api, board["id"])
    application = validate_success(
        api.create_license_application(
            endorsement_application_payload(nurse["id"], board["id"],
                                            prior_license_number="MI-RN-99213"),
            ANALYST,
        ),
        201,
    )
    assert application["prior_license_verified"] is False, (
        "The attestation defaults to false"
    )
    submitted = submit_application(api, application["id"])
    assert submitted["status"] == "SUBMITTED", (
        "An endorsement application carries no education_program_id and still submits"
    )

    refused = api.verify_license_application_qualification(application["id"], ANALYST)

    validate_error(refused, ApiErrorId.ERR_PRIOR_LICENSE_UNVERIFIED.value)
    verified = validate_success(
        api.verify_license_application_qualification(
            application["id"], ANALYST, {"prior_license_verified": True}
        )
    )
    assert verified["prior_license_verified"] is True
    assert verified["status"] == "SCREENING_IN_PROGRESS", (
        f"Verification runs straight through to screening, got {verified['status']}"
    )
    assert verified["screening_status"] == "REQUESTED"
    reports = reports_for_source(api, application["id"])
    assert len(reports) == 1, (
        f"An endorsement verification queues exactly one notice, got {len(reports)}"
    )
    assert reports[0]["channel"] == "INTERSTATE_COMPACT"
    assert reports[0]["basis_code"] == "ENDORSEMENT_VERIFICATION"
    assert reports[0]["source_entity_type"] == "LICENSE_APPLICATION"
    assert reports[0]["status"] == "QUEUED"


def test_an_advanced_practice_application_cannot_be_submitted_without_its_base(
    api: ApiClient,
):
    """PRD §3.2: "Three preconditions apply: the board named by `board_config_id`
    must be `ACTIVE`; an examination-route application must actually carry an
    `education_program_id`; and an advanced-practice application must actually
    carry a `base_license_id`, failing which the submit is refused with
    `ERR_BASE_LICENSE_REQUIRED`."

    PRD §2.11: "An advanced-practice application rests on a qualifying base
    credential — otherwise `ERR_BASE_LICENSE_REQUIRED`."

    PRD §3.2: "A new application begins at `DRAFT` with `screening_status`
    `NOT_ORDERED`, `deficiency_cycle_count` 0, `board_decision` `NONE`,
    `prior_license_verified` false, an empty `screening_offense_records` array,
    and both `submitted_at` and `decided_at` null."

    Design: Corner/validations/aprn_submission_without_a_base_license_returns_base_license_required
    """
    ctx = seed_board_program_nurse(
        api, program_overrides={"program_code": "OH-MSN-01",
                                "program_name": "Buckeye MSN",
                                "degree_level": "MSN",
                                "nclex_first_time_pass_rate_bp": 9200},
    )
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"], credential_type="APRN",
                                   aprn_role="NP")
    assert application["status"] == "DRAFT", (
        "Opening the filing is legal without a base credential"
    )

    refused = api.submit_license_application(application["id"], ANALYST)

    error = validate_error(refused, ApiErrorId.ERR_BASE_LICENSE_REQUIRED.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, (
        "DRAFT is a declared origin state for submit, so the state check passes"
    )
    stored = validate_success(api.get_license_application(application["id"], ANALYST))
    assert stored["status"] == "DRAFT"
    assert stored["submitted_at"] is None, (
        f"A refused submit stamps nothing, got {stored['submitted_at']}"
    )


def test_the_third_deficiency_freezes_the_filing_and_leaves_only_withdrawal(
    api: ApiClient,
):
    """PRD §3.2: "The budget is shared and hard: the deficiency count must be
    strictly below 3 both for a new return to be recorded and for a deficient
    application to be resubmitted."

    PRD §3.2: "Once `deficiency_cycle_count` reaches 3 the application simply
    freezes in `DEFICIENT`, and from that point a further return and a
    resubmission are *both* refused with `ERR_DEFICIENCY_LIMIT_REACHED`, leaving
    withdrawal by the applicant as the only remaining exit."

    PRD §3.2: "An applicant may withdraw at any point before a decision, from
    `DRAFT`, `SUBMITTED`, or `DEFICIENT`, which moves the application to
    `WITHDRAWN` and stamps `decided_at`."

    Design: Corner/validations/third_deficiency_freezes_the_application_and_resubmission_is_refused
    """
    ctx = seed_board_program_nurse(api)
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"])
    frozen = None
    for cycle in ("cycle one", "cycle two", "cycle three"):
        submit_application(api, application["id"])
        frozen = validate_success(
            api.return_license_application_deficient(
                application["id"], {"reason_note": cycle}, ANALYST
            )
        )
    assert frozen["status"] == "DEFICIENT"
    assert frozen["deficiency_cycle_count"] == 3, (
        f"Three returns spend the budget, got {frozen['deficiency_cycle_count']}"
    )

    refused = api.submit_license_application(application["id"], ANALYST)

    error = validate_error(refused, ApiErrorId.ERR_DEFICIENCY_LIMIT_REACHED.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, (
        "DEFICIENT is a declared origin state for submit, so the budget is what refuses"
    )
    validate_error(
        api.return_license_application_deficient(
            application["id"], {"reason_note": "cycle four"}, ANALYST
        ),
        ApiErrorId.ERR_DEFICIENCY_LIMIT_REACHED.value,
    )
    withdrawn = validate_success(
        api.withdraw_license_application(application["id"], ANALYST)
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"Withdrawal is the only remaining exit, got {withdrawn['status']}"
    )
    assert withdrawn["decided_at"] == CLOCK_DEFAULT_STAMP


def test_a_duplicate_finding_may_not_consolidate_a_complaint_into_itself(
    api: ApiClient,
):
    """PRD §3.6: "The consolidation target must exist, must not be the complaint
    being triaged, must concern the same `license_id`, and must itself have a
    `status` of `RECEIVED`, `TRIAGED`, `INVESTIGATION_OPEN`, or
    `EVIDENCE_COMPLETE` — a target that is itself already `CONSOLIDATED`,
    `DISMISSED`, or `CLOSED` cannot absorb another complaint."

    PRD §3.6: "Any failure of those conditions is refused with
    `ERR_CONSOLIDATION_TARGET_INVALID`."

    PRD §3.6: "A new complaint takes `status` `RECEIVED`, `jurisdiction_finding`
    `PENDING`, and a `received_at` stamped from the logical clock, with
    `consolidated_into_complaint_id`, `triaged_by_user_id`,
    `investigator_user_id`, and `disposition_at` all null."

    Design: Corner/validations/duplicate_triage_pointing_at_itself_returns_consolidation_target_invalid
    """
    ctx = seed_active_license(api)
    complaint = seed_complaint(api, ctx["license_id"],
                              complainant_type="OTHER_STATE_BOARD",
                              violation_category="PRACTICE_STANDARD",
                              incident_date="2026-07-02T00:00:00Z",
                              employer_custodian_codes=[])
    assert complaint["status"] == "RECEIVED"
    assert complaint["jurisdiction_finding"] == "PENDING"
    assert complaint["consolidated_into_complaint_id"] is None

    refused = api.triage_complaint(
        complaint["id"],
        {"jurisdiction_finding": "DUPLICATE", "target_complaint_id": complaint["id"]},
        INVESTIGATOR,
    )

    validate_error(refused, ApiErrorId.ERR_CONSOLIDATION_TARGET_INVALID.value)
    stored = reread_complaint(api, complaint["id"])
    assert stored["status"] == "RECEIVED", (
        f"A refused triage moves nothing, got {stored['status']}"
    )
    assert stored["jurisdiction_finding"] == "PENDING"
    assert stored["consolidated_into_complaint_id"] is None, (
        "No one-node consolidation chain was written"
    )
    assert stored["triaged_by_user_id"] is None


def test_alternative_to_discipline_is_refused_on_a_fraud_complaint(api: ApiClient):
    """PRD §3.6: "Offering alternative-to-discipline monitoring moves `status` to
    `ATD_OFFERED`, and is the most tightly gated of the three: the complaint's
    `violation_category` must be `SUBSTANCE_USE`, the nurse must have no
    monitoring agreement standing at `BREACHED`, and the nurse's
    `prior_discipline_count` must be 0."

    PRD §3.6: "A nurse who has already broken a monitoring agreement, or who has
    ever been disciplined, gets no second diversion, and the attempt is refused
    with `ERR_ATD_INELIGIBLE`."

    PRD §3.6: "Referring for a hearing moves `status` to `REFERRED_FOR_HEARING`
    and leaves the encumbrance exactly where it is."

    Design: Corner/validations/offering_atd_on_a_fraud_complaint_returns_atd_ineligible
    """
    ctx = seed_active_license(api)
    complaint = seed_evidence_complete_complaint(
        api, ctx["license_id"], page_count=18,
        evidence_overrides={"record_class": "EMPLOYER_INCIDENT",
                            "custodian_code": "MERCY-GEN",
                            "hold_start_at": "2026-08-02T00:00:00Z",
                            "hold_end_at": "2026-09-02T00:00:00Z"},
        complainant_type="EMPLOYER", violation_category="FRAUD",
        incident_date="2026-07-05T00:00:00Z",
        employer_custodian_codes=["MERCY-GEN"],
    )
    assert complaint["status"] == "EVIDENCE_COMPLETE"

    refused = api.dispose_complaint(complaint["id"], {"disposition": "OFFER_ATD"},
                                    INVESTIGATOR)

    validate_error(refused, ApiErrorId.ERR_ATD_INELIGIBLE.value)
    assert reread_complaint(api, complaint["id"])["status"] == "EVIDENCE_COMPLETE", (
        "A refused disposition leaves the complaint where it stood"
    )
    _, meta = validate_paginated(
        api.list_monitoring_agreements(INVESTIGATOR,
                                       params={"nurse_id": ctx["nurse_id"]})
    )
    assert meta["total_count"] == 0, (
        f"No agreement was offered to this nurse, got {meta['total_count']}"
    )
    referred = dispose_complaint(api, complaint["id"], "REFER_TO_PROCEEDING")
    assert referred["status"] == "REFERRED_FOR_HEARING", (
        "The contested route remains open to a fraud complaint"
    )


def test_a_hearing_date_inside_the_notice_period_is_refused_at_creation(api: ApiClient):
    """PRD §3.8: "The payload names the complaint through `complaint_id`, carries
    the `expected_complaint_version` described in §2.8, lists the panel through
    `seated_member_user_ids`, fixes the `hearing_date`, and may override
    `notice_period_days`, which defaults to 30."

    PRD §3.8: "Creation is refused with `ERR_NOTICE_PERIOD_NOT_MET` if the
    `hearing_date` does not sit at or after `noticed_at` advanced by
    `notice_period_days`."

    PRD §3.8: "The proceeding takes `status` `NOTICED`, stamps `noticed_at` from
    the logical clock, starts `continuance_count` at 0, `votes` as an empty array,
    `sanction_floor_tier` and `adopted_sanction_tier` at `NONE`, and
    `ordered_restriction_codes` as an empty array with `order_issued_at` null."

    Design: Corner/validations/proceeding_noticed_inside_the_notice_period_returns_notice_period_not_met
    """
    ctx = seed_referred_context(api, page_count=22)
    presiding = make_board_member_headers("bm-v11")
    version = complaint_version(api, ctx["complaint_id"])
    payload = {
        "complaint_id": ctx["complaint_id"],
        "expected_complaint_version": version,
        "seated_member_user_ids": ["bm-a", "bm-b", "bm-c"],
        "hearing_date": "2026-08-10T00:00:00Z",
    }

    refused = api.create_disciplinary_proceeding(payload, presiding)

    validate_error(refused, ApiErrorId.ERR_NOTICE_PERIOD_NOT_MET.value)
    unchanged = reread_complaint(api, ctx["complaint_id"])
    assert unchanged["status"] == "REFERRED_FOR_HEARING", (
        f"The complaint is untouched by the refused create, got {unchanged['status']}"
    )
    assert unchanged["version"] == version, (
        f"A refused create does not bump the parent, got version "
        f"{unchanged['version']} against {version}"
    )

    payload["hearing_date"] = "2026-08-31T00:00:00Z"
    opened = validate_success(
        api.create_disciplinary_proceeding(payload, presiding), 201
    )
    assert opened["status"] == "NOTICED", (
        f"Exactly thirty days out satisfies the notice period, got {opened['status']}"
    )
    assert opened["noticed_at"] == CLOCK_DEFAULT_STAMP, (
        f"noticed_at comes from the logical clock, got {opened['noticed_at']}"
    )
    assert opened["notice_period_days"] == 30, (
        f"The notice period defaults to 30, got {opened['notice_period_days']}"
    )
