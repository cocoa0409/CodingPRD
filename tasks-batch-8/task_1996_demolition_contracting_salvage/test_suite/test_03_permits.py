"""Demolition permits: tiered fee, duplicate gate, review loop, renewal OCC,
expiry sweep, and the startup logical clock."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_permit_payload, create_utility_disconnect_payload,
    make_utility_coordinator_headers,
    create_project, create_confirmed_disconnect,
    set_clock, create_and_complete_survey,
    setup_demolition_active, create_debris_ticket_payload,
    assert_iso8601_instant,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]
AUTHORITY = TEST_USERS["authority_reviewer_headers"]
HAULER = TEST_USERS["hauling_dispatcher_headers"]


class TestPermitFee:
    def test_permit_fee_tier_evaluation_order(self):
        """PRD §3.3: "first, a provisional subtotal is computed as a 150,000-cent
        base fee plus 12 cents per square foot of `gross_floor_area_sqft`; second,
        the application is classified as `TIER2` when that provisional subtotal is
        at least 500,000 cents, and `TIER1` otherwise; third, the final
        `fee_cents` is assessed as the 150,000-cent base plus the area multiplied
        by the tier's per-square-foot rate — 12 cents for `TIER1`, 18 cents for
        `TIER2` — plus, only for `TIER2`, a flat 25,000-cent surcharge. The tier
        is always selected by the provisional subtotal computed at the base rate,
        never by the final fee."

        Design: Difficulty/combinatorial_formula/permit_fee_tier_evaluation_order
        """
        pa = create_project(name="Fee A", address="1 A St", lot_area_sqft=90000)
        pb = create_project(name="Fee B", address="2 B St", lot_area_sqft=90000)
        pc = create_project(name="Fee C", address="3 C St", lot_area_sqft=90000)
        pd = create_project(name="Fee D", address="4 D St", lot_area_sqft=90000)

        fee_a = get_success_data(
            api_client.create_permit(pa["id"], create_permit_payload(
                permit_number="P-A", gross_floor_area_sqft=20000), PERMIT)
        )["fee_cents"]
        fee_b = get_success_data(
            api_client.create_permit(pb["id"], create_permit_payload(
                permit_number="P-B", gross_floor_area_sqft=30000), PERMIT)
        )["fee_cents"]
        fee_c = get_success_data(
            api_client.create_permit(pc["id"], create_permit_payload(
                permit_number="P-C", gross_floor_area_sqft=29166), PERMIT)
        )["fee_cents"]
        fee_d = get_success_data(
            api_client.create_permit(pd["id"], create_permit_payload(
                permit_number="P-D", gross_floor_area_sqft=29167), PERMIT)
        )["fee_cents"]

        # TIER1: provisional 390000 < 500000.
        assert fee_a == 390000
        # TIER2: provisional 510000 >= 500000 -> 150000 + 30000*18 + 25000.
        assert fee_b == 715000
        # Provisional 499992 < 500000 -> stays TIER1 even though a final-fee
        # check would round up.
        assert fee_c == 499992
        # Provisional 500004 >= 500000 -> TIER2: 150000 + 29167*18 + 25000.
        assert fee_d == 700006

    def test_permit_fee_computed_at_creation_and_pinned(self):
        """PRD §3.3: "The assessed `fee_cents` is computed at creation and never
        changes afterward."
        PRD §3.3: "second, the application is classified as `TIER2` when that
        provisional subtotal is at least 500,000 cents, and `TIER1` otherwise"

        Design: Difficulty/combinatorial_formula/permit_fee_tier_evaluation_order
        """
        project = create_project(name="FeePin", address="5 F St", lot_area_sqft=90000)
        created = get_success_data(
            api_client.create_permit(
                project["id"],
                create_permit_payload(permit_number="P-F", gross_floor_area_sqft=30000),
                PERMIT,
            )
        )
        assert created["fee_cents"] == 715000
        get_success_data(api_client.transition_permit(created["id"], {"action": "SUBMIT"}, PERMIT))
        listed = get_success_data(api_client.list_permits(project["id"], PERMIT))
        assert listed[0]["fee_cents"] == 715000, "fee must not change after creation"


class TestPermitLifecycle:
    def test_duplicate_active_permit_rejected(self):
        """PRD §3.3: "A project may hold at most one permit outside the terminal
        states at any moment: creating an application, or submitting a draft,
        while another permit of the same project sits in `DRAFT`, `UNDER_REVIEW`,
        `REVISION_REQUIRED`, `APPROVED`, or `ACTIVE` is rejected with
        `ERR_DUPLICATE_ACTIVE_PERMIT`."

        Design: Corner/validations/duplicate_active_permit_rejected
        """
        project = create_project(name="Dup", address="56 Pine St", lot_area_sqft=12000)
        pm1 = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(permit_number="P-1",
                                                     gross_floor_area_sqft=15000), PERMIT)
        )
        resp = api_client.create_permit(
            project["id"], create_permit_payload(permit_number="P-2",
                                                 gross_floor_area_sqft=9000), PERMIT
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_PERMIT)
        get_success_data(api_client.transition_permit(pm1["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm1["id"], {"action": "REJECT"}, AUTHORITY))
        ok = api_client.create_permit(
            project["id"], create_permit_payload(permit_number="P-3",
                                                 gross_floor_area_sqft=9000), PERMIT
        )
        data = validate_success(ok, expected_status=201)
        assert isinstance(data["id"], str)

    def test_permit_transition_from_rejected_rejected(self):
        """PRD §3.3: "an `AuthorityReviewer` approves it to `APPROVED`, rejects it
        to the terminal `REJECTED`, or sends it back to `REVISION_REQUIRED`"
        PRD §2.9: "the entity's state machine allows the requested transition
        from its current state ... violations surface as `ERR_INVALID_STATE`"

        Design: Corner/state_machines/permit_transition_from_rejected_rejected
        """
        project = create_project(name="Term", address="22 Pine St", lot_area_sqft=12000)
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(permit_number="P-T",
                                                     gross_floor_area_sqft=10000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "REJECT"}, AUTHORITY))
        resp = api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_permit_activate_with_zero_disconnects_rejected(self):
        """PRD §3.3: "a `PermitCoordinator` activates an `APPROVED` permit only
        when the project has at least one utility disconnect and every one of
        them stands at `disconnect_status` `REPORTED_DISCONNECTED` with
        `verification_status` `CONFIRMED` — otherwise the activation is rejected
        with `ERR_UTILITY_UNVERIFIED`."

        Design: Corner/validations/permit_activate_with_zero_disconnects_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="NoDisc", address="54 Pine St", lot_area_sqft=12000)
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(gross_floor_area_sqft=15000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        resp = api_client.transition_permit(pm["id"], {"action": "ACTIVATE"}, PERMIT)
        validate_error(resp, ApiErrorId.ERR_UTILITY_UNVERIFIED)
        listed = get_success_data(api_client.list_permits(project["id"], PERMIT))
        assert listed[0]["status"] == "APPROVED"

    def test_permit_activate_requires_all_utilities_confirmed(self):
        """PRD §3.3: "a `PermitCoordinator` activates an `APPROVED` permit only
        when the project has at least one utility disconnect and every one of
        them stands at `disconnect_status` `REPORTED_DISCONNECTED` with
        `verification_status` `CONFIRMED` — otherwise the activation is rejected
        with `ERR_UTILITY_UNVERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/permit_activate_requires_all_utilities_confirmed
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="Act Lot", address="69 Elm St", lot_area_sqft=20000)
        ud = get_success_data(
            api_client.create_utility_disconnect(
                project["id"],
                create_utility_disconnect_payload(
                    utility_type="SEWER", provider_name="City Sewer",
                    disconnect_window_start="2026-08-03T08:00:00Z",
                    disconnect_window_end="2026-08-03T10:00:00Z",
                ),
                TEST_USERS["utility_coordinator_headers"],
            )
        )
        get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "REPORT_DISCONNECTED"},
                make_utility_coordinator_headers("pa-r-1"),
            )
        )
        get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "VERIFY"}, make_utility_coordinator_headers("pa-v-1")
            )
        )
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(gross_floor_area_sqft=15000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        # FIELD_VERIFIED is not CONFIRMED.
        resp = api_client.transition_permit(pm["id"], {"action": "ACTIVATE"}, PERMIT)
        validate_error(resp, ApiErrorId.ERR_UTILITY_UNVERIFIED)
        listed = get_success_data(api_client.list_permits(project["id"], PERMIT))
        assert listed[0]["status"] == "APPROVED"

    def test_permit_activate_succeeds_when_utilities_confirmed(self):
        """PRD §3.3: "Activation stamps `activated_at` from the logical clock and
        sets `expires_at` to exactly 90 days later."

        Design: Difficulty/cross_entity_state_dependency/permit_activate_requires_all_utilities_confirmed
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="ActOk", address="69B Elm St", lot_area_sqft=20000)
        create_confirmed_disconnect(project["id"])
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(gross_floor_area_sqft=15000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        active = get_success_data(api_client.transition_permit(pm["id"], {"action": "ACTIVATE"}, PERMIT))
        assert active["status"] == "ACTIVE"
        assert_iso8601_instant(active["activated_at"], "2026-08-01T09:00:00Z")
        assert_iso8601_instant(active["expires_at"], "2026-10-30T09:00:00Z")


class TestPermitRenewal:
    def _active_permit(self):
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="OCC2", address="15 Role St", lot_area_sqft=12000)
        create_confirmed_disconnect(project["id"], utility_type="GAS")
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(gross_floor_area_sqft=15000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        pm = get_success_data(api_client.transition_permit(pm["id"], {"action": "ACTIVATE"}, PERMIT))
        return project, pm

    def test_occ_permit_renewal_stale_version_rejected(self):
        """PRD §2.6: "The permit-renewal operation — `POST
        /demolition/permits/{id}/renewals` — likewise requires
        `expected_permit_version` matching the permit's current `version`. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A renewal
        legitimately extends the prior expiry, so a subsequent renewal carrying
        the up-to-date version succeeds; only a stale `expected_permit_version`
        is rejected."
        PRD §3.3: "An `ACTIVE` permit can be renewed by a `PermitCoordinator`,
        extending `expires_at` by a further 90 days per renewal and incrementing
        `renewal_count` by 1; each renewal increments the permit's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_permit_renewal_stale_version_rejected
        """
        _, pm = self._active_permit()
        listed = get_success_data(api_client.list_permits(pm["project_id"], PERMIT))
        observed_version = listed[0]["version"]
        first = get_success_data(
            api_client.renew_permit(pm["id"], {"expected_permit_version": observed_version}, PERMIT)
        )
        assert_iso8601_instant(first["expires_at"], "2027-01-28T09:00:00Z")
        assert first["renewal_count"] == 1
        assert first["version"] == observed_version + 1
        stale = api_client.renew_permit(
            pm["id"], {"expected_permit_version": observed_version}, PERMIT
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_success_data(
            api_client.renew_permit(pm["id"], {"expected_permit_version": first["version"]}, PERMIT)
        )
        assert_iso8601_instant(fresh["expires_at"], "2027-04-28T09:00:00Z")
        assert fresh["renewal_count"] == 2

    def test_permit_renewal_from_approved_rejected_invalid_state(self):
        """PRD §3.3: "Attempting to renew an `EXPIRED` permit is rejected with
        `ERR_PERMIT_EXPIRED`; attempting it from `DRAFT`, `UNDER_REVIEW`,
        `REVISION_REQUIRED`, `APPROVED`, or `REJECTED` is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/cross_cutting_layers/occ_permit_renewal_stale_version_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="RenBad", address="15B Role St", lot_area_sqft=12000)
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(gross_floor_area_sqft=15000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        listed = get_success_data(api_client.list_permits(project["id"], PERMIT))
        resp = api_client.renew_permit(
            pm["id"], {"expected_permit_version": listed[0]["version"]}, PERMIT
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPermitExpiry:
    def test_error_permit_expired_on_renewal(self):
        """PRD §3.3: "The permit expiry sweep — run whenever the logical clock is
        set, and again on any permit or project interaction — moves every `ACTIVE`
        permit whose `expires_at` is strictly before the current logical time to
        the terminal `EXPIRED`."
        PRD §3.3: "Attempting to renew an `EXPIRED` permit is rejected with
        `ERR_PERMIT_EXPIRED`"

        Design: Corner/errors/error_permit_expired_on_renewal
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="ExpRen", address="88 Pine St", lot_area_sqft=12000)
        create_confirmed_disconnect(project["id"], utility_type="GAS")
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(gross_floor_area_sqft=15000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "ACTIVATE"}, PERMIT))
        set_clock("2026-10-31T00:00:00Z")
        listed = get_success_data(api_client.list_permits(project["id"], PERMIT))
        assert listed[0]["status"] == "EXPIRED"
        resp = api_client.renew_permit(
            pm["id"], {"expected_permit_version": listed[0]["version"]}, PERMIT
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_EXPIRED)

    def test_permit_expiry_cascade_cancels_manifested_tickets(self):
        """PRD §3.3: "Expiry cascades into the project: a project sitting in
        `RELEASED` or `DEMOLITION_ACTIVE` when its permit expires falls back to
        `PRECONDITIONS_PENDING`"
        PRD §3.8: "A ticket never reaches `CANCELLED` by client action:
        cancellation is the system cascade that strikes every `MANIFESTED` ticket
        when the project's permit expires under `DEMOLITION_ACTIVE` — per ticket,
        `in_transit_tons` falls by the `gross_tons` and `removed_tons` rises by
        it, as the project falls back to `PRECONDITIONS_PENDING`."

        Design: Difficulty/transitive_cascade/permit_expiry_cascade_cancels_manifested_tickets
        """
        ctx = setup_demolition_active(name="Cascade B", address="17 Elm St",
                                      required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        tk = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(
                    ticket_number="T-9", facility_type="TRANSFER", gross_tons=6.0), HAULER)
        )
        # Permit was activated at 2026-08-01T09:00:00Z -> expires 2026-10-30T09:00:00Z.
        set_clock("2026-10-30T09:00:01Z")
        permits = get_success_data(api_client.list_permits(pid, PERMIT))
        assert permits[0]["status"] == "EXPIRED"
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["status"] == "PRECONDITIONS_PENDING"
        tickets = get_success_data(api_client.list_debris_tickets(pid, HAULER))
        assert tickets[0]["status"] == "CANCELLED"
        assert tickets[0]["id"] == tk["id"]
        assert project["in_transit_tons"] == 0
        assert project["removed_tons"] == 6.0

    def test_permit_not_expired_at_exact_expiry_instant(self):
        """PRD §3.3: "The boundary is strict: a permit whose `expires_at` equals
        the current time exactly is still valid."
        PRD §3.3: "moves every `ACTIVE` permit whose `expires_at` is strictly
        before the current logical time to the terminal `EXPIRED`."

        Design: Difficulty/transitive_cascade/permit_expiry_cascade_cancels_manifested_tickets
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="SweepEdge", address="88B Pine St", lot_area_sqft=12000)
        create_confirmed_disconnect(project["id"], utility_type="GAS")
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(gross_floor_area_sqft=15000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "ACTIVATE"}, PERMIT))
        # Exactly at expires_at: still ACTIVE (strict inequality).
        set_clock("2026-10-30T09:00:00Z")
        listed = get_success_data(api_client.list_permits(project["id"], PERMIT))
        assert listed[0]["status"] == "ACTIVE"

    def test_default_clock_value_before_any_set(self):
        """PRD §2.4: "On server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."
        PRD §3.3: "Activation stamps `activated_at` from the logical clock and
        sets `expires_at` to exactly 90 days later."

        Design: Corner/endpoints/default_clock_value_before_any_set
        """
        project = create_project(name="ClockDef", address="82 Pine St", lot_area_sqft=12000)
        create_confirmed_disconnect(project["id"], utility_type="WATER")
        pm = get_success_data(
            api_client.create_permit(
                project["id"], create_permit_payload(gross_floor_area_sqft=15000), PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        active = get_success_data(api_client.transition_permit(pm["id"], {"action": "ACTIVATE"}, PERMIT))
        assert_iso8601_instant(active["activated_at"], "2026-08-01T00:00:00Z")
        assert_iso8601_instant(active["expires_at"], "2026-10-30T00:00:00Z")
