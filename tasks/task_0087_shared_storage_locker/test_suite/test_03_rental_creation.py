"""Rental creation, snapshot, and validation-ordering tests (PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    DECLARED_VALUE_CAP_CENTS,
    api_client,
    assert_rental,
    assert_rental_total_charged_on_create,
    create_active_rental,
    create_pricing_profile,
    create_rental_payload,
    drive_cabinet_offline,
    make_renter_headers,
    open_repair_ticket,
    rent_k_compartments,
    setup_basic_rental,
    setup_cabinet_with_compartment,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rental creation — happy path (PRD §3.2)
# ===========================================================================
class TestRentalCreationHappyPath:

    def test_create_active_rental_initial_state(self, api):
        """PRD §3.2: "On success the rental record is minted with status =
        ACTIVE, started_at set to the request time ... renewal_count is
        zero, ended_at and reminder_sent_at are null, and overdue_fee_cents,
        deposit_forfeited_cents, and deposit_refunded_cents are zero."

        Claim: a freshly created rental has ACTIVE / counters 0 / nulls.
        """
        ctx = setup_basic_rental()
        r = ctx["rental"]
        assert_rental(r)
        assert r["status"] == "ACTIVE"
        assert r["renewal_count"] == 0
        assert r["ended_at"] in (None,)
        assert r["reminder_sent_at"] in (None,)
        assert r["overdue_fee_cents"] == 0
        assert r["deposit_forfeited_cents"] == 0
        assert r["deposit_refunded_cents"] == 0
        assert r["renter_id"] == ctx["renter_id"]

    def test_snapshot_pinned_from_pricing_profile(self, api):
        """PRD §3.2: "the server resolves the active PricingProfile for
        (compartment.size_class, request rental_mode) and snapshots the
        canonical values onto the rental as unit_price_cents_snapshot,
        deposit_cents_snapshot, grace_minutes_snapshot, overdue_rate_snapshot,
        and forced_clearance_hours_snapshot."

        Claim: snapshot fields equal the profile's canonical values
        (the body-echoed values are ignored).
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            pricing_overrides={
                "unit_price_cents": 700,
                "deposit_cents": 3000,
                "grace_minutes": 20,
                "overdue_rate_cents_per_hour": 250,
                "forced_clearance_hours": 36,
            },
        )
        payload = create_rental_payload(
            unit_price_cents=999,  # lie about the price
            deposit_cents=1,
            grace_minutes=1,
            overdue_rate_cents_per_hour=1,
            forced_clearance_hours=1,
        )
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-snapshot"),
        )
        r = validate_success(resp, expected_status=201)
        assert r["unit_price_cents_snapshot"] == 700
        assert r["deposit_cents_snapshot"] == 3000
        assert r["grace_minutes_snapshot"] == 20
        assert r["overdue_rate_snapshot"] == 250
        assert r["forced_clearance_hours_snapshot"] == 36

    def test_rental_fee_equals_billing_units_times_unit_price(self, api):
        """PRD §3.2: "The rental fee at creation is computed as
        billing_units multiplied by unit_price_cents_snapshot, expressed
        in integer cents."

        Claim: billing_units=3, unit_price=500 → rental_fee_cents=1500.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            pricing_overrides={"unit_price_cents": 500},
        )
        rental, _ = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-fee",
            billing_units=3,
        )
        assert rental["rental_fee_cents"] == 1500

    def test_total_charged_is_fee_plus_premium_plus_deposit(self, api):
        """PRD §3.4: "The total charged at creation is the rental fee plus
        the insurance premium plus the deposit snapshot, stored as
        total_charged_cents."

        Claim: total_charged_cents equals
        rental_fee_cents + insurance_premium_cents + deposit_cents_snapshot.
        """
        ctx = setup_basic_rental(
            insurance_tier="BASIC",
            declared_value_cents=500_000,
            billing_units=1,
        )
        assert_rental_total_charged_on_create(ctx["rental"])


# ===========================================================================
# Pricing-profile resolution (PRD §3.2)
# ===========================================================================
class TestPricingProfileResolution:

    def test_missing_pricing_profile_returns_not_found(self, api):
        """PRD §3.2: "If no profile exists for the pair the request is
        rejected with ERR_PRICING_PROFILE_NOT_FOUND."

        Claim: requesting a rental with rental_mode=MONTHLY when only a
        HOURLY profile exists → ERR_PRICING_PROFILE_NOT_FOUND.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="HOURLY",
        )
        payload = create_rental_payload(rental_mode="MONTHLY")
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-no-profile"),
        )
        validate_error(resp,
                       ApiErrorId.ERR_PRICING_PROFILE_NOT_FOUND.value)


# ===========================================================================
# Compartment fault gating (PRD §3.2, §3.8)
# ===========================================================================
class TestCompartmentFaultGate:

    def test_rental_blocked_when_compartment_is_fault(self, api):
        """PRD §3.2: "the compartment's operational_status must be OK
        (otherwise ERR_COMPARTMENT_FAULT)."
        PRD §3.8: "The compartment's operational_status cascades from
        OK to FAULT and its fault_category is set; the compartment is
        now locked out from new rentals (rental-creation requests
        against it are rejected with ERR_COMPARTMENT_FAULT)."

        Claim: a compartment in FAULT rejects new rentals with
        ERR_COMPARTMENT_FAULT.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        open_repair_ticket(comps[0]["id"], fault_category="DOOR_NOT_CLOSED")
        payload = create_rental_payload()
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-fault"),
        )
        validate_error(resp, ApiErrorId.ERR_COMPARTMENT_FAULT.value)


# ===========================================================================
# Compartment occupancy gating (PRD §3.2)
# ===========================================================================
class TestCompartmentOccupancyGate:

    def test_second_rental_on_occupied_compartment_rejected(self, api):
        """PRD §3.2: "the compartment's occupancy_status must be IDLE
        (otherwise ERR_COMPARTMENT_UNAVAILABLE)."

        Claim: a second rental on a RENTED compartment →
        ERR_COMPARTMENT_UNAVAILABLE.
        """
        ctx = setup_basic_rental(renter_id="renter-a")
        payload = create_rental_payload()
        resp = api.create_rental(
            ctx["cabinet"]["id"], ctx["compartment"]["id"], payload,
            make_renter_headers("renter-b"),
        )
        validate_error(resp, ApiErrorId.ERR_COMPARTMENT_UNAVAILABLE.value)


# ===========================================================================
# Cabinet OFFLINE gating (PRD §3.1)
# ===========================================================================
class TestCabinetOfflineGate:

    def test_offline_rejects_qr(self, api):
        """PRD §3.1: "while OFFLINE, any IDLE compartment in the cabinet
        remains rentable only via the PASSWORD unlock channel, and
        rental attempts that supply QR or BLUETOOTH are rejected with
        ERR_CABINET_OFFLINE."

        Claim: OFFLINE cabinet + QR channel → ERR_CABINET_OFFLINE.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="HOURLY",
        )
        drive_cabinet_offline(cabinet["id"])
        payload = create_rental_payload(unlock_channel="QR")
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-offline-qr"),
        )
        validate_error(resp, ApiErrorId.ERR_CABINET_OFFLINE.value)

    def test_offline_rejects_bluetooth(self, api):
        """PRD §3.1: "rental attempts that supply QR or BLUETOOTH are
        rejected with ERR_CABINET_OFFLINE."

        Claim: OFFLINE cabinet + BLUETOOTH channel → ERR_CABINET_OFFLINE.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="HOURLY",
        )
        drive_cabinet_offline(cabinet["id"])
        payload = create_rental_payload(unlock_channel="BLUETOOTH")
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-offline-bt"),
        )
        validate_error(resp, ApiErrorId.ERR_CABINET_OFFLINE.value)

    def test_offline_accepts_password(self, api):
        """PRD §3.1: "while OFFLINE, any IDLE compartment in the cabinet
        remains rentable only via the PASSWORD unlock channel."

        Claim: OFFLINE cabinet + PASSWORD channel → 201 success.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="HOURLY",
        )
        drive_cabinet_offline(cabinet["id"])
        payload = create_rental_payload(unlock_channel="PASSWORD")
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-offline-pw"),
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Insurance coherence (PRD §3.4)
# ===========================================================================
class TestInsuranceCoherence:

    def test_none_tier_with_positive_declared_rejected(self, api):
        """PRD §3.4: "When insurance_tier is NONE, the renter must supply
        declared_value_cents = 0 ... Any of: a NONE rental with non-zero
        declared value, a BASIC or PREMIUM rental with zero declared
        value, or a declared value above the cap, are rejected with
        ERR_INVALID_INSURANCE."

        Claim: NONE + declared_value_cents=10 → ERR_INVALID_INSURANCE.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        payload = create_rental_payload(
            insurance_tier="NONE", declared_value_cents=10,
        )
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-ins-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INSURANCE.value)

    def test_basic_tier_with_zero_declared_rejected(self, api):
        """PRD §3.4: "a BASIC or PREMIUM rental with zero declared value
        ... [is] rejected with ERR_INVALID_INSURANCE."

        Claim: BASIC + declared_value_cents=0 → ERR_INVALID_INSURANCE.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        payload = create_rental_payload(
            insurance_tier="BASIC", declared_value_cents=0,
        )
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-ins-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INSURANCE.value)

    def test_declared_above_cap_rejected(self, api):
        """PRD §3.4: "when insurance_tier is BASIC or PREMIUM, the renter
        must supply declared_value_cents strictly greater than zero and
        no greater than the declared-value cap of 10,000,000 cents."
        PRD §3.4: "a declared value above the cap, are rejected with
        ERR_INVALID_INSURANCE."

        Claim: declared_value_cents = cap + 1 → ERR_INVALID_INSURANCE.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        payload = create_rental_payload(
            insurance_tier="BASIC",
            declared_value_cents=DECLARED_VALUE_CAP_CENTS + 1,
        )
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-ins-3"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INSURANCE.value)


# ===========================================================================
# Billing units validation (PRD §3.2)
# ===========================================================================
class TestBillingUnits:

    @pytest.mark.parametrize("bad_units", [0, -1])
    def test_billing_units_less_than_one_rejected(self, api, bad_units):
        """PRD §3.2: "billing_units (the number of hours, days, or months
        purchased upfront, which must be at least one)."

        Claim: billing_units in {0, -1} → ERR_BAD_REQUEST.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment()
        payload = create_rental_payload(billing_units=bad_units)
        resp = api.create_rental(
            cabinet["id"], comps[0]["id"], payload,
            make_renter_headers("renter-billing"),
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)


# ===========================================================================
# Side effects of rental creation (PRD §3.2)
# ===========================================================================
class TestRentalCreationSideEffects:

    def test_compartment_transitions_to_rented(self, api, operator_headers):
        """PRD §3.2: "The compartment's occupancy_status transitions to
        RENTED, active_rental_id is set."

        Claim: after rental creation, the compartment is RENTED with
        active_rental_id set to the rental's id.
        """
        ctx = setup_basic_rental()
        from test_helpers import api_client
        fresh = validate_success(api_client.get_compartment(
            ctx["cabinet"]["id"], ctx["compartment"]["id"], operator_headers,
        ))
        assert fresh["occupancy_status"] == "RENTED"
        assert fresh["active_rental_id"] == ctx["rental"]["id"]

    def test_rental_creation_emits_audit_event(self, api, operator_headers):
        """PRD §3.2: "an AuditEvent of event_kind COMPARTMENT_OPENED is
        emitted carrying the unlock_channel."

        Claim: GET /audit-events lists at least one COMPARTMENT_OPENED
        for the rental's compartment with the right unlock_channel.
        """
        ctx = setup_basic_rental(unlock_channel="QR")
        resp = api.list_audit_events(operator_headers, params={
            "event_kind": "COMPARTMENT_OPENED",
            "subject_id": ctx["compartment"]["id"],
        })
        body = resp.json()
        rows = body["data"]
        assert len(rows) >= 1, "Expected at least one COMPARTMENT_OPENED audit row"
        # At least one row carries unlock_channel=QR.
        assert any(r.get("unlock_channel") == "QR" for r in rows), (
            "Expected at least one row with unlock_channel='QR'"
        )

    def test_rental_creation_emits_rental_fee_revenue_record(self, api,
                                                             operator_headers):
        """PRD §3.2: "a RevenueRecord with revenue_kind = RENTAL_FEE is
        written with the row-level partner split described in §2.12."

        Claim: GET /revenue-records lists a RENTAL_FEE row for the rental.
        """
        ctx = setup_basic_rental()
        resp = api.list_revenue_records(operator_headers, params={
            "cabinet_id": ctx["cabinet"]["id"],
            "revenue_kind": "RENTAL_FEE",
        })
        rows = resp.json()["data"]
        assert any(r.get("rental_id") == ctx["rental"]["id"] for r in rows), (
            "Expected a RENTAL_FEE RevenueRecord for the new rental"
        )
