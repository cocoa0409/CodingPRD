"""ChargeItem creation defaults, server-minted system fields and independent read dimensions."""
from test_helpers import (
    api_client, validate_success, factories,
    setup_base, reprice_item, read_item, set_clock,
    is_valid_uuid, is_iso8601_timestamp,
    assert_charge_item,
    ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
        "rounding_mode": "NEAREST_CENT",
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
        "allowed_revenue_code_values": [],
    },
)


def _setup():
    set_clock("2026-09-01T00:00:00Z")
    return setup_base(**MERCY)


def _item_payload(base, **overrides):
    return factories.create_charge_item_payload(
        base["facility"]["id"], base["department"]["id"], base["revenue_code"]["id"],
        **overrides
    )


def test_creation_lands_in_draft_and_price_stale_with_an_untouched_pricing_dimension():
    """PRD §3.3: "A newly created item lands in `DRAFT` in the lifecycle dimension and
    `PRICE_STALE` in the pricing dimension, with `gross_charge_cents` at 0,
    `prior_gross_charge_cents` at 0, `price_conflict` false, `applied_price_rule_id` null
    (nothing has been priced yet), `duplicate_of_item_id` null, `approved_by_user_id` null,
    `last_code_cycle_id` null, and `version` 1."
    PRD §3.3: "`companion_window_hours` defaults to 24 when omitted, and
    `companion_required_item_id` is null when no pairing applies."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that
    starts with `req_`."

    Design: Corner/entities/charge_item_creation_returns_draft_stale_zero_gross_version_one
    """
    base = _setup()
    resp = api_client.create_charge_item(
        _item_payload(
            base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
            code_type="CPT", code_value="93458", cost_basis_cents=100000,
            medicare_rate_cents=50000, market_p75_cents=900000,
            effective_from="2026-09-01T00:00:00Z",
        ),
        ANALYST,
    )
    item = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")

    assert_charge_item(item)
    assert item["lifecycle_status"] == "DRAFT"
    assert item["price_status"] == "PRICE_STALE"
    assert item["gross_charge_cents"] == 0
    assert item["prior_gross_charge_cents"] == 0
    assert item["applied_price_rule_id"] is None, "nothing has been priced yet"
    assert item["price_conflict"] is False
    assert item["duplicate_of_item_id"] is None
    assert item["companion_required_item_id"] is None
    assert item["companion_window_hours"] == 24, "the declared default when omitted"
    assert item["version"] == 1


def test_the_read_reports_both_state_dimensions_independently_after_a_reprice():
    """PRD §3.3: "It sets `lifecycle_status` to `PENDING_REVIEW` and touches nothing in the
    pricing dimension: the two dimensions are independent and this transition does not read or
    write `price_status`."
    PRD §3.2: "Under `COST_PLUS_MARKUP`, the applicable tier is the last tier in the ascending
    `markup_tiers` array whose `min_cost_basis_cents` is at or below the item's
    `cost_basis_cents` — the boundary is inclusive, so a cost basis exactly equal to a tier's
    threshold selects *that* tier rather than the one below it — and the base is the item's
    `cost_basis_cents` multiplied by the selected tier's `markup_bp`, divided by 10000, rounded
    half up."
    PRD §2.4: "Most entities additionally carry `updated_at` (same format as `created_at`,
    refreshed on every mutation) and `version` (an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row)."

    Design: Corner/entities/charge_item_retrieval_returns_both_state_dimensions_and_version
    """
    base = _setup()
    created = validate_success(
        api_client.create_charge_item(
            _item_payload(
                base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                code_type="CPT", code_value="93458", cost_basis_cents=100000,
                medicare_rate_cents=50000, market_p75_cents=900000,
                effective_from="2026-09-01T00:00:00Z",
            ),
            ANALYST,
        ),
        201,
    )
    reprice_item(created["id"])

    item = read_item(created["id"])
    assert item["cdm_number"] == "CDM-1001"
    assert item["lifecycle_status"] == "DRAFT", (
        "repricing moves only the pricing dimension"
    )
    assert item["price_status"] == "PRICED_CURRENT"
    assert item["gross_charge_cents"] == 240000, (
        "100000 cents of cost sits in the 24000bp band, and the 60000-cent Medicare floor and "
        "990000-cent market cap both leave it alone"
    )
    assert item["prior_gross_charge_cents"] == 0
    assert item["applied_price_rule_id"] == base["price_rule"]["id"]
    assert item["price_conflict"] is False
    assert item["version"] == 2, "one create plus one reprice"


def test_system_fields_are_server_minted_rather_than_client_supplied():
    """PRD §2.4: "Every resource carries a server-minted `id` formatted as a UUID with no type
    prefix; clients never supply an `id`. Every resource also carries a `created_at` timestamp,
    an ISO 8601 UTC value with three fractional digits, recorded from the logical clock at the
    moment of creation."
    PRD §3.3: "A newly created item lands in `DRAFT` in the lifecycle dimension and `PRICE_STALE`
    in the pricing dimension, with `gross_charge_cents` at 0, `prior_gross_charge_cents` at 0,
    `price_conflict` false, `applied_price_rule_id` null (nothing has been priced yet),
    `duplicate_of_item_id` null, `approved_by_user_id` null, `last_code_cycle_id` null, and
    `version` 1."
    PRD §3.3: "Optionally it carries `code_value`, the CPT or HCPCS code string, which may be
    null only when `code_type` is `REV_ONLY` or `CDM_INTERNAL`."

    Design: Corner/entities/charge_item_system_fields_are_server_minted_not_client_supplied
    """
    base = _setup()
    item = validate_success(
        api_client.create_charge_item(
            _item_payload(
                base, cdm_number="CDM-2001", description="GENERIC LAB PANEL",
                code_type="REV_ONLY", code_value=None, cost_basis_cents=4000,
                medicare_rate_cents=1000, market_p75_cents=90000,
                effective_from="2026-10-01T00:00:00Z",
            ),
            ANALYST,
        ),
        201,
    )
    assert is_valid_uuid(item["id"]), "a UUID with no type prefix"
    assert is_iso8601_timestamp(item["created_at"])
    assert item["created_at"].startswith("2026-09-01T00:00:00"), (
        "created_at is read from the logical clock, not from wall-clock time"
    )
    assert item["updated_at"].startswith("2026-09-01T00:00:00")
    assert item["version"] == 1
    assert item["lifecycle_status"] == "DRAFT", "no lifecycle_status was ever supplied"
    assert item["price_status"] == "PRICE_STALE"
    assert item["approved_by_user_id"] is None
    assert item["last_code_cycle_id"] is None
    assert item["code_value"] is None, "REV_ONLY items may carry a null code_value"
    assert item["effective_from"].startswith("2026-10-01T00:00:00"), (
        "a forward-dated effective_from is legal; only back-dating is refused"
    )
