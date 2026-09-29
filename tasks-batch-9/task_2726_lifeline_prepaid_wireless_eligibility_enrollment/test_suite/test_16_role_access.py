"""Role access: exclusive writes, per-row ownership between peer carriers, and segregation of duties."""

from test_helpers import (
    AUDITOR_ADJUDICATOR,
    AUDITOR_ADJUDICATOR_ID,
    AUDITOR_DRAWER,
    AUDITOR_DRAWER_ID,
    NATIONAL_VERIFIER,
    PROGRAM_ADMIN,
    PROGRAM_ADMIN_ALT,
    PROGRAM_ADMIN_ID,
    ApiErrorId,
    assert_date_component,
    assert_instant,
    assert_instant_null,
    assert_ledger_tuple,
    expected_risk_score,
    factories as f,
    fixtures as fx,
    make_program_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
JUNE_START = "2026-06-01T00:00:00Z"
JULY_FILING = "2026-07-02T00:00:00Z"
DE_ENROLL_INSTANT = "2026-07-03T00:00:00Z"
PORT_FREEZE_UNTIL = "2026-09-30T00:00:00Z"
AFTER_FREEZE = "2026-10-01T00:00:00Z"
THIRD_ADMIN_ID = "PA-3"
THIRD_ADMIN = make_program_admin_headers(THIRD_ADMIN_ID)


def test_five_exclusive_writes_refuse_the_wrong_role_then_admit_the_right_one(api):
    """Each 403 is followed by the identical request from its owning role, and the shared
    operations answer two different roles on the same row.

    PRD: "A value of `X-User-Role` that is not one of these five is treated as a
    permitted-role failure rather than as a schema problem; the same code is returned when a
    recognised role attempts an operation it is not authorized for."

    Design: Corner/rbac/exclusive_operations_are_closed_to_every_other_role
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    agent = fx.provider_headers(provider)
    dwelling = fx.register_distinct_address(api, 1, headers=agent)
    applicant = fx.create_subscriber(api, dwelling["id"], headers=agent)
    check = fx.open_eligibility_check(api, applicant["id"], headers=agent)
    assert check["status"] == "PENDING_VERIFIER"
    holder = fx.subscriber_headers(applicant)

    rogue_registration = api.create_provider(
        f.provider_payload(name="Rogue Carrier", licensed_state_codes=["TX"], enrollment_cap=10),
        NATIONAL_VERIFIER,
    )
    validate_error(rogue_registration, ApiErrorId.UNAUTHORIZED.value, 403)

    agent_verdict = api.submit_verifier_result(
        check["id"], f.verifier_result_payload(verifier_outcome="MATCH"), agent
    )
    validate_error(agent_verdict, ApiErrorId.UNAUTHORIZED.value, 403)
    assert fx.refresh_eligibility_check(api, check["id"])["status"] == "PENDING_VERIFIER", (
        "the refused verdict left the certification where it was"
    )

    confirmed = validate_success(
        api.submit_verifier_result(
            check["id"],
            f.verifier_result_payload(verifier_outcome="MATCH"),
            NATIONAL_VERIFIER,
        )
    )
    assert confirmed["status"] == "ELIGIBLE_CONFIRMED", (
        "the identical verdict from the verifier is admitted"
    )

    body = f.enrollment_payload(
        subscriber_id=applicant["id"],
        provider_id=provider["id"],
        eligibility_check_id=check["id"],
        certified_address_id=dwelling["id"],
        service_type="VOICE",
        one_per_household_attested=True,
        benefit_start_date=CLOCK,
    )
    self_enrollment = api.create_enrollment(body, holder)
    validate_error(self_enrollment, ApiErrorId.UNAUTHORIZED.value, 403)
    _none, none_meta = validate_paginated(
        api.list_enrollments(PROGRAM_ADMIN, {"subscriber_id": applicant["id"]})
    )
    assert none_meta["total_count"] == 0, "the refused enrollment wrote no benefit row"

    benefit = validate_success(api.create_enrollment(body, agent), 201)
    assert benefit["benefit_status"] == "ACTIVE", (
        "the identical body from the carrier's own agent is admitted"
    )

    agent_sweep = api.run_compliance_sweep(provider["id"], agent)
    validate_error(agent_sweep, ApiErrorId.UNAUTHORIZED.value, 403)

    agent_recert = api.recertify(
        benefit["id"],
        f.recertify_payload(
            household_size=4,
            annual_income_cents=3000000,
            last_3mo_income_cents=750000,
            attested_qualifying_benefit="NONE",
        ),
        agent,
    )
    validate_error(agent_recert, ApiErrorId.UNAUTHORIZED.value, 403)
    assert agent_recert.json()["data"]["error_id"] != ApiErrorId.RECERT_NOT_NOTICED.value, (
        "the role check answers before the recertification state is examined"
    )

    shared_usage = validate_success(
        api.record_usage(benefit["id"], f.usage_payload(), PROGRAM_ADMIN)
    )
    assert shared_usage["usage_status"] == "USING", (
        "recording activity is shared with the administrator, not reserved to the carrier"
    )

    shared_read = validate_success(api.get_enrollment(benefit["id"], NATIONAL_VERIFIER))
    assert shared_read["benefit_status"] == "ACTIVE", "every read is open to all five roles"

    settled = fx.refresh_enrollment(api, benefit["id"])
    assert settled["recert_status"] == "NOT_DUE"
    assert_instant(settled["last_usage_at"], CLOCK, "last_usage_at")


def test_each_carrier_is_barred_from_the_endpoint_the_other_one_owns(api):
    """Issuing into a rival's benefit and accepting one's own outbound port are both refused.

    PRD: "On a port request the carrier that must match is the source carrier derived from
    the enrollment's current carrier reference; on accepting or rejecting a port the acting
    `X-User-ID` must instead be the gaining carrier named by `target_provider_id`."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_a_peers_rows
    """
    fx.set_clock(api, CLOCK)
    holding, gaining = fx.register_provider_pair(api, licensed_state_codes=["TX"])
    handset = fx.stock_device(api, holding, model_tier="BASIC", unit_cost_cents=2100)
    dwelling = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, dwelling["id"])
    benefit = fx.enroll(
        api,
        holding,
        applicant["subscriber"],
        applicant["check"],
        dwelling,
        service_type="VOICE",
        benefit_start_date=CLOCK,
    )
    assert_instant(benefit["port_freeze_until"], PORT_FREEZE_UNTIL, "port_freeze_until")

    fx.set_clock(api, AFTER_FREEZE)
    rival_issuance = api.issue_device(
        benefit["id"],
        f.device_issuance_payload(device_id=handset["id"]),
        fx.provider_headers(gaining),
    )
    validate_error(rival_issuance, ApiErrorId.UNAUTHORIZED.value, 403)
    assert fx.refresh_device(api, handset["id"])["status"] == "IN_STOCK", (
        "ownership is checked per row, so the rival's call wrote nothing"
    )

    issued = fx.issue_device(api, benefit["id"], holding, device_id=handset["id"])
    assert issued["status"] == "ISSUED", "the owning carrier's identical call is admitted"

    version = fx.enrollment_version(api, benefit["id"])
    gaining_opens = api.create_service_transfer(
        f.service_transfer_payload(
            enrollment_id=benefit["id"],
            target_provider_id=gaining["id"],
            expected_enrollment_version=version,
            subscriber_consent_ref="CONSENT-51",
        ),
        fx.provider_headers(gaining),
    )
    validate_error(gaining_opens, ApiErrorId.UNAUTHORIZED.value, 403)
    _no_ports, no_ports_meta = validate_paginated(
        api.list_service_transfers(PROGRAM_ADMIN, {"enrollment_id": benefit["id"]})
    )
    assert no_ports_meta["total_count"] == 0, (
        "on a port request the matching carrier is the source, so the gaining side wrote nothing"
    )

    opened = fx.request_transfer(
        api,
        holding,
        benefit["id"],
        gaining["id"],
        consent_ref="CONSENT-51",
    )
    assert opened["status"] == "REQUESTED"

    self_acceptance = api.accept_service_transfer(
        opened["id"],
        f.transfer_accept_payload(acceptance_note="taking over"),
        fx.provider_headers(holding),
    )
    validate_error(self_acceptance, ApiErrorId.UNAUTHORIZED.value, 403)
    assert fx.refresh_transfer(api, opened["id"])["status"] == "REQUESTED", (
        "the losing carrier cannot decide the port it opened"
    )

    completed = fx.accept_transfer(api, opened["id"], gaining)
    assert completed["status"] == "ACCEPTED_COMPLETED"
    assert_instant(completed["completed_at"], AFTER_FREEZE, "completed_at")

    ported = fx.refresh_enrollment(api, benefit["id"])
    assert ported["provider_id"] == gaining["id"]
    assert ported["transfer_count"] == 1
    assert_date_component(ported["benefit_start_date"], "2026-08-01", "benefit_start_date")
    assert_instant(ported["port_freeze_until"], PORT_FREEZE_UNTIL, "port_freeze_until")
    assert_date_component(ported["recert_due_date"], "2027-08-01", "recert_due_date")
    assert ported["device_status"] == "RECLAIM_PENDING"
    assert ported["usage_status"] == "PENDING_FIRST_USE"
    assert_instant_null(ported["last_usage_at"], "last_usage_at")
    assert ported["audit_risk_score"] == expected_risk_score(
        device_issuance_count=1, transfer_count=1
    )
    assert ported["audit_risk_score"] == 25, (
        f"ten for the issuance and fifteen for the port, got {ported['audit_risk_score']}"
    )
    assert fx.refresh_device(api, handset["id"])["status"] == "RECLAIM_PENDING", (
        "the port reclaims the losing carrier's handset in the same call"
    )

    loser = fx.refresh_provider(api, holding["id"])
    assert loser["active_enrollment_count"] == 0
    assert loser["devices_issued_count"] == 0
    assert loser["devices_reclaim_pending_count"] == 1
    winner = fx.refresh_provider(api, gaining["id"])
    assert winner["active_enrollment_count"] == 1
    assert winner["devices_total_count"] == 0, (
        "the handset stays in the losing carrier's warehouse ledger"
    )


def test_the_drawer_may_not_adjudicate_and_the_de_enroller_may_not_decide(api):
    """Both separations are keyed on X-User-ID inside an authorised role, so role cannot
    explain either refusal.

    PRD: "Two separations of duty are enforced, both keyed on `X-User-ID`, and both report
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_bars_the_drawer_and_the_de_enroller
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    residents = []
    benefits = []
    for index in (1, 2):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        residents.append(applicant["subscriber"])
        benefits.append(
            fx.enroll(
                api,
                provider,
                applicant["subscriber"],
                applicant["check"],
                address,
                service_type="VOICE",
                benefit_start_date=JUNE_START,
            )
        )

    fx.set_clock(api, JULY_FILING)
    claim = fx.file_claim(api, fx.draft_claim(api, provider, "2026-06")["id"], provider)
    assert claim["final_amount_cents"] == 1850
    sample = fx.draw_samples(api, claim["id"], sample_size=1)[0]
    assert sample["drawn_by_ref"] == AUDITOR_DRAWER_ID

    fx.set_clock(api, DE_ENROLL_INSTANT)
    stopped = fx.de_enroll(
        api, benefits[1]["id"], reason="SUBSCRIBER_REQUEST", headers=PROGRAM_ADMIN
    )
    assert stopped["de_enrolled_by_ref"] == PROGRAM_ADMIN_ID
    appeal = validate_success(
        api.create_subscriber_case(
            f.subscriber_case_payload(
                residents[1]["id"],
                benefits[1]["id"],
                case_type="DE_ENROLLMENT_APPEAL",
                narrative="The closure was recorded against my wishes",
            ),
            fx.subscriber_headers(residents[1]),
        ),
        201,
    )
    assigned = validate_success(
        api.assign_case_review(
            appeal["id"], f.assign_review_payload(reviewer_ref="REV-1"), PROGRAM_ADMIN_ALT
        )
    )
    assert assigned["status"] == "UNDER_REVIEW"
    assert assigned["review_round"] == 1

    self_review = api.adjudicate_audit_sample(
        sample["id"],
        f.adjudicate_payload(finding="COMPLIANT", finding_note="self review"),
        AUDITOR_DRAWER,
    )
    validate_error(self_review, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    untouched_sample = fx.refresh_sample(api, sample["id"])
    assert untouched_sample["status"] == "DRAWN"
    assert untouched_sample["finding"] is None
    assert untouched_sample["adjudicated_by_ref"] is None
    assert fx.refresh_claim(api, claim["id"])["status"] == "UNDER_AUDIT", (
        "the refused adjudication did not bubble anything up"
    )

    independent = validate_success(
        api.adjudicate_audit_sample(
            sample["id"],
            f.adjudicate_payload(finding="COMPLIANT", finding_note="independent review"),
            AUDITOR_ADJUDICATOR,
        )
    )
    assert independent["status"] == "ADJUDICATED_PASS", (
        "the identical finding from a second auditor is admitted"
    )
    assert independent["adjudicated_by_ref"] == AUDITOR_ADJUDICATOR_ID
    passed = fx.refresh_claim(api, claim["id"])
    assert passed["status"] == "AUDIT_PASSED"
    assert passed["net_payable_cents"] == 1850

    self_decision = api.decide_case(
        appeal["id"],
        f.decide_case_payload(
            decision="DENY", decision_rationale="deciding my own closure"
        ),
        PROGRAM_ADMIN,
    )
    validate_error(self_decision, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    untouched_case = fx.refresh_case(api, appeal["id"])
    assert untouched_case["status"] == "UNDER_REVIEW"
    assert untouched_case["decision"] is None
    assert untouched_case["decided_by_ref"] is None

    decided = validate_success(
        api.decide_case(
            appeal["id"],
            f.decide_case_payload(
                decision="DENY",
                decision_rationale="closure was properly requested by the subscriber",
            ),
            THIRD_ADMIN,
        )
    )
    assert decided["status"] == "DENIED"
    assert decided["decided_by_ref"] == THIRD_ADMIN_ID, (
        f"a third administrator carries no conflict, got {decided['decided_by_ref']}"
    )
    assert decided["reinstated_enrollment_flag"] is False

    stranded = fx.refresh_enrollment(api, benefits[1]["id"])
    assert stranded["benefit_status"] == "DE_ENROLLED", "the DENY arm leaves the benefit stopped"
    assert stranded["de_enrolled_by_ref"] == PROGRAM_ADMIN_ID

    assert_ledger_tuple(fx.refresh_provider(api, provider["id"]), 1850, 0, 1850, False)
