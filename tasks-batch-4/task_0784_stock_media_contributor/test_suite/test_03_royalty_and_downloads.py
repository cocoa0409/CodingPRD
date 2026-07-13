"""Royalty-rate snapshot, the royalty matrix/cap, career levels, and download reads."""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    TEST_USERS,
    register_contributor, onboard_active_contributor, get_contributor,
    create_license_tier, create_accepted_asset, create_download,
    add_exclusivity_window, add_earning_adjustment,
    assert_download,
)

FINANCE = TEST_USERS["finance_headers"]


def test_download_snapshots_computed_terms(api):
    """PRD §3.4: "`royalty_amount_cents` is the contributor's locked earning, computed as
    `sale_price_cents` multiplied by `royalty_rate_snapshot_pct`, rounded to the nearest whole
    cent using round half up. The download begins in `earning_status` `PENDING`".

    Design: Corner/entities/corner_download_computed_fields_ignore_client_input
    """
    create_license_tier(api, code="STANDARD", base_price_cents=1000)
    c = onboard_active_contributor(api, tax_id="US-1")
    asset = create_accepted_asset(api, c["id"])
    dl = create_download(api, asset["id"], "STANDARD")  # non-exclusive BRONZE -> 0.15
    assert_download(dl)
    assert dl["sale_price_cents"] == 1000
    assert dl["royalty_rate_snapshot_pct"] == 0.15
    assert dl["royalty_amount_cents"] == 150
    assert dl["earning_status"] == "PENDING"


def test_royalty_level_lower_bound_is_inclusive(api):
    """PRD §3.5: "a lifetime of exactly 25,000 cents is `SILVER`, while 24,999 cents is still
    `BRONZE`, because the lower bound is inclusive."

    Design: Corner/entities/corner_royalty_level_boundary_24999_vs_25000
    """
    cx = register_contributor(api, display_name="X")
    add_earning_adjustment(api, cx["id"], 24999, reason="s")
    cy = register_contributor(api, display_name="Y")
    add_earning_adjustment(api, cy["id"], 25000, reason="s")
    assert get_contributor(api, cx["id"])["royalty_level"] == "BRONZE"
    assert get_contributor(api, cy["id"])["royalty_level"] == "SILVER"


def test_list_downloads_filtered_by_asset(api):
    """PRD §3.4: "Downloads may be read individually and listed and filtered by `asset_id` or
    `contributor_id`."

    Design: Corner/endpoints/corner_reverse_fk_downloads_by_asset
    """
    create_license_tier(api, code="STANDARD", base_price_cents=1000)
    c = onboard_active_contributor(api, tax_id="US-10")
    asset = create_accepted_asset(api, c["id"])
    dl = create_download(api, asset["id"], "STANDARD")
    data, _meta = validate_paginated(api.list_downloads(FINANCE, params={"asset_id": asset["id"]}))
    assert any(d["id"] == dl["id"] for d in data), "the asset's download must appear in the filtered list"


def test_available_at_is_startup_clock_plus_30_days(api):
    """PRD §2.5: "On server startup the clock reads exactly `2026-03-01T00:00:00Z`".
    PRD §3.4: "its `available_at` — the earliest instant its earning may settle — is set to the
    download's `created_at` plus a clearing period of 30 days."

    Design: Corner/endpoints/corner_clock_default_before_set
    """
    create_license_tier(api, code="STANDARD", base_price_cents=1000)
    c = onboard_active_contributor(api, tax_id="US-CLK")
    asset = create_accepted_asset(api, c["id"])
    dl = create_download(api, asset["id"], "STANDARD")  # created at the untouched startup clock
    assert dl["available_at"][:10] == "2026-03-31", "startup 2026-03-01 + 30 days == 2026-03-31"


def test_royalty_amount_locked_from_download_time_snapshot(api):
    """PRD §3.4: "`royalty_rate_snapshot_pct` is locked by the royalty-rate calculation below using
    the contributor's `exclusivity` and `royalty_level` **as they stand at that instant**".

    Design: Difficulty/dual_variant_calc/royalty_locked_vs_current_level
    """
    create_license_tier(api, code="ENHANCED", base_price_cents=1500)
    c = onboard_active_contributor(api, tax_id="US-111")
    add_exclusivity_window(api, c["id"])  # EXCLUSIVE over the default clock
    asset = create_accepted_asset(api, c["id"])
    dl = create_download(api, asset["id"], "ENHANCED")  # EXCLUSIVE + BRONZE -> 0.25
    assert dl["royalty_rate_snapshot_pct"] == 0.25
    assert dl["royalty_amount_cents"] == 375, "round_half_up(1500 * 0.25)"


def test_locked_royalty_survives_later_level_change(api):
    """PRD §3.4: "any later change to the contributor's exclusivity or royalty level leaves
    already-recorded downloads untouched; the persisted `royalty_amount_cents` is the authoritative
    earning and is never recomputed against the contributor's current level."

    Design: Difficulty/dual_variant_calc/royalty_locked_vs_current_level
    """
    create_license_tier(api, code="ENHANCED", base_price_cents=1500)
    c = onboard_active_contributor(api, tax_id="US-112")
    add_exclusivity_window(api, c["id"])
    asset = create_accepted_asset(api, c["id"])
    dl = create_download(api, asset["id"], "ENHANCED")
    add_earning_adjustment(api, c["id"], 25000, reason="signing bonus")  # lifetime 25000 -> SILVER
    assert get_contributor(api, c["id"])["royalty_level"] == "SILVER"
    reread = get_success_data(api.get_download(dl["id"], FINANCE))
    assert reread["royalty_amount_cents"] == 375, "locked value stays 375, not the SILVER re-derivation 450"


def test_royalty_rate_matrix_exclusive_platinum_editorial_capped(api):
    """PRD §3.4: "the locked `royalty_rate_snapshot_pct` is the smaller of 0.45 and the sum of the
    matrix base rate and the editorial bonus."

    Design: Difficulty/combinatorial_formula/royalty_rate_matrix_exclusive_editorial_cap
    """
    create_license_tier(api, code="STANDARD", base_price_cents=1000)
    c = onboard_active_contributor(api, tax_id="US-333")
    add_exclusivity_window(api, c["id"])
    add_earning_adjustment(api, c["id"], 500000, reason="career backfill")  # PLATINUM
    asset = create_accepted_asset(api, c["id"], content_category="EDITORIAL", perceptual_hash="bbbb")
    dl = create_download(api, asset["id"], "STANDARD")
    assert dl["royalty_rate_snapshot_pct"] == 0.45, "0.40 (EXCLUSIVE PLATINUM) + 0.05 editorial, capped at 0.45"


def test_royalty_amount_at_capped_rate(api):
    """PRD §3.4: "`royalty_amount_cents` is the contributor's locked earning, computed as
    `sale_price_cents` multiplied by `royalty_rate_snapshot_pct`, rounded to the nearest whole
    cent using round half up."

    Design: Difficulty/combinatorial_formula/royalty_rate_matrix_exclusive_editorial_cap
    """
    create_license_tier(api, code="STANDARD", base_price_cents=1000)
    c = onboard_active_contributor(api, tax_id="US-334")
    add_exclusivity_window(api, c["id"])
    add_earning_adjustment(api, c["id"], 500000, reason="career backfill")
    assert get_contributor(api, c["id"])["royalty_level"] == "PLATINUM"
    asset = create_accepted_asset(api, c["id"], content_category="EDITORIAL", perceptual_hash="bbbb")
    dl = create_download(api, asset["id"], "STANDARD")
    assert dl["royalty_amount_cents"] == 450, "round_half_up(1000 * 0.45)"
