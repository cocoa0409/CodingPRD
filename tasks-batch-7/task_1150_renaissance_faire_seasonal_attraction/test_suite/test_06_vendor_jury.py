"""Vendor jury: applications, decisions, the single appeal, and waitlist promotion."""
from test_helpers import (
    ApiErrorId,
    decide_application,
    make_application,
    make_booth,
    make_juried_vendor,
    make_season,
    make_vendor,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, VENDOR_CO
from test_helpers.test_users import make_vendor_headers


def test_duplicate_application_rejected(api):
    """PRD §3.3: "A vendor may hold only one non-terminal application per season, so
    a second filing while an earlier one is still live fails with
    `ERR_DUPLICATE_APPLICATION`."

    Design: Corner/validations/duplicate_application_rejected
    """
    season = make_season(name="Dup Revel")
    vendor = make_vendor(business_name="Candle Corner", category="ARTISAN")
    make_application(season["id"], vendor["id"], 64, "STANDARD")

    res = api.create_vendor_application(
        {"season_id": season["id"], "booth_size_sqft": 100,
         "requested_location_tier": "PRIME"},
        make_vendor_headers(vendor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_APPLICATION, expected_status=409)


def test_appeal_twice_rejected(api):
    """PRD §3.3: "The appeal requires the application to be `JURIED_OUT` (else
    `ERR_APPLICATION_NOT_APPEALABLE`), requires `appeal_used` to still be false (a
    second attempt fails with `ERR_APPEAL_ALREADY_USED`), and requires the caller to
    own the application (else `ERR_NOT_RESOURCE_OWNER`); it moves the application to
    `APPEALED` and sets `appeal_used` true."

    Design: Corner/validations/appeal_twice_rejected
    """
    season = make_season(name="Appeal Revel")
    vendor = make_vendor(business_name="Bone Carvers", category="ARTISAN")
    application = make_application(season["id"], vendor["id"], 64, "MEADOW")
    decide_application(application["id"], "JURIED_OUT", 5, 5, 5)
    validate_success(
        api.appeal_application(application["id"], make_vendor_headers(vendor["id"])), 200
    )
    decide_application(application["id"], "JURIED_OUT", 5, 5, 5)

    res = api.appeal_application(application["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, ApiErrorId.ERR_APPEAL_ALREADY_USED, expected_status=409)
    current = validate_success(api.get_vendor_application(application["id"], ANY), 200)
    assert current["status"] == "JURIED_OUT"


def test_application_lifecycle_guards(api):
    """PRD §3.3: "Withdrawal is the vendor's own exit: from `JURY_REVIEW`,
    `APPEALED`, `JURIED_OUT`, or `WAITLISTED` — any non-terminal state, else
    `ERR_APPLICATION_NOT_WITHDRAWABLE` — the owning vendor may withdraw, moving the
    application to its terminal `WITHDRAWN` state."
    PRD §3.3: "The application must currently be in `JURY_REVIEW`, `APPEALED`, or
    `WAITLISTED`; deciding from any other state fails with
    `ERR_APPLICATION_NOT_DECIDABLE`."
    PRD §3.3: "The appeal requires the application to be `JURIED_OUT` (else
    `ERR_APPLICATION_NOT_APPEALABLE`)"

    Design: Corner/errors/application_lifecycle_guards
    """
    season = make_season(name="AppGuard Revel")
    vx = make_vendor(business_name="Silk Roaders", category="ARTISAN")
    vy = make_vendor(business_name="Tinsmiths", category="ARTISAN")
    ax = make_application(season["id"], vx["id"], 64, "STANDARD")
    ay = make_application(season["id"], vy["id"], 64, "STANDARD")
    decide_application(ax["id"], "JURIED_IN", 8, 8, 8)
    validate_success(api.withdraw_application(ay["id"], make_vendor_headers(vy["id"])), 200)

    res = api.withdraw_application(ax["id"], make_vendor_headers(vx["id"]))
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_WITHDRAWABLE, expected_status=409)

    res = api.decide_application(
        ay["id"],
        {"craft_score": 9, "authenticity_score": 9, "safety_score": 9,
         "outcome": "JURIED_IN"},
        VENDOR_CO,
    )
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_DECIDABLE, expected_status=409)

    res = api.appeal_application(ay["id"], make_vendor_headers(vy["id"]))
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_APPEALABLE, expected_status=409)


def test_appeal_cycle_scores_and_latch(api):
    """PRD §3.3: "On every decision the scores are stored and the `jury_score` is
    computed as half the craft score plus three-tenths of the authenticity score
    plus one-fifth of the safety score, rounded half up to two decimal places."
    PRD §3.3: "A vendor whose application lands in `JURIED_OUT` may appeal it
    exactly once."

    Design: Difficulty/non_linear_state_machine/vendor_application_appeal_cycle
    """
    season = make_season(name="Jury Revel", volunteer_min_hours=0)
    vendor = make_vendor(business_name="Glassblower Guild", category="ARTISAN")
    application = make_application(season["id"], vendor["id"], 64, "STANDARD")

    decided = decide_application(application["id"], "JURIED_OUT", 7, 8, 9)
    assert decided["status"] == "JURIED_OUT"
    # 0.5*7 + 0.3*8 + 0.2*9 = 3.5 + 2.4 + 1.8 = 7.7
    assert decided["jury_score"] == 7.7

    appealed = validate_success(
        api.appeal_application(application["id"], make_vendor_headers(vendor["id"])),
        200,
    )
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_used"] is True


def test_appeal_cycle_redecide_and_terminal_appeal_rejection(api):
    """PRD §3.3: "From `APPEALED` the coordinator may decide again under the same
    rules as above, with fresh scores stored and the `jury_score` recomputed."
    PRD §3.3: "The appeal requires the application to be `JURIED_OUT` (else
    `ERR_APPLICATION_NOT_APPEALABLE`)"

    Design: Difficulty/non_linear_state_machine/vendor_application_appeal_cycle
    """
    season = make_season(name="Jury Revel", volunteer_min_hours=0)
    vendor = make_vendor(business_name="Glassblower Guild", category="ARTISAN")
    application = make_application(season["id"], vendor["id"], 64, "STANDARD")
    decide_application(application["id"], "JURIED_OUT", 7, 8, 9)
    validate_success(
        api.appeal_application(application["id"], make_vendor_headers(vendor["id"])), 200
    )

    redecided = decide_application(application["id"], "JURIED_IN", 9, 9, 9)
    assert redecided["status"] == "JURIED_IN"
    # 0.5*9 + 0.3*9 + 0.2*9 = 9.0
    assert redecided["jury_score"] == 9.0

    res = api.appeal_application(application["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_APPEALABLE, expected_status=409)


def test_waitlist_promotion_selector_on_release(api, any_headers):
    """PRD §3.3: "Release by the coordinator is available only from `RESERVED` (else
    `ERR_BOOTH_NOT_RELEASEABLE`) and moves the booth to `RELEASED`. Releasing a booth
    triggers waitlist promotion for the season: among applications currently
    `WAITLISTED`, the top candidate by `jury_score` descending — applications
    without a score rank last — with ties broken by earliest `created_at`, is
    promoted automatically to `JURIED_IN`; when no application is waiting, the
    release simply stands."

    Design: Corner/state_machines/waitlist_promotion_selector_on_release
    """
    season = make_season(name="Waitlist Revel", volunteer_min_hours=0)
    vendors = {
        key: make_vendor(business_name=f"Vendor {key.upper()}", category="ARTISAN")
        for key in ("a", "b", "x", "y", "z")
    }
    apps = {
        key: make_application(season["id"], vendors[key]["id"], 64, "MEADOW")
        for key in ("a", "b", "x", "y", "z")
    }
    decide_application(apps["a"]["id"], "JURIED_IN", 8, 8, 8)
    decide_application(apps["b"]["id"], "JURIED_IN", 8, 8, 8)
    decide_application(apps["x"]["id"], "WAITLISTED", 8, 8, 8)   # 8.0, filed 3rd
    decide_application(apps["y"]["id"], "WAITLISTED", 8, 8, 8)   # 8.0, filed 4th
    decide_application(apps["z"]["id"], "WAITLISTED", 9, 8, 8)   # 8.5, filed 5th
    booth_a = make_booth(apps["a"]["id"], "B-01", residency_end_date="2026-06-21T00:00:00Z")
    booth_b = make_booth(apps["b"]["id"], "B-02", residency_end_date="2026-06-21T00:00:00Z")

    # First release: highest jury_score wins (8.5 beats 8.0).
    validate_success(api.release_booth(booth_a["id"], VENDOR_CO), 200)
    z = validate_success(api.get_vendor_application(apps["z"]["id"], ANY), 200)
    x_mid = validate_success(api.get_vendor_application(apps["x"]["id"], ANY), 200)
    assert z["status"] == "JURIED_IN"
    assert x_mid["status"] == "WAITLISTED"

    # Second release: equal scores break ties by earliest created_at.
    validate_success(api.release_booth(booth_b["id"], VENDOR_CO), 200)
    x = validate_success(api.get_vendor_application(apps["x"]["id"], ANY), 200)
    y = validate_success(api.get_vendor_application(apps["y"]["id"], ANY), 200)
    assert x["status"] == "JURIED_IN"
    assert y["status"] == "WAITLISTED"
