"""Health permits: category gate, duplicate/revoke guards, and the conduct-driven
revocation cascade into booth suspension and posture."""
from test_helpers import (
    ApiErrorId,
    get_booth,
    get_season,
    make_juried_vendor,
    make_season,
    set_clock,
    setup_conduct_revoke_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, OPERATOR, VENDOR_CO
from test_helpers.test_users import make_vendor_headers


def test_artisan_permit_not_applicable(api):
    """PRD §3.4: "Any vendor whose application is `JURIED_IN` and whose vendor
    `category` is `FOOD` or `BEVERAGE` may apply for a health permit against that
    application; the caller must own the application. Applying against an
    application in any other state fails with `ERR_APPLICATION_NOT_JURIED_IN`,
    applying for a vendor of any other category fails with
    `ERR_PERMIT_NOT_APPLICABLE`"

    Design: Corner/validations/artisan_permit_not_applicable
    """
    season = make_season(name="NA Revel")
    vendor, application = make_juried_vendor(
        season["id"], business_name="Leatherworks", category="ARTISAN",
        booth_size_sqft=64, requested_location_tier="STANDARD",
    )
    res = api.create_food_permit(
        {"application_id": application["id"]}, make_vendor_headers(vendor["id"])
    )
    validate_error(res, ApiErrorId.ERR_PERMIT_NOT_APPLICABLE, expected_status=409)


def test_permit_duplicate_and_revoke_guards(api, vendor_coordinator_headers):
    """PRD §3.4: "applying while the application already holds a non-terminal permit
    fails with `ERR_DUPLICATE_PERMIT` — only one live permit may exist per
    application."
    PRD §3.4: "Revocation by the coordinator requires an `ISSUED` permit (else
    `ERR_PERMIT_NOT_REVOKABLE`) and moves it to `REVOKED`."

    Design: Corner/errors/permit_duplicate_and_revoke_guards
    """
    season = make_season(name="PermitGuard Revel")
    vendor, application = make_juried_vendor(
        season["id"], business_name="Pie Cart", category="FOOD",
        booth_size_sqft=80, requested_location_tier="STANDARD",
    )
    permit = validate_success(
        api.create_food_permit(
            {"application_id": application["id"]}, make_vendor_headers(vendor["id"])
        ),
        201,
    )

    res = api.create_food_permit(
        {"application_id": application["id"]}, make_vendor_headers(vendor["id"])
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PERMIT, expected_status=409)

    res = api.revoke_permit(permit["id"], vendor_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_PERMIT_NOT_REVOKABLE, expected_status=409)


def test_conduct_revoke_permit_revokes_permit(api, operator_headers, any_headers):
    """PRD §3.9: "An upheld `REVOKE_PERMIT` fires the permit cascade of §3.4 in
    three steps: the linked permit moves `ISSUED` → `REVOKED`, the application's
    `CONFIRMED` booth drops to `SUSPENDED`, and the season's readiness posture is
    re-derived."

    Design: Difficulty/transitive_cascade/conduct_revoke_permit_booth_suspension_cascade
    """
    ctx = setup_conduct_revoke_scenario()
    assert get_season(ctx["season"]["id"])["readiness_posture"] == "READY"

    resolved = validate_success(
        api.resolve_conduct_case(
            ctx["case"]["id"],
            {"outcome": "UPHELD", "sanction": "REVOKE_PERMIT"},
            OPERATOR,
        ),
        200,
    )
    assert resolved["status"] == "UPHELD"
    assert resolved["sanction"] == "REVOKE_PERMIT"

    permit = validate_success(api.get_food_permit(ctx["permit"]["id"], ANY), 200)
    assert permit["status"] == "REVOKED"


def test_conduct_revoke_permit_suspends_booth_and_flips_posture(api, any_headers):
    """PRD §3.4: "Either event fires the same cascade: every booth assignment of the
    same application currently `CONFIRMED` drops to `SUSPENDED`, and the season's
    readiness posture is re-derived, since a juried-in food application no longer
    holds an issued permit."
    PRD §2.6: "the posture is `CONDITIONAL` when either of the following holds: some
    application of the season is `JURIED_IN` for a vendor whose `category` is `FOOD`
    or `BEVERAGE` yet has no food permit of the same application in `ISSUED` status
    with an `expiry_date` on or after the current clock instant"

    Design: Difficulty/transitive_cascade/conduct_revoke_permit_booth_suspension_cascade
    """
    ctx = setup_conduct_revoke_scenario()
    validate_success(
        api.resolve_conduct_case(
            ctx["case"]["id"],
            {"outcome": "UPHELD", "sanction": "REVOKE_PERMIT"},
            OPERATOR,
        ),
        200,
    )

    booth = validate_success(api.get_booth_assignment(ctx["booth"]["id"], ANY), 200)
    assert booth["status"] == "SUSPENDED"
    season = get_season(ctx["season"]["id"])
    assert season["readiness_posture"] == "CONDITIONAL"
