"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the runner re-launches the server before every test, so each test
starts against an empty database and the logical clock's startup default of
2026-05-01T00:00:00Z). Setup calls use get_success_data() so a setup failure
surfaces as a clear "Setup step failed" error naming the API error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_assign_payload,
    create_check_item_payload,
    create_claim_payload,
    create_clearing_bank_payload,
    create_code_payload,
    create_freeze_payload,
    create_recredit_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS, make_adjustment_analyst_headers

ADMIN = TEST_USERS["operations_admin_headers"]
PROCESSOR = TEST_USERS["item_processor_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SERVICE = TEST_USERS["customer_service_headers"]


def analyst(user_id: str = "analyst-1") -> dict:
    """AdjustmentAnalyst headers for a specific opaque analyst id."""
    return make_adjustment_analyst_headers(user_id)


# ─── Tier 0: primitives ─────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Drive the logical clock forward (PRD §2.4). Returns {current_utc}."""
    return get_success_data(api_client.set_logical_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_clearing_bank(**overrides) -> dict:
    return get_success_data(api_client.create_clearing_bank(create_clearing_bank_payload(**overrides), ADMIN))


def create_account(**overrides) -> dict:
    return get_success_data(api_client.create_account(create_account_payload(**overrides), ADMIN))


def create_check_item(account_id: str, clearing_bank_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_check_item(
            create_check_item_payload(account_id, clearing_bank_id, **overrides), PROCESSOR
        )
    )


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, ADMIN))


def get_check_item(item_id: str) -> dict:
    return get_success_data(api_client.get_check_item(item_id, ADMIN))


# ─── Tier 1: list/lookup helpers ────────────────────────────────────────────

def list_cases_for_item(item_id: str, **params) -> list:
    data, _meta = validate_paginated(
        api_client.list_item_adjustment_cases(item_id, ADMIN, params=params or None)
    )
    return data


def get_first_case_for_item(item_id: str, case_type: str | None = None) -> dict:
    params = {"case_type": case_type} if case_type else {}
    cases = list_cases_for_item(item_id, **params)
    assert cases, f"Setup expected at least one adjustment case for item {item_id}"
    return cases[0]


def list_claims_for_case(case_id: str, **params) -> list:
    data, _meta = validate_paginated(
        api_client.list_case_claims(case_id, ADMIN, params=params or None)
    )
    return data


def get_first_claim_for_case(case_id: str) -> dict:
    claims = list_claims_for_case(case_id)
    assert claims, f"Setup expected at least one adjustment claim for case {case_id}"
    return claims[0]


def list_warranties_for_case(case_id: str, **params) -> list:
    data, _meta = validate_paginated(
        api_client.list_case_warranty_claims(case_id, ADMIN, params=params or None)
    )
    return data


def list_fees(**params) -> list:
    data, _meta = validate_paginated(api_client.list_fees(ADMIN, params=params or None))
    return data


def get_fee_for_return_event(return_event_id: str) -> dict:
    fees = list_fees(return_event_id=return_event_id)
    assert fees, f"Setup expected a fee for return event {return_event_id}"
    return fees[0]


def list_notifications(**params) -> list:
    data, _meta = validate_paginated(api_client.list_notifications(ADMIN, params=params or None))
    return data


def list_ledger_entries(**params) -> list:
    data, _meta = validate_paginated(api_client.list_ledger_entries(ADMIN, params=params or None))
    return data


def sum_ledger_entries(**params) -> int:
    return sum(entry["amount_cents"] for entry in list_ledger_entries(**params))


def list_hold_decisions(item_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_hold_decisions(item_id, ADMIN))
    return data


# ─── Tier 2: item lifecycle progression ──────────────────────────────────────

def setup_presented_item(
    amount_cents: int = 100000,
    encoded_amount_cents: int | None = None,
    image_quality_score: int = 90,
    opening_balance_cents: int = 0,
    risk_tier: str = "STANDARD",
    reg_cc_eligible: bool = True,
    bank_overrides: dict | None = None,
    item_reference: str | None = None,
) -> dict:
    """Account + clearing bank + one item deposited and presented.

    Returns {"account", "bank", "item"}. Item lands in PRESENTED unless a
    duplicate branch fires. Default amount/encoded match and a clean image
    score, so no defect cases are created unless overridden.
    """
    bank = create_clearing_bank(**(bank_overrides or {}))
    account = create_account(
        opening_balance_cents=opening_balance_cents,
        risk_tier=risk_tier,
        reg_cc_eligible=reg_cc_eligible,
    )
    item_kwargs = {
        "amount_cents": amount_cents,
        "encoded_amount_cents": (
            encoded_amount_cents if encoded_amount_cents is not None else amount_cents
        ),
        "image_quality_score": image_quality_score,
    }
    if item_reference is not None:
        item_kwargs["item_reference"] = item_reference
    item = create_check_item(account["id"], bank["id"], **item_kwargs)
    presented = get_success_data(api_client.present_check_item(item["id"], PROCESSOR))
    return {"account": account, "bank": bank, "item": presented}


def setup_paid_item(**kwargs) -> dict:
    """Presented item then paid. Returns ctx with item in PAID."""
    ctx = setup_presented_item(**kwargs)
    ctx["item"] = get_success_data(api_client.pay_check_item(ctx["item"]["id"], PROCESSOR))
    return ctx


def setup_returned_item(**kwargs) -> dict:
    """Presented item then returned. Adds return_event and return_case."""
    ctx = setup_presented_item(**kwargs)
    ctx["return_event"] = get_success_data(
        api_client.create_return_event(ctx["item"]["id"], PROCESSOR)
    )
    ctx["return_case"] = get_first_case_for_item(ctx["item"]["id"], case_type="RETURN_ITEM")
    return ctx


def setup_coded_return(reason_code: str = "NSF", **kwargs) -> dict:
    """Returned item whose return event is coded. Adds coded event and fee."""
    ctx = setup_returned_item(**kwargs)
    ctx["return_event"] = get_success_data(
        api_client.code_return_event(ctx["return_event"]["id"], create_code_payload(reason_code=reason_code), PROCESSOR)
    )
    ctx["fee"] = get_fee_for_return_event(ctx["return_event"]["id"])
    return ctx


# ─── Tier 3: case / claim lifecycle ──────────────────────────────────────────

def setup_encoding_error_claim(
    amount_cents: int = 100000,
    encoded_amount_cents: int = 90000,
    **kwargs,
) -> dict:
    """Encoding-mismatch presentment: ENCODING_ERROR case (OPEN) plus its
    auto-created DRAFT AdjustmentClaim (claimed = |encoded - amount|)."""
    ctx = setup_presented_item(
        amount_cents=amount_cents, encoded_amount_cents=encoded_amount_cents, **kwargs
    )
    ctx["case"] = get_first_case_for_item(ctx["item"]["id"], case_type="ENCODING_ERROR")
    ctx["claim"] = get_first_claim_for_case(ctx["case"]["id"])
    return ctx


def assign_case(case_id: str, analyst_id: str = "analyst-1") -> dict:
    """Assign a case, reading the live version first (OCC per PRD §2.9)."""
    current = get_success_data(api_client.get_adjustment_case(case_id, ADMIN))
    return get_success_data(
        api_client.assign_adjustment_case(
            case_id,
            create_assign_payload(analyst_id, current["version"]),
            ADMIN,
        )
    )


def setup_assigned_encoding_claim(analyst_id: str = "analyst-1", **kwargs) -> dict:
    ctx = setup_encoding_error_claim(**kwargs)
    ctx["case"] = assign_case(ctx["case"]["id"], analyst_id)
    return ctx


def setup_submitted_claim(analyst_id: str = "analyst-1", **kwargs) -> dict:
    """Encoding-error case ASSIGNED and its auto claim SUBMITTED."""
    ctx = setup_assigned_encoding_claim(analyst_id=analyst_id, **kwargs)
    ctx["claim"] = get_success_data(
        api_client.submit_adjustment_claim(ctx["claim"]["id"], analyst(analyst_id))
    )
    return ctx


def setup_acknowledged_claim(analyst_id: str = "analyst-1", **kwargs) -> dict:
    ctx = setup_submitted_claim(analyst_id=analyst_id, **kwargs)
    ctx["claim"] = get_success_data(
        api_client.acknowledge_adjustment_claim(ctx["claim"]["id"], {}, ADMIN)
    )
    return ctx


def setup_denied_claim(analyst_id: str = "analyst-1", settler_id: str = "analyst-1", **kwargs) -> dict:
    """Claim walked to DENIED. The auto claim's creator is the literal 'system',
    so any analyst id satisfies the segregation rule on settle."""
    ctx = setup_acknowledged_claim(analyst_id=analyst_id, **kwargs)
    ctx["claim"] = get_success_data(
        api_client.settle_adjustment_claim(
            ctx["claim"]["id"], {"outcome": "DENIED"}, analyst(settler_id)
        )
    )
    return ctx


def setup_resolved_case_with_denied_claim(**kwargs) -> dict:
    """Denied claim plus its case RESOLVED (NO_ACTION) — ready for write-off
    and bubble-up closure tests."""
    ctx = setup_denied_claim(**kwargs)
    ctx["case"] = get_success_data(
        api_client.resolve_adjustment_case(
            ctx["case"]["id"], {"disposition": "NO_ACTION"}, analyst("analyst-1")
        )
    )
    return ctx


# ─── Tier 4: large items, holds, warranties ──────────────────────────────────

def setup_large_item_under_review(amount_cents: int = 600000, **kwargs) -> dict:
    """Deposit at/above the large-item threshold: item UNDER_REVIEW with an
    auto PENDING HoldDecision (source AUTO_LARGE_ITEM)."""
    bank = create_clearing_bank(**kwargs.pop("bank_overrides", {}) or {})
    account = create_account(**kwargs)
    item = create_check_item(account["id"], bank["id"], amount_cents=amount_cents)
    assert item["status"] == "UNDER_REVIEW", (
        f"Setup expected large item to be UNDER_REVIEW, got {item['status']}"
    )
    holds = list_hold_decisions(item["id"])
    assert holds, "Setup expected an auto hold decision for the large item"
    return {"account": account, "bank": bank, "item": item, "hold": holds[0]}


def setup_image_warranty_case(score: int = 50, **kwargs) -> dict:
    """Item with image_quality_score below 60 presented: IMAGE_WARRANTY case OPEN."""
    ctx = setup_presented_item(image_quality_score=score, **kwargs)
    ctx["case"] = get_first_case_for_item(ctx["item"]["id"], case_type="IMAGE_WARRANTY")
    return ctx


# ─── Tier 5: recredit lifecycle ──────────────────────────────────────────────

def setup_recredit_submitted(claim_amount_cents: int = 100000, item_amount_cents: int = 200000, **kwargs) -> dict:
    """PAID item plus a SUBMITTED recredit request (CustomerService intake)."""
    kwargs.setdefault("reg_cc_eligible", True)
    ctx = setup_paid_item(amount_cents=item_amount_cents, **kwargs)
    ctx["recredit"] = get_success_data(
        api_client.create_recredit_request(
            create_recredit_payload(
                ctx["account"]["id"], ctx["item"]["id"], claimed_amount_cents=claim_amount_cents
            ),
            SERVICE,
        )
    )
    return ctx


def setup_recredit_provisioned(**kwargs) -> dict:
    ctx = setup_recredit_submitted(**kwargs)
    ctx["recredit"] = get_success_data(
        api_client.grant_provisional_credit(ctx["recredit"]["id"], SERVICE)
    )
    return ctx
