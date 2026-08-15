"""Concentration add-on boundary precision and house-policy recompute."""
from test_helpers import (
    api_client,
    create_security_profile,
    get_account,
    place_order,
    post_mark,
    post_marks_both,
    setup_funded_account,
    TEST_USERS,
    validate_success,
)


def test_concentration_share_exactly_at_threshold_no_addon(api):
    """PRD §3.5: "A long position is "concentrated" when its market value
    multiplied by ten thousand strictly exceeds the security's
    `concentration_threshold_bps` multiplied by the account's gross long market
    value on the same basis ..."

    Design: Difficulty/boundary_precision_check/concentration_share_exactly_60pct_no_addon
    """
    abc = create_security_profile(symbol="ABC", concentration_threshold_bps=6000)
    xyz = create_security_profile(symbol="XYZ", concentration_threshold_bps=6000)
    post_marks_both(abc["id"], 10_000)
    post_marks_both(xyz["id"], 10_000)
    customer, account_id = setup_funded_account(1_200_000)
    place_order(account_id, customer["id"], abc["id"], "BUY", 60)  # mv 600000
    place_order(account_id, customer["id"], xyz["id"], "BUY", 40)  # mv 400000
    account = get_account(account_id)
    # ABC share exactly 6000bps: 600000*10000 == 6000*1000000 -> not strictly
    # greater -> no add-on; each line at flat house 3000bps.
    assert account["house_req_realtime_cents"] == 300_000


def test_concentration_share_one_cent_above_threshold_applies_addon(api):
    """PRD §3.5: "A concentrated long adds 1,000 basis points when its share
    stays at or under seventy-five percent of gross long market value —
    precisely, when its market value times ten thousand is less than or equal
    to 7,500 times the gross long market value — and adds 2,000 basis points
    when strictly above that band."

    Design: Difficulty/boundary_precision_check/concentration_share_exactly_60pct_no_addon
    """
    abc = create_security_profile(symbol="ABC", concentration_threshold_bps=6000)
    xyz = create_security_profile(symbol="XYZ", concentration_threshold_bps=6000)
    post_marks_both(abc["id"], 10_000)
    post_marks_both(xyz["id"], 10_000)
    customer, account_id = setup_funded_account(1_200_000)
    place_order(account_id, customer["id"], abc["id"], "BUY", 60)
    place_order(account_id, customer["id"], xyz["id"], "BUY", 40)
    # One-cent uptick: ABC mv becomes 600060; 600060*10000 > 6000*1000060.
    post_mark(abc["id"], "REALTIME", 10_001)
    account = get_account(account_id)
    # ABC line: share 5999.94bps... no — recomputed below.
    # gross long realtime = 600060 + 400000 = 1000060; 600060*10000 = 6000600000
    # > 6000*1000060 = 6000360000 -> concentrated. 600060*10000 = 6000600000 <=
    # 7500*1000060 = 7500450000 -> mid band +1000bps -> house 4000bps.
    # ABC line: 600060*4000/10000 = 240024. XYZ line: 400000*3000/10000 = 120000.
    assert account["house_req_realtime_cents"] == 360_024


def test_house_policy_patch_recomputes_official_requirements(api):
    """PRD §3.2: "When a supervisor amends a security's profile — any of
    `house_maint_long_bps`, `house_maint_short_bps`,
    `concentration_threshold_bps`, or `marginable` may change — the server
    recomputes the official maintenance requirements of every account holding
    that security and runs the full call evaluation of §3.6 for each affected
    account."

    Design: Corner/cross_cutting_layers/derived_fields_recompute_on_house_policy_patch
    """
    abc = create_security_profile(symbol="ABC", concentration_threshold_bps=9000)
    xyz = create_security_profile(symbol="XYZ", concentration_threshold_bps=9000)
    post_marks_both(abc["id"], 10_000)
    post_marks_both(xyz["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    place_order(account_id, customer["id"], abc["id"], "BUY", 50)
    place_order(account_id, customer["id"], xyz["id"], "BUY", 50)
    before = get_account(account_id)
    # Each position 500000 of gross 1000000 = 5000bps share, under 9000
    # threshold -> no add-on: 500000*0.30 + 500000*0.30 = 300000.
    assert before["house_req_official_cents"] == 300_000

    resp = api_client.patch_security_profile(
        abc["id"], {"house_maint_long_bps": 4000}, TEST_USERS["supervisor_headers"]
    )
    validate_success(resp)
    after = get_account(account_id)
    # ABC line: 500000*4000/10000 = 200000; XYZ line: 500000*3000/10000 = 150000.
    assert after["house_req_official_cents"] == 350_000
