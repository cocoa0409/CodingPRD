"""Booth booking: half-open site overlap, food-permit confirmation gate, and the
state-vs-safety validation priority pair."""
from test_helpers import (
    ApiErrorId,
    get_booth,
    make_booth,
    make_juried_vendor,
    make_season,
    set_clock,
    setup_food_booth_confirmed,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, OPERATOR, VENDOR_CO
from test_helpers.test_users import make_vendor_headers


def test_booth_site_adjacent_residency_accepted(api):
    """PRD §3.3: "the new residency must not intersect any existing one on the same
    `booth_site`; because intervals are half-open, a residency may begin on the
    exact day another ends, but any true overlap is rejected with
    `ERR_BOOTH_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/booth_site_unbuffered_adjacency
    """
    season = make_season(name="Booth Revel", volunteer_min_hours=0)
    _, app1 = make_juried_vendor(season["id"], business_name="Cloak & Dagger")
    _, app2 = make_juried_vendor(season["id"], business_name="Henna Heralds")
    make_booth(app1["id"], "B-07", "2026-06-06T00:00:00Z", "2026-06-20T00:00:00Z")

    # [06-20, 06-27) begins exactly at the existing residency's end: no overlap.
    booth2 = validate_success(
        api.create_booth_assignment(
            {
                "application_id": app2["id"], "booth_site": "B-07",
                "residency_start_date": "2026-06-20T00:00:00Z",
                "residency_end_date": "2026-06-27T00:00:00Z",
            },
            VENDOR_CO,
        ),
        201,
    )
    assert booth2["status"] == "RESERVED"


def test_booth_site_true_overlap_rejected(api):
    """PRD §3.3: "the new residency must not intersect any existing one on the same
    `booth_site`; because intervals are half-open, a residency may begin on the
    exact day another ends, but any true overlap is rejected with
    `ERR_BOOTH_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/booth_site_unbuffered_adjacency
    """
    season = make_season(name="Booth Revel", volunteer_min_hours=0)
    _, app1 = make_juried_vendor(season["id"], business_name="Cloak & Dagger")
    _, app3 = make_juried_vendor(season["id"], business_name="Wand Wrights")
    make_booth(app1["id"], "B-07", "2026-06-06T00:00:00Z", "2026-06-20T00:00:00Z")

    # [06-19, 06-28) overlaps the existing [06-06, 06-20) by a full day.
    res = api.create_booth_assignment(
        {
            "application_id": app3["id"], "booth_site": "B-07",
            "residency_start_date": "2026-06-19T00:00:00Z",
            "residency_end_date": "2026-06-28T00:00:00Z",
        },
        VENDOR_CO,
    )
    validate_error(res, ApiErrorId.ERR_BOOTH_OVERLAP, expected_status=409)


def test_booth_confirm_without_food_permit_rejected(api):
    """PRD §3.3: "For vendors whose `category` is `FOOD` or `BEVERAGE`, confirmation
    is gated on health compliance: a food permit of the same application must exist
    in `ISSUED` status with an `expiry_date` on or after the current clock instant,
    else the confirmation is rejected with `ERR_FOOD_PERMIT_NOT_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/booth_confirm_gated_by_food_permit
    """
    season = make_season(name="Health Revel", volunteer_min_hours=0)
    vendor, application = make_juried_vendor(
        season["id"], business_name="Ye Olde Pizza", category="FOOD",
        booth_size_sqft=80, requested_location_tier="STANDARD",
    )
    booth = make_booth(application["id"], "F-09", "2026-06-06T00:00:00Z",
                       "2026-06-21T00:00:00Z")

    res = api.confirm_booth(booth["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, ApiErrorId.ERR_FOOD_PERMIT_NOT_ISSUED, expected_status=409)
    assert get_booth(booth["id"])["status"] == "RESERVED"


def test_booth_confirm_succeeds_after_permit_issued(api):
    """PRD §3.3: "Confirmation belongs to the vendor who owns the linked application
    (else `ERR_NOT_RESOURCE_OWNER`) and moves the booth from `RESERVED` or
    `SUSPENDED` to `CONFIRMED` — from any other state it fails with
    `ERR_BOOTH_NOT_CONFIRMABLE`."
    PRD §3.4: "A `PASSED` outcome moves the permit to `ISSUED`: a server-minted
    `permit_number` is assigned, the `expiry_date` is set to the season's
    `closing_date` plus a fixed system grace period of additional days, and the
    season's readiness posture is re-derived."

    Design: Difficulty/cross_entity_state_dependency/booth_confirm_gated_by_food_permit
    """
    season = make_season(name="Health Revel", volunteer_min_hours=0)
    vendor, application = make_juried_vendor(
        season["id"], business_name="Ye Olde Pizza", category="FOOD",
        booth_size_sqft=80, requested_location_tier="STANDARD",
    )
    booth = make_booth(application["id"], "F-09", "2026-06-06T00:00:00Z",
                       "2026-06-21T00:00:00Z")

    permit = validate_success(
        api.create_food_permit(
            {"application_id": application["id"]}, make_vendor_headers(vendor["id"])
        ),
        201,
    )
    issued = validate_success(
        api.inspect_permit(permit["id"], {"outcome": "PASSED"}, VENDOR_CO), 200
    )
    assert issued["status"] == "ISSUED"

    confirmed = validate_success(
        api.confirm_booth(booth["id"], make_vendor_headers(vendor["id"])), 200
    )
    assert confirmed["status"] == "CONFIRMED"


def test_booth_confirm_state_error_beats_permit_safety(api):
    """PRD §2.9: "When several checks could reject the same request, the server
    evaluates them in a fixed nine-layer order, and the first failing layer
    determines the error returned" — the state gates sit at layer 5 ("The target
    resources must be in the states the operation requires.") while the food-safety
    gate sits at layer 6: "Confirming a booth for a `FOOD` or `BEVERAGE` vendor
    requires an `ISSUED`, unexpired food permit on the same application, else
    `ERR_FOOD_PERMIT_NOT_ISSUED` (HTTP 409)."
    PRD §3.3: "moves the booth from `RESERVED` or `SUSPENDED` to `CONFIRMED` — from
    any other state it fails with `ERR_BOOTH_NOT_CONFIRMABLE`."

    Design: Difficulty/priority_pair_validation_conflict/booth_confirm_state_beats_permit_safety
    """
    season = make_season(name="Priority Revel A", volunteer_min_hours=0)
    vendor, application = make_juried_vendor(
        season["id"], business_name="Mead Maven", category="BEVERAGE",
        booth_size_sqft=64, requested_location_tier="MEADOW",
    )
    booth = make_booth(application["id"], "M-03", "2026-06-06T00:00:00Z",
                       "2026-06-21T00:00:00Z")
    validate_success(api.begin_build(season["id"], OPERATOR), 200)
    validate_success(api.release_booth(booth["id"], VENDOR_CO), 200)

    # RELEASED booth AND no permit: the state error must win.
    res = api.confirm_booth(booth["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, ApiErrorId.ERR_BOOTH_NOT_CONFIRMABLE, expected_status=409)


def test_booth_confirm_reserved_without_permit_yields_safety_error(api):
    """PRD §2.9: "6. **Food-safety gate.** Confirming a booth for a `FOOD` or
    `BEVERAGE` vendor requires an `ISSUED`, unexpired food permit on the same
    application, else `ERR_FOOD_PERMIT_NOT_ISSUED` (HTTP 409)." — the safety gate
    fires in its own right once the state gate passes (booth `RESERVED`).

    Design: Difficulty/priority_pair_validation_conflict/booth_confirm_state_beats_permit_safety
    """
    season = make_season(name="Priority Revel A", volunteer_min_hours=0)
    vendor, application = make_juried_vendor(
        season["id"], business_name="Mead Maven", category="BEVERAGE",
        booth_size_sqft=64, requested_location_tier="MEADOW",
    )
    booth = make_booth(application["id"], "M-03", "2026-06-06T00:00:00Z",
                       "2026-06-21T00:00:00Z")

    res = api.confirm_booth(booth["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, ApiErrorId.ERR_FOOD_PERMIT_NOT_ISSUED, expected_status=409)
