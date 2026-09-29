"""The two non-linear state machines and the two four-link cascades."""
from test_helpers import (
    add_perfusionist,
    add_slot,
    ADMIN_HEADERS,
    api_client,
    assert_case_dimensions,
    assert_ce_hours,
    assert_cents,
    assert_contract_ledger,
    assert_device_state,
    assert_error_envelope,
    assert_event_log_fields,
    assert_fields_null,
    assert_readiness_score,
    build_incident_review,
    capture_device_event,
    close_case,
    close_incident_report,
    closed_case_setup,
    configure_pack,
    create_incident_report,
    end_bypass,
    make_perfusionist_headers,
    off_bypass_setup,
    open_checklist,
    pack_configured_setup,
    read_case,
    read_checklist,
    read_contract,
    read_device,
    read_incident_report,
    read_slot,
    review_incident_report,
    set_clock,
    settle_month,
    setup_verified_setup,
    staffed_setup,
    start_bypass,
    submit_incident_report,
    validate_error,
    validate_paginated,
    verify_checklist,
)


def _report_under_return_cycle(returns):
    """File a MAJOR report on an off-pump case and bounce it back `returns` times."""
    env = off_bypass_setup(
        end_bypass_overrides={
            "pump_time_minutes": 210,
            "cross_clamp_minutes": 95,
            "lowest_hematocrit_pct": 24,
            "adverse_event_count": 1,
        }
    )
    p2 = add_perfusionist(env, "p2", full_name="Tom Vasquez", employee_code="EMP-1003")
    report = create_incident_report(
        env["case"]["id"],
        env["p1"]["id"],
        p2["id"],
        severity="MAJOR",
        category="ANTICOAGULATION",
        narrative="ACT drifted below target for eleven minutes.",
    )
    env["report"] = submit_incident_report(report["id"], p2["id"])
    for index in range(returns):
        env["report"] = review_incident_report(
            report["id"], env["chief"]["id"], "RETURN_FOR_INFO", review_note="bounce %d" % index
        )
        env["report"] = submit_incident_report(report["id"], p2["id"])
    return env


def test_the_return_cycle_stops_at_two_while_the_accept_branch_of_the_same_call_still_opens():
    """A third return is refused, and the same endpoint accepts the very same report instead.

    PRD 3.9: A returned report goes back to the filer, who may resubmit, and the cycle `SUBMITTED → RETURNED_FOR_INFO → SUBMITTED` may run at most up to the two-return ceiling: a return attempt made when `return_count` has already reached 2 is refused with `ERR_INCIDENT_RETURN_LIMIT`, so a third return is not available and the chief must either accept the report for review or leave it submitted.
    PRD 3.9: Accepting for review moves the report `SUBMITTED → UNDER_REVIEW` and, crucially, **freezes** the audit variant of the involved perfusionist's readiness score onto the report as `reviewed_readiness_score`.
    PRD 3.9: Returning for more information moves the report `SUBMITTED → RETURNED_FOR_INFO`, raises `return_count` by one and leaves `reviewed_readiness_score` exactly as it was — null on a first return, because a returned report has not been audited.

    Design: Difficulty/non_linear_state_machine/incident_review_return_cycle_then_resubmit
    """
    env = _report_under_return_cycle(2)
    report_id = env["report"]["id"]
    assert env["report"]["status"] == "SUBMITTED"
    assert env["report"]["return_count"] == 2

    third = api_client.review_incident_report(
        report_id,
        build_incident_review("RETURN_FOR_INFO", review_note="third bounce"),
        env["chief_headers"],
    )
    validate_error(third, "ERR_INCIDENT_RETURN_LIMIT", 409)
    assert_error_envelope(third, "ERR_INCIDENT_RETURN_LIMIT")
    refused = read_incident_report(report_id)
    assert refused["status"] == "SUBMITTED", "the refused return must not move the report"
    assert refused["return_count"] == 2, "the refused return must not raise the counter"
    assert refused["reviewed_readiness_score"] is None

    accepted = review_incident_report(report_id, env["chief"]["id"], "ACCEPT_FOR_REVIEW")

    assert accepted["status"] == "UNDER_REVIEW"
    assert accepted["return_count"] == 2
    assert accepted["reviewed_readiness_score"] is not None, (
        "only the accept branch freezes the audit score"
    )
    assert_readiness_score(accepted["reviewed_readiness_score"], 0.45)
    assert accepted["finding"] == "NONE"
    assert accepted["corrective_action_required"] is False


def test_a_returned_report_carries_no_audit_score_and_resubmits_into_the_same_queue():
    """One turn of the loop leaves the frozen score null, and review is closed to a resubmission.

    PRD 3.9: Returning for more information moves the report `SUBMITTED → RETURNED_FOR_INFO`, raises `return_count` by one and leaves `reviewed_readiness_score` exactly as it was — null on a first return, because a returned report has not been audited.
    PRD 3.9: The absence of an audit score is precisely what distinguishes the two branches of the same operation.
    PRD 3.9: Only the filer may submit — the acting identity is compared against `filed_by_perfusionist_id` — and the report must be in `DRAFT` or in `RETURNED_FOR_INFO`, any other state drawing `ERR_INCIDENT_STATE_INVALID`.
    PRD 3.9: Accepting for review moves the report `SUBMITTED → UNDER_REVIEW` and, crucially, **freezes** the audit variant of the involved perfusionist's readiness score onto the report as `reviewed_readiness_score`.

    Design: Difficulty/non_linear_state_machine/incident_review_return_cycle_then_resubmit
    """
    env = _report_under_return_cycle(0)
    report_id = env["report"]["id"]
    assert env["report"]["status"] == "SUBMITTED"
    assert env["report"]["return_count"] == 0

    returned = review_incident_report(
        report_id, env["chief"]["id"], "RETURN_FOR_INFO", review_note="attach the ACT trend"
    )
    assert returned["status"] == "RETURNED_FOR_INFO"
    assert returned["return_count"] == 1
    assert returned["reviewed_readiness_score"] is None, (
        "a returned report has not been audited, so the frozen score stays null"
    )

    resubmitted = submit_incident_report(report_id, env["p2"]["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["return_count"] == 1
    assert resubmitted["reviewed_readiness_score"] is None

    accepted = review_incident_report(report_id, env["chief"]["id"], "ACCEPT_FOR_REVIEW")
    assert accepted["status"] == "UNDER_REVIEW"
    assert_readiness_score(accepted["reviewed_readiness_score"], 0.45)

    again = api_client.submit_incident_report(report_id, make_perfusionist_headers(env["p2"]["id"]))
    validate_error(again, "ERR_INCIDENT_STATE_INVALID", 409)
    assert read_incident_report(report_id)["status"] == "UNDER_REVIEW"


def test_three_clinical_transitions_leave_the_fiscal_dimension_pinned_where_assignment_put_it():
    """Pack, checklist and pump moves walk one dimension while the other holds its accrual.

    PRD 2.9: A bypass case carries two independent state dimensions: a clinical dimension in `bypass_status` and a fiscal dimension in `billing_status`.
    PRD 2.9: They advance on disjoint triggers, so the pair `(STAFFED, UNBILLED)` is as legitimate a resting state as `(STAFFED, PROVISIONAL_ACCRUED)` or `(CLOSED, INVOICED)`.
    PRD 2.9: No operation is permitted to infer one dimension from the other; each is moved only by the transitions that name it.
    PRD 3.10: The final variant of the case fee is computed and written to `final_fee_cents`, the fiscal dimension moves `PROVISIONAL_ACCRUED → FINAL_ACCRUED`, and the contract ledger absorbs **only the delta**: `accrued_case_fee_cents` changes by `final_fee_cents` minus `accrued_fee_cents`, after which `accrued_fee_cents` is set equal to `final_fee_cents`.
    PRD 3.10: As a side effect every settled case moves `FINAL_ACCRUED → INVOICED` with its `accrued_fee_cents` left **unchanged**, which is why invoicing does not disturb the contract's `accrued_case_fee_cents` at all: the ledger tracks what has been earned, and settlement only records that it has been billed.

    Design: Difficulty/non_linear_state_machine/case_bypass_and_billing_dimensions_advance_independently
    """
    env = staffed_setup()
    case_id = env["case"]["id"]
    assert_case_dimensions(env["case"], "STAFFED", "PROVISIONAL_ACCRUED")
    assert_cents(env["case"]["accrued_fee_cents"], 400000, "accrued_fee_cents")

    configure_pack(case_id, env["d1"]["id"], env["p1"]["id"])
    assert_case_dimensions(read_case(case_id), "PACK_CONFIGURED", "PROVISIONAL_ACCRUED")

    checklist = open_checklist(case_id, env["p1"]["id"], hematocrit_pct=26)
    assert_case_dimensions(read_case(case_id), "PACK_CONFIGURED", "PROVISIONAL_ACCRUED")

    verify_checklist(checklist["id"], env["p1"]["id"])
    verified = read_case(case_id)
    assert_case_dimensions(verified, "SETUP_VERIFIED", "PROVISIONAL_ACCRUED")
    assert_cents(verified["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert verified["final_fee_cents"] is None

    start_bypass(case_id, env["p1"]["id"])
    assert_case_dimensions(read_case(case_id), "ON_BYPASS", "PROVISIONAL_ACCRUED")
    end_bypass(
        case_id,
        env["p1"]["id"],
        pump_time_minutes=210,
        cross_clamp_minutes=95,
        lowest_hematocrit_pct=24,
        adverse_event_count=0,
    )
    off = read_case(case_id)
    assert_case_dimensions(off, "OFF_BYPASS", "PROVISIONAL_ACCRUED")
    assert off["final_fee_cents"] is None

    closed = close_case(case_id, env["chief"]["id"])
    assert_case_dimensions(closed, "CLOSED", "FINAL_ACCRUED")
    assert_cents(closed["final_fee_cents"], 520000, "final_fee_cents")
    assert_cents(closed["accrued_fee_cents"], 520000, "accrued_fee_cents")

    settle_month(env["contract"]["id"], "2026-08")

    invoiced = read_case(case_id)
    # The fiscal dimension moved on its own trigger; the clinical dimension did not follow.
    assert_case_dimensions(invoiced, "CLOSED", "INVOICED")
    assert_cents(invoiced["accrued_fee_cents"], 520000, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 520000, 1)


def test_the_fiscal_dimension_reaches_credited_while_the_clinical_dimension_stays_closed():
    """A crediting systemic close moves billing twice more and never touches bypass_status.

    PRD 2.9: A bypass case carries two independent state dimensions: a clinical dimension in `bypass_status` and a fiscal dimension in `billing_status`.
    PRD 2.9: No operation is permitted to infer one dimension from the other; each is moved only by the transitions that name it.
    PRD 3.9: When `credit_case_fee` is true **and** the case's `billing_status` reads `INVOICED`, the fiscal dimension moves `INVOICED → CREDITED`, the contract's `accrued_case_fee_cents` falls by the case's `accrued_fee_cents`, its `accrued_case_count` falls by one, and the case's `accrued_fee_cents` becomes 0.
    PRD 3.9: A crediting close is the only way a case leaves `INVOICED`, and `CREDITED` is terminal for the fiscal dimension.

    Design: Difficulty/non_linear_state_machine/case_bypass_and_billing_dimensions_advance_independently
    """
    env = closed_case_setup()
    case_id = env["case"]["id"]
    assert_case_dimensions(env["case"], "CLOSED", "FINAL_ACCRUED")
    assert_cents(env["case"]["final_fee_cents"], 400000, "final_fee_cents")

    settle_month(env["contract"]["id"], "2026-08")
    assert_case_dimensions(read_case(case_id), "CLOSED", "INVOICED")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)

    p2 = add_perfusionist(env, "p2", full_name="Tom Vasquez", employee_code="EMP-1003")
    report = create_incident_report(
        case_id,
        env["p1"]["id"],
        p2["id"],
        severity="SENTINEL",
        category="DEVICE_FAILURE",
        narrative="Oxygenator was changed out mid-run after a plasma leak.",
    )
    submit_incident_report(report["id"], p2["id"])
    review_incident_report(report["id"], env["chief"]["id"], "ACCEPT_FOR_REVIEW")

    closed_report = close_incident_report(
        report["id"], env["chief"]["id"], "SYSTEMIC", credit_case_fee=True
    )

    assert closed_report["status"] == "CLOSED_WITH_ACTION"
    credited = read_case(case_id)
    assert_case_dimensions(credited, "CLOSED", "CREDITED")
    assert_cents(credited["accrued_fee_cents"], 0, "accrued_fee_cents")
    assert_cents(credited["final_fee_cents"], 400000, "final_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 0, 0)


def test_a_critical_alarm_cascades_from_the_machine_through_case_checklist_and_ledger():
    """One captured alarm reaches four entities in order, each link opening the next.

    PRD 3.7: An `ALARM_CRITICAL`, an `ALARM_ADVISORY` or a `SELF_TEST_FAIL` raises the machine's `alarm_count_since_service` by one.
    PRD 3.7: And an `ALARM_CRITICAL` or a `SELF_TEST_FAIL` drives the machine to `NEEDS_SERVICE` from whichever of `AVAILABLE`, `RESERVED` or `IN_USE` it was in — which in turn fires a four-link cascade across the cases that were counting on it.
    PRD 3.7: The first link is the event itself, together with the counter increment and the machine's move to `NEEDS_SERVICE`.
    PRD 3.7: The second link reaches every bypass case naming that machine as its **primary** whose `bypass_status` is `PACK_CONFIGURED` or `SETUP_VERIFIED`: such a case falls back to `STAFFED`, its `setup_verified_at` is cleared to null, its `readiness_flag` is raised to `DEVICE_FALLBACK_REQUIRED`, both its `primary_device_id` and its `backup_device_id` are cleared to null, and the standby machine it was holding moves `RESERVED → AVAILABLE`.
    PRD 3.7: The third link invalidates paperwork: every pump checklist of each case affected by the primary-side link, in `DRAFT` or `VERIFIED`, moves to `INVALIDATED` with `blood_mgmt_signoff` false.
    PRD 3.7: The fourth link unwinds money: each of those same cases whose `billing_status` reads `PROVISIONAL_ACCRUED` moves to `UNBILLED`, its `accrued_fee_cents` drops to 0, and the contract's `accrued_case_fee_cents` falls by exactly that amount while `accrued_case_count` falls by one.
    PRD 3.7: Event logs are immutable and carry no `version`; they may be listed for one device filtered by `event_code`.

    Design: Difficulty/transitive_cascade/critical_alarm_cascades_device_case_checklist_billing
    """
    env = setup_verified_setup(checklist_overrides={"hematocrit_pct": 26})
    case_id = env["case"]["id"]
    assert_device_state(read_device(env["d1"]["id"]), "RESERVED", open_reservation_count=1)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", open_reservation_count=1)
    assert env["checklist"]["status"] == "VERIFIED"
    assert_case_dimensions(env["case"], "SETUP_VERIFIED", "PROVISIONAL_ACCRUED")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)

    event = capture_device_event(
        env["d1"]["id"],
        "ALARM_CRITICAL",
        detail="arterial pressure alarm latched during priming",
    )
    assert_event_log_fields(event)

    # Link 1: the alarmed machine.
    alarmed = read_device(env["d1"]["id"])
    assert_device_state(alarmed, "NEEDS_SERVICE", alarm_count_since_service=1)
    # Link 2: the case that was counting on it, and the standby it was holding.
    case = read_case(case_id)
    assert case["bypass_status"] == "STAFFED"
    assert case["readiness_flag"] == "DEVICE_FALLBACK_REQUIRED"
    assert_fields_null(case, ["setup_verified_at", "primary_device_id", "backup_device_id"])
    assert_device_state(read_device(env["d2"]["id"]), "AVAILABLE", open_reservation_count=0)
    # Link 3: the paperwork.
    checklist = read_checklist(env["checklist"]["id"])
    assert checklist["status"] == "INVALIDATED"
    assert checklist["blood_mgmt_signoff"] is False
    assert checklist["verified_at"] is None
    # Link 4: the money.
    assert case["billing_status"] == "UNBILLED"
    assert_cents(case["accrued_fee_cents"], 0, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 0, 0)

    logs, meta = validate_paginated(
        api_client.list_device_event_logs(env["d1"]["id"], env["tech_headers"])
    )
    assert meta["total_count"] == 1
    assert [row["event_code"] for row in logs] == ["ALARM_CRITICAL"]


def test_a_failed_self_test_unwinds_a_pack_configured_case_and_its_draft_checklist():
    """The same four links fire from the other qualifying code and from the earlier case state.

    PRD 3.7: An `ALARM_CRITICAL`, an `ALARM_ADVISORY` or a `SELF_TEST_FAIL` raises the machine's `alarm_count_since_service` by one.
    PRD 3.7: And an `ALARM_CRITICAL` or a `SELF_TEST_FAIL` drives the machine to `NEEDS_SERVICE` from whichever of `AVAILABLE`, `RESERVED` or `IN_USE` it was in — which in turn fires a four-link cascade across the cases that were counting on it.
    PRD 3.7: The second link reaches every bypass case naming that machine as its **primary** whose `bypass_status` is `PACK_CONFIGURED` or `SETUP_VERIFIED`: such a case falls back to `STAFFED`, its `setup_verified_at` is cleared to null, its `readiness_flag` is raised to `DEVICE_FALLBACK_REQUIRED`, both its `primary_device_id` and its `backup_device_id` are cleared to null, and the standby machine it was holding moves `RESERVED → AVAILABLE`.
    PRD 3.7: The third link invalidates paperwork: every pump checklist of each case affected by the primary-side link, in `DRAFT` or `VERIFIED`, moves to `INVALIDATED` with `blood_mgmt_signoff` false.
    PRD 3.7: The fourth link unwinds money: each of those same cases whose `billing_status` reads `PROVISIONAL_ACCRUED` moves to `UNBILLED`, its `accrued_fee_cents` drops to 0, and the contract's `accrued_case_fee_cents` falls by exactly that amount while `accrued_case_count` falls by one.
    PRD 3.7: A case whose primary machine was lost is back in `STAFFED`, so an attempt to go on pump reports `ERR_CASE_NOT_SETUP_VERIFIED` — the state check at rung 30 fires first and masks the flag check at rung 44.

    Design: Difficulty/transitive_cascade/critical_alarm_cascades_device_case_checklist_billing
    """
    env = pack_configured_setup()
    case_id = env["case"]["id"]
    checklist = open_checklist(case_id, env["p1"]["id"], hematocrit_pct=26)
    assert checklist["status"] == "DRAFT"
    assert_case_dimensions(read_case(case_id), "PACK_CONFIGURED", "PROVISIONAL_ACCRUED")

    capture_device_event(env["d1"]["id"], "SELF_TEST_FAIL", detail="pre-use self test failed")

    assert_device_state(
        read_device(env["d1"]["id"]), "NEEDS_SERVICE", alarm_count_since_service=1
    )
    case = read_case(case_id)
    assert case["bypass_status"] == "STAFFED"
    assert case["readiness_flag"] == "DEVICE_FALLBACK_REQUIRED"
    assert_fields_null(case, ["primary_device_id", "backup_device_id"])
    assert_device_state(read_device(env["d2"]["id"]), "AVAILABLE", open_reservation_count=0)
    invalidated = read_checklist(checklist["id"])
    assert invalidated["status"] == "INVALIDATED", "a DRAFT checklist is invalidated too"
    assert invalidated["blood_mgmt_signoff"] is False
    assert case["billing_status"] == "UNBILLED"
    assert_cents(case["accrued_fee_cents"], 0, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 0, 0)

    # The case is back in STAFFED, so the pump is closed to it on the state check.
    refused = api_client.start_bypass(case_id, env["p1_headers"])
    validate_error(refused, "ERR_CASE_NOT_SETUP_VERIFIED", 409)


def _report_under_review_off_pump(category="BLOOD_MANAGEMENT"):
    """Drive a case off pump and get a MAJOR report on it accepted for review."""
    env = off_bypass_setup(
        end_bypass_overrides={
            "pump_time_minutes": 210,
            "cross_clamp_minutes": 95,
            "lowest_hematocrit_pct": 24,
            "adverse_event_count": 1,
        }
    )
    p2 = add_perfusionist(env, "p2", full_name="Tom Vasquez", employee_code="EMP-1003")
    report = create_incident_report(
        env["case"]["id"],
        env["p1"]["id"],
        p2["id"],
        severity="MAJOR",
        category=category,
        narrative="Cell saver bowl discarded without protocol sign-off.",
    )
    submit_incident_report(report["id"], p2["id"])
    env["report"] = review_incident_report(
        report["id"], env["chief"]["id"], "ACCEPT_FOR_REVIEW", review_note="quality review opened"
    )
    return env


def _ccp_certification(perfusionist_id):
    """Read back the CCP cycle of one perfusionist."""
    rows, _ = validate_paginated(
        api_client.list_certifications(perfusionist_id, ADMIN_HEADERS)
    )
    ccp = [row for row in rows if row["cert_code"] == "CCP"]
    assert len(ccp) == 1, "expected exactly one CCP cycle"
    return ccp[0]


def test_a_systemic_finding_cascades_from_report_to_certification_slot_and_posture():
    """The credentialing link strips future primary call, and the stripped call drops the posture.

    PRD 3.9: The first link closes the report: `UNDER_REVIEW → CLOSED_WITH_ACTION`, `finding` set to `SYSTEMIC`, `corrective_action_required` set true, `closed_by_perfusionist_id` recorded.
    PRD 3.9: The second link reaches credentialing: the involved perfusionist's certification whose `cert_code` is `CCP` moves `ACTIVE → PROBATION` when its `probation_count` is below 2 — setting `remediation_credits_required` to 8 credit hours, `probation_credits_banked` to 0 and raising `probation_count` by one — or moves `PROBATION → REVOKED` when `probation_count` already stands at 2 or more, a third systemic finding ending the credential rather than extending probation.
    PRD 3.9: The third link reaches the rota: every call slot of that perfusionist whose `slot_type` is `PRIMARY_CALL`, whose `status` is `SCHEDULED` and whose `window_start` lies strictly after the logical clock moves to `RELEASED`, processed in ascending `window_start` with ties broken by ascending `created_at`.
    PRD 3.9: The fourth link reaches coverage: the coverage posture is recomputed for every contract that lost a slot, which may drop `coverage_posture` from `COVERED` to `THIN` or as far as `UNCOVERED`, and that in turn can block the scheduling of further elective cases on those contracts.
    PRD 3.3: Failing that, the contract is `THIN` when primary-call coverage reaches at least half the horizon, again 2160 minutes or more.
    PRD 3.3: Failing both, the contract is `UNCOVERED`.
    PRD 3.3: `SCHEDULED → RELEASED` is not an operator action at all: it is the third link of the systemic-finding cascade described in §3.9, which strips a sanctioned perfusionist of their future primary call.

    Design: Difficulty/transitive_cascade/systemic_incident_closure_cascades_cert_probation_slot_release
    """
    env = _report_under_review_off_pump()
    add_slot(
        env,
        env["p2"]["id"],
        key="slot_p2",
        slot_type="BACKUP_CALL",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )
    set_clock("2026-08-09T00:00:00Z")
    add_slot(
        env,
        env["p1"]["id"],
        key="slot_future",
        slot_type="PRIMARY_CALL",
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-13T00:00:00Z",
    )
    # The future window covers 2880 of the 4320 horizon minutes with no backup cover.
    assert read_contract(env["contract"]["id"])["coverage_posture"] == "THIN"
    assert read_slot(env["slot_p1"]["id"])["status"] == "COMPLETED"
    assert _ccp_certification(env["p1"]["id"])["status"] == "ACTIVE"
    device_before = read_device(env["d1"]["id"])["status"]
    checklist_before = read_checklist(env["checklist"]["id"])["status"]

    closed = close_incident_report(
        env["report"]["id"],
        env["chief"]["id"],
        "SYSTEMIC",
        closing_note="blood management protocol retraining ordered",
    )

    # Link 1: the report.
    assert closed["status"] == "CLOSED_WITH_ACTION"
    assert closed["finding"] == "SYSTEMIC"
    assert closed["corrective_action_required"] is True
    assert closed["closed_by_perfusionist_id"] == env["chief"]["id"]
    # Link 2: credentialing.
    cert = _ccp_certification(env["p1"]["id"])
    assert cert["status"] == "PROBATION"
    assert cert["probation_count"] == 1
    assert_ce_hours(cert["remediation_credits_required"], 8.0)
    assert_ce_hours(cert["probation_credits_banked"], 0.0)
    # Link 3: the rota.
    assert read_slot(env["slot_future"]["id"])["status"] == "RELEASED"
    assert read_slot(env["slot_p2"]["id"])["status"] == "SCHEDULED"
    assert read_slot(env["slot_p1"]["id"])["status"] == "COMPLETED"
    # Link 4: coverage.
    assert read_contract(env["contract"]["id"])["coverage_posture"] == "UNCOVERED"
    assert read_device(env["d1"]["id"])["status"] == device_before
    assert read_checklist(env["checklist"]["id"])["status"] == checklist_before


def test_the_systemic_cascade_leaves_backup_call_and_another_holders_primary_call_alone():
    """Credentialing still moves, but with no primary call to strip the posture never shifts.

    PRD 3.9: The second link reaches credentialing: the involved perfusionist's certification whose `cert_code` is `CCP` moves `ACTIVE → PROBATION` when its `probation_count` is below 2 — setting `remediation_credits_required` to 8 credit hours, `probation_credits_banked` to 0 and raising `probation_count` by one — or moves `PROBATION → REVOKED` when `probation_count` already stands at 2 or more, a third systemic finding ending the credential rather than extending probation.
    PRD 3.9: The third link reaches the rota: every call slot of that perfusionist whose `slot_type` is `PRIMARY_CALL`, whose `status` is `SCHEDULED` and whose `window_start` lies strictly after the logical clock moves to `RELEASED`, processed in ascending `window_start` with ties broken by ascending `created_at`.
    PRD 3.9: Slots already under way are left alone; only future primary call is stripped, and backup call is untouched.
    PRD 3.9: The fourth link reaches coverage: the coverage posture is recomputed for every contract that lost a slot, which may drop `coverage_posture` from `COVERED` to `THIN` or as far as `UNCOVERED`, and that in turn can block the scheduling of further elective cases on those contracts.
    PRD 3.3: Failing that, the contract is `THIN` when primary-call coverage reaches at least half the horizon, again 2160 minutes or more.

    Design: Difficulty/transitive_cascade/systemic_incident_closure_cascades_cert_probation_slot_release
    """
    env = _report_under_review_off_pump(category="GAS_EXCHANGE")
    set_clock("2026-08-09T00:00:00Z")
    add_slot(
        env,
        env["p1"]["id"],
        key="slot_p1_backup",
        slot_type="BACKUP_CALL",
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-13T00:00:00Z",
    )
    add_slot(
        env,
        env["p2"]["id"],
        key="slot_p2_primary",
        slot_type="PRIMARY_CALL",
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-13T00:00:00Z",
    )
    assert read_contract(env["contract"]["id"])["coverage_posture"] == "THIN"

    closed = close_incident_report(env["report"]["id"], env["chief"]["id"], "SYSTEMIC")

    assert closed["status"] == "CLOSED_WITH_ACTION"
    cert = _ccp_certification(env["p1"]["id"])
    assert cert["status"] == "PROBATION"
    assert cert["probation_count"] == 1
    # The sanctioned perfusionist holds only future backup call, which is untouched.
    assert read_slot(env["slot_p1_backup"]["id"])["status"] == "SCHEDULED"
    # Another holder's future primary call is none of this cascade's business.
    assert read_slot(env["slot_p2_primary"]["id"])["status"] == "SCHEDULED"
    # No contract lost a slot, so the posture that the primary cover earns still stands.
    assert read_contract(env["contract"]["id"])["coverage_posture"] == "THIN"
