"""Optimistic concurrency: the two write paths guarded against a parent's version."""
from test_helpers import (
    CASE_MANAGER,
    ApiErrorId,
    make_liaison_headers,
    read_episode,
    read_episode_version,
    read_referral,
    seed_dme_supplier,
    setup_broadcast_referral,
    setup_screened_episode,
    validate_error,
    validate_paginated,
    validate_success,
)

LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}


def _offer_body(version, **overrides):
    body = {
        "expected_referral_version": version,
        "bed_unit_code": "UNIT-A",
        "bed_available_from": "2026-08-05T00:00:00Z",
        "hold_expires_at": "2026-08-12T00:00:00Z",
        "daily_rate_cents": 30000,
    }
    body.update(overrides)
    return body


def test_a_bed_offer_carrying_a_stale_referral_version_is_rejected(api):
    """PRD §2.5: "Creating a bed offer against a referral requires the request body to
    carry `expected_referral_version`, a non-optional field holding the `version` of the
    target `Referral` as the liaison last observed it. If `expected_referral_version` does
    not equal that referral's current `version`, the create is rejected with
    `ERR_STALE_REFERRAL_VERSION` (HTTP 412)."
    PRD §3.4: "A created offer starts with `status` of `OFFERED`, copies the referral's
    current `round_index` into its own `round_index`, increments the provider's
    `held_bed_units` and `offers_submitted_count` by one each, computes its cost projection
    as described in §3.5, and advances the referral's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_referral_version_on_offer_create_returns_412
    """
    env = setup_broadcast_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-G001", "full_name": "Lev Jarrah", "date_of_birth": "1944-07-07",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    stale_version = env["referral_version"]

    first = validate_success(
        api.create_offer(
            env["referral"]["id"], _offer_body(stale_version),
            make_liaison_headers(env["provider_a"]["id"]),
        ),
        201,
    )
    assert first["status"] == "OFFERED"
    assert read_referral(env["referral"]["id"])["version"] == stale_version + 1

    response = api.create_offer(
        env["referral"]["id"],
        _offer_body(
            stale_version, bed_available_from="2026-08-06T00:00:00Z",
            hold_expires_at="2026-08-13T00:00:00Z", daily_rate_cents=28000,
        ),
        make_liaison_headers(env["provider_b"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_STALE_REFERRAL_VERSION, 412)
    from test_helpers import read_provider

    birch = read_provider(env["provider_b"]["id"])
    assert birch["held_bed_units"] == 0
    assert birch["offers_submitted_count"] == 0

    refreshed = read_referral(env["referral"]["id"], make_liaison_headers(env["provider_b"]["id"]))
    retry = validate_success(
        api.create_offer(
            env["referral"]["id"],
            _offer_body(
                refreshed["version"], bed_available_from="2026-08-06T00:00:00Z",
                hold_expires_at="2026-08-13T00:00:00Z", daily_rate_cents=28000,
            ),
            make_liaison_headers(env["provider_b"]["id"]),
        ),
        201,
    )
    assert retry["status"] == "OFFERED"
    _, meta = validate_paginated(
        api.list_offers(CASE_MANAGER, params={"referral_id": env["referral"]["id"]})
    )
    assert meta["total_count"] == 2


def test_a_logistics_order_carrying_a_stale_episode_version_is_rejected(api):
    """PRD §2.5: "Creating a logistics order against an episode requires the request body
    to carry `expected_episode_version`, a non-optional field holding the `version` of the
    target `Episode` as the case manager last observed it. If `expected_episode_version`
    does not equal that episode's current `version`, the create is rejected with
    `ERR_STALE_EPISODE_VERSION` (HTTP 412)."
    PRD §3.7: "An order is created in `REQUESTED` status with `cancel_reason` null, and
    creating one is a planning artifact, so an episode at `SCREENED` advances to `PLANNING`;
    the episode's `version` advances by one."
    PRD §3.7: "For a `DME_DELIVERY` order the cost is a flat published rate keyed on
    `item_code`: a hospital bed costs 45000 cents, an oxygen concentrator 32000 cents, a
    wheelchair 21000 cents, a walker 8000 cents, and a CPAP unit 27000 cents."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_episode_version_on_logistics_create_returns_412
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-G002", "full_name": "Mei Kessler", "date_of_birth": "1943-08-08",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    supplier = seed_dme_supplier()
    episode_id = env["episode"]["id"]
    stale_version = read_episode_version(episode_id)

    first = validate_success(
        api.create_logistics_order(
            episode_id,
            {
                "expected_episode_version": stale_version, "order_type": "DME_DELIVERY",
                "supplier_provider_id": supplier["id"], "item_code": "WALKER",
                "window_start": "2026-08-02T09:00:00Z",
                "window_end": "2026-08-02T12:00:00Z",
            },
            CASE_MANAGER,
        ),
        201,
    )
    assert first["cost_cents"] == 8000

    response = api.create_logistics_order(
        episode_id,
        {
            "expected_episode_version": stale_version, "order_type": "DME_DELIVERY",
            "supplier_provider_id": supplier["id"], "item_code": "CPAP",
            "window_start": "2026-08-02T13:00:00Z",
            "window_end": "2026-08-02T15:00:00Z",
        },
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_STALE_EPISODE_VERSION, 412)
    _, meta = validate_paginated(
        api.list_logistics_orders(CASE_MANAGER, params={"episode_id": episode_id})
    )
    assert meta["total_count"] == 1, "the stale create left no second order behind"

    retry = validate_success(
        api.create_logistics_order(
            episode_id,
            {
                "expected_episode_version": read_episode_version(episode_id),
                "order_type": "DME_DELIVERY", "supplier_provider_id": supplier["id"],
                "item_code": "CPAP", "window_start": "2026-08-02T13:00:00Z",
                "window_end": "2026-08-02T15:00:00Z",
            },
            CASE_MANAGER,
        ),
        201,
    )
    assert retry["cost_cents"] == 27000
    assert read_episode(episode_id)["logistics_committed_cents"] == 0, (
        "both orders are still REQUESTED and therefore uncommitted"
    )
