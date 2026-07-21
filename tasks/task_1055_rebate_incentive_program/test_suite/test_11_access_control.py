"""Authentication, role authorization, claim ownership and segregation of duties."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    attach_receipt,
    create_dealer_claimant,
    make_dealer_headers,
    make_finance_headers,
    open_claim,
    read_claim,
    read_claimant,
    read_payout,
    read_program,
    setup_catalogue,
    setup_claim_under_review,
    setup_pending_payout,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
PROCESSOR = TEST_USERS["claims_processor_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name one
    of the six roles defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_programs({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_dealer_may_not_approve_a_claim(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to invoke the requested operation, the rejection is
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `ClaimsProcessor` adjudicates: validating receipts, taking claims
    into review, approving them and denying them."

    Design: Corner/rbac/dealer_cannot_approve_a_claim
    """
    ctx = setup_claim_under_review(
        program_overrides={"name": "Rbac Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Rbac Offer"},
        claimant_overrides={"legal_name": "Rbac Dealer", "email": "rb@rb.example"},
        serial_number="SN-RB-1",
    )
    resp = api.approve_claim(ctx["claim"]["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    assert read_claim(ctx["claim"]["id"])["adjudication_status"] == "UNDER_REVIEW"
    assert read_program(ctx["program"]["id"])["committed_cents"] == 0


def test_dealer_may_not_submit_another_dealers_claim(api):
    """PRD §2.1: "Ownership checks on any claim, receipt, payout or virtual card
    compare the owning claim's `claimant_id` to `X-User-ID`, and a mismatch is
    rejected with `ERR_NOT_CLAIM_OWNER` (HTTP 403). That ownership check guards
    seven operations: opening a claim, attaching a receipt to it, submitting it,
    withdrawing it, appealing its denial, activating a virtual card, and spending
    against a virtual card."

    Design: Corner/rbac/dealer_cannot_submit_another_dealers_claim
    """
    ctx = setup_catalogue(
        program_overrides={"name": "Owner Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Owner Offer"},
        claimant_overrides={"legal_name": "Owner A", "email": "oa@oa.example"},
    )
    owner = ctx["claimant"]
    intruder = create_dealer_claimant(legal_name="Owner B", email="ob@ob.example")

    claim = open_claim(ctx["offer"]["id"], owner)
    attach_receipt(
        claim["id"],
        owner,
        serial_number="SN-OW-1",
        lines=[{"sku": "TOOLS-A", "quantity": 2, "unit_price_cents": 1000}],
    )

    resp = api.submit_claim(claim["id"], make_dealer_headers(intruder["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_CLAIM_OWNER.value)

    assert read_claim(claim["id"])["adjudication_status"] == "DRAFT"
    assert read_claimant(owner["id"])["open_claim_count"] == 0


def test_the_approving_operator_may_not_release_the_payout(api):
    """PRD §3.8: "An operator attempting to release money it itself approved is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "On release the payout moves to `RELEASED`, `released_at` is stamped
    from the logical clock and `released_by_user_id` from the acting `X-User-ID`;
    the claim's payment state moves `SCHEDULED → PAID`; and a ledger row of type
    `PAYMENT` with `amount_cents` equal to the payout's `net_cents` is appended,
    raising the program's `paid_cents`."

    Design: Corner/rbac/approver_cannot_also_release_the_payout
    """
    ctx = setup_pending_payout(
        method="CHECK",
        approver_user_id="u-proc-1",
        program_overrides={"name": "SoD Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "SoD Offer"},
        claimant_overrides={"legal_name": "SoD Dealer", "email": "sd@sd.example"},
        serial_number="SN-SD-1",
    )
    same_operator = api.release_payout(
        ctx["payout"]["id"], make_finance_headers("u-proc-1"), {"check_number": "CHK-5000"}
    )
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert read_payout(ctx["payout"]["id"])["status"] == "PENDING"

    released = validate_success(
        api.release_payout(
            ctx["payout"]["id"], make_finance_headers("u-fin-1"), {"check_number": "CHK-5001"}
        )
    )
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == "u-fin-1"
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "PAID"
    assert read_program(ctx["program"]["id"])["paid_cents"] == 1450


def test_unknown_ids_in_the_claim_family_report_their_own_not_found_code(api):
    """PRD §2.8: "Path existence — every resource named in the URL path must exist,
    resolved left to right, else the corresponding not-found error
    (`ERR_PROGRAM_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIMANT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`,
    `ERR_CARD_NOT_FOUND` or `ERR_FRAUD_CASE_NOT_FOUND`, all HTTP 404)."

    Design: Corner/endpoints/unknown_ids_across_the_claim_family_return_404
    """
    claimant = create_dealer_claimant(legal_name="NF Dealer", email="nf@nf.example")
    dealer = make_dealer_headers(claimant["id"])

    validate_error(
        api.submit_claim("00000000-0000-4000-8000-00000000000a", dealer),
        ApiErrorId.ERR_CLAIM_NOT_FOUND.value,
    )
    validate_error(
        api.validate_receipt("00000000-0000-4000-8000-00000000000b", PROCESSOR),
        ApiErrorId.ERR_RECEIPT_NOT_FOUND.value,
    )
    validate_error(
        api.release_payout(
            "00000000-0000-4000-8000-00000000000c", FINANCE, {"check_number": "CHK-0000"}
        ),
        ApiErrorId.ERR_PAYOUT_NOT_FOUND.value,
    )
    validate_error(
        api.activate_virtual_card("00000000-0000-4000-8000-00000000000d", dealer),
        ApiErrorId.ERR_CARD_NOT_FOUND.value,
    )


def test_unknown_ids_in_the_admin_family_report_their_own_not_found_code(api):
    """PRD §2.8: "Path existence — every resource named in the URL path must exist,
    resolved left to right, else the corresponding not-found error
    (`ERR_PROGRAM_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIMANT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`,
    `ERR_CARD_NOT_FOUND` or `ERR_FRAUD_CASE_NOT_FOUND`, all HTTP 404)."

    Design: Corner/endpoints/unknown_ids_across_the_admin_family_return_404
    """
    validate_error(
        api.publish_offer("00000000-0000-4000-8000-00000000000e", ADMIN),
        ApiErrorId.ERR_OFFER_NOT_FOUND.value,
    )
    validate_error(
        api.reinstate_claimant(
            "00000000-0000-4000-8000-00000000000f", {"memo": "cleared"}, FRAUD
        ),
        ApiErrorId.ERR_CLAIMANT_NOT_FOUND.value,
    )
    validate_error(
        api.transition_fraud_case(
            "00000000-0000-4000-8000-000000000010",
            {"to_status": "UNDER_INVESTIGATION"},
            FRAUD,
        ),
        ApiErrorId.ERR_FRAUD_CASE_NOT_FOUND.value,
    )
