"""The posting run's supersession chain, and the item statuses that admit a correction."""

from test_helpers import (
    api_client,
    assert_error_correction,
    assert_posted_price_payload,
    assert_posting_run_payload,
    assert_price_schedule,
    certify_schedule,
    create_error_correction_payload,
    new_item,
    new_schedule,
    new_tier,
    read_item,
    read_posted_price,
    read_schedule,
    read_tier,
    regulator_headers,
    run_posting,
    set_clock,
    setup_licensee_base,
    setup_submitted_schedule,
    submit_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_month_certified_scene():
    """One wholesaler with an August and a September schedule certified on the same key."""
    scene = setup_licensee_base()

    schedule_aug = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-08",
    )
    item_aug = new_item(
        schedule_aug["id"],
        scene["brand"]["id"],
        scene["agent_headers"],
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=120_000,
        unit_price_cents=11_000,
    )
    submit_schedule(schedule_aug["id"], scene["agent_headers"])
    schedule_aug = certify_schedule(schedule_aug["id"], scene["certifier_headers"])
    tier_aug = new_tier(
        item_aug["id"], scene["agent_headers"], min_cases=5, discount_pct=0.10
    )

    schedule_sep = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-09",
    )
    item_sep = new_item(
        schedule_sep["id"],
        scene["brand"]["id"],
        scene["agent_headers"],
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=125_000,
        unit_price_cents=12_000,
    )
    submit_schedule(schedule_sep["id"], scene["agent_headers"])
    schedule_sep = certify_schedule(schedule_sep["id"], scene["certifier_headers"])

    scene["schedule_aug"] = schedule_aug
    scene["item_aug"] = item_aug
    scene["tier_aug"] = tier_aug
    scene["schedule_sep"] = schedule_sep
    scene["item_sep"] = item_sep
    return scene


def _first_posting_run(scene):
    set_clock("2026-09-01T00:00:00Z")
    return run_posting(scene["program"]["id"])


def test_first_posting_run_takes_only_the_schedule_whose_effective_date_has_arrived():
    """September's filing is still waiting for its own month; August goes effective alone.

    PRD §3.7: "The run considers every schedule of that program whose `status` is `POSTED`
    and whose two temporal gates have both passed: the schedule's `effective_date` must be
    at or before the current server time, and its `hold_window_ends_at` must be at or
    before the current server time."

    Design: Difficulty/transitive_cascade/posting_run_supersession_cascades_from_new_item_through_tier_to_prior_schedule
    """
    scene = _two_month_certified_scene()

    result = _first_posting_run(scene)

    assert_posting_run_payload(result)
    assert result["processed_schedule_count"] == 1
    assert result["effective_schedule_ids"] == [scene["schedule_aug"]["id"]]
    assert result["superseded_schedule_ids"] == []

    assert read_schedule(scene["schedule_aug"]["id"])["status"] == "EFFECTIVE"
    assert read_item(scene["item_aug"]["id"])["status"] == "EFFECTIVE"
    assert read_schedule(scene["schedule_sep"]["id"])["status"] == "POSTED"
    assert read_item(scene["item_sep"]["id"])["status"] == "POSTED"
    assert read_tier(scene["tier_aug"]["id"])["status"] == "ACTIVE"


def test_second_posting_run_cascades_from_the_new_item_through_the_tier_to_the_schedule():
    """One newly effective item displaces the old item, kills its tier and supersedes its schedule.

    PRD §3.7: "Every quantity discount tier of a superseded item that was `ACTIVE` moves
    to `INACTIVE` — the old tiers stop being usable for invoice pricing the instant their
    item is displaced."

    Design: Difficulty/transitive_cascade/posting_run_supersession_cascades_from_new_item_through_tier_to_prior_schedule
    """
    scene = _two_month_certified_scene()
    _first_posting_run(scene)

    set_clock("2026-10-01T00:00:00Z")
    result = run_posting(scene["program"]["id"])

    assert_posting_run_payload(result)
    assert result["processed_schedule_count"] == 1
    assert result["effective_schedule_ids"] == [scene["schedule_sep"]["id"]]
    assert result["superseded_schedule_ids"] == [scene["schedule_aug"]["id"]]

    item_sep = read_item(scene["item_sep"]["id"])
    assert item_sep["status"] == "EFFECTIVE"
    assert item_sep["supersedes_item_id"] == scene["item_aug"]["id"]

    item_aug = read_item(scene["item_aug"]["id"])
    assert item_aug["status"] == "SUPERSEDED"
    assert item_aug.get("supersedes_item_id") is None

    tier_aug = read_tier(scene["tier_aug"]["id"])
    assert tier_aug["status"] == "INACTIVE"
    assert tier_aug["discounted_case_price_cents"] == 108_000

    schedule_aug = read_schedule(scene["schedule_aug"]["id"])
    assert_price_schedule(schedule_aug)
    assert schedule_aug["status"] == "SUPERSEDED"
    assert schedule_aug["superseded_by_schedule_id"] == scene["schedule_sep"]["id"]

    schedule_sep = read_schedule(scene["schedule_sep"]["id"])
    assert schedule_sep["status"] == "EFFECTIVE"
    assert schedule_sep.get("superseded_by_schedule_id") is None


def test_posted_price_for_the_displaced_key_resolves_to_the_newer_item():
    """Asking the superseded item what is posted returns its successor's price.

    PRD §3.7: "Otherwise the resolved item is the candidate with the greatest
    owning-schedule `effective_date`; ties are broken by the greatest owning-schedule
    `certified_at`; any remaining tie is broken by the earliest `created_at` — that is,
    ascending."

    Design: Difficulty/transitive_cascade/posting_run_supersession_cascades_from_new_item_through_tier_to_prior_schedule
    """
    scene = _two_month_certified_scene()
    _first_posting_run(scene)
    set_clock("2026-10-01T00:00:00Z")
    run_posting(scene["program"]["id"])

    payload = read_posted_price(
        scene["item_aug"]["id"], variant="as_amended", as_of="2026-10-01T00:00:00Z"
    )
    assert_posted_price_payload(payload)
    assert payload["item_id"] == scene["item_aug"]["id"]
    assert payload["resolved_item_id"] == scene["item_sep"]["id"]
    assert payload["posted_case_price_cents"] == 125_000
    assert payload["posted_unit_price_cents"] == 12_000

    items = api_client.list_price_schedule_items(
        regulator_headers(), params={"supersedes_item_id": scene["item_aug"]["id"]}
    )
    data, meta = validate_paginated(items)
    assert meta["total_count"] == 1
    assert data[0]["id"] == scene["item_sep"]["id"]

    tiers = api_client.list_quantity_discount_tiers(
        regulator_headers(),
        params={"item_id": scene["item_aug"]["id"], "status": "ACTIVE"},
    )
    _tier_data, tier_meta = validate_paginated(tiers)
    assert tier_meta["total_count"] == 0


def _long_correction_window_scene():
    """A submitted, uncertified schedule under a program with a 120 day correction window."""
    return setup_submitted_schedule(program_overrides={"correction_window_days": 120})


def test_correction_filed_against_a_draft_item_is_refused():
    """Submission does not post an item, so a correction has nothing admissible to correct.

    PRD §3.6: "The item's `status` must be `POSTED` or `EFFECTIVE`; anything else is
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/error_correction_filing_is_gated_by_the_price_schedule_item_status_across_draft_posted_effective
    """
    scene = _long_correction_window_scene()
    item = scene["items"][0]
    assert read_item(item["id"])["status"] == "DRAFT"

    response = api_client.create_error_correction(
        create_error_correction_payload(item["id"], 114_000, 10_500),
        scene["agent_headers"],
    )

    validate_error(response, "ERR_INVALID_STATE", 409)

    listing = api_client.list_error_corrections(
        regulator_headers(), params={"item_id": item["id"]}
    )
    _data, meta = validate_paginated(listing)
    assert meta["total_count"] == 0


def test_the_same_correction_is_admitted_once_certification_posts_the_item():
    """Certification is what opens the correction pathway on an unchanged filing.

    PRD §3.3: "Items remain `DRAFT` right through submission; it is certification, not
    filing, that posts them."

    Design: Difficulty/cross_entity_state_dependency/error_correction_filing_is_gated_by_the_price_schedule_item_status_across_draft_posted_effective
    """
    scene = _long_correction_window_scene()
    item = scene["items"][0]

    certify_schedule(scene["schedule"]["id"], scene["certifier_headers"])
    posted = read_item(item["id"])
    assert posted["status"] == "POSTED"
    assert posted["certified_case_price_cents"] == 120_000

    response = api_client.create_error_correction(
        create_error_correction_payload(item["id"], 114_000, 10_500),
        scene["agent_headers"],
    )

    created = validate_success(response, 201)
    assert_error_correction(created)
    assert created["status"] == "SUBMITTED"
    assert created["prior_case_price_cents"] == 120_000
    assert created["prior_unit_price_cents"] == 11_000
    assert created["variance_pct"] == 0.05


def test_correction_is_still_admitted_after_the_posting_run_makes_the_item_effective():
    """Both admissible statuses accept a filing, and each filing snapshots the live price.

    PRD §3.6: "Filing captures the item's current prices into the correction's
    `prior_case_price_cents` and `prior_unit_price_cents` and creates the correction in
    `SUBMITTED` status with `denial_reason` unset."

    Design: Difficulty/cross_entity_state_dependency/error_correction_filing_is_gated_by_the_price_schedule_item_status_across_draft_posted_effective
    """
    scene = _long_correction_window_scene()
    item = scene["items"][0]

    certify_schedule(scene["schedule"]["id"], scene["certifier_headers"])
    validate_success(
        api_client.create_error_correction(
            create_error_correction_payload(item["id"], 114_000, 10_500),
            scene["agent_headers"],
        ),
        201,
    )

    set_clock("2026-10-01T00:00:00Z")
    run_posting(scene["program"]["id"])
    assert read_item(item["id"])["status"] == "EFFECTIVE"

    response = api_client.create_error_correction(
        create_error_correction_payload(item["id"], 116_000, 10_700),
        scene["agent_headers"],
    )
    created = validate_success(response, 201)
    assert created["status"] == "SUBMITTED"
    assert created["prior_case_price_cents"] == 120_000

    listing = api_client.list_error_corrections(
        regulator_headers(), params={"item_id": item["id"]}
    )
    _data, meta = validate_paginated(listing)
    assert meta["total_count"] == 2

    stored = read_item(item["id"])
    assert stored["case_price_cents"] == 120_000
    assert stored["correction_count"] == 0
