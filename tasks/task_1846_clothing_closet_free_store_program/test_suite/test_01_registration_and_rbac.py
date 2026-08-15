"""Client registration, role-based access control, ownership scope, and the
client-profile optimistic-concurrency rule."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_client,
    checkin_signup,
    create_client_payload,
    create_partner,
    create_shift,
    grade_items,
    issue_voucher,
    make_client_headers,
    make_referral_partner_headers,
    make_volunteer_headers,
    make_volunteer_lead_headers,
    open_batch_in_sort,
    register_client,
    register_volunteer,
    setup_sorting_staff,
    signup_volunteer,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestClientRegistration:
    def test_client_creation_defaults_and_system_fields(self, api):
        """PRD: "A staff member registers a client by supplying the client's
        `full_name` and `household_size` — the count of people in the household,
        which must be at least 1 — and optionally an `eligibility_tier` of
        `STANDARD` or `HARDSHIP`, defaulting to `STANDARD` when omitted. New
        clients begin with status `ACTIVE`. Until a client's first checkout,
        `last_checkout_at` is null."

        Design: Corner/entities/client_creation_defaults_and_system_fields
        """
        staff = setup_sorting_staff()

        resp = api.create_client(
            create_client_payload(full_name="C", household_size=3), staff["headers"])
        client = validate_success(resp, 201)
        assert_client(client)
        assert client["eligibility_tier"] == "STANDARD", "omitted tier defaults to STANDARD"
        assert client["status"] == "ACTIVE"
        assert client["visits_in_30d"] == 0, "no in-window checkouts yet"
        assert client["items_in_30d"] == 0, "no distributed lines yet"
        assert client["last_checkout_at"] is None, "null until the first checkout"

    def test_client_create_missing_required_household_size(self, api):
        """PRD: "The cascade runs as follows: first, header presence and role
        recognition (`ERR_UNAUTHENTICATED`); second, role authorization on the
        endpoint (`ERR_FORBIDDEN`); third, ownership scoping for entity-backed
        roles (`ERR_FORBIDDEN`); fourth, existence of every referenced identifier
        (`ERR_NOT_FOUND`); fifth, request shape — required fields present, types
        and enum values valid, numeric ranges satisfied (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/client_create_missing_required_household_size
        """
        staff = setup_sorting_staff()

        resp = api.create_client({"full_name": "C"}, staff["headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_volunteer_get_not_found_returns_404(self, api):
        """PRD: "The cascade runs as follows: first, header presence and role
        recognition (`ERR_UNAUTHENTICATED`); second, role authorization on the
        endpoint (`ERR_FORBIDDEN`); third, ownership scoping for entity-backed
        roles (`ERR_FORBIDDEN`); fourth, existence of every referenced identifier
        (`ERR_NOT_FOUND`)"

        Design: Corner/entities/volunteer_get_not_found_returns_404
        """
        resp = api.get_volunteer(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthenticationAndRoleChecks:
    def test_checkin_missing_auth_headers_unauthenticated(self, api):
        """PRD: "A request whose headers are missing, or whose role value is not
        one of these five, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/checkin_missing_auth_headers_unauthenticated
        """
        resp = api.create_client(
            create_client_payload(full_name="C", household_size=2), None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_client_cannot_create_zone(self, api):
        """PRD: "A request whose role is recognized but not listed among the
        roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN`."
        PRD endpoint table: "| POST | `/closet/storage-zones` | Create a storage
        zone | ProgramAdmin |"

        Design: Corner/rbac/client_cannot_create_zone
        """
        resp = api.create_storage_zone(
            {"zone_code": "ZX", "season_policy": "ALL_SEASON", "capacity_items": 5},
            make_client_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_batch_close_volunteer_cannot_close(self, api):
        """PRD: "A `VolunteerLead` or `ProgramAdmin` moves a `SORTED` batch to
        `CLOSED`, recording themselves in `closed_by_user_id`."
        PRD: "A request whose role is recognized but not listed among the roles
        permitted for the target endpoint is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/batch_close_volunteer_cannot_close
        """
        lead = register_volunteer("Lead One", is_lead=True)
        lead_headers = make_volunteer_lead_headers(lead["id"])
        plain = register_volunteer("Vol Two", is_lead=False)
        shift = create_shift("2026-07-31T22:00:00Z", "2026-08-01T04:00:00Z",
                             role_type="SORTING", capacity_volunteers=2)
        signup = signup_volunteer(shift["id"], lead)
        checkin_signup(shift["id"], signup["id"], lead)
        batch = open_batch_in_sort(lead_headers, donor_name="D", item_count_declared=1)
        grade_items(batch["id"], [{"category": "ADULT_TOPS", "season": "ALL_SEASON",
                                   "quality_grade": "GOOD"}], lead_headers)

        resp = api.close_donation_batch(batch["id"], make_volunteer_headers(plain["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOwnershipScope:
    def test_client_ownership_scope_on_reads(self, api):
        """PRD: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the
        acting Client, and ownership checks compare against client-referencing
        fields; a Client may read only their own record, their own visits, and
        their own vouchers."
        PRD: "Any attempt by an entity-backed role to act outside its ownership
        scope is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/client_ownership_scope_on_reads
        """
        client_a = register_client("A", 2)
        client_b = register_client("B", 2)

        resp = api.get_client(client_b["id"], make_client_headers(client_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        own = validate_success(
            api.get_client(client_a["id"], make_client_headers(client_a["id"])), 200)
        assert own["full_name"] == "A"

    def test_partner_ownership_scope_on_issue(self, api):
        """PRD: "When `X-User-Role` is `ReferralPartner`, `X-User-ID` is the `id`
        of the acting ReferralPartner, and the partner may read only its own
        record and issue or revoke vouchers under its own partner id."
        PRD: "Any attempt by an entity-backed role to act outside its ownership
        scope is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/partner_ownership_scope_on_issue
        """
        partner_a = create_partner("Agency A", 5)
        partner_b = create_partner("Agency B", 5)
        client = register_client("C", 2)

        resp = api.issue_voucher(
            partner_b["id"],
            {"client_id": client["id"], "bonus_items": 1,
             "expires_at": "2026-12-01T00:00:00Z"},
            make_referral_partner_headers(partner_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        own = issue_voucher(partner_a, client["id"], bonus_items=1,
                            expires_at="2026-12-01T00:00:00Z")
        assert own["status"] == "ISSUED"
        assert own["partner_id"] == partner_a["id"]


class TestClientOptimisticConcurrency:
    def test_occ_client_stale_version(self, api):
        """PRD: "Updating a client profile requires the request to carry
        `expected_client_version`, holding the client's `version` as the writer
        last observed it. Because a visit's allowance snapshot is taken from the
        live profile at check-in, a writer who read the profile before another
        writer's update must not silently overwrite it; if the supplied value no
        longer matches the client's current `version`, the update is rejected
        with `ERR_STALE_VERSION` and the stale writer re-reads and retries."

        Design: Corner/cross_cutting_layers/occ_client_stale_version
        """
        client = register_client("C", 2)
        observed_version = client["version"]

        first = validate_success(
            api.patch_client(client["id"],
                             {"household_size": 5,
                              "expected_client_version": observed_version},
                             ADMIN),
            200)
        assert first["household_size"] == 5
        assert first["version"] == observed_version + 1, (
            "version increments by one with every modification")

        resp = api.patch_client(client["id"],
                                {"household_size": 6,
                                 "expected_client_version": observed_version},
                                ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        final = validate_success(api.get_client(client["id"], ADMIN), 200)
        assert final["household_size"] == 5, "the stale writer's update must not land"
