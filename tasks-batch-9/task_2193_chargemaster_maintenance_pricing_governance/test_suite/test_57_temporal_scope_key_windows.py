"""Half-open price-rule intervals versus closed contract terms, and the schema check above both."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_facility, create_item, reprice_item, read_item, read_facility, set_clock,
    ANALYST, CONTRACT,
)

FACILITY = {
    "name": "Mercy General", "cms_certification_number": "CCN-2193-TEMPORAL",
    "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
}
RC_0300 = {
    "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
    "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
    "pricing_class": "PROCEDURE", "status": "ACTIVE",
}


def _read_rule(rule_id: str) -> dict:
    return validate_success(api_client.get_price_rule(rule_id, ANALYST), 200)


def _read_contract(contract_id: str) -> dict:
    return validate_success(api_client.get_payer_contract(contract_id, CONTRACT), 200)


def test_an_inverted_interval_is_a_schema_error_and_supersession_exempts_the_incumbent():
    """PRD §3.2: "Creating a rule triggers a scope-key overlap check against other rules of the same
    `(facility_id, revenue_code_id)` whose `status` is `ACTIVE`; if the new interval intersects an
    existing one the create is refused with `ERR_PRICE_RULE_OVERLAP`. Because the intervals are
    half-open, an existing rule whose `effective_to` equals the new rule's `effective_from` abuts
    rather than overlaps and is entirely legal."
    PRD §3.2: "Naming a rule there excludes that rule from the overlap check, and on success four
    things follow. The named rule transitions `ACTIVE → SUPERSEDED`, its `effective_to` is truncated to
    the new rule's `effective_from`, and its `superseded_by_rule_id` is set to the new rule's
    identifier. Every `ChargeItem` whose `applied_price_rule_id` names the superseded rule transitions
    in the pricing dimension from `PRICED_CURRENT` to `PRICE_STALE`, with each such item's `version`
    advancing by 1."
    PRD §2.9: "11. Payload schema conformance — `ERR_VALIDATION` (422)."

    Design: Corner/validations/price_rule_overlap_yields_to_the_schema_check_while_abutting_and_superseding_rules_are_accepted
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(
        facility_overrides=FACILITY,
        revenue_code_overrides=RC_0300,
        department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                             "allowed_revenue_code_values": []},
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z",
                              "effective_to": "2026-10-01T00:00:00Z"},
    )
    facility_id = base["facility"]["id"]
    rule_a = base["price_rule"]
    item = create_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                       code_type="CPT", code_value="93458", cost_basis_cents=100000,
                       medicare_rate_cents=50000, market_p75_cents=900000,
                       effective_from="2026-09-01T00:00:00Z")
    priced = reprice_item(item["id"])
    assert priced["gross_charge_cents"] == 240000
    assert priced["price_status"] == "PRICED_CURRENT"
    assert priced["version"] == 2
    assert priced["applied_price_rule_id"] == rule_a["id"]

    def rule_body(**overrides):
        return factories.create_price_rule_payload(
            facility_id, base["revenue_code"]["id"], **overrides
        )

    validate_error(
        api_client.create_price_rule(rule_body(
            pricing_method="FLAT_FEE", flat_fee_cents=500000,
            effective_from="2026-06-01T00:00:00Z", effective_to="2026-03-01T00:00:00Z",
        ), ANALYST),
        ApiErrorId.ERR_VALIDATION.value, 422,
    )
    validate_error(
        api_client.create_price_rule(rule_body(
            pricing_method="FLAT_FEE", flat_fee_cents=500000,
            effective_from="2026-06-01T00:00:00Z", effective_to=None,
        ), ANALYST),
        ApiErrorId.ERR_PRICE_RULE_OVERLAP.value, 409,
    )

    rule_b = validate_success(api_client.create_price_rule(rule_body(
        pricing_method="FLAT_FEE", flat_fee_cents=500000,
        effective_from="2026-10-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        min_medicare_multiple_bp=12000, market_cap_multiple_bp=11000,
    ), ANALYST), 201)
    assert rule_b["status"] == "ACTIVE", "abutting the incumbent's exclusive end is legal"

    rule_c = validate_success(api_client.create_price_rule(rule_body(
        pricing_method="COST_PLUS_MARKUP",
        effective_from="2026-09-01T00:00:00Z", effective_to="2026-10-01T00:00:00Z",
        markup_tiers=[{"min_cost_basis_cents": 0, "markup_bp": 40000}],
        min_medicare_multiple_bp=12000, market_cap_multiple_bp=11000,
        supersede_rule_id=rule_a["id"],
    ), ANALYST), 201)
    assert rule_c["status"] == "ACTIVE"

    superseded = _read_rule(rule_a["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["effective_to"].startswith("2026-09-01T00:00:00")
    assert superseded["superseded_by_rule_id"] == rule_c["id"]

    staled = read_item(item["id"])
    assert staled["price_status"] == "PRICE_STALE"
    assert staled["version"] == 3

    facility = read_facility(facility_id)
    assert facility["stale_price_item_count"] == 0, (
        "the staled item is DRAFT, and the counter only counts ACTIVE items"
    )
    assert facility["chargemaster_posture"] == "OPEN"

    rows, meta = validate_paginated(
        api_client.list_price_rules(ANALYST, {"facility_id": facility_id})
    )
    assert meta["total_count"] == 3, "two refusals stored nothing"
    assert {row["id"] for row in rows} == {rule_a["id"], rule_b["id"], rule_c["id"]}


def test_contract_terms_are_closed_so_abutting_collides_and_the_notice_gap_must_be_exceeded():
    """PRD §3.6: "First, no other contract of the same `(facility_id, payer_code, product_line)` scope
    key whose `status` is `ACTIVE` or `EXPIRED` may have a `[term_start_date, term_end_date]` interval
    intersecting the new one; because both endpoints are inclusive, a prior term ending exactly on the
    new term's start date *does* collide, and the create is refused with `ERR_CONTRACT_TERM_OVERLAP`
    (409). Second, for the same scope key, the gap between the prior term's `term_end_date` and the new
    term's `term_start_date` must be **strictly greater** than the prior term's
    `renegotiation_notice_days` in days; a gap of exactly `renegotiation_notice_days` days fails with
    `ERR_CONTRACT_TERM_BUFFER_VIOLATION` (409)."
    PRD §3.6: "`renegotiation_notice_days`, defaulting to 30, sets the clear gap this term demands
    before a successor term of the same scope may begin. A contract's `status` starts at `ACTIVE` and
    may become `EXPIRED` (when the logical clock passes `term_end_date`) or `TERMINATED`."
    PRD §2.9: "11. Payload schema conformance — `ERR_VALIDATION` (422)."

    Design: Corner/validations/contract_term_closed_overlap_then_notice_buffer_then_scope_key_isolation
    """
    set_clock("2026-01-01T00:00:00Z")
    facility = create_facility(name="Mercy General",
                              cms_certification_number="CCN-2193-CONTRACT")
    facility_id = facility["id"]

    def contract_body(**overrides):
        fields = dict(payer_code="AETNA", product_line="COMMERCIAL",
                      reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=4000)
        fields.update(overrides)
        return factories.create_payer_contract_payload(facility_id, **fields)

    incumbent = validate_success(api_client.create_payer_contract(contract_body(
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-06-30T00:00:00Z",
    ), CONTRACT), 201)
    assert incumbent["status"] == "ACTIVE", "a contract's status starts at ACTIVE"
    set_clock("2026-09-01T00:00:00Z")
    stored_incumbent = _read_contract(incumbent["id"])
    assert stored_incumbent["status"] == "EXPIRED", "the clock has passed its term_end_date"
    assert stored_incumbent["renegotiation_notice_days"] == 30, "the omitted notice defaults to 30"

    validate_error(
        api_client.create_payer_contract(contract_body(
            term_start_date="2026-06-01T00:00:00Z", term_end_date="2026-05-01T00:00:00Z",
        ), CONTRACT),
        ApiErrorId.ERR_VALIDATION.value, 422,
    )
    validate_error(
        api_client.create_payer_contract(contract_body(
            term_start_date="2026-06-30T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
        ), CONTRACT),
        ApiErrorId.ERR_CONTRACT_TERM_OVERLAP.value, 409,
    )
    validate_error(
        api_client.create_payer_contract(contract_body(
            term_start_date="2026-07-30T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
        ), CONTRACT),
        ApiErrorId.ERR_CONTRACT_TERM_BUFFER_VIOLATION.value, 409,
    )

    successor = validate_success(api_client.create_payer_contract(contract_body(
        percent_of_charge_bp=4500, trailing_units=200,
        term_start_date="2026-07-31T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    ), CONTRACT), 201)
    assert successor["status"] == "ACTIVE", "a gap of 31 days clears the 30-day notice"

    other_line = validate_success(api_client.create_payer_contract(
        factories.create_payer_contract_payload(
            facility_id, payer_code="AETNA", product_line="MEDICARE_ADVANTAGE",
            reimbursement_method="CASE_RATE", percent_of_charge_bp=None,
            case_rate_cents=350000, trailing_units=40,
            term_start_date="2026-06-30T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
        ), CONTRACT), 201)
    assert other_line["status"] == "ACTIVE", (
        "payer_code plus product_line is the scope key, so another product line is unconstrained"
    )

    assert _read_contract(successor["id"])["percent_of_charge_bp"] == 4500
    assert _read_contract(other_line["id"])["case_rate_cents"] == 350000

    rows, meta = validate_paginated(
        api_client.list_payer_contracts(CONTRACT, {"facility_id": facility_id})
    )
    assert meta["total_count"] == 3, "the three refusals stored nothing"
    assert {row["id"] for row in rows} == {
        incumbent["id"], successor["id"], other_line["id"],
    }
