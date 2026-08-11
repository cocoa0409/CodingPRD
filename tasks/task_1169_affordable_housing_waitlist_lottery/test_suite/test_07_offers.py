"""Offer generation, response, refusal cycles, expiry sweeps, and the
conserved quantities across the offer lifecycle."""
from test_helpers import (
    ApiErrorId, assert_entry_census, assert_property_bucket_conservation,
    fixtures, get_success_data, make_applicant_headers, validate_error,
    validate_paginated, validate_success,
)

DEVELOPER = fixtures.DEVELOPER
LOTTERY_ADMIN = fixtures.LOTTERY_ADMIN


# --------------------------------------------------------------------------
# Offer/refusal cycle (difficulty: non-linear state machine)
# --------------------------------------------------------------------------
def test_offer_refusal_cycle_returns_entry_to_ranked(api):
    """PRD §3.6: "A declined offer also stamps `responded_at` and lands in
    terminal `DECLINED`; the entry's `refusal_count` increments by 1, and if
    the incremented count has reached the maximum of 2 allowed refusals the
    entry is removed outright ... otherwise the entry falls back to `RANKED`
    to await another offer".

    Design: Difficulty/non_linear_state_machine/waitlist_entry_offer_refusal_cycle
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-CYCLE")
    offer = world["offers"][0]
    entry_id = offer["entry_id"]
    before = get_success_data(api.get_waitlist_entry(entry_id, LOTTERY_ADMIN))
    assert before["status"] == "OFFERED", "RANKED -> OFFERED at generation"

    declined = fixtures.decline_offer(api, offer)
    assert declined["status"] == "DECLINED"
    after = get_success_data(api.get_waitlist_entry(entry_id, LOTTERY_ADMIN))
    assert after["status"] == "RANKED"
    assert after["refusal_count"] == 1, "1 < 2, so the entry survives"


def test_offer_refusal_cycle_releases_unit(api):
    """PRD §3.6: "either way the unit returns from `RESERVED` to
    `AVAILABLE`." PRD §3.6: "the entry must have no prior `DECLINED` or
    `EXPIRED` offer for this very unit — a household that already refused
    this unit is never offered it again."

    Design: Difficulty/non_linear_state_machine/waitlist_entry_offer_refusal_cycle
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-CYCLE")
    offer = world["offers"][0]
    unit_id = offer["unit_id"]
    assert world["generation"]["generated_count"] == 1
    reserved = get_success_data(api.get_unit(unit_id, DEVELOPER))
    assert reserved["status"] == "RESERVED"

    fixtures.decline_offer(api, offer)
    released = get_success_data(api.get_unit(unit_id, DEVELOPER))
    assert released["status"] == "AVAILABLE"


# --------------------------------------------------------------------------
# Decline -> refusal -> removal cascade (difficulty: transitive cascade)
# --------------------------------------------------------------------------
def _two_unit_leasing(api, seed="SEED-CASCADE"):
    return fixtures.setup_leasing_with_pending_offer(api, seed=seed,
                                                     num_units=2)


def test_offer_decline_max_refusal_cascade_removes_entry(api):
    """PRD §3.6: "if the incremented count has reached the maximum of 2
    allowed refusals the entry is removed outright — `REMOVED` with
    `removal_reason` `MAX_REFUSALS`, `removed_at` stamped, and
    `waitlist_active_count` recomputed".

    Design: Difficulty/transitive_cascade/offer_decline_max_refusal_cascade
    """
    world = _two_unit_leasing(api)
    offer1 = world["offers"][0]
    entry_id = offer1["entry_id"]
    fixtures.decline_offer(api, offer1)

    generation2 = fixtures.generate_offers(api, world["campaign"]["id"])
    assert generation2["generated_count"] == 1
    offer2 = fixtures.get_pending_offer(api, world["campaign"]["id"])
    fixtures.decline_offer(api, offer2)

    entry = get_success_data(api.get_waitlist_entry(entry_id, LOTTERY_ADMIN))
    assert entry["status"] == "REMOVED"
    assert entry["removal_reason"] == "MAX_REFUSALS"
    assert entry["refusal_count"] == 2


def test_offer_decline_max_refusal_cascade_updates_counters_and_units(api):
    """PRD §2.8: "`waitlist_active_count` (its waitlist entries in `RANKED`
    or `OFFERED` status)". PRD §3.6: "the entry must have no prior `DECLINED`
    or `EXPIRED` offer for this very unit — a household that already refused
    this unit is never offered it again."

    Design: Difficulty/transitive_cascade/offer_decline_max_refusal_cascade
    """
    world = _two_unit_leasing(api)
    unit1, unit2 = world["units"]
    offer1 = world["offers"][0]
    assert offer1["unit_id"] == unit1["id"], "oldest unit is offered first"
    entry_id = offer1["entry_id"]
    fixtures.decline_offer(api, offer1)

    fixtures.generate_offers(api, world["campaign"]["id"])
    offer2 = fixtures.get_pending_offer(api, world["campaign"]["id"])
    # Unit 101 is excluded for this entry by the prior decline; the second
    # offer lands on unit 102.
    assert offer2["unit_id"] == unit2["id"]
    fixtures.decline_offer(api, offer2)

    campaign = fixtures.get_campaign(api, world["campaign"]["id"])
    assert campaign["waitlist_active_count"] == 0
    unit2_after = get_success_data(api.get_unit(unit2["id"], DEVELOPER))
    assert unit2_after["status"] == "AVAILABLE"


# --------------------------------------------------------------------------
# Refusal boundary at MAX_REFUSALS (difficulty: boundary precision)
# --------------------------------------------------------------------------
def test_first_refusal_below_max_keeps_entry_ranked(api):
    """PRD §3.6: "the entry's `refusal_count` increments by 1, and if the
    incremented count has reached the maximum of 2 allowed refusals the entry
    is removed outright ... otherwise the entry falls back to `RANKED` to
    await another offer".

    Design: Difficulty/boundary_precision_check/second_refusal_exactly_at_max_removes_entry
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-BOUND")
    offer = world["offers"][0]
    fixtures.decline_offer(api, offer)
    entry = get_success_data(
        api.get_waitlist_entry(offer["entry_id"], LOTTERY_ADMIN))
    assert entry["refusal_count"] == 1
    assert entry["status"] == "RANKED", "1 < 2: below the removal threshold"


def test_second_refusal_exactly_at_max_removes_entry(api):
    """PRD §3.6: "if the incremented count has reached the maximum of 2
    allowed refusals the entry is removed outright — `REMOVED` with
    `removal_reason` `MAX_REFUSALS`, `removed_at` stamped".

    Design: Difficulty/boundary_precision_check/second_refusal_exactly_at_max_removes_entry
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-BOUND",
                                                      num_units=2)
    offer1 = world["offers"][0]
    entry_id = offer1["entry_id"]
    fixtures.decline_offer(api, offer1)
    fixtures.generate_offers(api, world["campaign"]["id"])
    offer2 = fixtures.get_pending_offer(api, world["campaign"]["id"])
    fixtures.decline_offer(api, offer2)
    entry = get_success_data(api.get_waitlist_entry(entry_id, LOTTERY_ADMIN))
    # The boundary value 2 itself (>= 2) triggers removal, not 3.
    assert entry["refusal_count"] == 2
    assert entry["status"] == "REMOVED"
    assert entry["removal_reason"] == "MAX_REFUSALS"


# --------------------------------------------------------------------------
# Unit bucket conservation (difficulty: compensating invariant)
# --------------------------------------------------------------------------
def _property_buckets(api, property_id):
    prop = get_success_data(api.get_property(property_id, DEVELOPER))
    assert_property_bucket_conservation(prop)
    return (prop["units_available_count"], prop["units_reserved_count"],
            prop["units_leased_count"], prop["units_out_of_service_count"])


def test_unit_status_bucket_conservation_offer_cycle(api):
    """PRD §3.6: "An accepted offer stamps `responded_at` and lands in
    terminal `ACCEPTED`; its entry moves from `OFFERED` to `LEASED`, which
    bumps the campaign's `entries_leased_count` and recomputes
    `waitlist_active_count`; and its unit moves from `RESERVED` to `LEASED`
    with property counters recomputed."

    Design: Difficulty/compensating_invariant/unit_status_bucket_conservation
    """
    world = fixtures.setup_leasing_pipeline(api, seed="SEED-UNIT",
                                            num_units=2)
    prop_id = world["property"]["id"]
    assert _property_buckets(api, prop_id) == (2, 0, 0, 0)

    fixtures.generate_offers(api, world["campaign"]["id"])
    assert _property_buckets(api, prop_id) == (1, 1, 0, 0)

    offer1 = fixtures.get_pending_offer(api, world["campaign"]["id"])
    fixtures.decline_offer(api, offer1)
    assert _property_buckets(api, prop_id) == (2, 0, 0, 0), (
        "the compensating release exactly restores the pre-offer buckets"
    )

    fixtures.generate_offers(api, world["campaign"]["id"])
    assert _property_buckets(api, prop_id) == (1, 1, 0, 0)

    offer2 = fixtures.get_pending_offer(api, world["campaign"]["id"])
    fixtures.accept_offer(api, offer2)
    assert _property_buckets(api, prop_id) == (1, 0, 1, 0)


def test_unit_status_buckets_retarget_after_decline(api):
    """PRD §3.6: "the entry must have no prior `DECLINED` or `EXPIRED` offer
    for this very unit — a household that already refused this unit is never
    offered it again." PRD §2.8: "A property exposes `units_total` (the count
    of its unit rows), `units_available_count`, `units_reserved_count`,
    `units_leased_count`, and `units_out_of_service_count`, each tallying
    units in the corresponding status".

    Design: Difficulty/compensating_invariant/unit_status_bucket_conservation
    """
    world = fixtures.setup_leasing_pipeline(api, seed="SEED-UNIT",
                                            num_units=2)
    unit1, unit2 = world["units"]
    fixtures.generate_offers(api, world["campaign"]["id"])
    offer1 = fixtures.get_pending_offer(api, world["campaign"]["id"])
    assert offer1["unit_id"] == unit1["id"]
    fixtures.decline_offer(api, offer1)

    fixtures.generate_offers(api, world["campaign"]["id"])
    offer2 = fixtures.get_pending_offer(api, world["campaign"]["id"])
    assert offer2["unit_id"] == unit2["id"]
    fixtures.accept_offer(api, offer2)

    assert get_success_data(api.get_unit(unit1["id"], DEVELOPER))["status"] \
        == "AVAILABLE"
    assert get_success_data(api.get_unit(unit2["id"], DEVELOPER))["status"] \
        == "LEASED"
    prop = get_success_data(api.get_property(world["property"]["id"],
                                             DEVELOPER))
    assert prop["units_total"] == 2
    assert_property_bucket_conservation(prop)


# --------------------------------------------------------------------------
# Waitlist entry census conservation (difficulty: compensating invariant)
# --------------------------------------------------------------------------
def _census(api, campaign_id, expected_total):
    entries = fixtures.list_entries(api, campaign_id=campaign_id, limit=100)
    return assert_entry_census(entries, expected_total)


def test_waitlist_entry_census_conserved_through_offer_cycle(api):
    """PRD §3.5: "generates one waitlist entry per snapshotted application,
    each born in `RANKED` status and stamped with its `lottery_run_id`,
    `campaign_id`, and `application_id`; `entries_generated` records how many
    were created."

    Design: Difficulty/compensating_invariant/waitlist_entry_census_conservation
    """
    world = fixtures.setup_leasing_pipeline(
        api, seed="SEED-CENSUS", num_units=1,
        applications=[{"full_name": "Quinn Q", "email": "q@x.com"},
                      {"full_name": "Rae R", "email": "r@x.com"}])
    campaign_id = world["campaign"]["id"]
    assert world["run"]["entries_generated"] == 2

    generation = fixtures.generate_offers(api, campaign_id)
    assert generation["generated_count"] == 1, "a single unit yields one offer"
    census = _census(api, campaign_id, 2)
    assert census.get("OFFERED") == 1 and census.get("RANKED") == 1

    offer = fixtures.get_pending_offer(api, campaign_id)
    fixtures.decline_offer(api, offer)
    census = _census(api, campaign_id, 2)
    assert census.get("RANKED") == 2, (
        "the refusal cycle conserves the census: 2 RANKED, none destroyed"
    )


def test_waitlist_entry_census_conserved_through_admin_removal(api):
    """PRD §3.6: "A `HousingDeveloper` may administratively remove an entry
    currently in `RANKED`, supplying a `removal_reason` of `ADMIN_REMOVED`".
    PRD §2.8: "`waitlist_active_count` (its waitlist entries in `RANKED` or
    `OFFERED` status)".

    Design: Difficulty/compensating_invariant/waitlist_entry_census_conservation
    """
    world = fixtures.setup_leasing_pipeline(
        api, seed="SEED-CENSUS", num_units=1,
        applications=[{"full_name": "Quinn Q", "email": "q@x.com"},
                      {"full_name": "Rae R", "email": "r@x.com"}])
    campaign_id = world["campaign"]["id"]
    fixtures.generate_offers(api, campaign_id)
    offer = fixtures.get_pending_offer(api, campaign_id)
    entry_id = offer["entry_id"]
    fixtures.decline_offer(api, offer)

    removed = validate_success(api.remove_waitlist_entry(
        entry_id, {"removal_reason": "ADMIN_REMOVED"}, DEVELOPER))
    assert removed["status"] == "REMOVED"
    assert removed["removal_reason"] == "ADMIN_REMOVED"

    census = _census(api, campaign_id, 2)
    assert census.get("RANKED") == 1 and census.get("REMOVED") == 1
    campaign = fixtures.get_campaign(api, campaign_id)
    assert campaign["waitlist_active_count"] == 1, (
        "RANKED + OFFERED only; REMOVED is excluded from the active count"
    )


# --------------------------------------------------------------------------
# Offer selector: filters, boost, and fallback
# --------------------------------------------------------------------------
def test_offer_selector_filters_boosts_and_fallback(api):
    """PRD §3.6: "if the row itself is missing, the unit is skipped entirely
    and receives no offer at all. ... if that row is missing, the entry is
    simply ineligible for that unit. ... Among survivors, an accessibility
    boost applies when the unit's `accessibility_feature` is anything other
    than `NONE` and the application's `verified_preference_categories`
    include `ACCESSIBILITY`; the chosen entry is the boosted one if any
    exist, then the lowest `effective_rank`, then the earliest `created_at`
    among ties."

    Design: Corner/calculations/offer_selector_filters_boosts_and_fallback
    """
    world = fixtures.setup_leasing_pipeline(
        api, seed="SEED-SEL",
        ami_limits=[(2, "AMI_50", 4_000_000), (2, "AMI_30", 2_400_000)],
        unit_specs=[{"unit_number": "A1", "ami_tier": "AMI_30"},
                    {"unit_number": "B2", "bedroom_count": "THREE_BR"},
                    {"unit_number": "C3", "accessibility_feature": "MOBILITY"}],
        applications=[
            {"full_name": "Kai K", "email": "k4@x.com",
             "claims": [("LOCAL_RESIDENT", "lease", "VERIFY")]},
            {"full_name": "Liv L", "email": "l4@x.com",
             "claims": [("ACCESSIBILITY", "mobility-cert", "VERIFY")]},
        ])
    unit_a1, unit_b2, unit_c3 = world["units"]
    generation = fixtures.generate_offers(api, world["campaign"]["id"])
    assert generation["generated_count"] == 1
    assert generation["units_considered"] == 3

    offer = fixtures.get_pending_offer(api, world["campaign"]["id"])
    assert offer["unit_id"] == unit_c3["id"], (
        "A1 is income-ineligible for both entries (3000000 > 2400000); "
        "B2 has no occupancy-standard row and is skipped"
    )
    winning_entry = get_success_data(
        api.get_waitlist_entry(offer["entry_id"], LOTTERY_ADMIN))
    app_liv = world["applications"][1]
    assert winning_entry["application_id"] == app_liv["id"], (
        "the ACCESSIBILITY boost outranks the other entry's better "
        "effective_rank for the MOBILITY unit"
    )
    assert get_success_data(api.get_unit(unit_a1["id"], DEVELOPER))["status"] \
        == "AVAILABLE"
    assert get_success_data(api.get_unit(unit_b2["id"], DEVELOPER))["status"] \
        == "AVAILABLE"


def test_offer_selector_empty_pool_generates_zero(api):
    """PRD §3.6: "If no entry survives for a unit, the unit stays `AVAILABLE`
    and the batch moves on; an empty pool is a non-event, not an error."
    PRD §3.6: "on the first generation batch of the campaign — the campaign
    itself flips from `LOTTERY_COMPLETED` to `LEASING`."

    Design: Corner/calculations/offer_selector_empty_pool_generates_zero
    """
    world = fixtures.setup_leasing_pipeline(api, seed="SEED-EMPTY",
                                            certify=False)
    generation = fixtures.generate_offers(api, world["campaign"]["id"])
    assert generation["generated_count"] == 0
    assert generation["units_considered"] == 1
    unit = world["units"][0]
    assert get_success_data(api.get_unit(unit["id"], DEVELOPER))["status"] \
        == "AVAILABLE"
    campaign = fixtures.get_campaign(api, world["campaign"]["id"])
    assert campaign["status"] == "LOTTERY_COMPLETED", (
        "the LEASING flip happens only when an offer is actually created"
    )


def test_offer_response_deadline_is_ten_days(api):
    """PRD §3.6: "The created offer records its `campaign_id`, `entry_id`,
    and `unit_id`, stamps `offered_at` with the current logical instant, and
    sets `response_deadline` exactly 10 days later".

    Design: Corner/calculations/offer_response_deadline_is_ten_days
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-DL")
    offer = world["offers"][0]
    # The logical clock has been pinned at 2026-06-30T00:00:00Z since the
    # campaign close.
    assert offer["offered_at"] == "2026-06-30T00:00:00.000Z"
    assert offer["response_deadline"] == "2026-07-10T00:00:00.000Z"


def test_expire_due_sweep_applies_refusal_cascade(api):
    """PRD §3.6: "A `HousingDeveloper` triggers the expiry sweep, which walks
    every `PENDING` offer whose `response_deadline` is strictly before the
    logical clock — processed in `offered_at` ascending order — and moves
    each to terminal `EXPIRED` with exactly the same refusal cascade as a
    decline: `refusal_count` increments, the two-refusal ceiling applies, and
    the unit is released. The sweep reports how many offers it expired in
    `expired_count`."

    Design: Corner/calculations/expire_due_sweep_applies_refusal_cascade
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-EXP")
    offer = world["offers"][0]
    entry_id = offer["entry_id"]
    unit_id = offer["unit_id"]
    fixtures.set_clock("2026-07-11T00:00:00Z", api)  # past the 2026-07-10 deadline

    swept = validate_success(api.expire_due_offers(DEVELOPER))
    assert swept["expired_count"] == 1
    offer_after = get_success_data(api.get_offer(offer["id"], DEVELOPER))
    assert offer_after["status"] == "EXPIRED"
    entry = get_success_data(api.get_waitlist_entry(entry_id, DEVELOPER))
    assert entry["status"] == "RANKED"
    assert entry["refusal_count"] == 1, "expiry counts as a refusal"
    assert get_success_data(api.get_unit(unit_id, DEVELOPER))["status"] \
        == "AVAILABLE"

    applicant_id = fixtures.offer_owner_applicant_id(api, offer)
    resp = api.respond_to_offer(offer["id"], {"action": "ACCEPT"},
                                make_applicant_headers(applicant_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_respond_after_deadline_returns_offer_expired(api):
    """PRD §3.6: "In both cases the logical clock must not have passed the
    offer's `response_deadline` — a response exactly at the deadline is still
    accepted, while one past it is rejected with `ERR_OFFER_EXPIRED`."

    Design: Corner/validations/respond_after_deadline_returns_offer_expired
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-EXP2")
    offer = world["offers"][0]
    applicant_id = fixtures.offer_owner_applicant_id(api, offer)
    fixtures.set_clock("2026-07-11T00:00:00Z", api)  # deadline is 2026-07-10

    resp = api.respond_to_offer(offer["id"], {"action": "ACCEPT"},
                                make_applicant_headers(applicant_id))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
    offer_after = get_success_data(api.get_offer(offer["id"], DEVELOPER))
    assert offer_after["status"] == "PENDING", (
        "the deadline rejection is not itself the expiry transition"
    )


def test_accept_with_expired_certification_returns_cert_expired(api):
    """PRD §3.4: "A successful certification stamps `determination` as
    `ELIGIBLE`, records `certified_at` and the officer's `X-User-ID` as
    `certified_by`, and sets `valid_until` to exactly 180 days after
    `certified_at`". PRD §3.6: "Acceptance additionally requires that the
    application's income certification be `CERTIFIED` with `valid_until`
    still in the future, else `ERR_CERTIFICATION_EXPIRED`."

    Design: Corner/cross_cutting_layers/accept_with_expired_certification_returns_cert_expired
    """
    prop = fixtures.new_property(api)
    fixtures.new_occupancy_standard(api, prop["id"])
    fixtures.new_ami_limit(api, prop["id"])
    fixtures.new_unit(api, prop["id"], unit_number="101")
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant = fixtures.new_applicant(api, full_name="Hyo H",
                                       email="h11@x.com")
    application = fixtures.submit_application(api, campaign["id"],
                                              applicant["id"])
    fixtures.verify_application(api, application["id"])
    # Certified at 2026-06-10 (the mid-window clock): valid_until is exactly
    # 180 days later.
    cert = fixtures.certify_household_income(api, application["id"],
                                             applicant["id"])
    assert cert["valid_until"] == "2026-12-07T00:00:00.000Z"

    fixtures.close_campaign_at(api, campaign["id"])
    fixtures.run_published_lottery(api, campaign["id"], seed="SEED-CEXP")
    fixtures.set_clock("2026-12-01T00:00:00Z", api)  # certification still valid
    generation = fixtures.generate_offers(api, campaign["id"])
    assert generation["generated_count"] == 1
    offer = fixtures.get_pending_offer(api, campaign["id"])

    fixtures.set_clock("2026-12-08T00:00:00Z", api)  # past valid_until
    resp = api.respond_to_offer(offer["id"], {"action": "ACCEPT"},
                                make_applicant_headers(applicant["id"]))
    # The offer's own deadline (2026-12-11) has not passed; the certification
    # validity gate fires instead.
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_EXPIRED)
    offer_after = get_success_data(api.get_offer(offer["id"], DEVELOPER))
    assert offer_after["status"] == "PENDING"


def test_entry_remove_offered_returns_invalid_state(api):
    """PRD §3.6: "A `HousingDeveloper` may administratively remove an entry
    currently in `RANKED`, supplying a `removal_reason` of `ADMIN_REMOVED`;
    removing an entry in any other status is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/entry_remove_offered_returns_invalid_state
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-RM")
    entry_id = world["offers"][0]["entry_id"]
    resp = api.remove_waitlist_entry(
        entry_id, {"removal_reason": "ADMIN_REMOVED"}, DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_offer_generate_without_published_run_returns_invalid_state(api):
    """PRD §3.6: "The campaign must have a `PUBLISHED` run; without one the
    request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/offer_generate_without_published_run_returns_invalid_state
    """
    prop = fixtures.new_property(api)
    fixtures.new_occupancy_standard(api, prop["id"])
    fixtures.new_ami_limit(api, prop["id"])
    fixtures.new_unit(api, prop["id"], unit_number="101")
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant, application = fixtures.new_verified_application(
        api, campaign["id"], full_name="Bob B", email="b10@x.com")
    fixtures.close_campaign_at(api, campaign["id"])
    run = fixtures.new_lottery_run(api, campaign["id"], seed="SEED-NP")
    fixtures.lottery_action(api, run["id"], "SEAL")
    fixtures.lottery_action(api, run["id"], "EXECUTE")
    # The run is EXECUTED, never PUBLISHED.
    resp = api.generate_offers({"campaign_id": campaign["id"]}, LOTTERY_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    _, meta = validate_paginated(
        api.list_offers(LOTTERY_ADMIN, params={"campaign_id": campaign["id"]}))
    assert meta["total_count"] == 0
