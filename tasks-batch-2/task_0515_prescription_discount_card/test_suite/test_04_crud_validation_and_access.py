"""CRUD shape, input validation, business-rule guards, RBAC/auth/ownership,
listing/pagination, OCC success, derived-field reconciliation, and immediate
consistency.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    validate_paginated, make_member_headers, make_role_headers, TEST_USERS,
    create_drug_payload, create_pharmacy_payload, create_gold_membership_payload,
    create_comparison_payload, create_insurance_estimate_payload,
    create_copay_card_payload, create_copay_link_payload, create_claim_payload,
    create_mail_order_payload, create_price_quote_payload,
    setup_resolved_comparison, setup_discount_card, setup_submitted_claim,
    setup_adjudicated_claim, setup_submitted_claim_with_copay_link,
    create_member, create_drug, create_pharmacy, create_quote, create_copay_card,
    set_clock,
    assert_drug, assert_member, assert_insurance_estimate,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
OPERATOR = TEST_USERS["pharmacy_operator_headers"]
SPONSOR = TEST_USERS["copay_sponsor_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — create_drug_returns_201_with_all_fields
# ─────────────────────────────────────────────────────────────────────────────

def test_create_drug_returns_201_with_all_fields(api):
    """PRD §3.1: "A drug is registered with a name ... an ndc National Drug Code
    ... a dosage_mg strength ... and a form ... Each drug also carries an awp_cents
    Average Wholesale Price per fill ... and an is_controlled flag that defaults
    to false".

    Design: Corner/entities/create_drug_returns_201_with_all_fields
    """
    set_clock()
    drug = validate_success(api.create_drug(
        create_drug_payload(name="Metformin", ndc="00093104101", dosage_mg=500,
                            form="TABLET", awp_cents=4000), ADMIN), 201)
    assert_drug(drug)
    assert drug["name"] == "Metformin"
    assert drug["awp_cents"] == 4000
    assert drug["is_controlled"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — get_member_returns_computed_zero_savings
# ─────────────────────────────────────────────────────────────────────────────

def test_fresh_member_has_zero_savings_and_null_gold(api):
    """PRD §3.3: "A newly created member starts with lifetime_savings_cents of 0
    and active_gold_membership_id of null".

    Design: Corner/entities/get_member_returns_computed_zero_savings
    """
    member = create_member(email="fresh@x.com")
    headers = make_member_headers(member["id"])
    fetched = validate_success(api.get_member(member["id"], headers), 200)
    assert_member(fetched)
    assert fetched["lifetime_savings_cents"] == 0
    assert fetched["active_gold_membership_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — drug_not_found_returns_404
# ─────────────────────────────────────────────────────────────────────────────

def test_drug_not_found_returns_404(api):
    """PRD §2.8: "When a path identifier in any single-resource read does not
    resolve, the response is ERR_NOT_FOUND."

    Design: Corner/entities/drug_not_found_returns_404
    """
    res = api.get_drug("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — create_drug_missing_required_field_returns_invalid_request
# ─────────────────────────────────────────────────────────────────────────────

def test_create_drug_missing_awp_returns_invalid_request(api):
    """PRD §3.1: "Each drug also carries an awp_cents Average Wholesale Price per
    fill, which must be at least 1 cent". PRD §5: ERR_INVALID_REQUEST is the
    "missing required field" guard (400).

    Design: Corner/entities/create_drug_missing_required_field_returns_invalid_request
    """
    payload = create_drug_payload(name="Lisinopril", ndc="00000000001",
                                  dosage_mg=10, form="TABLET")
    del payload["awp_cents"]
    res = api.create_drug(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — create_drug_invalid_enum_form_returns_invalid_request
# ─────────────────────────────────────────────────────────────────────────────

def test_create_drug_invalid_form_enum_returns_invalid_request(api):
    """PRD §3.1: "a form that must be one of TABLET, CAPSULE, LIQUID, or
    INJECTION". A value outside the declared set is the ERR_INVALID_REQUEST guard.

    Design: Corner/entities/create_drug_invalid_enum_form_returns_invalid_request
    """
    res = api.create_drug(create_drug_payload(name="Lisinopril", ndc="00000000002",
                                              dosage_mg=10, form="POWDER",
                                              awp_cents=3000), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — create_drug_default_is_controlled_false
# ─────────────────────────────────────────────────────────────────────────────

def test_create_drug_default_is_controlled_false(api):
    """PRD §3.1: "an is_controlled flag that defaults to false". Omitting the
    field yields false on the created drug.

    Design: Corner/entities/create_drug_default_is_controlled_false
    """
    payload = create_drug_payload(name="Amoxicillin", ndc="00000000003",
                                  dosage_mg=250, form="CAPSULE", awp_cents=2500)
    payload.pop("is_controlled", None)
    drug = validate_success(api.create_drug(payload, ADMIN), 201)
    assert drug["is_controlled"] is False


# NOTE: Corner/entities/system_fields_generated_on_member_create is SKIPPED.
# The instance asserts Member.version == 1, but PRD §2.4 states only that version
# "begins at its initial value and increments by one on every mutation" — it never
# names the initial value. A PRD-only implementer could legitimately start version
# at 0, so the asserted outcome is not uniquely derivable. Gap left as a gap.


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — list_drugs_paginated_envelope
# ─────────────────────────────────────────────────────────────────────────────

def test_list_drugs_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields limit, offset,
    total_count, and has_more inside the meta object of the envelope." PRD §2.2:
    response_type is "array" for a list.

    Design: Corner/entities/list_drugs_paginated_envelope
    """
    set_clock()
    create_drug(name="DrugA", ndc="11100000001", dosage_mg=10, awp_cents=1000)
    create_drug(name="DrugB", ndc="11100000002", dosage_mg=20, awp_cents=2000)
    data, meta = validate_paginated(api.list_drugs(ANON))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — insurance_estimate_immutable_no_version_field
# ─────────────────────────────────────────────────────────────────────────────

def test_insurance_estimate_immutable_no_version_field(api):
    """PRD §2.4: "An InsuranceEstimate is immutable once created and therefore
    carries only id and created_at; it has neither an updated_at field nor a
    version field."

    Design: Corner/entities/insurance_estimate_immutable_no_version_field
    """
    ctx = setup_resolved_comparison(member_overrides={"email": "imm@x.com",
                                                      "has_insurance": True})
    headers = make_member_headers(ctx["member"]["id"])
    est = validate_success(api.create_insurance_estimate(
        ctx["comparison"]["id"],
        create_insurance_estimate_payload(ctx["member"]["id"], copay_cents=1000,
                                          deductible_remaining_cents=0),
        headers), 201)
    assert_insurance_estimate(est)
    assert "version" not in est, "InsuranceEstimate must not expose a version field"
    assert "updated_at" not in est, "InsuranceEstimate must not expose updated_at"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities — create_pharmacy_wrong_state_code_length_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_create_pharmacy_wrong_state_code_length_rejected(api):
    """PRD §3.1: "a two-letter uppercase state_code identifying the single US
    state it operates in". A three-letter value violates the declared shape ->
    ERR_INVALID_REQUEST.

    Design: Corner/entities/create_pharmacy_wrong_state_code_length_rejected
    """
    res = api.create_pharmacy(create_pharmacy_payload(name="Bad", chain_code="X",
                                                      state_code="CAL",
                                                      dispense_fee_cents=100), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─────────────────────────────────────────────────────────────────────────────
# Corner / validations
# ─────────────────────────────────────────────────────────────────────────────

def test_price_order_violation_gold_above_discount(api):
    """PRD §3.2: "the gold price must not exceed the discount price. A quote that
    violates any link in that chain — cash above AWP, discount above cash, or gold
    above discount — is rejected with ERR_PRICE_ORDER_VIOLATION."

    Design: Corner/validations/price_order_violation_gold_above_discount
    """
    drug = create_drug()
    ph = create_pharmacy()
    res = api.create_price_quote(create_price_quote_payload(
        drug["id"], ph["id"], cash_price_cents=7000, discount_price_cents=5500,
        gold_price_cents=6000), ADMIN)
    validate_error(res, "ERR_PRICE_ORDER_VIOLATION")


def test_coverage_limit_individual_with_covered_ids(api):
    """PRD §3.5: "A GOLD_INDIVIDUAL submitted with a non-empty covered_member_ids,
    or a GOLD_FAMILY submitted with more than five covered ids, is rejected with
    ERR_COVERAGE_LIMIT."

    Design: Corner/validations/coverage_limit_individual_with_covered_ids
    """
    member = create_member(email="cl@x.com")
    other = create_member(email="oth@x.com")
    headers = make_member_headers(member["id"])
    res = api.create_gold_membership(
        create_gold_membership_payload(member["id"], tier="GOLD_INDIVIDUAL",
                                        covered_member_ids=[other["id"]]), headers)
    validate_error(res, "ERR_COVERAGE_LIMIT")


def test_mail_order_at_non_mail_pharmacy_rejected(api):
    """PRD §3.10: "the chosen pharmacy must have is_mail_order set to true,
    otherwise the request is rejected with ERR_NOT_MAIL_ORDER_PHARMACY".

    Design: Corner/validations/mail_order_at_non_mail_pharmacy_rejected
    """
    ctx = setup_discount_card(member_overrides={"email": "nm@x.com"})  # default pharmacy: not mail
    assert ctx["pharmacy"]["is_mail_order"] is False
    headers = make_member_headers(ctx["member"]["id"])
    res = api.create_mail_order(create_mail_order_payload(
        ctx["card"]["id"], ctx["pharmacy"]["id"], ctx["member"]["id"],
        quantity=2, ship_to_state="CA"), headers)
    validate_error(res, "ERR_NOT_MAIL_ORDER_PHARMACY")


def test_insurance_estimate_without_insurance_rejected(api):
    """PRD §3.4: "the member must have has_insurance set to true, otherwise the
    request is rejected with ERR_NO_INSURANCE_ON_FILE".

    Design: Corner/validations/insurance_estimate_without_insurance_rejected
    """
    ctx = setup_resolved_comparison(member_overrides={"email": "ni@x.com"})  # has_insurance false
    headers = make_member_headers(ctx["member"]["id"])
    res = api.create_insurance_estimate(
        ctx["comparison"]["id"],
        create_insurance_estimate_payload(ctx["member"]["id"], copay_cents=1000,
                                          deductible_remaining_cents=0), headers)
    validate_error(res, "ERR_NO_INSURANCE_ON_FILE")


def test_insurance_estimate_on_open_comparison_rejected(api):
    """PRD §3.4: "the comparison must be RESOLVED with best_price_cents set,
    otherwise it is rejected with ERR_COMPARISON_NOT_RESOLVED."

    Design: Corner/validations/insurance_estimate_on_open_comparison_rejected
    """
    set_clock()
    drug = create_drug()
    member = create_member(email="op@x.com", has_insurance=True)
    headers = make_member_headers(member["id"])
    cmp = get_success_data(api.create_comparison(
        create_comparison_payload(member["id"], drug["id"]), headers))  # OPEN, never run
    res = api.create_insurance_estimate(
        cmp["id"],
        create_insurance_estimate_payload(member["id"], copay_cents=1000,
                                          deductible_remaining_cents=0), headers)
    validate_error(res, "ERR_COMPARISON_NOT_RESOLVED")


def test_copay_drug_mismatch_link_rejected(api):
    """PRD §3.8: "the copay card's drug_id must equal the drug of the claim's
    card, otherwise the link is rejected with ERR_COPAY_DRUG_MISMATCH".

    Design: Corner/validations/copay_drug_mismatch_link_rejected
    """
    ctx = setup_submitted_claim(quantity=2, member_overrides={"email": "dm@x.com"})
    d2 = create_drug(name="Rosuvastatin", ndc="00310075190", dosage_mg=10, awp_cents=12000)
    cc = create_copay_card(d2["id"], sponsor_name="AstraZeneca")
    headers = make_member_headers(ctx["member"]["id"])
    res = api.create_copay_link(
        create_copay_link_payload(cc["id"], ctx["member"]["id"], ctx["claim"]["id"]), headers)
    validate_error(res, "ERR_COPAY_DRUG_MISMATCH")


def test_second_copay_link_to_same_claim_rejected(api):
    """PRD §3.8: "at most one LINKED copay link may reference any given claim_id,
    since a claim cannot stack manufacturer offsets, so a second link is rejected
    with ERR_COPAY_ALREADY_LINKED".

    Design: Corner/validations/second_copay_link_to_same_claim_rejected
    """
    ctx = setup_submitted_claim_with_copay_link(quantity=2, member_overrides={"email": "al@x.com"})
    cc2 = create_copay_card(ctx["drug"]["id"], sponsor_name="Mylan")
    headers = make_member_headers(ctx["member"]["id"])
    res = api.create_copay_link(
        create_copay_link_payload(cc2["id"], ctx["member"]["id"], ctx["claim"]["id"]), headers)
    validate_error(res, "ERR_COPAY_ALREADY_LINKED")


def test_controlled_drug_mail_order_blocked(api):
    """PRD §3.12: "For a controlled drug, the member's own state_code must equal
    the relevant destination state — the comparison's state for a telehealth
    referral, and the ship_to_state for a mail order — and the operation is
    otherwise blocked. A controlled-substance violation on either operation is
    rejected with ERR_CONTROLLED_SUBSTANCE_BLOCKED."

    Design: Corner/validations/controlled_drug_mail_order_blocked
    """
    ctx = setup_discount_card(
        member_overrides={"email": "ctl@x.com", "state_code": "CA"},
        drug_overrides={"name": "Oxycodone", "ndc": "00406012301", "dosage_mg": 5,
                        "awp_cents": 20000, "is_controlled": True},
        pharmacy_overrides={"name": "PHM", "chain_code": "MAIL", "state_code": "CA",
                            "dispense_fee_cents": 150, "is_mail_order": True},
        quote_overrides={"cash_price_cents": 15000, "discount_price_cents": 12000,
                         "gold_price_cents": 11000})
    headers = make_member_headers(ctx["member"]["id"])
    res = api.create_mail_order(create_mail_order_payload(
        ctx["card"]["id"], ctx["pharmacy"]["id"], ctx["member"]["id"],
        quantity=2, ship_to_state="NY"), headers)
    validate_error(res, "ERR_CONTROLLED_SUBSTANCE_BLOCKED")


def test_claim_quantity_zero_out_of_range(api):
    """PRD §3.7: "naming the discount_card_id, the adjudicating pharmacy_id, and
    the quantity of fills (which must be at least 1)." and "A quantity below 1 on
    a claim is rejected with ERR_QUANTITY_OUT_OF_RANGE."

    Design: Corner/validations/claim_quantity_zero_out_of_range
    """
    ctx = setup_discount_card(member_overrides={"email": "qz@x.com"})
    res = api.create_claim(
        create_claim_payload(ctx["card"]["id"], ctx["pharmacy"]["id"], quantity=0), OPERATOR)
    validate_error(res, "ERR_QUANTITY_OUT_OF_RANGE")


def test_existence_unknown_drug_fk_on_comparison(api):
    """PRD §2.7: "every path identifier and every foreign-key reference in the
    body must resolve to an existing resource, checked left-to-right, failing with
    ERR_NOT_FOUND on the first that does not."

    Design: Corner/validations/existence_unknown_drug_fk_on_comparison
    """
    member = create_member(email="ex2@x.com")
    headers = make_member_headers(member["id"])
    res = api.create_comparison(
        create_comparison_payload(member["id"], "00000000-0000-4000-8000-000000000999"),
        headers)
    validate_error(res, "ERR_NOT_FOUND")


# ─────────────────────────────────────────────────────────────────────────────
# Corner / endpoints
# ─────────────────────────────────────────────────────────────────────────────

def test_pagination_invalid_limit_rejected(api):
    """PRD §2.3: "A limit outside the inclusive range of 1 to 100, or a negative
    offset, is rejected with ERR_PAGINATION_INVALID."

    Design: Corner/endpoints/pagination_invalid_limit_rejected
    """
    res = api.list_drugs(ANON, params={"limit": 0})
    validate_error(res, "ERR_PAGINATION_INVALID")


def test_list_claims_filtered_by_discount_card_id(api):
    """PRD §2.8: "claims ... may each be filtered by the foreign keys they carry"
    and "Every relationship between resources is discovered by reading a
    resource's foreign-key field and then issuing a filtered list query."

    Design: Corner/endpoints/list_claims_filtered_by_discount_card_id
    """
    ctx = setup_submitted_claim(quantity=2, member_overrides={"email": "lc@x.com"})
    data, meta = validate_paginated(
        api.list_claims(OPERATOR, params={"discount_card_id": ctx["card"]["id"]}))
    assert meta["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Corner / errors — error_generic_validation_triggerable
# ─────────────────────────────────────────────────────────────────────────────

def test_link_withdrawn_copay_card_generic_validation(api):
    """PRD §3.8: "the referenced copay card must be ACTIVE — linking an EXHAUSTED
    or WITHDRAWN card is rejected with ERR_VALIDATION."

    Design: Corner/errors/error_generic_validation_triggerable
    """
    ctx = setup_submitted_claim(quantity=2, member_overrides={"email": "gv@x.com"})
    cc = create_copay_card(ctx["drug"]["id"])
    validate_success(api.withdraw_copay_card(cc["id"], SPONSOR), 200)
    headers = make_member_headers(ctx["member"]["id"])
    res = api.create_copay_link(
        create_copay_link_payload(cc["id"], ctx["member"]["id"], ctx["claim"]["id"]), headers)
    validate_error(res, "ERR_VALIDATION")


# ─────────────────────────────────────────────────────────────────────────────
# Corner / rbac
# ─────────────────────────────────────────────────────────────────────────────

def test_member_cannot_publish_price_quote(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to perform
    the requested operation is rejected with ERR_FORBIDDEN_ROLE." PRD §4:
    POST /price-quotes is authorized for PharmacyOperator, PlatformAdmin.

    Design: Corner/rbac/member_cannot_publish_price_quote
    """
    drug = create_drug()
    ph = create_pharmacy()
    member = create_member(email="rb@x.com")
    headers = make_member_headers(member["id"])
    res = api.create_price_quote(create_price_quote_payload(drug["id"], ph["id"]), headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_member_cannot_adjudicate_claim(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to perform
    the requested operation is rejected with ERR_FORBIDDEN_ROLE." PRD §4:
    POST /claims/{id}/adjudicate is authorized for PharmacyOperator only.

    Design: Corner/rbac/member_cannot_adjudicate_claim
    """
    ctx = setup_submitted_claim(quantity=2, member_overrides={"email": "ra@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    res = api.adjudicate_claim(ctx["claim"]["id"], headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_unauthenticated_unknown_role_rejected(api):
    """PRD §2.1: "A request that omits a required header, or carries an
    X-User-Role value that is not one of these five, is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/rbac/unauthenticated_protected_endpoint_rejected
    """
    drug = create_drug()
    member = create_member(email="un@x.com")
    bogus = make_role_headers("Ghost", member["id"])
    res = api.create_comparison(create_comparison_payload(member["id"], drug["id"]), bogus)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_member_revoke_other_members_gold_owner_check(api):
    """PRD §2.1: "When an entity-backed member acts on a resource they do not own,
    the request is rejected with ERR_NOT_RESOURCE_OWNER." PRD §3.5: revoke acts on
    the member's own membership.

    Design: Corner/rbac/member_revoke_other_members_gold_owner_check
    """
    from test_helpers import create_active_gold_member
    member_a, gm = create_active_gold_member(member_overrides={"email": "ao@x.com"})
    member_b = create_member(email="bo@x.com")
    res = api.revoke_gold_membership(
        gm["id"], {"member_id": member_b["id"]}, make_member_headers(member_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─────────────────────────────────────────────────────────────────────────────
# Corner / cross_cutting_complexity_layers
# ─────────────────────────────────────────────────────────────────────────────

def test_occ_correct_version_reverse_succeeds(api):
    """PRD §2.6: "The server compares this value against the claim's current
    version. If they match, the reversal proceeds". PRD §3.9: "On success the
    claim moves from ADJUDICATED to REVERSED".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_reverse_succeeds
    """
    ctx = setup_adjudicated_claim(quantity=2, member_overrides={"email": "occ@x.com"})
    reversed_claim = validate_success(api.reverse_claim(
        ctx["claim"]["id"], {"expected_claim_version": ctx["claim_version"]}, OPERATOR), 200)
    assert reversed_claim["status"] == "REVERSED"


def test_derived_active_gold_membership_id_set_on_payment(api):
    """PRD §3.5: "if the access dimension is currently INACTIVE it is set to
    ACTIVE, and the owning member's active_gold_membership_id is set to this
    membership's id (a derived-field reconciliation on the member)."

    Design: Corner/cross_cutting_complexity_layers/derived_active_gold_membership_id_set_on_payment
    """
    member = create_member(email="df@x.com")
    headers = make_member_headers(member["id"])
    gm = get_success_data(api.create_gold_membership(
        create_gold_membership_payload(member["id"]), headers))
    paid = validate_success(api.record_gold_payment(gm["id"], ADMIN), 200)
    assert paid["access_status"] == "ACTIVE"
    fresh = validate_success(api.get_member(member["id"], headers), 200)
    assert fresh["active_gold_membership_id"] == gm["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner / consistency_model — lifetime_savings_visible_immediately_after_adjudicate
# ─────────────────────────────────────────────────────────────────────────────

def test_lifetime_savings_visible_immediately_after_adjudicate(api):
    """PRD §3.7: "the owning member's lifetime_savings_cents is recomputed." PRD
    §2.10: "a member's lifetime_savings_cents is recomputed from that member's
    claims whenever a claim crosses an adjudication or reversal boundary". With
    qty=2, discount=5500, dispense=200: savings = 3000.

    Design: Corner/consistency_model/lifetime_savings_visible_immediately_after_adjudicate
    """
    ctx = setup_adjudicated_claim(quantity=2, member_overrides={"email": "im@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    member = validate_success(api.get_member(ctx["member"]["id"], headers), 200)
    assert member["lifetime_savings_cents"] == 3000
