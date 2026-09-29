"""Declared authorization: exclusive operations, shared reads, scoped identities."""

from test_helpers import (
    factories,
    fixtures,
    make_fleet_manager_headers,
    make_tire_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDealerAdminExclusiveOperations:
    def test_no_other_role_may_open_an_account_or_move_the_clock(self, api):
        """PRD §2.1: "Builds the location network, fleet accounts, tire policies,
        national agreements, production lines and technician rosters, and controls the
        logical clock."
        PRD §2.1: "If both headers are present and well-formed but the named role is
        not authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.5: "Before any request sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/rbac/billing_clerk_cannot_create_fleet_account_or_set_clock
        """
        location = fixtures.create_location(
            name="Rbac Commercial",
            location_code="RBC",
            scrap_permit_number="OH-SCRAP-4040",
        )

        validate_error(
            api.create_fleet_account(
                factories.fleet_account_payload(
                    location["id"], name="Sneaky Freight"
                ),
                fixtures.CLERK,
            ),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )
        validate_error(
            api.set_clock(
                factories.clock_payload("2027-01-01T00:00:00Z"), fixtures.SCHEDULER
            ),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )
        validate_error(
            api.create_fleet_account(
                factories.fleet_account_payload(
                    location["id"],
                    name="Sneaky Freight Two",
                    account_type="NOT_A_TYPE",
                ),
                fixtures.CLERK,
            ),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )
        # The role check precedes body validation, so the undeclared account type
        # never gets far enough to be reported as a malformed request.

        _rows, meta = validate_paginated(api.list_fleet_accounts(fixtures.ADMIN))
        assert meta["total_count"] == 0, "no account was opened by the wrong role"

        # The refused clock call left the default logical clock in place, which is
        # observable through the instant stamped on a ledger posting.
        fleet = fixtures.create_fleet(location["id"])
        fixtures.create_policy(fleet["id"])
        casing = fixtures.create_inspected_casing(
            fleet["id"], location["id"], grade="A"
        )
        entries = fixtures.list_casing_ledger(casing["id"])
        assert len(entries) == 1
        assert entries[0]["posted_at"].startswith("2026-08-01"), (
            "the clock never advanced to 2027"
        )


class TestSharedCasingRead:
    def test_all_six_reader_roles_receive_the_identical_row(self, api):
        """PRD §2.1: "When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of
        the acting `FleetAccount`; ownership checks on any resource that references a
        `FleetAccount` compare the resource's `fleet_account_id` to `X-User-ID`, and a
        mismatch is rejected with `ERR_FLEET_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.1: "When `X-User-Role` is `TireTechnician`, `X-User-ID` is the `id` of
        the acting `Technician`; a technician recording arrival or completion on a road
        service call must be the technician named in that call's `technician_id`, and
        any other technician is rejected with `ERR_TECHNICIAN_SCOPE_VIOLATION` (HTTP
        403)."

        Design: Corner/rbac/casing_read_is_shared_across_all_six_reader_roles
        """
        location = fixtures.create_location(
            name="Shared Commercial",
            location_code="SHC",
            scrap_permit_number="OH-SCRAP-4041",
        )
        fleet = fixtures.create_fleet(location["id"], name="Shared Freight")
        technician = fixtures.create_technician(
            location["id"], name="Shar E", certification_level="LEVEL_2"
        )
        casing = fixtures.create_casing(
            fleet["id"], casing_serial="CS-4041", scrap_weight_lbs=136
        )

        readers = {
            "DealerAdmin": fixtures.ADMIN,
            "FleetManager": make_fleet_manager_headers(fleet["id"]),
            "TireTechnician": make_tire_technician_headers(technician["id"]),
            "CasingInspector": fixtures.INSPECTOR,
            "PlantScheduler": fixtures.SCHEDULER,
            "ComplianceOfficer": fixtures.OFFICER,
        }

        seen = {}
        for role, headers in readers.items():
            data = validate_success(api.get_casing(casing["id"], headers))
            assert data["id"] == casing["id"], f"{role} read the wrong row"
            assert data["version"] == 1, f"{role}'s read mutated the row"
            seen[role] = data

        reference = seen["DealerAdmin"]
        for role, data in seen.items():
            assert data == reference, (
                f"{role} received a different projection of the same casing"
            )
        assert reference["fleet_account_id"] == fleet["id"], (
            "the FleetManager identity is the owning fleet's own identifier"
        )


class TestCostPerMileIsFleetScoped:
    def test_a_fleet_manager_is_confined_to_its_own_analytic(self, api):
        """PRD §2.1: "When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of
        the acting `FleetAccount`; ownership checks on any resource that references a
        `FleetAccount` compare the resource's `fleet_account_id` to `X-User-ID`, and a
        mismatch is rejected with `ERR_FLEET_SCOPE_VIOLATION` (HTTP 403)."
        PRD §3.9: "A group with no included assets is omitted entirely rather than
        emitted with a zero, and when no group survives at all the response carries a
        `group_count` of 0 and an empty `groups` array."

        Design: Corner/rbac/fleet_manager_cannot_read_another_fleets_cost_per_mile
        """
        location = fixtures.create_location(
            name="Scope Commercial",
            location_code="SPC2",
            scrap_permit_number="OH-SCRAP-4042",
        )
        fleet_a = fixtures.create_fleet(location["id"], name="Scope Fleet A")
        fleet_b = fixtures.create_fleet(location["id"], name="Scope Fleet B")
        manager_of_a = make_fleet_manager_headers(fleet_a["id"])

        validate_error(
            api.get_cost_per_mile(
                fleet_b["id"], manager_of_a, params={"variant": "HISTORICAL_ACTUAL"}
            ),
            "ERR_FLEET_SCOPE_VIOLATION",
            expected_status=403,
        )

        own = validate_success(
            api.get_cost_per_mile(
                fleet_a["id"], manager_of_a, params={"variant": "HISTORICAL_ACTUAL"}
            )
        )
        assert own["group_count"] == 0, (
            "an empty analytic is still a success, which is what separates the "
            "scope refusal from a thin result"
        )
        assert own["groups"] == []
        assert own["excluded_asset_count"] == 0

        peer = validate_success(
            api.get_cost_per_mile(
                fleet_b["id"], fixtures.ADMIN, params={"variant": "HISTORICAL_ACTUAL"}
            )
        )
        assert peer["group_count"] == 0, (
            "the endpoint itself is open to the administrator; only the fleet-backed "
            "identity is confined"
        )


class TestCreditMintingAndSpendingAreSeparated:
    def test_the_clerk_cannot_grade_and_the_inspector_cannot_bill(self, api):
        """PRD §2.1: "Records inspection grades and condemnations, the acts that make
        casing credit accrue."
        PRD §2.1: "Creates, submits and settles cross-location invoices, and shares
        the dispute action with `FleetManager`."
        PRD §2.1: "If both headers are present and well-formed but the named role is
        not authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/billing_clerk_cannot_grade_the_casing_it_will_later_bill
        """
        program = fixtures.setup_fleet_program(
            location_overrides={
                "name": "Sepduty Commercial",
                "location_code": "SPD",
                "scrap_permit_number": "OH-SCRAP-4043",
            },
            fleet_overrides={
                "name": "Sepduty Freight",
                "account_type": "NATIONAL_ACCOUNT",
                "billing_mode": "CROSS_LOCATION",
            },
        )
        fleet_id = program["fleet"]["id"]
        casing = fixtures.create_collected_casing(
            fleet_id,
            program["location"]["id"],
            casing_serial="CS-4043",
            scrap_weight_lbs=137,
        )
        fleet_version = fixtures.read_fleet(fleet_id, fixtures.CLERK)["version"]

        validate_error(
            api.inspect_casing(
                casing["id"],
                factories.inspect_casing_payload("A", casing["version"]),
                fixtures.CLERK,
            ),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )
        validate_error(
            api.reject_casing(
                casing["id"],
                factories.reject_casing_payload("Trying anyway"),
                fixtures.CLERK,
            ),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )
        validate_error(
            api.create_cross_location_invoice(
                factories.invoice_payload(
                    fleet_id, "2026-08-01", "2026-08-31", fleet_version
                ),
                fixtures.INSPECTOR,
            ),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )

        untouched = fixtures.read_casing(casing["id"])
        assert untouched["status"] == "COLLECTED"
        assert untouched.get("inspection_grade") is None
        assert untouched["provisional_credit_cents"] == 0

        assert fixtures.read_fleet(fleet_id)["casing_credit_balance_cents"] == 0
        assert fixtures.list_ledger(fleet_id) == [], (
            "the party that bills the credit cannot mint it"
        )
        assert fixtures.count_invoices(fleet_id) == 0, (
            "and the party that mints it cannot bill it"
        )


class TestAuthenticationPrecedesEverything:
    def test_a_request_without_a_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
        the acting user, and `X-User-Role`, naming the role that user is acting in."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
        eight role names declared below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/create_casing_missing_x_user_role_returns_unauthenticated
        """
        location = fixtures.create_location(
            name="Anon Commercial",
            location_code="ANC",
            scrap_permit_number="OH-SCRAP-4044",
        )
        fleet = fixtures.create_fleet(location["id"], name="Anon Freight")
        anonymous = {"X-User-ID": "anonymous-1"}

        validate_error(
            api.create_casing(
                factories.casing_payload(
                    fleet["id"], casing_serial="CS-4044", scrap_weight_lbs=138
                ),
                anonymous,
            ),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )
        validate_error(
            api.list_casings(anonymous, params={"fleet_account_id": fleet["id"]}),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )
        # Reads are guarded too: there is no public projection of the collection.

        _rows, meta = validate_paginated(api.list_casings(fixtures.ADMIN))
        assert meta["total_count"] == 0, "the anonymous write created nothing"
