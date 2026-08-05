"""Real-estate transfer certificates: charges, the two grading variants and the gates."""

from test_helpers import (
    ApiErrorId,
    assert_transfer_inspection,
    condemn_parcel_well,
    create_parcel,
    create_transfer_inspection_payload,
    create_well,
    open_and_issue_repair_order,
    pay_parcel_fees_in_full,
    refresh_operating_permit,
    refresh_parcel,
    refresh_transfer_inspection,
    refresh_well,
    request_transfer_inspection,
    set_clock,
    setup_operating_parcel,
    unique_apn,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_desk_review_certificate_is_conditional_on_a_due_soon_deadline(api, applicant_headers, ehs_reviewer_headers):
    """PRD §3.9: "Otherwise, if the permit's `compliance_status` is `DUE_SOON` or
    `DELINQUENT`, or the parcel's `water_quality_flag` is true, the base is
    `CONDITIONAL`."
    PRD §3.9: "Under `DESK_REVIEW`, step two does nothing: `certificate_grade` is the
    base grade unchanged, and field conditions are neither collected nor consulted."
    PRD §3.9: "On success `certified_at` is stamped from the logical clock and
    `certificate_valid_until` is set to 180 days after `certified_at`."

    Design: Difficulty/dual_variant_calc/transfer_certificate_desk_review_conditional_vs_field_verified_satisfactory
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-DV2"),
        site_address="2 Transfer Lane",
        water_source="PRIVATE_WELL",
    )
    pay_parcel_fees_in_full(api, ctx["parcel_id"], payer_headers=applicant_headers)
    set_clock(api, "2029-01-31T00:00:00Z")

    permit = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert permit["compliance_status"] == "DUE_SOON"
    assert permit["next_pumping_due_on"] == "2029-05-01T00:00:00.000Z"

    desk = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2029-01-31T00:00:00Z",
        buyer_name="Buyer One",
        seller_name="Seller One",
        inspection_mode="DESK_REVIEW",
    )
    assert desk["subtotal_cents"] == 18500
    assert desk["total_due_cents"] == 18500

    certified = validate_success(
        api.certify_transfer_inspection(desk["id"], {"decision": "CERTIFY"}, ehs_reviewer_headers),
        200,
    )
    assert_transfer_inspection(certified)
    assert certified["status"] == "CERTIFIED"
    assert certified["certificate_grade"] == "CONDITIONAL"
    assert certified["certified_at"] == "2029-01-31T00:00:00.000Z"
    assert certified["certificate_valid_until"] == "2029-07-30T00:00:00.000Z"


def test_field_verification_clears_a_due_soon_conditional_that_desk_review_keeps(api, applicant_headers, ehs_reviewer_headers):
    """PRD §3.9: "If both are `GOOD`, field verification may *clear* a records-only
    `CONDITIONAL`, but only in one narrow circumstance: when the base is `CONDITIONAL`,
    the permit's `compliance_status` is `DUE_SOON`, and the parcel's
    `water_quality_flag` is false — that is, when the sole defect was an approaching
    pumping deadline — the grade is upgraded to `SATISFACTORY`."
    PRD §3.9: "The consequence is deliberate: two requests against identical records
    yield `CONDITIONAL` under `DESK_REVIEW` and `SATISFACTORY` under `FIELD_VERIFIED`
    whenever the only blemish is a due-soon deadline."
    PRD §3.9: "The `subtotal_cents` is a base transfer fee of 18500 cents, plus 9500
    cents when the mode is `FIELD_VERIFIED`, plus a records-research fee of 4000 cents
    when the parcel's `open_repair_order_count` is greater than zero at that moment."

    Design: Difficulty/dual_variant_calc/transfer_certificate_desk_review_conditional_vs_field_verified_satisfactory
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-DV2B"),
        site_address="2 Transfer Lane",
        water_source="PRIVATE_WELL",
    )
    pay_parcel_fees_in_full(api, ctx["parcel_id"], payer_headers=applicant_headers)
    set_clock(api, "2029-01-31T00:00:00Z")

    desk = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2029-01-31T00:00:00Z",
        buyer_name="Buyer One",
        seller_name="Seller One",
        inspection_mode="DESK_REVIEW",
    )
    field = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2029-01-31T00:00:00Z",
        buyer_name="Buyer One",
        seller_name="Seller One",
        inspection_mode="FIELD_VERIFIED",
        tank_condition="GOOD",
        drainfield_condition="GOOD",
    )
    assert field["subtotal_cents"] == 28000
    assert field["total_due_cents"] == 28000

    desk_certified = validate_success(
        api.certify_transfer_inspection(desk["id"], {"decision": "CERTIFY"}, ehs_reviewer_headers),
        200,
    )
    field_certified = validate_success(
        api.certify_transfer_inspection(field["id"], {"decision": "CERTIFY"}, ehs_reviewer_headers),
        200,
    )

    assert desk_certified["certificate_grade"] == "CONDITIONAL"
    assert field_certified["certificate_grade"] == "SATISFACTORY", (
        "field verification with both conditions GOOD clears a due-soon-only CONDITIONAL"
    )


def test_expedite_rate_is_keyed_on_the_subtotal_alone(api, applicant_headers):
    """PRD §3.9: "When it is true, an expedite rate is selected **from the subtotal
    alone**: 30 percent when `subtotal_cents` is strictly below 20000, 20 percent when
    it is strictly below 30000, and 15 percent otherwise. The `expedite_fee_cents` is
    the subtotal multiplied by that rate and rounded half up to whole cents.
    `total_due_cents` is then the subtotal plus the expedite fee."
    PRD §3.9: "The evaluation order here is pinned and deliberately non-obvious:
    although the rate is described as keyed on a total, the tier is chosen from the
    pre-expedite subtotal and is never re-selected after the expedite fee is added, and
    the calculation is never iterated to a fixed point."

    Design: Difficulty/combinatorial_formula/transfer_expedite_rate_tier_selected_from_subtotal_not_from_final_total
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CF3"),
        site_address="5 Expedite Court",
    )
    request = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-02T00:00:00Z",
        buyer_name="Buyer Two",
        seller_name="Seller Two",
        inspection_mode="FIELD_VERIFIED",
        expedited=True,
        tank_condition="GOOD",
        drainfield_condition="GOOD",
    )

    assert request["expedite_fee_cents"] == 5600, "28000 sits below 30000, so the 20 percent tier applies"
    assert request["total_due_cents"] == 33600
    assert request["expedite_fee_cents"] != 4200, (
        "4200 is the answer produced by re-selecting the tier from the 33600 total"
    )


def test_expedited_request_starts_in_requested_with_its_subtotal_settled(api, applicant_headers):
    """PRD §3.9: "The `subtotal_cents` is a base transfer fee of 18500 cents, plus 9500
    cents when the mode is `FIELD_VERIFIED`, plus a records-research fee of 4000 cents
    when the parcel's `open_repair_order_count` is greater than zero at that moment."
    PRD §3.9: "A new request starts in `REQUESTED` with `certificate_grade`,
    `certified_at` and `certificate_valid_until` all null, and it advances the parcel's
    `version` by 1."

    Design: Difficulty/combinatorial_formula/transfer_expedite_rate_tier_selected_from_subtotal_not_from_final_total
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CF3B"),
        site_address="5 Expedite Court",
    )
    before = refresh_parcel(api, ctx["parcel_id"], applicant_headers)
    request = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-02T00:00:00Z",
        buyer_name="Buyer Two",
        seller_name="Seller Two",
        inspection_mode="FIELD_VERIFIED",
        expedited=True,
        tank_condition="GOOD",
        drainfield_condition="GOOD",
    )

    assert request["subtotal_cents"] == 28000, "no open repair order, so no records-research line"
    assert request["status"] == "REQUESTED"
    assert request["certificate_grade"] is None
    assert refresh_parcel(api, ctx["parcel_id"], applicant_headers)["version"] == before["version"] + 1


def test_records_research_line_lifts_the_subtotal_into_the_high_expedite_tier(api, applicant_headers):
    """PRD §3.9: "plus a records-research fee of 4000 cents when the parcel's
    `open_repair_order_count` is greater than zero at that moment."
    PRD §3.9: "30 percent when `subtotal_cents` is strictly below 20000, 20 percent when
    it is strictly below 30000, and 15 percent otherwise."
    PRD §3.9: "One exception: if the cited operating permit is already `SUSPENDED` at
    the moment the request is opened, the request starts in `BLOCKED` instead."

    Design: Corner/calculations/corner_transfer_charges_add_records_research_fee_and_select_high_expedite_tier
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-C10"),
        site_address="55 Research Reach",
    )
    open_and_issue_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="STRUCTURAL",
        reported_on="2026-05-03T00:00:00Z",
    )
    assert refresh_parcel(api, ctx["parcel_id"])["open_repair_order_count"] == 1

    request = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-04T00:00:00Z",
        buyer_name="Buyer Six",
        seller_name="Seller Six",
        inspection_mode="FIELD_VERIFIED",
        expedited=True,
        tank_condition="FAIR",
        drainfield_condition="GOOD",
    )

    assert request["subtotal_cents"] == 32000, "18500 base plus 9500 field plus 4000 research"
    assert request["expedite_fee_cents"] == 4800, "32000 is at or above 30000, so 15 percent applies"
    assert request["total_due_cents"] == 36800
    assert request["status"] == "BLOCKED"
    assert request["certificate_grade"] is None


def test_field_conditions_must_match_the_inspection_mode(api, applicant_headers):
    """PRD §3.9: "A `FIELD_VERIFIED` request must supply both `tank_condition` and
    `drainfield_condition`, each `GOOD`, `FAIR` or `POOR`. A `DESK_REVIEW` request must
    supply neither. Omitting either on a field-verified request, or supplying either on
    a desk review, is refused with `ERR_FIELD_CONDITIONS_REQUIRED`."

    Design: Corner/validations/corner_field_verified_transfer_without_conditions_is_rejected
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-V9"),
        site_address="62 Conditions Court",
    )
    parcel_version = refresh_parcel(api, ctx["parcel_id"], applicant_headers)["version"]

    missing_conditions = api.create_transfer_inspection(
        create_transfer_inspection_payload(
            ctx["parcel_id"],
            ctx["operating_permit_id"],
            parcel_version,
            requested_on="2026-05-03T00:00:00Z",
            buyer_name="Buyer Seven",
            seller_name="Seller Seven",
            inspection_mode="FIELD_VERIFIED",
        ),
        applicant_headers,
    )
    validate_error(missing_conditions, ApiErrorId.ERR_FIELD_CONDITIONS_REQUIRED.value, 422)

    surplus_conditions = api.create_transfer_inspection(
        create_transfer_inspection_payload(
            ctx["parcel_id"],
            ctx["operating_permit_id"],
            parcel_version,
            requested_on="2026-05-03T00:00:00Z",
            buyer_name="Buyer Seven",
            seller_name="Seller Seven",
            inspection_mode="DESK_REVIEW",
            tank_condition="GOOD",
        ),
        applicant_headers,
    )
    validate_error(surplus_conditions, ApiErrorId.ERR_FIELD_CONDITIONS_REQUIRED.value, 422)

    _, meta = validate_paginated(
        api.list_transfer_inspections(applicant_headers, params={"parcel_id": ctx["parcel_id"]})
    )
    assert meta["total_count"] == 0
    assert refresh_parcel(api, ctx["parcel_id"], applicant_headers)["version"] == parcel_version


def test_outstanding_fee_balance_blocks_certification_until_it_is_settled(api, applicant_headers, ehs_reviewer_headers):
    """PRD §2.6: "A transfer certificate may only be signed against a parcel whose fee
    ledger is settled; an outstanding balance is refused with
    `ERR_OUTSTANDING_FEE_BALANCE`, and this is the register's only HTTP 402."
    PRD §3.9: "and the parcel's `fee_balance_cents` must be exactly zero, else
    `ERR_OUTSTANDING_FEE_BALANCE`."
    PRD §3.9: "Otherwise the base is `SATISFACTORY`."

    Design: Corner/validations/corner_outstanding_fee_balance_blocks_transfer_certification
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-V12"),
        site_address="65 Arrears Avenue",
    )
    request = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-03T00:00:00Z",
        buyer_name="Buyer Eight",
        seller_name="Seller Eight",
        inspection_mode="DESK_REVIEW",
    )
    assert refresh_parcel(api, ctx["parcel_id"])["fee_balance_cents"] == 73018

    refused = api.certify_transfer_inspection(
        request["id"], {"decision": "CERTIFY"}, ehs_reviewer_headers
    )
    validate_error(refused, ApiErrorId.ERR_OUTSTANDING_FEE_BALANCE.value, 402)

    validate_success(
        api.record_fee_payment(ctx["parcel_id"], {"amount_cents": 73018}, applicant_headers), 200
    )
    settled = refresh_parcel(api, ctx["parcel_id"])
    assert settled["fees_paid_cents"] == 73018
    assert settled["fee_balance_cents"] == 0

    certified = validate_success(
        api.certify_transfer_inspection(
            request["id"], {"decision": "CERTIFY"}, ehs_reviewer_headers
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certificate_grade"] == "SATISFACTORY"
    assert certified["certified_at"] == "2026-05-01T00:00:00.000Z"
    assert certified["certificate_valid_until"] == "2026-10-28T00:00:00.000Z"


def test_condemned_well_raises_a_transfer_hold_that_blocks_certification(api, applicant_headers, ehs_reviewer_headers):
    """PRD §3.1: "`transfer_hold` is true when any of three conditions holds: the parcel
    has at least one open repair order, or any operating permit on the parcel is
    `REVOKED`, or any well on the parcel is `CONDEMNED`; while it is true, no transfer
    certificate may be signed for that parcel."
    PRD §3.9: "the parcel's `transfer_hold` must be false, else
    `ERR_TRANSFER_HOLD_ACTIVE`"

    Design: Corner/validations/corner_transfer_hold_from_condemned_well_blocks_certification
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-V13"),
        site_address="66 Condemned Crossing",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=110)
    ctx = setup_operating_parcel(
        api, existing_parcel=parcel, applicant_headers=applicant_headers
    )
    pay_parcel_fees_in_full(api, parcel["id"], payer_headers=applicant_headers)

    request = request_transfer_inspection(
        api,
        parcel["id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-03T00:00:00Z",
        buyer_name="Buyer Nine",
        seller_name="Seller Nine",
        inspection_mode="DESK_REVIEW",
    )
    condemn_parcel_well(api, well["id"], collected_at="2026-05-04T06:00:00Z")

    assert refresh_well(api, well["id"])["advisory_status"] == "CONDEMNED"
    parcel_now = refresh_parcel(api, parcel["id"])
    assert parcel_now["transfer_hold"] is True
    assert parcel_now["fee_balance_cents"] == 0
    assert refresh_operating_permit(api, ctx["operating_permit_id"])["status"] == "ACTIVE"

    refused = api.certify_transfer_inspection(
        request["id"], {"decision": "CERTIFY"}, ehs_reviewer_headers
    )
    validate_error(refused, ApiErrorId.ERR_TRANSFER_HOLD_ACTIVE.value, 409)

    unchanged = refresh_transfer_inspection(api, request["id"])
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["certificate_grade"] is None


def test_certification_is_refused_once_the_operating_permit_has_lapsed(api, applicant_headers, ehs_reviewer_headers):
    """PRD §3.9: "A certification moves `REQUESTED → CERTIFIED` and requires three things
    in the ladder order of §2.6: the cited operating permit must be `ACTIVE`, else
    `ERR_OPERATING_PERMIT_NOT_ACTIVE`; the parcel's `transfer_hold` must be false, else
    `ERR_TRANSFER_HOLD_ACTIVE`; and the parcel's `fee_balance_cents` must be exactly
    zero, else `ERR_OUTSTANDING_FEE_BALANCE`."
    PRD §3.7: "Separately, when the logical clock advances strictly past `expires_on`, a
    permit that is `ACTIVE` or `SUSPENDED` moves to `EXPIRED` with no further side
    effects."

    Design: Difficulty/cross_entity_state_dependency/transfer_certification_gated_on_operating_permit_status_active
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CE2"),
        site_address="15 Lapse Lane",
    )
    pay_parcel_fees_in_full(api, ctx["parcel_id"], payer_headers=applicant_headers)
    request = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-03T00:00:00Z",
        buyer_name="Buyer Four",
        seller_name="Seller Four",
        inspection_mode="DESK_REVIEW",
    )
    set_clock(api, "2031-06-01T00:00:00Z")

    refused = api.certify_transfer_inspection(
        request["id"], {"decision": "CERTIFY"}, ehs_reviewer_headers
    )
    validate_error(refused, ApiErrorId.ERR_OPERATING_PERMIT_NOT_ACTIVE.value, 409)


def test_lapsed_permit_leaves_the_request_untouched_and_the_parcel_clear(api, applicant_headers, ehs_reviewer_headers):
    """PRD §3.7: "Separately, when the logical clock advances strictly past `expires_on`,
    a permit that is `ACTIVE` or `SUSPENDED` moves to `EXPIRED` with no further side
    effects."
    PRD §3.9: "A new request starts in `REQUESTED` with `certificate_grade`,
    `certified_at` and `certificate_valid_until` all null, and it advances the parcel's
    `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/transfer_certification_gated_on_operating_permit_status_active
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CE2B"),
        site_address="15 Lapse Lane",
    )
    pay_parcel_fees_in_full(api, ctx["parcel_id"], payer_headers=applicant_headers)
    request = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-03T00:00:00Z",
        buyer_name="Buyer Four",
        seller_name="Seller Four",
        inspection_mode="DESK_REVIEW",
    )
    set_clock(api, "2031-06-01T00:00:00Z")
    validate_error(
        api.certify_transfer_inspection(request["id"], {"decision": "CERTIFY"}, ehs_reviewer_headers),
        ApiErrorId.ERR_OPERATING_PERMIT_NOT_ACTIVE.value,
        409,
    )

    permit = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert permit["status"] == "EXPIRED"
    assert permit["expires_on"] == "2031-05-01T00:00:00.000Z"

    unchanged = refresh_transfer_inspection(api, request["id"])
    assert unchanged["status"] == "REQUESTED", "expiry does not block the request the way a suspension does"
    assert unchanged["certificate_grade"] is None

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["fee_balance_cents"] == 0
    assert parcel["transfer_hold"] is False


def test_records_clerk_may_open_a_request_but_not_sign_the_certificate(api, applicant_headers, records_clerk_headers):
    """PRD §3.9: "A request is opened by the owning `Applicant` or by a `RecordsClerk` at
    the counter, naming the `parcel_id` changing hands, the `operating_permit_id` whose
    system is being certified, the `expected_parcel_version` of §2.7, the `requested_on`
    instant the certificate was asked for, the `buyer_name` of the purchasing party and
    the `seller_name` of the selling party — both non-empty — and the `inspection_mode`."
    PRD §3.9: "**Signing the certificate** belongs to an `EnvironmentalHealthSpecialist`,
    who answers a `decision` of `CERTIFY` or `DENY`."
    PRD §2.1: "If both headers are well formed but the named role is not among the roles
    the target operation authorises, the refusal is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_records_clerk_cannot_sign_a_transfer_certificate_returns_unauthorized
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-R4"),
        site_address="75 Clerk Close",
    )
    clerk_version = refresh_parcel(api, ctx["parcel_id"], records_clerk_headers)["version"]
    request = validate_success(
        api.create_transfer_inspection(
            create_transfer_inspection_payload(
                ctx["parcel_id"],
                ctx["operating_permit_id"],
                clerk_version,
                requested_on="2026-05-03T00:00:00Z",
                buyer_name="Buyer Ten",
                seller_name="Seller Ten",
                inspection_mode="DESK_REVIEW",
            ),
            records_clerk_headers,
        ),
        201,
    )
    assert request["status"] == "REQUESTED"

    refused = api.certify_transfer_inspection(
        request["id"], {"decision": "CERTIFY"}, records_clerk_headers
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert refresh_transfer_inspection(api, request["id"])["status"] == "REQUESTED"
