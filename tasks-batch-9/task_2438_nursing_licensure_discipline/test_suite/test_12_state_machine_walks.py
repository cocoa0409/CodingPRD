"""Edge-by-edge walks of the licensure, complaint, monitoring, and report lifecycles."""
from test_helpers import (
    ADMIN,
    ANALYST,
    CLOCK_DEFAULT_STAMP,
    INVESTIGATOR,
    PRESIDING,
    THREE_MEMBER_PANEL,
    ApiClient,
    ApiErrorId,
    all_reports,
    assert_created_fresh,
    assert_license,
    assert_license_application,
    assert_license_dimensions,
    assert_notification_report,
    assert_privilege_triple,
    cast_vote,
    change_report_status,
    complete_evidence,
    license_application_payload,
    license_version,
    make_board_member_headers,
    record_production,
    renewal_application_payload,
    reread_complaint,
    reread_license,
    reread_nurse,
    reread_proceeding,
    record_monitoring_event,
    screening_offense_record,
    seed_active_license,
    seed_application,
    seed_board_program_nurse,
    seed_convened_proceeding,
    seed_evidence_request,
    seed_executed_agreement,
    seed_investigated_complaint,
    seed_screened_application,
    set_clock,
    submit_application,
    validate_error,
    validate_success,
    verify_application_qualification,
)


def test_a_new_application_opens_in_draft_with_no_workflow_field_touched(api: ApiClient):
    """PRD §3.2: "A new application begins at `DRAFT` with `screening_status`
    `NOT_ORDERED`, `deficiency_cycle_count` 0, `board_decision` `NONE`,
    `prior_license_verified` false, an empty `screening_offense_records` array, and
    both `submitted_at` and `decided_at` null."

    PRD §2.6: "`version` (integer): a counter that starts at 1 when the record is
    created and increments by exactly 1 on every mutation, including mutations that
    only touch derived fields."

    Design: Corner/state_machines/license_application_is_created_in_draft_initial_state
    """
    ctx = seed_board_program_nurse(api)

    created = validate_success(
        api.create_license_application(
            license_application_payload(ctx["nurse_id"], ctx["board_id"],
                                        ctx["program_id"]),
            ANALYST,
        ),
        201,
    )

    assert_license_application(created)
    assert_created_fresh(created)
    assert created["status"] == "DRAFT", (
        f"A filing opens at DRAFT, got {created['status']}"
    )
    assert created["submitted_at"] is None, (
        f"Creation does not submit, got {created['submitted_at']}"
    )
    assert created["decided_at"] is None, (
        f"Creation does not decide, got {created['decided_at']}"
    )
    assert created["screening_status"] == "NOT_ORDERED"
    assert created["board_decision"] == "NONE"
    assert created["prior_license_verified"] is False
    assert created["screening_offense_records"] == []

    reread = validate_success(api.get_license_application(created["id"], ANALYST))
    assert reread["status"] == "DRAFT", (
        f"The stored filing is still at DRAFT, got {reread['status']}"
    )


def test_a_deficiency_return_and_resubmission_still_reach_screening(api: ApiClient):
    """PRD §3.2: "Board staff who find a filing incomplete return it to the
    applicant, moving it from `SUBMITTED` to `DEFICIENT` and recording a
    `reason_note` explaining what is missing."

    PRD §3.2: "Each such return increments `deficiency_cycle_count` by one, and a
    returned application may be revised and resubmitted, moving `DEFICIENT` back to
    `SUBMITTED` and restamping `submitted_at`."

    PRD §3.2: "A successful verification passes the application through
    `QUALIFICATION_VERIFIED` and out the other side to `SCREENING_IN_PROGRESS`
    within the same request, setting `screening_status` to `REQUESTED` on the way."

    Design: Corner/state_machines/deficiency_then_resubmission_cycle_reaches_screening_in_progress
    """
    ctx = seed_board_program_nurse(api)
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"])
    submit_application(api, application["id"])

    returned = validate_success(
        api.return_license_application_deficient(
            application["id"], {"reason_note": "transcript missing seal"}, ANALYST
        )
    )
    assert returned["status"] == "DEFICIENT", (
        f"An incomplete filing goes back to the applicant, got {returned['status']}"
    )
    assert returned["deficiency_cycle_count"] == 1, (
        f"The return is counted, got {returned['deficiency_cycle_count']}"
    )

    resubmitted = submit_application(api, application["id"])
    assert resubmitted["status"] == "SUBMITTED", (
        f"A revised filing is resubmitted, got {resubmitted['status']}"
    )
    assert resubmitted["deficiency_cycle_count"] == 1, (
        "The count records history and does not rewind on resubmission, got "
        f"{resubmitted['deficiency_cycle_count']}"
    )

    verified = verify_application_qualification(api, application["id"])
    assert verified["status"] == "SCREENING_IN_PROGRESS", (
        "Qualification verification passes straight through to screening, got "
        f"{verified['status']}"
    )
    assert verified["screening_status"] == "REQUESTED"
    assert verified["decided_at"] is None, (
        f"Nothing has been decided yet, got {verified['decided_at']}"
    )
    assert verified["board_decision"] == "NONE"


def test_submitting_a_filing_that_is_already_submitted_is_refused(api: ApiClient):
    """PRD §3.2: "Submitting the application advances it from `DRAFT` to
    `SUBMITTED` and stamps `submitted_at` with the logical clock."

    PRD §2.11: "The target resource's current state is a declared origin state for
    the requested transition, the resource is not in a terminal state, and the
    governing board configuration is not `ARCHIVED` — otherwise
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/submitting_an_already_submitted_application_is_rejected
    """
    ctx = seed_board_program_nurse(api)
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"])
    first = submit_application(api, application["id"])
    assert first["submitted_at"] == CLOCK_DEFAULT_STAMP, (
        f"The first submit stamps the logical clock, got {first['submitted_at']}"
    )

    response = api.submit_license_application(application["id"], ANALYST)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_license_application(application["id"], ANALYST))
    assert reread["status"] == "SUBMITTED", (
        f"The refused submit moved nothing, got {reread['status']}"
    )
    assert reread["deficiency_cycle_count"] == 0
    assert reread["submitted_at"] == first["submitted_at"], (
        "The refused submit did not restamp the submission time"
    )


def test_a_withdrawn_filing_accepts_neither_submission_nor_a_second_withdrawal(
    api: ApiClient,
):
    """PRD §3.2: "An applicant may withdraw at any point before a decision, from
    `DRAFT`, `SUBMITTED`, or `DEFICIENT`, which moves the application to
    `WITHDRAWN` and stamps `decided_at`."

    PRD §3.2: "`ISSUED`, `DENIED`, and `WITHDRAWN` are terminal."

    PRD §2.11: "The target resource's current state is a declared origin state for
    the requested transition, the resource is not in a terminal state, and the
    governing board configuration is not `ARCHIVED` — otherwise
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/withdrawn_application_is_terminal_and_refuses_submit
    """
    ctx = seed_board_program_nurse(api)
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"])
    submit_application(api, application["id"])

    withdrawn = validate_success(
        api.withdraw_license_application(application["id"], ANALYST)
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"Withdrawal was legal from SUBMITTED, got {withdrawn['status']}"
    )
    assert withdrawn["decided_at"] == CLOCK_DEFAULT_STAMP, (
        f"Withdrawal stamps the decision time, got {withdrawn['decided_at']}"
    )

    validate_error(
        api.submit_license_application(application["id"], ANALYST),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api.withdraw_license_application(application["id"], ANALYST),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    reread = validate_success(api.get_license_application(application["id"], ANALYST))
    assert reread["status"] == "WITHDRAWN", (
        f"The terminal state holds, got {reread['status']}"
    )


def test_an_unconditional_approval_over_a_disqualifying_record_is_refused(
    api: ApiClient,
):
    """PRD §3.2: "The test is a lookback test: an entry is disqualifying when its
    `offense_code` appears in the board's `disqualifying_offense_codes` **and** its
    `disposition_date` is at or after the logical clock minus the board's
    `criminal_lookback_years`."

    PRD §3.2: "If at least one entry is disqualifying, `screening_status` becomes
    `DISQUALIFYING` and the application advances to `SCREENING_FLAGGED` and then,
    in the same request, to `BOARD_REVIEW`; the entry into `BOARD_REVIEW` queues a
    notification report on the `NPDB` channel with `source_entity_type`
    `LICENSE_APPLICATION`, `basis_code` `SCREENING_FLAG`, and `status` `QUEUED`."

    PRD §3.2: "Such an application may only be approved with monitoring or denied,
    and an attempt to clear it unconditionally is refused with
    `ERR_DISQUALIFYING_OFFENSE`."

    PRD §3.2: "Either approval moves the application from `BOARD_REVIEW` to
    `APPROVED`; a denial moves it to `DENIED` and queues a notification report on
    the `INTERSTATE_COMPACT` channel with `source_entity_type`
    `LICENSE_APPLICATION`, `basis_code` `APPLICATION_DENIED`, and `status`
    `QUEUED`."

    Design: Corner/state_machines/board_approval_over_a_disqualifying_screening_returns_disqualifying_offense
    """
    ctx = seed_board_program_nurse(api)
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"])
    submit_application(api, application["id"])
    verify_application_qualification(api, application["id"])
    flagged = validate_success(
        api.record_screening_result(
            application["id"],
            {"screening_offense_records": [
                screening_offense_record("FEL-A", "2023-05-01T00:00:00Z")
            ]},
            ANALYST,
        )
    )
    assert flagged["status"] == "BOARD_REVIEW", (
        f"A flagged filing lands in board review, got {flagged['status']}"
    )
    assert flagged["screening_status"] == "DISQUALIFYING", (
        f"A felony inside the lookback disqualifies, got {flagged['screening_status']}"
    )

    response = api.record_board_decision(
        application["id"], {"decision": "APPROVED_UNCONDITIONAL"},
        make_board_member_headers("bm-corner-1"),
    )

    validate_error(response, ApiErrorId.ERR_DISQUALIFYING_OFFENSE.value)
    held = validate_success(api.get_license_application(application["id"], ANALYST))
    assert held["status"] == "BOARD_REVIEW", (
        f"The refused vote left the filing in review, got {held['status']}"
    )
    assert held["board_decision"] == "NONE", (
        f"No decision was written, got {held['board_decision']}"
    )

    denied = validate_success(
        api.record_board_decision(application["id"], {"decision": "DENIED"},
                                  make_board_member_headers("bm-corner-1"))
    )
    assert denied["status"] == "DENIED", (
        f"Denial is an available exit, got {denied['status']}"
    )
    assert denied["board_decision"] == "DENIED"


def test_minting_a_credential_stamps_its_dates_and_resolves_its_privilege(
    api: ApiClient,
):
    """PRD §3.3: "The system mints a board-assigned `license_number`, sets
    `license_status` to `ACTIVE` and `encumbrance_status` to `CLEAR`, stamps
    `issued_on` from the logical clock, sets `expires_on` to `issued_on` advanced
    by the board's `renewal_period_months`, initialises `practice_restriction_codes`
    to an empty array and `open_encumbrance_count` to 0, and moves the source
    application from `APPROVED` to the terminal `ISSUED`."

    PRD §3.3: "Under `RESIDENCY_DECLARED` — the variant used at issuance, on every
    registration change, and whenever it is requested explicitly — the primary
    state of residence is simply the nurse's `declared_primary_state`, taken at
    face value."

    PRD §3.3: "Only when both propagation rules pass is the answer `MULTISTATE`."

    PRD §3.3: "A credential whose `credential_type` is `NURSE_AIDE` is a registry
    entry rather than a practice licence, and minting one additionally queues a
    notification report on the `NURSE_AIDE_REGISTRY` channel with
    `source_entity_type` `LICENSE`, `report_kind` `INITIAL`, `basis_code`
    `REGISTRY_ENTRY`, and `status` `QUEUED`."

    Design: Corner/state_machines/issuing_a_license_stamps_dates_and_runs_the_privilege_determination
    """
    ctx = seed_screened_application(api)
    assert ctx["application"]["status"] == "APPROVED", (
        f"A clean screening approves outright, got {ctx['application']['status']}"
    )
    assert ctx["application"]["board_decision"] == "APPROVED_UNCONDITIONAL"

    credential = validate_success(
        api.create_license({"source_application_id": ctx["application_id"]}, ANALYST),
        201,
    )

    assert_license(credential)
    assert_license_dimensions(credential, "ACTIVE", "CLEAR")
    assert credential["issued_on"] == CLOCK_DEFAULT_STAMP, (
        f"Issuance stamps the logical clock, got {credential['issued_on']}"
    )
    assert credential["expires_on"] == "2028-08-01T00:00:00.000Z", (
        "A twenty-four month term from the default clock ends 2028-08-01, got "
        f"{credential['expires_on']}"
    )
    assert_privilege_triple(credential, "MULTISTATE", "RESIDENCY_DECLARED", "OH")
    assert isinstance(credential["license_number"], str) and credential["license_number"], (
        f"The board assigns a number, got {credential['license_number']!r}"
    )
    assert credential["open_encumbrance_count"] == 0
    assert credential["practice_restriction_codes"] == []

    application = validate_success(
        api.get_license_application(ctx["application_id"], ANALYST)
    )
    assert application["status"] == "ISSUED", (
        f"The source filing reaches its terminal state, got {application['status']}"
    )

    reports = all_reports(api, subject_nurse_id=ctx["nurse_id"])
    assert reports == [], (
        f"A registered-nurse credential is not a reportable registry entry, got {reports}"
    )


def test_evidence_cannot_be_closed_while_one_demand_is_still_outstanding(
    api: ApiClient,
):
    """PRD §3.6: "**Closing the evidence phase** moves the complaint from
    `INVESTIGATION_OPEN` to `EVIDENCE_COMPLETE`, and is permitted only when the
    complaint has at least one records demand and every one of them stands at
    `PRODUCED` or `WITHDRAWN`; a complaint with no demands at all, or with even one
    still `REQUESTED`, cannot close its evidence phase and the attempt is refused
    with `ERR_INVALID_STATE`."

    PRD §3.6: "Recording a **production** moves the demand from `REQUESTED` to
    `PRODUCED`, writes the supplied `page_count`, and stamps `produced_at` from the
    logical clock."

    PRD §3.6: "A new demand takes `status` `REQUESTED` and `page_count` 0, with
    `produced_at` null."

    Design: Corner/state_machines/evidence_completion_with_an_outstanding_request_is_rejected
    """
    ctx = seed_active_license(api)
    complaint = seed_investigated_complaint(
        api, ctx["license_id"],
        complainant_type="EMPLOYER",
        violation_category="PRACTICE_STANDARD",
        incident_date="2026-07-02T00:00:00Z",
        employer_custodian_codes=["MERCY-GEN", "ST-LUKE"],
    )
    first = seed_evidence_request(
        api, complaint["id"], record_class="EMPLOYER_PERSONNEL",
        custodian_code="MERCY-GEN",
        hold_start_at="2026-08-02T00:00:00Z", hold_end_at="2026-09-02T00:00:00Z",
    )
    second = seed_evidence_request(
        api, complaint["id"], record_class="EMPLOYER_INCIDENT",
        custodian_code="ST-LUKE",
        hold_start_at="2026-08-02T00:00:00Z", hold_end_at="2026-09-02T00:00:00Z",
    )
    produced = record_production(api, first["id"], 44)
    assert produced["status"] == "PRODUCED"
    assert produced["page_count"] == 44
    assert produced["produced_at"] == CLOCK_DEFAULT_STAMP

    response = api.complete_complaint_evidence(complaint["id"], INVESTIGATOR)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert reread_complaint(api, complaint["id"])["status"] == "INVESTIGATION_OPEN", (
        "The refused closure left the investigation open"
    )
    outstanding = validate_success(api.get_evidence_request(second["id"], INVESTIGATOR))
    assert outstanding["status"] == "REQUESTED", (
        f"The unsatisfied demand was not silently withdrawn, got {outstanding['status']}"
    )

    record_production(api, second["id"], 12)
    closed = complete_evidence(api, complaint["id"])
    assert closed["status"] == "EVIDENCE_COMPLETE", (
        f"With both demands satisfied the phase closes, got {closed['status']}"
    )


def test_a_queued_report_walks_transmission_and_acknowledgement_once(api: ApiClient):
    """PRD §3.9: "A newly queued report holds `status` `QUEUED` with `queued_at`
    stamped from the logical clock and both `transmitted_at` and `acknowledged_at`
    null."

    PRD §3.9: "Moving to `TRANSMITTED` requires the report to be `QUEUED` and
    stamps `transmitted_at`."

    PRD §3.9: "Moving to `ACKNOWLEDGED`, which is terminal, requires the report to
    be `TRANSMITTED` and stamps `acknowledged_at`."

    PRD §3.9: "An acknowledged report cannot be voided."

    Design: Corner/state_machines/notification_report_walks_queued_then_transmitted_then_acknowledged
    """
    ctx = seed_board_program_nurse(api)
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"])
    submit_application(api, application["id"])
    verify_application_qualification(api, application["id"])
    validate_success(
        api.record_screening_result(
            application["id"],
            {"screening_offense_records": [
                screening_offense_record("FEL-A", "2023-05-01T00:00:00Z")
            ]},
            ANALYST,
        )
    )

    queued = all_reports(api, subject_nurse_id=ctx["nurse_id"], channel="NPDB")
    assert len(queued) == 1, (
        f"The screening flag queues exactly one national report, got {len(queued)}"
    )
    report = queued[0]
    assert_notification_report(report)
    assert report["source_entity_type"] == "LICENSE_APPLICATION"
    assert report["basis_code"] == "SCREENING_FLAG"
    assert report["report_kind"] == "INITIAL"
    assert report["status"] == "QUEUED"
    assert report["queued_at"] == CLOCK_DEFAULT_STAMP
    assert report["transmitted_at"] is None
    assert report["acknowledged_at"] is None

    transmitted = change_report_status(api, report["id"], "TRANSMITTED")
    assert transmitted["status"] == "TRANSMITTED"
    assert transmitted["transmitted_at"] == CLOCK_DEFAULT_STAMP, (
        f"Transmission is stamped, got {transmitted['transmitted_at']}"
    )

    acknowledged = change_report_status(api, report["id"], "ACKNOWLEDGED")
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_at"] == CLOCK_DEFAULT_STAMP, (
        f"Acknowledgement is stamped, got {acknowledged['acknowledged_at']}"
    )
    assert acknowledged["report_kind"] == "INITIAL", (
        f"The kind is untouched by the walk, got {acknowledged['report_kind']}"
    )
    assert acknowledged["queued_at"] == report["queued_at"]

    validate_error(
        api.change_notification_report_status(report["id"], {"to_status": "VOID"}, ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_a_lapsed_credential_can_no_longer_be_renewed_or_reactivated(api: ApiClient):
    """PRD §3.3: "Second, every credential whose `license_status` is `EXPIRED` and
    whose `expires_on` advanced by the board's `lapse_after_grace_days` is at or
    before the new clock value moves to the terminal `LAPSED`; its
    `multistate_privilege_status` is set to `NOT_ELIGIBLE`, and every renewal
    filing on that credential still in a non-terminal filing state — `DRAFT`,
    `SUBMITTED`, `CE_DEFICIENT`, or `CE_VERIFIED` — is moved to `WITHDRAWN`."

    PRD §3.3: "First, every credential whose `license_status` is `ACTIVE` and whose
    `expires_on` is at or before the new clock value moves to `EXPIRED`, and its
    privilege determination is re-run, necessarily yielding `NOT_ELIGIBLE`; the
    identifiers of those credentials are reported in `expired_license_ids`."

    PRD §2.11: "The credential is renewable: its `license_status` is `ACTIVE` or
    `EXPIRED`, and when it is `EXPIRED` the logical clock is at or before its
    `expires_on` plus the board's `renewal_grace_period_days`. Otherwise
    `ERR_LICENSE_NOT_RENEWABLE`. This applies when a renewal is created, when it is
    paid, and when it is submitted."

    Design: Corner/state_machines/lapsed_license_is_terminal_and_refuses_renewal_creation
    """
    ctx = seed_active_license(api)
    expiry_sweep = set_clock(api, "2028-08-02T00:00:00Z")
    assert ctx["license_id"] in expiry_sweep["expired_license_ids"], (
        f"The expiry sweep names the credential, got {expiry_sweep['expired_license_ids']}"
    )
    lapse_sweep = set_clock(api, "2028-11-01T00:00:00Z")
    assert ctx["license_id"] in lapse_sweep["lapsed_license_ids"], (
        f"The lapse sweep names the credential, got {lapse_sweep['lapsed_license_ids']}"
    )
    credential = reread_license(api, ctx["license_id"])
    assert credential["license_status"] == "LAPSED", (
        f"Ninety days past expiry the credential lapses, got {credential['license_status']}"
    )
    assert credential["multistate_privilege_status"] == "NOT_ELIGIBLE"

    response = api.create_renewal_application(
        renewal_application_payload(ctx["license_id"],
                                    license_version(api, ctx["license_id"]),
                                    attested_practice_hours=1200),
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_LICENSE_NOT_RENEWABLE.value)
    validate_error(
        api.change_license_status(ctx["license_id"], {"to_status": "ACTIVE"}, ANALYST),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert reread_license(api, ctx["license_id"])["license_status"] == "LAPSED", (
        "The terminal registration state holds"
    )


def test_three_missed_screens_suspend_monitoring_and_a_report_restores_it(
    api: ApiClient,
):
    """PRD §3.7: "A `MISSED_SCREEN` increases `missed_screen_count` by the reported
    `missed_screens`, and once the running total reaches 3 or more the agreement is
    forced from `ACTIVE` to `SUSPENDED_PENDING_REVIEW`."

    PRD §3.7: "A `COMPLIANCE_REPORT` increments `compliance_report_count` by one
    and resets `missed_screen_count` to 0; if the agreement was sitting at
    `SUSPENDED_PENDING_REVIEW` it is returned to `ACTIVE`, completing the cycle
    from `ACTIVE` to `SUSPENDED_PENDING_REVIEW` and back."

    PRD §3.7: "Execution stamps `executed_at` from the logical clock and moves
    `status` from `OFFERED` to `EXECUTED`; if `start_date` is already at or before
    the logical clock, the agreement is advanced further to `ACTIVE` in the very
    same request, and only a future `start_date` leaves it sitting at `EXECUTED`."

    PRD §3.7: "The linked complaint moves from `ATD_OFFERED` to `ATD_ACTIVE`, and
    the nurse's `atd_participation_count` is incremented by one."

    Design: Corner/state_machines/monitoring_missed_screens_suspend_then_a_compliance_report_reactivates
    """
    ctx = seed_executed_agreement(
        api,
        complaint_overrides={
            "complainant_type": "SELF_REPORT",
            "violation_category": "SUBSTANCE_USE",
            "incident_date": "2026-07-10T00:00:00Z",
            "employer_custodian_codes": ["MERCY-GEN"],
            "page_count": 20,
            "evidence_overrides": {
                "record_class": "EMPLOYER_PERSONNEL",
                "custodian_code": "MERCY-GEN",
                "hold_start_at": "2026-08-02T00:00:00Z",
                "hold_end_at": "2026-09-02T00:00:00Z",
            },
        },
        start_date="2026-08-01T00:00:00Z",
        end_date="2027-08-01T00:00:00Z",
    )
    assert ctx["agreement"]["status"] == "ACTIVE", (
        "A start date already reached carries the agreement past EXECUTED, got "
        f"{ctx['agreement']['status']}"
    )
    assert reread_complaint(api, ctx["complaint_id"])["status"] == "ATD_ACTIVE"

    after_two = record_monitoring_event(api, ctx["agreement_id"], "MISSED_SCREEN",
                                        "mc-3", missed_screens=2)
    assert after_two["status"] == "ACTIVE", (
        f"Two missed screens do not reach the threshold, got {after_two['status']}"
    )
    assert after_two["missed_screen_count"] == 2

    after_three = record_monitoring_event(api, ctx["agreement_id"], "MISSED_SCREEN",
                                          "mc-3", missed_screens=1)
    assert after_three["status"] == "SUSPENDED_PENDING_REVIEW", (
        f"The third missed screen suspends the programme, got {after_three['status']}"
    )
    assert after_three["missed_screen_count"] == 3

    after_report = record_monitoring_event(api, ctx["agreement_id"], "COMPLIANCE_REPORT",
                                           "mc-3")
    assert after_report["status"] == "ACTIVE", (
        f"A compliance report reinstates the programme, got {after_report['status']}"
    )
    assert after_report["missed_screen_count"] == 0, (
        f"The counter is zeroed, got {after_report['missed_screen_count']}"
    )
    assert after_report["compliance_report_count"] == 1

    assert reread_complaint(api, ctx["complaint_id"])["status"] == "ATD_ACTIVE", (
        "The complaint rides out the suspension cycle unchanged"
    )
    assert_license_dimensions(reread_license(api, ctx["license_id"]),
                              "ACTIVE", "INVESTIGATION_PENDING")
    assert reread_nurse(api, ctx["nurse_id"])["atd_participation_count"] == 1


def test_deactivating_and_reactivating_a_credential_recomputes_its_privilege(
    api: ApiClient,
):
    """PRD §3.3: "Placing a credential on inactive status, transitioning
    `license_status` from `ACTIVE` to `INACTIVE`, requires that the credential
    currently be `ACTIVE` and that its `encumbrance_status` be either `CLEAR` or
    `INVESTIGATION_PENDING`; the privilege determination is re-run and necessarily
    yields `NOT_ELIGIBLE`, because the credential is no longer `ACTIVE`."

    PRD §3.3: "Reactivating runs the cycle the other way, `INACTIVE` back to
    `ACTIVE`, and requires only that `encumbrance_status` not be `REVOKED`; the
    privilege determination is re-run under `RESIDENCY_DECLARED`."

    PRD §3.3: "**Compact privilege** is recomputed, never stored by hand."

    Design: Corner/state_machines/license_deactivation_then_reactivation_restores_multistate_privilege
    """
    ctx = seed_active_license(api)
    assert ctx["license"]["multistate_privilege_status"] == "MULTISTATE"
    issued_expiry = ctx["license"]["expires_on"]

    deactivated = validate_success(
        api.change_license_status(ctx["license_id"], {"to_status": "INACTIVE"}, ANALYST)
    )
    assert deactivated["license_status"] == "INACTIVE"
    assert deactivated["multistate_privilege_status"] == "NOT_ELIGIBLE", (
        "An inactive credential holds no privilege, got "
        f"{deactivated['multistate_privilege_status']}"
    )

    reactivated = validate_success(
        api.change_license_status(ctx["license_id"], {"to_status": "ACTIVE"}, ANALYST)
    )

    assert reactivated["license_status"] == "ACTIVE"
    assert_privilege_triple(reactivated, "MULTISTATE", "RESIDENCY_DECLARED", "OH")
    assert reactivated["encumbrance_status"] == "CLEAR"
    assert reactivated["expires_on"] == issued_expiry, (
        f"Registration standing does not move the expiry: {issued_expiry} became "
        f"{reactivated['expires_on']}"
    )


def test_a_hearing_closed_with_no_clearing_tier_dissolves_the_matter(api: ApiClient):
    """PRD §3.8: "`CLOSE_HEARING` moves `HEARING_CONVENED` to `DELIBERATION`,
    requires at least one vote cast by a seated non-recused member, and writes the
    tallied result into `adopted_sanction_tier`."

    PRD §3.8: "When the tally yields `NONE`, the system advances the proceeding
    further to the terminal `DISMISSED_BY_PANEL` in the same request, moves the
    complaint from `PROCEEDING_OPENED` to the terminal `DISMISSED`, and returns the
    credential's encumbrance from `INVESTIGATION_PENDING` to `CLEAR` once
    `open_encumbrance_count` reaches zero — a panel that cannot agree on any
    sanction dissolves the encumbrance."

    PRD §3.8: "Members who never voted are still counted in the denominator, so
    abstentions weigh against every tier."

    PRD §3.8: "The threshold applied is the board's `revocation_vote_threshold_bp`
    at index 6 and the board's `majority_vote_threshold_bp` at every other index,
    and the test is integer cross-multiplication: the support count multiplied by
    10000 must be at or above the threshold multiplied by the seated count."

    Design: Corner/state_machines/closing_a_hearing_with_no_clearing_tier_dismisses_by_panel
    """
    ctx = seed_convened_proceeding(
        api, THREE_MEMBER_PANEL,
        proceeding_overrides={"hearing_date": "2026-09-15T00:00:00Z"},
        page_count=31,
        evidence_overrides={
            "record_class": "EMPLOYER_PERSONNEL",
            "custodian_code": "MERCY-GEN",
            "hold_start_at": "2026-08-02T00:00:00Z",
            "hold_end_at": "2026-09-02T00:00:00Z",
        },
        complainant_type="PATIENT",
        violation_category="PRACTICE_STANDARD",
        incident_date="2026-07-02T00:00:00Z",
        employer_custodian_codes=["MERCY-GEN"],
    )
    assert ctx["proceeding"]["status"] == "HEARING_CONVENED"
    assert ctx["proceeding"]["sanction_floor_tier"] == "REPRIMAND", (
        "A mitigated practice-standard matter floors at the mildest tier, got "
        f"{ctx['proceeding']['sanction_floor_tier']}"
    )
    assert ctx["proceeding"]["recused_member_user_ids"] == []
    cast_vote(api, ctx["proceeding_id"], "bm-1", "REPRIMAND")

    closed = validate_success(
        api.record_hearing_event(ctx["proceeding_id"], {"event_type": "CLOSE_HEARING"},
                                 PRESIDING)
    )

    assert closed["adopted_sanction_tier"] == "NONE", (
        "One of three seated members cannot carry a majority, got "
        f"{closed['adopted_sanction_tier']}"
    )
    assert closed["status"] == "DISMISSED_BY_PANEL", (
        f"An empty tally dissolves the proceeding, got {closed['status']}"
    )
    assert reread_complaint(api, ctx["complaint_id"])["status"] == "DISMISSED"
    credential = reread_license(api, ctx["license_id"])
    assert_license_dimensions(credential, "ACTIVE", "CLEAR")
    assert credential["open_encumbrance_count"] == 0
    nurse = reread_nurse(api, ctx["nurse_id"])
    assert nurse["status"] == "ACTIVE"
    assert nurse["prior_discipline_count"] == 0, (
        f"A panel dismissal is not discipline, got {nurse['prior_discipline_count']}"
    )

    validate_error(
        api.issue_order(ctx["proceeding_id"], PRESIDING, {"ordered_restriction_codes": []}),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert reread_proceeding(api, ctx["proceeding_id"])["status"] == "DISMISSED_BY_PANEL"
