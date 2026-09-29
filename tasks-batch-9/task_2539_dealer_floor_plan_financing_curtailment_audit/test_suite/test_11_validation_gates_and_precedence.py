"""Gates: uniqueness scope, inclusive age ceilings, class aggregates and band order."""
from test_helpers import (
    CO,
    ApiErrorId,
    api_client,
    assert_credit_line_capacity_identity,
    assert_inventory_unit,
    create_unit_payload,
    credit_line_version,
    floor_unit,
    fund_advance_payload,
    make_vin,
    move_title_custody,
    read_credit_line,
    read_unit,
    register_unit,
    request_advance,
    setup_active_line,
    setup_pending_line,
    validate_error,
    validate_paginated,
    validate_success,
)

NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}
USED_TIER_1000 = {
    "inventory_class": "USED",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}


def test_the_same_vin_collides_within_one_dealership_but_not_across_two():
    """A repeat VIN on one lot is a conflict while a different dealership may register it freely.

    PRD: "The `vin` must be unique among the dealership's units whose `funding_status` is anything other than `REPOSSESSED`; a collision is refused with `ERR_DUPLICATE_VIN`."

    Design: Corner/validations/duplicate_vin_within_the_same_dealer_returns_conflict
    """
    first = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Twin VIN One LLC", "state_code": "AL"},
    )
    second = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Twin VIN Two LLC", "state_code": "AL"},
    )
    vin = make_vin("CRNTWINVINUNIT01")

    original = register_unit(
        first["dealer"]["id"],
        first["credit_line"]["id"],
        "CRNTWINVINUNIT01",
        dealer_headers=first["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    assert original["vin"] == vin

    validate_error(
        api_client.create_unit(
            create_unit_payload(
                first["dealer"]["id"],
                first["credit_line"]["id"],
                vin,
                invoice_amount_cents=2000000,
            ),
            first["dealer_headers"],
        ),
        ApiErrorId.ERR_DUPLICATE_VIN,
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_units(CO, params={"dealer_id": first["dealer"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == original["id"]
    assert rows[0]["invoice_amount_cents"] == 3000000

    twin = register_unit(
        second["dealer"]["id"],
        second["credit_line"]["id"],
        "CRNTWINVINUNIT01",
        dealer_headers=second["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    assert_inventory_unit(twin)
    assert twin["vin"] == vin
    assert twin["dealer_id"] == second["dealer"]["id"]


def test_an_invoice_exactly_ninety_days_old_still_funds_and_carries_the_aged_haircut():
    """Ninety days is inside the ceiling and past the haircut threshold, so 9,750 bps pays 2,925,000.

    PRD: "An invoice may be at most 90 days old: exactly 90 days still funds, 91 days is refused with `ERR_INVOICE_TOO_OLD_TO_FLOOR`."

    PRD: "a unit whose invoice age in whole days is 45 or more loses a further 250 basis points, and the code `AGED_INVOICE` is appended."

    Design: Corner/validations/an_invoice_exactly_ninety_days_old_still_funds_with_the_aged_haircut
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Aged Invoice Motors LLC", "state_code": "MO"},
    )
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        ctx["dealer"]["id"],
        line_id,
        "CRNAGED90UNIT001",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
        invoice_date="2026-05-03",
    )
    move_title_custody(unit["id"], "LENDER_HELD", "MSO-C23")
    advance = request_advance(unit["id"], ctx["dealer_headers"], 3000000, "INV-C23")

    funded = validate_success(
        api_client.fund_advance(
            advance["id"],
            fund_advance_payload(credit_line_version(line_id), "WIRE-C23"),
            CO,
        )
    )
    assert funded["status"] == "FUNDED"
    assert funded["invoice_age_days_at_funding"] == 90
    assert funded["effective_advance_rate_bps"] == 9750
    assert funded["approved_advance_amount_cents"] == 2925000
    assert funded["rate_adjustment_codes"] == ["AGED_INVOICE"]

    unit_after = read_unit(unit["id"])
    assert unit_after["funding_status"] == "FLOORED"
    assert unit_after["outstanding_principal_cents"] == 2925000

    line = read_credit_line(line_id)
    assert line["available_credit_cents"] == 497075000
    assert_credit_line_capacity_identity(line)


def test_two_individually_valid_used_advances_breach_the_class_sublimit_together():
    """Each 1,800,000 advance fits the 3,000,000 used sublimit; their sum does not.

    PRD: "and for `USED` and `DEMONSTRATOR` units the class's current outstanding total plus the computed advance must not exceed that class's sublimit — `class_outstanding_cents_used` against `class_sublimit_cents_used`, `class_outstanding_cents_demonstrator` against `class_sublimit_cents_demonstrator` — with a breach refused as `ERR_CLASS_SUBLIMIT_EXCEEDED`."

    Design: Corner/validations/two_individually_valid_used_advances_breach_the_class_sublimit_together
    """
    ctx = setup_active_line(
        tiers=[USED_TIER_1000],
        class_sublimit_cents_used=3000000,
        dealer_overrides={
            "legal_name": "Corner Sublimit Motors LLC",
            "franchise_type": "INDEPENDENT_USED",
            "state_code": "AR",
        },
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]

    first = floor_unit(
        dealer_id,
        line_id,
        "CRNSUBLIMITUNIT1",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=2000000,
        document_reference="TITLE-C24-1",
        inventory_class="USED",
        invoice_amount_cents=2000000,
        title_document_type="TITLE",
    )
    assert first["advance"]["approved_advance_amount_cents"] == 1800000

    second_unit = register_unit(
        dealer_id,
        line_id,
        "CRNSUBLIMITUNIT2",
        dealer_headers=ctx["dealer_headers"],
        inventory_class="USED",
        invoice_amount_cents=2000000,
        title_document_type="TITLE",
    )
    move_title_custody(second_unit["id"], "LENDER_HELD", "TITLE-C24-2")
    second_advance = request_advance(
        second_unit["id"], ctx["dealer_headers"], 2000000, "INV-C24-2"
    )

    validate_error(
        api_client.fund_advance(
            second_advance["id"],
            fund_advance_payload(credit_line_version(line_id), "WIRE-C24-2"),
            CO,
        ),
        ApiErrorId.ERR_CLASS_SUBLIMIT_EXCEEDED,
        422,
    )

    line = read_credit_line(line_id)
    assert line["class_outstanding_cents_used"] == 1800000
    assert line["available_credit_cents"] == 498200000
    assert_credit_line_capacity_identity(line)

    blocked = validate_success(
        api_client.get_funding_advance(second_advance["id"], CO)
    )
    assert blocked["status"] == "REQUESTED"
    assert blocked["approved_advance_amount_cents"] == 0
    assert read_unit(second_unit["id"])["funding_status"] == "PENDING_FUNDING"


def test_the_document_rule_binds_new_inventory_only():
    """A NEW unit presented with a certificate of title is refused; the same row as USED is accepted.

    PRD: "`NEW` inventory must present a manufacturer statement of origin, so `title_document_type` must be `MSO`; `USED` inventory must present a certificate of title, so it must be `TITLE`; `DEMONSTRATOR` inventory accepts either. A mismatch is refused with `ERR_MSO_REQUIRED_FOR_NEW_UNIT`."

    Design: Corner/validations/the_mso_requirement_applies_only_to_new_inventory
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Document Motors LLC", "state_code": "MS"},
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]

    validate_error(
        api_client.create_unit(
            create_unit_payload(
                dealer_id,
                line_id,
                make_vin("CRNDOCRULEUNIT01"),
                inventory_class="NEW",
                invoice_amount_cents=3000000,
                title_document_type="TITLE",
            ),
            ctx["dealer_headers"],
        ),
        ApiErrorId.ERR_MSO_REQUIRED_FOR_NEW_UNIT,
        422,
    )

    _, meta = validate_paginated(
        api_client.list_units(CO, params={"dealer_id": dealer_id})
    )
    assert meta["total_count"] == 0

    as_used = validate_success(
        api_client.create_unit(
            create_unit_payload(
                dealer_id,
                line_id,
                make_vin("CRNDOCRULEUNIT01"),
                inventory_class="USED",
                invoice_amount_cents=3000000,
                title_document_type="TITLE",
            ),
            ctx["dealer_headers"],
        ),
        201,
    )
    assert as_used["title_document_type"] == "TITLE"
    assert as_used["title_custody_status"] == "NOT_RECEIVED"

    as_new = validate_success(
        api_client.create_unit(
            create_unit_payload(
                dealer_id,
                line_id,
                make_vin("CRNDOCRULEUNIT02"),
                inventory_class="NEW",
                invoice_amount_cents=3000000,
                title_document_type="MSO",
            ),
            ctx["dealer_headers"],
        ),
        201,
    )
    assert as_new["title_document_type"] == "MSO"


def test_the_line_state_refusal_hides_the_document_refusal_until_the_line_is_switched_on():
    """One request breaks both rules; the 409 comes back first and the 422 only surfaces afterwards.

    PRD: "**State preconditions** — on the target resource and on its parents (the HTTP 409 family)."

    PRD: "**Title, document and collateral-eligibility control** — the manufacturer-statement-of-origin rule, the lender-custody funding gate, the title release gate, the ineligible-collateral gate and the invoice-age gate."

    PRD: "Registration also requires the governing line to be `ACTIVE` (`ERR_CREDIT_LINE_NOT_ACTIVE`) and the dealership to be `ACTIVE` (`ERR_DEALER_NOT_ACTIVE`) — a `PROSPECT` dealership cannot floor inventory, and neither can a suspended, defaulted or terminated one."

    Design: Corner/validations/the_line_state_check_runs_before_the_title_document_check
    """
    ctx = setup_pending_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Band Order Motors LLC", "state_code": "LA"},
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    assert ctx["credit_line"]["status"] == "PENDING"

    offending_payload = create_unit_payload(
        dealer_id,
        line_id,
        make_vin("CRNBANDORDERUNT1"),
        inventory_class="NEW",
        invoice_amount_cents=3000000,
        title_document_type="TITLE",
    )

    validate_error(
        api_client.create_unit(offending_payload, ctx["dealer_headers"]),
        ApiErrorId.ERR_CREDIT_LINE_NOT_ACTIVE,
        409,
    )
    _, meta = validate_paginated(
        api_client.list_units(CO, params={"dealer_id": dealer_id})
    )
    assert meta["total_count"] == 0

    validate_success(api_client.activate_credit_line(line_id, CO))
    validate_error(
        api_client.create_unit(offending_payload, ctx["dealer_headers"]),
        ApiErrorId.ERR_MSO_REQUIRED_FOR_NEW_UNIT,
        422,
    )

    compliant = validate_success(
        api_client.create_unit(
            create_unit_payload(
                dealer_id,
                line_id,
                make_vin("CRNBANDORDERUNT1"),
                inventory_class="NEW",
                invoice_amount_cents=3000000,
                title_document_type="MSO",
            ),
            ctx["dealer_headers"],
        ),
        201,
    )
    assert compliant["funding_status"] == "REGISTERED"
