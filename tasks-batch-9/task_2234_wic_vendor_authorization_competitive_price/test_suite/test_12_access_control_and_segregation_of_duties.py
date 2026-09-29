"""
Role-based access control, vendor scoping, and the two maker-checker fences.

Every test here builds its whole world from scratch through the documented
endpoints, because the server is relaunched against an empty database before each
one. The logical clock reads 2026-08-01T00:00:00Z until a test moves it.
"""

from test_helpers import (
    ANALYST_HEADERS,
    INVESTIGATOR_HEADERS,
    NON_EXISTENT_UUID,
    SUPERVISOR_HEADERS,
    SUPERVISOR_TWO_HEADERS,
    SYSTEM_HEADERS,
    ApiErrorId,
    AdjustmentStatus,
    AdjustmentReasonCode,
    ClaimStatus,
    PriceCycleStatus,
    RiskTier,
    Role,
    SanctionResolution,
    SanctionStatus,
    VendorStatus,
    VisitOutcome,
    VisitStatus,
    VisitType,
    factories,
    fixtures,
    make_headers,
    make_partial_headers,
    make_vendor_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_analyst_cannot_authorize_or_publish(api):
    """
    A VendorUnitAnalyst is refused the supervisor's committing operations, and the
    refusal leaves the vendor and the price cycle exactly as they were.

    "If both headers are well-formed but the declared role is not among the roles
    authorized for the addressed endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    "The acting role appears in the addressed endpoint's role list — otherwise
    `ERR_FORBIDDEN_ROLE`."
    "| POST | `/vendors/{id}/authorize` | Authorize a vendor under review once training,
    price submissions, peer group and sanction status all clear | VendorUnitSupervisor |"
    "| POST | `/price-cycles/{id}/publish-ceilings` | Publish the maximum allowable
    reimbursement per item per peer group from the final candidate set |
    VendorUnitSupervisor |"
    "Authorizing a vendor is a supervisor decision that turns a reviewed application
    into an operating WIC vendor, advancing `authorization_status` from `IN_REVIEW` to
    `AUTHORIZED`."
    "For each pair with a non-empty candidate set, a PriceCeiling row is written with
    `status` `PROVISIONAL`; the number written becomes the cycle's
    `provisional_ceiling_count`, and the number of pairs skipped for having an empty
    candidate set becomes its `skipped_pair_count`."
    "Publishing moves a cycle `CLOSED → PUBLISHED` — again `ERR_INVALID_CYCLE_STATE` for
    any other status — stamps `published_at`, and performs three passes."

    Design: Corner/rbac/analyst_cannot_authorize_or_publish
    """
    catalogue = fixtures.bootstrap_catalogue(api)
    vendor = fixtures.vendor_in_review(api)
    submission = fixtures.submit_price(
        api, vendor["id"], catalogue["milk_item"]["id"], catalogue["cycle"]["id"], 320
    )
    fixtures.accept_submission(api, submission["id"])
    fixtures.close_cycle(api, catalogue["cycle"]["id"])

    # Every business precondition for authorize and for publish-ceilings is met; only
    # the acting role is wrong, and rule 2 of the ladder decides before any of them.
    validate_error(
        api.authorize_vendor(vendor["id"], None, ANALYST_HEADERS),
        ApiErrorId.FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.publish_ceilings(catalogue["cycle"]["id"], None, ANALYST_HEADERS),
        ApiErrorId.FORBIDDEN_ROLE.value,
    )

    refused_vendor = validate_success(api.get_vendor(vendor["id"], SUPERVISOR_HEADERS))
    assert refused_vendor["authorization_status"] == VendorStatus.IN_REVIEW.value
    assert refused_vendor["authorized_at"] is None

    refused_cycle = validate_success(
        api.get_price_cycle(catalogue["cycle"]["id"], SUPERVISOR_HEADERS)
    )
    assert refused_cycle["status"] == PriceCycleStatus.CLOSED.value
    assert refused_cycle["published_at"] is None
    # One ACTIVE peer group times one ACTIVE item is one pair, and its candidate set
    # holds the single accepted submission, so exactly one PROVISIONAL row was written.
    assert refused_cycle["provisional_ceiling_count"] == 1
    assert refused_cycle["skipped_pair_count"] == 0

    authorized = validate_success(
        api.authorize_vendor(vendor["id"], None, SUPERVISOR_HEADERS)
    )
    assert authorized["authorization_status"] == VendorStatus.AUTHORIZED.value


def test_compliance_buy_visit_type_cannot_be_created_by_analyst(api):
    """
    A compliance buy is refused to the analyst on visit-type grounds and to the
    investigator on warrant grounds, while the analyst's routine visit is created.

    "A monitoring visit whose `visit_type` is `COMPLIANCE_BUY` may only be created by a
    `ComplianceInvestigator`; a `VendorUnitAnalyst` may create `ROUTINE` and
    `HIGH_RISK_FOLLOWUP` visits only, and an attempt to create a compliance buy under
    any other role is rejected with `ERR_FORBIDDEN_VISIT_TYPE` (HTTP 403)."
    "On visit creation, the compliance-buy role restriction — otherwise
    `ERR_FORBIDDEN_VISIT_TYPE`."
    "A `COMPLIANCE_BUY` may only be created by a `ComplianceInvestigator`, as §2.1
    requires, and it may only be created when the vendor actually warrants one: either
    `compliance_buy_required` is true or `risk_tier` is `HIGH`."
    "A compliance buy scheduled against a vendor that is neither flagged nor in the top
    risk tier is refused with `ERR_COMPLIANCE_BUY_NOT_WARRANTED`."
    "Client-created visits begin `SCHEDULED` with `auto_generated` false, an `outcome` of
    `PENDING`, an `overcharge_cents` of 0, a `stock_compliance_pct` of 0.0, and
    `conducted_at` and `cancelled_reason` null."
    "| POST | `/monitoring-visits` | Schedule a routine, compliance-buy or high-risk
    follow-up monitoring visit | VendorUnitAnalyst, ComplianceInvestigator |"

    Design: Corner/rbac/compliance_buy_visit_type_cannot_be_created_by_analyst
    """
    bundle = fixtures.authorized_vendor_setup(api)
    vendor_id = bundle["vendor"]["id"]

    fresh_vendor = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert fresh_vendor["compliance_buy_required"] is False
    assert fresh_vendor["risk_tier"] == RiskTier.LOW.value

    buy_payload = factories.monitoring_visit_payload(
        vendor_id,
        visit_type=VisitType.COMPLIANCE_BUY.value,
        scheduled_for="2026-08-20T00:00:00Z",
    )

    # The analyst is a declared role for this endpoint, so rule 2 passes and the
    # visit_type restriction of rule 4 is what refuses the request.
    validate_error(
        api.create_monitoring_visit(buy_payload, ANALYST_HEADERS),
        ApiErrorId.FORBIDDEN_VISIT_TYPE.value,
    )
    # The investigator clears rule 4 and is stopped later, by the warrant test.
    validate_error(
        api.create_monitoring_visit(buy_payload, INVESTIGATOR_HEADERS),
        ApiErrorId.COMPLIANCE_BUY_NOT_WARRANTED.value,
    )

    routine = validate_success(
        api.create_monitoring_visit(
            factories.monitoring_visit_payload(
                vendor_id,
                visit_type=VisitType.ROUTINE.value,
                scheduled_for="2026-08-20T00:00:00Z",
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )
    assert routine["visit_type"] == VisitType.ROUTINE.value
    assert routine["status"] == VisitStatus.SCHEDULED.value
    assert routine["auto_generated"] is False
    assert routine["outcome"] == VisitOutcome.PENDING.value
    assert routine["overcharge_cents"] == 0
    assert routine["stock_compliance_pct"] == 0.0
    assert routine["conducted_at"] is None
    assert routine["cancelled_reason"] is None

    all_visits, all_meta = validate_paginated(
        api.list_monitoring_visits(ANALYST_HEADERS, {"vendor_id": vendor_id})
    )
    assert all_meta["total_count"] == 1
    assert [visit["id"] for visit in all_visits] == [routine["id"]]

    _, buy_meta = validate_paginated(
        api.list_monitoring_visits(
            ANALYST_HEADERS,
            {"vendor_id": vendor_id, "visit_type": VisitType.COMPLIANCE_BUY.value},
        )
    )
    assert buy_meta["total_count"] == 0


def test_applying_own_adjustment_is_forbidden(api):
    """
    The supervisor that raised a reimbursement adjustment may not apply it, while a
    different supervisor of the same role applies it and moves the money.

    "A pending reimbursement adjustment may not be applied by the same principal that
    created it: if `X-User-ID` equals the adjustment's `created_by_user_id`, the apply is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    "The adjustment begins in `status` `PENDING` with `created_by_user_id` stamped from
    the acting `X-User-ID` and with `applied_by_user_id`, `applied_at`, `reversed_at`,
    and `reversal_reason` all null."
    "Those lines are ordered by ascending `line_number`, and for each one the server
    records an entry in `line_recoupments` holding the `claim_line_id`, that line's
    `allowed_cents`, and a `recoupment_cents` equal to the line's `allowed_cents`
    multiplied by the `recoupment_rate`, rounded half up to a whole cent."
    "On success, `applied_by_user_id` and `applied_at` are stamped, and money moves in
    three places at once: the claim advances `ADJUDICATED → ADJUSTED` with its
    `net_payable_cents` reduced by the adjustment's `recoupment_cents`, each
    participating claim line has its `recouped_cents` increased by that line's prorated
    share, and the vendor's `recoupment_balance_cents` rises by the adjustment's
    `recoupment_cents`."
    "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`,
    and the server never falls back to real time."

    Design: Corner/rbac/applying_own_adjustment_is_forbidden
    """
    bundle = fixtures.pending_adjustment_setup(
        api, recoupment_rate=0.25, creator_headers=SUPERVISOR_HEADERS
    )
    adjustment = bundle["adjustment"]
    claim_id = bundle["claim"]["id"]
    vendor_id = bundle["vendor"]["id"]

    # The single line was accepted at the published ceiling of 336 cents, so the
    # prorated share is 336 x 0.25 = 84.0 -> 84 cents rounded half up.
    assert adjustment["reason_code"] == AdjustmentReasonCode.EDIT_ERROR.value
    assert adjustment["recoupment_cents"] == 84
    assert len(adjustment["line_recoupments"]) == 1
    assert adjustment["line_recoupments"][0]["allowed_cents"] == 336
    assert adjustment["line_recoupments"][0]["recoupment_cents"] == 84
    assert adjustment["status"] == AdjustmentStatus.PENDING.value
    assert adjustment["created_by_user_id"] == SUPERVISOR_HEADERS["X-User-ID"]

    validate_error(
        api.apply_adjustment(adjustment["id"], None, SUPERVISOR_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
    )

    refused = validate_success(
        api.get_reimbursement_adjustment(adjustment["id"], SUPERVISOR_HEADERS)
    )
    assert refused["status"] == AdjustmentStatus.PENDING.value
    assert refused["applied_at"] is None
    assert refused["applied_by_user_id"] is None

    refused_claim = validate_success(
        api.get_redemption_claim(claim_id, SUPERVISOR_HEADERS)
    )
    assert refused_claim["status"] == ClaimStatus.ADJUDICATED.value
    assert refused_claim["net_payable_cents"] == 336
    refused_vendor = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert refused_vendor["recoupment_balance_cents"] == 0

    applied = validate_success(
        api.apply_adjustment(adjustment["id"], None, SUPERVISOR_TWO_HEADERS)
    )
    assert applied["status"] == AdjustmentStatus.APPLIED.value
    assert applied["applied_by_user_id"] == SUPERVISOR_TWO_HEADERS["X-User-ID"]
    assert applied["applied_at"] == "2026-08-01T00:00:00.000Z"

    adjusted_claim = validate_success(
        api.get_redemption_claim(claim_id, SUPERVISOR_HEADERS)
    )
    assert adjusted_claim["status"] == ClaimStatus.ADJUSTED.value
    assert adjusted_claim["adjudicated_total_cents"] == 336
    assert adjusted_claim["net_payable_cents"] == 252  # 336 - 84 = 252
    paid_vendor = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert paid_vendor["recoupment_balance_cents"] == 84


def test_imposing_disqualification_on_own_case_is_forbidden(api):
    """
    The investigator that opened a sanction case may not impose its disqualification,
    while a supervisor may, running the full disqualification cascade.

    "Likewise, a disqualification may not be imposed by the principal that opened the
    case: if `X-User-ID` equals the case's `opened_by_user_id`, the imposition is
    rejected with the same error."
    "The `base_tier` comes from the violation class: `CLASS_A` is tier 4, `CLASS_B` is
    tier 3, `CLASS_C` is tier 2, and `CLASS_D` is tier 1."
    "The `case_points` come from the **base** tier and never from the effective one: tier
    1 carries 1 point, tier 2 carries 2, tier 3 carries 4, and tier 4 carries 8."
    "The escalation step is the number of escalation thresholds — there are two, at 4
    points and at 8 points — that the snapshot plus this case's own `case_points`
    reaches or exceeds."
    "The `effective_tier` is the base tier plus that escalation step, capped at 4."
    "`disqualification_months` is 0 at tier 1, 6 at tier 2, 12 at tier 3, and 36 at tier
    4 — a tier-1 case therefore carries no disqualification at all."
    "The `cmp_amount_cents` is the vendor's `avg_monthly_redemption_cents` multiplied by
    the tier's monthly multiplier — 0.05 at tier 1, 0.10 at tier 2, 0.25 at tier 3, and
    0.50 at tier 4 — multiplied again by the tier's month count — 1 month at tier 1, 3
    at tier 2, 6 at tier 3, and 12 at tier 4 — then rounded half up to a whole cent, and
    finally capped: the penalty is the lesser of that rounded figure and 5,625,000 cents,
    which is the statutory ceiling of fifty-six thousand two hundred fifty dollars."
    "If no such claim exists, `avg_monthly_redemption_cents` falls back to the vendor's
    self-reported `reported_monthly_redemption_cents`."
    "The transition `OPENED → NOTICE_SERVED` stamps `notice_served_at` from the logical
    clock and sets `response_due_at` to fifteen days later — that is the election
    deadline."
    "`disqualified_until` is set to the logical clock plus `disqualification_months`
    calendar months."
    "`sanction_points` rises by the case's `case_points`."
    "The vendor's peer group has its `member_count` decremented by one and its `version`
    incremented by one."

    Design: Corner/rbac/imposing_disqualification_on_own_case_is_forbidden
    """
    bundle = fixtures.published_ceiling_setup(api)
    vendor_id = bundle["vendor"]["id"]
    vendor = fixtures.get_vendor(api, vendor_id)
    opened = fixtures.open_sanction_case(
        api, vendor_id, vendor["version"], headers=INVESTIGATOR_HEADERS
    )

    assert opened["base_tier"] == 2  # CLASS_C
    assert opened["case_points"] == 2  # base tier 2 carries 2 points
    assert opened["cumulative_points_at_open"] == 0
    # 0 + 2 clears neither the 4-point nor the 8-point threshold, so no escalation.
    assert opened["effective_tier"] == 2
    assert opened["disqualification_months"] == 6
    assert opened["cmp_permitted"] is True
    # 6000000 x 0.10 x 3 months = 1800000, well under the 5625000 statutory cap.
    assert opened["cmp_amount_cents"] == 1_800_000
    assert opened["opened_by_user_id"] == INVESTIGATOR_HEADERS["X-User-ID"]

    served = fixtures.serve_notice(api, opened["id"], headers=INVESTIGATOR_HEADERS)
    assert served["status"] == SanctionStatus.NOTICE_SERVED.value
    assert served["response_due_at"] == "2026-08-16T00:00:00.000Z"

    fixtures.set_clock(api, "2026-08-17T00:00:00Z")

    validate_error(
        api.impose_disqualification(opened["id"], None, INVESTIGATOR_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
    )

    refused_case = validate_success(
        api.get_sanction_case(opened["id"], SUPERVISOR_HEADERS)
    )
    assert refused_case["status"] == SanctionStatus.NOTICE_SERVED.value
    refused_vendor = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert refused_vendor["authorization_status"] == VendorStatus.AUTHORIZED.value
    assert refused_vendor["disqualified_until"] is None

    imposed = validate_success(
        api.impose_disqualification(opened["id"], None, SUPERVISOR_TWO_HEADERS)
    )
    assert imposed["status"] == SanctionStatus.DISQUALIFICATION_IMPOSED.value
    assert imposed["resolution"] == SanctionResolution.DISQUALIFICATION.value

    disqualified = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert disqualified["authorization_status"] == VendorStatus.DISQUALIFIED.value
    # 2026-08-17 plus six calendar months lands on the same day-of-month in February.
    assert disqualified["disqualified_until"] == "2027-02-17T00:00:00.000Z"
    assert disqualified["sanction_points"] == 2

    peer_group = validate_success(
        api.get_peer_group(bundle["peer_group"]["id"], SUPERVISOR_HEADERS)
    )
    assert peer_group["member_count"] == 0


def test_vendor_operator_cannot_list_all_vendors(api):
    """
    The vendor collection endpoint is closed to a VendorOperator outright, while the
    published ceiling catalogue and the operator's own vendor record stay readable.

    "| GET | `/vendors` | List vendors, filterable by peer group, authorization status
    and risk tier | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator |"
    "| GET | `/price-ceilings` | List maximum allowable reimbursement rows, filterable by
    peer group, item, cycle and status | VendorUnitAnalyst, VendorUnitSupervisor,
    ComplianceInvestigator, VendorOperator |"
    "| GET | `/vendors/{id}` | Read one vendor with its computed authorization, training,
    risk and money fields | VendorUnitAnalyst, VendorUnitSupervisor,
    ComplianceInvestigator, VendorOperator |"
    "If both headers are well-formed but the declared role is not among the roles
    authorized for the addressed endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    "Reads of shared reference data — food categories, authorized food list items, price
    cycles, and price ceilings — are not vendor-scoped."

    Design: Corner/rbac/vendor_operator_cannot_list_all_vendors
    """
    fixtures.bootstrap_catalogue(api)
    vendor = fixtures.create_vendor(api)
    operator_headers = make_vendor_operator_headers(vendor["id"])

    # The refusal comes before any scoping could filter the collection down to one row.
    validate_error(
        api.list_vendors(operator_headers), ApiErrorId.FORBIDDEN_ROLE.value
    )

    _, ceiling_meta = validate_paginated(api.list_price_ceilings(operator_headers))
    # No cycle has been closed or published, so no ceiling row exists yet.
    assert ceiling_meta["total_count"] == 0

    investigator_rows, investigator_meta = validate_paginated(
        api.list_vendors(INVESTIGATOR_HEADERS)
    )
    assert investigator_meta["total_count"] == 1
    assert [row["id"] for row in investigator_rows] == [vendor["id"]]

    own_record = validate_success(api.get_vendor(vendor["id"], operator_headers))
    assert own_record["id"] == vendor["id"]


def test_vendor_operator_acting_for_another_vendor_is_forbidden(api):
    """
    A VendorOperator addressing another vendor's resources is refused on scope grounds,
    ahead of the body foreign-key sweep, while its own record stays readable.

    "When `X-User-Role` is `VendorOperator`, `X-User-ID` is the `id` of the acting
    Vendor; ownership checks on any resource that references a Vendor compare that
    resource's vendor foreign key to `X-User-ID`."
    "Concretely, a `VendorOperator` addressing a Vendor, PriceSubmission,
    RedemptionClaim, ClaimLine, or SanctionCase must be the vendor those resources belong
    to, and when a request body carries a `vendor_id` it must equal `X-User-ID`."
    "A mismatch is rejected with `ERR_VENDOR_SCOPE_VIOLATION` (HTTP 403)."
    "When a request violates more than one rule, exactly one error is returned: the one
    belonging to the lowest-numbered rule in the ladder below."
    "For any endpoint whose role list includes `VendorOperator`, the vendor scope check
    of §2.1 — otherwise `ERR_VENDOR_SCOPE_VIOLATION`."
    "The same 404 family applies — an unresolvable `food_item_id` yields
    `ERR_FOOD_ITEM_NOT_FOUND`, an unresolvable `vendor_id` yields `ERR_VENDOR_NOT_FOUND`,
    an unresolvable `source_visit_id` yields `ERR_VISIT_NOT_FOUND`, an unresolvable
    `redemption_claim_id` yields `ERR_CLAIM_NOT_FOUND`, an unresolvable
    `food_category_id` yields `ERR_FOOD_CATEGORY_NOT_FOUND`, and an unresolvable
    `price_cycle_id` yields `ERR_PRICE_CYCLE_NOT_FOUND`."

    Design: Corner/errors/vendor_operator_acting_for_another_vendor_is_forbidden
    """
    category = fixtures.create_food_category(api)
    item = fixtures.create_food_item(api, category["id"])
    cycle = fixtures.create_price_cycle(api)
    vendor_one = fixtures.create_vendor(api, store_name="Alpha Market")
    vendor_two = fixtures.create_vendor(
        api, store_name="Bravo Market", reported_monthly_redemption_cents=7_000_000
    )
    operator_one_headers = make_vendor_operator_headers(vendor_one["id"])

    validate_error(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor_two["id"], item["id"], cycle["id"], 320
            ),
            operator_one_headers,
        ),
        ApiErrorId.VENDOR_SCOPE_VIOLATION.value,
    )

    # Rule 3 precedes the body foreign-key sweep of rule 6, so the unresolvable
    # food_item_id never gets the chance to produce ERR_FOOD_ITEM_NOT_FOUND.
    validate_error(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor_two["id"], NON_EXISTENT_UUID, cycle["id"], 320
            ),
            operator_one_headers,
        ),
        ApiErrorId.VENDOR_SCOPE_VIOLATION.value,
    )

    # The rule guards the addressed resource, not only request bodies.
    validate_error(
        api.get_vendor(vendor_two["id"], operator_one_headers),
        ApiErrorId.VENDOR_SCOPE_VIOLATION.value,
    )

    own_record = validate_success(
        api.get_vendor(vendor_one["id"], operator_one_headers)
    )
    assert own_record["id"] == vendor_one["id"]

    _, meta = validate_paginated(
        api.list_price_submissions(ANALYST_HEADERS, {"vendor_id": vendor_two["id"]})
    )
    assert meta["total_count"] == 0


def test_missing_or_unknown_role_header_returns_unauthenticated(api):
    """
    An absent identity header or an undeclared role name fails authentication, while a
    declared role that is simply off the endpoint's list fails authorization.

    "Every request must carry two headers: `X-User-ID`, identifying the acting principal,
    and `X-User-Role`, declaring the capacity in which it acts."
    "If either header is absent, or if `X-User-Role` is not one of the five declared role
    names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    "The five roles are `VendorOperator`, `VendorUnitAnalyst`, `VendorUnitSupervisor`,
    `ComplianceInvestigator`, and `SystemOperator`."
    "Headers present and `X-User-Role` recognized — otherwise `ERR_UNAUTHENTICATED`."
    "The acting role appears in the addressed endpoint's role list — otherwise
    `ERR_FORBIDDEN_ROLE`."
    "A `SystemOperator` drives the logical clock and the periodic risk run and does
    nothing else."
    "| GET | `/vendors/{id}` | Read one vendor with its computed authorization, training,
    risk and money fields | VendorUnitAnalyst, VendorUnitSupervisor,
    ComplianceInvestigator, VendorOperator |"

    Design: Corner/errors/missing_or_unknown_role_header_returns_unauthenticated
    """
    vendor = fixtures.create_vendor(api)

    # No X-User-Role header at all.
    validate_error(
        api.get_vendor(vendor["id"], make_partial_headers(user_id=ANALYST_HEADERS["X-User-ID"])),
        ApiErrorId.UNAUTHENTICATED.value,
    )

    # X-User-Role present, X-User-ID absent.
    validate_error(
        api.get_vendor(
            vendor["id"],
            make_partial_headers(role=Role.VENDOR_UNIT_ANALYST.value),
        ),
        ApiErrorId.UNAUTHENTICATED.value,
    )

    # A syntactically fine role name that is not one of the five declared roles.
    validate_error(
        api.get_vendor(vendor["id"], make_headers("auditor-001", "PublicAuditor")),
        ApiErrorId.UNAUTHENTICATED.value,
    )

    # A declared role, absent from this endpoint's role list, reaches rule 2 instead.
    validate_error(
        api.get_vendor(vendor["id"], SYSTEM_HEADERS),
        ApiErrorId.FORBIDDEN_ROLE.value,
    )

    readable = validate_success(api.get_vendor(vendor["id"], ANALYST_HEADERS))
    assert readable["id"] == vendor["id"]
