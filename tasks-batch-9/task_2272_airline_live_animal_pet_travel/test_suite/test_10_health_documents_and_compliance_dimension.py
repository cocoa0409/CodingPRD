"""Health documents, the review loop and the reservation's compliance dimension.

The compliance dimension moves on its own edges and never writes the commercial
dimension, the review loop is capped at three revisions, and the compliance sweep
is atomic: when it refuses, nothing at all is written.
"""

from test_helpers import (
    ApiErrorId,
    SECOND_VETERINARY_REVIEWER_ID,
    assert_animal_state,
    assert_reservation_money,
    assert_reservation_state,
    assert_segment_state,
    validate_error,
    validate_success,
)


def test_verified_document_older_than_max_age_days_rejected(
    api, workbench, catalog, primary_leg
):
    """A verified certificate issued more than the permitted number of whole days
    before arrival does not satisfy the requirement it was filed against.

    PRD §3.4: "every `ACTIVE` destination requirement with `mandatory` true for the
    animal's species and destination country must be backed by a health document in
    `VERIFIED` status, a missing one being refused with
    `ERR_REQUIRED_DOCUMENT_MISSING` and a too-old one with
    `ERR_DOCUMENT_STALE_FOR_DESTINATION`."

    Design: Corner/validations/verified_document_older_than_max_age_days_rejected
    """
    leg = primary_leg()
    reservation = workbench.create_reservation()
    stale_animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.screen_animal(stale_animal["id"])
    workbench.create_segment(stale_animal["id"], leg["id"], sequence_index=1)
    workbench.verified_document(
        stale_animal["id"],
        issued_at="2026-06-01T00:00:00Z",
        expires_at="2026-12-01T00:00:00Z",
    )

    refused = api.mark_animal_record_travel_ready(
        stale_animal["id"], workbench.acceptance()
    )
    validate_error(refused, ApiErrorId.DOCUMENT_STALE_FOR_DESTINATION, 422)
    assert_animal_state(workbench.read_animal(stale_animal["id"]), status="SCREENED")

    fresh_animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Taro",
    )
    workbench.screen_animal(fresh_animal["id"])
    workbench.create_segment(fresh_animal["id"], leg["id"], sequence_index=1)
    workbench.verified_document(
        fresh_animal["id"],
        issued_at="2026-07-15T00:00:00Z",
        expires_at="2026-12-01T00:00:00Z",
    )

    promoted = validate_success(
        api.mark_animal_record_travel_ready(fresh_animal["id"], workbench.acceptance())
    )
    assert_animal_state(promoted, status="TRAVEL_READY")


def test_document_issuer_country_mismatch_with_origin_station_rejected(
    api, workbench, catalog, primary_leg
):
    """Verification reads the country of the origin station of the animal's first
    slot, so a certificate from anywhere else cannot be verified.

    PRD §3.6: "Before either, the document's `issuing_country_code` must equal the
    `country_code` of the origin station of the animal's `sequence_index` 1 slot; a
    mismatch is refused with `ERR_DOCUMENT_ISSUER_MISMATCH`."

    Design: Corner/validations/document_issuer_country_mismatch_with_origin_station_rejected
    """
    leg = primary_leg()
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.create_segment(animal["id"], leg["id"], sequence_index=1)

    foreign = workbench.submit_document(
        animal["id"],
        document_type="HEALTH_CERTIFICATE",
        issuing_country_code="SG",
        issued_at="2026-08-20T00:00:00Z",
        expires_at="2026-11-20T00:00:00Z",
    )
    under_review = workbench.start_document_review(foreign["id"])
    assert under_review["status"] == "UNDER_REVIEW"

    refused = api.verify_health_document(foreign["id"], workbench.reviewer())
    validate_error(refused, ApiErrorId.DOCUMENT_ISSUER_MISMATCH, 422)

    unchanged = workbench.read_document(foreign["id"])
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["reviewed_by_user_id"] is None
    assert unchanged["version"] == under_review["version"]

    domestic = workbench.submit_document(
        animal["id"],
        document_type="HEALTH_CERTIFICATE",
        issuing_country_code="HK",
        issued_at="2026-08-20T00:00:00Z",
        expires_at="2026-11-20T00:00:00Z",
    )
    workbench.start_document_review(domestic["id"])
    verified = validate_success(
        api.verify_health_document(domestic["id"], workbench.reviewer())
    )
    assert verified["status"] == "VERIFIED"


def test_reservation_compliance_dimension_degrades_while_booking_dimension_holds(
    api, workbench, confirmed_booking
):
    """Rejecting a document after confirmation drives the compliance dimension down
    two edges while the commercial dimension does not move at all.

    PRD §3.4: "The two evolve independently: every commercial transition described in
    this section leaves `compliance_status` untouched, and every compliance transition
    in §3.6 leaves `booking_status` untouched."

    Design: Difficulty/non_linear_state_machine/reservation_compliance_dimension_degrades_while_booking_dimension_holds
    """
    state = confirmed_booking()
    assert_reservation_state(
        workbench.read_reservation(state["reservation_id"]),
        booking_status="CONFIRMED",
        compliance_status="VERIFIED",
    )

    second_document = workbench.submit_document(
        state["animal_id"], document_type="RABIES_VACCINATION"
    )
    workbench.start_document_review(second_document["id"])
    assert_reservation_state(
        workbench.read_reservation(state["reservation_id"]),
        booking_status="CONFIRMED",
        compliance_status="VERIFIED",
    )

    workbench.reject_document(
        second_document["id"],
        as_user_id=SECOND_VETERINARY_REVIEWER_ID,
        payload={"rejection_reason": "vaccination lot unreadable"},
    )

    assert_reservation_state(
        workbench.read_reservation(state["reservation_id"]),
        booking_status="CONFIRMED",
        compliance_status="DEFICIENT",
    )


def test_document_rejection_returns_the_animal_to_screened_without_touching_money(
    api, workbench, confirmed_booking
):
    """The same rejection also walks the animal back one state and leaves the slot and
    the charge assembly untouched.

    PRD §3.6: "It also drives two other rows: the owning reservation's
    `compliance_status` is set to `DEFICIENT` — the `IN_REVIEW → DEFICIENT` and
    `VERIFIED → DEFICIENT` edges, both of which leave `booking_status` untouched — and
    the owning animal returns `TRAVEL_READY → SCREENED` if it was `TRAVEL_READY`, so a
    booking that had cleared its paperwork gate must clear it again."

    Design: Difficulty/non_linear_state_machine/reservation_compliance_dimension_degrades_while_booking_dimension_holds
    """
    state = confirmed_booking()
    assert_animal_state(
        workbench.read_animal(state["animal_id"]), status="TRAVEL_READY"
    )

    second_document = workbench.submit_document(
        state["animal_id"], document_type="RABIES_VACCINATION"
    )
    workbench.start_document_review(second_document["id"])
    rejected = workbench.reject_document(
        second_document["id"], as_user_id=SECOND_VETERINARY_REVIEWER_ID
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["reviewed_by_user_id"] == SECOND_VETERINARY_REVIEWER_ID

    assert_animal_state(
        workbench.read_animal(state["animal_id"]),
        status="SCREENED",
        container_compliance_state="COMPLIANT",
    )
    assert_segment_state(
        workbench.read_segment(state["segment_id"]),
        status="RESERVED",
        segment_fee_amount=33180,
    )
    assert_reservation_money(
        workbench.read_reservation(state["reservation_id"]),
        subtotal_amount=33180,
        refunded_amount=0,
        net_payable_amount=33180,
    )


def test_health_document_fourth_resubmission_rejected_at_revision_cap(
    api, workbench, catalog
):
    """Three revisions are permitted; the fourth is refused and the document keeps the
    instants its third revision carried.

    PRD §3.6: "The document's `revision_count` must be strictly less than three; a
    fourth attempt is refused with `ERR_DOC_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/health_document_fourth_resubmission_rejected_at_revision_cap
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    document = workbench.submit_document(animal["id"])

    for issued_at in (
        "2026-07-21T00:00:00Z",
        "2026-07-22T00:00:00Z",
        "2026-07-23T00:00:00Z",
    ):
        workbench.start_document_review(document["id"])
        workbench.reject_document(document["id"])
        workbench.resubmit_document(
            document["id"],
            issued_at=issued_at,
            expires_at="2026-10-01T00:00:00Z",
        )

    workbench.start_document_review(document["id"])
    workbench.reject_document(document["id"])

    refused = api.resubmit_health_document(
        document["id"],
        {"issued_at": "2026-07-24T00:00:00Z", "expires_at": "2026-10-01T00:00:00Z"},
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.DOC_REVISION_LIMIT_REACHED, 409)

    stored = workbench.read_document(document["id"])
    assert stored["revision_count"] == 3
    assert stored["issued_at"] == "2026-07-23T00:00:00Z"
    assert stored["status"] == "REJECTED"


def test_health_document_revision_loop_counts_each_resubmission(
    api, workbench, catalog
):
    """Each turn of the review loop increments the revision count, overwrites both
    instants and clears the reviewer stamp.

    PRD §3.6: "The document moves `REJECTED → SUBMITTED`, `revision_count` increments
    by one, both instants are overwritten with the supplied values under the same
    strict ordering rule, `reviewed_by_user_id` is cleared to null, and the document's
    `version` increments by one."

    Design: Difficulty/non_linear_state_machine/health_document_fourth_resubmission_rejected_at_revision_cap
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    document = workbench.submit_document(animal["id"])
    assert document["revision_count"] == 0
    assert document["reviewed_by_user_id"] is None

    for revision, issued_at in enumerate(
        ("2026-07-21T00:00:00Z", "2026-07-22T00:00:00Z", "2026-07-23T00:00:00Z"),
        start=1,
    ):
        workbench.start_document_review(document["id"])
        rejected = workbench.reject_document(document["id"])
        assert rejected["reviewed_by_user_id"] is not None

        resubmitted = workbench.resubmit_document(
            document["id"],
            issued_at=issued_at,
            expires_at="2026-10-01T00:00:00Z",
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == revision
        assert resubmitted["issued_at"] == issued_at
        assert resubmitted["reviewed_by_user_id"] is None


def test_empty_mandatory_requirement_set_verifies_compliance_vacuously(
    api, workbench, catalog
):
    """With no mandatory requirement matching the destination country the sweep has
    nothing to demand, so it verifies on an empty set.

    PRD §3.6: "If every demanded document exists and is young enough, the sweep then
    examines expiry: if every one of them has `expires_at` strictly after the logical
    clock, the reservation's `compliance_status` becomes `VERIFIED`".

    Design: Difficulty/boundary_precision_check/empty_mandatory_requirement_set_verifies_compliance_vacuously
    """
    leg = workbench.create_leg(
        catalog["hkg_id"],
        catalog["sin_id"],
        flight_number="AN301",
        scheduled_departure_utc="2026-09-10T02:00:00Z",
        scheduled_arrival_utc="2026-09-10T06:00:00Z",
        forecast_high_c=27,
        forecast_low_c=24,
    )
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.create_segment(animal["id"], leg["id"], sequence_index=1)
    permit = workbench.submit_document(animal["id"], document_type="IMPORT_PERMIT")
    workbench.start_document_review(permit["id"])

    swept = workbench.verify_compliance(reservation["id"])
    assert_reservation_state(
        swept, booking_status="PENDING", compliance_status="VERIFIED"
    )
    assert workbench.read_document(permit["id"])["status"] == "UNDER_REVIEW"


def test_mandatory_requirement_for_the_destination_makes_the_sweep_demanding(
    api, workbench, catalog
):
    """Adding a mandatory requirement for the destination country makes the same sweep
    fail, and the failure writes nothing.

    PRD §3.6: "If any demanded document is absent, the request fails with
    `ERR_REQUIRED_DOCUMENT_MISSING` and **nothing at all is written** — the operation
    is atomic all-or-nothing, and no field on the reservation, the animals or the
    documents changes."

    Design: Difficulty/boundary_precision_check/empty_mandatory_requirement_set_verifies_compliance_vacuously
    """
    leg = workbench.create_leg(
        catalog["hkg_id"],
        catalog["sin_id"],
        flight_number="AN301",
        scheduled_departure_utc="2026-09-10T02:00:00Z",
        scheduled_arrival_utc="2026-09-10T06:00:00Z",
        forecast_high_c=27,
        forecast_low_c=24,
    )
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.create_segment(animal["id"], leg["id"], sequence_index=1)
    permit = workbench.submit_document(animal["id"], document_type="IMPORT_PERMIT")
    workbench.start_document_review(permit["id"])
    vacuously_verified = workbench.verify_compliance(reservation["id"])

    workbench.create_destination_requirement(
        catalog["species_id"],
        destination_country_code="SG",
        document_type="IMPORT_PERMIT",
        max_age_days_at_arrival=60,
        mandatory=True,
    )

    refused = api.verify_reservation_compliance(
        reservation["id"], workbench.reviewer()
    )
    validate_error(refused, ApiErrorId.REQUIRED_DOCUMENT_MISSING, 422)

    unchanged = workbench.read_reservation(reservation["id"])
    assert_reservation_state(
        unchanged, booking_status="PENDING", compliance_status="VERIFIED"
    )
    assert unchanged["version"] == vacuously_verified["version"]
    assert workbench.read_document(permit["id"])["status"] == "UNDER_REVIEW"


def test_animal_state_outranks_missing_required_document_rejected(
    api, workbench, catalog
):
    """Promotion from `DRAFT` is refused on the state rung, above the paperwork rung
    that the same animal would also fail.

    PRD §3.4: "Any screen, promote, deny or downstream operation attempted from a
    status that does not permit it is refused with `ERR_ANIMAL_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/animal_state_outranks_missing_required_document_rejected
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )

    refused = api.mark_animal_record_travel_ready(animal["id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.ANIMAL_INVALID_STATE, 409)

    assert_animal_state(
        workbench.read_animal(animal["id"]),
        status="DRAFT",
        container_compliance_state="UNEVALUATED",
    )
    assert_reservation_state(
        workbench.read_reservation(reservation["id"]),
        booking_status="PENDING",
        compliance_status="UNVERIFIED",
    )


def test_missing_required_document_answers_once_the_animal_state_gate_passes(
    api, workbench, catalog, primary_leg
):
    """Screening the animal satisfies the state rung, which lets the paperwork rung
    answer for the very same promotion attempt.

    PRD §2.6: "Every mandatory destination requirement is backed by a `VERIFIED`
    document — otherwise `ERR_REQUIRED_DOCUMENT_MISSING` (422). Applies to two
    operations: `POST /animal-records/{id}/mark-travel-ready` and
    `POST /reservations/{id}/verify-compliance`."

    Design: Difficulty/priority_pair_validation_conflict/animal_state_outranks_missing_required_document_rejected
    """
    leg = primary_leg()
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.create_segment(animal["id"], leg["id"], sequence_index=1)
    workbench.screen_animal(animal["id"])

    refused = api.mark_animal_record_travel_ready(animal["id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.REQUIRED_DOCUMENT_MISSING, 422)

    assert_animal_state(
        workbench.read_animal(animal["id"]),
        status="SCREENED",
        container_compliance_state="COMPLIANT",
    )
