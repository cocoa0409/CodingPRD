"""Specimen accession: kit gating, consent gating, donor coherence, shape, listing."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    COORD_HEADERS,
    LAB_HEADERS,
    create_donor,
    create_donor_with_consent,
    create_distributed_kit,
    create_returned_kit,
    create_unit_with_slot,
    accession_specimen,
    withdraw_consent_and_finalize,
)


def _accession_payload(donor_id, kit_id, consent_id, **overrides):
    payload = {
        "donor_id": donor_id,
        "kit_id": kit_id,
        "consent_record_id": consent_id,
        "specimen_type": "BLOOD",
        "initial_volume_ml": 50.0,
        "collected_at": "2026-05-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_specimen_get_returns_not_found(api):
    """PRD §2.6: "3. **Path existence** — resource identifiers in the URL are validated
    strictly left-to-right; the first identifier that does not resolve to an existing
    resource fails the request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/specimen_get_returns_not_found
    """
    resp = api.get_specimen(NON_EXISTENT_UUID, LAB_HEADERS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_specimen_invalid_enum_specimen_type_rejected(api):
    """PRD §3.3: "The accession payload names the `donor_id`, the `kit_id` of the
    returned kit, the `consent_record_id` under which the material was collected, the
    `specimen_type` (`BLOOD`, `SALIVA`, `TISSUE`, or `PLASMA`), the `collected_at`
    timestamp, and an `initial_volume_ml` that must be greater than zero"
    PRD §2.6: "All shape failures return `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/specimen_invalid_enum_specimen_type_rejected
    """
    donor, consent = create_donor_with_consent()
    kit = create_returned_kit(donor["id"])
    resp = api.create_specimen(
        _accession_payload(donor["id"], kit["id"], consent["id"], specimen_type="URINE"),
        LAB_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_specimen_list_pagination(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
    sets the number of items skipped and defaults to 0."
    PRD §2.3: "The `meta` object of list responses carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/specimen_list_pagination
    """
    donor, consent = create_donor_with_consent()
    for kit_type, collected in (("BLOOD", "2026-05-02T00:00:00Z"),
                                ("SALIVA", "2026-05-02T01:00:00Z"),
                                ("TISSUE", "2026-05-02T02:00:00Z")):
        kit = create_returned_kit(donor["id"], kit_type=kit_type)
        accession_specimen(donor["id"], kit["id"], consent["id"],
                           specimen_type=kit_type, initial_volume_ml=10.0,
                           collected_at=collected)
    page1, meta1 = validate_paginated(api.list_specimens(LAB_HEADERS, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_specimens(LAB_HEADERS, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_specimen_initial_state_depends_on_slot(api):
    """PRD §3.3: "Its `lifecycle_status` starts at `IN_STORAGE` when a storage slot was
    provided and `ACCESSIONED` otherwise; a specimen accessioned without a slot later
    advances from `ACCESSIONED` to `IN_STORAGE` when the first of its aliquots is
    placed into a slot."

    Design: Corner/state_machines/specimen_initial_state_depends_on_slot
    """
    donor, consent = create_donor_with_consent()
    _, slot = create_unit_with_slot(unit_code="FRZ-SM4")
    kit1 = create_returned_kit(donor["id"])
    kit2 = create_returned_kit(donor["id"])
    no_slot = accession_specimen(donor["id"], kit1["id"], consent["id"],
                                 initial_volume_ml=10.0)
    with_slot = accession_specimen(donor["id"], kit2["id"], consent["id"],
                                   initial_volume_ml=10.0, storage_slot_id=slot["id"])
    assert no_slot["lifecycle_status"] == "ACCESSIONED"
    assert with_slot["lifecycle_status"] == "IN_STORAGE"


def test_consent_withdrawn_blocks_accession(api):
    """PRD §3.3: "Accession checks, in order: the kit must be `RETURNED`, failing as
    `ERR_KIT_NOT_RETURNED`; the referenced consent must be `ACTIVE` and effective,
    failing as `ERR_CONSENT_NOT_ACTIVE`; the donor references must cohere — the kit's
    `donor_id` and the consent's `donor_id` must both equal the payload's `donor_id`,
    failing as `ERR_DONOR_MISMATCH` (HTTP 400); and the kit must still be unexpired at
    accession, failing as `ERR_KIT_EXPIRED`."

    Design: Corner/validations/consent_withdrawn_blocks_accession
    """
    donor, consent = create_donor_with_consent()
    kit = create_returned_kit(donor["id"])
    sweep = withdraw_consent_and_finalize(consent["id"])
    assert sweep["withdrawals_finalized"] == 1
    resp = api.create_specimen(
        _accession_payload(donor["id"], kit["id"], consent["id"], initial_volume_ml=10.0),
        LAB_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)


def test_donor_mismatch_at_accession_rejected(api):
    """PRD §3.3: "the donor references must cohere — the kit's `donor_id` and the
    consent's `donor_id` must both equal the payload's `donor_id`, failing as
    `ERR_DONOR_MISMATCH` (HTTP 400)"

    Design: Corner/validations/donor_mismatch_at_accession_rejected
    """
    donor_a, consent_a = create_donor_with_consent()
    donor_b = create_donor("D-VAL4b")
    kit = create_returned_kit(donor_a["id"])  # kit distributed to donor A
    resp = api.create_specimen(
        _accession_payload(donor_b["id"], kit["id"], consent_a["id"], initial_volume_ml=10.0),
        LAB_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_DONOR_MISMATCH)


class TestAccessionRequiresKitReturned:
    """Cross-entity gate: accession requires the kit in RETURNED state."""

    def test_accession_with_distributed_kit_rejected(self, api):
        """PRD §3.3: "Accession checks, in order: the kit must be `RETURNED`, failing
        as `ERR_KIT_NOT_RETURNED`; the referenced consent must be `ACTIVE` and
        effective, failing as `ERR_CONSENT_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/accession_requires_kit_returned
        """
        donor, consent = create_donor_with_consent()
        kit = create_distributed_kit(donor["id"])  # DISTRIBUTED, never returned
        resp = api.create_specimen(
            _accession_payload(donor["id"], kit["id"], consent["id"]),
            LAB_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_KIT_NOT_RETURNED)

    def test_accession_after_receive_return_succeeds(self, api):
        """PRD §3.3: "Accession checks, in order: the kit must be `RETURNED`, failing
        as `ERR_KIT_NOT_RETURNED`"
        PRD §3.3: "Its `lifecycle_status` starts at `IN_STORAGE` when a storage slot
        was provided and `ACCESSIONED` otherwise"

        Design: Difficulty/cross_entity_state_dependency/accession_requires_kit_returned
        """
        donor, consent = create_donor_with_consent()
        kit = create_distributed_kit(donor["id"])
        # While DISTRIBUTED, accession is refused.
        resp = api.create_specimen(
            _accession_payload(donor["id"], kit["id"], consent["id"]),
            LAB_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_KIT_NOT_RETURNED)
        # After receive-return the identical accession succeeds.
        resp = api.receive_return_kit(kit["id"], {}, COORD_HEADERS)
        validate_success(resp, expected_status=200)
        resp = api.create_specimen(
            _accession_payload(donor["id"], kit["id"], consent["id"]),
            LAB_HEADERS,
        )
        data = validate_success(resp, expected_status=201)
        assert data["lifecycle_status"] == "ACCESSIONED"  # no slot supplied
