"""Endpoint envelopes, error-code triggers, RBAC, and optimistic concurrency.

Covers corner queue (B) sections: endpoints, errors, rbac,
cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_taxpayer_headers,
    make_hearing_officer_headers,
    create_owner,
    create_open_roll,
    create_parcel,
    create_assessment,
    claim_exemption,
    setup_certified_parcel,
    setup_final_assessment,
    setup_draft_assessment,
    setup_filed_appeal,
    setup_under_review_appeal,
    setup_deferral_with_accrual,
    setup_deferral_after_payment,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# --- endpoints -------------------------------------------------------------
def test_list_assessments_paginated_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside its `meta` object, where `total_count` is the size of the full filtered set and
    `has_more` is true exactly when records remain beyond the current window."

    Design: Corner/endpoints/list_assessments_paginated_envelope
    """
    owner = create_owner()
    roll = create_open_roll()
    p1 = create_parcel(owner["id"])
    p2 = create_parcel(owner["id"])
    create_assessment(p1["id"], roll["id"], 100000, reassessment_event="NONE")
    create_assessment(p2["id"], roll["id"], 120000, reassessment_event="NONE")
    resp = api.list_assessments(ASSESSOR, params={"tax_roll_id": roll["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1


def test_issue_bill_computed_read_amount(api):
    """PRD §3.8: "(Equivalently, the cents amount is the billed taxable value times the mill
    rate divided by 10, rounded half-up.)"
    PRD §3.8: "A newly issued bill is `ISSUED`, its `is_deferred` flag false."

    Design: Corner/endpoints/issue_bill_computed_read_amount
    """
    # final_taxable_value 100000, mill_rate 10.0 -> round(100000*10/10) = 100000.
    owner, roll, parcel, final = setup_final_assessment(market_value=100000, reassessment_event="SALE")
    bill = validate_success(api.issue_bill(final["id"], ASSESSOR), expected_status=201)
    assert bill["tax_amount_cents"] == 100000
    assert bill["billed_taxable_value"] == 100000
    assert bill["status"] == "ISSUED"


def test_pay_issued_tax_bill_transitions_to_paid(api):
    """PRD §3.8: "A taxpayer (or the assessor on their behalf) may pay an issued bill in full,
    moving it `ISSUED → PAID`".

    Design: Corner/endpoints/pay_issued_tax_bill_transitions_to_paid
    """
    owner, roll, parcel, final = setup_final_assessment(market_value=100000, reassessment_event="SALE")
    bill = validate_success(api.issue_bill(final["id"], ASSESSOR), expected_status=201)
    paid = validate_success(api.pay_tax_bill(bill["id"], make_taxpayer_headers(owner["id"])))
    assert paid["status"] == "PAID"


# --- errors ----------------------------------------------------------------
def test_no_certified_successor_close_rejected(api):
    """PRD §3.1: "Closing a `CERTIFIED` roll is permitted only when a successor roll — one
    whose `prior_roll_id` equals this roll's `id` — already exists and is itself `CERTIFIED`;
    absent such a successor the close is refused with `ERR_NO_CERTIFIED_SUCCESSOR`."

    Design: Corner/errors/no_certified_successor_close_rejected
    """
    roll = create_open_roll()
    validate_success(api.certify_tax_roll(roll["id"], ASSESSOR))  # empty roll certifies
    resp = api.close_tax_roll(roll["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_NO_CERTIFIED_SUCCESSOR)


def test_grant_without_held_hearing_rejected(api):
    """PRD §3.6: "Both grant and deny require that a hearing on this appeal has already been
    held — a hearing in `HELD` status — and either decision attempted without one is refused
    with `ERR_NO_HELD_HEARING`."

    Design: Corner/errors/grant_without_held_hearing_rejected
    """
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    resp = api.grant_appeal(appeal["id"], make_hearing_officer_headers(ho_id))
    validate_error(resp, ApiErrorId.ERR_NO_HELD_HEARING)


def test_owner_not_found_on_record_sale(api):
    """PRD §3.2: "When a property changes hands the assessor records the sale by supplying the
    `new_owner_id` of the buyer, who must already exist as an owner — otherwise the sale is
    refused with `ERR_OWNER_NOT_FOUND`."

    Design: Corner/errors/owner_not_found_on_record_sale
    """
    owner = create_owner()
    parcel = create_parcel(owner["id"])
    resp = api.record_sale(parcel["id"], {"new_owner_id": "00000000-0000-4000-8000-0000000000aa"}, ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_OWNER_NOT_FOUND)


# --- rbac ------------------------------------------------------------------
def test_assessor_cannot_approve_exemption(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.4: "A reviewer — and only a reviewer — then approves or denies each claim".

    Design: Corner/rbac/reviewer_cannot_approve_exemption_via_assessor_only_path
    """
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=100000, reassessment_event="NONE", parcel_overrides={"is_primary_residence": True}
    )
    exm = claim_exemption(asmt["id"], "HOMESTEAD")
    resp = api.approve_exemption(exm["id"], ASSESSOR)  # Assessor on a Reviewer-only path
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_taxpayer_cannot_withdraw_other_owners_appeal(api):
    """PRD §2.1: "Concretely, when a taxpayer submits evidence on or withdraws an appeal,
    their `X-User-ID` must equal that appeal's `filed_by_owner_id`; when a taxpayer pays a
    deferral, their `X-User-ID` must match the relevant `owner_id`."
    PRD §2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/taxpayer_cannot_withdraw_other_owners_appeal
    """
    owner, roll, parcel, asmt, appeal = setup_filed_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    other = create_owner()
    resp = api.withdraw_appeal(appeal["id"], make_taxpayer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


# --- cross_cutting_complexity_layers ---------------------------------------
def test_occ_appeal_stale_assessment_version_412(api):
    """PRD §2.7: "Because filing an appeal drives that assessment from `NOTICED` to
    `UNDER_APPEAL` and advances its `version`, a second filing that still carries the
    previously observed version is working from a stale view and is rejected with
    `ERR_STALE_VERSION` (HTTP 412) before the open-appeal state check is ever reached."

    Design: Corner/cross_cutting_complexity_layers/occ_appeal_stale_assessment_version_412
    """
    owner, roll, parcel, asmt, appeal = setup_filed_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    # asmt["version"] is the NOTICED version observed before the first filing bumped it.
    stale_version = asmt["version"]
    resp = api.create_appeal(
        f.create_appeal_payload(asmt["id"], owner["id"], 70000, stale_version),
        make_taxpayer_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_deferral_payment_stale_version_rejected(api):
    """PRD §2.7: "applying a deferral payment must carry `expected_deferral_version`, which
    must equal the current `version` of the target `DeferralAgreement`; because each applied
    payment waterfalls against the live balance and advances the agreement's `version`, a
    payment carrying a stale version was computed against an outdated balance and is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_deferral_payment_stale_version_rejected
    """
    # After one applied 60000 payment the agreement version advanced; a payment carrying the
    # prior (now-stale) version must be rejected.
    owner, roll, parcel, final, bill, deferral = setup_deferral_after_payment(
        principal_market=200000, annual_interest_rate=0.05, first_payment_cents=60000
    )
    live_version = deferral["version"]
    resp = api.create_payment(
        deferral["id"], f.create_payment_payload(5000, live_version - 1), ASSESSOR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api.get_deferral(deferral["id"], ASSESSOR))
    assert after["outstanding_balance_cents"] == 150000, \
        f"a rejected stale payment must not change the balance, got {after['outstanding_balance_cents']}"


def test_derived_field_taxable_value_recomputed_on_exemption_approve(api):
    """PRD §3.4: "A veteran deduction is a flat 4,000 dollars."
    PRD §3.4: "On approval the deduction is computed and recorded as `claimed_amount`, then
    folded into the parent assessment's running total."
    PRD §3.5: "The `taxable_value` is then the greater of 0 and `assessed_value` minus
    `exemption_total`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_taxable_value_recomputed_on_exemption_approve
    """
    # assessed 100000 (market rebase), veteran owner, VETERAN flat 4000 -> taxable 96000.
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=100000, reassessment_event="NONE",
        owner_overrides={"is_veteran": True},
    )
    exm = claim_exemption(asmt["id"], "VETERAN")
    data = validate_success(api.approve_exemption(exm["id"], REVIEWER))
    assert data["claimed_amount"] == 4000
    asmt_after = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert asmt_after["exemption_total"] == 4000
    assert asmt_after["taxable_value"] == 96000
