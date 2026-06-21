"""Payload factories — one per entity, input fields only.

All factories accept **overrides so tests can pin only what they care about.
"""


def create_household_payload(case_number="CA-100000", state_code="CA",
                             address_line="1 Test St", heap_recipient=None,
                             **overrides) -> dict:
    payload = {
        "case_number": case_number,
        "state_code": state_code,
        "address_line": address_line,
    }
    if heap_recipient is not None:
        payload["heap_recipient"] = heap_recipient
    payload.update(overrides)
    return payload


def create_household_member_payload(household_id, full_name="Test Member",
                                    date_of_birth="1980-01-01",
                                    relationship="HEAD",
                                    monthly_earned_income_cents=None,
                                    monthly_unearned_income_cents=None,
                                    disabled=None,
                                    **overrides) -> dict:
    payload = {
        "household_id": household_id,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "relationship": relationship,
    }
    if monthly_earned_income_cents is not None:
        payload["monthly_earned_income_cents"] = monthly_earned_income_cents
    if monthly_unearned_income_cents is not None:
        payload["monthly_unearned_income_cents"] = monthly_unearned_income_cents
    if disabled is not None:
        payload["disabled"] = disabled
    payload.update(overrides)
    return payload


def create_application_payload(household_id, **overrides) -> dict:
    payload = {"household_id": household_id}
    payload.update(overrides)
    return payload


def create_monthly_allotment_payload(household_id, benefit_month,
                                     **overrides) -> dict:
    payload = {
        "household_id": household_id,
        "benefit_month": benefit_month,
    }
    payload.update(overrides)
    return payload


def create_eligible_item_category_payload(code, name=None, eligible=True,
                                          **overrides) -> dict:
    payload = {
        "code": code,
        "name": name if name is not None else code.title().replace("_", " "),
        "eligible": eligible,
    }
    payload.update(overrides)
    return payload


def create_purchase_transaction_payload(ebt_card_id, merchant_id="M001",
                                        line_items=None, **overrides) -> dict:
    payload = {
        "ebt_card_id": ebt_card_id,
        "merchant_id": merchant_id,
        "line_items": line_items if line_items is not None
        else [{"category_code": "FRESH_PRODUCE", "amount_cents": 5000, "quantity": 1}],
    }
    payload.update(overrides)
    return payload


def create_fraud_flag_payload(household_id, trigger_rule="VELOCITY_SPIKE",
                              **overrides) -> dict:
    payload = {
        "household_id": household_id,
        "trigger_rule": trigger_rule,
    }
    payload.update(overrides)
    return payload


def create_abawd_waiver_payload(household_member_id, quarter="2026-Q3",
                                county_unemployment_pct=10.00,
                                monthly_work_hours=0, **overrides) -> dict:
    payload = {
        "household_member_id": household_member_id,
        "quarter": quarter,
        "county_unemployment_pct": county_unemployment_pct,
        "monthly_work_hours": monthly_work_hours,
    }
    payload.update(overrides)
    return payload


def create_emergency_allotment_payload(state_code, benefit_month,
                                       min_supplement_cents=None,
                                       **overrides) -> dict:
    payload = {
        "state_code": state_code,
        "benefit_month": benefit_month,
    }
    if min_supplement_cents is not None:
        payload["min_supplement_cents"] = min_supplement_cents
    payload.update(overrides)
    return payload
