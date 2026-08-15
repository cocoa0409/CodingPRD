"""Claim intake, policy terms, claim listing, and claim lifecycle basics.

Covers claim creation snapshots, required fields, enum and existence checks,
the policy-period closed interval, pagination, the computed financial summary,
and the manual claim transition edges.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid,
    NON_EXISTENT_UUID, ApiErrorId,
    make_carrier, make_customer, make_policy, make_claim,
    create_claim_payload, create_customer_payload,
    read_claim, transition_claim,
    TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


def _policy_with_flat_deductible(policy_number="POL-1", **policy_overrides):
    carrier = make_carrier(name="Acme Mutual", tax_rate=0.07)
    customer = make_customer(full_name="Pat Homeowner", email="pat@example.com")
    policy = make_policy(customer["id"], carrier["id"],
                         policy_number=policy_number,
                         coverage_a_limit_cents=100000000,
                         deductible_type="FLAT", flat_deductible_cents=100000,
                         recoverable_depreciation=True, **policy_overrides)
    return carrier, customer, policy


def test_claim_creation_snapshots_deductible_and_initial_state(api):
    """PRD §3.2: "At creation the system copies the policy's `customer_id` onto the
    claim for ownership checks and snapshots the deductible into `deductible_cents`:
    for a `FLAT` policy the snapshot is `flat_deductible_cents`"
    PRD §3.2: "A new claim starts in `INTAKE` status with all money aggregates at
    zero and `payment_posture` `UNPAID`."

    Design: Corner/entities/claim_creation_snapshots_deductible_and_initial_state
    """
    _, customer, policy = _policy_with_flat_deductible()
    res = api.create_claim(create_claim_payload(policy["id"], cause_of_loss="WATER",
                                                date_of_loss="2026-03-10T00:00:00Z"),
                           ADMIN)
    claim = validate_success(res, 201)
    assert claim["status"] == "INTAKE"
    assert claim["version"] == 1
    assert claim["deductible_cents"] == 100000, "FLAT deductible snapshot"
    assert claim["customer_id"] == customer["id"], "customer_id copied from policy"
    assert claim["rcv_total_cents"] == 0, "no APPROVED estimates yet"


def test_claim_missing_policy_id_returns_invalid_request(api):
    """PRD §3.2: "Opening a claim takes a `policy_id`, a `cause_of_loss` of `WATER`,
    `FIRE`, `WIND`, `MOLD`, or `HAIL`, a `date_of_loss`, and an optional
    `loss_address` (defaulting to an empty string)."
    PRD §2.7: "**Payload shape and basic constraints** — required fields present;
    types and enum memberships valid; `qty` and `amount_cents` strictly positive;
    `effective_to` strictly later than `effective_from`; `scheduled_end` strictly
    later than `scheduled_start`; the deductible field matching the policy's
    `deductible_type`; photo parent and tag consistency (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/claim_missing_policy_id_returns_invalid_request
    """
    res = api.create_claim({"cause_of_loss": "WATER",
                            "date_of_loss": "2026-03-10T00:00:00Z"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_invalid_enum_cause_of_loss_returns_invalid_request(api):
    """PRD §3.2: "Opening a claim takes a `policy_id`, a `cause_of_loss` of `WATER`,
    `FIRE`, `WIND`, `MOLD`, or `HAIL`, a `date_of_loss`, and an optional
    `loss_address` (defaulting to an empty string)."
    PRD §2.7: "**Payload shape and basic constraints** — required fields present;
    types and enum memberships valid; `qty` and `amount_cents` strictly positive;
    `effective_to` strictly later than `effective_from`; `scheduled_end` strictly
    later than `scheduled_start`; the deductible field matching the policy's
    `deductible_type`; photo parent and tag consistency (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/invalid_enum_cause_of_loss_returns_invalid_request
    """
    _, _, policy = _policy_with_flat_deductible()
    res = api.create_claim(create_claim_payload(policy["id"], cause_of_loss="ALIEN"),
                           ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_claim_get_with_unknown_id_not_found(api):
    """PRD §2.6: "Identifiers appearing in a URL path are validated in strict
    left-to-right order: the first identifier that does not resolve to an existing
    resource rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), before
    any later identifier or any business rule is examined."

    Design: Corner/entities/claim_get_with_unknown_id_not_found
    """
    res = api.get_claim(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_system_fields_input_ignored_on_create(api):
    """PRD §2.5: "`id` (string): a unique, server-generated identifier formatted as
    a UUID, with no type prefix."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by 1
    on every mutation of the resource"

    Design: Corner/entities/system_fields_input_ignored_on_create
    """
    forged_id = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    payload = create_customer_payload(full_name="Pat Homeowner",
                                      email="pat@example.com")
    payload["id"] = forged_id
    payload["version"] = 99
    customer = validate_success(api.create_customer(payload, ADMIN), 201)
    assert is_valid_uuid(customer["id"])
    assert customer["id"] != forged_id, "server mints its own id"
    assert customer["version"] == 1


def test_ordinance_limit_min_of_pct_and_cap(api):
    """PRD §3.2: "From these the policy's `ordinance_limit_cents` is computed once:
    the ordinance coverage percentage multiplied by `coverage_a_limit_cents`,
    rounded half up to integer cents, taken as the lesser value against the flat
    cap."

    Design: Corner/entities/ordinance_limit_min_of_pct_and_cap
    """
    carrier = make_carrier(name="Acme Mutual", tax_rate=0.07)
    customer = make_customer(full_name="Sam Owner", email="sam@example.com")
    # percentage governs: round(0.10 * 2,500,000) = 250,000 < cap 300,000
    p1 = validate_success(api.create_policy(
        {"customer_id": customer["id"], "carrier_id": carrier["id"],
         "policy_number": "POL-M1", "coverage_a_limit_cents": 2500000,
         "deductible_type": "FLAT", "flat_deductible_cents": 50000,
         "recoverable_depreciation": True, "ordinance_coverage_pct": 0.10,
         "ordinance_flat_cap_cents": 300000,
         "period_start": "2026-01-01T00:00:00Z",
         "period_end": "2026-12-31T23:59:59Z"}, ADMIN), 201)
    assert p1["ordinance_limit_cents"] == 250000
    # cap governs: min(250,000, 100,000) = 100,000
    p2 = validate_success(api.create_policy(
        {"customer_id": customer["id"], "carrier_id": carrier["id"],
         "policy_number": "POL-M2", "coverage_a_limit_cents": 2500000,
         "deductible_type": "FLAT", "flat_deductible_cents": 50000,
         "recoverable_depreciation": True, "ordinance_coverage_pct": 0.10,
         "ordinance_flat_cap_cents": 100000,
         "period_start": "2026-01-01T00:00:00Z",
         "period_end": "2026-12-31T23:59:59Z"}, ADMIN), 201)
    assert p2["ordinance_limit_cents"] == 100000


def test_loss_date_outside_policy_period_rejected(api):
    """PRD §3.2: "The `date_of_loss` must fall inside the policy period as a closed
    interval — on or after `period_start` and on or before `period_end` — or the
    creation is rejected with `ERR_POLICY_WINDOW_VIOLATION` (HTTP 422)."

    Design: Corner/validations/loss_date_outside_policy_period_rejected
    """
    _, _, policy = _policy_with_flat_deductible()
    # one second before period_start 2026-01-01 -> outside the closed interval
    res = api.create_claim(create_claim_payload(
        policy["id"], cause_of_loss="WATER",
        date_of_loss="2025-12-31T23:59:59Z"), ADMIN)
    validate_error(res, ApiErrorId.ERR_POLICY_WINDOW_VIOLATION)
    # exactly period_start is covered (closed interval)
    ok = validate_success(api.create_claim(create_claim_payload(
        policy["id"], cause_of_loss="WATER",
        date_of_loss="2026-01-01T00:00:00Z"), ADMIN), 201)
    assert is_valid_uuid(ok["id"])


def test_claims_list_pagination_and_status_filter(api):
    """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.3: "Most list endpoints also accept optional equality filters drawn from
    the resource's own fields — for example, claims filter by `policy_id`,
    `customer_id`, or `status`"

    Design: Corner/endpoints/claims_list_pagination_and_status_filter
    """
    _, _, policy = _policy_with_flat_deductible()
    make_claim(policy["id"], cause_of_loss="WATER",
               date_of_loss="2026-03-10T00:00:00Z")
    make_claim(policy["id"], cause_of_loss="FIRE",
               date_of_loss="2026-04-15T00:00:00Z")

    data, meta = validate_paginated(
        api.list_claims(ADJUSTER, params={"policy_id": policy["id"], "limit": 1}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api.list_claims(ADJUSTER, params={"policy_id": policy["id"],
                                          "status": "COMPLETE"}))
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_financial_summary_computed_read(api):
    """PRD §3.9: "A computed financial summary per claim exposes `rcv_total_cents`,
    `acv_total_cents`, `grand_total_cents`, `depreciation_total_cents`,
    `recoverable_depreciation_cents`, `deductible_cents`,
    `deductible_collected_cents`, `carrier_paid_cents`, `customer_paid_cents`,
    `outstanding_balance_cents`, `ordinance_limit_cents`,
    `ordinance_consumed_cents`, and `payment_posture` in one read."
    PRD §3.2: "A new claim starts in `INTAKE` status with all money aggregates at
    zero and `payment_posture` `UNPAID`."

    Design: Corner/endpoints/financial_summary_computed_read
    """
    _, _, policy = _policy_with_flat_deductible(
        ordinance_coverage_pct=0.10, ordinance_flat_cap_cents=250000)
    claim = make_claim(policy["id"], cause_of_loss="WATER",
                       date_of_loss="2026-03-10T00:00:00Z")
    summary = validate_success(api.get_financial_summary(claim["id"], ADJUSTER), 200)
    assert summary["rcv_total_cents"] == 0
    assert summary["carrier_paid_cents"] == 0
    assert summary["payment_posture"] == "UNPAID"
    assert summary["deductible_cents"] == 100000
    assert summary["ordinance_limit_cents"] == 250000
    assert summary["ordinance_consumed_cents"] == 0


def test_claim_skip_state_transition_rejected(api):
    """PRD §3.2: "Any target state that is not a declared edge from the current
    state is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/claim_skip_state_transition_rejected
    """
    _, _, policy = _policy_with_flat_deductible()
    claim = make_claim(policy["id"], cause_of_loss="WATER",
                       date_of_loss="2026-03-10T00:00:00Z")
    # INTAKE -> ESTIMATING is not a declared edge
    res = api.transition_claim(claim["id"], {"to": "ESTIMATING"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert read_claim(claim["id"])["status"] == "INTAKE"


def test_withdrawn_claim_terminal_lockdown(api):
    """PRD §3.2: "`CLOSED`, `DENIED`, and `WITHDRAWN` are terminal."
    PRD §3.2: "Any target state that is not a declared edge from the current state
    is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/withdrawn_claim_terminal_lockdown
    """
    _, _, policy = _policy_with_flat_deductible()
    claim = make_claim(policy["id"], cause_of_loss="WATER",
                       date_of_loss="2026-03-10T00:00:00Z")
    withdrawn = transition_claim(claim["id"], "WITHDRAWN")
    assert withdrawn["status"] == "WITHDRAWN"
    res = api.transition_claim(claim["id"], {"to": "ASSESSING"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
