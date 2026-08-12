"""Fulfillment: selector determinism, quota charge tiers, fee rounding, priority order."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    ADMIN_HEADERS,
    create_donor_with_consent,
    create_unit_with_slot,
    create_stored_specimen,
    create_aliquot_for,
    create_active_agreement,
    create_approved_request,
    checkout_reserved_aliquot,
    setup_reserved_aliquot,
    set_clock_to,
    run_sweep,
    get_aliquot,
    get_agreement,
    get_request,
    get_specimen,
)


def _fulfill(api, request_id):
    return api.fulfill_sample_request(request_id, {}, ADMIN_HEADERS)


class TestSpecimenCommittedVolumeBookVsPhysical:
    """Dual committed-volume variants on the same specimen data."""

    def test_book_variant_counts_reserved_aliquot(self, api):
        """PRD §3.3: "The forward-looking `committed_volume_book_ml` sums the
        `initial_volume_ml` of aliquots in `RESERVED`, `DESTRUCTION_PENDING`,
        `DISTRIBUTED`, or `DESTROYED` status — it counts material that is merely
        reserved or queued for destruction, so it exceeds the physical figure whenever
        reservations exist."

        Design: Difficulty/dual_variant_calc/specimen_committed_volume_book_vs_physical
        """
        env = setup_reserved_aliquot(volume_needed_ml=40.0, aliquot_volume_ml=40.0,
                                     specimen_volume_ml=100.0)
        specimen = get_specimen(env["specimen"]["id"])
        assert specimen["committed_volume_book_ml"] == pytest.approx(40.0), (
            f"RESERVED aliquot must count toward the book variant, got "
            f"{specimen['committed_volume_book_ml']}")

    def test_physical_variant_excludes_reserved_aliquot(self, api):
        """PRD §3.3: "The chronological `committed_volume_physical_ml` sums only
        aliquots in `DISTRIBUTED` or `DESTROYED` — material that is physically gone —
        so it lags the book figure until checkouts and destructions complete."

        Design: Difficulty/dual_variant_calc/specimen_committed_volume_book_vs_physical
        """
        env = setup_reserved_aliquot(volume_needed_ml=40.0, aliquot_volume_ml=40.0,
                                     specimen_volume_ml=100.0)
        specimen = get_specimen(env["specimen"]["id"])
        assert specimen["committed_volume_physical_ml"] == pytest.approx(0.0), (
            f"nothing DISTRIBUTED/DESTROYED yet, got {specimen['committed_volume_physical_ml']}")
        aliquot = get_aliquot(env["aliquot"]["id"])
        assert aliquot["status"] == "RESERVED"
        assert aliquot["reserved_for_request_id"] == env["request"]["id"]


class TestFulfillmentQuotaChargeTieredSurcharge:
    """Combinatorial charge: selection volume x utilization-tiered multiplier, capped
    against the remaining quota."""

    def _setup(self, api):
        donor, consent = create_donor_with_consent()
        _, slot = create_unit_with_slot(unit_code="FRZ-CF1")
        specimen, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                             initial_volume_ml=100.0)
        aliquot_a, _ = create_aliquot_for(specimen["id"], 80.0, storage_slot_id=slot["id"])
        aliquot_b, _ = create_aliquot_for(specimen["id"], 10.0, storage_slot_id=slot["id"])
        agreement = create_active_agreement(total_committed_volume_ml=100.0)
        request_a = create_approved_request(agreement["id"], researcher_id="researcher-1",
                                            volume_needed_ml=80.0)
        validate_success(_fulfill(api, request_a["id"]), expected_status=200)
        checkout_reserved_aliquot(aliquot_a["id"], request_a["id"])
        request_b = create_approved_request(agreement["id"], researcher_id="researcher-2",
                                            volume_needed_ml=10.0)
        return agreement, aliquot_b, request_b

    def test_surcharge_multiplier_fires_at_utilization_boundary(self, api):
        """PRD §3.7: "Third, the multiplier branch: when that utilization is already at
        least 0.8 — that is, 80 percent of the contracted total has been consumed —
        the surcharge multiplier 1.25 applies; otherwise the multiplier is 1.0."
        PRD §3.7: "Second, the agreement's pre-fulfillment utilization is its
        `fulfilled_volume_ml` divided by its `total_committed_volume_ml`."

        Design: Difficulty/combinatorial_formula/fulfillment_quota_charge_tiered_surcharge
        """
        _, _, request_b = self._setup(api)
        validate_success(_fulfill(api, request_b["id"]), expected_status=200)
        request_b = get_request(request_b["id"])
        # U_pre = 80.0 / 100.0 = 0.8 >= 0.8, so charge = 10.0 * 1.25 = 12.5.
        assert request_b["charged_volume_ml"] == pytest.approx(12.5), (
            f"surcharge must apply at U_pre == 0.8, got {request_b['charged_volume_ml']}")

    def test_charge_debits_reserved_and_remaining(self, api):
        """PRD §3.7: "On success the agreement's `reserved_volume_ml` increases by the
        charge and its `remaining_volume_ml` decreases by the same amount; the
        request's `charged_volume_ml` records the charge; and each selected aliquot
        flips from `IN_STORAGE` to `RESERVED` with `reserved_for_request_id` set to the
        request."

        Design: Difficulty/combinatorial_formula/fulfillment_quota_charge_tiered_surcharge
        """
        agreement, aliquot_b, request_b = self._setup(api)
        validate_success(_fulfill(api, request_b["id"]), expected_status=200)
        agreement = get_agreement(agreement["id"])
        # Ledger after checkout of the 80.0 charge (reserved 80 -> fulfilled 80),
        # then reservation of the 12.5 surcharge charge: reserved 12.5, remaining 7.5.
        assert agreement["fulfilled_volume_ml"] == pytest.approx(80.0)
        assert agreement["reserved_volume_ml"] == pytest.approx(12.5)
        assert agreement["remaining_volume_ml"] == pytest.approx(7.5)
        assert get_aliquot(aliquot_b["id"])["status"] == "RESERVED"


class TestHandlingFeePerAliquotRounding:
    """Pinned rounding order: round each per-aliquot fee to whole cents, then sum."""

    def _setup(self, api):
        donor, consent = create_donor_with_consent()
        _, slot = create_unit_with_slot(unit_code="FRZ-CF2")
        specimen, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                             initial_volume_ml=10.0)
        aliquot_1, _ = create_aliquot_for(specimen["id"], 0.5, storage_slot_id=slot["id"])
        aliquot_2, _ = create_aliquot_for(specimen["id"], 0.5, storage_slot_id=slot["id"])
        agreement = create_active_agreement(total_committed_volume_ml=1000.0)
        request = create_approved_request(agreement["id"], volume_needed_ml=1.0)
        return agreement, aliquot_1, aliquot_2, request

    def test_fee_rounds_per_aliquot_then_sums(self, api):
        """PRD §3.7: "The order matters: two 0.5 ml aliquots produce raw fees of 501.25
        cents each, which round to 501 each and sum to 1002, whereas summing the raw
        fees first would round 1002.5 to 1003 — the former rule is the one in force."

        Design: Difficulty/combinatorial_formula/handling_fee_per_aliquot_rounding
        """
        _, _, _, request = self._setup(api)
        validate_success(_fulfill(api, request["id"]), expected_status=200)
        request = get_request(request["id"])
        assert request["handling_fee_cents"] == 1002, (
            f"round-per-aliquot-then-sum must give 501 + 501 = 1002, got "
            f"{request['handling_fee_cents']}")

    def test_both_aliquots_reserved_to_cover_volume(self, api):
        """PRD §3.7: "The selector accumulates aliquots greedily in ranking order until
        the cumulative selected volume reaches the request's `volume_needed_ml`."
        PRD §3.7: "each selected aliquot flips from `IN_STORAGE` to `RESERVED` with
        `reserved_for_request_id` set to the request."

        Design: Difficulty/combinatorial_formula/handling_fee_per_aliquot_rounding
        """
        _, aliquot_1, aliquot_2, request = self._setup(api)
        validate_success(_fulfill(api, request["id"]), expected_status=200)
        assert get_aliquot(aliquot_1["id"])["status"] == "RESERVED"
        assert get_aliquot(aliquot_2["id"])["status"] == "RESERVED"


class TestFulfillTemporalVsFiscal:
    """When fulfillment violates both the agreement temporal window and the quota
    gate, the temporal error is returned first."""

    def _setup(self, api):
        donor, consent = create_donor_with_consent()
        _, slot = create_unit_with_slot(unit_code="FRZ-PC2")
        specimen, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                             initial_volume_ml=100.0)
        aliquot_a, _ = create_aliquot_for(specimen["id"], 40.0, storage_slot_id=slot["id"])
        aliquot_b, _ = create_aliquot_for(specimen["id"], 30.0, storage_slot_id=slot["id"])
        agreement = create_active_agreement(
            total_committed_volume_ml=50.0,
            effective_from="2026-04-01T00:00:00Z", effective_to="2026-05-10T00:00:00Z")
        request_a = create_approved_request(agreement["id"], researcher_id="researcher-1",
                                            volume_needed_ml=40.0)
        validate_success(_fulfill(api, request_a["id"]), expected_status=200)
        checkout_reserved_aliquot(aliquot_a["id"], request_a["id"])
        request_b = create_approved_request(agreement["id"], researcher_id="researcher-2",
                                            volume_needed_ml=30.0)
        # Advance past effective_to and expire the agreement via the sweep.
        set_clock_to("2026-05-11T00:00:00Z")
        run_sweep()
        return agreement, request_b

    def test_expired_agreement_reports_temporal_error_not_quota(self, api):
        """PRD §3.7: "Fulfillment then evaluates its checks in a fixed order: every
        candidate's specimen consent must be `ACTIVE` and effective
        (`ERR_CONSENT_NOT_ACTIVE`); consent scope coverage must hold
        (`ERR_CONSENT_SCOPE_VIOLATION`, HTTP 403); the linked agreement must be
        `ACTIVE` and inside its effective window (`ERR_AGREEMENT_NOT_EFFECTIVE`); the
        eligible inventory must suffice (`ERR_INSUFFICIENT_INVENTORY`); and only then —
        last among the business rules — the fiscal quota check
        (`ERR_INSUFFICIENT_QUOTA`)."

        Design: Difficulty/priority_pair_validation_conflict/fulfill_temporal_vs_fiscal
        """
        _, request_b = self._setup(api)
        resp = _fulfill(api, request_b["id"])
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EFFECTIVE)

    def test_rejected_fulfill_leaves_agreement_ledger_untouched(self, api):
        """PRD §3.5: "Independently, the sweep expires an `ACTIVE` agreement once the
        current time reaches its `effective_to`, moving it to `EXPIRED`."
        PRD §3.7: "if the charge exceeds the agreement's `remaining_volume_ml`,
        fulfillment is rejected with `ERR_INSUFFICIENT_QUOTA` (HTTP 402) and no partial
        debit occurs."

        Design: Difficulty/priority_pair_validation_conflict/fulfill_temporal_vs_fiscal
        """
        agreement, request_b = self._setup(api)
        resp = _fulfill(api, request_b["id"])
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EFFECTIVE)
        agreement = get_agreement(agreement["id"])
        assert agreement["status"] == "EXPIRED"
        assert agreement["reserved_volume_ml"] == pytest.approx(0.0)
        assert agreement["fulfilled_volume_ml"] == pytest.approx(40.0)
        assert agreement["remaining_volume_ml"] == pytest.approx(10.0)


def test_fulfill_selector_oldest_specimen_first(api):
    """PRD §3.7: "Eligible aliquots are ranked by their specimen's `collected_at`
    ascending, ties broken by the aliquot's own `created_at` ascending — never by
    identifier."

    Design: Corner/endpoints/fulfill_selector_oldest_specimen_first
    """
    donor, consent = create_donor_with_consent()
    _, slot = create_unit_with_slot(unit_code="FRZ-EP1")
    sp_old, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                       initial_volume_ml=50.0,
                                       collected_at="2026-05-01T00:00:00Z")
    al_old, _ = create_aliquot_for(sp_old["id"], 30.0, storage_slot_id=slot["id"])
    sp_new, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                       initial_volume_ml=50.0,
                                       collected_at="2026-05-03T00:00:00Z")
    al_new, _ = create_aliquot_for(sp_new["id"], 30.0, storage_slot_id=slot["id"])
    agreement = create_active_agreement(total_committed_volume_ml=1000.0)
    request = create_approved_request(agreement["id"], volume_needed_ml=30.0)
    validate_success(_fulfill(api, request["id"]), expected_status=200)
    al_old = get_aliquot(al_old["id"])
    assert al_old["status"] == "RESERVED", "earlier collected_at specimen must win"
    assert al_old["reserved_for_request_id"] == request["id"]
    assert get_aliquot(al_new["id"])["status"] == "IN_STORAGE", "later specimen not selected"


def test_fulfill_insufficient_inventory_rejected(api):
    """PRD §3.7: "If the entire eligible pool cannot cover `volume_needed_ml`,
    fulfillment is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409) and nothing is
    reserved — partial reservations never happen."

    Design: Corner/endpoints/fulfill_insufficient_inventory_rejected
    """
    donor, consent = create_donor_with_consent()
    _, slot = create_unit_with_slot(unit_code="FRZ-EP2")
    specimen, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                         initial_volume_ml=100.0)
    aliquot, _ = create_aliquot_for(specimen["id"], 40.0, storage_slot_id=slot["id"])
    agreement = create_active_agreement(total_committed_volume_ml=1000.0)
    request = create_approved_request(agreement["id"], volume_needed_ml=500.0)
    resp = _fulfill(api, request["id"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
    assert get_aliquot(aliquot["id"])["status"] == "IN_STORAGE", (
        "atomic: no partial reservation may remain")
    assert get_agreement(agreement["id"])["reserved_volume_ml"] == pytest.approx(0.0)


def test_fulfill_exceeding_quota_returns_insufficient_quota(api):
    """PRD §3.7: "Fifth, the feasibility gate: if the charge exceeds the agreement's
    `remaining_volume_ml`, fulfillment is rejected with `ERR_INSUFFICIENT_QUOTA`
    (HTTP 402) and no partial debit occurs."

    Design: Corner/endpoints/fulfill_exceeding_quota_returns_insufficient_quota
    """
    donor, consent = create_donor_with_consent()
    _, slot = create_unit_with_slot(unit_code="FRZ-EP3")
    specimen, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                         initial_volume_ml=100.0)
    aliquot, _ = create_aliquot_for(specimen["id"], 40.0, storage_slot_id=slot["id"])
    agreement = create_active_agreement(total_committed_volume_ml=30.0)
    request = create_approved_request(agreement["id"], volume_needed_ml=40.0)
    resp = _fulfill(api, request["id"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_QUOTA)
    # Utilization is 0 < 0.8, so no surcharge; the 40.0 charge simply exceeds the 30.0
    # remaining quota, and the aliquot must stay unreserved.
    assert get_aliquot(aliquot["id"])["status"] == "IN_STORAGE"


def test_fulfill_effects_immediately_visible(api):
    """PRD §3.7: "On success the agreement's `reserved_volume_ml` increases by the
    charge and its `remaining_volume_ml` decreases by the same amount; the request's
    `charged_volume_ml` records the charge; and each selected aliquot flips from
    `IN_STORAGE` to `RESERVED` with `reserved_for_request_id` set to the request."
    PRD §3.7: "each selected aliquot's fee is 500 cents plus 2.5 cents per milliliter
    of its `initial_volume_ml`, and each per-aliquot fee is rounded half-up to whole
    cents first; only then are the rounded lines summed into the request's
    `handling_fee_cents`."

    Design: Corner/consistency_model/fulfill_effects_immediately_visible
    """
    env = setup_reserved_aliquot(volume_needed_ml=40.0, aliquot_volume_ml=40.0,
                                 specimen_volume_ml=100.0, agreement_total_ml=1000.0)
    # Reads issued immediately after fulfill observe every effect with no delay.
    assert get_aliquot(env["aliquot"]["id"])["status"] == "RESERVED"
    agreement = get_agreement(env["agreement"]["id"])
    assert agreement["reserved_volume_ml"] == pytest.approx(40.0)
    assert agreement["remaining_volume_ml"] == pytest.approx(960.0)
    request = get_request(env["request"]["id"])
    assert request["charged_volume_ml"] == pytest.approx(40.0)
    assert request["handling_fee_cents"] == 600  # 500 + 40.0 * 2.5
