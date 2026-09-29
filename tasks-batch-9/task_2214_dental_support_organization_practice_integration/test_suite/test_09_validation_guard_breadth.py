"""Validation breadth, part one: the guards whose boundary is inclusive on one
side only, the uniqueness scopes, the identity-based refusals and the two
fiscal ceilings that bite at the moment a commitment becomes real."""

from test_helpers import (
    COUNSEL,
    FINANCE,
    FINANCE_RESERVER_USER_ID,
    FINANCE_SETTLER_USER_ID,
    LEAD,
    SETTLER,
    ApiErrorId,
    api_client,
    assert_doctor_employment,
    assert_earnout_pool_ledger,
    assert_service_agreement,
    build_clinical_director,
    build_closed_deal,
    build_closed_deal_two_doctors,
    build_priced_contract,
    build_approved_enrollment,
    build_reserved_tranche,
    activate_fee_schedule,
    add_service_line_item,
    advance_to_diligence,
    create_affiliation,
    create_clinical_quality_review,
    create_conversion_vendor,
    create_doctor,
    create_doctor_employment_payload,
    create_practice,
    create_service_agreement,
    close_quality_review,
    project_tranche,
    read_affiliation,
    read_earnout_tranche,
    read_employment,
    read_payer_contract,
    read_practice,
    read_quality_review,
    read_service_agreement,
    separate_employment,
    set_clock,
    sign_deal,
    standardize_staffing,
    build_deal_in_draft,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOSE_DAY = "2026-09-01T00:00:00Z"
SECOND_SEPARATION_DAY = "2026-10-01T00:00:00Z"
COVENANT_END_DAY = "2028-09-01T00:00:00Z"
RESERVE_CLOCK = "2027-03-01T00:00:00Z"
SETTLE_CLOCK = "2027-09-02T00:00:00Z"
SUBMIT_CLOCK = "2026-11-15T00:00:00Z"
ENROLLMENT_EFFECTIVE = "2027-02-13T00:00:00Z"

D2740_EROSION_LINE = {
    "procedure_code": "D2740",
    "legacy_allowed_cents": 108_000,
    "dso_allowed_cents": 107_500,
    "annual_volume": 1538,
}
D0120_MATERIAL_LINE = {
    "procedure_code": "D0120",
    "legacy_allowed_cents": 5000,
    "dso_allowed_cents": 4999,
    "annual_volume": 231,
}
D0120_IMMATERIAL_LINE = {
    "procedure_code": "D0120",
    "legacy_allowed_cents": 5000,
    "dso_allowed_cents": 4999,
    "annual_volume": 229,
}


def _line_by_code(payer_contract_id, procedure_code):
    rows, _ = validate_paginated(
        api_client.list_fee_schedule_items(payer_contract_id, FINANCE)
    )
    return next(row for row in rows if row["procedure_code"] == procedure_code)


def test_a_doctor_licensed_in_another_state_cannot_be_offered_terms():
    """PRD §3.1: "Licensure is checked against geography here: the doctor's `license_state` must equal the practice's `state_code`, and a mismatch is refused with `ERR_LICENSE_STATE_MISMATCH`."
    PRD §2.11: "19. A doctor's licensure matches the employing practice's jurisdiction — `ERR_LICENSE_STATE_MISMATCH` (422)."

    Design: Corner/validations/license_state_mismatch_blocks_employment_offer
    """
    set_clock(CLOSE_DAY)
    affiliation = create_affiliation()
    vendor = create_conversion_vendor()
    practice = create_practice(affiliation["id"], vendor["id"], state_code="IL")

    out_of_state = create_doctor(
        full_name="Wes Nolan",
        npi="1710000031",
        license_number="WI-DDS-7788",
        license_state="WI",
        is_seller_owner=False,
    )
    in_state = create_doctor()

    validate_error(
        api_client.create_doctor_employment(
            create_doctor_employment_payload(practice["id"], out_of_state["id"]), LEAD
        ),
        ApiErrorId.ERR_LICENSE_STATE_MISMATCH.value,
        422,
    )

    accepted_payload = create_doctor_employment_payload(practice["id"], in_state["id"])
    accepted_payload.pop("comp_model")
    employment = validate_success(
        api_client.create_doctor_employment(accepted_payload, LEAD), expected_status=201
    )
    assert_doctor_employment(employment)
    assert employment["employment_status"] == "OFFERED"
    assert employment["comp_model"] == "MONTHLY_MIN_GUARANTEE"

    _, meta = validate_paginated(
        api_client.list_doctor_employments(LEAD, {"practice_id": practice["id"]})
    )
    assert meta["total_count"] == 1


def test_clinical_domains_never_reach_the_support_scope():
    """PRD §2.12: "First, the management services agreement may never buy clinical judgement. A scope line whose `service_domain` falls in the clinical set — `TREATMENT_PLANNING`, `CLINICAL_SUPERVISION` or `DIAGNOSIS` — is refused outright, so the computed `is_clinical` flag on a persisted scope line is always false; the flag exists precisely because a clinical domain never survives to be stored."
    PRD §2.12: "The non-clinical domains that may be purchased are `BILLING`, `HR`, `PROCUREMENT`, `IT`, `MARKETING`, `FACILITIES` and `CREDENTIALING`."

    Design: Corner/validations/corporate_practice_violation_blocks_clinical_scope_line
    """
    ctx = build_deal_in_draft(clock_utc=CLOSE_DAY)
    advance_to_diligence(ctx["affiliation_id"])
    agreement = create_service_agreement(ctx["practice_id"])
    add_service_line_item(agreement["id"])

    for service_code, service_domain, monthly_fee_cents in (
        ("SVC-TX-PLAN", "TREATMENT_PLANNING", 400_000),
        ("SVC-SUP-01", "CLINICAL_SUPERVISION", 150_000),
    ):
        validate_error(
            api_client.add_service_line_item(
                agreement["id"],
                {
                    "service_code": service_code,
                    "service_domain": service_domain,
                    "monthly_fee_cents": monthly_fee_cents,
                },
                COUNSEL,
            ),
            ApiErrorId.ERR_CORPORATE_PRACTICE_VIOLATION.value,
            422,
        )

    accepted = validate_success(
        api_client.add_service_line_item(
            agreement["id"],
            {
                "service_code": "SVC-IT-01",
                "service_domain": "IT",
                "monthly_fee_cents": 120_000,
            },
            COUNSEL,
        ),
        expected_status=201,
    )
    assert accepted["is_clinical"] is False

    reread = read_service_agreement(agreement["id"])
    assert_service_agreement(reread)
    assert reread["line_item_count"] == 2
    assert reread["status"] == "DRAFT"

    _, meta = validate_paginated(
        api_client.list_service_line_items(agreement["id"], COUNSEL)
    )
    assert meta["total_count"] == 2


def test_a_clinician_cannot_sign_off_on_their_own_charts():
    """PRD §3.8: "And no clinician may sign off on the quality of their own charts: when the closing director's own doctor identity is the same doctor named by the reviewed employment, the close is refused with `ERR_SELF_REVIEW_PROHIBITED`."
    PRD §3.8: "On a permitted close, the review moves from `OPEN` to `CLOSED_NO_FINDINGS`, `CLOSED_WITH_PLAN` or `ESCALATED` as requested, `closed_by_doctor_id` is stamped with the closing director's doctor identifier, `outcome_note` records the clinical narrative, and the review's `version` increments by one."

    Design: Corner/validations/self_review_prohibited_on_own_charts
    """
    ctx = build_closed_deal()
    director, _ = build_clinical_director()

    review = create_clinical_quality_review(
        ctx["employment_id"],
        director["id"],
        charts_sampled=40,
        charts_with_findings=0,
        treatment_plan_overrides=0,
    )
    assert review["score_bps"] == 10_000
    assert review["finding_rate_bps"] == 0
    assert review["override_rate_bps"] == 0

    validate_error(
        close_quality_review(
            review["id"],
            "CLOSED_NO_FINDINGS",
            ctx["doctor_id"],
            outcome_note="self sign-off attempt",
        ),
        ApiErrorId.ERR_SELF_REVIEW_PROHIBITED.value,
        422,
    )

    untouched = read_quality_review(review["id"], director["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["closed_by_doctor_id"] is None

    closed = validate_success(
        close_quality_review(
            review["id"],
            "CLOSED_NO_FINDINGS",
            director["id"],
            outcome_note="independent oversight sign-off",
        )
    )
    assert closed["status"] == "CLOSED_NO_FINDINGS"
    assert closed["closed_by_doctor_id"] == director["id"]


def test_the_reserving_controller_may_not_settle_what_they_reserved():
    """PRD §3.9: "It requires the tranche to be `RESERVED`, supplies `final_net_collections_cents` and `final_expenses_cents`, and enforces segregation of duties: the settling `X-User-ID` must differ from the `reserved_by_user_id` recorded at reservation, and an identical user is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "Two distinct controller users are required even though both act in the single `DsoFinanceController` role."

    Design: Corner/validations/segregation_of_duties_blocks_reserver_from_settling
    """
    ctx = build_closed_deal()
    reserved = build_reserved_tranche(
        ctx,
        reserve_clock=RESERVE_CLOCK,
        reported_net_collections_cents=210_000_000,
        reported_expenses_cents=151_000_000,
    )
    assert reserved["reserved_cents"] == 14_216_163
    set_clock(SETTLE_CLOCK)

    final_payload = {
        "final_net_collections_cents": 420_000_000,
        "final_expenses_cents": 285_000_000,
    }
    validate_error(
        api_client.settle_tranche(reserved["id"], final_payload, FINANCE),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    untouched = read_earnout_tranche(reserved["id"])
    assert untouched["status"] == "RESERVED"
    assert untouched["reserved_cents"] == 14_216_163
    assert untouched["settled_by_user_id"] is None

    settled = validate_success(
        api_client.settle_tranche(reserved["id"], final_payload, SETTLER)
    )
    assert settled["status"] == "SETTLED"
    assert settled["awarded_cents"] == 41_921_250
    assert settled["settled_by_user_id"] == FINANCE_SETTLER_USER_ID
    assert settled["reserved_by_user_id"] == FINANCE_RESERVER_USER_ID

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert_earnout_pool_ledger(affiliation)
    assert affiliation["earnout_unallocated_cents"] == 48_078_750


def test_a_covenant_cannot_be_asserted_on_the_instant_it_runs_out():
    """PRD §3.4: "Transaction counsel **enforces the restrictive covenant**, optionally recording an `enforcement_note`; this requires `employment_status` to be `SEPARATED`, requires `non_compete_enforcement_state` to be `PENDING`, and requires the logical clock to be strictly earlier than `non_compete_end_date`, since a covenant cannot be asserted once its own term has run — a clock at or after that instant is refused with `ERR_NON_COMPETE_EXPIRED`."
    PRD §3.4: "Hop one touches the employment row: `employment_status` moves `ACTIVE → SEPARATED`, `separation_date` is stamped from the logical clock, `separation_reason` is recorded from the request, `non_compete_end_date` is set to `separation_date` advanced by `non_compete_months` calendar months, `records_custody_state` moves `HELD_BY_PRACTICE → TRANSFER_PENDING`, `non_compete_enforcement_state` moves `NOT_APPLICABLE → PENDING`, and the practice's `active_doctor_count` decreases by one."

    Design: Corner/validations/non_compete_cannot_be_enforced_on_its_end_date
    """
    ctx = build_closed_deal_two_doctors(clock_utc=CLOSE_DAY, accept_second=True)

    expired = separate_employment(ctx["employment_id"])
    assert expired["non_compete_end_date"] == COVENANT_END_DAY

    set_clock(SECOND_SEPARATION_DAY)
    still_live = separate_employment(ctx["second_employment_id"])
    assert still_live["non_compete_end_date"] == "2028-10-01T00:00:00Z"

    set_clock(COVENANT_END_DAY)

    validate_error(
        api_client.enforce_non_compete(
            ctx["employment_id"], COUNSEL, {"enforcement_note": "expired covenant"}
        ),
        ApiErrorId.ERR_NON_COMPETE_EXPIRED.value,
        422,
    )
    refused = read_employment(ctx["employment_id"])
    assert refused["non_compete_enforcement_state"] == "PENDING"

    enforced = validate_success(
        api_client.enforce_non_compete(
            ctx["second_employment_id"],
            COUNSEL,
            {"enforcement_note": "10-mile radius asserted"},
        )
    )
    assert enforced["non_compete_enforcement_state"] == "ENFORCED"

    for employment_id in (ctx["employment_id"], ctx["second_employment_id"]):
        row = read_employment(employment_id)
        assert row["employment_status"] == "SEPARATED"
        assert row["records_custody_state"] == "TRANSFER_PENDING"


def test_both_ends_of_the_hygiene_ratio_band_are_accepted():
    """PRD §3.7: "The request supplies the standardized hygienist-to-doctor `fte_hygiene_ratio_bps`, which must fall inside the inclusive band from 8,000 to 25,000 basis points — from 0.8 hygienist FTE per doctor up to 2.5 — where both 8,000 and 25,000 are accepted and anything outside is refused with `ERR_STAFFING_RATIO_OUT_OF_RANGE`."
    PRD §3.7: "On success the ratio is stored, `staffing_model_state` moves `LEGACY → STANDARDIZED`, and the practice's `version` increments by one."

    Design: Corner/validations/staffing_ratio_bounds_are_inclusive
    """
    ctx = build_closed_deal()
    assert ctx["practice"]["integration_posture"] == "STABILIZING"
    assert ctx["practice"]["staffing_model_state"] == "LEGACY"
    assert ctx["practice"]["fte_hygiene_ratio_bps"] is None

    for out_of_band in (25_001, 7999):
        validate_error(
            standardize_staffing(ctx["practice_id"], out_of_band),
            ApiErrorId.ERR_STAFFING_RATIO_OUT_OF_RANGE.value,
            422,
        )
        refused = read_practice(ctx["practice_id"])
        assert refused["staffing_model_state"] == "LEGACY"
        assert refused["fte_hygiene_ratio_bps"] is None

    standardized = validate_success(standardize_staffing(ctx["practice_id"], 8000))
    assert standardized["staffing_model_state"] == "STANDARDIZED"
    assert standardized["fte_hygiene_ratio_bps"] == 8000
    assert standardized["integration_posture"] == "STABILIZING"


def test_the_management_fee_cap_admits_exactly_two_thousand_basis_points():
    """PRD §2.5: "A management services agreement may carry any non-negative `mgmt_fee_bps` while it is being drafted and reviewed, but at the moment it would become effective the fee is capped at 2,000 basis points — twenty percent of collections — and exactly 2,000 is allowed while 2,001 is rejected with `ERR_MGMT_FEE_CAP_EXCEEDED`."
    PRD §3.2: "Making the agreement effective carries it `LEGAL_REVIEW → EFFECTIVE` and stamps `effective_date` from the logical clock."

    Design: Corner/validations/mgmt_fee_cap_boundary_at_two_thousand_bps
    """
    ctx = build_deal_in_draft(clock_utc=CLOSE_DAY)
    advance_to_diligence(ctx["affiliation_id"])
    sign_deal(ctx["affiliation_id"])

    agreements = {}
    for label, mgmt_fee_bps in (("over", 2001), ("at_cap", 2000)):
        agreement = create_service_agreement(
            ctx["practice_id"], mgmt_fee_bps=mgmt_fee_bps
        )
        add_service_line_item(agreement["id"])
        validate_success(api_client.submit_legal_review(agreement["id"], COUNSEL))
        agreements[label] = agreement["id"]

    validate_error(
        api_client.make_agreement_effective(agreements["over"], COUNSEL),
        ApiErrorId.ERR_MGMT_FEE_CAP_EXCEEDED.value,
        422,
    )
    refused = read_service_agreement(agreements["over"])
    assert refused["status"] == "LEGAL_REVIEW"
    assert refused["effective_date"] is None

    effective = validate_success(
        api_client.make_agreement_effective(agreements["at_cap"], COUNSEL)
    )
    assert effective["status"] == "EFFECTIVE"
    assert effective["effective_date"] == CLOSE_DAY
    assert effective["mgmt_fee_bps"] == 2000

    assert read_affiliation(ctx["affiliation_id"])["status"] == "SIGNED"


def test_a_national_provider_identifier_is_unique_across_every_doctor():
    """PRD §3.1: "No two doctor records may share an identifier: a second registration of an `npi` already on file is refused with `ERR_DUPLICATE_NPI`."
    PRD §2.11: "40. A National Provider Identifier is unique across all doctors — `ERR_DUPLICATE_NPI` (409)."

    Design: Corner/validations/duplicate_npi_rejected_across_all_doctors
    """
    first = create_doctor()

    validate_error(
        api_client.create_doctor(
            {
                "full_name": "Beto Alvarez",
                "npi": first["npi"],
                "license_number": "WI-DDS-5521",
                "license_state": "WI",
                "specialty": "ENDODONTICS",
                "is_seller_owner": False,
            },
            LEAD,
        ),
        ApiErrorId.ERR_DUPLICATE_NPI.value,
        409,
    )

    second = validate_success(
        api_client.create_doctor(
            {
                "full_name": "Beto Alvarez",
                "npi": "1710000002",
                "license_number": "WI-DDS-5521",
                "license_state": "WI",
                "specialty": "ENDODONTICS",
                "is_seller_owner": False,
            },
            LEAD,
        ),
        expected_status=201,
    )
    assert second["npi"] == "1710000002"
    assert second["specialty"] == "ENDODONTICS"

    untouched = validate_success(api_client.get_doctor(first["id"], LEAD))
    assert untouched["full_name"] == first["full_name"]
    assert untouched["npi"] == first["npi"]


def test_child_code_uniqueness_is_measured_inside_one_parent_only():
    """PRD §3.6: "Each priced line names a CDT `procedure_code`, unique within its contract — a repeat is refused with `ERR_DUPLICATE_PROCEDURE_CODE` — together with the `legacy_allowed_cents` allowed amount under the seller's schedule, the `dso_allowed_cents` allowed amount under the DSO master schedule (both zero or more) and the `annual_volume` of that code at the practice (zero or more)."
    PRD §3.2: "A service code may appear only once per agreement; a repeat is refused with `ERR_DUPLICATE_SERVICE_CODE`."

    Design: Corner/validations/procedure_and_service_code_uniqueness_is_scoped_to_the_parent
    """
    ctx = build_closed_deal()
    repeated_line = {
        "procedure_code": "D0120",
        "legacy_allowed_cents": 5503,
        "dso_allowed_cents": 4800,
        "annual_volume": 50,
    }
    first_contract = build_priced_contract(ctx["practice_id"], lines=[repeated_line])
    second_contract = build_priced_contract(
        ctx["practice_id"], lines=[], payer_name="Prairie Dental Benefits"
    )

    validate_error(
        api_client.add_fee_schedule_item(first_contract["id"], repeated_line, FINANCE),
        ApiErrorId.ERR_DUPLICATE_PROCEDURE_CODE.value,
        409,
    )
    assert read_payer_contract(first_contract["id"])["fee_schedule_item_count"] == 1

    validate_success(
        api_client.add_fee_schedule_item(second_contract["id"], repeated_line, FINANCE),
        expected_status=201,
    )
    assert read_payer_contract(second_contract["id"])["fee_schedule_item_count"] == 1

    repeated_scope = {
        "service_code": "SVC-HR-01",
        "service_domain": "HR",
        "monthly_fee_cents": 95_000,
    }
    second_agreement = create_service_agreement(ctx["practice_id"])
    third_agreement = create_service_agreement(ctx["practice_id"])
    validate_success(
        api_client.add_service_line_item(
            second_agreement["id"], repeated_scope, COUNSEL
        ),
        expected_status=201,
    )

    validate_error(
        api_client.add_service_line_item(
            second_agreement["id"], repeated_scope, COUNSEL
        ),
        ApiErrorId.ERR_DUPLICATE_SERVICE_CODE.value,
        409,
    )
    assert read_service_agreement(second_agreement["id"])["line_item_count"] == 1

    validate_success(
        api_client.add_service_line_item(third_agreement["id"], repeated_scope, COUNSEL),
        expected_status=201,
    )
    assert read_service_agreement(third_agreement["id"])["line_item_count"] == 1


def test_erosion_of_exactly_five_thousand_dollars_demands_an_acknowledgement():
    """PRD §2.5: "A payer contract whose blended transition impact is materially erosive may still be activated, but only when the activating request carries `erosion_override_ack` set to true; material erosion means a blended impact at or below negative 500,000 cents (a loss of five thousand dollars a year or worse), and an impact of exactly negative 500,000 cents counts as material."
    PRD §2.5: "Without the acknowledgement the activation is rejected with `ERR_FEE_EROSION_MATERIAL`."

    Design: Corner/validations/fee_erosion_material_at_exactly_the_threshold_needs_acknowledgement
    """
    ctx = build_closed_deal()
    material = build_priced_contract(
        ctx["practice_id"], lines=[D2740_EROSION_LINE, D0120_MATERIAL_LINE]
    )
    immaterial = build_priced_contract(
        ctx["practice_id"],
        lines=[D2740_EROSION_LINE, D0120_IMMATERIAL_LINE],
        payer_name="Prairie Dental Benefits",
    )

    set_clock(SUBMIT_CLOCK)
    for contract in (material, immaterial):
        approved = build_approved_enrollment(
            contract["id"], ctx["employment_id"], ENROLLMENT_EFFECTIVE
        )
        assert approved["lead_days"] == 90

    assert _line_by_code(material["id"], "D2740")["line_impact_cents"] == -499_850
    assert _line_by_code(material["id"], "D0120")["line_impact_cents"] == -150
    assert _line_by_code(immaterial["id"], "D0120")["line_impact_cents"] == -149
    assert read_payer_contract(material["id"])["blended_impact_cents"] == -500_000
    assert read_payer_contract(immaterial["id"])["blended_impact_cents"] == -499_999

    validate_error(
        activate_fee_schedule(material["id"], ENROLLMENT_EFFECTIVE),
        ApiErrorId.ERR_FEE_EROSION_MATERIAL.value,
        422,
    )
    assert read_payer_contract(material["id"])["transition_state"] == (
        "PENDING_CREDENTIALING"
    )

    acknowledged = validate_success(
        activate_fee_schedule(
            material["id"], ENROLLMENT_EFFECTIVE, erosion_override_ack=True
        )
    )
    assert acknowledged["transition_state"] == "DSO_SCHEDULE_ACTIVE"
    assert acknowledged["erosion_override_ack"] is True

    unacknowledged = validate_success(
        activate_fee_schedule(immaterial["id"], ENROLLMENT_EFFECTIVE)
    )
    assert unacknowledged["transition_state"] == "DSO_SCHEDULE_ACTIVE"
    assert unacknowledged["erosion_override_ack"] is False


def test_the_first_projected_tranche_freezes_the_pool_against_repricing():
    """PRD §3.1: "Repricing also becomes impossible once the pool has been committed against: if even one earn-out tranche exists for the affiliation, the pool size is frozen and the attempt is refused with `ERR_EARNOUT_POOL_LOCKED`."
    PRD §3.9: "A new tranche opens in `PROJECTED` with no `variant_applied`, with `reserved_cents`, `awarded_cents` and `clawed_back_cents` all at zero, with every reported, annualized, final and derived figure still empty, and with neither `reserved_by_user_id` nor `settled_by_user_id` recorded; it increments the affiliation's `version` by one."

    Design: Corner/validations/earnout_pool_locked_once_a_tranche_is_projected
    """
    ctx = build_deal_in_draft(clock_utc=CLOSE_DAY)
    advance_to_diligence(ctx["affiliation_id"])
    tranche = project_tranche(ctx["affiliation_id"])

    validate_error(
        api_client.reprice_affiliation(
            ctx["affiliation_id"],
            {
                "purchase_price_cents": 430_000_000,
                "earnout_pool_cents": 110_000_000,
                "reprice_note": "diligence adjustment after the tranche was projected",
            },
            COUNSEL,
        ),
        ApiErrorId.ERR_EARNOUT_POOL_LOCKED.value,
        409,
    )

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert affiliation["status"] == "DILIGENCE"
    assert affiliation["repricing_round"] == 0
    assert affiliation["purchase_price_cents"] == 450_000_000
    assert affiliation["earnout_pool_cents"] == 90_000_000
    assert affiliation["earnout_unallocated_cents"] == 90_000_000
    assert read_earnout_tranche(tranche["id"])["status"] == "PROJECTED"


def test_the_clock_accepts_its_own_value_but_never_an_earlier_one():
    """PRD §2.4: "Any role may advance it by supplying a `current_utc` instant; the clock may move forward or stay where it is, but a requested value earlier than the current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` and an equal value is accepted as a no-op."
    PRD §2.4: "Every timestamp the server stamps — `diligence_opened_at`, `signed_date`, `close_date`, `effective_date` on an agreement, `comp_effective_date`, `separation_date`, `submitted_at`, `decided_at` — is read from the logical clock, as are every lead-time computation, every annualization denominator and every cutover-window comparison."

    Design: Corner/validations/logical_clock_rejects_backward_moves_and_accepts_equal
    """
    set_clock(CLOSE_DAY)
    validate_success(api_client.set_clock({"current_utc": CLOSE_DAY}, LEAD))

    validate_error(
        api_client.set_clock({"current_utc": "2026-08-31T23:59:59Z"}, LEAD),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
        422,
    )

    validate_success(api_client.set_clock({"current_utc": "2026-09-02T00:00:00Z"}, LEAD))
    affiliation = create_affiliation()
    assert affiliation["created_at"].startswith("2026-09-02T00:00:00")
