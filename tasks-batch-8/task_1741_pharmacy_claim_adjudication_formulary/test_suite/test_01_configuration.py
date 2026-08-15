"""Benefit configuration: plan/drug/member creation defaults, uniqueness, FK integrity."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    NON_EXISTENT_UUID,
    assert_plan, assert_drug, assert_member,
    create_plan_payload, create_drug_payload, create_formulary_entry_payload,
    create_member_payload,
    make_plan, make_drug, make_formulary_entry,
)


class TestPlanCreation:
    def test_plan_creation_defaults(self, api, pbm_admin_headers):
        """PRD §3.1: "A plan is born in `DRAFT` status."
        PRD §2.4: "`version` (integer): a system-managed integer that increments by one
        on every mutation."

        Design: Corner/entities/plan_creation_defaults_and_missing_field_rejected
        """
        res = api.create_plan(
            create_plan_payload(
                name="P-NEW",
                deductible_cents=15000,
                oop_max_cents=100000,
                assistance_model="ACCUMULATOR",
                member_min_pay_cents=500,
                card_fill_cap_cents=0,
                dispensing_fee_cents=200,
            ),
            pbm_admin_headers,
        )
        plan = validate_success(res, 201)
        assert_plan(plan)
        assert plan["status"] == "DRAFT", f"New plan must be DRAFT, got {plan['status']}"
        assert plan["version"] == 1, f"New plan version must be 1, got {plan['version']}"
        assert plan["deductible_cents"] == 15000

    def test_plan_missing_oop_max_rejected(self, api, pbm_admin_headers):
        """PRD §2.6: "required fields are present, integers parse, enumerations are
        valid, quantities and day supplies are positive, dates are valid ISO dates with
        start not after end, and structure-conditional fields are present exactly when
        required; violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `PbmAdmin` creates a plan by supplying a `name`, an annual
        individual `deductible_cents`, an annual `oop_max_cents`, a flat
        `dispensing_fee_cents` added to every claim's allowed amount, and the plan's
        copay-assistance posture"

        Design: Corner/entities/plan_creation_defaults_and_missing_field_rejected
        """
        payload = create_plan_payload(name="P-BAD", deductible_cents=15000)
        del payload["oop_max_cents"]
        res = api.create_plan(payload, pbm_admin_headers)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_drug_creation_defaults(api, pbm_admin_headers):
    """PRD §3.1: "and an optional `is_specialty` flag (default false) marking the drug
    as restricted to specialty-channel dispensing."

    Design: Corner/entities/drug_creation_defaults
    """
    payload = {
        "ndc": "00000-9001",
        "name": "Plainex",
        "therapeutic_class": "EMOLLIENT",
        "unit_cost_cents": 250,
        "max_daily_dose_units": 6,
    }
    drug = validate_success(api.create_drug(payload, pbm_admin_headers), 201)
    assert_drug(drug)
    assert drug["is_specialty"] is False, "Omitted is_specialty must default to false"
    assert drug["version"] == 1


def test_member_creation_defaults(api, pbm_admin_headers):
    """PRD §3.2: "A member is born `ACTIVE`; the computed accumulators
    `deductible_paid_cents` and `oop_paid_cents` start at 0, and `oop_max_reached`
    starts false."
    PRD §3.2: "`card_drug_id` names the drug the card covers (null, or omitted, means
    the member holds no card) and `card_balance_cents` seeds the card's remaining funds
    (defaulting to 0, never negative)."

    Design: Corner/entities/member_creation_defaults
    """
    plan = make_plan(
        name="P-MDF",
        deductible_cents=1000,
        oop_max_cents=5000,
        assistance_model="MAXIMIZER",
        member_min_pay_cents=0,
        card_fill_cap_cents=1000,
        dispensing_fee_cents=100,
    )
    member = validate_success(
        api.create_member(
            create_member_payload(
                plan["id"],
                external_ref="M-NEW",
                full_name="New Pat",
                eligibility_start_date="2026-01-01",
                eligibility_end_date="2026-12-31",
            ),
            pbm_admin_headers,
        ),
        201,
    )
    assert_member(member)
    assert member["status"] == "ACTIVE"
    assert member["deductible_paid_cents"] == 0
    assert member["oop_paid_cents"] == 0
    assert member["oop_max_reached"] is False
    assert member["card_balance_cents"] == 0
    assert member["card_drug_id"] is None


def test_claim_get_not_found_returns_404(api, pbm_admin_headers):
    """PRD §2.7: "The first identifier that fails to resolve determines the error: an
    unknown plan yields `ERR_PLAN_NOT_FOUND`, an unknown drug (whether referenced as
    `drug_id`, `step_drug_id`, or `card_drug_id`) yields `ERR_DRUG_NOT_FOUND`, an unknown
    member yields `ERR_MEMBER_NOT_FOUND`, an unknown pharmacy yields
    `ERR_PHARMACY_NOT_FOUND`, an unknown claim yields `ERR_CLAIM_NOT_FOUND`, an unknown
    prior authorization yields `ERR_PA_NOT_FOUND`, an unknown audit yields
    `ERR_AUDIT_NOT_FOUND`, and an unknown formulary entry yields
    `ERR_FORMULARY_ENTRY_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/claim_get_not_found_returns_404
    """
    res = api.get_claim(NON_EXISTENT_UUID, pbm_admin_headers)
    validate_error(res, "ERR_CLAIM_NOT_FOUND", expected_status=404)


def test_formulary_entry_duplicate_plan_drug_rejected(api, pbm_admin_headers):
    """PRD §3.1: "The pairing of plan and drug is unique across all statuses: adding a
    second entry for the same `plan_id` and `drug_id` is rejected with
    `ERR_DUPLICATE_FORMULARY_ENTRY` (HTTP 409), even if the first entry has since gone
    `INACTIVE`."

    Design: Corner/entities/formulary_entry_duplicate_plan_drug_rejected
    """
    plan = make_plan(name="P-DUP")
    drug = make_drug(ndc="00000-9002", name="Duplix", unit_cost_cents=100,
                     max_daily_dose_units=10)
    first = make_formulary_entry(
        plan["id"], drug["id"], tier=1, quantity_limit_per_fill=30,
        max_days_supply=30, copay_type="FLAT", copay_flat_cents=100,
    )
    res = api.create_formulary_entry(
        create_formulary_entry_payload(
            plan["id"], drug["id"], tier=2, quantity_limit_per_fill=60,
            max_days_supply=60, copay_type="FLAT", copay_flat_cents=200,
        ),
        pbm_admin_headers,
    )
    validate_error(res, "ERR_DUPLICATE_FORMULARY_ENTRY", expected_status=409)
    after = get_success_data(api.get_formulary_entry(first["id"], pbm_admin_headers))
    assert after["tier"] == 1, "First entry must be unchanged after rejected duplicate"
    assert after["copay_flat_cents"] == 100


def test_member_with_unknown_plan_rejected(api, pbm_admin_headers):
    """PRD §2.7: "an unknown plan yields `ERR_PLAN_NOT_FOUND`" (HTTP 404).

    Design: Corner/entities/member_with_unknown_plan_rejected
    """
    res = api.create_member(
        create_member_payload(
            NON_EXISTENT_UUID,
            external_ref="M-ORPHAN",
            full_name="Orphan Pat",
            eligibility_start_date="2026-01-01",
            eligibility_end_date="2026-12-31",
        ),
        pbm_admin_headers,
    )
    validate_error(res, "ERR_PLAN_NOT_FOUND", expected_status=404)
    data, meta = validate_paginated(api.list_members(pbm_admin_headers))
    assert meta["total_count"] == 0, f"No member may be persisted, got {meta['total_count']}"
