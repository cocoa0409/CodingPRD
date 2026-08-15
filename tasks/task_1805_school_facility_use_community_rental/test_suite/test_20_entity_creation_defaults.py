"""Entity creation surface: defaults, server-minted system fields, uniqueness
scopes, required/enum field checks, and 404s on unknown ids (PRD §2.5, §2.6,
§2.9, §2.10, §3.1, §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    is_valid_uuid, is_iso8601_timestamp,
    make_site,
    create_site_payload, create_facility_payload, create_renter_payload,
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestSiteCreationDefaults:
    def test_create_site_returns_201_with_defaults(self, api):
        """PRD §3.1: "A `DistrictAdmin` registers a site with a district-wide
        unique `site_code` and a human-readable `display_name`; the
        `rental_timezone` may be supplied and otherwise defaults to
        `America/Los_Angeles`. Every site is born with `site_status` `ACTIVE`."
        PRD §4: "Operations that create a new, stand-alone resource — a site, a
        facility, a rate policy, a renter registration, an insurance certificate,
        a calendar event, a rental request, a payment transaction, a damage
        assessment, or a seasonal series — return a `201 Created` status code."

        Design: Corner/entities/create_site_returns_201_with_defaults
        """
        res = api.create_site({"site_code": "RHS", "display_name": "Riverview High"},
                              ADMIN)
        site = validate_success(res, 201)
        assert site["site_status"] == "ACTIVE", "site is born ACTIVE"
        assert site["rental_timezone"] == "America/Los_Angeles", (
            "timezone default applied when omitted")
        assert is_valid_uuid(site["id"]), "id is a type-prefix-free UUID"


class TestFacilityCreation:
    def test_facility_defaults_applied_when_omitted(self, api):
        """PRD §3.1: "Two scheduling guards travel with every facility:
        `setup_buffer_minutes` prepended to, and `teardown_buffer_minutes`
        appended to, every confirmed occupancy; each defaults to 30 minutes, must
        be at least zero, and must be a whole multiple of 15 minutes — anything
        else is rejected with `ERR_INVALID_TIME_WINDOW`. The `requires_custodian`
        flag, defaulting to true, decides whether every permit on the facility
        generates custodial labor. Facilities are born `AVAILABLE`."

        Design: Corner/entities/facility_defaults_and_unique_code_within_site
        """
        site = make_site("RSA", display_name="Site A")
        facility = validate_success(api.create_facility(
            site["id"],
            {"facility_code": "GYM", "facility_tier": "STANDARD", "capacity": 300},
            ADMIN), 201)
        assert facility["setup_buffer_minutes"] == 30
        assert facility["teardown_buffer_minutes"] == 30
        assert facility["requires_custodian"] is True
        assert facility["facility_status"] == "AVAILABLE"

    def test_facility_code_unique_within_site_only(self, api):
        """PRD §2.10: "A facility's `facility_code` is unique within its owning
        site."
        PRD §2.10: "Any violation is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/facility_defaults_and_unique_code_within_site
        """
        site_a = make_site("RSA", display_name="Site A")
        site_b = make_site("RSB", display_name="Site B")
        validate_success(api.create_facility(
            site_a["id"],
            {"facility_code": "GYM", "facility_tier": "STANDARD", "capacity": 300},
            ADMIN), 201)

        dup = api.create_facility(
            site_a["id"],
            {"facility_code": "GYM", "facility_tier": "PREMIUM", "capacity": 100},
            ADMIN)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE)

        # Uniqueness scope is site-local: the same code on another site succeeds.
        other = api.create_facility(
            site_b["id"],
            {"facility_code": "GYM", "facility_tier": "STANDARD", "capacity": 100},
            ADMIN)
        validate_success(other, 201)


class TestRenterCreation:
    def test_computed_fields_ignore_client_input(self, api):
        """PRD §3.3: "A fresh registration starts in `GOOD_STANDING` with
        `credit_balance_cents` at 0, `outstanding_balance_cents` at 0, and
        `forfeiture_count` at 0."

        Design: Corner/entities/computed_fields_ignore_client_input
        """
        res = api.create_renter(
            {"org_name": "Sneaky Org", "rate_class": "FOR_PROFIT",
             "outstanding_balance_cents": 0, "credit_balance_cents": 999999,
             "forfeiture_count": 0, "org_standing": "GOOD_STANDING"},
            DIRECTOR)
        org = validate_success(res, 201)
        assert org["credit_balance_cents"] == 0, "client-supplied 999999 ignored"
        assert org["outstanding_balance_cents"] == 0
        assert org["forfeiture_count"] == 0
        assert org["org_standing"] == "GOOD_STANDING"

    def test_org_name_uniqueness_is_case_insensitive(self, api):
        """PRD §2.10: "A renter organization's `org_name` is unique
        case-insensitively — two registrations whose names differ only in letter
        case collide."

        Design: Corner/entities/renter_org_name_case_insensitive_uniqueness
        """
        validate_success(api.create_renter(
            create_renter_payload(org_name="Riverview PTA"), DIRECTOR), 201)
        res = api.create_renter(
            create_renter_payload(org_name="riverview pta",
                                  nonprofit_registration_no="99-9999999"),
            DIRECTOR)
        validate_error(res, ApiErrorId.ERR_DUPLICATE)

    def test_nonprofit_requires_registration_number(self, api):
        """PRD §3.3: "A **RenterOrganization** is registered by a
        `FacilitiesDirector` or `DistrictAdmin` with a case-insensitively unique
        `org_name` and a `rate_class`; a `NONPROFIT` registration must
        additionally supply its `nonprofit_registration_no` (the 501(c)(3) EIN),
        which remains null for the other classes."
        PRD §2.9: "At this same tier, before any deeper business rule, the body
        itself is checked: a malformed body, a missing required field, a value of
        the wrong type, or an enum value outside its declared set yields
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/nonprofit_requires_registration_number
        """
        res = api.create_renter(
            {"org_name": "NoReg Nonprofit", "rate_class": "NONPROFIT"}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

        ok = api.create_renter(
            {"org_name": "Plain Profit", "rate_class": "FOR_PROFIT"}, DIRECTOR)
        org = validate_success(ok, 201)
        assert org["rate_class"] == "FOR_PROFIT"

    def test_enum_out_of_range_rejected(self, api):
        """PRD §3.2: "Every renter belongs to a rate class — `INTERNAL`,
        `NONPROFIT`, or `FOR_PROFIT` — and every facility belongs to a tier; the
        **RateClassPolicy** is where those two dimensions meet money."
        PRD §2.9: "At this same tier, before any deeper business rule, the body
        itself is checked: a malformed body, a missing required field, a value of
        the wrong type, or an enum value outside its declared set yields
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/enum_out_of_range_rejected
        """
        res = api.create_renter(
            {"org_name": "Bad Enum Org", "rate_class": "CHARITY"}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestSystemFields:
    def test_system_fields_are_server_minted(self, api):
        """PRD §2.5: "Client-supplied `id`, `created_at`, or `version` values in
        a creation payload are ignored: the server mints all three."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as
        a UUID, with no type prefix."

        Design: Corner/entities/system_fields_server_minted
        """
        res = api.create_site(
            {"site_code": "SYS1", "display_name": "System Field Test",
             "id": "00000000-0000-0000-0000-000000000000",
             "created_at": "1999-01-01T00:00:00Z", "version": 42},
            ADMIN)
        site = validate_success(res, 201)
        assert site["id"] != "00000000-0000-0000-0000-000000000000"
        assert is_valid_uuid(site["id"])
        assert site["version"] != 42, "client-supplied version ignored"
        assert isinstance(site["version"], int)
        assert site["created_at"] != "1999-01-01T00:00:00Z"
        assert is_iso8601_timestamp(site["created_at"])


class TestNotFound:
    def test_get_nonexistent_resources_return_404(self, api):
        """PRD §2.6: "The first identifier that does not correspond to an
        existing resource aborts the request immediately with `ERR_NOT_FOUND`
        (HTTP 404), before any deeper path segment is examined and before any
        business rule runs."

        Design: Corner/entities/get_nonexistent_resources_return_404
        """
        missing = NON_EXISTENT_UUID
        checks = [
            api.get_site(missing, DIRECTOR),
            api.get_facility(missing, DIRECTOR),
            api.get_request(missing, DIRECTOR),
            api.get_permit(missing, DIRECTOR),
            api.get_invoice(missing, DIRECTOR),
            api.get_work_order(missing, DIRECTOR),
            api.get_damage_assessment(missing, DIRECTOR),
            api.get_seasonal_permit(missing, DIRECTOR),
        ]
        for res in checks:
            validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_facility_creation_requires_existing_site_parent(self, api):
        """PRD §2.6: "For any endpoint whose path contains more than one
        identifier, the server validates existence strictly left-to-right: the
        site segment before the facility segment, the organization segment before
        the request segment, the permit segment before any of its invoices,
        payments, work orders, or damage assessments."

        Design: Corner/entities/facility_requires_existing_site_parent
        """
        res = api.create_facility(
            NON_EXISTENT_UUID,
            create_facility_payload(),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestBufferShape:
    @pytest.mark.parametrize("bad_overrides", [
        {"setup_buffer_minutes": 20},      # not a whole multiple of 15
        {"teardown_buffer_minutes": -15},  # below the at-least-zero floor
    ])
    def test_buffer_must_be_quarter_hour_multiple(self, api, bad_overrides):
        """PRD §3.1: "Two scheduling guards travel with every facility:
        `setup_buffer_minutes` prepended to, and `teardown_buffer_minutes`
        appended to, every confirmed occupancy; each defaults to 30 minutes, must
        be at least zero, and must be a whole multiple of 15 minutes — anything
        else is rejected with `ERR_INVALID_TIME_WINDOW`."

        Design: Corner/entities/buffer_must_be_15_minute_multiple
        """
        site = make_site("RHS")
        payload = {"facility_code": "GYM", "facility_tier": "STANDARD",
                   "capacity": 100}
        payload.update(bad_overrides)
        res = api.create_facility(site["id"], payload, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW)
