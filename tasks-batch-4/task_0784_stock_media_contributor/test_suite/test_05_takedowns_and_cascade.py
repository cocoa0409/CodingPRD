"""Takedown adjudication, the uphold cascade, conserved counters, and hold buffers."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_contributor_headers,
    onboard_active_contributor, get_contributor,
    create_accepted_asset, set_clock,
    setup_accepted_asset_with_open_takedown,
    create_takedown_payload,
)

COMPLIANCE = TEST_USERS["compliance_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


def _open_takedown(api, asset_id, claim_type="COPYRIGHT", claimant="Acme"):
    return get_success_data(
        api.create_takedown(asset_id, {"claim_type": claim_type, "claimant_name": claimant}, COMPLIANCE)
    )


def test_taken_down_asset_is_terminal(api):
    """PRD §3.3: "Any submission attempt from a state other than `DRAFT` or `REJECTED` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_taken_down_asset_is_terminal
    """
    cid, asset, _dl, td_id = setup_accepted_asset_with_open_takedown(api, settle=False)
    get_success_data(api.decide_takedown(td_id, {"decision": "UPHOLD"}, COMPLIANCE))
    down = get_success_data(api.get_asset(asset["id"], REVIEWER))
    assert down["status"] == "TAKEN_DOWN"
    ch = make_contributor_headers(cid)
    validate_error(api.submit_asset(asset["id"], ch), ApiErrorId.ERR_INVALID_STATE.value)


def test_dismiss_takedown_leaves_asset_accepted(api):
    """PRD §3.8: "Dismissing an `OPEN` request moves it to `DISMISSED`, storing the optional
    `resolution_note`, and increments the takedown's `version` by 1."

    Design: Corner/state_machines/corner_takedown_dismiss_leaves_asset_accepted
    """
    c = onboard_active_contributor(api, tax_id="US-4")
    asset = create_accepted_asset(api, c["id"])
    td = _open_takedown(api, asset["id"], claim_type="PRIVACY")
    decided = validate_success(api.decide_takedown(td["id"], {"decision": "DISMISS", "resolution_note": "no merit"}, COMPLIANCE))
    assert decided["status"] == "DISMISSED"
    still = get_success_data(api.get_asset(asset["id"], REVIEWER))
    assert still["status"] == "ACCEPTED"
    contributor = get_contributor(api, c["id"])
    assert contributor["accepted_asset_count"] == 1
    assert contributor["strike_count"] == 0


def test_cascade_reverses_pending_download_without_balance_change(api):
    """PRD §3.8: "reverses every download of that asset whose `earning_status` is `PENDING` or
    `AVAILABLE`, moving each to `REVERSED` — where a reversed `AVAILABLE` download debits the
    contributor's `lifetime_earnings_cents` and `available_balance_cents` by its
    `royalty_amount_cents` and triggers a `royalty_level` recomputation, while a reversed `PENDING`
    download changes no balance".

    Design: Corner/cross_cutting_complexity_layers/corner_cascade_partial_pending_download_reversed
    """
    cid, _asset, dl_id, td_id = setup_accepted_asset_with_open_takedown(api, settle=False)
    get_success_data(api.decide_takedown(td_id, {"decision": "UPHOLD"}, COMPLIANCE))
    dl = get_success_data(api.get_download(dl_id, TEST_USERS["finance_headers"]))
    assert dl["earning_status"] == "REVERSED"
    contributor = get_contributor(api, cid)
    assert contributor["lifetime_earnings_cents"] == 0
    assert contributor["available_balance_cents"] == 0
    assert contributor["accepted_asset_count"] == 0
    assert contributor["strike_count"] == 1


def test_uphold_cascade_takes_down_asset_and_reverses_download(api):
    """PRD §3.8: "Upholding drives the asset from `ACCEPTED` to `TAKEN_DOWN` (a terminal state)
    and, in one atomic operation: decrements the owning contributor's `accepted_asset_count` by 1;
    reverses every download of that asset whose `earning_status` is `PENDING` or `AVAILABLE`,
    moving each to `REVERSED`".

    Design: Difficulty/transitive_cascade/takedown_uphold_cascade_depth3
    """
    cid, asset, dl_id, td_id = setup_accepted_asset_with_open_takedown(api, settle=True)
    get_success_data(api.decide_takedown(td_id, {"decision": "UPHOLD"}, COMPLIANCE))
    down = get_success_data(api.get_asset(asset["id"], REVIEWER))
    assert down["status"] == "TAKEN_DOWN"
    dl = get_success_data(api.get_download(dl_id, TEST_USERS["finance_headers"]))
    assert dl["earning_status"] == "REVERSED"


def test_uphold_cascade_debits_ledger_and_adds_strike(api):
    """PRD §3.8: "a reversed `AVAILABLE` download debits the contributor's `lifetime_earnings_cents`
    and `available_balance_cents` by its `royalty_amount_cents` and triggers a `royalty_level`
    recomputation ... increments the contributor's `strike_count` by 1".

    Design: Difficulty/transitive_cascade/takedown_uphold_cascade_depth3
    """
    cid, _asset, _dl_id, td_id = setup_accepted_asset_with_open_takedown(api, settle=True)
    get_success_data(api.decide_takedown(td_id, {"decision": "UPHOLD"}, COMPLIANCE))
    contributor = get_contributor(api, cid)
    assert contributor["lifetime_earnings_cents"] == 0
    assert contributor["available_balance_cents"] == 0
    assert contributor["accepted_asset_count"] == 0
    assert contributor["strike_count"] == 1


def test_accept_then_takedown_conserves_accepted_count(api):
    """PRD §3.8: "decrements the owning contributor's `accepted_asset_count` by 1".
    PRD §3.3: "the owning contributor's `accepted_asset_count` increases by 1".

    Design: Difficulty/compensating_invariant/accept_then_takedown_conserves_accepted_count
    """
    c = onboard_active_contributor(api, tax_id="US-V")
    asset = create_accepted_asset(api, c["id"])
    assert get_contributor(api, c["id"])["accepted_asset_count"] == 1
    td = _open_takedown(api, asset["id"], claim_type="MODEL_RELEASE", claimant="Claim")
    get_success_data(api.decide_takedown(td["id"], {"decision": "UPHOLD"}, COMPLIANCE))
    assert get_contributor(api, c["id"])["accepted_asset_count"] == 0


def test_accept_then_takedown_marks_asset_and_strike(api):
    """PRD §3.8: "Upholding drives the asset from `ACCEPTED` to `TAKEN_DOWN` (a terminal state) and,
    in one atomic operation: decrements the owning contributor's `accepted_asset_count` by 1 ...
    increments the contributor's `strike_count` by 1".

    Design: Difficulty/compensating_invariant/accept_then_takedown_conserves_accepted_count
    """
    c = onboard_active_contributor(api, tax_id="US-V2")
    asset = create_accepted_asset(api, c["id"])
    td = _open_takedown(api, asset["id"], claim_type="MODEL_RELEASE", claimant="Claim")
    get_success_data(api.decide_takedown(td["id"], {"decision": "UPHOLD"}, COMPLIANCE))
    down = get_success_data(api.get_asset(asset["id"], REVIEWER))
    assert down["status"] == "TAKEN_DOWN"
    assert get_contributor(api, c["id"])["strike_count"] == 1


def test_takedown_within_hold_buffer_rejected(api):
    """PRD §3.8: "A new takedown on an asset must be filed at least 14 days after the end of the
    closed hold interval of any prior `UPHELD` takedown on that same asset ... A filing that falls
    within the buffer is rejected with `ERR_TAKEDOWN_HOLD_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/takedown_hold_closed_buffer_gap
    """
    c = onboard_active_contributor(api, tax_id="US-T")
    asset = create_accepted_asset(api, c["id"])
    td1 = _open_takedown(api, asset["id"], claimant="First")  # hold [2026-03-01, 2026-05-30]
    get_success_data(api.decide_takedown(td1["id"], {"decision": "UPHOLD"}, COMPLIANCE))
    set_clock(api, "2026-06-05T00:00:00Z")  # < 2026-05-30 + 14d = 2026-06-13
    validate_error(
        api.create_takedown(asset["id"], {"claim_type": "PRIVACY", "claimant_name": "Second"}, COMPLIANCE),
        ApiErrorId.ERR_TAKEDOWN_HOLD_CONFLICT.value,
    )


def test_takedown_after_hold_buffer_allowed(api):
    """PRD §3.8: "the filing instant must be no earlier than that prior interval's `hold_end` plus
    14 days."

    Design: Difficulty/resource_temporal_overlap/takedown_hold_closed_buffer_gap
    """
    c = onboard_active_contributor(api, tax_id="US-T2")
    asset = create_accepted_asset(api, c["id"])
    td1 = _open_takedown(api, asset["id"], claimant="First")  # hold_end 2026-05-30
    get_success_data(api.decide_takedown(td1["id"], {"decision": "UPHOLD"}, COMPLIANCE))
    set_clock(api, "2026-06-20T00:00:00Z")  # >= 2026-06-13, buffer cleared
    td3 = validate_success(
        api.create_takedown(asset["id"], {"claim_type": "TRADEMARK", "claimant_name": "Third"}, COMPLIANCE), 201)
    assert td3["status"] == "OPEN"
