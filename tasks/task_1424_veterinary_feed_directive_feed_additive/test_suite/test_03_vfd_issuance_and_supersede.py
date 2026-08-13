"""VFD issuance: initial state, computed quota, issuance guards, supersession
with optimistic concurrency (PRD §2.7, §2.8, §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_vfd_authorization_payload,
    setup_clinic_with_vet, setup_producer_with_group, setup_drug,
    record_vcpr, issue_vfd, fresh_vfd, setup_audit_bundle,
    setup_validated_order, set_clock, submit_order, validate_order,
    make_veterinarian_headers,
)


def test_newly_issued_vfd_has_status_issued(api):
    """PRD §3.3: "At issuance the `issued_on` timestamp is set to the current
    logical time, `status` becomes `ISSUED`, and `remaining_animal_count` is
    initialized equal to `authorized_animal_count`."

    Design: Corner/state_machines/vfd_authorization_initial_state_issued
    """
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group()
    drug = setup_drug()
    record_vcpr(vet, producer)
    vfd = issue_vfd(vet, producer, group, drug, authorized_animal_count=5)
    assert vfd["status"] == "ISSUED", f"Expected ISSUED, got {vfd['status']}"


def test_vfd_remaining_count_initialized_to_authorized(api):
    """PRD §3.3: "At issuance the `issued_on` timestamp is set to the current
    logical time, `status` becomes `ISSUED`, and `remaining_animal_count` is
    initialized equal to `authorized_animal_count`."

    Design: Corner/entities/vfd_remaining_count_computed_at_issuance
    """
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group()
    drug = setup_drug()
    record_vcpr(vet, producer)
    vfd = issue_vfd(vet, producer, group, drug, authorized_animal_count=25)
    assert vfd["remaining_animal_count"] == 25
    assert vfd["status"] == "ISSUED"


def test_issue_vfd_with_extra_label_intent_rejected(api):
    """PRD §3.3: "Finally, the optional `extra_label_intended` flag defaults to
    false; if a veterinarian attempts to set it to true the issuance is rejected
    with `ERR_EXTRA_LABEL_USE` (HTTP 422), because VFD drugs admit no extra-label
    use."

    Design: Corner/validations/create_vfd_with_extra_label_intent_rejected
    """
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group()
    drug = setup_drug()
    record_vcpr(vet, producer)
    res = api.create_vfd_authorization(
        create_vfd_authorization_payload(
            producer["id"], group["id"], vet["id"], drug["id"],
            authorized_animal_count=5, extra_label_intended=True,
        ),
        make_veterinarian_headers(vet["id"]),
    )
    validate_error(res, ApiErrorId.ERR_EXTRA_LABEL_USE, expected_status=422)


def test_issue_vfd_with_species_class_mismatch_rejected(api):
    """PRD §3.3: "The drug's `allowed_species_classes` must contain the
    `SPECIES:CLASS` pair formed from the target animal group's `species` and
    `production_class`, otherwise the issuance is rejected with
    `ERR_SPECIES_CLASS_MISMATCH` (HTTP 422)."

    Design: Corner/validations/create_vfd_with_species_mismatch_rejected
    """
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group(
        group_overrides={"species": "POULTRY", "production_class": "LAYER",
                         "head_count": 500, "average_weight_lbs": 5}
    )
    drug = setup_drug(allowed_species_classes=["CATTLE:BEEF"])
    record_vcpr(vet, producer)
    res = api.create_vfd_authorization(
        create_vfd_authorization_payload(
            producer["id"], group["id"], vet["id"], drug["id"], authorized_animal_count=5,
        ),
        make_veterinarian_headers(vet["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SPECIES_CLASS_MISMATCH, expected_status=422)


def test_issue_vfd_with_duration_over_six_months_rejected(api):
    """PRD §3.3: "The `expiration_date` may not be more than six months past
    `issued_on` per 21 CFR 558.6; a longer horizon is rejected with
    `ERR_VFD_DURATION_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/create_vfd_with_duration_over_6mo_rejected
    """
    # Default logical clock is 2026-08-01T00:00:00Z (PRD §2.5); 2027-03-01 is
    # more than six months past issuance.
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group()
    drug = setup_drug()
    record_vcpr(vet, producer)
    res = api.create_vfd_authorization(
        create_vfd_authorization_payload(
            producer["id"], group["id"], vet["id"], drug["id"],
            authorized_animal_count=5, expiration_date="2027-03-01T00:00:00Z",
        ),
        make_veterinarian_headers(vet["id"]),
    )
    validate_error(res, ApiErrorId.ERR_VFD_DURATION_EXCEEDED, expected_status=422)


def test_issue_vfd_for_suspended_producer_rejected(api, inspector_headers):
    """PRD §3.3: "The producer must currently be `ACTIVE`; otherwise the issuance
    is rejected with `ERR_PRODUCER_SUSPENDED` (HTTP 409)."
    PRD §3.9: "an inspector may mark an `OPEN` bundle as `DEFICIENT`; this
    transitions the bundle to `DEFICIENT`, flips the producer's `status` to
    `SUSPENDED`"

    Design: Corner/validations/vfd_issued_for_suspended_producer_rejected
    """
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group()
    drug = setup_drug()
    record_vcpr(vet, producer)
    # Suspend the producer via a deficient audit (PRD §3.9).
    audit = setup_audit_bundle(producer["id"])
    validate_success(api.mark_audit_deficient(audit["id"], inspector_headers), 200)
    producer_after = validate_success(api.get_producer(producer["id"], inspector_headers), 200)
    assert producer_after["status"] == "SUSPENDED"

    res = api.create_vfd_authorization(
        create_vfd_authorization_payload(
            producer["id"], group["id"], vet["id"], drug["id"], authorized_animal_count=5,
        ),
        make_veterinarian_headers(vet["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PRODUCER_SUSPENDED, expected_status=409)


def test_supersede_moves_old_vfd_to_superseded(api):
    """PRD §3.3: "When the supersede succeeds, the older VFD transitions to
    `SUPERSEDED`, its `version` increments, its `remaining_animal_count` is zeroed,
    and its `superseded_by_id` is set to the new VFD's `id`. The new VFD is created
    in `ISSUED` with its own independent `authorized_animal_count`"

    Design: Corner/state_machines/vfd_supersede_old_vfd_terminal
    """
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group()
    drug = setup_drug()
    record_vcpr(vet, producer)
    old = issue_vfd(vet, producer, group, drug, authorized_animal_count=10)

    new = validate_success(api.create_vfd_authorization(
        create_vfd_authorization_payload(
            producer["id"], group["id"], vet["id"], drug["id"],
            authorized_animal_count=15, expiration_date="2026-11-01T00:00:00Z",
            supersedes_id=old["id"],
            expected_vfd_authorization_version=old["version"],
        ),
        make_veterinarian_headers(vet["id"]),
    ), 201)
    assert new["status"] == "ISSUED"

    old_after = validate_success(api.get_vfd_authorization(old["id"], make_veterinarian_headers(vet["id"])), 200)
    assert old_after["status"] == "SUPERSEDED"
    assert old_after["superseded_by_id"] == new["id"]
    assert old_after["remaining_animal_count"] == 0
    assert old_after["version"] == old["version"] + 1


def test_supersede_with_stale_expected_version_rejected(api):
    """PRD §2.7: "Issuing a replacement VFD via the `supersedes_id` parameter is
    one such operation: if the existing VFD's current `version` no longer matches
    `expected_vfd_authorization_version`, the issuance is rejected with
    `ERR_STALE_VERSION` (HTTP 412), because another writer has already superseded
    or otherwise mutated the same VFD."

    Setup note: the VFD's version is advanced by a successful feed-order
    validation (PRD §3.5: "its `version` is incremented"), leaving the VFD in
    PARTIALLY_USED — still supersedable per §3.3 — so the stale version is the
    only failing precondition.

    Design: Corner/validations/occ_stale_version_on_supersede
    """
    chain = setup_validated_order()
    stale_version = chain["vfd"]["version"]
    # Advance the VFD version with a second successful validation.
    order2 = submit_order(chain["mill"], chain["vfd"], chain["producer"], animal_count=5)
    validate_order(chain["mill"], order2, chain["vfd"]["id"], expected_version=stale_version)
    current = fresh_vfd(chain["vfd"]["id"])
    assert current["version"] > stale_version
    assert current["status"] == "PARTIALLY_USED"

    res = api.create_vfd_authorization(
        create_vfd_authorization_payload(
            chain["producer"]["id"], chain["group"]["id"], chain["vet"]["id"],
            chain["drug"]["id"],
            authorized_animal_count=20, expiration_date="2026-11-01T00:00:00Z",
            supersedes_id=chain["vfd"]["id"],
            expected_vfd_authorization_version=stale_version,
        ),
        make_veterinarian_headers(chain["vet"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
