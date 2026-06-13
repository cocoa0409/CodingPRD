"""Corner breadth tests for entity CRUD, defaults, computed fields,
type/required-field validation, immutability, and FK season cohesion.

Covers corner section: entities.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    setup_open_season, register_member, confirm_subscription, get_season_version,
    make_member_headers,
    create_season_payload, create_subscription_payload, create_member_payload,
    create_share_type_payload,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
)

FM = TEST_USERS["farm_manager_headers"]
DC = TEST_USERS["delivery_coordinator_headers"]


def test_create_season_returns_201_with_initial_fields(api):
    """PRD §3.1: "A new season begins in the `DRAFT` state, and its `confirmed_share_count` starts at 0."
    PRD §2.4: "The `version` field is an integer that begins at its initial value on creation and increments by one with every mutation".

    Design: Corner/entities/create_season_returns_201_with_all_fields
    """
    res = api_client.create_season(
        create_season_payload(name="Fall 2026", week_count=10,
                              first_delivery_date="2026-09-01T00:00:00Z",
                              signup_close_date="2026-08-25T00:00:00Z",
                              total_share_capacity=50), FM)
    season = validate_success(res, 201)
    assert season["status"] == "DRAFT"
    assert season["confirmed_share_count"] == 0
    assert season["version"] == 1


def test_get_season_not_found_returns_404(api):
    """PRD §2.6: "the parent in the path is resolved first, and if it does not exist the request fails immediately with `ERR_NOT_FOUND` (HTTP 404) for that parent".

    Design: Corner/entities/get_season_not_found_returns_404
    """
    res = api_client.get_season(NON_EXISTENT_UUID, FM)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_subscription_missing_share_type_id_rejected(api):
    """PRD §3.3: "A `Member` creates a **subscription** against an `OPEN` season by supplying the `season_id`, the `member_id` of the owning member, the chosen `share_type_id`, the `current_site_id` naming the assigned site or delivery zone".
    PRD §2.7: "Request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422)".

    Design: Corner/entities/create_subscription_missing_required_field_returns_invalid_request
    """
    base = setup_open_season(week_count=10, base_price_cents=50000)
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    payload = {
        "season_id": base["season"]["id"],
        "member_id": member["id"],
        "current_site_id": base["site"]["id"],
        # share_type_id deliberately omitted.
    }
    res = api_client.create_subscription(payload, mh)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_member_defaults_tier_to_baseline(api):
    """PRD §3.2: "The sliding-scale tier is the member's self-declared pay tier and is one of `SOLIDARITY`, `BASELINE`, or `SUSTAINER`, defaulting to `BASELINE` when omitted."
    PRD §3.2: "A newly registered member's `wallet_credit_cents` — the running credit balance, in cents, accrued from completed working-share shifts and refunded held weeks — starts at 0."

    Design: Corner/entities/create_member_default_sliding_scale_tier_baseline
    """
    res = api_client.create_member(
        {"email": "default-tier@example.com", "full_name": "Def"})
    member = validate_success(res, 201)
    assert member["sliding_scale_tier"] == "BASELINE"
    assert member["wallet_credit_cents"] == 0


def test_confirm_computes_season_price_for_solidarity(api):
    """PRD §3.3: "the member's pay-tier multiplier (0.80 for `SOLIDARITY`, 1.00 for `BASELINE`, 1.25 for `SUSTAINER`) is multiplied against the share type's `base_price_cents`, and the product is rounded half-up to a whole number of cents and stored as the subscription's `season_price_cents`."

    Design: Corner/entities/confirm_ignores_client_supplied_season_price_computes_it
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    member = register_member(tier="SOLIDARITY")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(base["season"]["id"], member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    confirmed = confirm_subscription(base["season"]["id"], sub["id"])
    # 50000 × 0.80 = 40000.
    assert confirmed["season_price_cents"] == 40000, (
        f"SOLIDARITY season_price expected 40000, got {confirmed['season_price_cents']}")


def test_create_share_type_invalid_size_enum_rejected(api):
    """PRD §3.1: "a `size` of `SMALL`, `MEDIUM`, or `LARGE".
    PRD §2.7: "Request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422)".

    Design: Corner/entities/create_share_type_invalid_size_enum_rejected
    """
    season = get_success_data(api_client.create_season(
        create_season_payload(name="S-enum", week_count=10,
                              first_delivery_date="2026-09-01T00:00:00Z",
                              signup_close_date="2026-08-25T00:00:00Z",
                              total_share_capacity=50), FM))
    res = api_client.create_share_type(
        create_share_type_payload(season["id"], size="JUMBO",
                                  base_price_cents=50000, items_per_box=8), FM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_ledger_entry_has_no_version_field(api):
    """PRD §2.4: "A `LedgerEntry` is an append-only record: once posted it is never modified. Accordingly, a `LedgerEntry` carries only `id` and `created_at` — it has no `updated_at` and no `version`."
    PRD §3.3: "A `CHARGE_SEASON` ledger entry is posted for that amount."

    Design: Corner/entities/ledger_entry_immutable_no_version_field
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(base["season"]["id"], member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    confirm_subscription(base["season"]["id"], sub["id"])

    data, _ = _list(api_client.list_ledger_entries(sub["id"], FM, params={"limit": 100}))
    charge = [e for e in data if e["entry_type"] == "CHARGE_SEASON"]
    assert charge, "expected a CHARGE_SEASON ledger entry"
    assert charge[0]["amount_cents"] == 50000
    for entry in data:
        assert "version" not in entry, "LedgerEntry must not expose a version field"
        assert "updated_at" not in entry, "LedgerEntry must not expose updated_at"


def test_subscription_share_type_from_other_season_rejected(api):
    """PRD §2.6: "When a subscription is created, its referenced `share_type_id` and `current_site_id` must each belong to the same `Season` named by `season_id".
    PRD §2.6: "A reference that points into a different season is rejected with `ERR_SEASON_MISMATCH` (HTTP 409)."

    Design: Corner/entities/flat_topology_fk_season_mismatch_share_type
    """
    season_a = setup_open_season(week_count=10, base_price_cents=50000,
                                 signup_close_date="2026-12-25T00:00:00Z")
    # Season B with its own share type.
    season_b = get_success_data(api_client.create_season(
        create_season_payload(name="SeasonB", week_count=10,
                              first_delivery_date="2026-09-01T00:00:00Z",
                              signup_close_date="2026-12-25T00:00:00Z",
                              total_share_capacity=50), FM))
    share_b = get_success_data(api_client.create_share_type(
        create_share_type_payload(season_b["id"], size="MEDIUM",
                                  base_price_cents=50000, items_per_box=8), FM))
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])

    res = api_client.create_subscription(
        create_subscription_payload(season_a["season"]["id"], member["id"],
                                    share_b["id"], season_a["site"]["id"]), mh)
    validate_error(res, ApiErrorId.ERR_SEASON_MISMATCH.value)


def _list(res):
    body = res.json()
    return body.get("data", []), body.get("meta", {})
