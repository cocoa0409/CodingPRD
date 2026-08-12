"""Endpoint behavior: list filters, the weekly close, computed reads (PRD §2.3, §3.6, §3.8)."""
from test_helpers import (
    validate_success,
    validate_paginated,
    setup_distributor_film_theatre_screen,
    setup_proposed_booking,
    setup_accepted_booking,
    setup_in_play_agreement,
    file_and_submit_report,
    close_week,
    close_week_with_reports,
    settle_latest,
    get_latest_settlement,
    run_settled_week,
    setup_screen,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_booking_agreements_filter_by_deal_status(api):
    """PRD §2.3: "Most collections additionally accept optional equality filters drawn
    from the resource's own fields: `lifecycle_status`, `release_pattern`,
    `distributor_id`, `market_code`, `circuit`, `status`, `film_id`, `theatre_id`,
    `screen_id`, `aggregate_deal_id`, `deal_status`, `print_status`,
    `booking_agreement_id`, `week_index`, `variant`, `decision`, `market_id`,
    `parent_dispute_id`, and `window_kind`, as applicable per collection in §4."

    Design: Corner/endpoints/get_booking_agreements_filter_by_deal_status
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    tid = env["theatre"]["id"]
    fid = env["film"]["id"]
    ba1 = setup_accepted_booking(did, fid, tid, env["screen"]["id"])
    s2 = setup_screen(did, tid, auditorium_label="Auditorium 2")
    ba2 = setup_proposed_booking(did, fid, tid, s2["id"])

    data, meta = validate_paginated(
        api.list_booking_agreements(did, AUDITOR, params={"deal_status": "ACCEPTED"})
    )
    ids = [b["id"] for b in data]
    assert ba1["id"] in ids, "the ACCEPTED agreement must be returned"
    assert ba2["id"] not in ids, "the PROPOSED agreement must be filtered out"
    assert all(b["deal_status"] == "ACCEPTED" for b in data)

    all_data, _ = validate_paginated(api.list_booking_agreements(did, AUDITOR))
    all_ids = [b["id"] for b in all_data]
    assert ba1["id"] in all_ids and ba2["id"] in all_ids


def test_close_box_office_week_side_effects(api):
    """PRD §3.6: "Closing the week increments the distributor's `week_epoch` by one,
    locks every `SUBMITTED` report belonging to the prior week — stamping each with a
    `week_index` equal to the epoch — and walks each affected settlement through
    `PROVISIONAL` → `PENDING_FINAL` → `FINALIZED` in that order."

    Design: Corner/endpoints/close_box_office_week_side_effects_full
    """
    env = setup_in_play_agreement(
        booking_overrides={"min_weeks_committed": 1, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    report = file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 500000, 2000)

    distributor = close_week(did)
    assert distributor["week_epoch"] == 1, (
        f"the close must increment week_epoch 0 -> 1, got {distributor['week_epoch']}"
    )

    locked = validate_success(api.get_box_office_report(did, baid, report["id"], CLERK), 200)
    assert locked["status"] == "LOCKED", f"report must be LOCKED, got {locked['status']}"
    assert locked["week_index"] == 0, (
        f"the locked report must be stamped with the closed epoch 0, "
        f"got {locked['week_index']}"
    )

    settlement = get_latest_settlement(did, baid)
    assert settlement["week_index"] == 0
    assert settlement["status"] == "FINALIZED", (
        f"with no DRAFT or SUBMITTED reports remaining the settlement must finalize, "
        f"got {settlement['status']}"
    )


def test_holdover_decisions_computed_read(api):
    """PRD §3.8: "The weekly close also renders an automatic recommendation for every
    in-play, holdover-eligible agreement."
    PRD §3.8: "the decision's `week_index` is the epoch in which the decision was made,
    and its `prior_week_gross_cents` is the sum of the prior week's locked reports."
    With min_weeks_committed=1 and a locked week-1 gross of 250000 (>= 1 * 100000),
    the recommendation is AUTO_HOLD.

    Design: Corner/endpoints/holdover_decisions_computed_read
    """
    env = setup_in_play_agreement(
        booking_overrides={"min_weeks_committed": 1, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    # Week 0: settled, so weeks_played reaches 1 and the agreement becomes
    # holdover-eligible. Week 1: locked gross 250000 is the "prior week" for the
    # recommendation computed by the second close.
    run_settled_week(did, baid, 0, gross_cents=250000, admissions=1500)
    close_week_with_reports(did, 1, [(baid, 250000, 1500)])

    data = api.list_holdover_decisions(did, baid, BOOKER).json()["data"]
    assert len(data) == 1, f"expected exactly one recommendation, got {len(data)}"
    decision = data[0]
    assert decision["decision"] == "AUTO_HOLD", (
        f"250000 >= 1 * 100000 must recommend AUTO_HOLD, got {decision['decision']}"
    )
    assert decision["prior_week_gross_cents"] == 250000, (
        f"prior week locked gross must be 250000, got {decision['prior_week_gross_cents']}"
    )
