"""Claimant registration, opening a claim and attaching proof of purchase."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_claim,
    assert_claimant,
    assert_receipt,
    create_active_program,
    create_claimant_payload,
    create_consumer_claimant,
    create_dealer_claimant,
    create_offer,
    create_published_offer,
    create_receipt_payload,
    make_consumer_headers,
    make_dealer_headers,
    read_claim,
    setup_catalogue,
    setup_draft_claim,
    setup_submitted_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_registered_claimant_starts_active_with_zeroed_counters(api):
    """PRD §3.3: "New claimants start `ACTIVE` with a `fraud_score` of 0 and with
    `duplicate_attempt_count`, `denied_claim_count` and `open_claim_count` all at
    zero."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increases by exactly 1 on every mutation of that resource;
    `updated_at` is refreshed on the same occasions."

    Design: Corner/entities/claimant_system_fields_are_server_minted
    """
    data = validate_success(
        api.create_claimant(
            create_claimant_payload(
                type="CONSUMER",
                legal_name="System Fields Consumer",
                email="sf@sf.example",
                mailing_state="NY",
            ),
            ADMIN,
        ),
        201,
    )
    assert_claimant(data)
    assert data["status"] == "ACTIVE"
    assert data["fraud_score"] == 0
    assert data["denied_claim_count"] == 0
    assert data["open_claim_count"] == 0
    assert data["duplicate_attempt_count"] == 0
    assert data["version"] == 1


def test_claimant_type_outside_the_declared_set_is_rejected(api):
    """PRD §2.8: "Shape validation — required fields present, enum values drawn
    from their declared sets, constrained integers positive, an offer's
    `effective_end_date` strictly later than its `effective_start_date`, and a
    receipt's `lines` a non-empty array each of whose entries carries `sku`, a
    `quantity` greater than zero and a `unit_price_cents` greater than zero.
    Any breach is `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_claimant_with_invalid_enum_is_rejected
    """
    resp = api.create_claimant(
        create_claimant_payload(
            type="DISTRIBUTOR", legal_name="Bad Type", email="bt@bt.example"
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_claim_opens_in_draft_on_both_state_dimensions(api):
    """PRD §3.3: "The new claim starts with `adjudication_status` of `DRAFT` and
    `payment_status` of `NONE`, with `total_units` and `provisional_rebate_cents`
    at zero, `final_rebate_cents`, `fraud_score_at_submit`, `submitted_at`,
    `approved_at`, `denied_at`, `approved_by_user_id` and `denial_reason_code` all
    null, and `appeal_count` at zero."

    Design: Corner/state_machines/claim_starts_in_draft_with_payment_status_none
    """
    ctx = setup_catalogue(
        clock=None,
        program_overrides={"name": "Initial Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Initial Offer"},
    )
    data = validate_success(
        api.create_claim(
            {"offer_id": ctx["offer"]["id"], "claimant_id": ctx["claimant"]["id"]},
            ctx["headers"],
        ),
        201,
    )
    assert_claim(data)
    assert data["adjudication_status"] == "DRAFT"
    assert data["payment_status"] == "NONE"
    assert data["provisional_rebate_cents"] == 0
    assert data["final_rebate_cents"] is None
    assert data["appeal_count"] == 0
    assert data["version"] == 1


def test_claim_cannot_be_opened_against_an_unpublished_offer(api):
    """PRD §3.3: "The offer must be `PUBLISHED` at that moment, otherwise
    `ERR_OFFER_NOT_PUBLISHED` is returned."

    Design: Corner/state_machines/create_claim_against_draft_offer_is_rejected
    """
    program = create_active_program(name="Unpublished Program", budget_total_cents=100000000)
    offer = create_offer(program["id"], name="Still Draft Offer")
    claimant = create_dealer_claimant(legal_name="Eager Dealer", email="eg@eg.example")
    headers = make_dealer_headers(claimant["id"])

    resp = api.create_claim(
        {"offer_id": offer["id"], "claimant_id": claimant["id"]}, headers
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_PUBLISHED.value)

    _, meta = validate_paginated(api.list_claims(ADMIN, params={"claimant_id": claimant["id"]}))
    assert meta["total_count"] == 0


def test_receipt_line_count_units_and_gross_amount_are_computed(api):
    """PRD §3.3: "On creation the server computes `line_count` as the number of
    entries in `lines`, `units` as the sum of the `quantity` values across those
    entries, and `gross_amount_cents` as the sum, over the entries, of `quantity`
    multiplied by `unit_price_cents`. The receipt begins with `validated` false and
    `validated_at` null."

    Design: Corner/entities/receipt_units_and_gross_amount_are_computed_from_lines
    """
    ctx = setup_draft_claim(
        clock=None,
        with_receipt=False,
        program_overrides={"name": "Computed Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Computed Offer"},
    )
    data = validate_success(
        api.create_receipt(
            ctx["claim"]["id"],
            create_receipt_payload(
                serial_number="SN-CMP-1",
                lines=[
                    {"sku": "TOOLS-A", "quantity": 3, "unit_price_cents": 1000},
                    {"sku": "TOOLS-B", "quantity": 2, "unit_price_cents": 2500},
                ],
            ),
            ctx["headers"],
        ),
        201,
    )
    assert_receipt(data)
    assert data["line_count"] == 2
    assert data["units"] == 5
    assert data["gross_amount_cents"] == 8000
    assert data["validated"] is False
    assert data["validated_at"] is None


def test_receipt_cannot_be_attached_after_submission(api):
    """PRD §3.3: "Proof of purchase is attached as **receipts**, and only while the
    claim is still `DRAFT` — attaching to a claim in any later state reports
    `ERR_CLAIM_NOT_DRAFT` (HTTP 409)."

    Design: Corner/validations/attaching_a_receipt_to_a_submitted_claim_is_rejected
    """
    ctx = setup_submitted_claim(
        program_overrides={"name": "Late Receipt Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Late Receipt Offer"},
        lines=[{"sku": "TOOLS-A", "quantity": 2, "unit_price_cents": 1000}],
    )
    resp = api.create_receipt(
        ctx["claim"]["id"],
        create_receipt_payload(
            serial_number="SN-LT-2",
            purchase_date="2026-06-21T00:00:00Z",
            lines=[{"sku": "TOOLS-B", "quantity": 2, "unit_price_cents": 1000}],
        ),
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_DRAFT.value)

    _, meta = validate_paginated(api.list_claim_receipts(ctx["claim"]["id"], ADMIN))
    assert meta["total_count"] == 1
    assert read_claim(ctx["claim"]["id"])["provisional_rebate_cents"] == 100


def test_receipt_with_twenty_one_lines_exceeds_the_line_ceiling(api):
    """PRD §2.8: "Receipt line ceiling — a receipt's `lines` array may carry at most
    20 entries; a longer array is `ERR_RECEIPT_LIMIT_EXCEEDED` (HTTP 422). This is
    checked after shape validation, so an empty array reports `ERR_VALIDATION`
    while a 21-entry array reports `ERR_RECEIPT_LIMIT_EXCEEDED`."

    Design: Corner/validations/receipt_with_twenty_one_lines_exceeds_the_line_limit
    """
    ctx = setup_draft_claim(
        clock=None,
        with_receipt=False,
        program_overrides={"name": "Lines Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Lines Offer"},
    )
    lines = [
        {"sku": f"TOOLS-{i:02d}", "quantity": 1, "unit_price_cents": 1000}
        for i in range(1, 22)
    ]
    resp = api.create_receipt(
        ctx["claim"]["id"],
        create_receipt_payload(serial_number="SN-LN-21", lines=lines),
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RECEIPT_LIMIT_EXCEEDED.value)

    _, meta = validate_paginated(api.list_claim_receipts(ctx["claim"]["id"], ADMIN))
    assert meta["total_count"] == 0


def test_consumer_claiming_a_dealer_only_offer_is_a_channel_mismatch(api):
    """PRD §3.3: "A claimant's `type` must be compatible with the `channel` of any
    offer it claims against: a `DEALER` claimant may claim only against a `DEALER`
    or `BOTH` offer, and a `CONSUMER` claimant only against a `CONSUMER` or `BOTH`
    offer. Incompatibility is reported as `ERR_CHANNEL_MISMATCH` (HTTP 422), and
    the check is enforced twice — once when the claim is opened and again when it
    is submitted, because the offer may have been re-scoped in between."

    Design: Corner/validations/consumer_claiming_a_dealer_offer_is_a_channel_mismatch
    """
    program = create_active_program(name="Channel Program", budget_total_cents=100000000)
    dealer_offer = create_published_offer(
        program["id"], name="Dealer Only Offer", channel="DEALER", sku_scope="TOOLS"
    )
    both_offer = create_published_offer(
        program["id"], name="Both Channel Offer", channel="BOTH", sku_scope="APPLIANCE"
    )
    claimant = create_consumer_claimant(
        legal_name="Channel Consumer", email="ch@ch.example", mailing_state="NY"
    )
    headers = make_consumer_headers(claimant["id"])

    rejected = api.create_claim(
        {"offer_id": dealer_offer["id"], "claimant_id": claimant["id"]}, headers
    )
    validate_error(rejected, ApiErrorId.ERR_CHANNEL_MISMATCH.value)

    accepted = validate_success(
        api.create_claim(
            {"offer_id": both_offer["id"], "claimant_id": claimant["id"]}, headers
        ),
        201,
    )
    assert accepted["adjudication_status"] == "DRAFT"
