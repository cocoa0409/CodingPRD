"""Encounter admission rules: dates, windows, scope, billability and payment ceilings."""

from test_helpers import (
    BILLER,
    OFFICER,
    REP,
    ApiErrorId,
    advance_clock,
    api_client,
    bill_encounter,
    create_encounter_payload,
    create_waiver_payload,
    record_payment_payload,
    refresh_encounter,
    refresh_patient,
    same_instant,
    seed_poverty_guidelines,
    setup_baseline_service,
    setup_baseline_site,
    setup_boot_core,
    setup_boot_pt,
    setup_encounter,
    setup_grantee,
    setup_patient,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_2026_GUIDELINE = ((2026, 1620000, 570000),)


def _encounter_body(ctx, **overrides):
    body = create_encounter_payload(
        ctx["patient_id"],
        ctx["site_id"],
        ctx["service_id"],
    )
    body.update(overrides)
    return body


def _encounter_count():
    _, meta = validate_paginated(api_client.list_encounters(BILLER))
    return meta["total_count"]


def test_a_date_of_service_after_the_clock_is_refused():
    """The future-date rule is checked even when every window covers the date.

    PRD 2.12: "23. `encounter_date` is not after the logical clock, on encounter
    creation — otherwise `ERR_ENCOUNTER_DATE_IN_FUTURE` (422)."

    Design: Corner/validations/encounter_date_after_the_logical_clock_rejected
    """
    ctx = setup_boot_pt()

    validate_error(
        api_client.create_encounter(
            _encounter_body(
                ctx,
                encounter_date="2026-09-01T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=8000,
            ),
            BILLER,
        ),
        ApiErrorId.ERR_ENCOUNTER_DATE_IN_FUTURE.value,
        422,
    )

    assert _encounter_count() == 0
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 0


def test_a_date_of_service_exactly_at_the_clock_is_accepted_and_priced():
    """A date of service equal to the clock is not after it, so it is admitted.

    PRD 2.12: "23. `encounter_date` is not after the logical clock, on encounter
    creation — otherwise `ERR_ENCOUNTER_DATE_IN_FUTURE` (422)."

    Design: Corner/validations/encounter_dated_exactly_at_the_logical_clock_is_accepted
    """
    ctx = setup_boot_pt()
    advance_clock("2026-06-01T00:00:00Z")

    response = api_client.create_encounter(
        _encounter_body(
            ctx,
            encounter_date="2026-06-01T00:00:00Z",
            payer_type="SELF_PAY",
            gross_charge_cents=8000,
        ),
        BILLER,
    )
    encounter = validate_success(response, 201)

    assert same_instant(encounter["encounter_date"]) == "2026-06-01T00:00:00Z"
    assert encounter["charge_basis"] == "SLIDING_FEE_TIER"
    assert encounter["patient_charge_cents"] == 2500, (
        "the encounter is priced through the sliding fee rather than refused, got "
        f"{encounter['patient_charge_cents']}"
    )
    assert encounter["income_verification_id"] == ctx["income_verification_id"]
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500


def test_a_verification_pinned_outside_its_window_is_refused_not_ignored():
    """An explicit pin is validated rather than silently replaced by the fallback.

    PRD 3.5: "When the client does supply `income_verification_id` explicitly, the named
    verification must have `status` equal to `VERIFIED` and its closed window must
    contain the `encounter_date`, or the request is rejected with
    `ERR_VERIFICATION_DOES_NOT_COVER_ENCOUNTER`."

    Design: Corner/validations/explicit_income_verification_outside_its_window_rejected
    """
    ctx = setup_boot_pt()

    validate_error(
        api_client.create_encounter(
            _encounter_body(
                ctx,
                encounter_date="2026-02-01T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=8000,
                income_verification_id=ctx["income_verification_id"],
            ),
            BILLER,
        ),
        ApiErrorId.ERR_VERIFICATION_DOES_NOT_COVER_ENCOUNTER.value,
        422,
    )

    assert _encounter_count() == 0, (
        "the encounter did not fall back to the unverified branch"
    )


def test_an_in_scope_administrative_site_still_carries_no_encounter():
    """Billability is a separate question from scope membership.

    PRD 3.1: "The `site_type` is one of `SERVICE_DELIVERY`, `INTERMITTENT` or
    `ADMINISTRATIVE`; the last of these is an important distinction, because an
    `ADMINISTRATIVE` site may never carry an encounter and an `INTERMITTENT` site
    attracts a reduced encounter rate."

    PRD 2.12: "34. The encounter's site is not administrative, on encounter creation —
    otherwise `ERR_ADMINISTRATIVE_SITE_NOT_BILLABLE` (422)."

    Design: Corner/validations/encounter_on_an_administrative_site_rejected
    """
    ctx = setup_boot_pt()
    administrative = setup_baseline_site(
        ctx["health_center_id"],
        site_name="Corner Admin Annex",
        site_type="ADMINISTRATIVE",
        address_line="3 Corner Ave",
        weekly_service_hours=0,
    )
    assert administrative["status"] == "IN_SCOPE"

    validate_error(
        api_client.create_encounter(
            _encounter_body(
                ctx,
                service_site_id=administrative["id"],
                encounter_date="2026-05-01T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=8000,
            ),
            BILLER,
        ),
        ApiErrorId.ERR_ADMINISTRATIVE_SITE_NOT_BILLABLE.value,
        422,
    )

    assert _encounter_count() == 0


def test_a_service_still_awaiting_admission_cannot_carry_an_encounter():
    """A pending service is refused with its own error, not the site's.

    PRD 2.12: "35. The encounter's service is `IN_SCOPE`, on encounter creation —
    otherwise `ERR_SERVICE_NOT_IN_SCOPE` (409)."

    Design: Corner/validations/encounter_against_a_pending_service_definition_rejected
    """
    ctx = setup_boot_pt()
    pending = setup_baseline_service(
        ctx["health_center_id"],
        service_code="DENTAL_ADDL",
        service_category="ADDITIONAL",
        delivery_method="COLUMN_II_CONTRACT",
        in_initial_scope=False,
    )
    assert pending["status"] == "PENDING"

    validate_error(
        api_client.create_encounter(
            _encounter_body(
                ctx,
                service_definition_id=pending["id"],
                encounter_date="2026-05-01T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=8000,
            ),
            BILLER,
        ),
        ApiErrorId.ERR_SERVICE_NOT_IN_SCOPE.value,
        409,
    )

    assert _encounter_count() == 0


def test_an_encounter_cannot_be_priced_when_no_schedule_has_been_adopted():
    """The selector's empty candidate set is an error, not an unverified fallback.

    PRD 3.5: "If the candidate set is empty, the encounter cannot be priced and the
    request is rejected with `ERR_NO_EFFECTIVE_FEE_SCHEDULE`."

    Design: Corner/validations/encounter_without_any_adopted_fee_schedule_rejected
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    grantee = setup_grantee(
        legal_name="Corner Community Health",
        grant_number="H80CS00500",
        pps_base_rate_cents=20000,
    )
    site = setup_baseline_site(grantee["id"], site_name="Corner Clinic")
    service = setup_baseline_service(grantee["id"])
    patient = setup_patient(mrn="MRN-C01", full_name="Val Osei", household_size=1)

    validate_error(
        api_client.create_encounter(
            create_encounter_payload(
                patient["id"],
                site["id"],
                service["id"],
                encounter_date="2026-05-01T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=8000,
            ),
            BILLER,
        ),
        ApiErrorId.ERR_NO_EFFECTIVE_FEE_SCHEDULE.value,
        409,
    )

    _, meta = validate_paginated(
        api_client.list_fee_schedules(
            OFFICER, {"health_center_id": grantee["id"], "status": "ADOPTED"}
        )
    )
    assert meta["total_count"] == 0
    assert _encounter_count() == 0


def test_a_remittance_above_the_allowable_rate_is_refused_and_posts_nothing():
    """The ceiling is the encounter's own pinned rate.

    PRD 3.7: "Posting the payer's payment supplies `mco_paid_cents`, the managed-care
    organisation payment, which must be zero or greater and must not exceed the
    encounter's `pps_encounter_rate_cents`; a payment above the allowable rate is
    rejected with `ERR_PAYMENT_EXCEEDS_PPS_RATE`."

    Design: Corner/validations/mco_payment_above_the_pps_encounter_rate_rejected
    """
    ctx = setup_boot_pt()
    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-15T00:00:00Z",
        payer_type="MEDICAID_MCO",
        gross_charge_cents=8000,
    )
    billed = bill_encounter(encounter, "CLM-M1")
    assert billed["pps_encounter_rate_cents"] == 20000, (
        "the base rate carries no site or service multiplier here, got "
        f"{billed['pps_encounter_rate_cents']}"
    )

    validate_error(
        api_client.record_encounter_payment(
            encounter["id"], record_payment_payload(20001), BILLER
        ),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_PPS_RATE.value,
        422,
    )

    after = refresh_encounter(encounter["id"])
    assert after["pps_claim_status"] == "BILLED", (
        "the refused remittance left the claim where billing put it"
    )
    assert after["mco_paid_cents"] == billed["mco_paid_cents"], (
        "no payment amount was stored"
    )
    assert after["wraparound_status"] == billed["wraparound_status"], (
        "the wraparound computation never ran"
    )
    assert after["wraparound_due_cents"] == billed["wraparound_due_cents"]


def test_a_full_charge_balance_is_not_protected_by_the_inability_to_pay_policy():
    """The policy protects the nominal fee only, so an undiscounted charge is refused.

    PRD 3.6: "Accordingly, a `PatientServicesRep` may request an **inability-to-pay
    waiver** against an encounter only when that encounter's `charge_basis` is
    `SLIDING_FEE_TIER` *and* its `patient_charge_cents` is exactly equal to the
    `nominal_fee_cents` of the fee schedule it pinned. Any other encounter is rejected
    with `ERR_WAIVER_NOT_ELIGIBLE`."

    Design: Corner/validations/waiver_request_on_a_full_charge_unverified_encounter_rejected
    """
    ctx = setup_boot_core()
    undocumented = setup_patient(mrn="MRN-C03", full_name="Rue Marsh", household_size=1)
    encounter = setup_encounter(
        ctx,
        undocumented["id"],
        encounter_date="2026-05-01T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=8000,
    )
    assert encounter["charge_basis"] == "FULL_CHARGE_UNVERIFIED"
    assert encounter["patient_charge_cents"] == 8000, (
        "an undocumented self-pay patient owes the full gross charge"
    )

    validate_error(
        api_client.create_waiver(
            encounter["id"], create_waiver_payload("NO_INCOME"), REP
        ),
        ApiErrorId.ERR_WAIVER_NOT_ELIGIBLE.value,
        422,
    )

    _, meta = validate_paginated(
        api_client.list_encounter_waivers(encounter["id"], REP)
    )
    assert meta["total_count"] == 0, "no waiver row was created"
    assert refresh_encounter(encounter["id"])["waived_amount_cents"] == 0
    assert refresh_patient(undocumented["id"])["patient_balance_cents"] == 8000
