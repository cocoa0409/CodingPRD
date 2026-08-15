"""Aliquoting: volume invariant on create/void, equality boundary, OCC, terminal lockdown."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    LAB_HEADERS,
    assert_specimen_volume_invariant,
    create_donor_with_consent,
    create_returned_kit,
    accession_specimen,
    create_aliquot_for,
    get_specimen,
)


def _specimen_100ml():
    """ACCESSIONED (no slot) 100.0ml specimen under an ACTIVE consent."""
    donor, consent = create_donor_with_consent()
    kit = create_returned_kit(donor["id"])
    specimen = accession_specimen(donor["id"], kit["id"], consent["id"],
                                  initial_volume_ml=100.0)
    return donor, consent, kit, specimen


class TestAliquotCreateVoidVolumeInvariant:
    """Conserved physical volume across the forward (create) and compensating (void) actions."""

    def test_create_debits_residual_volume(self, api):
        """PRD §3.3: "The `residual_volume_ml` is the specimen's accessioned volume
        minus the sum of the `initial_volume_ml` of every child aliquot whose status is
        not `VOID`; it is recomputed immediately when an aliquot is created (a debit)
        and when one is voided (a compensating credit)."

        Design: Difficulty/compensating_invariant/aliquot_create_void_volume_invariant
        """
        _, _, _, specimen = _specimen_100ml()
        aliquot, fresh = create_aliquot_for(specimen["id"], 40.0,
                                            expected_version=specimen["version"])
        assert fresh["residual_volume_ml"] == pytest.approx(60.0), (
            f"invariant after create: 100.0 == residual + 40.0, got {fresh['residual_volume_ml']}")
        aliquots = validate_success(api.list_specimen_aliquots(specimen["id"], LAB_HEADERS))
        assert_specimen_volume_invariant(fresh, aliquots)

    def test_void_restores_residual_volume(self, api):
        """PRD §3.3: "Voiding sets the aliquot's status to `VOID`, zeroes its
        `remaining_volume_ml`, restores the specimen's `residual_volume_ml` by adding
        the aliquot's `initial_volume_ml` back, and increments the specimen's `version`
        by one."

        Design: Difficulty/compensating_invariant/aliquot_create_void_volume_invariant
        """
        _, _, _, specimen = _specimen_100ml()
        aliquot, fresh = create_aliquot_for(specimen["id"], 40.0,
                                            expected_version=specimen["version"])
        resp = api.void_aliquot(aliquot["id"], {}, LAB_HEADERS)
        voided = validate_success(resp, expected_status=200)
        assert voided["status"] == "VOID"
        assert voided["remaining_volume_ml"] == 0.0
        after = get_specimen(specimen["id"])
        assert after["residual_volume_ml"] == pytest.approx(100.0), (
            f"invariant after void: 100.0 == residual + 0, got {after['residual_volume_ml']}")
        aliquots = validate_success(api.list_specimen_aliquots(specimen["id"], LAB_HEADERS))
        assert_specimen_volume_invariant(after, aliquots)


def test_aliquot_volume_equality_boundary(api):
    """PRD §3.3: "then the volume check: the requested `initial_volume_ml` must be
    greater than zero and no larger than the specimen's current `residual_volume_ml`,
    with equality allowed, failing as `ERR_INSUFFICIENT_SPECIMEN_VOLUME` (HTTP 422)."

    Design: Corner/validations/aliquot_volume_equality_boundary
    """
    _, _, _, specimen = _specimen_100ml()
    # Equality is allowed: 100.0 of 100.0 residual.
    aliquot, fresh = create_aliquot_for(specimen["id"], 100.0,
                                        expected_version=specimen["version"])
    assert aliquot["initial_volume_ml"] == pytest.approx(100.0)
    assert fresh["residual_volume_ml"] == pytest.approx(0.0)
    # Any further volume exceeds the zero residual.
    resp = api.create_aliquot(
        specimen["id"],
        {"initial_volume_ml": 0.01, "expected_specimen_version": fresh["version"]},
        LAB_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SPECIMEN_VOLUME)


def test_aliquot_void_then_checkout_rejected(api):
    """PRD §2.6: "Attempting an action on a resource that has already reached a
    terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)."
    PRD §3.3: "Aliquot statuses are `IN_STORAGE`, `RESERVED`, `QUARANTINED`,
    `DESTRUCTION_PENDING`, `DISTRIBUTED`, `DESTROYED`, and `VOID`; the last three are
    terminal."

    Design: Corner/state_machines/aliquot_void_then_checkout_rejected
    """
    donor, consent = create_donor_with_consent()
    kit = create_returned_kit(donor["id"])
    specimen = accession_specimen(donor["id"], kit["id"], consent["id"],
                                  initial_volume_ml=50.0)
    aliquot, _ = create_aliquot_for(specimen["id"], 20.0,
                                    expected_version=specimen["version"])
    resp = api.void_aliquot(aliquot["id"], {}, LAB_HEADERS)
    validate_success(resp, expected_status=200)
    resp = api.checkout_aliquot(aliquot["id"], {"request_id": NON_EXISTENT_UUID}, LAB_HEADERS)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_occ_stale_specimen_version_rejected(api):
    """PRD §2.7: "If the specimen's version has advanced since the client last observed
    it — for example because another aliquot creation debited its `residual_volume_ml`
    or a void restored it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412); the client must re-read the specimen and retry with the fresh version."

    Design: Corner/cross_cutting_layers/occ_stale_specimen_version_rejected
    """
    _, _, _, specimen = _specimen_100ml()
    observed_version = specimen["version"]
    payload = {"initial_volume_ml": 10.0, "expected_specimen_version": observed_version}
    resp = api.create_aliquot(specimen["id"], payload, LAB_HEADERS)
    validate_success(resp, expected_status=201)  # version matched; specimen now at version+1
    # Replaying the same observed version must fail on the stale version alone.
    resp = api.create_aliquot(specimen["id"], payload, LAB_HEADERS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
