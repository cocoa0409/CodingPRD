"""Corrosion coupons: exposure/rating boundary, closed-interval plus buffer
conflict semantics, weight-gain allowance, minimum exposure."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_asset,
    create_rack,
    install_coupon,
    remove_coupon,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

CHEMIST = TEST_USERS["chemist_headers"]


def _account_asset(account_name):
    account = create_account(account_name=account_name)
    asset = create_asset(account["id"], asset_type="COOLING_TOWER",
                         recirculation_rate_gpm=300, system_volume_gal=6000)
    return account, asset


def test_coupon_exposure_exactly_30_days_is_reliable(api):
    """PRD §3.6: "Finally, the `rating` is set: `RELIABLE` when
    `exposure_days` is at least 30 — exactly 30 days is reliable — and
    `UNRELIABLE` below that." "The coupon's `corrosion_rate_mpy` is then
    computed: the weight loss in grams (`pre_weight_g` minus `post_weight_g`)
    multiplied by 22,300, divided by the product of `density_g_cm3`,
    `area_in2`, and `exposure_days`, stored to 3 decimal places rounded
    half up."

    Design: Difficulty/boundary_precision_check/coupon_exposure_exactly_30_days_is_reliable
    """
    set_clock("2026-08-01T00:00:00Z")
    _, asset = _account_asset("Coupon Co 30")
    rack = create_rack(asset["id"], position_count=4)
    coupon = install_coupon(rack["id"], 1, "2026-08-01T00:00:00Z",
                            density_g_cm3=7.87, area_in2=5.4, pre_weight_g=50.0)

    set_clock("2026-08-31T00:00:00Z")
    removed = remove_coupon(coupon["id"], 49.82)
    assert removed["status"] == "REMOVED"
    assert removed["exposure_days"] == 30
    assert removed["rating"] == "RELIABLE"
    # (50.0 - 49.82) * 22300 / (7.87 * 5.4 * 30) = 3.148 mpy (3dp).
    assert removed["corrosion_rate_mpy"] == pytest.approx(3.148, abs=1e-3)


def test_coupon_exposure_29_days_is_unreliable(api):
    """PRD §3.6: "the `rating` is set: `RELIABLE` when `exposure_days` is at
    least 30 — exactly 30 days is reliable — and `UNRELIABLE` below that."
    "`exposure_days` is the elapsed time from `installed_at` to `removed_at`
    rounded down to whole days of 86,400 seconds".

    Design: Difficulty/boundary_precision_check/coupon_exposure_exactly_30_days_is_reliable
    """
    set_clock("2026-08-01T00:00:00Z")
    _, asset = _account_asset("Coupon Co 29")
    rack = create_rack(asset["id"], position_count=4)
    coupon = install_coupon(rack["id"], 1, "2026-08-01T00:00:00Z",
                            density_g_cm3=7.87, area_in2=5.4, pre_weight_g=50.0)

    set_clock("2026-08-30T00:00:00Z")
    removed = remove_coupon(coupon["id"], 49.82)
    assert removed["exposure_days"] == 29
    assert removed["rating"] == "UNRELIABLE"
    # (50.0 - 49.82) * 22300 / (7.87 * 5.4 * 29) = 3.257 mpy (3dp).
    assert removed["corrosion_rate_mpy"] == pytest.approx(3.257, abs=1e-3)


def test_coupon_install_inside_repassivation_buffer_rejected(api):
    """PRD §3.6: "a new coupon conflicts — and is rejected with
    `ERR_COUPON_INTERVAL_CONFLICT` — when any existing coupon on the same rack
    and `position_index` is still `INSTALLED` (an installed coupon's interval
    is treated as open-ended), or when the new `installed_at` is earlier than
    an existing removed coupon's `removed_at` plus seven days of
    re-passivation buffer."

    Design: Difficulty/resource_temporal_overlap/coupon_interval_closed_plus_7day_buffer_adjacency_forbidden
    """
    set_clock("2026-08-01T00:00:00Z")
    _, asset = _account_asset("Buffer Co")
    rack = create_rack(asset["id"], rack_code="RK-B", position_count=2)
    first = install_coupon(rack["id"], 1, "2026-08-01T00:00:00Z",
                           alloy="COPPER", density_g_cm3=8.96, pre_weight_g=40.0)
    set_clock("2026-08-10T00:00:00Z")
    removed = remove_coupon(first["id"], 39.9)
    assert removed["exposure_days"] == 9  # 2026-08-01 -> 2026-08-10

    # 6 days 23 hours after removal: inside the 7-day buffer.
    set_clock("2026-08-17T00:00:00Z")
    resp = api_client.install_coupon(
        rack["id"],
        {
            "position_index": 1,
            "alloy": "COPPER",
            "density_g_cm3": 8.96,
            "area_in2": 5.4,
            "pre_weight_g": 40.0,
            "installed_at": "2026-08-16T23:00:00Z",
        },
        CHEMIST,
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_INTERVAL_CONFLICT)
    assert resp.status_code == 409


def test_coupon_install_exactly_at_buffer_end_allowed(api):
    """PRD §3.6: "Adjacency is not allowed here: the new `installed_at` must
    be at or after the previous coupon's `removed_at` plus the full seven-day
    buffer."

    Design: Difficulty/resource_temporal_overlap/coupon_interval_closed_plus_7day_buffer_adjacency_forbidden
    """
    set_clock("2026-08-01T00:00:00Z")
    _, asset = _account_asset("Buffer Co 2")
    rack = create_rack(asset["id"], rack_code="RK-B2", position_count=2)
    first = install_coupon(rack["id"], 1, "2026-08-01T00:00:00Z",
                           alloy="COPPER", density_g_cm3=8.96, pre_weight_g=40.0)
    set_clock("2026-08-10T00:00:00Z")
    remove_coupon(first["id"], 39.9)

    # Exactly removed_at + 7 days: the boundary is inclusive ("at or after").
    set_clock("2026-08-17T00:00:00Z")
    second = validate_success(
        api_client.install_coupon(
            rack["id"],
            {
                "position_index": 1,
                "alloy": "COPPER",
                "density_g_cm3": 8.96,
                "area_in2": 5.4,
                "pre_weight_g": 40.0,
                "installed_at": "2026-08-17T00:00:00Z",
            },
            CHEMIST,
        ),
        expected_status=201,
    )
    assert second["status"] == "INSTALLED"


def test_coupon_weight_gain_beyond_allowance_rejected(api):
    """PRD §3.6: "the request carries the `post_weight_g`, which must be
    strictly positive and must not exceed `pre_weight_g` plus a 2.0-gram
    deposit allowance — a heavier coupon beyond that allowance is rejected
    with `ERR_COUPON_WEIGHT_GAIN`."

    Design: Corner/validations/coupon_weight_gain_beyond_allowance_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    _, asset = _account_asset("Gain Co")
    rack = create_rack(asset["id"], position_count=2)
    coupon = install_coupon(rack["id"], 1, "2026-08-01T00:00:00Z", pre_weight_g=50.0)

    set_clock("2026-08-20T00:00:00Z")
    resp = api_client.remove_coupon(coupon["id"], {"post_weight_g": 52.01}, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_COUPON_WEIGHT_GAIN)
    assert resp.status_code == 422

    after = validate_success(api_client.list_coupons(rack["id"], CHEMIST))
    assert after[0]["status"] == "INSTALLED"


def test_exposure_under_one_day_rejected(api):
    """PRD §3.6: "the exposure must total at least one full day, failing with
    `ERR_EXPOSURE_TOO_SHORT` otherwise."

    Design: Corner/validations/exposure_under_one_day_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    _, asset = _account_asset("Short Co")
    rack = create_rack(asset["id"], position_count=2)
    coupon = install_coupon(rack["id"], 1, "2026-08-01T00:00:00Z",
                            alloy="COPPER", density_g_cm3=8.96, pre_weight_g=40.0)

    set_clock("2026-08-01T12:00:00Z")  # 12 hours of exposure: floor(0.5 day) == 0
    resp = api_client.remove_coupon(coupon["id"], {"post_weight_g": 39.9}, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_EXPOSURE_TOO_SHORT)
    assert resp.status_code == 422
