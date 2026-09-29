"""Bed offers: the half-open hold interval, its exclusivity per bed unit, the
conserved held-bed-unit count, and the lazy expiry sweep."""
from test_helpers import (
    CASE_MANAGER,
    ApiErrorId,
    assert_bed_offer,
    document_choice_payload,
    make_liaison_headers,
    read_provider,
    read_referral,
    set_logical_clock,
    setup_broadcast_referral,
    setup_choice_pending_referral,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}


def _broadcast_env(mrn, name="Rae Toussaint", dob="1942-09-19"):
    return setup_broadcast_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": mrn, "full_name": name, "date_of_birth": dob,
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )


def _offer_body(version, **overrides):
    body = {
        "expected_referral_version": version,
        "bed_unit_code": "UNIT-A",
        "bed_available_from": "2026-08-05T00:00:00Z",
        "hold_expires_at": "2026-08-12T00:00:00Z",
        "daily_rate_cents": 30000,
    }
    body.update(overrides)
    return body


def test_a_hold_starting_exactly_where_another_ends_is_accepted(api):
    """PRD §3.4: "Bed holds are exclusive per bed unit. The new offer's half-open interval
    must not intersect the interval of any other bed offer on the same combination of
    `provider_id` and `bed_unit_code` whose `status` is `OFFERED` or
    `ACCEPTED_BY_PATIENT`; an intersection is `ERR_BED_HOLD_OVERLAP` (HTTP 409). Because
    the intervals are half-open, touching endpoints do not intersect: a new hold whose
    `bed_available_from` equals an existing hold's `hold_expires_at` is accepted, and the
    two sit back to back."

    Design: Difficulty/resource_temporal_overlap/bed_hold_half_open_adjacency_accepted_overlap_rejected
    """
    env = _broadcast_env("MRN-8001")
    cedar = env["provider_a"]["id"]
    liaison = make_liaison_headers(cedar)

    first = validate_success(
        api.create_offer(env["referral"]["id"], _offer_body(env["referral_version"]), liaison),
        201,
    )
    version_after_first = read_referral(env["referral"]["id"], liaison)["version"]

    adjacent = validate_success(
        api.create_offer(
            env["referral"]["id"],
            _offer_body(
                version_after_first,
                bed_available_from="2026-08-12T00:00:00Z",
                hold_expires_at="2026-08-18T00:00:00Z",
            ),
            liaison,
        ),
        201,
    )

    assert_bed_offer(adjacent)
    assert adjacent["status"] == "OFFERED"
    assert adjacent["bed_available_from"].startswith("2026-08-12T00:00:00")
    assert first["hold_expires_at"].startswith("2026-08-12T00:00:00")
    assert read_provider(cedar)["held_bed_units"] == 2, (
        "two back-to-back holds both stay live"
    )


def test_a_hold_overlapping_a_live_hold_on_the_same_bed_unit_is_rejected(api):
    """PRD §3.4: "Bed holds are exclusive per bed unit. The new offer's half-open interval
    must not intersect the interval of any other bed offer on the same combination of
    `provider_id` and `bed_unit_code` whose `status` is `OFFERED` or
    `ACCEPTED_BY_PATIENT`; an intersection is `ERR_BED_HOLD_OVERLAP` (HTTP 409)."
    PRD §3.4: "A created offer starts with `status` of `OFFERED`, copies the referral's
    current `round_index` into its own `round_index`, increments the provider's
    `held_bed_units` and `offers_submitted_count` by one each, computes its cost projection
    as described in §3.5, and advances the referral's `version` by one."

    Design: Difficulty/resource_temporal_overlap/bed_hold_half_open_adjacency_accepted_overlap_rejected
    """
    env = _broadcast_env("MRN-8002")
    cedar = env["provider_a"]["id"]
    liaison = make_liaison_headers(cedar)

    validate_success(
        api.create_offer(env["referral"]["id"], _offer_body(env["referral_version"]), liaison),
        201,
    )
    version_after_first = read_referral(env["referral"]["id"], liaison)["version"]
    validate_success(
        api.create_offer(
            env["referral"]["id"],
            _offer_body(
                version_after_first,
                bed_available_from="2026-08-12T00:00:00Z",
                hold_expires_at="2026-08-18T00:00:00Z",
            ),
            liaison,
        ),
        201,
    )
    version_after_second = read_referral(env["referral"]["id"], liaison)["version"]

    response = api.create_offer(
        env["referral"]["id"],
        _offer_body(
            version_after_second,
            bed_available_from="2026-08-11T23:59:00Z",
            hold_expires_at="2026-08-15T00:00:00Z",
        ),
        liaison,
    )

    validate_error(response, ApiErrorId.ERR_BED_HOLD_OVERLAP, 409)
    provider = read_provider(cedar)
    assert provider["held_bed_units"] == 2, "the rejected offer never took a hold"
    assert provider["offers_submitted_count"] == 2
    rows, meta = validate_paginated(
        api.list_offers(CASE_MANAGER, params={"referral_id": env["referral"]["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_withdrawing_an_offer_restores_the_held_bed_unit_count(api):
    """PRD §2.10: "`PostAcuteProvider.held_bed_units` is the count of that provider's bed
    offers in `OFFERED` or `ACCEPTED_BY_PATIENT` status; making an offer holds a unit, and
    every path out of `OFFERED` other than acceptance releases it."
    PRD §3.4: "A liaison may withdraw its own outstanding offer, which moves it to
    `WITHDRAWN`, decrements that provider's `held_bed_units`, and makes the hold interval
    immediately reusable; withdrawing an offer that belongs to another provider is
    `ERR_NOT_OWNER`, and withdrawing one that is no longer `OFFERED` is
    `ERR_INVALID_OFFER_STATE`."
    PRD §3.1: "`offers_submitted_count` counts every bed offer it has ever created
    regardless of outcome"

    Design: Difficulty/compensating_invariant/held_bed_units_conserved_across_offer_and_withdraw
    """
    env = _broadcast_env("MRN-9001", name="Uma Castellano", dob="1940-06-06")
    cedar = env["provider_a"]["id"]
    liaison = make_liaison_headers(cedar)
    assert read_provider(cedar)["held_bed_units"] == 0

    offer = validate_success(
        api.create_offer(env["referral"]["id"], _offer_body(env["referral_version"]), liaison),
        201,
    )
    assert read_provider(cedar)["held_bed_units"] == 1, "creating an offer holds a unit"

    withdrawn = validate_success(api.withdraw_offer(offer["id"], liaison))

    assert withdrawn["status"] == "WITHDRAWN"
    provider = read_provider(cedar)
    assert provider["held_bed_units"] == 0, (
        f"the withdrawal returns the count to zero with no drift, got {provider['held_bed_units']}"
    )
    assert provider["offers_submitted_count"] == 1, "submissions are never un-counted"
    assert provider["acceptance_rate_pct"] == 0.0


def test_the_released_interval_is_immediately_reusable_by_an_identical_offer(api):
    """PRD §3.4: "A liaison may withdraw its own outstanding offer, which moves it to
    `WITHDRAWN`, decrements that provider's `held_bed_units`, and makes the hold interval
    immediately reusable; withdrawing an offer that belongs to another provider is
    `ERR_NOT_OWNER`, and withdrawing one that is no longer `OFFERED` is
    `ERR_INVALID_OFFER_STATE`."
    PRD §2.10: "`PostAcuteProvider.held_bed_units` is the count of that provider's bed
    offers in `OFFERED` or `ACCEPTED_BY_PATIENT` status; making an offer holds a unit, and
    every path out of `OFFERED` other than acceptance releases it."

    Design: Difficulty/compensating_invariant/held_bed_units_conserved_across_offer_and_withdraw
    """
    env = _broadcast_env("MRN-9002", name="Uma Castellano", dob="1940-06-06")
    cedar = env["provider_a"]["id"]
    liaison = make_liaison_headers(cedar)

    first = validate_success(
        api.create_offer(env["referral"]["id"], _offer_body(env["referral_version"]), liaison),
        201,
    )
    validate_success(api.withdraw_offer(first["id"], liaison))
    version_after_withdraw = read_referral(env["referral"]["id"], liaison)["version"]

    reoffer = validate_success(
        api.create_offer(
            env["referral"]["id"], _offer_body(version_after_withdraw), liaison
        ),
        201,
    )

    assert reoffer["status"] == "OFFERED"
    assert reoffer["bed_available_from"] == first["bed_available_from"]
    assert reoffer["hold_expires_at"] == first["hold_expires_at"]
    provider = read_provider(cedar)
    assert provider["held_bed_units"] == 1
    assert provider["offers_submitted_count"] == 2
    rows, meta = validate_paginated(api.list_offers(CASE_MANAGER, params={"provider_id": cedar}))
    assert meta["total_count"] == 2
    live = [row for row in rows if row["status"] == "OFFERED"]
    assert len(live) == 1, (
        f"exactly one offer stays live, matching held_bed_units, got {len(live)}"
    )


def test_a_zero_length_bed_hold_is_refused_as_an_invalid_interval(api):
    """PRD §3.4: "The bed hold the offer creates is **half-open**: it includes
    `bed_available_from` and excludes `hold_expires_at`, and `hold_expires_at` must be
    strictly after `bed_available_from` or the request is `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/zero_length_bed_hold_returns_invalid_interval
    """
    env = _broadcast_env("MRN-D003", name="Rio Sandoval", dob="1949-07-07")
    cedar = env["provider_a"]["id"]

    response = api.create_offer(
        env["referral"]["id"],
        _offer_body(
            env["referral_version"],
            bed_available_from="2026-08-05T00:00:00Z",
            hold_expires_at="2026-08-05T00:00:00Z",
        ),
        make_liaison_headers(cedar),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_INTERVAL, 422)
    provider = read_provider(cedar)
    assert provider["held_bed_units"] == 0
    assert provider["offers_submitted_count"] == 0
    assert read_referral(env["referral"]["id"])["status"] == "BROADCAST", (
        "the round was never opened by the refused offer"
    )


def test_offer_referential_guards_reject_uninvited_providers_and_unknown_bed_units(api):
    """PRD §3.4: "The offering provider's `provider_type` must equal the referral's
    `requested_level_of_care`, and a mismatch is `ERR_PROVIDER_TYPE_MISMATCH`. The offering
    provider must be a member of the referral's current `broadcast_provider_ids` — a
    liaison may only answer a round it was invited to, and answering an uninvited round is
    `ERR_PROVIDER_NOT_IN_BROADCAST`. And `bed_unit_code` must be one of the strings in that
    provider's `bed_unit_codes` list, or the request is `ERR_UNKNOWN_BED_UNIT`."

    Design: Corner/errors/offer_rejections_for_broadcast_membership_and_bed_unit
    """
    from test_helpers import (
        get_success_data,
        referral_payload,
        seed_provider,
        setup_screened_episode,
    )

    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-E101", "full_name": "Bo Zheng", "date_of_birth": "1948-02-02",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A"])
    birch = seed_provider(name="Birch SNF", quality_star_rating=5,
                          distance_miles_from_hospital=22, bed_unit_codes=["UNIT-A"])
    alder = seed_provider(name="Alder SNF", quality_star_rating=3,
                          distance_miles_from_hospital=12, bed_unit_codes=["UNIT-A"])
    willow = seed_provider(name="Willow SNF", quality_star_rating=2,
                           distance_miles_from_hospital=30, bed_unit_codes=["UNIT-A"])
    home_health = seed_provider(name="Riverside Home Health", provider_type="HOME_HEALTH",
                                quality_star_rating=4, distance_miles_from_hospital=8,
                                bed_unit_codes=[])
    referral = get_success_data(
        api.create_referral(env["episode"]["id"], referral_payload(), CASE_MANAGER)
    )
    broadcast = get_success_data(
        api.broadcast_referral(
            referral["id"],
            {"provider_ids": [cedar["id"], birch["id"], alder["id"], home_health["id"]]},
            CASE_MANAGER,
        )
    )
    version = broadcast["version"]

    uninvited = api.create_offer(
        referral["id"], _offer_body(version), make_liaison_headers(willow["id"])
    )
    validate_error(uninvited, ApiErrorId.ERR_PROVIDER_NOT_IN_BROADCAST, 422)

    unknown_unit = api.create_offer(
        referral["id"],
        _offer_body(version, bed_unit_code="UNIT-Z"),
        make_liaison_headers(cedar["id"]),
    )
    validate_error(unknown_unit, ApiErrorId.ERR_UNKNOWN_BED_UNIT, 422)

    wrong_type = api.create_offer(
        referral["id"], _offer_body(version), make_liaison_headers(home_health["id"])
    )
    validate_error_is_one_of(
        wrong_type,
        [ApiErrorId.ERR_PROVIDER_TYPE_MISMATCH.value, ApiErrorId.ERR_UNKNOWN_BED_UNIT.value],
    )
    assert wrong_type.status_code == 422

    _, meta = validate_paginated(
        api.list_offers(CASE_MANAGER, params={"referral_id": referral["id"]})
    )
    assert meta["total_count"] == 0, "none of the three refusals created an offer"
    after = read_referral(referral["id"])
    assert after["status"] == "BROADCAST"
    assert after["version"] == version, "a refused offer never advances the referral version"


def test_hold_expiry_at_the_exact_instant_releases_the_bed_and_blocks_the_choice(api):
    """PRD §3.4: "Separately, an offer whose `hold_expires_at` the logical clock has
    reached moves lazily `OFFERED → EXPIRED`, again releasing `held_bed_units` and the
    interval; that sweep runs before the state check on any request touching the offer or
    its referral, so an attempt to withdraw or to choose a hold that has run out reads the
    offer as `EXPIRED` and is refused with `ERR_OFFER_EXPIRED` (HTTP 409)."

    Design: Corner/state_machines/bed_offer_lazy_expiry_at_hold_expires_at_releases_hold
    """
    env = setup_choice_pending_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-C206", "full_name": "Hal Ibarra", "date_of_birth": "1946-08-08",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"hold_expires_at": "2026-08-12T00:00:00Z", "daily_rate_cents": 30000},
    )
    set_logical_clock("2026-08-12T00:00:00Z")

    read_back = validate_success(api.get_offer(env["offer"]["id"], CASE_MANAGER))
    assert read_back["status"] == "EXPIRED", (
        "the comparison is >=, so the offer expires at exactly hold_expires_at"
    )
    assert read_provider(env["provider_a"]["id"])["held_bed_units"] == 0

    response = api.document_choice(
        env["referral"]["id"],
        document_choice_payload(env["offer"]["id"], choice_basis="ONLY_AVAILABLE"),
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED, 409)
    referral = read_referral(env["referral"]["id"])
    assert referral["status"] == "CHOICE_PENDING"
    assert referral["chosen_bed_offer_id"] is None
