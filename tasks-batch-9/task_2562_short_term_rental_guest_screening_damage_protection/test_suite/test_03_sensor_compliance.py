"""Monitoring-device disclosure: privacy floors, notice copy and review edges."""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    types,
    validate_error,
    validate_success,
)
from test_helpers.test_users import COMPLIANCE_OFFICER


def test_a_camera_in_a_bedroom_is_refused_even_where_indoor_cameras_are_allowed(api):
    """The bedroom and bathroom floor is absolute, not jurisdictional.

    The bound rule set permits indoor cameras, so the only thing standing between
    this registration and success is the placement zone. Nothing may be stored: the
    listing's sensor posture must still read the vacuous COMPLIANT it had before.

    PRD: "A device whose `device_type` is `INDOOR_CAMERA` or `OUTDOOR_CAMERA` may never be placed in a `BEDROOM` or a `BATHROOM` zone."
    PRD: "No jurisdiction flag unlocks this; the registration is refused with `ERR_SENSOR_PLACEMENT_PROHIBITED`."
    PRD: "Otherwise the posture is `COMPLIANT`, and that includes the vacuous case of a listing with no devices at all: an unmonitored listing is deliberately bookable."

    Design: Corner/validations/sensor_camera_in_bedroom_rejected
    """
    cast = fixtures.setup_waiver_listing(api)
    assert cast.jurisdiction_rule["indoor_camera_allowed"] is True, (
        "the scenario needs a jurisdiction that permits indoor cameras, so the "
        "refusal can only come from the placement floor"
    )
    before = fixtures.read_property(api, cast)

    validate_error(
        api.create_monitoring_device(
            cast.host_headers,
            **factories.monitoring_device_payload(
                cast.property_id,
                device_type="INDOOR_CAMERA",
                placement_zone="BEDROOM",
                guest_disclosure_text="A camera monitors the primary bedroom.",
            )
        ),
        ApiErrorId.ERR_SENSOR_PLACEMENT_PROHIBITED,
        expected_status=422,
    )

    assertions.assert_page(
        api.list_monitoring_devices(cast.host_headers, property_id=cast.property_id),
        total_count=0,
    )
    after = fixtures.read_property(api, cast)
    assertions.assert_fields(
        after,
        "property",
        sensor_compliance_state="COMPLIANT",
        listing_state="ACTIVE",
    )
    assertions.assert_version_unchanged(before, after, "property")


def test_disclosure_copy_is_demanded_only_where_the_jurisdiction_asks_for_it(api):
    """A plain decibel meter needs notice copy in one city and not in the other.

    Two listings of the same host are bound to different rule sets. The device body
    is identical in both cases — a noise sensor, outside, recording no audio, with
    no disclosure text at all — so the only input that moves is the jurisdiction's
    notice flag.

    PRD: "`guest_disclosure_text` must be present and non-empty whenever any one of three conditions holds: the jurisdiction has `sensor_notice_required` true, or the `device_type` is `INDOOR_CAMERA` or `OUTDOOR_CAMERA`, or `records_audio` is true."
    PRD: "A jurisdiction that requires notice therefore demands disclosure copy even for a plain `NOISE_DECIBEL` sensor."
    PRD: "A missing or empty disclosure in any of those cases is refused with `ERR_DISCLOSURE_TEXT_REQUIRED`."

    Design: Corner/validations/disclosure_text_required_only_when_jurisdiction_requires_notice
    """
    cast = fixtures.setup_waiver_listing(
        api,
        rule_overrides={
            "jurisdiction_code": "US-TX-AUS",
            "min_stay_nights": 1,
            "max_occupancy_cap": 10,
            "indoor_camera_allowed": True,
            "indoor_audio_allowed": True,
            "sensor_notice_required": False,
            "noise_threshold_db": 80,
        },
    )
    notice_rule = fixtures.create_jurisdiction_rule(api, jurisdiction_code="US-CA-SFO")
    noticed_listing = validate_success(
        api.create_property(
            cast.host_headers,
            **factories.waiver_property_payload(
                cast.host_id,
                notice_rule["id"],
                address_line="27 Notice Lane",
                city="San Francisco",
            )
        ),
        expected_status=201,
    )

    quiet_payload = factories.monitoring_device_payload(cast.property_id)
    quiet_payload.pop("guest_disclosure_text")
    permitted = validate_success(
        api.create_monitoring_device(cast.host_headers, **quiet_payload),
        expected_status=201,
    )
    assertions.assert_fields(
        permitted,
        "monitoring_device",
        device_type="NOISE_DECIBEL",
        placement_zone="EXTERIOR",
        records_audio=False,
        disclosure_state="DRAFT",
    )

    noticed_payload = factories.monitoring_device_payload(noticed_listing["id"])
    noticed_payload.pop("guest_disclosure_text")
    validate_error(
        api.create_monitoring_device(cast.host_headers, **noticed_payload),
        ApiErrorId.ERR_DISCLOSURE_TEXT_REQUIRED,
        expected_status=422,
    )
    assertions.assert_page(
        api.list_monitoring_devices(
            cast.host_headers, property_id=noticed_listing["id"]
        ),
        total_count=0,
    )


def test_a_new_device_lands_in_draft_and_pends_the_listing_without_suspending_it(api):
    """Registration parks the device in DRAFT and re-derives the listing posture.

    The listing must move from COMPLIANT to PENDING_REVIEW and bump its version,
    while staying ACTIVE with no suspension reason: only a rejected disclosure
    takes a listing down.

    PRD: "A newly registered device starts in `DRAFT` with `reject_reason_code` and `reviewed_by_user_id` both null and its own `version` at 1."
    PRD: "Registration immediately re-derives the listing's `sensor_compliance_state` to `PENDING_REVIEW` and increases the listing's `version` by 1."
    PRD: "Note carefully what this does and does not do: `PENDING_REVIEW` blocks new confirmations on the listing, but it never suspends an `ACTIVE` listing."

    Design: Corner/state_machines/monitoring_device_initial_disclosure_state_is_draft
    """
    cast = fixtures.setup_waiver_listing(api)
    before = fixtures.read_property(api, cast)
    assertions.assert_fields(before, "property", sensor_compliance_state="COMPLIANT")

    device = validate_success(
        api.create_monitoring_device(
            cast.host_headers,
            **factories.monitoring_device_payload(
                cast.property_id,
                device_type="OCCUPANCY_COUNTER",
                placement_zone="COMMON_INTERIOR",
                guest_disclosure_text="An occupancy counter in the living room tallies "
                                      "how many people are present and records nothing "
                                      "else.",
            )
        ),
        expected_status=201,
    )

    types.assert_is_monitoring_device(device)
    assertions.assert_fields(
        device,
        "monitoring_device",
        property_id=cast.property_id,
        device_type="OCCUPANCY_COUNTER",
        placement_zone="COMMON_INTERIOR",
        records_audio=False,
        disclosure_state="DRAFT",
        reject_reason_code=None,
        reviewed_by_user_id=None,
        version=1,
    )

    after = fixtures.read_property(api, cast)
    assertions.assert_fields(
        after,
        "property",
        sensor_compliance_state="PENDING_REVIEW",
        listing_state="ACTIVE",
        suspension_reason=None,
    )
    assertions.assert_version_advanced_by(before, after, 1, "property")


def test_submitting_the_same_device_for_review_twice_is_an_invalid_transition(api):
    """The submit edge leaves DRAFT or REJECTED, and PENDING_REVIEW is neither.

    The first submission is the legitimate DRAFT edge; the second finds the device
    already awaiting a reviewer and must be refused without touching the row.

    PRD: "From `DRAFT` it advances `disclosure_state` to `PENDING_REVIEW`; from `REJECTED` — after the host has remediated whatever the reviewer objected to — it returns `disclosure_state` to `PENDING_REVIEW` and clears `reject_reason_code` back to null."
    PRD: "The resource sits in a non-terminal state from which the requested transition exists — `ERR_INVALID_STATE`."

    Design: Corner/state_machines/device_submit_for_review_twice_returns_invalid_state
    """
    cast = fixtures.setup_waiver_listing(api)
    device = fixtures.register_device(api, cast, approve=False)

    submitted = validate_success(
        api.submit_device_for_review(device["id"], cast.host_headers)
    )
    assertions.assert_fields(
        submitted, "monitoring_device", disclosure_state="PENDING_REVIEW"
    )
    assertions.assert_version_advanced_by(device, submitted, 1, "monitoring_device")

    validate_error(
        api.submit_device_for_review(device["id"], cast.host_headers),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )

    unchanged = validate_success(
        api.get_monitoring_device(device["id"], cast.host_headers)
    )
    assertions.assert_fields(
        unchanged,
        "monitoring_device",
        disclosure_state="PENDING_REVIEW",
        reviewed_by_user_id=None,
    )
    assertions.assert_version_unchanged(submitted, unchanged, "monitoring_device")


def test_confirm_is_blocked_by_a_sibling_device_the_reservation_never_names(api):
    """An unreviewed sensor on the listing stops a faultless stay from confirming.

    The reservation is created while the listing has no devices at all, so it
    passes screening and holds nothing against it. A device registered afterwards
    pulls the listing's sensor posture down, and the very same confirm request now
    fails — then succeeds again, byte for byte, once the officer approves the
    disclosure. No field of the reservation differs between the two attempts.

    PRD: "The listing's `sensor_compliance_state` must read `COMPLIANT`. A listing with any device sitting in `DRAFT`, `PENDING_REVIEW` or `REJECTED` is refused with `ERR_SENSOR_COMPLIANCE_BLOCKED` — this is the rule that makes an unreviewed sensor disclosure commercially expensive without taking the listing down."
    PRD: "A successful approval sets `reviewed_by_user_id` to the officer's `X-User-ID`, moves `disclosure_state` to `APPROVED`, re-derives the listing's `sensor_compliance_state` — which becomes `COMPLIANT` once every sibling device of the listing is `APPROVED` — and increases the listing's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_gated_by_property_device_disclosure_state
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Tomas Iversen", guest_email="tomas@guest.test"
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", sensor_compliance_state="COMPLIANT"
    )
    reservation = fixtures.book_stay(api, cast)
    assertions.assert_fields(
        reservation, "reservation", stay_state="REQUESTED", screening_state="CLEARED"
    )

    device = fixtures.register_device(api, cast, approve=False)
    assertions.assert_fields(device, "monitoring_device", disclosure_state="DRAFT")

    validate_error(
        api.confirm_reservation(reservation["id"], cast.host_headers),
        ApiErrorId.ERR_SENSOR_COMPLIANCE_BLOCKED,
        expected_status=409,
    )
    held = validate_success(api.get_reservation(reservation["id"], cast.host_headers))
    assertions.assert_fields(
        held, "reservation", stay_state="REQUESTED", screening_state="CLEARED"
    )

    validate_success(api.submit_device_for_review(device["id"], cast.host_headers))
    approved = validate_success(
        api.review_monitoring_device(
            device["id"], COMPLIANCE_OFFICER, decision="APPROVE"
        )
    )
    assertions.assert_fields(
        approved,
        "monitoring_device",
        disclosure_state="APPROVED",
        reviewed_by_user_id="co-1",
        reject_reason_code=None,
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", sensor_compliance_state="COMPLIANT"
    )

    confirmed = validate_success(
        api.confirm_reservation(reservation["id"], cast.host_headers)
    )
    assertions.assert_fields(
        confirmed, "reservation", stay_state="CONFIRMED", deposit_state="NONE"
    )


def test_pending_review_blocks_confirmation_without_ever_suspending_the_listing(api):
    """Both unreviewed disclosure states gate the confirm, and neither suspends.

    The device is walked DRAFT then PENDING_REVIEW, and the confirm is attempted at
    each stop: the gate is the listing's posture, not one particular device state.
    Throughout, the listing stays ACTIVE with a null suspension reason, so the
    commercial cost falls on new confirmations alone.

    PRD: "The listing's `sensor_compliance_state` must read `COMPLIANT`. A listing with any device sitting in `DRAFT`, `PENDING_REVIEW` or `REJECTED` is refused with `ERR_SENSOR_COMPLIANCE_BLOCKED` — this is the rule that makes an unreviewed sensor disclosure commercially expensive without taking the listing down."
    PRD: "Otherwise, if any device sits in `DRAFT` or `PENDING_REVIEW`, the posture is `PENDING_REVIEW`."
    PRD: "Note carefully what this does and does not do: `PENDING_REVIEW` blocks new confirmations on the listing, but it never suspends an `ACTIVE` listing."

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_gated_by_property_device_disclosure_state
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Tomas Iversen", guest_email="tomas@guest.test"
    )
    reservation = fixtures.book_stay(api, cast)
    device = fixtures.register_device(api, cast, approve=False)

    validate_error(
        api.confirm_reservation(reservation["id"], cast.host_headers),
        ApiErrorId.ERR_SENSOR_COMPLIANCE_BLOCKED,
        expected_status=409,
    )
    drafted_listing = fixtures.read_property(api, cast)
    assertions.assert_fields(
        drafted_listing,
        "property",
        sensor_compliance_state="PENDING_REVIEW",
        listing_state="ACTIVE",
        suspension_reason=None,
    )

    validate_success(api.submit_device_for_review(device["id"], cast.host_headers))
    validate_error(
        api.confirm_reservation(reservation["id"], cast.host_headers),
        ApiErrorId.ERR_SENSOR_COMPLIANCE_BLOCKED,
        expected_status=409,
    )
    submitted_listing = fixtures.read_property(api, cast)
    assertions.assert_fields(
        submitted_listing,
        "property",
        sensor_compliance_state="PENDING_REVIEW",
        listing_state="ACTIVE",
        suspension_reason=None,
    )

    still_requested = validate_success(
        api.get_reservation(reservation["id"], cast.host_headers)
    )
    assertions.assert_fields(still_requested, "reservation", stay_state="REQUESTED")
    assertions.assert_version_unchanged(reservation, still_requested, "reservation")

    validate_success(
        api.review_monitoring_device(
            device["id"], COMPLIANCE_OFFICER, decision="APPROVE"
        )
    )
    confirmed = validate_success(
        api.confirm_reservation(reservation["id"], cast.host_headers)
    )
    assertions.assert_fields(confirmed, "reservation", stay_state="CONFIRMED")
