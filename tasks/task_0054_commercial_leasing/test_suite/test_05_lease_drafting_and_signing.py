"""Lease drafting, signing preconditions, reservation flow.

PRD §3.3.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_audit_event,
    assert_deposit,
    assert_lease,
    create_approved_tenant,
    create_building,
    create_lease,
    create_lease_payload,
    create_tenant,
    create_unit,
    finish_renovation,
    list_audit_events,
    make_stepped_entry,
    reserve_unit,
    reserve_unit_payload,
    setup_building_with_unit,
    setup_draft_lease,
    setup_signed_lease,
    setup_active_lease,
    sign_lease,
    start_renovation,
    advance_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    LA,
)


# ===========================================================================
# Reservation
# ===========================================================================
class TestReservation:
    """PRD §3.3: 'When a tenant has expressed intent for a specific
    vacant unit, a LeasingAgent may attach a soft reservation by
    supplying the tenant_id to the reserve action on a unit. The
    unit's status moves from VACANT to RESERVED.'
    """

    def test_reserve_vacant_unit_moves_to_reserved(self, api):
        """PRD §3.3: 'The unit's status moves from VACANT to RESERVED.'"""
        b, u = setup_building_with_unit()
        t = create_approved_tenant()
        res = api.reserve_unit(
            b["id"], u["id"], reserve_unit_payload(tenant_id=t["id"]),
            LA,
        )
        data = validate_success(res)
        assert data["status"] == "RESERVED"

    def test_reserve_non_vacant_unit_rejected(self, api):
        """PRD §3.3: 'The reservation is rejected with
        ERR_INVALID_STATE unless the unit is presently VACANT.'"""
        b, u = setup_building_with_unit()
        # Advance clock so the renovation interval is active and the
        # unit's derived status becomes UNDER_RENOVATION (not VACANT).
        advance_clock("2026-03-01T00:00:00.000Z")
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        t = create_approved_tenant()
        res = api.reserve_unit(
            b["id"], u["id"], reserve_unit_payload(tenant_id=t["id"]),
            LA,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_release_blocked_by_draft_lease(self, api):
        """PRD §3.3: 'release is rejected with ERR_LEASE_DEPENDENCY if
        a DRAFT or SIGNED lease still references this unit.'"""
        ctx = setup_draft_lease()
        # The lease in ctx is DRAFT — first reserve, then attempt release.
        building = ctx["building"]
        unit = ctx["unit"]
        # Reserve via API for the tenant.
        reserve_unit(building["id"], unit["id"], ctx["tenant"]["id"])
        # Try to release — DRAFT lease still references this unit.
        res = api.release_reservation(building["id"], unit["id"], LA)
        validate_error(res, ApiErrorId.ERR_LEASE_DEPENDENCY.value)


# ===========================================================================
# Lease drafting
# ===========================================================================
class TestLeaseDrafting:
    """PRD §3.3: 'A leasing agent drafts a lease by supplying the
    unit_id and tenant_id, a start_date and end_date defining the
    half-open window [start_date, end_date) (end strictly later than
    start), a base_monthly_rent_cents for year 1, an escalation_mode
    drawn from NONE, ANNUAL, BIENNIAL, or STEPPED ...'
    """

    def test_draft_lease_starts_in_draft(self, api):
        """PRD §3.3: 'The newly drafted lease is persisted with status
        DRAFT, terminated_on null, and amendment_count zero.'"""
        b, u = setup_building_with_unit()
        t = create_approved_tenant()
        res = api.create_lease(
            create_lease_payload(
                unit_id=u["id"], tenant_id=t["id"],
                start_date="2026-01-01T00:00:00.000Z",
                end_date="2026-12-01T00:00:00.000Z",
                base_monthly_rent_cents=100000,
                escalation_mode="NONE",
                deposit_months=1,
            ),
            LA,
        )
        data = validate_success(res, expected_status=201)
        assert_lease(data)
        assert data["status"] == "DRAFT"
        assert data["terminated_on"] is None
        assert data["amendment_count"] == 0

    def test_draft_lease_with_nonexistent_unit_rejected(self, api):
        """PRD §2.7: 'foreign keys carried in request bodies ...
        unresolved bodies are rejected with ERR_NOT_FOUND before any
        business validation runs.'"""
        t = create_approved_tenant()
        res = api.create_lease(
            create_lease_payload(
                unit_id=NON_EXISTENT_UUID, tenant_id=t["id"],
                start_date="2026-01-01T00:00:00.000Z",
                end_date="2026-12-01T00:00:00.000Z",
                base_monthly_rent_cents=100000,
            ),
            LA,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_draft_stepped_schedule_invalid_first_entry(self, api):
        """PRD §3.3: 'Stepped schedule rows must be ... the first row's
        effective_from must equal the lease's start_date.'"""
        b, u = setup_building_with_unit()
        t = create_approved_tenant()
        res = api.create_lease(
            create_lease_payload(
                unit_id=u["id"], tenant_id=t["id"],
                start_date="2026-01-01T00:00:00.000Z",
                end_date="2026-12-01T00:00:00.000Z",
                base_monthly_rent_cents=100000,
                escalation_mode="STEPPED",
                # First effective_from is 2026-02-01, NOT equal to start_date
                stepped_schedule=[
                    make_stepped_entry(
                        effective_from="2026-02-01T00:00:00.000Z",
                        monthly_rent_cents=100000,
                    ),
                ],
                deposit_months=1,
            ),
            LA,
        )
        validate_error(res, ApiErrorId.ERR_STEPPED_SCHEDULE_INVALID.value)

    def test_draft_stepped_schedule_invalid_not_ascending(self, api):
        """PRD §3.3: 'rows must be strictly ascending in effective_from'."""
        b, u = setup_building_with_unit()
        t = create_approved_tenant()
        res = api.create_lease(
            create_lease_payload(
                unit_id=u["id"], tenant_id=t["id"],
                start_date="2026-01-01T00:00:00.000Z",
                end_date="2026-12-01T00:00:00.000Z",
                base_monthly_rent_cents=100000,
                escalation_mode="STEPPED",
                stepped_schedule=[
                    make_stepped_entry(
                        effective_from="2026-01-01T00:00:00.000Z",
                        monthly_rent_cents=100000,
                    ),
                    make_stepped_entry(
                        # Equal to previous — not strictly ascending.
                        effective_from="2026-01-01T00:00:00.000Z",
                        monthly_rent_cents=110000,
                    ),
                ],
                deposit_months=1,
            ),
            LA,
        )
        validate_error(res, ApiErrorId.ERR_STEPPED_SCHEDULE_INVALID.value)


# ===========================================================================
# Lease signing
# ===========================================================================
class TestLeaseSigning:
    """PRD §3.3: 'Signing a drafted lease moves it from DRAFT to
    SIGNED. ... On success, the lease's status becomes SIGNED, a
    Deposit row is created with required_cents equal to deposit_months
    × base_monthly_rent_cents, with collected_cents zero, with
    adjustment_status AT_REST, and with frozen_status UNFROZEN. The
    unit cascades to LEASED, the per-month rent ledger is generated as
    described below, and an AuditEvent with subject_kind LEASE and
    action CONTRACT_SIGNED is recorded.'
    """

    def test_sign_draft_lease_transitions_to_signed(self, api):
        """PRD §3.3: 'Signing a drafted lease moves it from DRAFT to
        SIGNED. ... the lease's status becomes SIGNED.'"""
        ctx = setup_draft_lease()
        res = api.sign_lease(ctx["lease"]["id"], LA)
        data = validate_success(res)
        assert data["status"] == "SIGNED"

    def test_sign_creates_deposit_row_with_required_cents(self, api):
        """PRD §3.3: 'a Deposit row is created with required_cents equal
        to deposit_months × base_monthly_rent_cents, with collected_cents
        zero, with adjustment_status AT_REST, and with frozen_status
        UNFROZEN.'"""
        ctx = setup_signed_lease(
            deposit_months=3, base_monthly_rent_cents=100000,
        )
        deposit = ctx["deposit"]
        assert_deposit(deposit)
        assert deposit["required_cents"] == 3 * 100000
        assert deposit["collected_cents"] == 0
        assert deposit["adjustment_status"] == "AT_REST"
        assert deposit["frozen_status"] == "UNFROZEN"

    def test_sign_cascades_unit_to_leased(self, api):
        """PRD §2.6: 'Whenever a Lease transitions from DRAFT to
        SIGNED, the bound Unit is forced to LEASED.'"""
        ctx = setup_signed_lease()
        from test_helpers import get_unit
        unit = get_unit(ctx["building"]["id"], ctx["unit"]["id"])
        assert unit["status"] == "LEASED"

    def test_sign_emits_contract_signed_audit_event(self, api):
        """PRD §3.3: 'an AuditEvent with subject_kind LEASE and action
        CONTRACT_SIGNED is recorded.'"""
        ctx = setup_signed_lease()
        rows = list_audit_events(
            subject_kind="LEASE", subject_id=ctx["lease"]["id"],
            action="CONTRACT_SIGNED",
        )
        assert len(rows) >= 1
        for r in rows:
            assert_audit_event(r)
            assert r["subject_kind"] == "LEASE"
            assert r["action"] == "CONTRACT_SIGNED"

    def test_sign_with_unapproved_tenant_rejected(self, api):
        """PRD §3.3: 'The signing endpoint is rejected with
        ERR_TENANT_NOT_APPROVED unless the lease's tenant has
        qualification_status APPROVED.'"""
        b, u = setup_building_with_unit()
        t_pending = create_tenant()  # PENDING_REVIEW
        lease = create_lease(
            unit_id=u["id"], tenant_id=t_pending["id"],
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000,
            deposit_months=1,
        )
        res = api.sign_lease(lease["id"], LA)
        validate_error(res, ApiErrorId.ERR_TENANT_NOT_APPROVED.value)

    def test_sign_already_signed_lease_rejected(self, api):
        """PRD §2.10 priority 5: 'state-machine preconditions ... fail
        with ERR_INVALID_STATE'. A SIGNED lease cannot be re-signed."""
        ctx = setup_signed_lease()
        res = api.sign_lease(ctx["lease"]["id"], LA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_sign_with_renovation_overlap_rejected(self, api):
        """PRD §3.3: 'with ERR_RENOVATION_LEASE_CONFLICT if the unit's
        current renovation interval — when extended by one buffer day
        at its end — overlaps the lease window.'

        We stamp a renovation interval that is in the past relative to
        the server clock so that the unit's derived status is VACANT
        (the renovation no longer falls inside the current date per
        PRD §3.1) — that lets the sign request pass the unit-
        availability gate and exercise the renovation-overlap check.
        PRD §3.1 says finish_renovation clears both dates, so we do
        NOT finish: the stored interval must remain on the unit for
        the overlap rule to apply.
        """
        b, u = setup_building_with_unit()
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        # Advance the logical clock to a date past renovation_end_date
        # so the unit's derived status is VACANT and the sign request
        # reaches the renovation-overlap check.
        advance_clock("2026-04-01T00:00:00.000Z")
        t = create_approved_tenant()
        # Lease starts on 2026-03-10, inside renovation interval.
        lease = create_lease(
            unit_id=u["id"], tenant_id=t["id"],
            start_date="2026-03-10T00:00:00.000Z",
            end_date="2026-09-10T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(lease["id"], LA)
        validate_error(res, ApiErrorId.ERR_RENOVATION_LEASE_CONFLICT.value)

    def test_sign_with_lease_overlap_rejected(self, api):
        """PRD §3.3: 'with ERR_LEASE_OVERLAP if any other lease on the
        same unit whose status is SIGNED, ACTIVE, AMENDMENT_PENDING, or
        TERMINATING has an interval that overlaps the half-open window
        of this lease.'"""
        b, u = setup_building_with_unit()
        t1 = create_approved_tenant()
        # First lease occupies [2026-01-01, 2026-06-01)
        l1 = create_lease(
            unit_id=u["id"], tenant_id=t1["id"],
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-06-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        sign_lease(l1["id"])
        # Second lease attempts to sign overlapping window.
        t2 = create_approved_tenant()
        l2 = create_lease(
            unit_id=u["id"], tenant_id=t2["id"],
            start_date="2026-05-15T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(l2["id"], LA)
        validate_error(res, ApiErrorId.ERR_LEASE_OVERLAP.value)

    def test_sign_with_adjacent_window_allowed(self, api):
        """PRD §3.3: '(note: adjacency where the end_date of one lease
        equals the start_date of another is permitted and does not
        count as overlap).'"""
        b, u = setup_building_with_unit()
        t1 = create_approved_tenant()
        l1 = create_lease(
            unit_id=u["id"], tenant_id=t1["id"],
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-06-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        sign_lease(l1["id"])
        t2 = create_approved_tenant()
        l2 = create_lease(
            unit_id=u["id"], tenant_id=t2["id"],
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        res = api.sign_lease(l2["id"], LA)
        data = validate_success(res)
        assert data["status"] == "SIGNED"
