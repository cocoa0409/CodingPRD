"""Hold amendment and error correction state machines: adjudication, terminality, windows.

Every test builds its own program, wholesalers, staff, brands, schedules and
adjudicable records through PRD-declared endpoints, because the server is
restarted against an empty database before each test.
"""

import pytest

from test_helpers import (
    accept_amendment,
    deny_correction,
    deny_error_correction_payload,
    new_amendment,
    new_correction,
    read_amendment,
    read_correction,
    read_item,
    read_schedule,
    read_wholesaler,
    regulator_headers,
    reject_amendment,
    reject_hold_amendment_payload,
    revoke_hold_amendment_payload,
    schedule_version,
    set_clock,
    setup_certified_schedule,
    setup_pending_amendment,
    setup_two_wholesalers_certified,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_01_hold_amendment_rejections_accrue_the_frivolous_penalty_only_on_reaching_three(api):
    """PRD §3.6: "What it does move is the filer's record: the amending
    wholesaler's `frivolous_amendment_count` is incremented by 1, and when the
    resulting count reaches 3 or more the program's
    `frivolous_amendment_penalty_cents` is added to that wholesaler's
    `amendment_penalty_accrued_cents`."
    PRD §3.6: "It records the supplied `rejection_reason` and leaves the amending
    item's prices, its `amendment_count`, its tiers and its combinations entirely
    unchanged."
    PRD §3.1: "`frivolous_amendment_penalty_cents` defaults to 75,000 cents and
    must be at least 0"

    Design: Corner/state_machines/hold_amendment_rejections_accrue_the_frivolous_penalty_only_on_reaching_three
    """
    scene = setup_two_wholesalers_certified()
    item_a = scene["items_a"][0]
    wholesaler_a_id = scene["wholesaler_a"]["id"]
    schedule_a_id = scene["schedule_a"]["id"]

    first = new_amendment(
        item_a["id"],
        scene["item_b"]["id"],
        119_000,
        10_900,
        schedule_version(schedule_a_id),
        scene["agent_a_headers"],
    )
    reject_amendment(first["id"], "no competitor posting supports this match")
    after_first = read_wholesaler(wholesaler_a_id)
    assert after_first["frivolous_amendment_count"] == 1, (
        f"the first rejection must take frivolous_amendment_count to 1, "
        f"got {after_first['frivolous_amendment_count']}"
    )
    assert after_first["amendment_penalty_accrued_cents"] == 0, (
        f"one rejection is below the threshold of three, so no penalty accrues, "
        f"got {after_first['amendment_penalty_accrued_cents']}"
    )
    assert after_first["penalty_exposure_cents"] == 0, (
        f"penalty_exposure_cents must stay 0 after one rejection, "
        f"got {after_first['penalty_exposure_cents']}"
    )

    second = new_amendment(
        item_a["id"],
        scene["item_b"]["id"],
        118_000,
        10_800,
        schedule_version(schedule_a_id),
        scene["agent_a_headers"],
    )
    reject_amendment(second["id"], "second unsupported match")
    after_second = read_wholesaler(wholesaler_a_id)
    assert after_second["frivolous_amendment_count"] == 2, (
        f"the second rejection must take frivolous_amendment_count to 2, "
        f"got {after_second['frivolous_amendment_count']}"
    )
    assert after_second["amendment_penalty_accrued_cents"] == 0, (
        f"two rejections are still below the threshold of three, "
        f"got {after_second['amendment_penalty_accrued_cents']}"
    )
    assert after_second["penalty_exposure_cents"] == 0, (
        f"penalty_exposure_cents must stay 0 after two rejections, "
        f"got {after_second['penalty_exposure_cents']}"
    )

    third = new_amendment(
        item_a["id"],
        scene["item_b"]["id"],
        117_000,
        10_700,
        schedule_version(schedule_a_id),
        scene["agent_a_headers"],
    )
    data = validate_success(
        api.reject_hold_amendment(
            third["id"],
            reject_hold_amendment_payload("third unsupported match"),
            regulator_headers(),
        ),
        200,
    )
    assert data["status"] == "REJECTED", (
        f"the third amendment must end REJECTED, got {data['status']!r}"
    )
    assert data["rejection_reason"] == "third unsupported match", (
        f"rejection must record the supplied reason, got {data['rejection_reason']!r}"
    )

    after_third = read_wholesaler(wholesaler_a_id)
    assert after_third["frivolous_amendment_count"] == 3, (
        f"the third rejection must take frivolous_amendment_count to 3, "
        f"got {after_third['frivolous_amendment_count']}"
    )
    assert after_third["amendment_penalty_accrued_cents"] == 75_000, (
        f"reaching three rejections must accrue the 75000 cent frivolous amendment "
        f"penalty exactly once, got {after_third['amendment_penalty_accrued_cents']}"
    )
    assert after_third["penalty_exposure_cents"] == 75_000, (
        f"penalty_exposure_cents must pick up the newly accrued amendment penalty, "
        f"got {after_third['penalty_exposure_cents']}"
    )

    item = read_item(item_a["id"])
    assert item["case_price_cents"] == 120_000, (
        f"rejections leave the amending item's case price untouched at 120000, "
        f"got {item['case_price_cents']}"
    )
    assert item["unit_price_cents"] == 11_000, (
        f"rejections leave the amending item's unit price untouched at 11000, "
        f"got {item['unit_price_cents']}"
    )
    assert item["amendment_count"] == 0, (
        f"rejections leave the item's amendment_count at 0, got {item['amendment_count']}"
    )

    _, meta = validate_paginated(
        api.list_hold_amendments(
            regulator_headers(),
            params={"amending_item_id": item_a["id"], "status": "REJECTED"},
        )
    )
    assert meta["total_count"] == 3, (
        f"all three amendments must be readable as REJECTED, got {meta['total_count']}"
    )


def test_02_hold_amendment_accept_applied_twice_returns_invalid_state(api):
    """PRD §3.6: "It requires the amendment to be in `PENDING` (otherwise
    `ERR_INVALID_STATE`) and the amending item's schedule to still be inside its
    post-and-hold window (otherwise `ERR_HOLD_WINDOW_CLOSED`) — the window is
    re-tested at acceptance time, so an amendment filed inside the window but
    adjudicated after it closed cannot be accepted."
    PRD §3.6: "Acceptance first captures the amending item's current prices into
    the amendment's `prior_case_price_cents` and `prior_unit_price_cents`, then
    writes `new_case_price_cents` into the item's `case_price_cents` and
    `new_unit_price_cents` into the item's `unit_price_cents`, then increments the
    item's `amendment_count` by 1, then recomputes `discounted_case_price_cents`
    on every `ACTIVE` quantity discount tier of that item, then recomputes
    `floor_price_cents` and `min_allowed_price_cents` on every `ACTIVE`
    combination sale that contains the item and moves to `VOID` any such
    combination whose `combined_case_price_cents` now falls strictly below its
    recomputed `min_allowed_price_cents`, and finally advances the item's
    `version` by 1."

    Design: Corner/state_machines/hold_amendment_accept_applied_twice_returns_invalid_state
    """
    scene = setup_pending_amendment(
        new_case_price_cents=115_000, new_unit_price_cents=10_500
    )
    amendment_id = scene["amendment"]["id"]
    accept_amendment(amendment_id)

    response = api.accept_hold_amendment(amendment_id, regulator_headers())
    assert response.status_code == 409, (
        f"accepting an already ACCEPTED amendment must be a 409 conflict, "
        f"got {response.status_code}"
    )
    validate_error(response, "ERR_INVALID_STATE")

    amendment = read_amendment(amendment_id)
    assert amendment["status"] == "ACCEPTED", (
        f"the amendment must remain ACCEPTED, got {amendment['status']!r}"
    )
    assert amendment["prior_case_price_cents"] == 120_000, (
        f"prior_case_price_cents must still hold the pre-amendment 120000 captured by "
        f"the first acceptance, got {amendment['prior_case_price_cents']}"
    )
    assert amendment["prior_unit_price_cents"] == 11_000, (
        f"prior_unit_price_cents must still hold the pre-amendment 11000, "
        f"got {amendment['prior_unit_price_cents']}"
    )

    item = read_item(scene["items_a"][0]["id"])
    assert item["case_price_cents"] == 115_000, (
        f"the item must hold the amended case price 115000, got {item['case_price_cents']}"
    )
    assert item["unit_price_cents"] == 10_500, (
        f"the item must hold the amended unit price 10500, got {item['unit_price_cents']}"
    )
    assert item["amendment_count"] == 1, (
        f"the refused second acceptance must not increment amendment_count past 1, "
        f"got {item['amendment_count']}"
    )


def test_03_hold_amendment_revoke_from_pending_returns_invalid_state(api):
    """PRD §3.6: "Revocation is the `ACCEPTED → REVOKED` transition, requiring
    `ACCEPTED` status (otherwise `ERR_INVALID_STATE`) and taking a
    `revocation_reason`."
    PRD §3.6: "Filing a valid amendment creates a `HoldAmendment` in `PENDING`
    status with `prior_case_price_cents`, `prior_unit_price_cents`,
    `rejection_reason` and `revocation_reason` all unset, and advances the
    amending item's schedule `version` by 1."

    Design: Corner/state_machines/hold_amendment_revoke_from_pending_returns_invalid_state
    """
    scene = setup_pending_amendment()
    amendment_id = scene["amendment"]["id"]

    response = api.revoke_hold_amendment(
        amendment_id,
        revoke_hold_amendment_payload("filer changed their mind"),
        regulator_headers(),
    )
    assert response.status_code == 409, (
        f"revoking a PENDING amendment must be a 409 conflict, got {response.status_code}"
    )
    validate_error(response, "ERR_INVALID_STATE")

    amendment = read_amendment(amendment_id)
    assert amendment["status"] == "PENDING", (
        f"the amendment must remain PENDING, got {amendment['status']!r}"
    )
    assert amendment.get("revocation_reason") is None, (
        f"the refused revoke must not record a revocation_reason, "
        f"got {amendment.get('revocation_reason')!r}"
    )
    assert amendment.get("prior_case_price_cents") is None, (
        f"prior_case_price_cents is captured only by acceptance and must stay unset, "
        f"got {amendment.get('prior_case_price_cents')!r}"
    )

    item = read_item(scene["items_a"][0]["id"])
    assert item["case_price_cents"] == 120_000, (
        f"a never-accepted amendment leaves the item at 120000, "
        f"got {item['case_price_cents']}"
    )
    assert item["amendment_count"] == 0, (
        f"the item's amendment_count must stay 0, got {item['amendment_count']}"
    )


def test_04_rejected_hold_amendment_is_terminal_and_both_accept_and_revoke_are_refused(api):
    """PRD §3.6: "Both `REJECTED` and `REVOKED` are terminal for an amendment;
    there is no path back to `PENDING`."
    PRD §2.10: "State admissibility outranks every business rule below it — an
    amendment filed against an item that has already gone `EFFECTIVE` is reported
    as `ERR_INVALID_STATE` even though its post-and-hold window has also closed,
    because priority 8 is reached before priority 12."
    PRD §3.6: "It records the supplied `rejection_reason` and leaves the amending
    item's prices, its `amendment_count`, its tiers and its combinations entirely
    unchanged."

    Design: Corner/state_machines/rejected_hold_amendment_is_terminal_and_both_accept_and_revoke_are_refused
    """
    scene = setup_pending_amendment()
    amendment_id = scene["amendment"]["id"]
    reject_amendment(amendment_id, "no competitor posting supports this match")

    accept_response = api.accept_hold_amendment(amendment_id, regulator_headers())
    assert accept_response.status_code == 409, (
        f"accepting a REJECTED amendment must be a 409 conflict, "
        f"got {accept_response.status_code}"
    )
    validate_error(accept_response, "ERR_INVALID_STATE")

    revoke_response = api.revoke_hold_amendment(
        amendment_id,
        revoke_hold_amendment_payload("undo the rejection"),
        regulator_headers(),
    )
    assert revoke_response.status_code == 409, (
        f"revoking a REJECTED amendment must be a 409 conflict, "
        f"got {revoke_response.status_code}"
    )
    validate_error(revoke_response, "ERR_INVALID_STATE")

    amendment = read_amendment(amendment_id)
    assert amendment["status"] == "REJECTED", (
        f"REJECTED is terminal, got {amendment['status']!r}"
    )
    assert amendment.get("revocation_reason") is None, (
        f"the refused revoke must not record a revocation_reason, "
        f"got {amendment.get('revocation_reason')!r}"
    )
    assert amendment.get("prior_case_price_cents") is None, (
        f"the refused accept must not capture prior prices, "
        f"got {amendment.get('prior_case_price_cents')!r}"
    )

    item = read_item(scene["items_a"][0]["id"])
    assert item["case_price_cents"] == 120_000, (
        f"the amending item's price must stay 120000, got {item['case_price_cents']}"
    )
    assert item["amendment_count"] == 0, (
        f"the item's amendment_count must stay 0, got {item['amendment_count']}"
    )

    wholesaler = read_wholesaler(scene["wholesaler_a"]["id"])
    assert wholesaler["frivolous_amendment_count"] == 1, (
        f"only the one genuine rejection may count, got "
        f"{wholesaler['frivolous_amendment_count']}"
    )


def test_05_hold_amendment_accept_after_the_hold_window_closes_returns_hold_window_closed(api):
    """PRD §3.6: "It requires the amendment to be in `PENDING` (otherwise
    `ERR_INVALID_STATE`) and the amending item's schedule to still be inside its
    post-and-hold window (otherwise `ERR_HOLD_WINDOW_CLOSED`) — the window is
    re-tested at acceptance time, so an amendment filed inside the window but
    adjudicated after it closed cannot be accepted."
    PRD §2.7: "A current server time exactly equal to `hold_window_ends_at` means
    the window is closed."

    Design: Corner/state_machines/hold_amendment_accept_after_the_hold_window_closes_returns_hold_window_closed
    """
    scene = setup_pending_amendment(
        new_case_price_cents=115_000, new_unit_price_cents=10_500
    )
    amendment_id = scene["amendment"]["id"]

    schedule = read_schedule(scene["schedule_a"]["id"])
    assert schedule["hold_window_ends_at"] == "2026-08-04T00:00:00.000Z", (
        f"the three-day window on a schedule certified at 2026-08-01T00:00:00.000Z "
        f"ends at 2026-08-04T00:00:00.000Z, got {schedule['hold_window_ends_at']!r}"
    )

    set_clock("2026-08-04T00:00:00Z")

    response = api.accept_hold_amendment(amendment_id, regulator_headers())
    assert response.status_code == 409, (
        f"accepting at the exact window boundary must be a 409 conflict, "
        f"got {response.status_code}"
    )
    validate_error(response, "ERR_HOLD_WINDOW_CLOSED")

    amendment = read_amendment(amendment_id)
    assert amendment["status"] == "PENDING", (
        f"the refused acceptance must leave the amendment PENDING, "
        f"got {amendment['status']!r}"
    )
    assert amendment.get("prior_case_price_cents") is None, (
        f"the refused acceptance must not capture prior prices, "
        f"got {amendment.get('prior_case_price_cents')!r}"
    )

    item = read_item(scene["items_a"][0]["id"])
    assert item["case_price_cents"] == 120_000, (
        f"the amending item must keep its posted 120000, got {item['case_price_cents']}"
    )
    assert item["unit_price_cents"] == 11_000, (
        f"the amending item must keep its posted 11000, got {item['unit_price_cents']}"
    )
    assert item["amendment_count"] == 0, (
        f"the item's amendment_count must stay 0, got {item['amendment_count']}"
    )


def test_06_error_correction_deny_records_the_reason_and_leaves_every_derived_price_untouched(api):
    """PRD §3.6: "Denial is the `SUBMITTED → DENIED` transition, requiring
    `SUBMITTED` status (otherwise `ERR_INVALID_STATE`). It records the supplied
    `denial_reason`, leaves the item's prices, counters and tiers untouched, and
    advances the correction's own `version` by 1."
    PRD §3.6: "Filing captures the item's current prices into the correction's
    `prior_case_price_cents` and `prior_unit_price_cents` and creates the
    correction in `SUBMITTED` status with `denial_reason` unset."
    PRD §3.6: "A correction must actually look like a typo, and that is measured
    by `variance_pct`: the absolute difference between
    `corrected_case_price_cents` and `prior_case_price_cents`, divided by
    `prior_case_price_cents`, left as an unrounded decimal fraction."

    Design: Corner/state_machines/error_correction_deny_records_the_reason_and_leaves_every_derived_price_untouched
    """
    scene = setup_certified_schedule(posting_month="2026-09")
    item = scene["items"][0]
    correction = new_correction(
        item["id"],
        114_000,
        10_500,
        scene["agent_headers"],
        reason="transposed digits on the filed case price",
    )

    data = validate_success(
        api.deny_error_correction(
            correction["id"],
            deny_error_correction_payload("supporting invoice was not attached"),
            regulator_headers(),
        ),
        200,
    )

    assert data["status"] == "DENIED", (
        f"deny must move the correction to DENIED, got {data['status']!r}"
    )
    assert data["denial_reason"] == "supporting invoice was not attached", (
        f"denial must record the supplied reason, got {data['denial_reason']!r}"
    )
    assert data["prior_case_price_cents"] == 120_000, (
        f"prior_case_price_cents was captured at filing as 120000, "
        f"got {data['prior_case_price_cents']}"
    )
    assert data["prior_unit_price_cents"] == 11_000, (
        f"prior_unit_price_cents was captured at filing as 11000, "
        f"got {data['prior_unit_price_cents']}"
    )
    assert data["variance_pct"] == pytest.approx(0.05, abs=1e-9), (
        f"variance_pct is |114000 - 120000| / 120000 = 0.05, got {data['variance_pct']!r}"
    )

    item_after = read_item(item["id"])
    assert item_after["case_price_cents"] == 120_000, (
        f"a denied correction leaves the item's case price at 120000, "
        f"got {item_after['case_price_cents']}"
    )
    assert item_after["unit_price_cents"] == 11_000, (
        f"a denied correction leaves the item's unit price at 11000, "
        f"got {item_after['unit_price_cents']}"
    )
    assert item_after["correction_count"] == 0, (
        f"a denied correction does not count against the item, "
        f"got {item_after['correction_count']}"
    )

    schedule = read_schedule(scene["schedule"]["id"])
    assert schedule["correction_count"] == 0, (
        f"a denied correction does not count against the schedule, "
        f"got {schedule['correction_count']}"
    )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["correction_penalty_accrued_cents"] == 0, (
        f"a denied correction accrues no repeat correction penalty, "
        f"got {wholesaler['correction_penalty_accrued_cents']}"
    )
    assert wholesaler["penalty_exposure_cents"] == 0, (
        f"penalty_exposure_cents must stay 0, got {wholesaler['penalty_exposure_cents']}"
    )


def test_07_denied_error_correction_is_terminal_and_a_later_approve_is_refused(api):
    """PRD §3.6: "Both `APPROVED` and `DENIED` are terminal."
    PRD §3.6: "It requires the correction to be in `SUBMITTED` (otherwise
    `ERR_INVALID_STATE`) and requires the item's schedule to have strictly fewer
    approved corrections than the program's `max_corrections_per_schedule`; at or
    above that number the approval is refused with
    `ERR_CORRECTION_LIMIT_EXCEEDED`."
    PRD §3.6: "Denial is the `SUBMITTED → DENIED` transition, requiring
    `SUBMITTED` status (otherwise `ERR_INVALID_STATE`). It records the supplied
    `denial_reason`, leaves the item's prices, counters and tiers untouched, and
    advances the correction's own `version` by 1."
    PRD §2.5: "Conversely, a record whose stored fields are not changed by a
    request keeps its `updated_at` and its `version` untouched."

    Design: Corner/state_machines/denied_error_correction_is_terminal_and_a_later_approve_is_refused
    """
    scene = setup_certified_schedule(posting_month="2026-09")
    item = scene["items"][0]
    correction = new_correction(
        item["id"],
        114_000,
        10_500,
        scene["agent_headers"],
        reason="transposed digits on the filed case price",
    )
    denied = deny_correction(correction["id"], "supporting invoice was not attached")
    version_after_denial = denied["version"]

    response = api.approve_error_correction(correction["id"], regulator_headers())
    assert response.status_code == 409, (
        f"approving a DENIED correction must be a 409 conflict, got {response.status_code}"
    )
    validate_error(response, "ERR_INVALID_STATE")

    correction_after = read_correction(correction["id"])
    assert correction_after["status"] == "DENIED", (
        f"DENIED is terminal, got {correction_after['status']!r}"
    )
    assert correction_after["denial_reason"] == "supporting invoice was not attached", (
        f"the recorded denial_reason must survive the refused approval, "
        f"got {correction_after['denial_reason']!r}"
    )
    assert correction_after["version"] == version_after_denial, (
        f"a refused request changes no stored field, so version must stay "
        f"{version_after_denial}, got {correction_after['version']}"
    )

    item_after = read_item(item["id"])
    assert item_after["case_price_cents"] == 120_000, (
        f"the refused approval must not apply the corrected price, "
        f"got {item_after['case_price_cents']}"
    )
    assert item_after["unit_price_cents"] == 11_000, (
        f"the refused approval must not apply the corrected unit price, "
        f"got {item_after['unit_price_cents']}"
    )
    assert item_after["correction_count"] == 0, (
        f"the refused approval must not increment correction_count, "
        f"got {item_after['correction_count']}"
    )

    schedule = read_schedule(scene["schedule"]["id"])
    assert schedule["correction_count"] == 0, (
        f"the schedule's correction_count must stay 0, got {schedule['correction_count']}"
    )

    _, meta = validate_paginated(
        api.list_error_corrections(
            regulator_headers(), params={"item_id": item["id"], "status": "APPROVED"}
        )
    )
    assert meta["total_count"] == 0, (
        f"no correction on this item may be readable as APPROVED, got {meta['total_count']}"
    )
