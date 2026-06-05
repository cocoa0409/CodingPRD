"""Entity creation, defaults, system fields, listing, immutability, and the
computed-read calculations (tiered award, sub-threshold withholding, ledger
balance).

Queue B (Corner): entities, calculations sections.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    fixtures,
    ApiErrorId,
)
from test_helpers.api_client import api_client

ADMIN = fixtures.ADMIN
ADMINISTRATOR = fixtures.ADMINISTRATOR
CONTROLLER = fixtures.CONTROLLER


# ─── entities ────────────────────────────────────────────────────────────
def test_create_settlement_returns_201_with_computed_net():
    """PRD §3.1: "On creation the settlement is born in `DRAFT`, its `net_distributable_cents` is computed immediately, and both `allocated_cents` and `residual_cents` begin at 0."
    PRD §2.8: "The `net_distributable_cents` is the gross fund minus the attorney fee minus the administration cost"

    Design: Corner/entities/create_settlement_returns_201_with_computed_net
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    result = validate_success(api_client.create_settlement({
        "case_caption": "In re Create",
        "gross_fund_cents": 1000000,
        "attorney_fee_cents": 250000,
        "admin_cost_cents": 50000,
        "distribution_method": "PRO_RATA",
        "claim_filing_deadline": "2026-02-01T00:00:00Z",
        "objection_deadline": "2026-01-20T00:00:00Z",
        "cy_pres_floor_cents": 0,
    }, ADMIN), expected_status=201)
    assert result["net_distributable_cents"] == 700000
    assert result["status"] == "DRAFT"
    assert result["allocated_cents"] == 0
    assert result["residual_cents"] == 0


def test_get_settlement_not_found_returns_404():
    """PRD §2.5: "A request against a path-referenced settlement (or any other primary path resource) that does not exist is rejected with `ERR_SETTLEMENT_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_settlement_not_found_returns_404
    """
    resp = api_client.get_settlement("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value)


def test_create_settlement_missing_gross_fund_returns_422():
    """PRD §2.11: "Any create or transition endpoint that declares required body fields rejects a request missing one of them with `ERR_MISSING_REQUIRED_FIELD` (HTTP 422)."

    Design: Corner/entities/create_settlement_missing_gross_fund_returns_422
    """
    resp = api_client.create_settlement({
        "case_caption": "In re Missing",
        "attorney_fee_cents": 0,
        "admin_cost_cents": 0,
        "distribution_method": "PRO_RATA",
        "claim_filing_deadline": "2026-02-01T00:00:00Z",
        "objection_deadline": "2026-01-20T00:00:00Z",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_FIELD.value)


def test_create_settlement_invalid_distribution_method_enum_returns_422():
    """PRD §2.11: "Any endpoint that accepts an enum-typed body field — `distribution_method`, `claimant_tier`, `channel`, `delivery_status`, `reason_code`, `form_type`, or the objection `ruling` — rejects a value outside that field's declared set with `ERR_INVALID_ENUM` (HTTP 422)."

    Design: Corner/entities/create_settlement_invalid_distribution_method_enum_returns_422
    """
    resp = api_client.create_settlement({
        "case_caption": "In re Enum",
        "gross_fund_cents": 100000,
        "attorney_fee_cents": 0,
        "admin_cost_cents": 0,
        "distribution_method": "BOGUS",
        "claim_filing_deadline": "2026-02-01T00:00:00Z",
        "objection_deadline": "2026-01-20T00:00:00Z",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_member_claimant_tier_default_applied():
    """PRD §3.2: "an optional `claimant_tier` (either `TIER_A` or `TIER_B`, defaulting to `TIER_B`)"
    PRD §3.2: "A member is born in `NOTIFIED` with a `notice_count` of 0."

    Design: Corner/entities/member_claimant_tier_default_applied
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(case_caption="In re Default")
    result = validate_success(api_client.create_class_member(
        settlement["id"], {"full_name": "M", "email": "m@x.com"}, ADMINISTRATOR
    ), expected_status=201)
    assert result["claimant_tier"] == "TIER_B"
    assert result["status"] == "NOTIFIED"


def test_member_status_and_notice_count_system_minted():
    """PRD §3.2: "A member is born in `NOTIFIED` with a `notice_count` of 0."

    Design: Corner/entities/member_id_system_minted_input_ignored
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(case_caption="In re Sys")
    result = get_success_data(api_client.create_class_member(
        settlement["id"], {"full_name": "M", "email": "m@x.com", "tin_on_file": True}, ADMINISTRATOR
    ))
    assert result["status"] == "NOTIFIED"
    assert result["notice_count"] == 0


def test_list_settlements_pagination_envelope():
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_settlements_pagination_envelope
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    fixtures.create_settlement(case_caption="S1")
    fixtures.create_settlement(case_caption="S2")
    data, meta = validate_paginated(api_client.list_settlements(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert len(data) == 1
    assert meta["has_more"] is True


def test_notice_record_is_append_only_and_bumps_notice_count():
    """PRD §2.4: "A `NoticeRecord` and a `LedgerEntry` are immutable audit rows: each carries only an `id` and a `created_at`. Neither has an `updated_at` and neither has a `version`, because neither is ever mutated after it is written"
    PRD §3.2: "Each recorded notice creates a `NoticeRecord` referencing the member through `class_member_id` and increments that member's `notice_count` by one."

    Design: Corner/entities/notice_record_immutable_no_version_field
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(case_caption="In re Immutable")
    member = fixtures.register_member(settlement["id"], full_name="M", email="m@x.com", tin_on_file=True)
    result = validate_success(api_client.create_notice(
        member["id"], {"channel": "EMAIL", "delivery_status": "DELIVERED"}, ADMINISTRATOR
    ), expected_status=201)
    assert "version" not in result
    assert "updated_at" not in result
    refreshed = get_success_data(api_client.get_class_member(member["id"], ADMINISTRATOR))
    assert refreshed["notice_count"] == 1


# ─── calculations ────────────────────────────────────────────────────────
def test_tiered_award_full_flat_within_fund():
    """PRD §3.6: "a claim whose member's `claimant_tier` is `TIER_A` receives `tier_a_amount_cents`, and a claim whose member's tier is `TIER_B` receives `tier_b_amount_cents`."

    Design: Corner/calculations/tiered_award_full_flat_amounts_within_fund
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="TIERED",
        gross_fund_cents=760000,
        attorney_fee_cents=100000,
        admin_cost_cents=100000,
        tier_a_amount_cents=250000,
        tier_b_amount_cents=150000,
        cy_pres_floor_cents=0,
        members=[
            {"email": "x@x.com", "full_name": "X", "claimant_tier": "TIER_A", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "y@x.com", "full_name": "Y", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "z@x.com", "full_name": "Z", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
        ],
    )
    cx, cy, _cz = ctx["claims"]

    def gross(claim_id):
        data, _ = validate_paginated(api_client.list_payments(CONTROLLER, params={"claim_id": claim_id}))
        return data[0]["gross_amount_cents"]

    assert gross(cx["id"]) == 250000
    assert gross(cy["id"]) == 150000
    assert ctx["batch"]["planned_total_cents"] == 550000


def test_withholding_below_threshold_at_59999_not_applied_corner():
    """PRD §3.6: "For every other claim the withholding is 0. Each payment's `amount_cents` — the net cents that will actually debit the fund — is its gross minus its withholding."

    Design: Corner/calculations/withholding_below_threshold_at_59999_not_applied
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=59999,
        members=[{"email": "m@x.com", "full_name": "M", "tin_on_file": False, "claimed_loss_cents": 59999, "recognized_loss_cents": 59999}],
    )
    data, _ = validate_paginated(
        api_client.list_payments(CONTROLLER, params={"claim_id": ctx["claims"][0]["id"]}))
    assert data[0]["withholding_cents"] == 0
    assert data[0]["amount_cents"] == 59999


def test_ledger_balance_after_open_notice_equals_net():
    """PRD §2.7: "the ledger accumulates: the gross fund as a positive `FUND_OPEN` entry; the attorney fee and the administration cost as negative `FEE_DEBIT` and `ADMIN_DEBIT` entries; one negative `PAYMENT_DEBIT` per committed payment"
    PRD §2.7: "returns it alongside the fund's `net_distributable_cents`, `allocated_cents`, and `residual_cents`."

    Design: Corner/calculations/ledger_balance_computed_read_after_open_notice
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(
        gross_fund_cents=100000, attorney_fee_cents=25000, admin_cost_cents=5000,
        cy_pres_floor_cents=0, case_caption="In re Bal",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    bal = get_success_data(api_client.get_ledger_balance(s_id, CONTROLLER))
    assert bal["balance_cents"] == 70000
    assert bal["net_distributable_cents"] == 70000
    assert bal["allocated_cents"] == 0
