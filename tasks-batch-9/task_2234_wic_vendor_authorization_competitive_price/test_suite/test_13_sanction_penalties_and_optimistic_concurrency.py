"""
Civil money penalties, election-window boundaries, parent-version guards, and the
risk score at its tier boundary.

Each test builds its own world through the documented endpoints against an empty
database, and moves the logical clock explicitly whenever a different instant matters.
"""

from test_helpers import (
    ANALYST_HEADERS,
    INVESTIGATOR_HEADERS,
    SUPERVISOR_HEADERS,
    SUPERVISOR_TWO_HEADERS,
    SYSTEM_HEADERS,
    AdjustmentStatus,
    ApiErrorId,
    ClaimStatus,
    EditCode,
    EditResult,
    RiskBasis,
    RiskFlag,
    RiskTier,
    SanctionResolution,
    SanctionStatus,
    VendorStatus,
    ViolationCode,
    VisitOutcome,
    VisitStatus,
    assert_risk_score_components,
    assert_sanction_schedule,
    assert_version_incremented,
    factories,
    fixtures,
    make_vendor_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# A UPC that resolves to no authorized food item, so its claim line is rejected by E01.
UNKNOWN_UPC = "00099988877"


def test_close_cmp_case_with_payment_one_cent_short_rejected(api):
    """
    A civil money penalty case closes only once the payment reaches the penalty in
    full, and the case's points land at closure rather than at election.

    "The `base_tier` comes from the violation class: `CLASS_A` is tier 4, `CLASS_B` is
    tier 3, `CLASS_C` is tier 2, and `CLASS_D` is tier 1."
    "The `case_points` come from the **base** tier and never from the effective one: tier
    1 carries 1 point, tier 2 carries 2, tier 3 carries 4, and tier 4 carries 8."
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
    "The new case begins in `status` `OPENED` with `resolution` `NONE`, `cmp_paid_cents`
    0, and `notice_served_at`, `response_due_at`, and `dismissal_reason` null."
    "Electing the penalty leaves the vendor's `authorization_status` untouched and its
    peer group `member_count` unchanged: the store keeps operating and owes
    `cmp_amount_cents`."
    "No sanction points are added at election."
    "Closing from `CMP_ELECTED` carries a `cmp_payment_cents` in the body, and the case
    may only close when `cmp_paid_cents` plus that payment reaches or exceeds
    `cmp_amount_cents`; a short payment is refused with `ERR_CMP_UNDERPAID`, while an
    exact or over-payment closes the case."
    "On success `cmp_paid_cents` is increased by `cmp_payment_cents` and the vendor's
    `sanction_points` rises by the case's `case_points` — the penalty branch adds its
    points only at closure."

    Design: Corner/errors/close_cmp_case_with_payment_one_cent_short_rejected
    """
    bundle = fixtures.published_ceiling_setup(api)
    vendor_id = bundle["vendor"]["id"]
    vendor = fixtures.get_vendor(api, vendor_id)
    opened = fixtures.open_sanction_case(
        api,
        vendor_id,
        vendor["version"],
        violation_code=ViolationCode.CLASS_D.value,
    )

    # No claim has ever been adjudicated, so the penalty base is the reported figure of
    # 6,000,000 cents: 6000000 x 0.05 x 1 month = 300000, far below the cap.
    assert_sanction_schedule(
        opened,
        base_tier=1,
        case_points=1,
        cumulative_points_at_open=0,
        effective_tier=1,
        disqualification_months=0,
        cmp_permitted=True,
        cmp_amount_cents=300_000,
    )
    assert opened["status"] == SanctionStatus.OPENED.value
    assert opened["resolution"] == SanctionResolution.NONE.value
    assert opened["cmp_paid_cents"] == 0

    served = fixtures.serve_notice(api, opened["id"])
    assert served["response_due_at"] == "2026-08-16T00:00:00.000Z"

    elected = fixtures.elect_cmp(api, opened["id"], vendor_id)
    assert elected["status"] == SanctionStatus.CMP_ELECTED.value
    assert elected["resolution"] == SanctionResolution.CMP.value

    after_election = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert after_election["authorization_status"] == VendorStatus.AUTHORIZED.value
    assert after_election["sanction_points"] == 0

    # One cent short of the penalty: 300000 - 1 = 299999.
    validate_error(
        api.close_sanction_case(
            opened["id"], factories.cmp_close_payload(299_999), SUPERVISOR_HEADERS
        ),
        ApiErrorId.CMP_UNDERPAID.value,
    )

    refused = validate_success(api.get_sanction_case(opened["id"], SUPERVISOR_HEADERS))
    assert refused["status"] == SanctionStatus.CMP_ELECTED.value
    assert refused["cmp_paid_cents"] == 0
    still_clean = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert still_clean["sanction_points"] == 0

    closed = validate_success(
        api.close_sanction_case(
            opened["id"], factories.cmp_close_payload(300_000), SUPERVISOR_HEADERS
        )
    )
    assert closed["status"] == SanctionStatus.CLOSED.value
    assert closed["cmp_paid_cents"] == 300_000
    assert closed["resolution"] == SanctionResolution.CMP.value

    settled = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert settled["sanction_points"] == 1
    assert settled["authorization_status"] == VendorStatus.AUTHORIZED.value
    assert settled["disqualified_until"] is None


def test_elect_cmp_on_class_a_case_rejected_as_not_permitted(api):
    """
    The gravest violation class may never be settled by money, and its notice suspends
    the store before the immediate disqualification runs.

    "`cmp_permitted` is true for every violation class except `CLASS_A`, which may never
    be settled by money."
    "The `case_points` come from the **base** tier and never from the effective one: tier
    1 carries 1 point, tier 2 carries 2, tier 3 carries 4, and tier 4 carries 8."
    "The escalation step is the number of escalation thresholds — there are two, at 4
    points and at 8 points — that the snapshot plus this case's own `case_points`
    reaches or exceeds."
    "The `effective_tier` is the base tier plus that escalation step, capped at 4."
    "If the case's `base_tier` is exactly 4, serving the notice also moves an
    `AUTHORIZED` vendor `AUTHORIZED → SUSPENDED`; the suspension is a precaution, not a
    penalty, and because a suspended vendor remains a peer group member, `member_count`
    is unchanged."
    "The case must be `NOTICE_SERVED`, or `ERR_INVALID_SANCTION_STATE`; `cmp_permitted`
    must be true, or the election is refused with `ERR_CMP_NOT_PERMITTED`; and the
    logical clock must be at or before `response_due_at`, with a clock exactly equal to
    the deadline still qualifying, or the election is refused with
    `ERR_CMP_ELECTION_WINDOW_EXPIRED`."
    "The election window must have closed — the logical clock strictly past
    `response_due_at` — unless the `violation_code` is `CLASS_A`, for which no election
    was ever available and imposition is immediate; a premature imposition on a
    non-`CLASS_A` case is refused with `ERR_ELECTION_WINDOW_OPEN`."
    "`disqualified_until` is set to the logical clock plus `disqualification_months`
    calendar months."
    "The vendor's peer group has its `member_count` decremented by one and its `version`
    incremented by one."

    Design: Corner/errors/elect_cmp_on_class_a_case_rejected_as_not_permitted
    """
    bundle = fixtures.served_case_setup(
        api, violation_code=ViolationCode.CLASS_A.value
    )
    case = bundle["case"]
    vendor_id = bundle["vendor"]["id"]

    # 0 + 8 points clears both the 4-point and the 8-point threshold, so the escalation
    # step is 2 and the effective tier is 4 + 2 capped back to 4. The uncapped penalty
    # would be 6000000 x 0.50 x 12 = 36000000, so the 5625000 ceiling binds.
    assert_sanction_schedule(
        case,
        base_tier=4,
        case_points=8,
        cumulative_points_at_open=0,
        effective_tier=4,
        disqualification_months=36,
        cmp_permitted=False,
        cmp_amount_cents=5_625_000,
    )
    assert case["status"] == SanctionStatus.NOTICE_SERVED.value

    suspended = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert suspended["authorization_status"] == VendorStatus.SUSPENDED.value
    peer_group = validate_success(
        api.get_peer_group(bundle["peer_group"]["id"], SUPERVISOR_HEADERS)
    )
    assert peer_group["member_count"] == 1

    validate_error(
        api.elect_cmp(case["id"], None, make_vendor_operator_headers(vendor_id)),
        ApiErrorId.CMP_NOT_PERMITTED.value,
    )

    refused = validate_success(api.get_sanction_case(case["id"], SUPERVISOR_HEADERS))
    assert refused["status"] == SanctionStatus.NOTICE_SERVED.value
    assert refused["resolution"] == SanctionResolution.NONE.value

    # The clock is still at 2026-08-01T00:00:00Z, well inside what would be an election
    # window, but CLASS_A never had one, so the imposition is immediate.
    imposed = validate_success(
        api.impose_disqualification(case["id"], None, SUPERVISOR_TWO_HEADERS)
    )
    assert imposed["status"] == SanctionStatus.DISQUALIFICATION_IMPOSED.value
    assert imposed["resolution"] == SanctionResolution.DISQUALIFICATION.value

    disqualified = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert disqualified["authorization_status"] == VendorStatus.DISQUALIFIED.value
    # 2026-08-01 plus 36 calendar months is 2029-08-01.
    assert disqualified["disqualified_until"] == "2029-08-01T00:00:00.000Z"
    assert disqualified["sanction_points"] == 8

    emptied = validate_success(
        api.get_peer_group(bundle["peer_group"]["id"], SUPERVISOR_HEADERS)
    )
    assert emptied["member_count"] == 0


def test_election_window_transitions_rejected_at_each_boundary(api):
    """
    The fifteen-day election deadline is inclusive at its last instant, and either side
    of it exactly one of election and imposition is available.

    "The transition `OPENED → NOTICE_SERVED` stamps `notice_served_at` from the logical
    clock and sets `response_due_at` to fifteen days later — that is the election
    deadline."
    "The election window must have closed — the logical clock strictly past
    `response_due_at` — unless the `violation_code` is `CLASS_A`, for which no election
    was ever available and imposition is immediate; a premature imposition on a
    non-`CLASS_A` case is refused with `ERR_ELECTION_WINDOW_OPEN`."
    "The case must be `NOTICE_SERVED`, or `ERR_INVALID_SANCTION_STATE`; `cmp_permitted`
    must be true, or the election is refused with `ERR_CMP_NOT_PERMITTED`; and the
    logical clock must be at or before `response_due_at`, with a clock exactly equal to
    the deadline still qualifying, or the election is refused with
    `ERR_CMP_ELECTION_WINDOW_EXPIRED`."
    "And `disqualification_months` must be greater than zero, or the imposition is
    refused with `ERR_DISQUALIFICATION_NOT_AVAILABLE`, which is what a tier-1 case always
    yields."
    "`disqualification_months` is 0 at tier 1, 6 at tier 2, 12 at tier 3, and 36 at tier
    4 — a tier-1 case therefore carries no disqualification at all."
    "27. On `POST /sanction-cases/{id}/impose-disqualification`, the election window has
    closed or the violation is `CLASS_A` — otherwise `ERR_ELECTION_WINDOW_OPEN`."
    "28. On `POST /sanction-cases/{id}/impose-disqualification`,
    `disqualification_months` is greater than zero — otherwise
    `ERR_DISQUALIFICATION_NOT_AVAILABLE`."
    "Electing the penalty leaves the vendor's `authorization_status` untouched and its
    peer group `member_count` unchanged: the store keeps operating and owes
    `cmp_amount_cents`."

    Design: Corner/errors/election_window_transitions_rejected_at_each_boundary
    """
    bundle = fixtures.served_case_setup(
        api, violation_code=ViolationCode.CLASS_D.value
    )
    case = bundle["case"]
    vendor_id = bundle["vendor"]["id"]
    operator_headers = make_vendor_operator_headers(vendor_id)

    assert case["notice_served_at"] == "2026-08-01T00:00:00.000Z"
    # 2026-08-01 plus fifteen 24-hour days is 2026-08-16.
    assert case["response_due_at"] == "2026-08-16T00:00:00.000Z"
    assert case["disqualification_months"] == 0  # tier 1 carries no disqualification

    # Inside the window, rule 27 decides before the tier-1 rule 28 ever gets a look in.
    validate_error(
        api.impose_disqualification(case["id"], None, SUPERVISOR_TWO_HEADERS),
        ApiErrorId.ELECTION_WINDOW_OPEN.value,
    )

    # One millisecond past the deadline the window is strictly closed.
    fixtures.set_clock(api, "2026-08-16T00:00:00.001Z")

    validate_error(
        api.elect_cmp(case["id"], None, operator_headers),
        ApiErrorId.CMP_ELECTION_WINDOW_EXPIRED.value,
    )
    # With the window closed, rule 28 is now the one that bites on a tier-1 case.
    validate_error(
        api.impose_disqualification(case["id"], None, SUPERVISOR_TWO_HEADERS),
        ApiErrorId.DISQUALIFICATION_NOT_AVAILABLE.value,
    )

    stuck = validate_success(api.get_sanction_case(case["id"], SUPERVISOR_HEADERS))
    assert stuck["status"] == SanctionStatus.NOTICE_SERVED.value
    assert stuck["resolution"] == SanctionResolution.NONE.value

    # Rewound to the deadline exactly, which still qualifies for the election.
    fixtures.set_clock(api, "2026-08-16T00:00:00.000Z")

    elected = validate_success(api.elect_cmp(case["id"], None, operator_headers))
    assert elected["status"] == SanctionStatus.CMP_ELECTED.value
    assert elected["resolution"] == SanctionResolution.CMP.value

    untouched = validate_success(api.get_vendor(vendor_id, SUPERVISOR_HEADERS))
    assert untouched["authorization_status"] == VendorStatus.AUTHORIZED.value
    assert untouched["sanction_points"] == 0
    assert untouched["disqualified_until"] is None


def test_stale_expected_claim_version_on_adjustment_create_returns_precondition_failed(api):
    """
    An adjustment raised against a claim version the adjudication has already replaced
    is refused, and the accepted retry itself moves the claim's version on.

    "Raising a reimbursement adjustment against a redemption claim requires
    `expected_claim_version` in the body of a `POST /reimbursement-adjustments` request,
    carrying the `version` the client last observed on that RedemptionClaim."
    "If it does not equal the claim's current `version`, the create is rejected with
    `ERR_STALE_CLAIM_VERSION` (HTTP 412)."
    "Note that a successful create itself increments the claim's `version` by one, so a
    client raising two adjustments in sequence must re-read the claim between them."
    "`version` (integer): a counter that increments by one on every mutation of the row."
    "Those lines are ordered by ascending `line_number`, and for each one the server
    records an entry in `line_recoupments` holding the `claim_line_id`, that line's
    `allowed_cents`, and a `recoupment_cents` equal to the line's `allowed_cents`
    multiplied by the `recoupment_rate`, rounded half up to a whole cent."
    "The adjustment begins in `status` `PENDING` with `created_by_user_id` stamped from
    the acting `X-User-ID` and with `applied_by_user_id`, `applied_at`, `reversed_at`,
    and `reversal_reason` all null."
    "`net_payable_cents` is that total less the sum of `recoupment_cents` over the
    claim's reimbursement adjustments whose `status` is `APPLIED` — normally zero at
    first adjudication."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_claim_version_on_adjustment_create_returns_precondition_failed
    """
    bundle = fixtures.published_ceiling_setup(api)
    filed = fixtures.file_claim(
        api,
        bundle["vendor"]["id"],
        [factories.claim_line_payload(1, fixtures.MILK_UPC, 1, 336)],
    )
    version_at_filing = filed["version"]

    adjudicated = fixtures.adjudicate(api, filed["id"])
    assert_version_incremented(adjudicated["version"], version_at_filing)
    current_version = adjudicated["version"]
    assert adjudicated["status"] == ClaimStatus.ADJUDICATED.value
    assert adjudicated["adjudicated_total_cents"] == 336
    assert adjudicated["net_payable_cents"] == 336

    validate_error(
        api.create_reimbursement_adjustment(
            factories.reimbursement_adjustment_payload(
                filed["id"], version_at_filing, recoupment_rate=0.10
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.STALE_CLAIM_VERSION.value,
    )

    _, meta = validate_paginated(
        api.list_reimbursement_adjustments(
            ANALYST_HEADERS, {"redemption_claim_id": filed["id"]}
        )
    )
    assert meta["total_count"] == 0
    unchanged = validate_success(api.get_redemption_claim(filed["id"], ANALYST_HEADERS))
    assert unchanged["version"] == current_version

    accepted = validate_success(
        api.create_reimbursement_adjustment(
            factories.reimbursement_adjustment_payload(
                filed["id"], current_version, recoupment_rate=0.10
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )
    # The single accepted line allows 336 cents: 336 x 0.10 = 33.6 -> 34 half up.
    assert accepted["recoupment_cents"] == 34
    assert accepted["status"] == AdjustmentStatus.PENDING.value
    assert accepted["applied_at"] is None

    after_create = validate_success(
        api.get_redemption_claim(filed["id"], ANALYST_HEADERS)
    )
    assert after_create["version"] == current_version + 1
    # Nothing has been applied yet, so the money on the claim has not moved.
    assert after_create["status"] == ClaimStatus.ADJUDICATED.value
    assert after_create["net_payable_cents"] == 336


def test_stale_expected_vendor_version_on_sanction_case_open_returns_precondition_failed(api):
    """
    A sanction case opened from a vendor view that authorization has since superseded is
    refused, and the accepted retry itself moves the vendor's version on.

    "Opening a sanction case against a vendor requires `expected_vendor_version` in the
    body of a `POST /sanction-cases` request, carrying the `version` the client last
    observed on that Vendor."
    "If it does not equal the vendor's current `version`, the create is rejected with
    `ERR_STALE_VENDOR_VERSION` (HTTP 412)."
    "A successful create increments the vendor's `version` by one."
    "`version` (integer): a counter that increments by one on every mutation of the row."
    "Derived and denormalized fields are not exempt: recomputing `price_submission_complete`,
    `risk_score`, or `recoupment_balance_cents` on a Vendor is a mutation of the Vendor."
    "The new case begins in `status` `OPENED` with `resolution` `NONE`, `cmp_paid_cents`
    0, and `notice_served_at`, `response_due_at`, and `dismissal_reason` null."
    "`opened_by_user_id` is stamped from the acting `X-User-ID`."
    "The `base_tier` comes from the violation class: `CLASS_A` is tier 4, `CLASS_B` is
    tier 3, `CLASS_C` is tier 2, and `CLASS_D` is tier 1."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_vendor_version_on_sanction_case_open_returns_precondition_failed
    """
    catalogue = fixtures.bootstrap_catalogue(api)
    in_review = fixtures.vendor_in_review(api)
    stale_version = in_review["version"]

    submission = fixtures.submit_price(
        api,
        in_review["id"],
        catalogue["milk_item"]["id"],
        catalogue["cycle"]["id"],
        320,
    )
    fixtures.accept_submission(api, submission["id"])
    authorized = fixtures.authorize_vendor(api, in_review["id"])
    fresh_version = authorized["version"]
    # Accepting the price recomputed price_submission_complete and authorizing recomputed
    # the redemption average, and each such recomputation is a mutation of the vendor.
    assert_version_incremented(fresh_version, stale_version)

    validate_error(
        api.create_sanction_case(
            factories.sanction_case_payload(
                in_review["id"],
                stale_version,
                violation_code=ViolationCode.CLASS_C.value,
            ),
            INVESTIGATOR_HEADERS,
        ),
        ApiErrorId.STALE_VENDOR_VERSION.value,
    )

    _, meta = validate_paginated(
        api.list_sanction_cases(
            INVESTIGATOR_HEADERS, {"vendor_id": in_review["id"]}
        )
    )
    assert meta["total_count"] == 0
    unchanged = validate_success(api.get_vendor(in_review["id"], INVESTIGATOR_HEADERS))
    assert unchanged["version"] == fresh_version

    opened = validate_success(
        api.create_sanction_case(
            factories.sanction_case_payload(
                in_review["id"],
                fresh_version,
                violation_code=ViolationCode.CLASS_C.value,
            ),
            INVESTIGATOR_HEADERS,
        ),
        expected_status=201,
    )
    assert opened["status"] == SanctionStatus.OPENED.value
    assert opened["opened_by_user_id"] == INVESTIGATOR_HEADERS["X-User-ID"]
    assert opened["base_tier"] == 2  # CLASS_C
    assert opened["resolution"] == SanctionResolution.NONE.value
    assert opened["cmp_paid_cents"] == 0
    assert opened["notice_served_at"] is None
    assert opened["response_due_at"] is None
    assert opened["dismissal_reason"] is None

    after_create = validate_success(
        api.get_vendor(in_review["id"], INVESTIGATOR_HEADERS)
    )
    assert after_create["version"] == fresh_version + 1


def test_risk_run_at_exactly_sixty_flips_vendor_to_high_tier(api):
    """
    A score of exactly 60.0 lands in the top tier, and the risk run that computes it
    flags the vendor and requires a compliance buy.

    "From those lines, `edit_rejection_rate_pct` is 100 multiplied by the number of lines
    whose `edit_result` is `REJECTED` divided by the total number of lines considered,
    and `price_excess_pct` is 100 multiplied by the number of lines whose `edit_code` is
    `E05` divided by that same total; when no lines fall in the window, both figures are
    0."
    "The visits considered are the vendor's MonitoringVisits whose `status` is `PASSED`,
    `FAILED`, `CURED`, or `ESCALATED` and whose `conducted_at` falls in the same window,
    and `failed_visit_pct` is 100 multiplied by the number of those whose `status` is
    `FAILED` or `ESCALATED` divided by the number considered; with no visits in the
    window the figure is 0."
    "The weighted sum takes 0.40 of `edit_rejection_rate_pct`, plus 0.25 of
    `price_excess_pct`, plus 0.20 of `failed_visit_pct`, plus 15.0 for each of the
    vendor's `sanction_points` counted up to a cap of two points — so a vendor with three
    or more points contributes exactly 30.0 from that term, and a vendor with one point
    contributes 15.0."
    "Both boundaries are inclusive at the bottom, so a score of exactly 60.0 is `HIGH`
    and exactly 30.0 is `ELEVATED`."
    "It walks every non-terminal vendor in ascending `created_at` order, refreshing each
    vendor's `risk_score`, `risk_tier`, and `risk_epoch_at` from the epoch variant."
    "A vendor whose refreshed `risk_tier` comes out `HIGH` has its `risk_flag` set to
    `HIGH_SCORE` and its `compliance_buy_required` set to true — the second,
    score-driven route to a compliance buy alongside the finding-count route of §3.6."
    "The run reports the `epoch_at` instant it used, the `evaluated_vendor_count`, the
    `high_risk_vendor_count`, the `escalated_visit_count`, and the
    `opened_sanction_case_count`."
    "**Hop 1** always runs: `conducted_at`, the `outcome`, the `stock_findings` verdicts,
    `stock_compliance_pct`, and `overcharge_cents` are stamped; the vendor's
    `open_finding_count` rises by one; and the vendor's `cure_deadline_at` is set to
    thirty days after the logical clock, opening the cure window."
    "The first failing visit of an otherwise clean vendor therefore stops after hop 1:
    one finding is recorded, a cure deadline is set, and nothing else moves."
    "**`E01`** — the UPC did not resolve to any authorized food item, or the resolved
    item's `status` is `DELISTED`. The line's `edit_result` becomes `REJECTED` and its
    `allowed_cents` is 0."
    "Every other computed field starts at its documented baseline:
    `reauth_completed_count`, `accepted_submission_count`, `open_finding_count`,
    `recoupment_balance_cents`, `avg_monthly_redemption_cents`, and `sanction_points` at
    0; `price_submission_complete` and `compliance_buy_required` and
    `reauthorization_hold` false; `risk_flag` `NONE`; and `authorized_at`,
    `reauthorization_due_at`, `training_type`, `training_completed_at`,
    `training_expires_at`, `cure_deadline_at`, `risk_epoch_at`, `reauth_blocked_reason`,
    `authorization_blocked_reason`, `disqualified_until`, and `denial_reason` all null."

    Design: Corner/cross_cutting_complexity_layers/risk_run_at_exactly_sixty_flips_vendor_to_high_tier
    """
    bundle = fixtures.published_ceiling_setup(api)
    vendor_id = bundle["vendor"]["id"]

    fixtures.set_clock(api, "2026-08-10T00:00:00Z")

    # One conducted visit, and it fails for want of any milk observation at all.
    visit = fixtures.schedule_visit(api, vendor_id, "2026-08-11T00:00:00Z")
    conducted = fixtures.conduct_visit(api, visit["id"])
    assert conducted["status"] == VisitStatus.FAILED.value
    assert conducted["outcome"] == VisitOutcome.FAIL_MISSING_CATEGORY.value

    # One adjudicated claim line, and it is rejected because its UPC resolves to nothing.
    filed = fixtures.file_claim(
        api, vendor_id, [factories.claim_line_payload(1, UNKNOWN_UPC, 1, 500)]
    )
    fixtures.adjudicate(api, filed["id"])
    lines = fixtures.claim_lines_of(api, filed["id"])
    assert len(lines) == 1
    assert lines[0]["edit_result"] == EditResult.REJECTED.value
    assert lines[0]["edit_code"] == EditCode.E01.value

    before = validate_success(api.get_vendor(vendor_id, ANALYST_HEADERS))
    assert before["risk_score"] == 0.0
    assert before["risk_tier"] == RiskTier.LOW.value
    assert before["risk_epoch_at"] is None
    assert before["risk_flag"] == RiskFlag.NONE.value
    assert before["compliance_buy_required"] is False
    assert before["open_finding_count"] == 1
    # Thirty 24-hour days after 2026-08-10 is 2026-09-09.
    assert before["cure_deadline_at"] == "2026-09-09T00:00:00.000Z"
    assert before["reauthorization_hold"] is False

    summary = validate_success(api.risk_run(None, SYSTEM_HEADERS))
    assert summary["epoch_at"] == "2026-08-10T00:00:00.000Z"
    assert summary["evaluated_vendor_count"] == 1
    assert summary["high_risk_vendor_count"] == 1
    # The cure deadline is still ahead of the clock, so no failed visit escalates.
    assert summary["escalated_visit_count"] == 0
    assert summary["opened_sanction_case_count"] == 0

    after = validate_success(api.get_vendor(vendor_id, ANALYST_HEADERS))
    # 0.40 x 100.0 + 0.25 x 0.0 + 0.20 x 100.0 + 0 points = 60.0, the HIGH boundary.
    assert after["risk_score"] == 60.0
    assert after["risk_tier"] == RiskTier.HIGH.value
    assert after["risk_epoch_at"] == "2026-08-10T00:00:00.000Z"
    assert after["risk_flag"] == RiskFlag.HIGH_SCORE.value
    assert after["compliance_buy_required"] is True
    assert after["open_finding_count"] == 1
    assert after["reauthorization_hold"] is False

    still_failed = validate_success(
        api.get_monitoring_visit(visit["id"], ANALYST_HEADERS)
    )
    assert still_failed["status"] == VisitStatus.FAILED.value

    replay = validate_success(
        api.get_vendor_risk_profile(
            vendor_id, ANALYST_HEADERS, {"basis": RiskBasis.EPOCH.value}
        )
    )
    assert replay["basis"] == RiskBasis.EPOCH.value
    assert replay["window_end"] == "2026-08-10T00:00:00.000Z"
    assert_risk_score_components(
        replay,
        edit_rejection_rate_pct=100.0,
        price_excess_pct=0.0,
        failed_visit_pct=100.0,
        sanction_points=0,
        expected_score=60.0,
        expected_tier=RiskTier.HIGH.value,
    )


def test_risk_profile_computed_read_matches_rolling_calculation(api):
    """
    The rolling risk profile counts records the last risk run never saw, and persists
    nothing, so the stored score keeps lagging by a whole epoch.

    "The **rolling** variant is a computed read available to analysts, supervisors, and
    investigators; a `basis` query parameter of `ROLLING`, or an omitted `basis`,
    evaluates the window against the logical clock at request time, so a claim
    adjudicated one second ago is already counted, and nothing is persisted."
    "The response reports the `vendor_id`, the `basis` used, the `window_start` and
    `window_end` instants, the `evaluated_line_count` and `evaluated_visit_count` that
    fell in the window, the three component percentages `edit_rejection_rate_pct`,
    `price_excess_pct`, and `failed_visit_pct`, the vendor's `sanction_points`, and the
    resulting `risk_score` and `risk_tier`."
    "The score is evaluated over a window ending at a variant-supplied instant and
    beginning 180 days earlier."
    "Records created after that run are invisible to the vendor's stored `risk_score` and
    `risk_tier` until the next run, so the persisted tier — the one that gates
    compliance-buy eligibility — can lag the rolling tier by a whole epoch."
    "The weighted sum takes 0.40 of `edit_rejection_rate_pct`, plus 0.25 of
    `price_excess_pct`, plus 0.20 of `failed_visit_pct`, plus 15.0 for each of the
    vendor's `sanction_points` counted up to a cap of two points — so a vendor with three
    or more points contributes exactly 30.0 from that term, and a vendor with one point
    contributes 15.0."
    "That sum is rounded half up to one decimal place, and the score is the lesser of
    100.0 and that rounded value."
    "The `risk_tier` is then read off the rounded score: `HIGH` when the score is at
    least 60.0, `ELEVATED` when it is at least 30.0 but below 60.0, and `LOW` below
    30.0."
    "Within that window, the claim lines considered are those belonging to the vendor's
    RedemptionClaims whose `status` is `ADJUDICATED`, `ADJUSTED`, or `PAID` and whose
    claim's `adjudicated_at` falls after the window start and at or before the window
    end."
    "It walks every non-terminal vendor in ascending `created_at` order, refreshing each
    vendor's `risk_score`, `risk_tier`, and `risk_epoch_at` from the epoch variant."

    Design: Corner/endpoints/risk_profile_computed_read_matches_rolling_calculation
    """
    bundle = fixtures.published_ceiling_setup(api)
    vendor_id = bundle["vendor"]["id"]

    # A run at 2026-08-01 pins the epoch before any failure or rejection exists.
    epoch_summary = fixtures.run_risk_run(api)
    assert epoch_summary["epoch_at"] == "2026-08-01T00:00:00.000Z"
    assert epoch_summary["high_risk_vendor_count"] == 0

    fixtures.set_clock(api, "2026-08-10T00:00:00Z")

    visit = fixtures.schedule_visit(api, vendor_id, "2026-08-11T00:00:00Z")
    conducted = fixtures.conduct_visit(api, visit["id"])
    assert conducted["status"] == VisitStatus.FAILED.value

    filed = fixtures.file_claim(
        api, vendor_id, [factories.claim_line_payload(1, UNKNOWN_UPC, 1, 500)]
    )
    adjudicated = fixtures.adjudicate(api, filed["id"])
    assert adjudicated["adjudicated_at"] == "2026-08-10T00:00:00.000Z"

    profile = validate_success(api.get_vendor_risk_profile(vendor_id, ANALYST_HEADERS))
    assert profile["vendor_id"] == vendor_id
    # An omitted basis is the rolling one, evaluated against the clock at request time.
    assert profile["basis"] == RiskBasis.ROLLING.value
    assert profile["window_end"] == "2026-08-10T00:00:00.000Z"
    # 180 days before 2026-08-10 is 2026-02-11.
    assert profile["window_start"] == "2026-02-11T00:00:00.000Z"
    assert profile["evaluated_line_count"] == 1
    assert profile["evaluated_visit_count"] == 1
    assert_risk_score_components(
        profile,
        edit_rejection_rate_pct=100.0,
        price_excess_pct=0.0,
        failed_visit_pct=100.0,
        sanction_points=0,
        expected_score=60.0,
        expected_tier=RiskTier.HIGH.value,
    )

    # Nothing was persisted: the stored figures still belong to the earlier epoch.
    stored = validate_success(api.get_vendor(vendor_id, ANALYST_HEADERS))
    assert stored["risk_score"] == 0.0
    assert stored["risk_tier"] == RiskTier.LOW.value
    assert stored["risk_epoch_at"] == "2026-08-01T00:00:00.000Z"
    assert stored["risk_flag"] == RiskFlag.NONE.value
    assert stored["compliance_buy_required"] is False
