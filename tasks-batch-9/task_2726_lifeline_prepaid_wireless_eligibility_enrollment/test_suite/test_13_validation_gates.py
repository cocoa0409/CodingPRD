"""Validation gates: hard certifications, satisfaction arms, and the priority ladders between them."""

from test_helpers import (
    AUDITOR_DRAWER,
    EMPTY_AUTH_HEADERS,
    NATIONAL_VERIFIER,
    PROGRAM_ADMIN,
    ApiErrorId,
    assert_date_component,
    assert_device,
    assert_device_counters,
    assert_eligibility_check,
    assert_enrollment,
    assert_instant,
    assert_instant_null,
    assert_ledger_tuple,
    expected_recoupment,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
JUNE_START = "2026-06-01T00:00:00Z"
JULY_FILING = "2026-07-02T00:00:00Z"
AUGUST_FILING = "2026-08-01T00:00:00Z"


def _ready_to_enroll(api):
    """A carrier, a clean dwelling and a VERIFIED_ELIGIBLE applicant on a confirmed check."""
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "address": address,
        "subscriber": applicant["subscriber"],
        "check": applicant["check"],
    }


def _enrollment_body(context, **overrides):
    return f.enrollment_payload(
        subscriber_id=context["subscriber"]["id"],
        provider_id=context["provider"]["id"],
        eligibility_check_id=context["check"]["id"],
        certified_address_id=context["address"]["id"],
        **overrides,
    )


def test_the_household_certification_is_a_gate_not_a_stored_flag(api):
    """A false attestation writes nothing, and the identical request with true then succeeds.

    PRD: "Then `one_per_household_attested` must be present and true, otherwise
    `ERR_HOUSEHOLD_CERTIFICATION_MISSING` (HTTP 422); this is the subscriber's own attestation
    and is a separate rule from the system-side occupancy test."

    Design: Corner/validations/enrollment_without_one_per_household_certification_is_rejected
    """
    context = _ready_to_enroll(api)

    refused = api.create_enrollment(
        _enrollment_body(context, service_type="VOICE", one_per_household_attested=False),
        context["agent"],
    )
    validate_error(refused, ApiErrorId.HOUSEHOLD_CERTIFICATION_MISSING.value, 422)

    _rows, meta = validate_paginated(
        api.list_enrollments(PROGRAM_ADMIN, {"certified_address_id": context["address"]["id"]})
    )
    assert meta["total_count"] == 0, "the refused request created no benefit"
    assert fx.refresh_subscriber(api, context["subscriber"]["id"])["status"] == "VERIFIED_ELIGIBLE", (
        "the applicant is left exactly where the screening left it"
    )
    assert fx.refresh_address(api, context["address"]["id"])["occupied_benefit_slots"] == 0

    accepted = validate_success(
        api.create_enrollment(
            _enrollment_body(context, service_type="VOICE", one_per_household_attested=True),
            context["agent"],
        ),
        201,
    )
    assert_enrollment(accepted)
    assert accepted["benefit_status"] == "ACTIVE"
    assert accepted["one_per_household_attested"] is True
    assert fx.refresh_address(api, context["address"]["id"])["occupied_benefit_slots"] == 1


def test_only_a_program_the_household_can_actually_claim_passes_the_basis_gate(api):
    """NONE fails, a Tribal-only program off Tribal lands fails, and SNAP passes at any income.

    PRD: "A benefit-claimed check is refused with `ERR_NO_QUALIFYING_BASIS` in two situations:
    when the applicant's `qualifying_benefit` is `NONE`, and when the claimed program is one of
    the two Tribal-only programs — `TRIBAL_TANF` or `BIA_GENERAL_ASSISTANCE` — while the
    applicant's `tribal_lands_flag` is false."

    Design: Corner/validations/benefit_basis_check_passes_only_with_a_non_tribal_qualifying_program
    """
    fx.set_clock(api, CLOCK)
    fx.register_provider(api)

    no_program = fx.create_subscriber(
        api, fx.register_distinct_address(api, 1)["id"], qualifying_benefit="NONE"
    )
    tribal_only = fx.create_subscriber(
        api,
        fx.register_distinct_address(api, 2)["id"],
        qualifying_benefit="TRIBAL_TANF",
        tribal_lands_flag=False,
    )
    on_snap = fx.create_subscriber(
        api,
        fx.register_distinct_address(api, 3)["id"],
        qualifying_benefit="SNAP",
        annual_income_cents=9000000,
    )

    first = api.create_eligibility_check(
        no_program["id"],
        f.eligibility_check_payload(claimed_basis="BENEFIT", proof_document_ref="DOC-Q2"),
        PROGRAM_ADMIN,
    )
    validate_error(first, ApiErrorId.NO_QUALIFYING_BASIS.value, 409)
    assert fx.refresh_subscriber(api, no_program["id"])["status"] == "PROSPECT"

    second = api.create_eligibility_check(
        tribal_only["id"],
        f.eligibility_check_payload(claimed_basis="BENEFIT", proof_document_ref="DOC-Q3"),
        PROGRAM_ADMIN,
    )
    validate_error(second, ApiErrorId.NO_QUALIFYING_BASIS.value, 409)
    assert fx.refresh_subscriber(api, tribal_only["id"])["status"] == "PROSPECT", (
        "a Tribal-only program claimed off Tribal lands is no basis at all"
    )

    assert on_snap["income_threshold_cents"] == 4341600
    assert on_snap["annual_income_cents"] == 9000000, (
        "the SNAP applicant is far above its own income bar on purpose"
    )

    accepted = validate_success(
        api.create_eligibility_check(
            on_snap["id"],
            f.eligibility_check_payload(claimed_basis="BENEFIT", proof_document_ref="DOC-Q4"),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_eligibility_check(accepted)
    assert accepted["status"] == "PENDING_VERIFIER"
    assert accepted["claimed_basis"] == "BENEFIT"
    assert accepted["income_variant"] == "NOT_APPLICABLE", (
        "the income rule stays silent on a benefit-claimed check, got "
        f"{accepted['income_variant']}"
    )
    assert fx.refresh_subscriber(api, on_snap["id"])["status"] == "ELIGIBILITY_PENDING"


def test_one_malformed_body_reveals_the_schema_failure_only_to_the_authorised_caller(api):
    """The same service_type-less body climbs 401, then 403, then finally 422.

    PRD: "The role is one of the five declared roles and is permitted on this operation —
    otherwise `ERR_UNAUTHORIZED`."

    Design: Corner/validations/auth_ladder_unauthenticated_then_unauthorized_outrank_the_schema_check
    """
    context = _ready_to_enroll(api)
    body = _enrollment_body(context, one_per_household_attested=True)
    body.pop("service_type")

    unauthenticated = api.create_enrollment(body, EMPTY_AUTH_HEADERS)
    validate_error(unauthenticated, ApiErrorId.UNAUTHENTICATED.value, 401)

    wrong_role = api.create_enrollment(body, NATIONAL_VERIFIER)
    validate_error(wrong_role, ApiErrorId.UNAUTHORIZED.value, 403)

    schema = api.create_enrollment(body, context["agent"])
    validate_error(schema, ApiErrorId.INVALID_REQUEST.value, 422)

    _rows, meta = validate_paginated(
        api.list_enrollments(PROGRAM_ADMIN, {"subscriber_id": context["subscriber"]["id"]})
    )
    assert meta["total_count"] == 0, "none of the three refusals wrote a benefit"
    assert fx.refresh_subscriber(api, context["subscriber"]["id"])["status"] == "VERIFIED_ELIGIBLE"
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 0


def _carrier_on_audit_hold_with_a_draft_for_the_open_month(api):
    """June filed at 1850 and then failed on audit, while a July draft sits at 120."""
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api)
    for index in (1, 2):
        address = fx.register_distinct_address(api, index)
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
    june = fx.file_claim(
        api,
        fx.draft_claim(api, provider, "2026-06")["id"],
        provider,
        certifying_officer_ref="OFFICER-17",
    )
    assert june["final_amount_cents"] == 1850, (
        f"two full-month voice lines, got {june['final_amount_cents']}"
    )

    july = fx.draft_claim(api, provider, "2026-07")
    assert july["provisional_amount_cents"] == 120, (
        "each benefit earns 2026-07-01 and 2026-07-02 of July's 31 days, so 60 per line, got "
        f"{july['provisional_amount_cents']}"
    )

    samples = fx.draw_samples(api, june["id"], sample_size=2)
    fx.adjudicate(
        api,
        samples[0]["id"],
        finding="NON_USAGE_UNCURED",
        finding_note="no usage evidence for the sampled month",
    )
    return {
        "provider": provider,
        "june": june,
        "july": july,
        "spare_sample": samples[1],
    }


def test_the_open_month_shadows_the_audit_hold_until_the_clock_moves_on(api):
    """One request, two live violations: the temporal gate answers first, the fiscal gate second.

    PRD: "The month must be closed: while today's date is on or before the last calendar day
    of `service_month` the request is refused with `ERR_SERVICE_MONTH_NOT_CLOSED`, which forces
    the switch from provisional to final pricing to happen only once the month is complete."

    Design: Corner/validations/service_month_temporal_gate_outranks_the_audit_hold_fiscal_gate
    """
    context = _carrier_on_audit_hold_with_a_draft_for_the_open_month(api)
    july_id = context["july"]["id"]
    agent = fx.provider_headers(context["provider"])

    assert fx.refresh_provider(api, context["provider"]["id"])["audit_hold_flag"] is True, (
        "the hold is already standing when the first filing is attempted"
    )

    while_open = api.file_claim(july_id, f.claim_file_payload("OFFICER-18"), agent)
    validate_error(while_open, ApiErrorId.SERVICE_MONTH_NOT_CLOSED.value, 409)
    assert fx.refresh_claim(api, july_id)["status"] == "DRAFT"

    fx.set_clock(api, AUGUST_FILING)
    once_closed = api.file_claim(july_id, f.claim_file_payload("OFFICER-18"), agent)
    validate_error(once_closed, ApiErrorId.PROVIDER_AUDIT_HOLD.value, 409)

    unfiled = fx.refresh_claim(api, july_id)
    assert unfiled["status"] == "DRAFT", (
        f"neither refusal moved the draft, got {unfiled['status']}"
    )
    assert unfiled["final_amount_cents"] == 0, (
        "a draft's final figure initialises to zero and is only written at file time"
    )
    assert_instant_null(unfiled["filed_at"], "filed_at")

    failed = fx.refresh_claim(api, context["june"]["id"])
    assert failed["status"] == "AUDIT_FAILED"
    assert failed["penalty_cents"] == 93, (
        f"ten percent of 925 is 92.5, which rounds half up, got {failed['penalty_cents']}"
    )
    assert failed["recoupment_amount_cents"] == 1018
    assert failed["net_payable_cents"] == 832
    assert expected_recoupment(1850, 1, 2)["recoupment_amount_cents"] == 1018

    assert fx.refresh_sample(api, context["spare_sample"]["id"])["status"] == "DRAWN"

    carrier = fx.refresh_provider(api, context["provider"]["id"])
    assert_ledger_tuple(carrier, 1850, 1018, 832, True)
    assert carrier["open_claim_count"] == 1, (
        f"only the July draft is still open, got {carrier['open_claim_count']}"
    )


def test_the_check_is_examined_before_the_applicant_it_belongs_to(api):
    """An unconfirmed check answers first; a confirmed one exposes the held applicant beneath it.

    PRD: "The applicant must be `VERIFIED_ELIGIBLE`, otherwise `ERR_SUBSCRIBER_NOT_ELIGIBLE`,
    which is what a `PROSPECT`, `ELIGIBILITY_PENDING`, `DUPLICATE_HOLD`, already-`ENROLLED` or
    `DE_ENROLLED` applicant receives."

    Design: Corner/validations/enrollment_gate_reads_check_state_before_subscriber_state
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    agent = fx.provider_headers(provider)

    cohort = fx.duplicate_cohort(api, count=2)
    contested = cohort[0]
    assert fx.refresh_address(api, contested["id"])["status"] == "DUPLICATE_FLAGGED"
    clean = fx.register_distinct_address(api, 9)

    held = fx.create_subscriber(api, contested["id"])
    assert held["status"] == "DUPLICATE_HOLD", (
        f"an applicant at a flagged dwelling is born held, got {held['status']}"
    )
    held_check = fx.confirm_eligibility_check(
        api, fx.open_eligibility_check(api, held["id"], proof_document_ref="DOC-R1")["id"]
    )
    assert held_check["status"] == "ELIGIBLE_CONFIRMED"
    assert fx.refresh_subscriber(api, held["id"])["status"] == "DUPLICATE_HOLD", (
        "a verifier MATCH cannot release an applicant the cohort is holding"
    )

    parked = fx.create_subscriber(api, clean["id"])
    parked_check = fx.open_eligibility_check(api, parked["id"], proof_document_ref="DOC-R2")
    assert parked_check["status"] == "PENDING_VERIFIER"

    on_check = api.create_enrollment(
        f.enrollment_payload(
            subscriber_id=parked["id"],
            provider_id=provider["id"],
            eligibility_check_id=parked_check["id"],
            certified_address_id=clean["id"],
            service_type="VOICE",
        ),
        agent,
    )
    validate_error(on_check, ApiErrorId.ELIGIBILITY_CHECK_NOT_CONFIRMED.value, 409)
    assert fx.refresh_eligibility_check(api, parked_check["id"])["status"] == "PENDING_VERIFIER"

    held_body = f.enrollment_payload(
        subscriber_id=held["id"],
        provider_id=provider["id"],
        eligibility_check_id=held_check["id"],
        certified_address_id=contested["id"],
        service_type="VOICE",
    )
    on_applicant = api.create_enrollment(held_body, agent)
    validate_error(on_applicant, ApiErrorId.SUBSCRIBER_NOT_ELIGIBLE.value, 409)

    resolved = fx.resolve_multi_household(
        api, contested["id"], declared_household_count=2, worksheet_ref="WS-11"
    )
    assert resolved["status"] == "RESOLVED_MULTI_HOUSEHOLD"
    assert fx.refresh_subscriber(api, held["id"])["status"] == "VERIFIED_ELIGIBLE", (
        "the resolution releases every applicant the cohort was holding"
    )
    assert fx.refresh_eligibility_check(api, held_check["id"])["status"] == "ELIGIBLE_CONFIRMED", (
        "nothing about the check changed between the refusal and the acceptance"
    )

    admitted = validate_success(api.create_enrollment(held_body, agent), 201)
    assert admitted["benefit_status"] == "ACTIVE"
    assert admitted["eligibility_check_id"] == held_check["id"]

    dwelling = fx.refresh_address(api, contested["id"])
    assert dwelling["max_permitted_benefit_slots"] == 2, (
        f"the declared household count becomes the slot ceiling, got {dwelling['max_permitted_benefit_slots']}"
    )
    assert dwelling["occupied_benefit_slots"] == 1


NOTICE_SWEEP = "2027-06-02T00:00:00Z"
RESPONSE_DEADLINE = "2027-08-01T23:59:59.999Z"
ONE_MS_PAST_DEADLINE = "2027-08-02T00:00:00.000Z"


def test_the_answer_lands_at_the_deadline_instant_and_is_closed_one_millisecond_later(api):
    """Two benefits noticed by one sweep: one answers at the deadline, the other one millisecond late.

    PRD: "And the response must be inside the window: an instant strictly past
    `recert_response_deadline_at` is refused with `ERR_RECERT_WINDOW_CLOSED`, while an instant
    exactly equal to it is accepted."

    Design: Corner/validations/recert_response_accepted_at_the_deadline_instant_and_closed_one_ms_later
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    agent = fx.provider_headers(provider)
    benefits = []
    holders = []
    for index in (1, 2):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        benefits.append(
            fx.enroll(
                api,
                provider,
                applicant["subscriber"],
                applicant["check"],
                address,
                service_type="VOICE",
                benefit_start_date=CLOCK,
            )
        )
        holders.append(fx.subscriber_headers(applicant["subscriber"]))
        assert_date_component(benefits[-1]["recert_due_date"], "2027-08-01", "recert_due_date")

    fx.set_clock(api, "2027-06-01T00:00:00Z")
    for benefit in benefits:
        fx.record_usage(api, benefit["id"], headers=agent)

    fx.set_clock(api, NOTICE_SWEEP)
    swept = fx.sweep(api, provider["id"])
    assert_instant(swept["swept_at"], NOTICE_SWEEP, "swept_at")
    assert swept["evaluated_enrollment_count"] == 2
    assert swept["non_usage_flagged_enrollment_ids"] == [], (
        "yesterday's activity keeps the idle count at one day"
    )
    assert swept["recert_noticed_enrollment_ids"] == [benefits[0]["id"], benefits[1]["id"]], (
        "the notice window opens exactly 60 days before the anniversary, for both benefits in visit order"
    )
    for benefit in benefits:
        noticed = fx.refresh_enrollment(api, benefit["id"])
        assert noticed["recert_status"] == "NOTICED"
        assert_instant(
            noticed["recert_response_deadline_at"], RESPONSE_DEADLINE, "recert_response_deadline_at"
        )

    fx.set_clock(api, RESPONSE_DEADLINE)
    answered = validate_success(
        api.recertify(
            benefits[0]["id"],
            f.recertify_payload(
                household_size=4,
                annual_income_cents=3000000,
                last_3mo_income_cents=750000,
                attested_qualifying_benefit="NONE",
                attestation_ref="ATT-11",
            ),
            holders[0],
        )
    )
    assert answered["recert_status"] == "NOT_DUE", (
        f"the eligible arm closes the annual cycle, got {answered['recert_status']}"
    )
    assert answered["recert_evaluated_income_cents"] == 3000000
    assert_date_component(answered["recert_due_date"], "2028-07-31", "recert_due_date")
    assert_instant_null(answered["recert_notice_sent_at"], "recert_notice_sent_at")
    assert_instant_null(answered["recert_response_deadline_at"], "recert_response_deadline_at")
    assert_instant(
        answered["recert_last_responded_at"], RESPONSE_DEADLINE, "recert_last_responded_at"
    )
    assert answered["benefit_status"] == "ACTIVE"

    fx.set_clock(api, ONE_MS_PAST_DEADLINE)
    too_late = api.recertify(
        benefits[1]["id"],
        f.recertify_payload(
            household_size=4,
            annual_income_cents=3000000,
            last_3mo_income_cents=750000,
            attested_qualifying_benefit="NONE",
            attestation_ref="ATT-12",
        ),
        holders[1],
    )
    validate_error(too_late, ApiErrorId.RECERT_WINDOW_CLOSED.value, 409)

    stranded = fx.refresh_enrollment(api, benefits[1]["id"])
    assert stranded["recert_status"] == "NOTICED", (
        f"the refused answer leaves the notice outstanding, got {stranded['recert_status']}"
    )
    assert_instant_null(stranded["recert_last_responded_at"], "recert_last_responded_at")
    assert stranded["benefit_status"] == "ACTIVE"


def test_the_outstanding_handset_blocks_the_successor_benefit_until_it_comes_back(api):
    """A RECLAIM_PENDING handset from a closed benefit refuses issuance on the applicant's new one.

    PRD: "If any handset whose `issued_enrollment_id` points at *any* benefit of the same
    applicant currently has `status` of `ISSUED` or `RECLAIM_PENDING`, the request is refused
    with `ERR_SINGLE_DEVICE_PER_SUBSCRIBER`."

    Design: Corner/validations/single_device_rule_fires_only_while_a_prior_handset_is_outstanding
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    agent = fx.provider_headers(provider)
    outstanding, spare = fx.stock_devices(api, provider, [("BASIC", 2100), ("BASIC", 2200)])

    dwelling = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, dwelling["id"])
    first = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        dwelling,
        service_type="VOICE",
        benefit_start_date=CLOCK,
    )
    fx.issue_device(api, first["id"], provider, device_id=outstanding["id"])

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.de_enroll(api, first["id"], reason="SUBSCRIBER_REQUEST", headers=agent)
    assert fx.refresh_device(api, outstanding["id"])["status"] == "RECLAIM_PENDING", (
        "stopping the benefit reclaims the handset without taking it back"
    )

    fx.set_clock(api, "2026-09-02T00:00:00Z")
    second_check = fx.confirm_eligibility_check(
        api,
        fx.open_eligibility_check(
            api, applicant["subscriber"]["id"], proof_document_ref="DOC-S2"
        )["id"],
    )
    second = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        second_check,
        dwelling,
        service_type="VOICE",
        benefit_start_date="2026-09-02T00:00:00Z",
    )
    assert_instant_null(second["last_device_issued_at"], "last_device_issued_at")
    assert second["device_status"] == "AWAITING_DEVICE", (
        "neither the freeze nor the custody rule can be what refuses the issuance"
    )

    refused = api.issue_device(
        second["id"], f.device_issuance_payload(device_id=spare["id"]), agent
    )
    validate_error(refused, ApiErrorId.SINGLE_DEVICE_PER_SUBSCRIBER.value, 409)
    assert fx.refresh_device(api, spare["id"])["status"] == "IN_STOCK"
    assert fx.refresh_enrollment(api, second["id"])["device_issuance_count"] == 0

    returned = fx.return_device(api, outstanding["id"], return_condition="GOOD")
    assert returned["status"] == "IN_STOCK"
    assert returned["return_condition"] == "GOOD"
    assert_instant(returned["returned_at"], "2026-09-02T00:00:00Z", "returned_at")
    assert fx.refresh_enrollment(api, first["id"])["device_status"] == "AWAITING_DEVICE"

    issued = validate_success(
        api.issue_device(
            second["id"], f.device_issuance_payload(device_id=spare["id"]), agent
        )
    )
    assert_device(issued)
    assert issued["status"] == "ISSUED", (
        "returning the outstanding handset is the only change between the two requests"
    )
    assert issued["issued_enrollment_id"] == second["id"]

    settled = fx.refresh_enrollment(api, second["id"])
    assert settled["device_status"] == "DEVICE_ISSUED"
    assert settled["device_issuance_count"] == 1
    assert_device_counters(fx.refresh_provider(api, provider["id"]), 2, 1, 1, 0, 0)


def test_the_lifecycle_gate_shadows_the_sample_size_check_in_both_directions(api):
    """An illegal sample size on a DRAFT answers with the lifecycle code, and only later with its own.

    PRD: "The claim must be `FILED`, or the request is refused with `ERR_CLAIM_NOT_FILED` —
    which is also what a `HELD` claim returns, so a carrier under audit hold cannot have a
    second draw opened, as well as what a `DRAFT`, `UNDER_AUDIT`, `AUDIT_PASSED` or
    `AUDIT_FAILED` claim returns."

    Design: Corner/validations/claim_lifecycle_gate_runs_before_the_sample_size_check
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api)
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
    draft = fx.draft_claim(api, provider, "2026-06")
    assert draft["status"] == "DRAFT"

    shadowed = api.draw_audit_sample(
        draft["id"], f.audit_draw_payload(sample_size=0), AUDITOR_DRAWER
    )
    validate_error(shadowed, ApiErrorId.CLAIM_NOT_FILED.value, 409)
    still_draft = fx.refresh_claim(api, draft["id"])
    assert still_draft["status"] == "DRAFT", (
        "the lifecycle gate answered before the cardinality check was consulted"
    )
    assert still_draft["audit_sample_count"] == 0

    filed = fx.file_claim(api, draft["id"], provider, certifying_officer_ref="OFFICER-19")
    assert filed["status"] == "FILED"

    revealed = api.draw_audit_sample(
        draft["id"], f.audit_draw_payload(sample_size=0), AUDITOR_DRAWER
    )
    validate_error(revealed, ApiErrorId.INVALID_SAMPLE_SIZE.value, 422)
    assert fx.refresh_claim(api, draft["id"])["status"] == "FILED"

    refiled = api.file_claim(draft["id"], f.claim_file_payload("OFFICER-20"), agent)
    validate_error(refiled, ApiErrorId.CLAIM_NOT_DRAFT.value, 409)

    settled = fx.refresh_claim(api, draft["id"])
    assert settled["certifying_officer_ref"] == "OFFICER-19", (
        f"the refused second filing did not overwrite the officer, got {settled['certifying_officer_ref']}"
    )
    assert settled["final_amount_cents"] == 925
    carrier = fx.refresh_provider(api, provider["id"])
    assert carrier["claim_gross_cents"] == 925
    assert carrier["open_claim_count"] == 1
