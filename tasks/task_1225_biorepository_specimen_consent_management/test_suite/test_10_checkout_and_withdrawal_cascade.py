"""Checkout gates and the consent-withdrawal cascade; fulfill/cancel quota invariant."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    ADMIN_HEADERS,
    COORD_HEADERS,
    LAB_HEADERS,
    create_donor_with_consent,
    create_unit_with_slot,
    create_stored_specimen,
    create_aliquot_for,
    create_active_agreement,
    create_approved_request,
    setup_reserved_aliquot,
    set_clock_to,
    run_sweep,
    ingest_reading,
    get_aliquot,
    get_agreement,
    get_request,
    get_specimen,
    get_consent,
    make_researcher_headers,
)


class TestConsentWithdrawalCascadeDepth4:
    """Withdrawal finalization cascade: consent -> specimens -> aliquots -> requests
    and agreements, with a destruction order auto-created per specimen."""

    def _setup_and_sweep(self, api):
        env = setup_reserved_aliquot(volume_needed_ml=40.0, aliquot_volume_ml=40.0,
                                     specimen_volume_ml=100.0, agreement_total_ml=1000.0)
        # Withdraw as the consent coordinator, then finalize at the grace deadline.
        validate_success(api.withdraw_consent(env["consent"]["id"], {}, COORD_HEADERS),
                         expected_status=200)
        set_clock_to("2026-05-04T00:00:00Z")  # grace_deadline == 2026-05-04T00:00:00Z
        sweep = run_sweep()
        return env, sweep

    def test_cascade_flips_specimen_and_aliquot_to_destruction_pending(self, api):
        """PRD §3.9: "**Depth 1 — specimens.** Every specimen of the consent's donor
        whose `lifecycle_status` is `ACCESSIONED` or `IN_STORAGE` flips to
        `DESTRUCTION_PENDING`, and one destruction order is auto-created per such
        specimen: reason `CONSENT_WITHDRAWAL`, `created_by_user_id` recorded as
        "system", and `consent_record_id` set to the withdrawn consent."
        PRD §3.9: "**Depth 2 — aliquots and keys.** Every aliquot of those specimens
        whose status is `IN_STORAGE`, `RESERVED`, or `QUARANTINED` flips to
        `DESTRUCTION_PENDING`, and every `ACTIVE` de-identification key referencing an
        affected specimen flips to `REVOKED`."

        Design: Difficulty/transitive_cascade/consent_withdrawal_cascade_depth4
        """
        env, sweep = self._setup_and_sweep(api)
        assert sweep["withdrawals_finalized"] == 1, "deadline is inclusive"
        assert get_consent(env["consent"]["id"])["status"] == "WITHDRAWN"
        assert get_specimen(env["specimen"]["id"])["lifecycle_status"] == "DESTRUCTION_PENDING"
        assert get_aliquot(env["aliquot"]["id"])["status"] == "DESTRUCTION_PENDING"

    def test_cascade_compromises_request_and_rebalances_agreement(self, api):
        """PRD §3.9: "**Depth 3 — requests and agreements.** For each flipped aliquot
        that had been `RESERVED`, the reserving sample request flips from `APPROVED` to
        `COMPROMISED`, and its sharing agreement's ledger is rebalanced as release
        compensation — `reserved_volume_ml` decreases by that request's
        `charged_volume_ml` while `remaining_volume_ml` increases by the same amount."

        Design: Difficulty/transitive_cascade/consent_withdrawal_cascade_depth4
        """
        env, sweep = self._setup_and_sweep(api)
        assert get_request(env["request"]["id"])["status"] == "COMPROMISED"
        agreement = get_agreement(env["agreement"]["id"])
        assert agreement["reserved_volume_ml"] == pytest.approx(0.0)
        assert agreement["remaining_volume_ml"] == pytest.approx(1000.0)
        orders = validate_success(
            api.list_destruction_orders(
                ADMIN_HEADERS, params={"consent_record_id": env["consent"]["id"]}))
        assert len(orders) == 1, f"exactly one auto-created order expected, got {len(orders)}"
        assert orders[0]["reason"] == "CONSENT_WITHDRAWAL"
        assert orders[0]["status"] == "PENDING"


class TestCheckoutRequiresUnitOperational:
    """Checkout gate on the housing unit's posture."""

    def _setup_reserved_then_warning(self, api):
        env = setup_reserved_aliquot(
            volume_needed_ml=40.0, aliquot_volume_ml=40.0, specimen_volume_ml=100.0,
            unit_overrides={"warn_threshold_c": -70.0, "fail_threshold_c": -60.0})
        # A reading strictly above the warn threshold puts the unit into WARNING.
        ingest_reading(env["unit"]["id"], "2026-05-03T00:00:00Z", -69.9)
        return env

    def test_checkout_blocked_when_unit_warning(self, api):
        """PRD §3.7: "and the storage unit housing the aliquot's slot must have
        `posture` `OPERATIONAL`, failing as `ERR_UNIT_NOT_OPERATIONAL`."

        Design: Difficulty/cross_entity_state_dependency/checkout_requires_unit_operational
        """
        env = self._setup_reserved_then_warning(api)
        resp = api.checkout_aliquot(env["aliquot"]["id"],
                                    {"request_id": env["request"]["id"]}, LAB_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_OPERATIONAL)

    def test_warning_posture_does_not_quarantine_reserved_aliquot(self, api):
        """PRD §3.4: "Declaration moves the unit's `posture` from `OPERATIONAL` or
        `WARNING` to `FAILURE` and fires the contingency cascade: every slot of the
        unit flips from `AVAILABLE` to `OFFLINE`; every `BOOKED` reservation on those
        slots whose `ends_at` is still in the future is `CANCELLED`; every aliquot
        housed in the unit's slots and currently `IN_STORAGE` flips to `QUARANTINED`"

        Design: Difficulty/cross_entity_state_dependency/checkout_requires_unit_operational
        """
        env = self._setup_reserved_then_warning(api)
        resp = api.checkout_aliquot(env["aliquot"]["id"],
                                    {"request_id": env["request"]["id"]}, LAB_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_OPERATIONAL)
        aliquot = get_aliquot(env["aliquot"]["id"])
        assert aliquot["status"] == "RESERVED", (
            "the WARNING posture alone must not quarantine or release the aliquot")


class TestCheckoutStateVsConsentScope:
    """When checkout violates both the reservation-state rule and consent scope, the
    reservation-state error is returned."""

    def _setup(self, api):
        donor, consent = create_donor_with_consent(permitted_uses=["GENERAL_RESEARCH"])
        _, slot = create_unit_with_slot(unit_code="FRZ-PC1")
        specimen, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                             initial_volume_ml=100.0)
        aliquot, _ = create_aliquot_for(specimen["id"], 40.0, storage_slot_id=slot["id"])
        agreement = create_active_agreement(
            total_committed_volume_ml=1000.0,
            scope_uses=["GENERAL_RESEARCH", "GENETIC_ANALYSIS"])
        request_1 = create_approved_request(agreement["id"], researcher_id="researcher-1",
                                            volume_needed_ml=40.0)
        validate_success(api.fulfill_sample_request(request_1["id"], {}, ADMIN_HEADERS),
                         expected_status=200)
        # RQ2 requires GENETIC_ANALYSIS: scope-covered by the agreement but not by the
        # specimen's consent; it is APPROVED but never fulfilled.
        request_2 = create_approved_request(agreement["id"], researcher_id="researcher-2",
                                            required_uses=["GENETIC_ANALYSIS"],
                                            volume_needed_ml=40.0)
        return aliquot, request_1, request_2

    def test_checkout_for_other_request_reports_state_error(self, api):
        """PRD §3.7: "Its checks run in order: the aliquot must be `RESERVED` and its
        `reserved_for_request_id` must equal the payload's `request_id`, failing as
        `ERR_ALIQUOT_NOT_RESERVED_FOR_REQUEST` (HTTP 409); the request must be
        `APPROVED`, failing as `ERR_REQUEST_NOT_APPROVED`; the specimen's consent must
        be `ACTIVE`, failing as `ERR_CONSENT_NOT_ACTIVE`; scope coverage must hold
        against the request's `required_uses`, failing as `ERR_CONSENT_SCOPE_VIOLATION`"

        Design: Difficulty/priority_pair_validation_conflict/checkout_state_vs_consent_scope
        """
        aliquot, _, request_2 = self._setup(api)
        resp = api.checkout_aliquot(aliquot["id"], {"request_id": request_2["id"]},
                                    LAB_HEADERS)
        validate_error(resp, ApiErrorId.ERR_ALIQUOT_NOT_RESERVED_FOR_REQUEST)

    def test_failed_checkout_leaves_reservation_intact(self, api):
        """PRD §3.3: "The `reserved_for_request_id` field links a `RESERVED` aliquot to
        the sample request holding it — set by fulfillment, cleared by release or
        checkout, and null at all other times."

        Design: Difficulty/priority_pair_validation_conflict/checkout_state_vs_consent_scope
        """
        aliquot, request_1, request_2 = self._setup(api)
        resp = api.checkout_aliquot(aliquot["id"], {"request_id": request_2["id"]},
                                    LAB_HEADERS)
        validate_error(resp, ApiErrorId.ERR_ALIQUOT_NOT_RESERVED_FOR_REQUEST)
        aliquot = get_aliquot(aliquot["id"])
        assert aliquot["status"] == "RESERVED"
        assert aliquot["reserved_for_request_id"] == request_1["id"]


class TestFulfillCancelQuotaInvariant:
    """Conserved contractual quota across fulfill (forward) and cancel (compensating)."""

    def test_fulfill_moves_quota_from_remaining_to_reserved(self, api):
        """PRD §3.5: "From then on the ledger invariant holds at all times:
        `remaining_volume_ml` is always `total_committed_volume_ml` minus
        `reserved_volume_ml` minus `fulfilled_volume_ml`, where the reserved figure is
        quota debited at fulfillment but not yet checked out and the fulfilled figure
        is quota consumed by completed checkouts."

        Design: Difficulty/compensating_invariant/fulfill_cancel_quota_invariant
        """
        env = setup_reserved_aliquot(volume_needed_ml=40.0, aliquot_volume_ml=40.0,
                                     agreement_total_ml=1000.0)
        agreement = get_agreement(env["agreement"]["id"])
        assert agreement["remaining_volume_ml"] == pytest.approx(960.0)
        assert agreement["reserved_volume_ml"] == pytest.approx(40.0)
        assert agreement["fulfilled_volume_ml"] == pytest.approx(0.0)
        # 1000 == 960 + 40 + 0

    def test_cancel_restores_quota_and_releases_aliquot(self, api):
        """PRD §3.6: "From `APPROVED`, cancellation additionally performs the release
        compensation of §3.7: every aliquot `RESERVED` for the request returns to
        `IN_STORAGE` with its `reserved_for_request_id` cleared, and the agreement's
        ledger is rebalanced — its `reserved_volume_ml` decreases by the request's
        `charged_volume_ml` while its `remaining_volume_ml` increases by the same
        amount."

        Design: Difficulty/compensating_invariant/fulfill_cancel_quota_invariant
        """
        env = setup_reserved_aliquot(volume_needed_ml=40.0, aliquot_volume_ml=40.0,
                                     agreement_total_ml=1000.0)
        resp = api.cancel_sample_request(
            env["request"]["id"], {},
            make_researcher_headers(env["researcher_id"]))
        validate_success(resp, expected_status=200)
        agreement = get_agreement(env["agreement"]["id"])
        assert agreement["remaining_volume_ml"] == pytest.approx(1000.0)
        assert agreement["reserved_volume_ml"] == pytest.approx(0.0)
        assert agreement["fulfilled_volume_ml"] == pytest.approx(0.0)
        # 1000 == 1000 + 0 + 0, fully compensated
        aliquot = get_aliquot(env["aliquot"]["id"])
        assert aliquot["status"] == "IN_STORAGE"
        assert aliquot["reserved_for_request_id"] is None
        assert get_request(env["request"]["id"])["status"] == "CANCELLED"
