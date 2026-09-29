"""The two deliberately different occupancy rules: ad windows and ice-bed slots."""
from test_helpers import ApiErrorId, fixtures, validate_error, validate_success
from test_helpers.assertions import assert_advertised_item, assert_instant, assert_weight
from test_helpers.factories import ad_item_payload
from test_helpers.test_users import make_merchandising_lead_headers, make_seafood_manager_headers


def _cod_lot_with_a_morning_window(api) -> dict:
    """A cased cod lot advertised across the 09:00 to 12:00 window."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(api, counter_id, env["supplier"]["id"], env["cod"]["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    morning = fixtures.draft_ad_item(
        api,
        counter_id,
        lot["id"],
        headline="Morning Cod Feature",
        ad_start_at="2026-08-01T09:00:00Z",
        ad_end_at="2026-08-01T12:00:00Z",
    )
    env.update({"lot": lot, "morning": morning})
    return env


def _slot_one_vacated_at_ten(api) -> dict:
    """A 5.000 kg lot sold out of slot 1 at 10:00, with a second lot waiting to be cased."""
    env = fixtures.base_environment(api, "2026-08-01T10:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    first = fixtures.receive_lot(
        api, counter_id, supplier_id, env["cod"]["id"], received_weight_kg=5.000
    )
    fixtures.case_lot(api, counter_id, first["id"], 1)
    second = fixtures.receive_lot(
        api,
        counter_id,
        supplier_id,
        env["cod"]["id"],
        lot_code="COD-0801-B",
        received_weight_kg=8.000,
    )
    depleted = fixtures.record_sales(api, counter_id, first["id"], 5.000)
    env.update({"first": first, "second": second, "depleted": depleted})
    return env


def test_01_two_ad_windows_that_merely_touch_are_both_permitted(api):
    """PRD §3.6: "Two windows that merely touch, where one ends at exactly the instant the
    next begins, are permitted; a genuine overlap is rejected with `ERR_AD_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/ad_window_half_open_adjacency_allowed
    """
    env = _cod_lot_with_a_morning_window(api)
    counter_id = env["counter"]["id"]

    response = api.create_ad_item(
        ad_item_payload(
            counter_id,
            env["lot"]["id"],
            headline="Afternoon Cod Feature",
            ad_start_at="2026-08-01T12:00:00Z",
            ad_end_at="2026-08-01T15:00:00Z",
        ),
        make_merchandising_lead_headers(),
    )
    afternoon = validate_success(response, expected_status=201)

    assert_advertised_item(afternoon)
    assert afternoon["status"] == "DRAFT"
    assert_instant(afternoon["ad_start_at"], "2026-08-01T12:00:00Z")


def test_02_a_window_that_starts_one_minute_early_genuinely_overlaps(api):
    """PRD §3.6: "And the advertising window is a **half-open interval** running from
    `ad_start_at` inclusive to `ad_end_at` exclusive, with no buffer whatsoever: it must not
    overlap the window of any other `AdvertisedItem` for the same `lot_id` whose `status` is
    `DRAFT`, `APPROVED` or `PUBLISHED`."

    Design: Difficulty/resource_temporal_overlap/ad_window_half_open_adjacency_allowed
    """
    env = _cod_lot_with_a_morning_window(api)
    counter_id = env["counter"]["id"]
    fixtures.draft_ad_item(
        api,
        counter_id,
        env["lot"]["id"],
        headline="Afternoon Cod Feature",
        ad_start_at="2026-08-01T12:00:00Z",
        ad_end_at="2026-08-01T15:00:00Z",
    )

    response = api.create_ad_item(
        ad_item_payload(
            counter_id,
            env["lot"]["id"],
            headline="Overlapping Cod Feature",
            ad_start_at="2026-08-01T11:59:00Z",
            ad_end_at="2026-08-01T13:00:00Z",
        ),
        make_merchandising_lead_headers(),
    )

    validate_error(response, ApiErrorId.ERR_AD_WINDOW_OVERLAP.value, expected_status=409)


def test_03_the_rejected_window_leaves_only_the_two_accepted_drafts(api):
    """PRD §3.6: "The draft is created with `status` `DRAFT`, `cool_review_status`
    `COOL_PENDING`, `claim_review_status` `CLAIM_PENDING`, `cool_statement` null, both
    reviewer identifiers null and `retract_reason` null."

    Design: Difficulty/resource_temporal_overlap/ad_window_half_open_adjacency_allowed
    """
    env = _cod_lot_with_a_morning_window(api)
    counter_id = env["counter"]["id"]
    fixtures.draft_ad_item(
        api,
        counter_id,
        env["lot"]["id"],
        headline="Afternoon Cod Feature",
        ad_start_at="2026-08-01T12:00:00Z",
        ad_end_at="2026-08-01T15:00:00Z",
    )
    response = api.create_ad_item(
        ad_item_payload(
            counter_id,
            env["lot"]["id"],
            headline="Overlapping Cod Feature",
            ad_start_at="2026-08-01T11:59:00Z",
            ad_end_at="2026-08-01T13:00:00Z",
        ),
        make_merchandising_lead_headers(),
    )
    validate_error(response, ApiErrorId.ERR_AD_WINDOW_OVERLAP.value, expected_status=409)

    items = fixtures.list_ad_items(api, {"lot_id": env["lot"]["id"]})
    assert len(items) == 2, f"expected exactly two advertisement rows, got {len(items)}"
    for item in items:
        assert item["status"] == "DRAFT"
        assert item["cool_review_status"] == "COOL_PENDING"
        assert item["claim_review_status"] == "CLAIM_PENDING"
        assert item["cool_statement"] is None
        assert item["retract_reason"] is None


def test_04_selling_the_last_kilogram_vacates_the_slot(api):
    """PRD §3.3: "When a sale brings `remaining_weight_kg` to exactly 0.000, the lot advances
    from `CASED` to `DEPLETED`: `vacated_at` is stamped from the logical clock, `case_slot` is
    cleared to null, and every `PUBLISHED` case label for that lot is withdrawn with a
    `withdraw_reason` of `MANUAL`."

    Design: Difficulty/resource_temporal_overlap/case_slot_closed_interval_with_sanitation_buffer
    """
    env = _slot_one_vacated_at_ten(api)

    depleted = env["depleted"]
    assert depleted["intake_status"] == "DEPLETED"
    assert depleted["case_slot"] is None
    assert_instant(depleted["vacated_at"], "2026-08-01T10:00:00Z")
    assert_weight(depleted["remaining_weight_kg"], 0.000)


def test_05_the_next_occupant_is_refused_inside_the_sanitation_buffer(api):
    """PRD §3.3: "The slot must be genuinely free, which the system evaluates as a **closed
    interval** running from `cased_at` through `vacated_at` with a 30-minute sanitation buffer
    appended: no other lot on the counter may currently hold the requested slot with an
    `intake_status` of `CASED` or `HELD`, and for the slot's most recent previous occupant the
    logical clock must be at or after that occupant's `vacated_at` plus 30 minutes. Either
    failure yields `ERR_CASE_SLOT_OCCUPIED`."

    Design: Difficulty/resource_temporal_overlap/case_slot_closed_interval_with_sanitation_buffer
    """
    env = _slot_one_vacated_at_ten(api)
    counter_id = env["counter"]["id"]
    fixtures.set_clock(api, "2026-08-01T10:20:00Z")

    response = api.case_lot(
        env["second"]["id"], {"case_slot": 1}, make_seafood_manager_headers(counter_id)
    )
    validate_error(response, ApiErrorId.ERR_CASE_SLOT_OCCUPIED.value, expected_status=409)

    assert fixtures.read_lot(api, counter_id, env["second"]["id"])["intake_status"] == "RECEIVED"


def test_06_the_slot_reopens_exactly_thirty_minutes_after_it_was_vacated(api):
    """PRD §3.3: "The slot must be genuinely free, which the system evaluates as a **closed
    interval** running from `cased_at` through `vacated_at` with a 30-minute sanitation buffer
    appended: no other lot on the counter may currently hold the requested slot with an
    `intake_status` of `CASED` or `HELD`, and for the slot's most recent previous occupant the
    logical clock must be at or after that occupant's `vacated_at` plus 30 minutes."

    Design: Difficulty/resource_temporal_overlap/case_slot_closed_interval_with_sanitation_buffer
    """
    env = _slot_one_vacated_at_ten(api)
    counter_id = env["counter"]["id"]
    fixtures.set_clock(api, "2026-08-01T10:30:00Z")

    response = api.case_lot(
        env["second"]["id"], {"case_slot": 1}, make_seafood_manager_headers(counter_id)
    )
    cased = validate_success(response, expected_status=200)

    assert cased["intake_status"] == "CASED"
    assert cased["case_slot"] == 1
    assert_instant(cased["cased_at"], "2026-08-01T10:30:00Z")
