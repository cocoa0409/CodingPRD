"""Fed order lifecycle: initial state, submit guards, recall cycle, cancel,
advice dispute cycle, and immediate consistency of the submit response."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_fed_order,
    create_draft_order_with_line,
    create_fed_order_payload,
    create_received_order_shipment,
    create_carrier,
    create_staffed_site,
    create_submitted_order,
    get_success_data,
    get_site,
    validate_error,
)


class TestInitialState:
    def test_new_order_is_draft_with_zeroed_totals(self, api):
        """PRD §3.2: "First an empty `FedOrder` is created with its `site_id`, a
        `direction` of `ORDER` (cash coming in from the Fed) or `DEPOSIT` (cash
        going out to the Fed), and a `business_date` on which the order settles;
        it starts in `DRAFT` with version 1."
        PRD §3.2: "Every line's face value `line_cents` is computed exactly as its
        denomination times 100 notes per strap times its strap count, and the
        order's `face_total_cents` is the plain integer sum of all line values —
        zero lines means a face total of zero."

        Design: Corner/state_machines/fed_order_initial_state_draft
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        order = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=ctx["site"]["id"],
                    direction="ORDER",
                    business_date="2026-08-03",
                ),
                coord,
            )
        )
        assert_fed_order(order)
        assert order["status"] == "DRAFT"
        assert order["face_total_cents"] == 0
        assert order["fee_total_cents"] == 0
        assert order["advice_count"] == 0
        assert order["version"] == 1


class TestRecallCycle:
    def test_submit_recall_resubmit_cycle_releases_and_reacquires_pending(self, api):
        """PRD §3.2: "A successful submission increments the order's version, and
        for an `ORDER` it adds the face total to the site's
        `pending_inbound_order_cents`, re-deriving the site's totals and posture
        and incrementing the site version."
        PRD §3.2: "While in `SUBMITTED`, the coordinator may still recall the order
        — `SUBMITTED → DRAFT` — which releases the pending-inbound exposure for an
        `ORDER` and allows editing and resubmission; or record the Fed's
        acknowledgement — `SUBMITTED → ACKNOWLEDGED`."

        Design: Difficulty/non_linear_state_machine/fed_order_submit_recall_cycle
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        order = create_draft_order_with_line(
            site_id, coord, direction="ORDER", business_date="2026-08-03"
        )
        assert order["version"] == 2, (
            f"create (1) + one line add must give version 2, got {order['version']}"
        )
        submitted = get_success_data(api.submit_fed_order(order["id"], coord))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["version"] == 3
        assert get_site(site_id)["pending_inbound_order_cents"] == 2000000

        recalled = get_success_data(api.recall_fed_order(order["id"], coord))
        assert recalled["status"] == "DRAFT"
        assert recalled["version"] == 4
        assert get_site(site_id)["pending_inbound_order_cents"] == 0, (
            "recall must release the pending-inbound exposure"
        )

        resubmitted = get_success_data(api.submit_fed_order(order["id"], coord))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["version"] == 5
        assert get_site(site_id)["pending_inbound_order_cents"] == 2000000

    def test_recall_releases_pending_exposure_while_draft(self, api):
        """PRD §3.2: "While in `SUBMITTED`, the coordinator may still recall the
        order — `SUBMITTED → DRAFT` — which releases the pending-inbound exposure
        for an `ORDER` and allows editing and resubmission; or record the Fed's
        acknowledgement — `SUBMITTED → ACKNOWLEDGED`."

        Design: Difficulty/non_linear_state_machine/fed_order_submit_recall_cycle
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        order = create_submitted_order(
            site_id, coord, direction="ORDER", business_date="2026-08-03"
        )
        assert get_site(site_id)["pending_inbound_order_cents"] == order["face_total_cents"]
        recalled = get_success_data(api.recall_fed_order(order["id"], coord))
        assert recalled["status"] == "DRAFT"
        site = get_site(site_id)
        assert site["pending_inbound_order_cents"] == 0
        # Editing is possible again while DRAFT: a further line add succeeds.
        get_success_data(
            api.add_denomination_line(
                order["id"],
                {
                    "denomination_cents": 2000,
                    "strap_count": 10,
                    "expected_fed_order_version": recalled["version"],
                },
                coord,
            )
        )
        final = get_success_data(api.get_fed_order(order["id"], coord))
        assert final["face_total_cents"] == 4000000


class TestRecallFromDraftRejected:
    def test_recall_only_defined_from_submitted(self, api):
        """PRD §3.2: "While in `SUBMITTED`, the coordinator may still recall the
        order — `SUBMITTED → DRAFT` — which releases the pending-inbound exposure
        for an `ORDER` and allows editing and resubmission; or record the Fed's
        acknowledgement — `SUBMITTED → ACKNOWLEDGED`."
        PRD §5: "ERR_FED_ORDER_INVALID_STATE | 409"

        Design: Corner/state_machines/recall_from_draft_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        order = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=ctx["site"]["id"],
                    direction="ORDER",
                    business_date="2026-08-03",
                ),
                coord,
            )
        )
        resp = api.recall_fed_order(order["id"], coord)
        validate_error(resp, ApiErrorId.ERR_FED_ORDER_INVALID_STATE)
        after = get_success_data(api.get_fed_order(order["id"], coord))
        assert after["status"] == "DRAFT"


class TestCutoff:
    def test_submit_after_cutoff_rejected_and_future_date_admitted(self, api):
        """PRD §3.2: "The submission cutoff is strict: the current logical clock
        must be earlier than 18:00:00Z on the day before the order's
        `business_date`, or the submission is rejected with
        `ERR_ORDER_CUTOFF_PASSED` (HTTP 422)."
        PRD §2.4: "The logical clock starts at exactly 2026-08-01T00:00:00Z before
        any call is made, and a `CashOperationsAdmin` advances it via an
        admin-only test-driving capability that sets the current instant to a
        supplied `to_iso8601` value."

        Design: Corner/validations/order_submit_after_cutoff_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        # business_date == clock date (2026-08-01): the cutoff (2026-07-31T18:00Z)
        # is already past at the default clock.
        o1 = create_draft_order_with_line(
            site_id, coord, direction="ORDER", business_date="2026-08-01"
        )
        resp = api.submit_fed_order(o1["id"], coord)
        validate_error(resp, ApiErrorId.ERR_ORDER_CUTOFF_PASSED)
        assert get_success_data(api.get_fed_order(o1["id"], coord))["status"] == "DRAFT"

        # business_date 2026-08-03: cutoff 2026-08-02T18:00Z is still ahead.
        o2 = create_draft_order_with_line(
            site_id, coord, direction="ORDER", business_date="2026-08-03"
        )
        submitted = get_success_data(api.submit_fed_order(o2["id"], coord))
        assert submitted["status"] == "SUBMITTED"


class TestSubmitBlockedByFrozenVault:
    def test_submit_rejected_with_vault_frozen_when_born_at_limit(self, api):
        """PRD §2.9: "The posture is `FROZEN` when `on_hand_total_cents` is greater
        than or equal to `vault_limit_cents`, or when `insurance_headroom_cents`
        is less than or equal to zero, or when the site holds any counterfeit case
        still in `SEIZED` status whose `seized_at` is more than 10 days before the
        current logical clock."
        PRD §2.9: "A `FROZEN` posture blocks three operations — Fed order
        submission, shipment loading, and fitness batch creation — each rejected
        with `ERR_VAULT_FROZEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/fed_order_submit_blocked_by_frozen_vault
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "vault_limit_cents": 10000000,
                "insurance_coverage_cents": 50000000,
                "opening_fit_cents": 10000000,
            },
        )
        assert ctx["site"]["posture"] == "FROZEN", (
            f"site born with on_hand_total == vault_limit must be FROZEN, "
            f"got {ctx['site']['posture']}"
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        order = create_draft_order_with_line(
            ctx["site"]["id"], coord, direction="ORDER", business_date="2026-08-03"
        )
        resp = api.submit_fed_order(order["id"], coord)
        validate_error(resp, ApiErrorId.ERR_VAULT_FROZEN)
        assert get_success_data(api.get_fed_order(order["id"], coord))["status"] == "DRAFT"

    def test_submit_on_normal_site_with_lines_succeeds(self, api):
        """PRD §3.2: "The site's posture must not be `FROZEN`."
        PRD §2.9: "A `FROZEN` posture blocks three operations — Fed order
        submission, shipment loading, and fitness batch creation — each rejected
        with `ERR_VAULT_FROZEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/fed_order_submit_blocked_by_frozen_vault
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        assert ctx["site"]["posture"] == "NORMAL"
        coord = ctx["staff"]["coordinator"]["headers"]
        order = create_draft_order_with_line(
            ctx["site"]["id"], coord, direction="ORDER", business_date="2026-08-03"
        )
        submitted = get_success_data(api.submit_fed_order(order["id"], coord))
        assert submitted["status"] == "SUBMITTED"


class TestDepositSufficiency:
    def test_deposit_face_above_cash_on_hand_rejected(self, api):
        """PRD §3.2: "For a `DEPOSIT`, the face total must not exceed the site's
        combined fit plus unfit cash on hand — deposits draw from the `UNFIT`
        bucket first and then the `FIT` bucket — failing with
        `ERR_INSUFFICIENT_CASH_FOR_DEPOSIT` (HTTP 422)."

        Design: Corner/validations/deposit_exceeding_cash_on_hand_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 100000, "opening_unfit_cents": 50000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        order = create_draft_order_with_line(
            ctx["site"]["id"],
            coord,
            direction="DEPOSIT",
            business_date="2026-08-03",
            denomination_cents=100,
            strap_count=20,
        )
        assert order["face_total_cents"] == 200000
        resp = api.submit_fed_order(order["id"], coord)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CASH_FOR_DEPOSIT)
        assert get_success_data(api.get_fed_order(order["id"], coord))["status"] == "DRAFT"


class TestAdviceDisputeCycle:
    def test_basis_relative_deltas_net_to_zero(self, api):
        """PRD §3.2: "Each advice resets `settled_basis_cents` to the advice's
        `counted_total_cents`, and the effective basis for the next comparison is
        `settled_basis_cents` when set, otherwise `face_total_cents`. When the
        delta between an advice's counted total and the effective basis is
        nonzero, that signed delta posts an `ADJUSTMENT` ledger entry in the `FIT`
        bucket value-dated to the current clock date; the ledger append then
        triggers the site on-hand recompute, and that recompute cascades to a
        reconciliation refresh and posture re-derivation per §2.10."
        PRD §3.2: "recording an advice with a `counted_total_cents` equal to the
        order's `face_total_cents` moves it to the terminal `RECONCILED` state,
        while a mismatched count moves it `RECEIVED → DISPUTED`."

        Design: Corner/endpoints/fed_advice_dispute_cycle_adjusts_basis
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 5000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]
        carrier = create_carrier()

        bundle = create_received_order_shipment(
            site_id,
            coord,
            carrier["id"],
            direction="DEPOSIT",
            business_date="2026-08-03",
        )
        order = bundle["order"]
        assert order["status"] == "RECEIVED"
        site_mid = get_site(site_id)
        assert site_mid["on_hand_fit_cents"] == 3000000, (
            f"outbound load must debit fit to 3,000,000, got {site_mid['on_hand_fit_cents']}"
        )

        disputed = get_success_data(
            api.record_fed_advice(order["id"], {"counted_total_cents": 1800000}, coord)
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["settled_basis_cents"] == 1800000
        site_after_dispute = get_site(site_id)
        assert site_after_dispute["on_hand_fit_cents"] == 2800000, (
            f"the -200,000 delta must book against fit, got {site_after_dispute['on_hand_fit_cents']}"
        )

        reconciled = get_success_data(
            api.record_fed_advice(order["id"], {"counted_total_cents": 2000000}, coord)
        )
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["settled_basis_cents"] == 2000000
        assert reconciled["advice_count"] == 2
        site_end = get_site(site_id)
        assert site_end["on_hand_fit_cents"] == 3000000, (
            "basis-relative deltas must net to zero across the dispute cycle, "
            f"got {site_end['on_hand_fit_cents']}"
        )


class TestImmediateConsistency:
    def test_submit_response_carries_final_state_and_totals(self, api):
        """PRD §2.10: "Whenever a ledger entry is appended, the owning site's
        totals re-derive, its posture re-derives, and any matching reconciliation
        in `OPEN` or `COUNTED` status refreshes its final expected balance and
        variance — which may flip its status, as described in §3.8."
        PRD §3.2: "A successful submission increments the order's version, and for
        an `ORDER` it adds the face total to the site's
        `pending_inbound_order_cents`, re-deriving the site's totals and posture
        and incrementing the site version."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_consistency_submit_response_final
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]
        order = create_draft_order_with_line(
            site_id, coord, direction="ORDER", business_date="2026-08-03"
        )
        response = get_success_data(api.submit_fed_order(order["id"], coord))
        # The submit response itself must already carry the final state and totals.
        assert response["status"] == "SUBMITTED"
        assert response["face_total_cents"] == 2000000
        assert response["fee_total_cents"] == 12500, (
            f"round_half_up(2,000,000 / 160) must be 12,500, got {response['fee_total_cents']}"
        )
        assert response["grand_total_cents"] == 2012500
        site = get_site(site_id)
        assert site["pending_inbound_order_cents"] == 2000000, (
            "pending inbound must be visible immediately after the submit response"
        )


class TestMissingAndInvalidFields:
    def test_missing_direction_rejected(self, api):
        """PRD §2.8: "When a request fails several rules at once, the server
        reports the first failure in a fixed evaluation order: authentication
        context first (missing or invalid headers, then role permission, then
        site-scope or carrier ownership), then existence of path identifiers
        validated left-to-right along the URL, then existence of body-referenced
        foreign keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`,
        `fitness_batch_id`), then request shape and uniqueness
        (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum
        members, or an end date before its start date), then the target
        resource's own state machine, then cross-entity state guards, then
        segregation-of-duties checks, then business rules (insurance headroom,
        cutoff and scheduling windows, denomination mix, fiscal sufficiency)."
        PRD §3.2: "First an empty `FedOrder` is created with its `site_id`, a
        `direction` of `ORDER` (cash coming in from the Fed) or `DEPOSIT` (cash
        going out to the Fed), and a `business_date` on which the order settles;
        it starts in `DRAFT` with version 1."

        Design: Corner/entities/fed_order_missing_required_direction
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        resp = api.create_fed_order(
            {"site_id": ctx["site"]["id"], "business_date": "2026-08-03"}, coord
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_direction_enum_rejected(self, api):
        """PRD §3.2: "First an empty `FedOrder` is created with its `site_id`, a
        `direction` of `ORDER` (cash coming in from the Fed) or `DEPOSIT` (cash
        going out to the Fed), and a `business_date` on which the order settles;
        it starts in `DRAFT` with version 1."
        PRD §2.8: "When a request fails several rules at once, the server reports
        the first failure in a fixed evaluation order: authentication context
        first (missing or invalid headers, then role permission, then site-scope
        or carrier ownership), then existence of path identifiers validated
        left-to-right along the URL, then existence of body-referenced foreign
        keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`,
        `fitness_batch_id`), then request shape and uniqueness
        (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum
        members, or an end date before its start date), then the target
        resource's own state machine, then cross-entity state guards, then
        segregation-of-duties checks, then business rules (insurance headroom,
        cutoff and scheduling windows, denomination mix, fiscal sufficiency)."

        Design: Corner/entities/fed_order_invalid_enum_direction
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        resp = api.create_fed_order(
            {
                "site_id": ctx["site"]["id"],
                "direction": "SIDEWAYS",
                "business_date": "2026-08-03",
            },
            coord,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestBundleMultiple:
    def test_order_direction_requires_bundle_multiples_deposit_does_not(self, api):
        """PRD §3.2: "For an `ORDER`-direction request the bundle rules of the Fed
        apply: denominations of 2000 cents or below must be requested in multiples
        of 10 straps, and denominations of 5000 cents or above in multiples of 5
        straps; a `DEPOSIT` accepts any strap count of at least 1. A bad
        denomination, a strap count below 1, or a bundle-multiple violation is
        rejected with `ERR_INVALID_DENOMINATION_MIX` (HTTP 422)."

        Design: Corner/validations/order_bundle_multiple_violation_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        o1 = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=site_id, direction="ORDER", business_date="2026-08-03"
                ),
                coord,
            )
        )
        resp = api.add_denomination_line(
            o1["id"],
            {
                "denomination_cents": 2000,
                "strap_count": 3,
                "expected_fed_order_version": o1["version"],
            },
            coord,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DENOMINATION_MIX)

        o2 = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=site_id, direction="DEPOSIT", business_date="2026-08-03"
                ),
                coord,
            )
        )
        line = get_success_data(
            api.add_denomination_line(
                o2["id"],
                {
                    "denomination_cents": 2000,
                    "strap_count": 3,
                    "expected_fed_order_version": o2["version"],
                },
                coord,
            )
        )
        assert line["line_cents"] == 600000


class TestNotFound:
    def test_get_nonexistent_fed_order(self, api):
        """PRD §2.8: "Path-parameter identifiers that do not resolve produce the
        resource-specific not-found error — for example `ERR_VAULT_SITE_NOT_FOUND`,
        `ERR_FED_ORDER_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND` — each at HTTP 404."

        Design: Corner/entities/get_nonexistent_fed_order_returns_not_found
        """
        admin = TEST_USERS["admin_headers"]
        create_staffed_site()
        resp = api.get_fed_order("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin)
        validate_error(resp, ApiErrorId.ERR_FED_ORDER_NOT_FOUND)
