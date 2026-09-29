"""Authentication, the role matrix, entity-backed identity and separation of duties.

The seven roles carve the surface into non-overlapping slices, so authorization
is never a two-tier admin/user check. These tests drive the exclusive slices, the
two shared grants, the one entity-backed identity and the two duty pairs, and
they confirm the screening order: no identity outranks a wrong role, and a wrong
role outranks the existence of the resource named in the path.
"""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    approve_claim_payload,
    create_capacity_obligation_payload,
    create_capacity_test_payload,
    create_market_bid_payload,
    create_storage_asset_payload,
    create_telemetry_sample_payload,
    deny_claim_payload,
)
from test_helpers.fixtures import (
    ASSET_MANAGER,
    CLAIM_FILER,
    CONTROL_ROOM,
    DISPATCH_DAY_CLOCK,
    MARKET_OPERATOR,
    OPENING_OFFICER,
    SAFETY_OFFICER,
    TRADER,
    accept_dispatch,
    cleared_bid,
    close_event,
    execute_dispatch,
    file_claim,
    finish_test,
    hold_reservation,
    issue_dispatch,
    lightly_cycled_plant,
    open_safety_event,
    provision_asset,
    refresh_claim,
    refresh_dispatch,
    refresh_safety_event,
    schedule_test,
    set_clock,
    start_test,
    submit_claim,
)
from test_helpers.test_users import (
    make_headers,
    make_platform_admin_headers,
    make_safety_officer_headers,
    make_site_controller_headers,
)

NO_AUTH_HEADERS = {"Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = make_headers("battery-whisperer-1", "BatteryWhisperer")
ABSENT_DISPATCH_ID = "00000000-0000-4000-8000-00000000fff9"
ABSENT_RESERVATION_ID = "00000000-0000-4000-8000-00000000fff8"
ABSENT_CLAIM_ID = "00000000-0000-4000-8000-00000000fffa"
WINDOW_START = "2026-08-10T12:00:00Z"
WINDOW_END = "2026-08-10T20:00:00Z"


class TestExclusiveOperationsRejectEveryOtherRole:
    """Five endpoints, five roles that hold an adjacent but different mandate."""

    def test_a_trader_cannot_register_an_asset(self):
        """Registration belongs to the platform administrator alone.

        PRD: "The acting role appears in the target operation's authorised-role list — otherwise `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/other_roles_exclusive_operations_are_forbidden
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        validate_error(
            api_client.create_storage_asset(
                create_storage_asset_payload(
                    name="Rogue BESS",
                    nameplate_energy_mwh=50.0,
                    power_rating_mw=12.0,
                    poi_mw_limit=12.0,
                    poi_mva_limit=13.2,
                    reactive_capability_mvar=6.0,
                    initial_soc_mwh=40.0,
                ),
                TRADER,
            ),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )

        data, meta = validate_paginated(api_client.list_storage_assets(ASSET_MANAGER))
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [asset["id"]]

    def test_the_market_operator_that_clears_offers_cannot_draft_them(self):
        """Clearing and drafting are adjacent duties held by different desks.

        PRD: "`MarketTrader` builds and manages market offers: drafting, submitting, revising and withdrawing them, and reserving the state of charge that backs them."

        Design: Corner/rbac/other_roles_exclusive_operations_are_forbidden
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        validate_error(
            api_client.create_market_bid(
                create_market_bid_payload(
                    asset["id"],
                    ABSENT_RESERVATION_ID,
                    offer_mw=10.0,
                ),
                MARKET_OPERATOR,
            ),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )

        _, meta = validate_paginated(api_client.list_market_bids(ASSET_MANAGER))
        assert meta["total_count"] == 0

    def test_the_control_room_that_accepts_an_instruction_cannot_execute_it(self):
        """Acceptance is the control room's act; execution belongs to the plant.

        PRD: "`ControlRoomOperator` runs the fleet control room: it accepts dispatch instructions, aborts them, records unavailability, and may raise a safety event."

        Design: Corner/rbac/other_roles_exclusive_operations_are_forbidden
        """
        set_clock(DISPATCH_DAY_CLOCK)
        provision_asset()

        validate_error(
            api_client.execute_dispatch_instruction(ABSENT_DISPATCH_ID, CONTROL_ROOM),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )

    def test_a_safety_officer_cannot_schedule_a_capacity_test(self):
        """The testing programme is the asset manager's, not the safety desk's.

        PRD: "`SafetyOfficer` owns the safety lifecycle: reporting events, recording suppression discharge, and closing events once emergency response has cleared the site."

        Design: Corner/rbac/other_roles_exclusive_operations_are_forbidden
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        validate_error(
            api_client.create_capacity_test(
                create_capacity_test_payload(
                    asset["id"], scheduled_date="2026-08-20T00:00:00Z"
                ),
                SAFETY_OFFICER,
            ),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )

        _, meta = validate_paginated(api_client.list_capacity_tests(ASSET_MANAGER))
        assert meta["total_count"] == 0

    def test_an_asset_manager_cannot_adjudicate_a_claim_it_might_have_filed(self):
        """The provider's seat is the platform administrator's, on a path id that does not exist.

        PRD: "The resource named by an `{id}` path segment exists; when a path carries more than one identifier they are resolved strictly left to right."

        Design: Corner/rbac/other_roles_exclusive_operations_are_forbidden
        """
        set_clock(DISPATCH_DAY_CLOCK)
        provision_asset()

        validate_error(
            api_client.adjudicate_warranty_claim(
                ABSENT_CLAIM_ID, deny_claim_payload("NO_SHORTFALL"), ASSET_MANAGER
            ),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )

    def test_a_forbidden_role_never_learns_whether_the_resource_exists(self):
        """Role rejection at priority 2 outranks the existence check at priority 4.

        PRD: "The Authorized Role(s) column lists the roles permitted to call the endpoint; any authenticated caller holding a different role receives `ERR_FORBIDDEN_ROLE`, and the ownership and separation-of-duties rules of §2.1 are applied on top of the role check where they apply."

        Design: Corner/rbac/other_roles_exclusive_operations_are_forbidden
        """
        set_clock(DISPATCH_DAY_CLOCK)
        provision_asset()

        validate_error(
            api_client.execute_dispatch_instruction(ABSENT_DISPATCH_ID, CONTROL_ROOM),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )
        validate_error(
            api_client.adjudicate_warranty_claim(
                ABSENT_CLAIM_ID, deny_claim_payload("NO_SHORTFALL"), ASSET_MANAGER
            ),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )


class TestObligationEnrolmentIsSharedByTwoRoles:
    """The grant is per-operation: both owning roles enrol into the same collection."""

    def test_the_asset_manager_may_enrol_the_plant(self):
        """Enrolment is one of the asset manager's shared duties.

        PRD: "An `AssetManager` or a `MarketOperator` enrols the asset by naming `asset_id`, the `program_name` — the programme the asset is enrolled in, such as an ISO capacity auction or a resource-adequacy programme, 1 to 120 characters and not blank — and the `program_year`, an integer between 2000 and 2100 inclusive."

        Design: Corner/rbac/shared_capacity_obligation_creation_works_for_both_owning_roles
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        obligation = validate_success(
                api_client.create_capacity_obligation(
                    create_capacity_obligation_payload(
                        asset["id"],
                        program_name="Desert RA",
                        program_year=2027,
                        committed_mw=20.0,
                        availability_hours_required=7884.0,
                        penalty_rate_usd_per_mw_hour=3000.0,
                    ),
                    ASSET_MANAGER,
                ),
                expected_status=201,
            )

        assert obligation["status"] == "ACTIVE"

    def test_the_market_operator_may_enrol_the_plant_too(self):
        """The same endpoint, a different owning role, the same created status.

        PRD: "It shares commissioning with `PlatformAdmin`, state-of-charge reservation and release with `MarketTrader`, and capacity-programme enrolment with `MarketOperator`."

        Design: Corner/rbac/shared_capacity_obligation_creation_works_for_both_owning_roles
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        obligation = validate_success(
                api_client.create_capacity_obligation(
                    create_capacity_obligation_payload(
                        asset["id"],
                        program_name="ISO Winter RA",
                        program_year=2027,
                        committed_mw=15.0,
                        availability_hours_required=2160.0,
                        penalty_rate_usd_per_mw_hour=2500.0,
                    ),
                    MARKET_OPERATOR,
                ),
                expected_status=201,
            )

        assert obligation["status"] == "ACTIVE"

    def test_both_enrolments_land_in_the_same_readable_collection(self):
        """Every role may read the collection both owning roles wrote to.

        PRD: "All seven roles may read every collection and every single resource."

        Design: Corner/rbac/shared_capacity_obligation_creation_works_for_both_owning_roles
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        by_manager = get_success_data(
            api_client.create_capacity_obligation(
                create_capacity_obligation_payload(
                    asset["id"],
                    program_name="Desert RA",
                    program_year=2027,
                    committed_mw=20.0,
                    availability_hours_required=7884.0,
                    penalty_rate_usd_per_mw_hour=3000.0,
                ),
                ASSET_MANAGER,
            )
        )
        by_operator = get_success_data(
            api_client.create_capacity_obligation(
                create_capacity_obligation_payload(
                    asset["id"],
                    program_name="ISO Winter RA",
                    program_year=2027,
                    committed_mw=15.0,
                    availability_hours_required=2160.0,
                    penalty_rate_usd_per_mw_hour=2500.0,
                ),
                MARKET_OPERATOR,
            )
        )

        data, meta = validate_paginated(
            api_client.list_capacity_obligations(
                CONTROL_ROOM, params={"asset_id": asset["id"]}
            )
        )

        assert meta["total_count"] == 2
        assert {row["id"] for row in data} == {by_manager["id"], by_operator["id"]}


class TestSiteControllerIdentityIsTheAssetId:
    """A valid `SiteController` role with the wrong asset id is still forbidden."""

    def _accepted_instruction(self):
        set_clock(DISPATCH_DAY_CLOCK)
        own = provision_asset()
        foreign = provision_asset(name="Mesa Verde BESS 5")
        reservation = hold_reservation(
            own["id"],
            reserved_mwh=40.0,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
        bid = cleared_bid(
            own["id"], reservation["id"], cleared_mw=10.0, offer_mw=10.0
        )
        dispatch = issue_dispatch(
            bid["id"],
            own["id"],
            instructed_mw=10.0,
            setpoint_start="2026-08-10T12:00:00Z",
            setpoint_end="2026-08-10T14:00:00Z",
        )
        accept_dispatch(dispatch["id"])
        return own, foreign, dispatch

    def test_a_foreign_controller_cannot_execute_the_instruction(self):
        """The role is right and the identity is not, so the ownership check rejects.

        PRD: "When the acting role is `SiteController`, `X-User-ID` equals the `id` of the storage asset the request targets, reached through the instruction, test or dispatch reference."

        Design: Corner/rbac/site_controller_with_a_foreign_asset_id_is_forbidden
        """
        _, foreign, dispatch = self._accepted_instruction()

        validate_error(
            api_client.execute_dispatch_instruction(
                dispatch["id"], make_site_controller_headers(foreign["id"])
            ),
            "ERR_ASSET_OWNERSHIP_MISMATCH",
            expected_status=403,
        )
        assert refresh_dispatch(dispatch["id"])["execution_status"] == "ACCEPTED"

    def test_a_foreign_controller_cannot_append_telemetry_either(self):
        """Here the asset is reached through the body's `dispatch_id`, not a path id.

        PRD: "Concretely, a `SiteController` may append telemetry, drive dispatch execution, completion or failure, and start or complete a capacity test only for the asset whose `id` equals its own `X-User-ID`, reached through the instruction's or test's asset reference; a mismatch is rejected with `ERR_ASSET_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/site_controller_with_a_foreign_asset_id_is_forbidden
        """
        _, foreign, dispatch = self._accepted_instruction()

        validate_error(
            api_client.create_telemetry_sample(
                create_telemetry_sample_payload(
                    dispatch["id"],
                    1,
                    "2026-08-10T13:00:00Z",
                    measured_mw=10.0,
                    measured_mvar=4.0,
                    soc_mwh_reading=78.0,
                    max_cell_temp_c=40.0,
                ),
                make_site_controller_headers(foreign["id"]),
            ),
            "ERR_ASSET_OWNERSHIP_MISMATCH",
            expected_status=403,
        )
        assert refresh_dispatch(dispatch["id"])["telemetry_sample_count"] == 0

    def test_the_assets_own_controller_executes_the_instruction(self):
        """Execution belongs to the plant whose id the controller carries.

        PRD: "The `SiteController` whose `X-User-ID` equals the asset's `id` moves the instruction `ACCEPTED → EXECUTING`."

        Design: Corner/rbac/site_controller_with_a_foreign_asset_id_is_forbidden
        """
        own, foreign, dispatch = self._accepted_instruction()
        validate_error(
            api_client.execute_dispatch_instruction(
                dispatch["id"], make_site_controller_headers(foreign["id"])
            ),
            "ERR_ASSET_OWNERSHIP_MISMATCH",
        )

        executing = execute_dispatch(dispatch["id"], own["id"])

        assert executing["execution_status"] == "EXECUTING"
        assert executing["asset_id"] == own["id"]


class TestFilerCannotAdjudicateTheirOwnClaim:
    """Both hats on one operator is exactly what the tracked identity catches."""

    def _submitted_claim(self):
        set_clock()
        asset = lightly_cycled_plant()
        test = schedule_test(asset["id"], scheduled_date="2026-08-01T00:00:00Z")
        start_test(test["id"], asset["id"])
        finish_test(test["id"], asset["id"], measured_capacity_mwh=90.0)
        claim = file_claim(asset["id"], test["id"], headers=CLAIM_FILER)
        return asset, submit_claim(claim["id"], headers=CLAIM_FILER)

    def test_the_claim_is_in_the_state_adjudication_departs_from(self):
        """The state guard cannot be what rejects the filer's own adjudication.

        PRD: "`submitted_by_user_id` records the filing identifier."

        Design: Corner/rbac/filer_cannot_adjudicate_their_own_warranty_claim_forbidden
        """
        _, claim = self._submitted_claim()

        assert claim["status"] == "SUBMITTED"
        assert claim["created_by_user_id"] == "am_filer"

    def test_the_filer_wearing_the_provider_hat_is_refused(self):
        """The role is correct, the state is correct, and the identity is not.

        PRD: "Adjudicating a warranty claim requires `X-User-ID` to differ from the claim's `created_by_user_id`, and closing a safety event requires `X-User-ID` to differ from the event's `opened_by_user_id`; either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/filer_cannot_adjudicate_their_own_warranty_claim_forbidden
        """
        _, claim = self._submitted_claim()

        validate_error(
            api_client.adjudicate_warranty_claim(
                claim["id"],
                approve_claim_payload(
                    remedy_install_date="2026-09-15T00:00:00Z", remedy_outage_days=5
                ),
                make_platform_admin_headers("am_filer"),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            expected_status=403,
        )
        assert refresh_claim(claim["id"])["status"] == "SUBMITTED"

    def test_a_different_administrator_approves_and_sizes_the_remedy(self):
        """A second pair of eyes approves, and the remedy is sized with the oversize factor.

        PRD: "**Remedy sizing** happens later, on the approval branch of adjudication: `remedy_energy_add_mwh` is the step-1 rated energy multiplied by the claim's `claimed_shortfall_pct` divided by 100, multiplied by an oversize factor of 1.10, rounded half up to 3 decimal places."

        Design: Corner/rbac/filer_cannot_adjudicate_their_own_warranty_claim_forbidden
        """
        _, claim = self._submitted_claim()
        validate_error(
            api_client.adjudicate_warranty_claim(
                claim["id"],
                approve_claim_payload(
                    remedy_install_date="2026-09-15T00:00:00Z", remedy_outage_days=5
                ),
                make_platform_admin_headers("am_filer"),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
        )

        approved = validate_success(
                api_client.adjudicate_warranty_claim(
                    claim["id"],
                    approve_claim_payload(
                        remedy_install_date="2026-09-15T00:00:00Z", remedy_outage_days=5
                    ),
                    make_platform_admin_headers("pa_boss"),
                )
            )

        assert approved["status"] == "APPROVED"
        assert approved["remedy_energy_add_mwh"] == pytest.approx(2.31, abs=0.01)

    def test_both_audit_identifiers_are_retained(self):
        """Filing and adjudication are recorded separately for audit.

        PRD: "The server records it where a transition names an audit field — `submitted_by_user_id` on an offer or a claim, `accepted_by_user_id` on an instruction, `opened_by_user_id` and `closed_by_user_id` on a safety event, `created_by_user_id` and `adjudicated_by_user_id` on a claim — but never compares it to any entity's `id`."

        Design: Corner/rbac/filer_cannot_adjudicate_their_own_warranty_claim_forbidden
        """
        _, claim = self._submitted_claim()
        get_success_data(
            api_client.adjudicate_warranty_claim(
                claim["id"],
                approve_claim_payload(
                    remedy_install_date="2026-09-15T00:00:00Z", remedy_outage_days=5
                ),
                make_platform_admin_headers("pa_boss"),
            )
        )

        after = refresh_claim(claim["id"])
        assert after["created_by_user_id"] == "am_filer"
        assert after["adjudicated_by_user_id"] == "pa_boss"


class TestEventOpenerCannotCloseTheSameEvent:
    """One role holds both duties, so only the user id separates them."""

    def _open_event(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        return open_safety_event(
            asset["id"],
            event_type="THERMAL_ANOMALY",
            severity="ADVISORY",
            detected_max_cell_temp_c=41.0,
            headers=OPENING_OFFICER,
        )

    def test_the_reporting_officer_is_recorded_on_the_event(self):
        """The recorded opener is what the closure check compares against.

        PRD: "A manually reported event is created with `source` of `MANUAL`, `status` of `OPEN`, `opened_by_user_id` set to the acting identifier, `suppression_discharged` false, `suppression_agent_kg` null, `emergency_response_ack_at` null, `emergency_ack_agencies` as an empty array, `responder_cleared` false, `closed_by_user_id` null, and `source_dispatch_id` and `source_sample_index` null."

        Design: Corner/rbac/safety_event_opener_cannot_close_the_same_event_forbidden
        """
        event = self._open_event()

        assert event["opened_by_user_id"] == "so_1"
        assert event["status"] == "OPEN"

    def test_the_reporting_officer_cannot_close_it(self):
        """Closure is the second officer's act, and the first officer is refused.

        PRD: "Closure is the second officer's act and has two divergent branches on the same action."

        Design: Corner/rbac/safety_event_opener_cannot_close_the_same_event_forbidden
        """
        event = self._open_event()

        validate_error(
            api_client.close_safety_event(
                event["id"], OPENING_OFFICER, {"responder_cleared": True}
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            expected_status=403,
        )
        assert refresh_safety_event(event["id"])["status"] == "OPEN"

    def test_a_second_officer_closes_it_and_is_recorded(self):
        """A different identifier satisfies the rule and is stored as the closer.

        PRD: "A successful closure sets `status` to `CLOSED`, records `closed_by_user_id` as the acting identifier, stores the supplied `emergency_response_ack_at`, and recomputes the asset's `safety_state` over the remaining non-closed events."

        Design: Corner/rbac/safety_event_opener_cannot_close_the_same_event_forbidden
        """
        event = self._open_event()
        validate_error(
            api_client.close_safety_event(
                event["id"], OPENING_OFFICER, {"responder_cleared": True}
            ),
            "ERR_SEGREGATION_OF_DUTIES",
        )

        closed = close_event(
            event["id"],
            headers=make_safety_officer_headers("so_2"),
            responder_cleared=True,
        )

        assert closed["status"] == "CLOSED"
        assert closed["closed_by_user_id"] == "so_2"


class TestUnauthenticatedRequestsAreRejectedFirst:
    """Priority 1 outranks the role check and the body check alike."""

    def test_a_read_without_headers_is_unauthenticated(self):
        """No identity at all is answered 401, never 403.

        PRD: "Both headers present and non-empty, with `X-User-Role` naming one of the seven roles — otherwise `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_or_unknown_auth_headers_are_unauthenticated
        """
        validate_error(
            api_client.list_storage_assets(NO_AUTH_HEADERS),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )

    def test_a_write_without_headers_is_unauthenticated_not_malformed(self):
        """Authentication is screened before the body is inspected at all.

        PRD: "Checks run in a fixed order, and the first failing check decides the response; no later check runs, and no partial write survives a rejection."

        Design: Corner/rbac/missing_or_unknown_auth_headers_are_unauthenticated
        """
        validate_error(
            api_client.create_storage_asset({}, NO_AUTH_HEADERS),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )

    def test_an_unknown_role_string_is_unauthenticated_not_forbidden(self):
        """A role outside the seven declared ones is not authenticated at all.

        PRD: "Both headers present and non-empty, with `X-User-Role` naming one of the seven roles — otherwise `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_or_unknown_auth_headers_are_unauthenticated
        """
        validate_error(
            api_client.list_storage_assets(UNKNOWN_ROLE_HEADERS),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )
