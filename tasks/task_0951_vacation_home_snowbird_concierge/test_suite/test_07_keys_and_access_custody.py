"""Key assets, the copy ledger, issuance deadlines and access grants."""

from test_helpers import (
    AUDITOR,
    DISPATCHER,
    ApiErrorId,
    activate_grant,
    assert_key_copy_conservation,
    assert_same_instant,
    create_access_grant_payload,
    create_grant,
    create_key_issuance_payload,
    issue_key,
    make_vendor_headers,
    new_eligible_vendor,
    new_key_asset,
    new_owner,
    new_property,
    refresh_access_grant,
    refresh_key_asset,
    refresh_key_issuance,
    refresh_vendor,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def _key_scenario(clock="2026-06-11T09:00:00Z", key_overrides=None, vendor_overrides=None):
    set_clock(clock)
    owner = new_owner()
    prop = new_property(owner["id"], label="Key House", address_line="1 Latch Ln",
                        travel_distance_miles=5.0)
    vendor = new_eligible_vendor(**(vendor_overrides or {"legal_name": "Harbor Locksmiths",
                                                         "trade": "LOCKSMITH",
                                                         "hourly_rate_cents": 7000,
                                                         "rating": 4.2}))
    key_asset = new_key_asset(prop["id"], **(key_overrides or {}))
    return {"owner": owner, "property": prop, "property_id": prop["id"],
            "vendor": vendor, "vendor_id": vendor["id"], "key_asset": key_asset,
            "key_asset_id": key_asset["id"]}


# --------------------------------------------------------------------------
# The copy ledger
# --------------------------------------------------------------------------

def test_issuing_and_returning_physical_copies_restores_the_ledger(api):
    """PRD 2.11: "For every key asset, `copies_total` equals `copies_on_hand` plus
    `copies_issued_outstanding` plus `copies_lost`. Issuing copies and then recording
    their return returns `copies_on_hand` and `copies_issued_outstanding` to their
    pre-issuance values."
    PRD 3.7: "Issuance stamps `issued_at` to the logical clock, computes
    `return_deadline_at` as `issued_at` plus a window that is 24 hours for a `LOCKBOX` key
    and 48 hours for a `PHYSICAL` key, sets `status` to `ISSUED` and `overdue_days` to
    zero, and re-derives the key's `copies_issued_outstanding` and `copies_on_hand`."

    Design: Difficulty/compensating_invariant/key_issuance_return_restores_physical_copy_ledger
    """
    scenario = _key_scenario(key_overrides={"key_type": "PHYSICAL", "label": "House keys",
                                            "copies_total": 3})
    before = scenario["key_asset"]
    assert (before["copies_on_hand"], before["copies_issued_outstanding"],
            before["copies_lost"]) == (3, 0, 0)
    assert_key_copy_conservation(before)

    issuance = issue_key(scenario["key_asset_id"], scenario["vendor_id"], copies_issued=2)
    assert_same_instant(issuance["return_deadline_at"], "2026-06-13T09:00:00Z",
                        "return_deadline_at")
    during = refresh_key_asset(scenario["key_asset_id"])
    assert (during["copies_on_hand"], during["copies_issued_outstanding"],
            during["copies_lost"]) == (1, 2, 0)
    assert_key_copy_conservation(during)

    returned = validate_success(api.return_key_issuance(issuance["id"], {}, DISPATCHER))
    assert returned["status"] == "RETURNED"
    after = refresh_key_asset(scenario["key_asset_id"])
    assert (after["copies_on_hand"], after["copies_issued_outstanding"],
            after["copies_lost"]) == (3, 0, 0)
    assert after["copies_total"] == 3
    assert_key_copy_conservation(after)
    assert refresh_vendor(scenario["vendor_id"])["outstanding_key_count"] == 0


def test_a_late_lockbox_return_also_restores_the_ledger(api):
    """PRD 3.7: "Returning from `OVERDUE` moves the issuance to the terminal
    `RETURNED_LATE` with no precondition, stamping `returned_at` and re-deriving the same
    ledger fields."
    PRD 3.7: "`copies_issued_outstanding` is the sum of `copies_issued` over the key's
    issuances in status `ISSUED` or `OVERDUE`; `copies_lost` is the same sum over
    issuances in status `LOST` or `REKEY_ORDERED`; and `copies_on_hand` is `copies_total`
    minus those two."

    Design: Difficulty/compensating_invariant/key_issuance_return_restores_physical_copy_ledger
    """
    scenario = _key_scenario(key_overrides={"key_type": "LOCKBOX", "label": "Rear lockbox",
                                            "copies_total": 2, "current_code": "2222"})
    issuance = issue_key(scenario["key_asset_id"], scenario["vendor_id"])
    assert_same_instant(issuance["return_deadline_at"], "2026-06-12T09:00:00Z",
                        "return_deadline_at")
    during = refresh_key_asset(scenario["key_asset_id"])
    assert (during["copies_on_hand"], during["copies_issued_outstanding"]) == (1, 1)

    set_clock("2026-06-12T16:00:00Z")
    overdue = validate_success(api.mark_overdue_key_issuance(issuance["id"], {}, DISPATCHER))
    assert overdue["status"] == "OVERDUE"
    still_out = refresh_key_asset(scenario["key_asset_id"])
    assert (still_out["copies_on_hand"], still_out["copies_issued_outstanding"]) == (1, 1)
    assert_key_copy_conservation(still_out)

    returned = validate_success(api.return_key_issuance(issuance["id"], {}, DISPATCHER))
    assert returned["status"] == "RETURNED_LATE"
    assert returned["returned_at"] is not None
    after = refresh_key_asset(scenario["key_asset_id"])
    assert (after["copies_on_hand"], after["copies_issued_outstanding"],
            after["copies_lost"]) == (2, 0, 0)
    assert_key_copy_conservation(after)


def test_requesting_more_copies_than_are_on_hand_is_refused(api):
    """PRD 3.7: "the key must have a `copies_on_hand` at least equal to the requested
    `copies_issued` with `rekey_pending_flag` false, otherwise
    `ERR_KEY_COPIES_UNAVAILABLE`."
    PRD 3.7: "`copies_on_hand` may legitimately reach zero, but an issuance that would
    drive it negative is refused."

    Design: Corner/errors/err_key_copies_unavailable_when_request_exceeds_on_hand_returns_409
    """
    scenario = _key_scenario(clock="2026-06-01T00:00:00Z",
                             key_overrides={"key_type": "PHYSICAL", "label": "Front",
                                            "copies_total": 2})
    response = api.create_key_asset_key_issuance(
        scenario["key_asset_id"],
        create_key_issuance_payload(scenario["vendor_id"], copies_issued=3),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_KEY_COPIES_UNAVAILABLE.value)
    key_asset = refresh_key_asset(scenario["key_asset_id"])
    assert (key_asset["copies_on_hand"], key_asset["copies_issued_outstanding"],
            key_asset["copies_lost"]) == (2, 0, 0)


def test_a_rejected_issuance_leaves_no_partial_state_behind(api):
    """PRD 2.11: "For every key asset, `copies_total` equals `copies_on_hand` plus
    `copies_issued_outstanding` plus `copies_lost`."
    PRD 2.4: "`version`, an integer that starts at 1 when the row is created and increases
    as the row is mutated."

    Design: Corner/consistency_model/immediate_consistency_rejected_write_leaves_no_partial_state
    """
    scenario = _key_scenario(clock="2026-06-01T00:00:00Z",
                             key_overrides={"key_type": "PHYSICAL", "label": "Front",
                                            "copies_total": 2},
                             vendor_overrides={"legal_name": "Atom Locks", "trade": "LOCKSMITH",
                                               "hourly_rate_cents": 7000, "rating": 4.0})
    assert scenario["key_asset"]["version"] == 1

    response = api.create_key_asset_key_issuance(
        scenario["key_asset_id"],
        create_key_issuance_payload(scenario["vendor_id"], copies_issued=5),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_KEY_COPIES_UNAVAILABLE.value)
    _, meta = validate_paginated(
        api.list_key_issuances(headers=AUDITOR,
                               params={"key_asset_id": scenario["key_asset_id"]})
    )
    assert meta["total_count"] == 0, "no half-written issuance row may survive"
    key_asset = refresh_key_asset(scenario["key_asset_id"])
    assert (key_asset["copies_on_hand"], key_asset["copies_issued_outstanding"],
            key_asset["copies_lost"]) == (2, 0, 0)
    assert key_asset["version"] == 1, "a rejected write must not advance the version counter"


def test_unknown_vendor_on_a_key_issuance_is_a_404(api):
    """PRD 2.8: "A body field `vendor_id` resolves to an existing vendor. This applies to
    key issuance and access-grant creation. Otherwise `ERR_VENDOR_NOT_FOUND`, HTTP 404."

    Design: Corner/errors/err_vendor_not_found_on_key_issuance_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="NoVend House", address_line="12 Miss Mews",
                        travel_distance_miles=5.0)
    key_asset = new_key_asset(prop["id"], key_type="PHYSICAL", label="Front", copies_total=2)
    response = api.create_key_asset_key_issuance(
        key_asset["id"],
        create_key_issuance_payload("00000000-0000-4000-8000-0000000000b3"),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_VENDOR_NOT_FOUND.value)
    reread = refresh_key_asset(key_asset["id"])
    assert reread["copies_on_hand"] == 2
    assert reread["copies_issued_outstanding"] == 0


# --------------------------------------------------------------------------
# Overdue arithmetic
# --------------------------------------------------------------------------

def test_overdue_days_take_the_ceiling_of_the_elapsed_gap(api):
    """PRD 3.7: "That day count is zero while the clock is at or before
    `return_deadline_at`, and is otherwise the **ceiling** of the seconds since the
    deadline divided by 86400 — one second past the deadline is already one overdue day."
    PRD 3.6: "`outstanding_key_count` counts that vendor's key issuances in status
    `ISSUED` or `OVERDUE` and is re-derived on every issuance transition."

    Design: Corner/calculations/key_overdue_days_uses_ceiling_not_floor
    """
    scenario = _key_scenario(key_overrides={"key_type": "LOCKBOX", "label": "Rear lockbox",
                                            "copies_total": 1, "current_code": "2222"})
    issuance = issue_key(scenario["key_asset_id"], scenario["vendor_id"])
    assert_same_instant(issuance["return_deadline_at"], "2026-06-12T09:00:00Z",
                        "return_deadline_at")
    set_clock("2026-06-12T16:00:00Z")
    overdue = validate_success(api.mark_overdue_key_issuance(issuance["id"], {}, DISPATCHER))
    assert overdue["status"] == "OVERDUE"
    assert overdue["overdue_days"] == 1, "ceil(7 hours / 24 hours) == 1, not floor 0"
    assert refresh_vendor(scenario["vendor_id"])["outstanding_key_count"] == 1


def test_marking_overdue_inside_the_six_hour_grace_is_refused(api):
    """PRD 3.7: "Marking an issuance overdue moves it from `ISSUED` to `OVERDUE` and is
    permitted only once the logical clock is strictly past `return_deadline_at` plus a
    grace of 6 hours; an earlier attempt is rejected with `ERR_ISSUANCE_NOT_OVERDUE`."

    Design: Corner/errors/err_issuance_not_overdue_inside_the_grace_window_returns_409
    """
    scenario = _key_scenario(key_overrides={"key_type": "LOCKBOX", "label": "Side box",
                                            "copies_total": 1, "current_code": "7777"})
    issuance = issue_key(scenario["key_asset_id"], scenario["vendor_id"])
    assert_same_instant(issuance["return_deadline_at"], "2026-06-12T09:00:00Z",
                        "return_deadline_at")
    set_clock("2026-06-12T14:00:00Z")

    response = api.mark_overdue_key_issuance(issuance["id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_ISSUANCE_NOT_OVERDUE.value)
    reread = refresh_key_issuance(issuance["id"])
    assert reread["status"] == "ISSUED"
    assert reread["overdue_days"] == 0


def test_declaring_a_key_lost_before_seven_overdue_days_is_refused(api):
    """PRD 3.7: "Declaring an overdue key lost requires `overdue_days` to be at least 7, an
    earlier attempt being rejected with `ERR_LOST_THRESHOLD_NOT_MET`."

    Design: Corner/errors/err_lost_threshold_not_met_on_early_declare_lost_returns_409
    """
    scenario = _key_scenario(key_overrides={"key_type": "LOCKBOX", "label": "Side box",
                                            "copies_total": 1, "current_code": "8888"})
    issuance = issue_key(scenario["key_asset_id"], scenario["vendor_id"])
    set_clock("2026-06-12T16:00:00Z")
    overdue = validate_success(api.mark_overdue_key_issuance(issuance["id"], {}, DISPATCHER))
    assert overdue["overdue_days"] == 1

    response = api.declare_lost_key_issuance(issuance["id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_LOST_THRESHOLD_NOT_MET.value)
    assert refresh_key_issuance(issuance["id"])["status"] == "OVERDUE"
    key_asset = refresh_key_asset(scenario["key_asset_id"])
    assert key_asset["rekey_pending_flag"] is False
    assert key_asset["copies_lost"] == 0


def test_an_overdue_issuance_blocks_the_same_vendor_on_a_different_key(api):
    """PRD 3.7: "Two custody gates apply, and they are the two key-custody rungs: the
    vendor must hold no key issuance in status `OVERDUE` or `LOST`, otherwise
    `ERR_VENDOR_KEY_OVERDUE`"
    PRD 3.7: "The overdue mark blocks any further issuance to that vendor until the
    issuance leaves `OVERDUE`, and it computes `overdue_days`."

    Design: Corner/errors/err_vendor_key_overdue_blocks_second_issuance_returns_409
    """
    scenario = _key_scenario(key_overrides={"key_type": "LOCKBOX", "label": "Key A",
                                            "copies_total": 1, "current_code": "1010"},
                             vendor_overrides={"legal_name": "Holder Locks",
                                               "trade": "LOCKSMITH",
                                               "hourly_rate_cents": 7000, "rating": 4.0})
    key_b = new_key_asset(scenario["property_id"], key_type="PHYSICAL", label="Key B",
                          copies_total=1)
    issuance = issue_key(scenario["key_asset_id"], scenario["vendor_id"])
    set_clock("2026-06-12T16:00:00Z")
    validate_success(api.mark_overdue_key_issuance(issuance["id"], {}, DISPATCHER))
    assert refresh_vendor(scenario["vendor_id"])["outstanding_key_count"] == 1

    response = api.create_key_asset_key_issuance(
        key_b["id"], create_key_issuance_payload(scenario["vendor_id"]), DISPATCHER
    )
    validate_error(response, ApiErrorId.ERR_VENDOR_KEY_OVERDUE.value)
    reread = refresh_key_asset(key_b["id"])
    assert reread["copies_on_hand"] == 1
    assert reread["copies_issued_outstanding"] == 0


# --------------------------------------------------------------------------
# Access grants
# --------------------------------------------------------------------------

def test_revoking_an_active_grant_drops_the_active_count(api):
    """PRD 3.7: "Revoking a grant supplies a `revoke_reason`. With a reason of `OPERATOR`
    the grant moves from `ACTIVE` to the terminal `REVOKED` with no precondition."
    PRD 2.11: "A key asset's `active_grant_count` equals the number of grants on it in
    status `ACTIVE`."

    Design: Corner/state_machines/access_grant_revoke_decrements_active_count
    """
    scenario = _key_scenario(clock="2026-06-11T10:30:00Z",
                             key_overrides={"key_type": "PHYSICAL", "label": "Garage key",
                                            "copies_total": 2},
                             vendor_overrides={"legal_name": "Rev Locks", "trade": "LOCKSMITH",
                                               "hourly_rate_cents": 7000, "rating": 4.4})
    grant = create_grant(scenario["key_asset_id"], scenario["vendor_id"],
                         "2026-06-11T10:00:00Z", "2026-06-11T14:00:00Z",
                         scenario["key_asset"]["version"])
    activate_grant(grant["id"])
    assert refresh_key_asset(scenario["key_asset_id"])["active_grant_count"] == 1

    revoked = validate_success(
        api.revoke_access_grant(grant["id"], {"revoke_reason": "OPERATOR"}, DISPATCHER)
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["invalidated_reason"] is None
    assert refresh_key_asset(scenario["key_asset_id"])["active_grant_count"] == 0


def test_touching_grant_windows_exhaust_a_single_copy_key(api):
    """PRD 3.7: "the concurrent count is the number of grants on the same key, excluding
    the candidate itself, whose `status` is `PENDING` or `ACTIVE` and whose window
    satisfies both "that grant's `window_start_at` is at or before the candidate's
    `window_end_at`" and "the candidate's `window_start_at` is at or before that grant's
    `window_end_at`"."
    PRD 3.7: "**Touching endpoints do collide here**: a grant ending at 12:00 and one
    starting at 12:00 are concurrent."
    PRD 3.7: "And the count of `ACTIVE` grants on the key must be strictly less than the
    key's `copies_total`, an excess being rejected with `ERR_ACCESS_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/access_grant_closed_interval_aggregate_capacity_on_physical_key
    """
    scenario = _key_scenario(clock="2026-06-11T10:30:00Z",
                             key_overrides={"key_type": "PHYSICAL", "label": "Spare front key",
                                            "copies_total": 1},
                             vendor_overrides={"legal_name": "Coastal Locksmiths",
                                               "trade": "LOCKSMITH",
                                               "hourly_rate_cents": 7000, "rating": 4.2})
    first = create_grant(scenario["key_asset_id"], scenario["vendor_id"],
                         "2026-06-11T10:00:00Z", "2026-06-11T12:00:00Z",
                         scenario["key_asset"]["version"])
    version_after_first = refresh_key_asset(scenario["key_asset_id"])["version"]
    activate_grant(first["id"])
    second = create_grant(scenario["key_asset_id"], scenario["vendor_id"],
                          "2026-06-11T12:00:00Z", "2026-06-11T14:00:00Z", version_after_first)
    set_clock("2026-06-11T12:00:00Z")

    response = api.activate_access_grant(second["id"], {}, DISPATCHER)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_ACCESS_CAPACITY_EXCEEDED.value)
    assert refresh_access_grant(first["id"])["status"] == "ACTIVE"
    assert refresh_access_grant(second["id"])["status"] == "PENDING"
    assert refresh_access_grant(first["id"])["rotation_index_at_grant"] == 0
    assert refresh_access_grant(second["id"])["rotation_index_at_grant"] == 0
    key_asset = refresh_key_asset(scenario["key_asset_id"])
    assert key_asset["code_rotation_count"] == 0, "a physical key never rotates a code"
    assert key_asset["active_grant_count"] == 1


def test_two_touching_grants_fit_inside_a_two_copy_key(api):
    """PRD 3.7: "Activation is allowed while that concurrent count is strictly below
    `copies_total`, and it advances `active_grant_count` by one."
    PRD 3.7: "`copies_total` doubles as the aggregate concurrency capacity for
    simultaneous access windows on the key."

    Design: Difficulty/resource_temporal_overlap/access_grant_closed_interval_aggregate_capacity_on_physical_key
    """
    scenario = _key_scenario(clock="2026-06-11T10:30:00Z",
                             key_overrides={"key_type": "PHYSICAL", "label": "Pair of keys",
                                            "copies_total": 2},
                             vendor_overrides={"legal_name": "Pair Locksmiths",
                                               "trade": "LOCKSMITH",
                                               "hourly_rate_cents": 7000, "rating": 4.2})
    first = create_grant(scenario["key_asset_id"], scenario["vendor_id"],
                         "2026-06-11T10:00:00Z", "2026-06-11T12:00:00Z",
                         scenario["key_asset"]["version"])
    version_after_first = refresh_key_asset(scenario["key_asset_id"])["version"]
    activate_grant(first["id"])
    second = create_grant(scenario["key_asset_id"], scenario["vendor_id"],
                          "2026-06-11T12:00:00Z", "2026-06-11T14:00:00Z", version_after_first)
    set_clock("2026-06-11T12:00:00Z")

    activated = validate_success(api.activate_access_grant(second["id"], {}, DISPATCHER))
    assert activated["status"] == "ACTIVE"
    assert refresh_access_grant(first["id"])["status"] == "ACTIVE"
    assert refresh_key_asset(scenario["key_asset_id"])["active_grant_count"] == 2


def test_an_explicit_rotation_invalidates_the_grant_stamped_at_the_old_index(api):
    """PRD 3.7: "An explicit rotation supplies an explicit `new_code` together with
    `expected_key_asset_version`. It advances `code_rotation_count` by one, rewrites
    `current_code` to the supplied value, invalidates every grant in `PENDING` or `ACTIVE`
    whose `rotation_index_at_grant` is strictly less than the new count with an
    `invalidated_reason` of `CODE_ROTATION`, re-derives `active_grant_count`, and advances
    the key asset's `version` by one."
    PRD 3.7: "`INVALIDATED` is the third terminal state, reached only through a code
    rotation, a key loss or an assignment withdrawal"

    Design: Corner/errors/explicit_rotation_invalidates_the_earlier_grant_and_activation_returns_409
    """
    scenario = _key_scenario(clock="2026-06-11T10:00:00Z",
                             key_overrides={"key_type": "LOCKBOX", "label": "Rot lockbox",
                                            "copies_total": 2, "current_code": "9000"},
                             vendor_overrides={"legal_name": "Rotate Locks",
                                               "trade": "LOCKSMITH",
                                               "hourly_rate_cents": 7000, "rating": 4.0})
    grant = create_grant(scenario["key_asset_id"], scenario["vendor_id"],
                         "2026-06-11T09:00:00Z", "2026-06-11T18:00:00Z",
                         scenario["key_asset"]["version"])
    assert grant["rotation_index_at_grant"] == 1
    assert grant["code_snapshot"] == "9001"
    version_after_grant = refresh_key_asset(scenario["key_asset_id"])["version"]

    rotated = validate_success(api.rotate_code_key_asset(
        scenario["key_asset_id"],
        {"new_code": "9001", "expected_key_asset_version": version_after_grant},
        DISPATCHER,
    ))
    assert rotated["code_rotation_count"] == 2
    assert rotated["current_code"] == "9001"
    assert rotated["active_grant_count"] == 0
    invalidated = refresh_access_grant(grant["id"])
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["invalidated_reason"] == "CODE_ROTATION"

    response = api.activate_access_grant(grant["id"], {}, DISPATCHER)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ALREADY_TERMINAL.value, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value],
    )


def test_a_second_grant_replaying_the_pre_rotation_version_is_stale(api):
    """PRD 2.10: "**Access-grant creation on a key asset** requires
    `expected_key_asset_version` carrying the client's last observed `version` of that
    `KeyAsset`. A mismatch is rejected with `ERR_STALE_KEY_ASSET_VERSION` and HTTP 412."
    PRD 3.7: "On a `LOCKBOX` key the creation **rotates the code first**, so the grant
    carries the post-rotation snapshot"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_key_asset_version_on_second_grant_returns_412
    """
    scenario = _key_scenario(clock="2026-06-11T10:00:00Z",
                             key_overrides={"key_type": "LOCKBOX", "label": "Occ lockbox",
                                            "copies_total": 2, "current_code": "4200"},
                             vendor_overrides={"legal_name": "Occ Locks", "trade": "LOCKSMITH",
                                               "hourly_rate_cents": 7000, "rating": 4.1})
    stale_version = scenario["key_asset"]["version"]
    first = create_grant(scenario["key_asset_id"], scenario["vendor_id"],
                         "2026-06-11T10:00:00Z", "2026-06-11T18:00:00Z", stale_version)

    response = api.create_key_asset_access_grant(
        scenario["key_asset_id"],
        create_access_grant_payload(scenario["vendor_id"], "2026-06-11T12:00:00Z",
                                    "2026-06-11T20:00:00Z", stale_version),
        DISPATCHER,
    )
    assert response.status_code == 412, f"expected 412, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_STALE_KEY_ASSET_VERSION.value)

    key_asset = refresh_key_asset(scenario["key_asset_id"])
    assert key_asset["code_rotation_count"] == 1
    assert key_asset["current_code"] == "4201"
    reread = refresh_access_grant(first["id"])
    assert reread["status"] == "PENDING"
    assert reread["rotation_index_at_grant"] == 1
    assert reread["code_snapshot"] == "4201"
    _, meta = validate_paginated(
        api.list_access_grants(headers=AUDITOR,
                               params={"key_asset_id": scenario["key_asset_id"]})
    )
    assert meta["total_count"] == 1
