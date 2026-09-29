"""Queue B — section: consistency_model.

The declared consistency model is immediate: a mutation's own response body already
carries every derived field it produced, the very next read of a parent shows the
reconciled roll-ups and the bumped `version`, list projections reflect the write
with no settling delay, and a rejected write leaves nothing partially visible.

Every precondition is built inside the test: the server restarts per test, so the
database is empty when each test begins.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.corner_support_g import (
    CE,
    CE_ALT,
    CM,
    DC,
    cat_coded_claim,
    declared_hurricane_event,
    desk_certified_adjuster,
    inspected_claim_via_desk_assignment,
    make_adjuster_headers_for,
    triaged_fast_track_claim,
    two_room_block,
)


def test_triage_response_already_carries_every_derived_claim_field(api):
    """PRD §3.6: "Triage stamps `severity_score` and `triage_tier`, stamps
    `inspection_mode`, stamps `deadline_utc`, and appends an `INITIAL_CASE` entry to the
    reserve ledger whose case-reserve movement comes from the initial-reserve rule and whose
    paid movement is exactly 0.00, taking the next per-event sequence number."
    PRD §3.6: "Clamp the result so it is not below 0 and not above 100, and only then round
    half up to 2 decimal places — a single rounding, applied after the clamp."
    PRD §3.6: "The score then selects the band recorded in `triage_tier`: a score of 75.00
    or more is `CAT_SEVERE`, a score of 50.00 or more but below 75.00 is `COMPLEX`, a score
    of 25.00 or more but below 50.00 is `STANDARD`, and anything below 25.00 is
    `FAST_TRACK`."
    PRD §3.6: "Otherwise, if the tier is `FAST_TRACK` and the `reported_loss_amount` is
    10000.00 or less, the mode is `DESK` — the boundary is inclusive, so a reported loss of
    exactly 10000.00 resolves to `DESK` while 10000.01 resolves to `FIELD`."
    PRD §3.6: "First compute the eligible damage of each coverage line as the line's
    `estimated_damage_amount` capped at its `limit_amount`, less its `deductible_amount`,
    with a floor of zero; sum those **raw, unrounded** line values; take the greater of that
    sum and the claim's `reported_loss_amount` as the basis; multiply the basis by the tier
    reserve factor for the claim's `triage_tier` — 0.85 for `CAT_SEVERE`, 0.65 for
    `COMPLEX`, 0.45 for `STANDARD`, 0.25 for `FAST_TRACK` — and round half up to 2 decimal
    places **once, at the end**."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/corner_cm_triage_response_carries_every_derived_output
    """
    event = declared_hurricane_event(api, "CAT-2026-134")
    claim = cat_coded_claim(api, event["id"], "POL-1015")
    assert claim["handling_status"] == "INTAKE"

    triaged = validate_success(api.triage_claim(claim["id"], CE))
    # 100 * (8000/300000) * 1.15 HURRICANE + 20 * 0.1000 = 5.0667 -> 5.07 -> FAST_TRACK.
    assert triaged["handling_status"] == "TRIAGED"
    assert_money_equals(triaged["severity_score"], 5.07, "severity_score")
    assert triaged["triage_tier"] == "FAST_TRACK"
    assert triaged["inspection_mode"] == "DESK"
    # (120000 capped at 300000) - 5000 = 115000 raw, * 0.25 FAST_TRACK = 28750.00.
    assert_money_equals(triaged["case_reserve"], 28750.00, "case_reserve in the triage response")

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_CASE"
    assert_money_equals(rows[0]["delta_case_reserve"], 28750.00, "delta_case_reserve")


def test_event_read_after_triage_shows_reconciled_rollups_and_version_four(api):
    """PRD §2.5: "Any operation that changes an event's own status or any of its computed
    roll-ups increments that event's `version` by 1; any operation that changes a claim's own
    fields, its handling or payment axis, or its reserve position increments that claim's
    `version` by 1."
    PRD §2.5: "A single request may therefore increment two versions — triaging a claim, for
    example, advances both the claim's `version` and its parent event's `version`."
    PRD §3.6: "When `event_id` was supplied, the parent event's `open_claim_count` and
    posture are recomputed at once."
    PRD §3.1: "`open_claim_count` is the number of claims on the event whose
    `handling_status` is neither `CLOSED` nor `TRANSFERRED`."
    PRD §3.1: "`case_reserve_total` and `paid_total` are the sums of the case-reserve and
    paid movements of every ledger entry belonging to the event, each to 2 decimal places,
    and `incurred_total` is their sum — the conserved quantity of §2.10."
    PRD §2.9: "**Step three bands the strain total.** A strain of 8 or more bands as
    `FROZEN`; a strain of 3 or more but below 8 bands as `RESTRICTED`; a strain below 3 bands
    as `OPEN`."

    Design: Corner/consistency_model/corner_cm_parent_rollups_and_version_visible_on_next_read
    """
    event = declared_hurricane_event(api, "CAT-2026-135")
    triaged_fast_track_claim(api, event["id"], "POL-1016")

    after = validate_success(api.get_event(event["id"], CM))
    assert after["open_claim_count"] == 1
    assert_money_equals(after["case_reserve_total"], 28750.00, "case_reserve_total")
    assert_money_equals(after["paid_total"], 0.00, "paid_total")
    assert_money_equals(after["incurred_total"], 28750.00, "incurred_total")
    # Registration 1, declaration 2, cat-coded intake 3, triage 4.
    assert after["version"] == 4, f"expected version 4 after three mutations, got {after['version']}"
    assert after["status"] == "DECLARED"
    # A FAST_TRACK claim is not severe, no snapshot exists and no moratorium binds: strain 0.
    assert after["posture"] == "OPEN"
    assert_money_equals(after["gross_loss_estimate"], 0.00, "gross_loss_estimate")


def test_advance_issuance_is_visible_on_the_advance_the_claim_and_the_event_at_once(api):
    """PRD §3.8: "Issuance creates the advance in `ISSUED`, refreshes the claim's
    `advance_cap`, and appends a `PAYMENT` ledger entry whose paid movement is the issued
    `amount` and whose case-reserve movement is the negation of that amount, recording that
    row's identifier in the advance's `reserve_entry_id`."
    PRD §3.8: "The claim's `advance_paid_total`, `paid_amount` and `case_reserve` and the
    event's `paid_total` and `case_reserve_total` are all recomputed — but the event's
    `incurred_total` is **unchanged**, because the two movements on the entry are equal and
    opposite."
    PRD §3.8: "Multiply the line-derived cap by the tier multiplier for the claim's
    `triage_tier` — 1.00 for `CAT_SEVERE`, 0.85 for `COMPLEX`, 0.60 for `STANDARD`, 0.40 for
    `FAST_TRACK` — and round to 2 decimal places."
    PRD §3.8: "Otherwise the issued `amount` is the lesser of the `requested_amount` and the
    headroom."

    Design: Corner/consistency_model/corner_cm_advance_issuance_visible_in_both_parents_at_once
    """
    event = declared_hurricane_event(api, "CAT-2026-136")
    claim = triaged_fast_track_claim(api, event["id"], "POL-1017")

    advance = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 1000, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )
    assert advance["status"] == "ISSUED"
    assert_money_equals(advance["amount"], 1000.00, "amount")

    after_claim = validate_success(api.get_claim(claim["id"], CE))
    assert after_claim["payment_status"] == "ADVANCE_ISSUED"
    assert_money_equals(after_claim["advance_paid_total"], 1000.00, "advance_paid_total")
    assert_money_equals(after_claim["paid_amount"], 1000.00, "paid_amount")
    assert_money_equals(after_claim["case_reserve"], 27750.00, "case_reserve")
    # (120000 capped) - 5000 = 115000 * 30% DWELLING = 34500.00, * 0.40 FAST_TRACK = 13800.00.
    assert_money_equals(after_claim["advance_cap"], 13800.00, "advance_cap")

    after_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(after_event["paid_total"], 1000.00, "paid_total")
    assert_money_equals(after_event["case_reserve_total"], 27750.00, "case_reserve_total")
    assert_money_equals(after_event["incurred_total"], 28750.00, "incurred_total")

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 2
    payment_row = [r for r in rows if r["sequence_no"] == 2][0]
    assert payment_row["entry_type"] == "PAYMENT"
    assert_money_equals(payment_row["delta_paid"], 1000.00, "delta_paid")
    assert_money_equals(payment_row["delta_case_reserve"], -1000.00, "delta_case_reserve")


def test_ledger_list_read_after_three_appends_returns_sequence_one_two_three(api):
    """PRD §2.3: "Two collections deliberately depart from that default because their
    business meaning is sequential: the reserve ledger is returned in `sequence_no` ascending
    order, and loss-estimate snapshots are returned in `computed_at_utc` ascending order."
    PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` inside
    `meta`, where `total_count` is the number of rows matching the filters before pagination
    is applied and `has_more` is true when rows remain beyond the current page."
    PRD §3.8: "The append is written with the next per-event `sequence_no`, an
    `effective_utc` of the current instant, and a null `reverses_entry_id`."
    PRD §3.1: "`case_reserve_total` and `paid_total` are the sums of the case-reserve and
    paid movements of every ledger entry belonging to the event, each to 2 decimal places,
    and `incurred_total` is their sum — the conserved quantity of §2.10."

    Design: Corner/consistency_model/corner_cm_reserve_ledger_readback_in_sequence_order
    """
    event = declared_hurricane_event(api, "CAT-2026-137")
    claim = triaged_fast_track_claim(api, event["id"], "POL-1018")
    validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 1000, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )
    current_version = validate_success(api.get_claim(claim["id"], CE))["version"]
    validate_success(
        api.create_reserve_entry(
            claim["id"],
            {
                "expected_claim_version": current_version,
                "entry_type": "REVISION",
                "delta_case_reserve": 500,
                "delta_paid": 0,
            },
            CE,
        ),
        201,
    )

    rows, meta = validate_paginated(api.list_reserve_entries(CM, params={"event_id": event["id"]}))
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert [r["sequence_no"] for r in rows] == [1, 2, 3], "the ledger reads in sequence_no ASC"
    assert [r["entry_type"] for r in rows] == ["INITIAL_CASE", "PAYMENT", "REVISION"]

    after_claim = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(after_claim["case_reserve"], 28250.00, "case_reserve")
    assert_money_equals(after_claim["paid_amount"], 1000.00, "paid_amount")

    after_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(after_event["case_reserve_total"], 28250.00, "case_reserve_total")
    assert_money_equals(after_event["paid_total"], 1000.00, "paid_total")
    assert_money_equals(after_event["incurred_total"], 29250.00, "incurred_total")


def test_a_coordinators_block_open_immediately_stales_the_managers_event_version(api):
    """PRD §3.4: "Opening recomputes the parent event's `housing_committed_cost`, because the
    block now sits in the committed population."
    PRD §2.5: "Any operation that changes an event's own status or any of its computed
    roll-ups increments that event's `version` by 1; any operation that changes a claim's own
    fields, its handling or payment axis, or its reserve position increments that claim's
    `version` by 1."
    PRD §2.8: "A request that creates a loss-estimate snapshot must carry
    `expected_event_version` holding the client's last observed `version` of the target
    `CatastropheEvent`. If that value does not equal the event's current `version`, the
    request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412) and nothing is created."

    Design: Corner/consistency_model/corner_cm_interleaved_event_write_immediately_invalidates_earlier_read
    """
    event = declared_hurricane_event(api, "CAT-2026-138")
    manager_read_version = validate_success(api.get_event(event["id"], CM))["version"]

    block = two_room_block(api, event["id"])
    validate_success(api.open_housing_block(block["id"], DC))

    coordinator_bumped = validate_success(api.get_event(event["id"], CM))["version"]
    assert coordinator_bumped > manager_read_version, (
        "opening a block recomputes an event roll-up, so the manager's read is already stale"
    )

    rejected = api.create_loss_estimate(
        {
            "event_id": event["id"],
            "method": "EXPOSURE_BASED",
            "expected_event_version": manager_read_version,
        },
        CM,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_EVENT_VERSION, 412)

    after = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(after["gross_loss_estimate"], 0.00, "gross_loss_estimate")
    _, meta = validate_paginated(api.list_loss_estimates(CM, params={"event_id": event["id"]}))
    assert meta["total_count"] == 0, "the rejected mint stored nothing"


def test_inspection_completion_immediately_stales_the_post_triage_claim_version(api):
    """PRD §2.8: "A request that appends a manual reserve entry to a claim must carry
    `expected_claim_version` holding the client's last observed `version` of that `Claim`. If
    that value does not equal the claim's current `version`, the request is rejected with
    `ERR_STALE_CLAIM_VERSION` (HTTP 412) and no ledger row is written."
    PRD §3.7: "Completion stamps `report_submitted_at_utc` at the current logical-clock
    instant, recomputes the adjuster's `open_assignment_count` and `surge_capacity_score`, and
    pushes the claim `INSPECTION_PENDING → INSPECTED`."
    PRD §3.7: "Sum the `deductible_amount` of every coverage line on the claim. Subtract that
    total from the claim's newly refreshed `verified_damage_amount`, floor the result at zero,
    and round half up to 2 decimal places to obtain the target case reserve."
    PRD §3.7: "The entry's case-reserve movement is that target less the claim's
    `case_reserve` as it stands immediately before the append, rounded half up to 2 decimal
    places — a figure that is frequently **negative**, when an inspection verifies less damage
    than the first notice suggested."

    Design: Corner/consistency_model/corner_cm_cascade_claim_version_bump_immediately_invalidates_earlier_read
    """
    event = declared_hurricane_event(api, "CAT-2026-139")
    claim_at_triage, _adjuster, _assignment = inspected_claim_via_desk_assignment(
        api, event["id"], "POL-1019", verified_damage_amount=90000
    )

    rejected = api.create_reserve_entry(
        claim_at_triage["id"],
        {
            "expected_claim_version": claim_at_triage["version"],
            "entry_type": "REVISION",
            "delta_case_reserve": 250,
            "delta_paid": 0,
        },
        CE,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_CLAIM_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_reserve_entries(CE, params={"claim_id": claim_at_triage["id"]})
    )
    assert meta["total_count"] == 2, "the opening row plus the inspection-driven revision"
    assert [r["entry_type"] for r in rows] == ["INITIAL_CASE", "REVISION"]

    after_claim = validate_success(api.get_claim(claim_at_triage["id"], CE))
    assert after_claim["handling_status"] == "INSPECTED"
    # 90000 verified less the single 5000 deductible = 85000.00 target case reserve.
    assert_money_equals(after_claim["case_reserve"], 85000.00, "case_reserve")
    assert_money_equals(after_claim["verified_damage_amount"], 90000.00, "verified_damage_amount")


def test_close_blocked_by_an_outstanding_advance_commits_nothing_observable(api):
    """PRD §3.6: "The claim's `payment_status` must be either `NONE` or `SETTLED` — a file
    sitting in `ADVANCE_ISSUED` or `PARTIAL_PAID` has money out the door and unfinished
    settlement, and closing it is refused with `ERR_ADVANCE_OUTSTANDING`."
    PRD §3.6: "Closure records the acting `X-User-ID` in `closing_examiner_user_id` and
    recomputes the event's `open_claim_count` and posture."
    PRD §3.1: "`open_claim_count` is the number of claims on the event whose
    `handling_status` is neither `CLOSED` nor `TRANSFERRED`."

    Design: Corner/consistency_model/corner_cm_rejected_close_leaves_no_partial_visibility
    """
    event = declared_hurricane_event(api, "CAT-2026-140")
    claim = triaged_fast_track_claim(api, event["id"], "POL-1020")
    validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 1000, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )
    adjuster = desk_certified_adjuster(api)
    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "DESK",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-02T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    own = make_adjuster_headers_for(adjuster)
    validate_success(api.start_inspection(assignment["id"], own))
    validate_success(
        api.complete_inspection(assignment["id"], {"verified_damage_amount": 90000}, own)
    )

    # examiner-bob never issued the advance, so segregation of duties does not bite.
    rejected = api.close_claim(claim["id"], CE_ALT)
    validate_error(rejected, ApiErrorId.ERR_ADVANCE_OUTSTANDING, 409)

    after_claim = validate_success(api.get_claim(claim["id"], CE))
    assert after_claim["handling_status"] == "INSPECTED", "the rejected close committed nothing"
    assert after_claim["payment_status"] == "ADVANCE_ISSUED"
    assert after_claim["closing_examiner_user_id"] is None

    after_event = validate_success(api.get_event(event["id"], CM))
    assert after_event["open_claim_count"] == 1, "the claim never left the open population"


def test_triage_stales_the_snapshot_and_the_next_read_already_shows_restricted(api):
    """PRD §3.6: "It then recomputes the claim's `case_reserve` and the event's
    `case_reserve_total` and `incurred_total`, flips every loss-estimate snapshot on the event
    whose recorded ledger high-water mark is below the new sequence number to stale, and
    recomputes posture."
    PRD §3.8: "Its `stale` flag is a computed property re-evaluated on every read: it reads
    true exactly when a ledger entry exists on the event whose `sequence_no` is greater than
    the snapshot's recorded high-water mark."
    PRD §2.9: "The second term contributes 3 when the event's latest loss-estimate snapshot is
    stale, and 0 otherwise; the latest snapshot is the one with the greatest `computed_at_utc`,
    and if several share that instant, the one with the earliest `created_at` wins."
    PRD §2.9: "**Step three bands the strain total.** A strain of 8 or more bands as `FROZEN`;
    a strain of 3 or more but below 8 bands as `RESTRICTED`; a strain below 3 bands as `OPEN`."
    PRD §2.9: "**Step four takes the stricter of the floor and the band** as the event's
    `posture`, so a `DEMOBILIZING` event whose strain bands `OPEN` still reads `RESTRICTED`,
    and any event whose strain reaches 8 reads `FROZEN` even while `SURGE_ACTIVE`."

    Design: Corner/consistency_model/corner_cm_posture_flip_visible_in_the_read_after_staling_write
    """
    event = declared_hurricane_event(api, "CAT-2026-141")
    validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": event["version"],
            },
            CM,
        ),
        201,
    )
    claim = cat_coded_claim(api, event["id"], "POL-1021")

    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert triaged["triage_tier"] == "FAST_TRACK"
    assert_money_equals(triaged["case_reserve"], 28750.00, "case_reserve")

    after_event = validate_success(api.get_event(event["id"], CM))
    assert after_event["status"] == "DECLARED"
    # Strain 0 severe-unassigned + 3 stale-snapshot + 0 moratorium = 3 -> RESTRICTED.
    assert after_event["posture"] == "RESTRICTED"

    rows, meta = validate_paginated(api.list_loss_estimates(CM, params={"event_id": event["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["stale"] is True, "sequence_no 1 sits above the recorded high-water mark 0"
    assert rows[0]["input_reserve_sequence_high_water"] == 0
    assert_money_equals(rows[0]["gross_estimate"], 35000000.00, "gross_estimate")

    _, stale_meta = validate_paginated(
        api.list_loss_estimates(CM, params={"event_id": event["id"], "stale": "true"})
    )
    assert stale_meta["total_count"] == 1, "the stale filter sees the flip immediately"


def test_claim_list_and_parent_count_reflect_the_intake_with_no_lag(api):
    """PRD §3.6: "A new claim is `INTAKE` on the handling axis and `NONE` on the payment axis,
    with `reported_at_utc` stamped at the current logical-clock instant, `severity_score` of
    0.00, `reopen_count` of 0, and `triage_tier`, `inspection_mode`, `deadline_utc` and
    `verified_damage_amount` all null."
    PRD §3.6: "Claim lists may be filtered by `event_id`, `transfer_batch_id`,
    `handling_status`, `payment_status`, `triage_tier` and `loss_state`."
    PRD §2.3: "`limit` controls page size: its default is 10, its minimum accepted value is 1,
    and its maximum accepted value is 100."
    PRD §2.3: "`offset` controls the starting position: its default is 0 and its minimum
    accepted value is 0."
    PRD §3.1: "`open_claim_count` is the number of claims on the event whose
    `handling_status` is neither `CLOSED` nor `TRANSFERRED`."

    Design: Corner/consistency_model/corner_cm_list_projection_reflects_write_without_lag
    """
    event = declared_hurricane_event(api, "CAT-2026-142")

    claim = cat_coded_claim(api, event["id"], "POL-1022")
    assert claim["handling_status"] == "INTAKE"
    assert claim["payment_status"] == "NONE"

    rows, meta = validate_paginated(api.list_claims(CE, params={"event_id": event["id"]}))
    assert meta["total_count"] == 1
    assert meta["limit"] == 10, "the default page size is 10"
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert rows[0]["id"] == claim["id"]

    _, triaged_meta = validate_paginated(
        api.list_claims(CE, params={"event_id": event["id"], "handling_status": "TRIAGED"})
    )
    assert triaged_meta["total_count"] == 0, "the claim has not been triaged yet"

    after_event = validate_success(api.get_event(event["id"], CM))
    assert after_event["open_claim_count"] == 1
    # Registration 1, declaration 2, cat-coded intake 3.
    assert after_event["version"] == 3, f"expected version 3, got {after_event['version']}"
