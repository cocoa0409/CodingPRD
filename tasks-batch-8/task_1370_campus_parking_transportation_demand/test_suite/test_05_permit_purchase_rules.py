"""Permit purchase gates: eligibility, plate windows, standing, credit, OCC,
and the state-vs-fiscal validation priority."""
from test_helpers import (
    ApiErrorId,
    create_allocation,
    create_lot,
    create_patron,
    get_allocation,
    get_allocation_version,
    make_commuter_headers,
    purchase_permit,
    setup_account_with_credit,
    setup_blocked_patron,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEligibility:
    def test_eligibility_role_mismatch_rejected(self, api):
        """PRD §3.3: "The patron's `campus_role` must appear in the
        allocation's `eligible_roles` and the patron's `residency` must
        satisfy the allocation's `residency_rule` (`ANY` accepts both
        residencies; `ON_CAMPUS_ONLY` requires `ON_CAMPUS`; `OFF_CAMPUS_ONLY`
        requires `OFF_CAMPUS`) — violations are rejected with
        `ERR_PATRON_INELIGIBLE` (HTTP 403)."

        Design: Corner/validations/eligibility_role_mismatch_rejected
        """
        patron = create_patron(full_name="S", campus_role="STUDENT",
                               residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="LS", name="Lot S")
        allocation = create_allocation(lot["id"], permit_code="FAC",
                                       eligible_roles=["FACULTY"], quota=5)
        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": allocation["id"],
                "plate_number": "S111",
                "expected_allocation_version": allocation["version"],
            },
            make_commuter_headers(patron["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PATRON_INELIGIBLE, 403)

    def test_residency_rule_mismatch_rejected(self, api):
        """PRD §3.3: "The patron's `campus_role` must appear in the
        allocation's `eligible_roles` and the patron's `residency` must
        satisfy the allocation's `residency_rule` (`ANY` accepts both
        residencies; `ON_CAMPUS_ONLY` requires `ON_CAMPUS`; `OFF_CAMPUS_ONLY`
        requires `OFF_CAMPUS`) — violations are rejected with
        `ERR_PATRON_INELIGIBLE` (HTTP 403)."

        Design: Corner/validations/residency_rule_mismatch_rejected
        """
        patron = create_patron(full_name="R", campus_role="STAFF",
                               residency="ON_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="LR", name="Lot R")
        allocation = create_allocation(lot["id"], permit_code="COMM",
                                       eligible_roles=["STAFF"],
                                       residency_rule="OFF_CAMPUS_ONLY", quota=5)
        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": allocation["id"],
                "plate_number": "R111",
                "expected_allocation_version": allocation["version"],
            },
            make_commuter_headers(patron["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PATRON_INELIGIBLE, 403)


class TestPlateWindowOverlap:
    def test_plate_overlap_inclusive_touching_rejected(self, api):
        """PRD §3.3: "The same `plate_number` may not be covered by more than
        one permit with status `ACTIVE` or `SUSPENDED` over any overlapping
        inclusive `[valid_from, valid_to]` window — a touching date counts as
        overlap. Violations are rejected with `ERR_DUPLICATE_ACTIVE_PERMIT`
        (HTTP 409)."
        PRD §2.7: "permit validity windows use inclusive `[valid_from,
        valid_to]` semantics where touching dates DO count as overlap."

        Design: Corner/validations/plate_overlap_inclusive_touching_rejected
        """
        patron = create_patron(full_name="K", campus_role="STUDENT",
                               residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="LK", name="Lot K")
        allocation = create_allocation(lot["id"], eligible_roles=["STUDENT"], quota=2)
        purchase_permit(patron["id"], allocation["id"], "K111")

        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": allocation["id"],
                "plate_number": "K111",
                "valid_from": "2026-11-22",  # touches the first permit's valid_to
                "expected_allocation_version": get_allocation_version(allocation["id"]),
            },
            make_commuter_headers(patron["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_PERMIT, 409)


class TestStandingGate:
    def test_blocked_patron_purchase_rejected(self, api):
        """PRD §3.3: "The patron's `standing` must be `GOOD_STANDING`; a
        `BLOCKED` patron is rejected with `ERR_PATRON_BLOCKED` (HTTP 402)."
        PRD §3.1: "`standing` flips to `BLOCKED` whenever
        `outstanding_balance_cents` reaches or exceeds `10000` cents, and
        returns to `GOOD_STANDING` when the balance falls back below that
        threshold."

        Design: Corner/validations/blocked_patron_purchase_rejected
        """
        ctx = setup_blocked_patron(name="X", plate="X666")
        allocation = ctx["allocation"]
        version = get_allocation_version(allocation["id"])
        resp = api.create_permit(
            {
                "patron_id": ctx["patron"]["id"],
                "allocation_id": allocation["id"],
                "plate_number": "X999",
                "expected_allocation_version": version,
            },
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PATRON_BLOCKED, 402)


class TestCreditGate:
    def test_credit_overdraw_rejected(self, api):
        """PRD §3.3.3: "If `apply_credit_cents` is supplied,
        `credit_applied_cents` is the smaller of `apply_credit_cents` and
        `fee_total_cents`; otherwise `credit_applied_cents` is `0`. The
        supplied `apply_credit_cents` must not exceed the patron's incentive
        `credit_balance_cents` — violations are rejected with
        `ERR_INSUFFICIENT_CREDIT` (HTTP 422), and the same error applies if
        the patron has no incentive account at all."

        Design: Corner/validations/credit_overdraw_rejected
        """
        ctx = setup_account_with_credit(name="M", blocks=1)  # 2500 cents of credit
        lot = create_lot(lot_code="LM", name="Lot M")
        allocation = create_allocation(lot["id"], eligible_roles=["STAFF"], quota=5)
        resp = api.create_permit(
            {
                "patron_id": ctx["patron"]["id"],
                "allocation_id": allocation["id"],
                "plate_number": "M111",
                "expected_allocation_version": get_allocation_version(allocation["id"]),
                "apply_credit_cents": 3000,
            },
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT, 422)


class TestPurchaseOcc:
    def test_occ_permit_purchase_stale_version_rejected(self, api, admin_headers):
        """PRD §2.6: "If `expected_allocation_version` does not match the
        allocation's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_permit_purchase_stale_version_rejected
        """
        patron_a = create_patron(full_name="A", campus_role="STUDENT",
                                 residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        patron_b = create_patron(full_name="B", campus_role="STUDENT",
                                 residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="LS", name="Lot S")
        allocation = create_allocation(lot["id"], eligible_roles=["STUDENT"], quota=5)
        observed_version = allocation["version"]

        first = api.create_permit(
            {
                "patron_id": patron_a["id"],
                "allocation_id": allocation["id"],
                "plate_number": "A111",
                "expected_allocation_version": observed_version,
            },
            admin_headers,
        )
        first_data = validate_success(first, 201)
        assert first_data["status"] == "ACTIVE"

        stale = api.create_permit(
            {
                "patron_id": patron_b["id"],
                "allocation_id": allocation["id"],
                "plate_number": "B111",
                "expected_allocation_version": observed_version,
            },
            admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)


class TestStateMasksFiscal:
    """Both defects present: allocation WAITLISTING (state tier) and patron
    BLOCKED (fiscal tier). The earlier tier's error is returned."""

    def _setup(self):
        ctx = setup_blocked_patron(name="X", plate="X666")
        # quota-1 allocation on the violation lot, filled by Y -> WAITLISTING
        other = create_patron(full_name="Y", campus_role="STAFF",
                              residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        alloc_b = create_allocation(ctx["violation_lot"]["id"], permit_code="GEN2",
                                    eligible_roles=["STAFF"], quota=1)
        purchase_permit(other["id"], alloc_b["id"], "Y111")
        return ctx, alloc_b

    def test_purchase_closed_allocation_masks_patron_blocked(self, api):
        """PRD §2.8: "Every write endpoint evaluates checks in a fixed
        priority order. A failure at an earlier tier masks later checks (the
        earlier error is the one returned)" — with "7. **Target resource
        state**" preceding "12. **Capacity & fiscal** — patron standing,
        credit balance, displacement capacity, route funding and seat
        coverage, redemption points. Fiscal checks always run after state and
        temporal checks."
        PRD §3.2: "New permit purchases against a `WAITLISTING` allocation are
        rejected with `ERR_ALLOCATION_NOT_OPEN` (HTTP 409); waitlist joins
        against an `OPEN` allocation are rejected with
        `ERR_ALLOCATION_NOT_WAITLISTING` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/purchase_allocation_closed_vs_patron_blocked
        """
        ctx, alloc_b = self._setup()
        version = get_allocation_version(alloc_b["id"])
        resp = api.create_permit(
            {
                "patron_id": ctx["patron"]["id"],
                "allocation_id": alloc_b["id"],
                "plate_number": "X777",
                "expected_allocation_version": version,
            },
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_OPEN, 409)

    def test_purchase_closed_allocation_creates_no_permit(self, api, admin_headers):
        """PRD §3.2: "New permit purchases against a `WAITLISTING` allocation
        are rejected with `ERR_ALLOCATION_NOT_OPEN` (HTTP 409); waitlist joins
        against an `OPEN` allocation are rejected with
        `ERR_ALLOCATION_NOT_WAITLISTING` (HTTP 409)."
        PRD §2.8: "A failure at an earlier tier masks later checks (the
        earlier error is the one returned)" — so even though the patron is
        BLOCKED, the rejection is the state error and no permit is created.

        Design: Difficulty/priority_pair_validation_conflict/purchase_allocation_closed_vs_patron_blocked
        """
        ctx, alloc_b = self._setup()
        version = get_allocation_version(alloc_b["id"])
        resp = api.create_permit(
            {
                "patron_id": ctx["patron"]["id"],
                "allocation_id": alloc_b["id"],
                "plate_number": "X777",
                "expected_allocation_version": version,
            },
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_OPEN, 409)

        permits, meta = validate_paginated(
            api.list_permits(admin_headers, params={"patron_id": ctx["patron"]["id"]})
        )
        assert meta["total_count"] == 1, (
            f"patron X must still hold exactly one permit (the original), "
            f"got {meta['total_count']}"
        )
        after = get_allocation(alloc_b["id"])
        assert after["allocated_count"] == 1 and after["status"] == "WAITLISTING", (
            "rejected purchase must not disturb the filled allocation"
        )


class TestPurchaseRequiresOpen:
    def _setup(self):
        v1 = create_patron(full_name="V1", campus_role="STUDENT",
                           residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        v2 = create_patron(full_name="V2", campus_role="STUDENT",
                           residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="LV", name="Lot V")
        allocation = create_allocation(lot["id"], eligible_roles=["STUDENT"], quota=1)
        purchase_permit(v1["id"], allocation["id"], "V111")
        return v2, allocation

    def test_purchase_on_waitlisting_allocation_rejected(self, api):
        """PRD §3.2: "New permit purchases against a `WAITLISTING` allocation
        are rejected with `ERR_ALLOCATION_NOT_OPEN` (HTTP 409); waitlist joins
        against an `OPEN` allocation are rejected with
        `ERR_ALLOCATION_NOT_WAITLISTING` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/permit_purchase_requires_allocation_open
        """
        v2, allocation = self._setup()
        version = get_allocation_version(allocation["id"])
        resp = api.create_permit(
            {
                "patron_id": v2["id"],
                "allocation_id": allocation["id"],
                "plate_number": "V222",
                "expected_allocation_version": version,
            },
            make_commuter_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_OPEN, 409)

    def test_waitlist_join_available_when_allocation_waitlisting(self, api):
        """PRD §3.4: "When an allocation is `WAITLISTING`, a `Commuter` (or
        `ParkingAdmin` on behalf of a patron) joins the queue by submitting
        `patron_id` and `allocation_id`." and "The new entry is created with
        status `WAITING`, `waiting_since` set to the current logical time,
        `decline_count` of `0`, and `requeue_count` of `0`."

        Design: Difficulty/cross_entity_state_dependency/permit_purchase_requires_allocation_open
        """
        v2, allocation = self._setup()
        resp = api.create_waitlist_entry(
            {"patron_id": v2["id"], "allocation_id": allocation["id"]},
            make_commuter_headers(v2["id"]),
        )
        entry = validate_success(resp, 201)
        assert entry["status"] == "WAITING", (
            f"the waitlist path must be available while WAITLISTING, got {entry['status']}"
        )
        assert entry["decline_count"] == 0 and entry["requeue_count"] == 0
